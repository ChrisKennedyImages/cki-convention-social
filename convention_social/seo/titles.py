"""Part one of the SEO loop (Chris, 2026-11-01: "shouldn't we have it do it all. Why wouldn't we?"): the pages whose
title and description lose the click, rewritten from what people searched, each proposed to him through seo/changes.py.

Which pages, from the newest Search Console window kept (seo/search_console.py): a public page of the site shown at
least MIN_SHOWINGS times, at an average place on Google's first page, whose click rate is below half of what a result at
that place usually gets (EXPECTED_CTR). Past the first page almost nobody clicks whatever the words say; that is part
two's ground (near misses), not this. The most clicks missing first, at most PER_WEEK pages a week.

For each, Claude (MODEL, under the monthly cap through ai/spend: reserve before, record after) writes a new title and
description from the page's own words and its real top searches, in the brand's voice. Every draft is checked before it
is proposed: the copy rules (no price, no dash, no claim, no hype), the names rule (no event, company or person), the
lengths a search result shows whole (site/build.words_problems). A draft that fails is dropped with the reason in the
run's summary, never proposed. The weekly run calls this only live: a dry run reads nothing, pays nothing, proposes
nothing.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from .. import offer
from ..ai import names as ai_names
from ..ai import spend
from ..ai.claude import FALLBACK_BETA, tidy
from ..core import config, runner, secrets
from ..site import build
from . import changes, search_console

KIND = "title"
MODEL = "claude-opus-5"
MIN_SHOWINGS = 100           # a page shown fewer times in the window says too little to judge its words
WEAK = 0.5                   # below half the click rate its place usually gets
PER_WEEK = 2                 # pages drafted a week, at most
SEARCHES = 10                # the page's top searches Claude is shown
# How often a Google result is clicked at each average place on the first page. General industry figures, rounded from
# published click-through studies of Google results across the web: what a result at that place usually gets, not this
# site's own numbers.
EXPECTED_CTR = {1: 0.276, 2: 0.158, 3: 0.110, 4: 0.084, 5: 0.063, 6: 0.049, 7: 0.039, 8: 0.033, 9: 0.027, 10: 0.024}
LAST_PLACE = max(EXPECTED_CTR)

SYSTEM = """You rewrite the words one page of eventcaliber.com shows in Google's results: its title and its description.
Event Caliber is Chris and Nic Kennedy, two brothers who photograph conventions, conferences, galas and award dinners. They are based in Washington, DC and travel nationwide.
The page is shown in Google often, but few people click it. Write a title and a description that match what the people searching typed, using the words of the searches given, so this result is plainly the one they want.
Rules:
1. Plain, short words in sentence case. No hype, no exclamation marks, no superlatives such as best, top or number one, nothing guaranteed or award winning.
2. Never a dash of any kind. Use commas and periods.
3. Never a price, a rate or a discount.
4. Never name an event, a conference, a company or a person, even when a search does. Say what kind of event it is.
5. Never say what a service includes or comes with, what anyone leaves with, how fast anything arrives, packages or turnaround. Never claim to be any event's official photographer or anyone's partner.
6. Say only what the page itself says. Invent nothing.
7. The title is at most title_max_characters long; the site adds title_suffix after it. The description is at most description_max_characters long, one or two sentences.
Return JSON."""
SCHEMA = {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string"}},
          "required": ["title", "description"], "additionalProperties": False}


class CapReached(RuntimeError):
    """The monthly AI cap would be passed by one more call."""


def expected_ctr(position: float) -> Optional[float]:
    """What a result at this average place usually gets, read between the table's places; None past the first page
    (and for a place Google did not give)."""
    if position <= 0 or position > LAST_PLACE:
        return None
    low = max(1, int(position))
    high = min(low + 1, LAST_PLACE)
    return EXPECTED_CTR[low] + (EXPECTED_CTR[high] - EXPECTED_CTR[low]) * max(0.0, position - low)


def weak_pages(conn: sqlite3.Connection, win: tuple[str, str], cfg=None) -> list[dict]:
    """The site's public pages in a kept window whose words lose the click, the most clicks missing first."""
    paths = {search_console.page_url(p, cfg): p for p in offer.public_pages()}
    out = []
    for r in search_console.page_totals(conn, win):
        path, usual = paths.get(r["page"]), expected_ctr(r["position"])
        if path is None or usual is None or r["impressions"] < MIN_SHOWINGS:
            continue
        if r["clicks"] < WEAK * usual * r["impressions"]:
            out.append({**r, "path": path, "usual": usual, "missing": r["impressions"] * usual - r["clicks"]})
    return sorted(out, key=lambda r: (-r["missing"], r["path"]))


def reason(r: dict) -> str:
    return (f"Shown {r['impressions']} times in Google search from {changes.span(r['start'], r['end'])}, at an average place of "
            f"{r['position']:g}, and clicked {r['clicks']} time{'' if r['clicks'] == 1 else 's'} ({r['ctr']:.1%}). Results at "
            f"that place usually get about {r['usual']:.1%}, so its title and description are likely losing the click.")


def page_text(path: str) -> str:
    """What a coverage page says beyond its title and description, for Claude to keep to; other pages have only those."""
    for c in offer.load()["coverage"]:
        if offer.coverage_page(c["key"]) == path:
            return f"{c['label']}. {c['about']}"
    return ""


