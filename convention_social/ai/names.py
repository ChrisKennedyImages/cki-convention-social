"""No public word names an event, the company behind it, or a person.

Chris, 2026-10-11: "Because A LOT of the images are ACU and CPAC (the same company) i want to make
sure the captions don't say the specific event or person." Captions say what kind of event it was
(a conference, a fan convention), never which one, and never who is in the photo. The same holds for
the words printed on the post images, the search fields inside the image files and the website's
photo text, since all of those are public too. Private mail to an organizer about their own event
(outreach, quote replies) is not public copy and is not covered.

`public_names` is every name the suite knows: the two Chris named, every event name the sorting or
the calendar recorded, and every person and handle on the credits sheet. `mentions` finds them in a
text, plus any @handle at all; ai/copy_rules.py blocks on it, so the gate is not the prompt.
"""
from __future__ import annotations

import re
import sqlite3

from ..core import db

# the ones Chris named, in every form a caption might use
ALWAYS = ("CPAC", "ACU", "American Conservative Union", "Conservative Political Action Conference",
          "Conservative Political Action")
NOT_NAMES = {"unknown", "none", "n/a", "na", "event", "events", "convention", "conference", "other", "misc"}
YEAR = re.compile(r"\s*\b(?:19|20)\d{2}\b\s*")
HANDLE = re.compile(r"(?<![\w.])@[A-Za-z0-9_.]{2,}")
HASHTAG = re.compile(r"#(\w+)")


def _forms(name: str) -> set[str]:
    """The name, and the name without a year ("Katsucon 2025" is also "Katsucon")."""
    name = " ".join((name or "").split())
    out = {name, YEAR.sub(" ", name).strip()}
    return {n for n in out if len(n) >= 3 and n.lower() not in NOT_NAMES}


def public_names(conn: sqlite3.Connection) -> list[str]:
    names: set[str] = set()
    for n in ALWAYS:
        names |= _forms(n)
    for sql in ("SELECT DISTINCT convention_name AS n FROM classifications WHERE convention_name IS NOT NULL",
                "SELECT DISTINCT name AS n FROM conventions",
                "SELECT DISTINCT person_name AS n FROM credits WHERE person_name IS NOT NULL",
                "SELECT DISTINCT handle AS n FROM credits WHERE handle IS NOT NULL"):
        try:
            for r in db.rows(conn, sql):
                names |= _forms(str(r["n"]).lstrip("@"))
        except sqlite3.OperationalError:          # a table not made yet names nobody
            continue
    return sorted(names, key=lambda n: (-len(n), n.lower()))


def mentions(text: str, names) -> list[str]:
    """The names (and @handles) this text contains. Matching ignores case and sits on letter
    boundaries, so "#CPAC2025" names CPAC and "vacuum" does not name ACU; inside a hashtag the
    words run together, so a name of four letters or more is also found there ("#cpacphotos")."""
    text = text or ""
    found = []
    for name in names:
        if re.search(r"(?<![A-Za-z])" + re.escape(name) + r"(?![A-Za-z])", text, re.IGNORECASE):
            found.append(name)
            continue
        squashed = re.sub(r"\W+", "", name).lower()
        if len(squashed) >= 4 and any(squashed in tag.lower() for tag in HASHTAG.findall(text)):
            found.append(name)
    found += HANDLE.findall(text)
    return found
