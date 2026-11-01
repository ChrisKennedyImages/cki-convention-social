"""An event's dates, read off its own page, kept only when the page says them word for word.

Chris, 2026-11-01, on events the scout found without dates (the three-month rule cannot be checked, the note's first line
names the dates, and the scout never searches a known event again), chose "Look up their dates": "When the agent reads
an event's site for an email, it also reads the dates (a small Claude read, well under a cent each, through the AI
budget). A draft comes only once dates are found and are 3+ months out."

One call per event, on the words of the event's own page (no markup, at most TEXT_MAX characters), with the cheapest
model the suite already uses (claude-haiku-4-5, as the photo writer). Fail closed: the dates are
kept only when the words the model quotes are in the page exactly as written and name those days (the year, the month
and the day of the start, and of the end where it differs), and the start is not past; otherwise no dates and a plain
note. Paid through ai/spend like every call: reserved before (no call when it would pass the monthly cap), recorded at
the model that answered. No call in a dry run, with AI_MODEL=template, or with no key.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Optional

from ..ai import spend
from ..core import config, secrets
from . import keys

DEFAULT_MODEL = "claude-haiku-4-5"
TEXT_MAX = 12_000               # the top of an event page, where its dates are; about 3,000 tokens, a third of a cent
RESERVE_USD = 0.02             # held on the ledger while the call is in flight
QUOTE_MAX = 200
LONGEST_EVENT_DAYS = 31

SYSTEM = """You read the text of one event's web page and report the dates of that event, exactly as the page states them.
Rules:
1. Only the dates of the coming edition of the event the page is about. Never a past edition, never a deadline, a registration or hotel date, or another event the page mentions.
2. quote is the shortest passage of the page, copied character for character, that states those dates and their year (for example "March 11-14, 2027"). If the page gives no dates, or no year with them, every field is an empty string.
3. start_date and end_date are YYYY-MM-DD. end_date is empty for a one-day event.
4. Never guess. When unsure, every field is an empty string."""

SCHEMA = {
    "type": "object",
    "properties": {"start_date": {"type": "string"}, "end_date": {"type": "string"}, "quote": {"type": "string"}},
    "required": ["start_date", "end_date", "quote"],
    "additionalProperties": False,
}

MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
          "december")


@dataclass
class Dates:
    start: str = ""
    end: str = ""
    note: str = ""              # read off <page>: "<the words>", or why there are none
    later: bool = False         # not read this run (the cap, the API): the event is read again on a later run


def flat(text: str) -> str:
    """One space for every run of whitespace (a page's line breaks and no-break spaces included)."""
    return " ".join((text or "").split())


def _month_named(quote: str, day: date) -> bool:
    name = MONTHS[day.month - 1]
    words = {name, name[:3]} | ({"sept"} if day.month == 9 else set())
    return any(re.search(rf"\b{w}\b", quote) for w in words) or bool(
        re.search(rf"(?<!\d)0?{day.month}[/.-]0?{day.day}(?!\d)|{day.year}-{day.month:02d}-{day.day:02d}", quote))


def _day_named(quote: str, day: date) -> bool:
    return bool(re.search(rf"(?<!\d)0?{day.day}(?:st|nd|rd|th)?(?!\d)", quote))


def names_days(quote: str, start: date, end: Optional[date]) -> bool:
    """The quoted words say these days: the start's year, month and day, and the end's day (its month and year too when
    they differ from the start's)."""
    q = quote.lower()
    if str(start.year) not in re.findall(r"\d{4}", q) or not _month_named(q, start) or not _day_named(q, start):
        return False
    if end and end != start:
        if not _day_named(q, end):
            return False
        if end.month != start.month and not _month_named(q, end):
            return False
        if end.year != start.year and str(end.year) not in re.findall(r"\d{4}", q):
            return False
    return True


def checked(raw: dict, page_text: str, page_url: str, today: date) -> Dates:
    """The model's answer, kept only when the page says it. Every refusal says why in plain words."""
    quote = flat(str(raw.get("quote") or ""))
    start, end = keys.iso_day(raw.get("start_date")), keys.iso_day(raw.get("end_date"))
    if not quote and not start:
        return Dates(note=f"no dates on {page_url}")
    if not start:
        return Dates(note=f"the dates on {page_url} could not be read as days")
    if not quote or len(quote) > QUOTE_MAX or quote not in flat(page_text):
        return Dates(note=f"the dates read were not found on {page_url} word for word; none kept")
    first = date.fromisoformat(start)
    last = date.fromisoformat(end) if end else None
    if last and not (first <= last and (last - first).days <= LONGEST_EVENT_DAYS):
        return Dates(note=f"the dates read off {page_url} do not make one event ({start} to {end}); none kept")
    if not names_days(quote, first, last):
        return Dates(note=f'the words "{quote}" on {page_url} do not name {start}{" to " + end if end else ""}; none kept')
    if first < today:
        return Dates(note=f'"{quote}" on {page_url} has passed: the last edition, not the next; none kept')
    return Dates(start=start, end=end or "", note=f'read off {page_url}: "{quote}"')


class Reader:
    """One small Claude read a call, on the ledger like every other."""

    def __init__(self, conn: sqlite3.Connection, *, client, agent: str = "outreach"):
        self.conn, self.client, self.agent, self.model = conn, client, agent, DEFAULT_MODEL

    def read(self, page_text: str, page_url: str, today: date) -> Dates:
        held = spend.reserve(self.conn, self.agent, self.model, estimate_usd=RESERVE_USD)
        if held is None:
            return Dates(note="the monthly AI cap is reached; the dates are read on a later run", later=True)
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=300, system=SYSTEM,
                output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": f"Today: {today.isoformat()}\nPage: {page_url}\n\n"
                                                      f"{flat(page_text)[:TEXT_MAX]}"}])
        except Exception as e:  # noqa: BLE001 — the API or the network: nothing spent, read again on a later run
            spend.release(self.conn, held)
            return Dates(note=f"the dates could not be read this run ({type(e).__name__}); a later run tries again", later=True)
        u = response.usage
        spend.record(self.conn, self.agent, getattr(response, "model", None) or self.model, int(u.input_tokens or 0),
                     int(u.output_tokens or 0), f"event dates {page_url}"[:300], reservation=held)
        text = next((b.text for b in response.content if b.type == "text"), None)
        if response.stop_reason == "refusal" or not text:
            return Dates(note=f"no dates read off {page_url}")
        try:
            raw = json.loads(text)
        except ValueError:
            return Dates(note=f"no dates read off {page_url}")
        return checked(raw if isinstance(raw, dict) else {}, page_text, page_url, today)


def reader(conn: sqlite3.Connection, *, dry_run: bool, client=None, agent: str = "outreach") -> tuple[Optional[Reader], str]:
    """(the reader, '') or (None, why no date is read this run): a dry run, AI_MODEL=template and no key pay nothing."""
    if dry_run:
        return None, "a dry run reads no dates (a paid call)"
    if (config.getenv("AI_MODEL") or "").lower() == "template":
        return None, "AI_MODEL=template: no dates read"
    if client is None:
        key = secrets.get_secret("ANTHROPIC_API_KEY")
        if not key:
            return None, "no ANTHROPIC_API_KEY: no dates read"
        import anthropic  # here, so a run that reads no dates needs neither key nor SDK
        client = anthropic.Anthropic(api_key=key)
    return Reader(conn, client=client, agent=agent), ""
