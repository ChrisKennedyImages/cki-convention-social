"""The words on a reel in one of the ten looks (render/reel_looks.py): Event Caliber's own lines, and the beat words its
photos give it.

Chris approved ten reel looks on 2026-11-08, each with words written by hand for Event Caliber. Those ten sets are the
lines here (SETS): the hook (two words and a short line under them), line 1, line 2 and the marquee. No claim, no price,
no event or person named. Any set goes with any look; a reel takes the set the reels used least lately (`choose`), so a
set comes round again only after the others.

The three beat words and the stack label come from the reel's own photos. Chris, 2026-11-08, of a preview whose words
did not fit its pictures: "The screen shot says each award and they are portraits". So a beat word is the room the
final check confirmed its photo plainly shows (content.checked_rooms, the same rooms a post's title prints), one word a
room (BEAT_WORDS); a photo without a confirmed room carries no word; the three words are different where the photos
allow. Axis takes portraits only, so its room words would all be "Portrait.": Chris chose its three himself, the same on
every Axis reel (FIXED_WORDS, 2026-11-08: "Poise. Light. Presence."). The counter never names anything a photo could
contradict (COUNTER).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional, Sequence

from .core import db

# What every reel says about the company, the same on every look (the approved reels, 2026-11-08).
COMPANY = {"business": "Event Caliber", "kicker": "event & conference photography", "town": "DC · MD · VA",
           "phone": "eventcaliber.com", "cta": "Request a quote", "accent": "#00E1FF", "accent2": "#F3F3F1"}


@dataclass(frozen=True)
class Lines:
    open: tuple[str, str]           # the hook, two words
    open_sub: str                   # the short line under the hook
    line1: tuple[str, str]
    line2: tuple[str, str]
    marquee: str


# The ten sets of the approved reels (2026-11-08), numbered 1 to 10 in the order of the reels they were written for.
SETS = {
    1: Lines(("Every", "room."), "every moment.", ("Step", "back."), ("Then", "the room."), "Seen"),
    2: Lines(("Be", "seen."), "be remembered.", ("Shot", "in the room."), ("Not", "from the back."), "Now"),
    3: Lines(("Every", "frame."), "chosen by hand.", ("Shot", "on the day."), ("Picked", "by hand."), "Kept"),
    4: Lines(("Opening", "night."), "the doors open.", ("Lights", "up."), ("Faces", "framed."), "Live"),
    5: Lines(("Every", "floor."), "every room.", ("Floor", "by floor."), ("Room", "by room."), "Inside"),
    6: Lines(("Same", "moment."), "every angle.", ("Stage", "and floor."), ("All", "at once."), "Live"),
    7: Lines(("Rain", "or shine."), "we're in the room.", ("Indoor", "or out."), ("Every", "room."), "Here"),
    8: Lines(("Still.", "Then"), "the moment.", ("Wait", "for it."), ("Then", "it happens."), "Now"),
    9: Lines(("The", "light"), "finds the moment.", ("Wait", "for it."), ("Then", "the frame."), "Seen"),
    10: Lines(("Exactly", "right."), "every time.", ("On", "the line."), ("Dead", "center."), "Now"),
}
# The counter sits over photos that carry no word, so it says nothing a photo could contradict.
COUNTER = {"label": "Every moment", "value": "1", "unit": "take"}
# A confirmed room (library/classify.EVENT_SHOTS) as its beat word, and as it reads in the stack label.
BEAT_WORDS = {"main_stage": "Stage.", "stage_panel": "Panel.", "breakout": "Session.", "portrait": "Portrait.",
              "backstage": "Backstage.", "candid": "Candid.", "reception": "Reception."}
STACK_WORDS = {"main_stage": "stage", "stage_panel": "panels", "breakout": "sessions", "portrait": "portraits",
               "backstage": "backstage", "candid": "candids", "reception": "reception"}
# A look's own three words, the same on every reel in it (Chris, 2026-11-08), on its first three photos; its stack label
# still the rooms, or ALL_PORTRAITS when the three are portraits.
FIXED_WORDS = {"axis": ("Poise.", "Light.", "Presence.")}
ALL_PORTRAITS = "Portraits · headshots"


class TooFewRooms(ValueError):
    """Fewer than three of the reel's photos have a room the final check confirmed: no beat word may be guessed."""


