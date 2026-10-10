"""The scout's research: one Claude call with Anthropic's web search, then checks that keep only what a source shows.

Claude (claude-opus-5, SCOUT_MODEL overrides) searches with the server-side
web_search tool (it runs on Anthropic's side; up to SEARCH_TOOL["max_uses"]
searches a run) and ends its answer with a fenced JSON block of events. That
block is parsed defensively; only if it cannot be read does a second call,
with no tools and a json_schema format, structure the research text.

Never invent (vet()):
  * every URL the searches returned, or that a citation points at, is "seen";
    an event keeps only source URLs that were seen, and with none it is dropped
  * a website whose host was never seen is blanked
  * an organizer email is kept only when it was read on the event's own site:
    a seen page on the website's host, or a citation from that site that
    quotes the address; otherwise it is blanked
  * dates that are not real YYYY-MM-DD days are blanked; an event that starts
    before today or after the horizon is dropped

Money: no call once ai.spend.cap_reached; tokens are recorded through
ai.spend.record at the model that answered, and each web search (USD 10 per
1,000 searches, Anthropic price list) as its own api_usage row, so the cap sees it.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from ..ai import spend
from ..ai.claude import FALLBACK_BETA
from ..core import config, db
from . import keys

DEFAULT_MODEL = "claude-opus-5"
SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 8}
WEB_SEARCH_USD = 0.01            # USD 10 per 1,000 searches
MAX_CONTINUATIONS = 3            # pause_turn resumes before giving up on a run
MAX_EVENTS = 25
KINDS = ("fan", "business", "other")
LIMITS = {"name": 200, "city": 120, "venue": 200, "organizer": 160, "website": 500}

SYSTEM = """You find upcoming conventions and conferences that a convention and event photographer could pitch to photograph. You search the web and report only what the sources you found say.
Rules:
1. Only events in the region you are given, starting between the two dates you are given. Fan conventions (comic, anime, gaming, cosplay), business, trade and political conferences, and galas and award dinners all count.
2. Never invent anything. A field you did not find in a source is an empty string. A date you are not sure of is empty. Dates are YYYY-MM-DD.
3. Every event lists in sources the URLs of the pages you found it on. Leave out any event you have no source URL for.
4. organizer_email: only a public contact address printed on the event's own website (organizers, press, media or general contact), with the page it is printed on in email_source_url. Never guess an address, never build one from a name or a pattern, never take one from a third party listing. If there is none, leave both empty.
5. kind is fan, business or other. website is the event's own site, never a ticket seller or a listing.
6. Skip events in the already known list.
When you are done, end your answer with one fenced json block: {"events": [...]}, each event an object with exactly these keys: name, kind, start_date, end_date, city, venue, website, organizer, organizer_email, email_source_url, sources (a list of URLs)."""

STRUCTURE_SYSTEM = """You turn research notes about upcoming events into JSON. Use only what the notes state. A field the notes do not give is an empty string; never fill one in. Keep every source URL exactly as written in the notes. Leave out any event the notes give no source URL for."""

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
        "start_date": {"type": "string"}, "end_date": {"type": "string"},
        "city": {"type": "string"}, "venue": {"type": "string"}, "website": {"type": "string"},
        "organizer": {"type": "string"}, "organizer_email": {"type": "string"}, "email_source_url": {"type": "string"},
        "sources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name", "kind", "start_date", "end_date", "city", "venue", "website", "organizer",
                 "organizer_email", "email_source_url", "sources"],
    "additionalProperties": False,
}
EVENTS_SCHEMA = {"type": "object", "properties": {"events": {"type": "array", "items": EVENT_SCHEMA}},
                 "required": ["events"], "additionalProperties": False}

FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class Research:
    candidates: list = field(default_factory=list)
    seen: set = field(default_factory=set)                 # canonical URLs the searches returned or citations named
    citations: list = field(default_factory=list)          # (canonical url, cited text)
    text: str = ""
    model: str = ""
    calls: int = 0
    searches: int = 0
    search_errors: list = field(default_factory=list)
    refused: bool = False
    structured: bool = False
    stopped: str = ""                                      # why research stopped early, if it did


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def canonical(url) -> str:
    """Lowercase scheme and host, no 'www.', no fragment, no trailing slash: how seen and claimed URLs are compared."""
    text = str(url or "").strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return ""
    host = parts.hostname.lower()
    host = host[4:] if host.startswith("www.") else host
    path = parts.path.rstrip("/")
    return urlunsplit(("https", host, path, parts.query, ""))


def host_of(url) -> str:
    c = canonical(url)
    return (urlsplit(c).hostname or "") if c else ""


def same_site(host: str, site: str) -> bool:
    return bool(host and site) and (host == site or host.endswith("." + site))


def collect(res: Research, response) -> None:
    """Seen URLs and citations from one response; a web_search_tool_result's content is a list on success, an object on error."""
    for block in _get(response, "content", None) or []:
        kind = _get(block, "type", "")
        if kind == "web_search_tool_result":
            content = _get(block, "content", None)
            if isinstance(content, (list, tuple)):
                for item in content:
                    c = canonical(_get(item, "url", ""))
                    if c:
                        res.seen.add(c)
            else:
                res.search_errors.append(str(_get(content, "error_code", "unknown error")))
        elif kind == "text":
            res.text += (_get(block, "text", "") or "") + "\n"
            for cite in _get(block, "citations", None) or []:
                c = canonical(_get(cite, "url", ""))
                if c:
                    res.seen.add(c)
                    res.citations.append((c, str(_get(cite, "cited_text", "") or "")))


