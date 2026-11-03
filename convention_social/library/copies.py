"""Copies: one picture, however many files Drive holds of it.

Chris, 2026-11-02: "And I thought you got rid of the duplicates and I still see so many". Identical files had been one
picture since 2026-10-26 (the same md5), but the same picture is also saved as other files: a low-res export beside the
original ("Stone_Point-14.jpg", 916x600 in "Low-Res Images" and 7867x5151 in "Stone Point Apartments"), the client's
copies filed into one folder per person ("1-Texas_2022NICL4065-TEXAS2022.jpg" in "Scott Hall" and in "Steven"). That
day 620 pictures put 825 extra cards on To review. His ruling: one card per picture, the largest file; a decision on the
card applies to every copy, and a post uses the largest file.

Two photos are copies of one picture when
  - they are the same bytes (md5), or
  - they are the same file saved again: the same file name (name_key), taken in the same second by the camera's clock
    (both known), and the same shape (same_shape),
and a copy of a copy is a copy. Frames of one burst are different pictures: the camera numbers every frame (DSC_6552,
DSC_6553), and a phone's frames inside one second carry a counter with no space ("20170811_204436(1).jpg"), which is
never taken off.

photos.picture is the id of the photo that stands for the picture (stands_first): the largest file by pixel area, the
lowest id on a tie, of the files still in Drive the sorter has looked at. A picture is on To review only when its card is
sorted, and the sorter only takes photos from folders that look like work, so the largest file of all would have taken 53
pictures off To review on 2 November (one file sat in a folder the sorter never reads, the copy it sorted elsewhere); a
larger copy stands for the picture from the pass after it is sorted. A photo removed from Drive never stands for a
picture and takes no decision, but it keeps its picture, so a post of a file since removed still holds the copies that
remain. A photo the pass has not seen yet (its picture is NULL) stands for itself: STANDS_FOR_ITS_PICTURE.

link() runs after every inventory pass (agents/scanner) and gives every copy in Drive the picture's decision: his Use on
any copy wins (2026-11-02: where he had tapped Use on one file and Never use on its duplicate, he chose "Approved": the
second swipe was at the repeat, not the picture), then Never use; a picture with neither is left as it is.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from ..core import db
from . import moments
from .eligibility import SORTED_METHODS

# The SQL test that the photo row `p` stands for its picture: the one card on the photo lists and the one file a post,
# a wall or the site takes.
STANDS_FOR_ITS_PICTURE = "p.id = COALESCE(p.picture, p.id)"
COPY_OF = "copy of "                     # Drive names a copy "Copy of <name>", once for every time it was copied
EXTENSION = re.compile(r"\.[a-z0-9]{1,5}$")
# "acura (1).jpg" beside "acura.jpg": the same file downloaded twice. With the space only: "20170811_204436(1).jpg" is a
# phone's second frame in that second, a different picture.
DOWNLOAD_COUNTER = re.compile(r" \(\d+\)$")


def stands_for_its_picture(row) -> bool:
    """STANDS_FOR_ITS_PICTURE, for a photo row already read."""
    return row["picture"] in (None, row["id"])


def every_copy(conn: sqlite3.Connection, photo_ids) -> set[int]:
    """These photos with every live copy of their pictures (2026-10-26 for identical files, 2026-11-02 for the rest)."""
    out = {int(p) for p in photo_ids}
    ids = sorted(out)
    for k in range(0, len(ids), 500):
        marks = ",".join("?" * len(ids[k:k + 500]))
        out.update(r["id"] for r in db.rows(conn, f"SELECT id FROM photos WHERE trashed = 0 AND picture IN "
                                                  f"(SELECT picture FROM photos WHERE id IN ({marks}))", ids[k:k + 500]))
    return out


def name_key(name: str) -> str:
    """The file name two copies share: lower case, without Drive's "Copy of ", the extension or a download counter."""
    key = (name or "").strip().lower()
    while key.startswith(COPY_OF):
        key = key[len(COPY_OF):]
    return DOWNLOAD_COUNTER.sub("", EXTENSION.sub("", key)).strip()


