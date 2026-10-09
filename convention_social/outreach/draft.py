"""Drafting the note to an event organizer, in Chris's voice. Chris edits and approves; nothing sends on its own.

The note is short and specific to their event: it names the event, offers
coverage from offer.json, asks whether they have a photographer lined up, and
is signed Chris and the company name. It never names a price, past clients or
an official role (there are none: FOUNDER_DECISIONS.md), and the footer and
opt-out line are added at send time by outreach.compliance, not here.

Claude (claude-opus-5-5, OUTREACH_MODEL overrides) when a key is set and the
monthly cap allows; a plain template otherwise. A Claude draft that fails any
check is thrown away for the template, so what Chris sees always passes.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional

from .. import offer
from ..ai import spend
from ..ai.claude import FALLBACK_BETA, tidy
from ..core import config, secrets
from . import compliance, keys

DEFAULT_MODEL = "claude-opus-5-5"
MAX_WORDS = 160

# what fits each kind of event, as offer.json keys; labels always come from offer.json
COVERAGE_BY_KIND = {
    "fan": ("cosplay", "stage", "portraits", "exhibition_hall", "vendors"),
    "business": ("stage", "breakouts", "headshots", "evening_events", "dinners"),
    "other": ("stage", "portraits", "evening_events", "dinners"),
}

SYSTEM = """You draft a short first email from Chris, a convention and event photographer, to the organizer of one event he would like to photograph. Write in his voice: warm, plain, short sentences, commas and periods, never a dash of any kind, no exclamation marks in a row, no hype.
Rules:
1. Never write a price, a rate, a discount, a package or anything about cost. The next step is a quote.
2. Never claim past clients, past bookings, an official role at any event, a partnership, awards, or that he has photographed, attended or worked this event before. He has no past clients to name. Never use the word official.
3. Offer only coverage from the offer list you are given; pick the few that fit this event. Never promise anything else, and never promise a delivery time.
4. Be specific to their event: name it, and its dates or city when you are given them. Never invent a fact about the event.
5. Ask whether they already have a photographer lined up.
6. Under 140 words. No links, no attachments, no footer and no unsubscribe line: those are added for you.
7. Greet by first name only if the organizer is clearly a person; otherwise open with Hello.
8. Sign off with Chris on one line and the company name on the next.
Return JSON only: a subject and the body. The subject is plain and accurate, about photography for their event, and never starts with Re or Fwd."""

SCHEMA = {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
          "required": ["subject", "body"], "additionalProperties": False}


@dataclass
class OutreachDraft:
    subject: str
    body: str
    model: str
    note: str = ""          # why the template was used, or what Chris must fix first


def _get(ev, key: str) -> str:
    try:
        value = ev[key]
    except (KeyError, IndexError):
        value = None
    return str(value or "").strip()


def coverage_for(kind: str) -> list[str]:
    return offer.coverage_labels(COVERAGE_BY_KIND.get(kind if kind in COVERAGE_BY_KIND else "other"))


def facts(ev) -> str:
    o = offer.load()
    cfg = config.get_config()
    kind = _get(ev, "event_kind") or "other"
    return "\n".join([
        f"Company: {cfg.brand_name} ({o.get('tagline')})",
        f"Offer list: {'; '.join(offer.coverage_labels())}",
        f"Fits this kind of event best: {'; '.join(coverage_for(kind))}",
        "Their event:",
        f"  name: {_get(ev, 'event_name')}",
        f"  kind: {kind}",
        f"  dates: {keys.dates_in_words(_get(ev, 'start_date'), _get(ev, 'end_date')) or 'not known, do not mention dates'}",
        f"  city: {_get(ev, 'city') or 'not known'}",
        f"  venue: {_get(ev, 'venue') or 'not known'}",
        f"  organizer: {_get(ev, 'organizer') or 'not known'}",
    ])


def template_first(ev) -> OutreachDraft:
    cfg = config.get_config()
    event = _get(ev, "event_name") or "your event"
    when = keys.dates_in_words(_get(ev, "start_date"), _get(ev, "end_date"))
    city = _get(ev, "city")
    where = (f" on {when}" if when else "") + (f" in {city}" if city else "")
    lines = ["Hello,", "",
             f"I am Chris, a convention and event photographer with {cfg.brand_name}. I saw that {event} is coming up{where}, "
             "and I wanted to ask: do you have a photographer lined up yet?", "",
             f"We cover whole events. For {event} that could include:"]
    lines += [f"  {label}" for label in coverage_for(_get(ev, "event_kind"))]
    lines += ["", "We can also deliver approved images on site to attendees, staff, speakers and presenters.", "",
              "If that would help, reply with the days and the parts of the event that matter most, and I will put together a quote.",
              "", "Chris", cfg.brand_name]
    return OutreachDraft(subject=tidy(f"Photography for {event}"), body=tidy_lines(lines), model="template")


def template_follow_up(ev) -> OutreachDraft:
    cfg = config.get_config()
    event = _get(ev, "event_name") or "your event"
    lines = ["Hello,", "",
             f"I wrote earlier about photography for {event}. In case it got buried: if you still need a photographer, "
             "I would be glad to put together a quote. Reply with the days and the parts of the event that matter most.",
             "", "Chris", cfg.brand_name]
    return OutreachDraft(subject=tidy(f"Following up: photography for {event}"), body=tidy_lines(lines), model="template")


def tidy_lines(lines: list[str]) -> str:
    """ai.claude.tidy per line, so the indented coverage lines keep their indent."""
    return "\n".join(("  " + tidy(line)) if line.startswith("  ") else tidy(line) for line in lines)


def with_note(d: OutreachDraft) -> OutreachDraft:
    found = compliance.text_problems(d.subject, d.body)
    if found:
        d.note = "Fix before approving: " + " ".join(p.message for p in found)
    return d


def use_claude(conn: sqlite3.Connection, client) -> Optional[str]:
    """None when a Claude call may be made; else why not."""
    if (config.getenv("AI_MODEL") or "").lower() == "template":
        return "AI_MODEL=template"
    if client is None and not secrets.get_secret("ANTHROPIC_API_KEY"):
        return "no ANTHROPIC_API_KEY"
    if spend.cap_reached(conn):
        return "monthly AI cap reached"
    return None


def draft_first(conn: sqlite3.Connection, ev, *, client=None, agent: str = "outreach") -> OutreachDraft:
    why_not = use_claude(conn, client)
    if why_not:
        d = template_first(ev)
        d.note = f"template ({why_not})"
        return with_note(d)
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    model = config.getenv("OUTREACH_MODEL") or DEFAULT_MODEL
    fallback = template_first(ev)
    try:
        response = client.beta.messages.create(
            model=model, max_tokens=4000, betas=[FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": facts(ev)}],
        )
    except Exception as e:  # noqa: BLE001 — an API hiccup costs one Claude draft, not the day's sends
        fallback.note = f"template (the Claude call failed: {type(e).__name__})"
        return with_note(fallback)
    u = response.usage
    answered = getattr(response, "model", None) or model
    spend.record(conn, agent, answered, int(u.input_tokens or 0), int(u.output_tokens or 0), "outreach draft")
    if response.stop_reason == "refusal":
        fallback.note = "template (the model declined)"
        return with_note(fallback)
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), None)
    try:
        data = json.loads(text or "")
        subject, body = tidy(str(data["subject"])), "\n".join(tidy(line) for line in str(data["body"]).splitlines())
    except (ValueError, KeyError, TypeError):
        fallback.note = f"template (unreadable answer, stop_reason={response.stop_reason})"
        return with_note(fallback)
    cfg = config.get_config()
    if "Chris" not in body.split("\n")[-3:] and not body.rstrip().endswith(cfg.brand_name):
        body = body.rstrip() + f"\n\nChris\n{cfg.brand_name}"
    reasons = [p.message for p in compliance.text_problems(subject, body)]
    if "http" in body.lower() or "www." in body.lower():
        reasons.append("it put a link in the message")
    if len(body.split()) > MAX_WORDS:
        reasons.append("it ran long")
    if reasons:
        fallback.note = "template (the drafted note was thrown away: " + " ".join(reasons) + ")"
        return with_note(fallback)
    return OutreachDraft(subject=subject, body=body, model=answered)