def record_usage(conn: sqlite3.Connection, agent: str, response, model: str, detail: str) -> tuple[str, int]:
    """Tokens through ai.spend at the model that answered; web searches as their own priced row. -> (model, searches)"""
    usage = _get(response, "usage", None)
    answered = _get(response, "model", None) or model
    spend.record(conn, agent, answered, int(_get(usage, "input_tokens", 0) or 0), int(_get(usage, "output_tokens", 0) or 0), detail)
    server = _get(usage, "server_tool_use", None)
    n = int(_get(server, "web_search_requests", 0) or 0) if server is not None else 0
    if n:
        db.insert(conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent=agent, units=n, unit_kind="web_searches",
                  cost_usd=round(n * WEB_SEARCH_USD, 6), detail=f"{answered} web_search x{n} {detail}")
    return answered, n


def parse_events(text: str) -> Optional[list]:
    """The events from the last fenced JSON block (or the outermost braces); None when nothing readable is there."""
    chunks = [m.group(1) for m in FENCED.finditer(text or "")][::-1]
    start, end = (text or "").find("{"), (text or "").rfind("}")
    if start != -1 and end > start:
        chunks.append(text[start:end + 1])
    for chunk in chunks:
        try:
            data = json.loads(chunk.strip())
        except ValueError:
            continue
        events = data.get("events") if isinstance(data, dict) else data
        if isinstance(events, list):
            return [e for e in events if isinstance(e, dict)]
    return None


def prompt(region: str, today: date, horizon: date, known: list[str]) -> str:
    known_line = "; ".join(known[:60]) or "none"
    return "\n".join([
        f"Region: {region}",
        f"Today: {today.isoformat()}",
        f"Find events starting between {today.isoformat()} and {horizon.isoformat()}.",
        f"Already known (skip these): {known_line}",
        f"Up to {MAX_EVENTS} events, the event's own website first.",
    ])


def _create(client, model: str, **kw):
    return client.beta.messages.create(model=model, max_tokens=16000, betas=[FALLBACK_BETA], fallbacks="default",
                                       thinking={"type": "adaptive"}, **kw)