def same_shape(a, b) -> bool:
    """The smaller file is the larger one resized: the same way round, and its sides are the larger's scaled to it within a
    pixel, which is all a resize rounds. A crop is another picture, however slight: CK6_0180.jpg at 7344x4931 is the
    8256x5504 frame cropped (0.7% off its shape, a man cut at the edge)."""
    if not (a["width"] and a["height"] and b["width"] and b["height"]):
        return False
    (w, h), (big_w, big_h) = sorted(((a["width"], a["height"]), (b["width"], b["height"])), key=lambda s: s[0] * s[1])
    return abs(w * big_h - h * big_w) <= big_w + big_h


def stands_first(row) -> tuple:
    """The order the photos of one picture stand for it in: in Drive first, then sorted by a model, then the largest,
    then the lowest id."""
    return row["trashed"], not row["sorted"], -(row["width"] or 0) * (row["height"] or 0), row["id"]


@dataclass
class Linked:
    pictures: int = 0          # pictures held in more than one file in Drive
    extra: int = 0             # the files beyond one per such picture: the cards that do not show
    relinked: int = 0          # photos whose picture this pass changed
    decided: int = 0           # copies this pass gave their picture's decision

    def line(self) -> str:
        return (f"copies: {self.pictures} picture{'' if self.pictures == 1 else 's'} in more than one file ({self.extra} extra), "
                f"{self.relinked} relinked, {self.decided} given their picture's decision")


def link(conn: sqlite3.Connection) -> Linked:
    """Group every photo with its copies, store the photo that stands for each picture in photos.picture, and give the
    copies in Drive their picture's decision. Read and written in one transaction that holds the write lock, so a tap on
    the dashboard meanwhile waits for it and is never undone by it; what changed is counted for the run line."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        out = _link(conn)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return out


def _link(conn: sqlite3.Connection) -> Linked:
    rows = db.rows(conn, f"""SELECT p.id, p.name, p.md5, p.width, p.height, p.taken_at, p.trashed, p.clearance, p.clearance_at,
                                    p.picture, COALESCE(c.method IN ({",".join("?" * len(SORTED_METHODS))}), 0) AS sorted
                             FROM photos p LEFT JOIN classifications c ON c.photo_id = p.id""", SORTED_METHODS)
    parent = {r["id"]: r["id"] for r in rows}

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def join(a: int, b: int) -> None:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_md5: dict[str, int] = {}
    by_file: dict[tuple, list] = {}
    for r in rows:
        if r["md5"]:
            join(by_md5.setdefault(r["md5"], r["id"]), r["id"])
        when, key = moments.taken(r["taken_at"]), name_key(r["name"])
        if when is not None and key:
            by_file.setdefault((key, when), []).append(r)
    for same_file in by_file.values():
        for i, a in enumerate(same_file):
            for b in same_file[i + 1:]:
                if same_shape(a, b):
                    join(a["id"], b["id"])
    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(root(r["id"]), []).append(r)
    out = Linked()
    links, decisions = [], []
    for members in groups.values():
        rep = min(members, key=stands_first)["id"]
        links += [(rep, r["id"]) for r in members if r["picture"] != rep]
        live = [r for r in members if not r["trashed"]]
        if len(live) < 2:
            continue
        out.pictures += 1
        out.extra += len(live) - 1
        states = {r["clearance"] for r in live}
        decision = "cleared" if "cleared" in states else "blocked" if "blocked" in states else None
        if decision is None:
            continue
        at = max((r["clearance_at"] or "" for r in live if r["clearance"] == decision), default="") or None
        decisions += [(decision, at, r["id"]) for r in live if r["clearance"] != decision]
    conn.executemany("UPDATE photos SET picture=? WHERE id=?", links)
    conn.executemany("UPDATE photos SET clearance=?, clearance_at=? WHERE id=?", decisions)
    out.relinked, out.decided = len(links), len(decisions)
    return out
