"""The free first pass: what the folder path and dates say about a photo.

Words in the folder path decide whether a folder looks like convention or
event work, which kind (fan or business), and which words to drop to get a
readable event name. This only nominates candidates: nothing becomes
eligible from a folder name; Chris clears folders himself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

FAN_WORDS = ("comic", "comicon", "comic-con", "anime", "cosplay", "otakon", "katsucon", "gaming", "game con",
             "fan expo", "fanexpo", "dragon con", "dragoncon", "awesome con", "awesomecon", "megacon", "furry",
             "sci-fi", "scifi", "horror con", "toy", "manga")
BUSINESS_WORDS = ("cpac", "conference", "summit", "convention", "expo", "trade show", "tradeshow", "forum",
                  "symposium", "gala", "awards", "award", "reception", "keynote", "breakout", "panel", "booth",
                  "vendor", "exhibit", "networking", "step and repeat", "speaker", "acu", "breakfast", "luncheon",
                  "dinner", "headshot", "festival", "fest", "con ")
NOT_EVENT_WORDS = ("wedding", "bride", "groom", "engagement", "birthday", "bday", "prom", "homecoming", "baby",
                   "newborn", "family", "maternity", "real estate", "realestate", "apartment", "listing", "house",
                   "home tour", "interior", "architecture", "logo", "invoice", "receipt", "screenshot", "scan",
                   "unedited", "raw", "low-res", "low res", "preview", "video")
YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
TIDY = re.compile(r"[\s_\-]+")


@dataclass
class FolderGuess:
    is_event: Optional[bool]          # True event-like, False clearly not, None no signal
    event_kind: str                   # fan | business | unknown
    event_name: str
    year: Optional[int]


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def guess(path: str, taken_at: Optional[str] = None) -> FolderGuess:
    leafs = [p for p in (path or "").split("/") if p and p != "My Drive" and not p.startswith("Shared drive:")]
    low = " " + " ".join(leafs).lower() + " "
    kind = "fan" if _has(low, FAN_WORDS) else ("business" if _has(low, BUSINESS_WORDS) else "unknown")
    if _has(low, NOT_EVENT_WORDS) and kind == "unknown":
        is_event: Optional[bool] = False
    elif kind != "unknown":
        is_event = True
    else:
        is_event = None
    years = [int(y) for y in YEAR.findall(" ".join(leafs))]
    year = years[-1] if years else None
    if year is None and taken_at:
        m = YEAR.search(taken_at[:4])
        year = int(m.group(1)) if m else None
    # the event name: the outermost folder that names the event, years and filler dropped
    name = ""
    for part in leafs:
        if _has(" " + part.lower() + " ", FAN_WORDS + BUSINESS_WORDS):
            name = part
            break
    name = YEAR.sub("", name)
    name = re.sub(r"(?i)\b(selects?|final|finals|photos?|images?|edited|exports?|jpe?gs?|immediate release|website)\b", "", name)
    name = TIDY.sub(" ", name).strip(" -_,.")
    return FolderGuess(is_event=is_event, event_kind=kind, event_name=name, year=year)