def research(conn: sqlite3.Connection, client, *, region: str, today: date, horizon: date, known: list[str],
             agent: str = "scout") -> Research:
    """The research call (with pause_turn resumes), then a structuring call only if the answer cannot be parsed."""
    model = config.getenv("SCOUT_MODEL") or DEFAULT_MODEL
    effort = config.getenv("SCOUT_EFFORT") or "medium"
    res = Research(model=model)
    ask = prompt(region, today, horizon, known)
    system = [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}]
    messages: list = [{"role": "user", "content": ask}]
    turn: list = []
    for _ in range(1 + MAX_CONTINUATIONS):
        if spend.cap_reached(conn):
            res.stopped = "the monthly AI cap was reached during research"
            break
        response = _create(client, model, output_config={"effort": effort}, system=system,
                           tools=[dict(SEARCH_TOOL)], messages=messages)
        res.calls += 1
        res.model, n = record_usage(conn, agent, response, model, "scout research")
        res.searches += n
        collect(res, response)
        stop = _get(response, "stop_reason", "")
        if stop == "refusal":
            res.refused = True
            return res
        if stop != "pause_turn":
            break
        turn.extend(_get(response, "content", None) or [])          # the same assistant turn, resumed where it paused
        messages = [{"role": "user", "content": ask}, {"role": "assistant", "content": list(turn)}]
    else:
        res.stopped = f"research still paused after {MAX_CONTINUATIONS} resumes"
    events = parse_events(res.text)
    if events is None and res.text.strip() and not spend.cap_reached(conn):
        response = _create(client, model,
                           output_config={"effort": "low", "format": {"type": "json_schema", "schema": EVENTS_SCHEMA}},
                           system=[{"type": "text", "text": STRUCTURE_SYSTEM}],
                           messages=[{"role": "user", "content": "Research notes:\n\n" + res.text}])
        res.calls += 1
        record_usage(conn, agent, response, model, "scout structuring")
        res.structured = True
        if _get(response, "stop_reason", "") == "refusal":
            res.refused = True
            return res
        text = next((_get(b, "text", "") for b in _get(response, "content", None) or [] if _get(b, "type", "") == "text"), "")
        events = parse_events(text)
    res.candidates = events or []
    return res


def own_site_email(res: Research, cand: dict, site: str) -> tuple[str, str]:
    """(address, page) only when the address was read on the event's own site; else ('', '')."""
    email = keys.normalize_email(str(cand.get("organizer_email") or ""))
    if not site or not keys.valid_email(email):
        return "", ""
    page = str(cand.get("email_source_url") or "").strip()
    if canonical(page) in res.seen and same_site(host_of(page), site):
        return email, page
    for url, quoted in res.citations:
        if same_site(urlsplit(url).hostname or "", site) and email in quoted.lower():
            return email, url
    return "", ""


def _clip(value, key: str) -> str:
    return str(value or "").strip()[:LIMITS.get(key, 200)]


def vet(res: Research, *, today: date, horizon: date) -> tuple[list[dict], dict[str, int]]:
    """Keep what a seen source backs; blank what it does not; drop what cannot stand. Returns (kept, dropped counts)."""
    kept: list[dict] = []
    dropped = {"no_name": 0, "no_source": 0, "past": 0, "beyond_horizon": 0}
    seen_hosts = {urlsplit(u).hostname for u in res.seen}
    for cand in res.candidates:
        name = _clip(cand.get("name"), "name")
        if not name:
            dropped["no_name"] += 1
            continue
        raw_sources = cand.get("sources") if isinstance(cand.get("sources"), list) else []
        sources = []
        for u in raw_sources:
            c = canonical(u)
            if c and c in res.seen and str(u).strip() not in sources:
                sources.append(str(u).strip())
        if not sources:
            dropped["no_source"] += 1
            continue
        start, end = keys.iso_day(cand.get("start_date")), keys.iso_day(cand.get("end_date"))
        if start and end and end < start:
            end = None
        if (start and start < today.isoformat()) or (not start and end and end < today.isoformat()):
            dropped["past"] += 1
            continue
        if start and start > horizon.isoformat():
            dropped["beyond_horizon"] += 1
            continue
        website = _clip(cand.get("website"), "website")
        site = host_of(website)
        if not site or site not in seen_hosts:
            website, site = "", ""
        email, email_url = own_site_email(res, cand, site)
        kind = str(cand.get("kind") or "").strip().lower()
        kept.append({"name": name, "kind": kind if kind in KINDS else "other", "start_date": start, "end_date": end,
                     "city": _clip(cand.get("city"), "city"), "venue": _clip(cand.get("venue"), "venue"),
                     "website": website, "organizer": _clip(cand.get("organizer"), "organizer"),
                     "organizer_email": email, "email_source_url": email_url, "sources": sources[:5]})
    return kept, dropped
