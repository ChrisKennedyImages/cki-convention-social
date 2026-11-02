"""Moments and shoots: the frames of one burst are one picture, and a post draws across shoots.

Chris, 2026-11-02: "You keep using the same fucking photos for reels! You MUST figure this out too. I'm tired of asking
the same fucking question!" No photo id had gone out twice, but 97 times a frame went out within ten minutes of a frame
from the same Drive folder already on another post (9508 to 9512, one folder, 10:21 to 10:22 on 2021-07-11, went out on
five posts in ten days), and one folder supplied photos to 20 of 32 posts.

- A **moment** is the frames of one Drive folder taken within MOMENT_MINUTES of each other (ten unless the .env says
  otherwise). For the repeat window a moment counts as one photo: once any frame of it airs on a network, its siblings
  stay off that network for the window (agents/content.recent_use, photo_holder; agents/publisher.repeat_of). A single
  post never holds two frames of one moment. A photo with no taken_at, or no folder, is its own moment.
- A **shoot** is a Drive folder. A post takes at most FOLDER_CAP photos from one shoot (two unless the .env says
  otherwise), unless fewer shoots are free than the post needs; then they are spread as evenly as they can be and the
  run line says so (agents/content.Picker). Candidates come in order of the shoot's last use on the networks that are
  on, the least recently used shoot first, then the photo's own last use, then quality (agents/content.in_turn).
"""
from __future__ import annotations

import sqlite3
from bisect import bisect_left, bisect_right
from datetime import datetime
from typing import Iterable, Optional

from ..core import config, db

DEFAULT_MINUTES = 10
DEFAULT_FOLDER_CAP = 2


def minutes() -> int:
    """MOMENT_MINUTES from the .env (Keys page), else ten."""
    try:
        return max(0, int(config.getenv("MOMENT_MINUTES", str(DEFAULT_MINUTES)) or DEFAULT_MINUTES))
    except ValueError:
        return DEFAULT_MINUTES


def folder_cap() -> int:
    """FOLDER_CAP from the .env, else two: the most photos one post takes from one shoot while other shoots are free."""
    try:
        return max(1, int(config.getenv("FOLDER_CAP", str(DEFAULT_FOLDER_CAP)) or DEFAULT_FOLDER_CAP))
    except ValueError:
        return DEFAULT_FOLDER_CAP


def taken(value) -> Optional[datetime]:
    """The camera's clock as the photo row holds it ("2026:06:18 14:18:19", EXIF style; an ISO form is read too)."""
    text = (value or "").strip()[:19]
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def shoot_of(row) -> str:
    return str(row["folder_id"] or "") if "folder_id" in row.keys() else ""


def same_moment(a, b) -> bool:
    """Two photo rows of one moment: the same folder, both timed, within MOMENT_MINUTES."""
    folder = shoot_of(a)
    if not folder or folder != shoot_of(b):
        return False
    ta, tb = taken(a["taken_at"] if "taken_at" in a.keys() else None), taken(b["taken_at"] if "taken_at" in b.keys() else None)
    return ta is not None and tb is not None and abs((ta - tb).total_seconds()) <= minutes() * 60


def siblings(conn: sqlite3.Connection, photo_ids: Iterable[int]) -> set[int]:
    """These photos and every frame of their moments: the same Drive folder, taken within MOMENT_MINUTES of one of them.
    A photo with no taken_at or no folder brings only itself."""
    ids = {int(p) for p in photo_ids}
    if not ids:
        return set()
    out = set(ids)
    marks = ",".join("?" * len(ids))
    seeds = db.rows(conn, f"SELECT id, folder_id, taken_at FROM photos WHERE id IN ({marks})", list(ids))
    by_folder: dict[str, list[datetime]] = {}
    for r in seeds:
        t = taken(r["taken_at"])
        if r["folder_id"] and t is not None:
            by_folder.setdefault(r["folder_id"], []).append(t)
    if not by_folder:
        return out
    span = minutes() * 60
    marks = ",".join("?" * len(by_folder))
    timed = db.rows(conn, f"SELECT id, folder_id, taken_at FROM photos WHERE folder_id IN ({marks}) AND taken_at IS NOT NULL",
                    list(by_folder))
    frames: dict[str, list[tuple[datetime, int]]] = {}
    for r in timed:
        t = taken(r["taken_at"])
        if t is not None:
            frames.setdefault(r["folder_id"], []).append((t, r["id"]))
    for folder, seed_times in by_folder.items():
        rows = sorted(frames.get(folder, []))
        times = [t for t, _ in rows]
        for t in seed_times:
            lo = bisect_left(times, datetime.fromtimestamp(t.timestamp() - span))
            hi = bisect_right(times, datetime.fromtimestamp(t.timestamp() + span))
            out.update(pid for _, pid in rows[lo:hi])
    return out


def cap_for(need: int, counts: Iterable[int]) -> int:
    """How many photos one shoot may give a post of `need` photos, `counts` being how many each free shoot has:
    FOLDER_CAP while that fills the post, else the smallest cap that does (spread as evenly as the shoots allow)."""
    sizes = [int(c) for c in counts if c > 0]
    cap = folder_cap()
    while sizes and sum(min(s, cap) for s in sizes) < need and cap < max(sizes):
        cap += 1
    return cap
