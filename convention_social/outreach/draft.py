"""The note to an event organizer: Chris's own words, with the event's facts in their places. Chris edits and
approves on the Outreach page; nothing sends on its own.

2026-10-31, after reading the first two drafts Claude wrote: "I just read it and wasn't really satisfied. Here is
what I want it to say Specifically and this should be the template for all of them." So every first note is his
template (FOUNDER_DECISIONS.md carries it verbatim) and Claude no longer writes them. The footer and the opt-out
line are added at send time by outreach.compliance, not here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..ai.claude import tidy
from ..core import config
from . import compliance, keys

# the word for their event in "while the ___ is still underway", read off the event's name; "event" when it says nothing
KIND_WORDS = (("meeting", re.compile(r"\bmeeting\b", re.I)),
              ("convention", re.compile(r"\bconvention\b", re.I)),
              ("conference", re.compile(r"\b(conference|congress|summit|symposium|forum)\b", re.I)),
              ("show", re.compile(r"\b(expo|exposition|show|exhibition|fair)\b", re.I)),
              ("gala", re.compile(r"\b(gala|awards?|dinner|ball)\b", re.I)))


@dataclass
class OutreachDraft:
    subject: str
    body: str
    model: str
    note: str = ""          # what Chris must fix before approving, when anything


def _get(ev, key: str) -> str:
    try:
        value = ev[key]
    except (KeyError, IndexError):
        value = None
    return str(value or "").strip()


def kind_word(event_name: str) -> str:
    for word, pattern in KIND_WORDS:
        if pattern.search(event_name):
            return word
    return "event"


def month_of(start: str) -> str:
    """'2027-03-11' -> 'March'; '' when the start is not a real day."""
    iso = keys.iso_day(start)
    return date.fromisoformat(iso).strftime("%B") if iso else ""


def dates_as_chris_writes_them(start: str, end: str) -> str:
    """'March 11–14, 2027' (his template's form, an en dash and no spaces); 'March 30–April 2, 2027' across months;
    'December 31, 2026–January 2, 2027' across years; one day is 'March 11, 2027'; '' when the start is not a real day."""
    a, b = keys.iso_day(start), keys.iso_day(end)
    if not a:
        return ""
    first = date.fromisoformat(a)
    last = date.fromisoformat(b) if b else first
    if last <= first:
        return f"{first.strftime('%B')} {first.day}, {first.year}"
    if (first.year, first.month) == (last.year, last.month):
        return f"{first.strftime('%B')} {first.day}–{last.day}, {first.year}"
    if first.year == last.year:
        return f"{first.strftime('%B')} {first.day}–{last.strftime('%B')} {last.day}, {first.year}"
    return f"{first.strftime('%B')} {first.day}, {first.year}–{last.strftime('%B')} {last.day}, {last.year}"


def template_first(ev) -> OutreachDraft:
    """Chris's words (2026-10-31), the event's name, dates, city and month in their places; nothing said that is not known."""
    cfg = config.get_config()
    event = tidy(_get(ev, "event_name")) or "your event"
    when = dates_as_chris_writes_them(_get(ev, "start_date"), _get(ev, "end_date"))
    city = _get(ev, "city")
    month = month_of(_get(ev, "start_date"))
    opening = f"I'm reaching out regarding {event}"
    if when:
        opening += f", taking place {when}"
    if city:
        opening += f", in {city}" if when else f" in {city}"
    asked = f"Do you already have a photographer lined up for {month}?" if month else "Do you already have a photographer lined up?"
    lines = [
        "Hello,", "",
        opening + ".", "",
        "We're local convention and event photographers offering a unique service: delivering photos to attendees while the "
        f"{kind_word(event)} is still underway. We can provide this service to all attendees or exclusively to your staff, "
        "depending on your preference.", "",
        "For an event like yours, we can cover keynotes and main-stage presentations, breakout sessions and panels, dinners and "
        "receptions, and portraits. We also offer flexible coverage before, during, and into the evening to accommodate your "
        "event schedule.", "",
        asked + " If not, I'd love to hear a little about your plans so I can put together a quote tailored to your needs.", "",
        "Chris", cfg.brand_name,
    ]
    return OutreachDraft(subject=f"Photography for {event}", body="\n".join(lines), model="template")


def template_follow_up(ev) -> OutreachDraft:
    cfg = config.get_config()
    event = _get(ev, "event_name") or "your event"
    lines = ["Hello,", "",
             f"I wrote earlier about photography for {event}. In case it got buried: if you still need a photographer, "
             "I would be glad to put together a quote. Reply with the days and the parts of the event that matter most.",
             "", "Chris", cfg.brand_name]
    return OutreachDraft(subject=tidy(f"Following up: photography for {event}"), body=tidy_lines(lines), model="template")


def tidy_lines(lines: list[str]) -> str:
    """ai.claude.tidy per line, so an indented line keeps its indent."""
    return "\n".join(("  " + tidy(line)) if line.startswith("  ") else tidy(line) for line in lines)


def with_note(d: OutreachDraft) -> OutreachDraft:
    found = compliance.text_problems(d.subject, d.body)
    if found:
        d.note = "Fix before approving: " + " ".join(p.message for p in found)
    return d


def draft_first(ev) -> OutreachDraft:
    """The first note to an organizer, checked against the rules Chris's edits must keep passing too."""
    return with_note(template_first(ev))
