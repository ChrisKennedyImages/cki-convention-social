"""One normalization for the scout and outreach: event keys, addresses, opt-out tokens and dates in words."""
from __future__ import annotations

import re
import secrets
from datetime import date
from typing import Optional

EMAIL = re.compile(r"^[^\s@<>,;\"']+@[^\s@<>,;\"']+\.[a-z]{2,}$", re.IGNORECASE)
TOKEN = re.compile(r"^[a-f0-9]{32}$")
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def name_key(name: str) -> str:
    """Lowercase letters and digits, single spaces: 'Awesome Con: 2027!' -> 'awesome con 2027'."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def event_key(name: str, start_date: Optional[str]) -> str:
    return f"{name_key(name)}|{start_date or ''}"


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return bool(EMAIL.match(normalize_email(email)))


def new_token() -> str:
    """Random, 32 hex characters (no dashes, nothing derived from the address)."""
    return secrets.token_hex(16)


def iso_day(value) -> Optional[str]:
    """'2027-03-05' stays; anything that is not a real calendar day becomes None."""
    text = str(value or "").strip()
    if not ISO_DAY.match(text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def in_words(day: Optional[str]) -> str:
    """'2027-03-05' -> 'March 5, 2027' (letters and digits only, so no dash ever reaches copy)."""
    d = iso_day(day)
    if not d:
        return ""
    parsed = date.fromisoformat(d)
    return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"


def dates_in_words(start: Optional[str], end: Optional[str]) -> str:
    first, last = in_words(start), in_words(end)
    if not first:
        return ""
    if not last or last == first:
        return first
    a, b = date.fromisoformat(iso_day(start)), date.fromisoformat(iso_day(end))
    if a.year == b.year and a.month == b.month:
        return f"{a.strftime('%B')} {a.day} to {b.day}, {a.year}"          # March 5 to 7, 2027
    if a.year == b.year:
        return f"{a.strftime('%B')} {a.day} to {b.strftime('%B')} {b.day}, {a.year}"
    return f"{first} to {last}"