def ask(conn: sqlite3.Connection, client, facts: dict, *, agent: str) -> Optional[dict]:
    """Claude's title and description for one page (raw), or None when it refused or answered nothing readable.
    Raises CapReached before a call that would pass the cap; any failure of the call itself is raised after the
    reservation is released."""
    held = spend.reserve(conn, agent, MODEL)
    if held is None:
        raise CapReached("the monthly AI cap is reached")
    try:
        response = client.beta.messages.create(
            model=MODEL, max_tokens=3000, betas=[FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM, messages=[{"role": "user", "content": json.dumps(facts, indent=1)}])
    except Exception:
        spend.release(conn, held)
        raise
    u = response.usage
    spend.record(conn, agent, getattr(response, "model", None) or MODEL, int(u.input_tokens or 0), int(u.output_tokens or 0),
                 f"seo title {facts['page']}", reservation=held)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _clean(value) -> str:
    return " ".join(tidy(value).split()) if isinstance(value, str) else ""


def draft(conn: sqlite3.Connection, client, r: dict, win: tuple[str, str], *, agent: str = "seo", cfg=None) -> str:
    """One weak page: Claude's words, checked, proposed and pinged; or dropped with the reason. What happened, in words."""
    cfg = cfg or config.get_config()
    brand, path = cfg.brand_name, r["path"]
    rel = build.rel_of(path)
    title, description = build.site_words(conn)[rel]
    searches = search_console.searches(conn, win, r["page"], SEARCHES)
    suffix = build.full_title(rel, "", brand)
    facts = {"page": path, "title_now": title, "description_now": description,
             "title_max_characters": build.TITLE_MAX - len(suffix), "title_suffix": suffix,
             "description_max_characters": build.DESCRIPTION_MAX, "page_text": page_text(path),
             "searches": [{"search": q["query"], "shown": q["impressions"], "clicked": q["clicks"], "average_place": q["position"]}
                          for q in searches],
             "numbers": {"shown": r["impressions"], "clicked": r["clicks"], "average_place": r["position"],
                         "usual_click_rate_at_that_place": round(r["usual"], 3)}}
    raw = ask(conn, client, facts, agent=agent)
    if raw is None:
        return f"{path}: dropped, Claude refused or gave nothing readable"
    new_title, new_description = _clean(raw.get("title")), _clean(raw.get("description"))
    why = build.words_problems(rel, new_title, new_description, brand, ai_names.public_names(conn))
    if not why and (new_title, new_description) == (title, description):
        why = ["Claude kept the words the page has"]
    if why:
        return f"{path}: dropped, {'; '.join(why)}"
    cid = changes.propose(conn, kind=KIND, page=path, before={"title": title, "description": description},
                          after={"title": new_title, "description": new_description}, queries=searches,
                          reason=reason(r))
    pushed = changes.ping(conn, cid, dry_run=False, agent=agent)
    return f"{path}: proposed (change {cid}), ping {pushed}"


def propose_week(conn: sqlite3.Connection, cfg=None, *, client=None, agent: str = "seo") -> str:
    """The weekly finding, live only: the weak pages in the newest kept window, at most PER_WEEK drafted. What happened."""
    cfg = cfg or config.get_config()
    win = search_console.latest_window(conn)
    if win is None:
        return "no Search Console numbers kept yet"
    weak = weak_pages(conn, win, cfg)
    if not weak:
        return f"no page lost its clicks to its words from {changes.span(*win)}"
    said, tried = [], 0
    for r in weak:
        if tried >= PER_WEEK:
            break
        why = changes.resting(conn, r["path"])
        if why:
            said.append(f"{r['path']}: left alone, {why}")
            continue
        if client is None:
            if not secrets.get_secret("ANTHROPIC_API_KEY"):
                said.append("no Anthropic key, so nothing drafted")
                break
            import anthropic  # here, so a week with nothing to draft needs neither key nor SDK
            client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
        tried += 1
        try:
            said.append(draft(conn, client, r, win, agent=agent, cfg=cfg))
        except CapReached as e:
            said.append(f"{e}, so nothing more drafted")
            break
        except Exception as e:  # noqa: BLE001  the API or the network: this page waits a week, said once, never a dead run
            runner.record_error_once(conn, agent, "seo_title", f"New search words for {r['path']} could not be drafted "
                                                               f"({type(e).__name__}: {e}); tried again next week.")
            said.append(f"{r['path']}: Claude could not be asked ({type(e).__name__})")
    return "; ".join(said)


# ------------------------------------------------------------------ the kind, for seo/changes.py

def problems(conn: sqlite3.Connection, row) -> list[str]:
    """Why this change may not go on the site now: its words against today's rules and lengths, and the page still saying
    what it replaces."""
    brand = config.get_config().brand_name
    rel = build.rel_of(row["page"])
    before, after = json.loads(row["before"]), json.loads(row["after"])
    now = build.site_words(conn).get(rel)
    if now is None:
        return [f"the site no longer has the page {row['page']}"]
    why = build.words_problems(rel, after.get("title", ""), after.get("description", ""), brand, ai_names.public_names(conn))
    if (before.get("title"), before.get("description")) != now:
        why.insert(0, "the page's words changed since this was drafted")
    return why


def shown(row) -> list[tuple[str, str, str]]:
    """(what, before, after) as Chris reads them: the title as a search result shows it, and the description."""
    brand = config.get_config().brand_name
    rel = build.rel_of(row["page"])
    before, after = json.loads(row["before"]), json.loads(row["after"])
    return [("Title", build.full_title(rel, before["title"], brand), build.full_title(rel, after["title"], brand)),
            ("Description", before["description"], after["description"])]