def choose(conn: sqlite3.Connection) -> int:
    """The set the reels used least lately: one never used first (in number order), else the one whose last reel is
    oldest. Read from the drafts themselves (rule_report.lines), every road and every outcome, so a set a turned-back
    reel had also waits its turn."""
    last: dict[int, str] = {}
    for r in db.rows(conn, "SELECT json_extract(rule_report, '$.lines') AS lines, MAX(created_at) AS at FROM content_queue "
                           "WHERE json_extract(rule_report, '$.lines') IS NOT NULL GROUP BY lines"):
        try:
            last[int(r["lines"])] = r["at"] or ""
        except (TypeError, ValueError):
            continue
    return min(SETS, key=lambda n: (last.get(n, ""), n))


@dataclass(frozen=True)
class Beats:
    photos: tuple[int, int, int]    # which of the reel's photos carries each word (indexes into the reel's photos)
    words: tuple[str, str, str]
    stack: str                      # the stack label: the rooms of the three, "Stage · portraits · reception"


def stack_label(rooms: Sequence[str]) -> str:
    """The rooms as the stack label reads them, each once, in order: "Stage · portraits · reception"."""
    stack: list[str] = []
    for r in rooms:
        if STACK_WORDS[r] not in stack:
            stack.append(STACK_WORDS[r])
    label = " · ".join(stack)
    return label[:1].upper() + label[1:]


def beats(rooms: Sequence[Optional[str]], look: Optional[str] = None) -> Beats:
    """The beat words for a reel whose photos (in its order, the hero first) have these confirmed rooms (None: no room
    confirmed). The word photos are the first photos with a confirmed room, one of each room before any room twice, so
    the three words differ wherever the photos allow; each word is its own photo's room. A look with words of its own
    (FIXED_WORDS) puts them on its first three photos; its stack label is their rooms, a photo with none counted a
    portrait (the look takes portraits only), and ALL_PORTRAITS when all three are."""
    if look in FIXED_WORDS:
        if len(rooms) < 3:
            raise ValueError(f"the {look} words go on three photos; {len(rooms)} came")
        three = [r if r in BEAT_WORDS else "portrait" for r in rooms[:3]]
        stack = ALL_PORTRAITS if all(r == "portrait" for r in three) else stack_label(three)
        return Beats(photos=(0, 1, 2), words=FIXED_WORDS[look], stack=stack)
    known = [(i, r) for i, r in enumerate(rooms) if r in BEAT_WORDS]
    if len(known) < 3:
        raise TooFewRooms(f"{len(known)} of the reel's {len(rooms)} photos have a room the final check confirmed; "
                          "its three words need three")
    picked: list[tuple[int, str]] = []
    for i, r in known:
        if r not in {room for _, room in picked} and len(picked) < 3:
            picked.append((i, r))
    for i, r in known:
        if len(picked) < 3 and (i, r) not in picked:
            picked.append((i, r))
    picked.sort()
    return Beats(photos=tuple(i for i, _ in picked), words=tuple(BEAT_WORDS[r] for _, r in picked),
                 stack=stack_label([r for _, r in picked]))


def props(lines: int, beats_: Beats) -> dict:
    """The reel's words as the looks read them (reel-looks/src/look.ts ReelProps), the photos' word indexes included."""
    s = SETS[lines]
    return {**COMPANY, "open": list(s.open), "openSub": s.open_sub, "line1": list(s.line1), "line2": list(s.line2),
            "marquee": s.marquee, "stackLabel": beats_.stack, "counter": dict(COUNTER), "words": list(beats_.words),
            "wordPhotos": list(beats_.photos)}
