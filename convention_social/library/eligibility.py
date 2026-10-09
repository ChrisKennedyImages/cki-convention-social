"""May this photo ever be posted? One function answers, and it fails closed.

A photo is eligible only when ALL of these hold:
  1. it is still in Drive (not trashed) and is a postable image;
  2. Chris cleared it: the photo itself is 'cleared', or it is 'inherit' and
     the nearest folder above it with a decision is 'cleared' (an 'excluded'
     folder nearer to the photo wins; no decision anywhere means not cleared);
  3. it was classified and the classifier said nobody in it could be a minor
     (possible_minor = 0; NULL, unchecked, is a no);
  4. no readable personal detail (badge name, plate, screen, document) was seen;
  5. nothing on the do-not-use list covers it: the photo, any folder above it,
     or a person or handle credited on it;
  6. no credit row for it (or its folders) records consent 'no'.

The publisher asks again at the door, right before anything leaves, so a
takedown added after approval still stops the post.
"""
from __future__ import annotations

import json
import sqlite3

from ..core import db

MAX_DEPTH = 64


def folder_chain(conn: sqlite3.Connection, folder_id: str | None) -> list[sqlite3.Row]:
    """The photo's folder, then its parent, and so on up (nearest first)."""
    out, seen = [], set()
    while folder_id and folder_id not in seen and len(out) < MAX_DEPTH:
        seen.add(folder_id)
        row = db.one(conn, "SELECT drive_id, parent_id, clearance FROM drive_folders WHERE drive_id=?", (folder_id,))
        if row is None:
            break
        out.append(row)
        folder_id = row["parent_id"]
    return out


def clearance_of(conn: sqlite3.Connection, photo: sqlite3.Row) -> str:
    """'cleared' | 'blocked' | 'excluded' | 'not_cleared' — the decision that applies to this photo."""
    if photo["clearance"] == "blocked":
        return "blocked"
    if photo["clearance"] == "cleared":
        return "cleared"
    for f in folder_chain(conn, photo["folder_id"]):
        if f["clearance"] in ("cleared", "excluded"):
            return f["clearance"]
    return "not_cleared"


def credits_for(conn: sqlite3.Connection, photo: sqlite3.Row) -> list[sqlite3.Row]:
    folder_ids = [f["drive_id"] for f in folder_chain(conn, photo["folder_id"])]
    rows = db.rows(conn, "SELECT * FROM credits WHERE scope='photo' AND drive_id=?", (photo["drive_id"],))
    if folder_ids:
        marks = ",".join("?" for _ in folder_ids)
        rows += db.rows(conn, f"SELECT * FROM credits WHERE scope='folder' AND drive_id IN ({marks})", folder_ids)
    return rows


def blocked_by_list(conn: sqlite3.Connection, photo: sqlite3.Row) -> str | None:
    if db.one(conn, "SELECT 1 FROM do_not_use WHERE kind='photo' AND value=?", (photo["drive_id"],)):
        return "this photo is on the do-not-use list"
    for f in folder_chain(conn, photo["folder_id"]):
        if db.one(conn, "SELECT 1 FROM do_not_use WHERE kind='folder' AND value=?", (f["drive_id"],)):
            return "its folder is on the do-not-use list"
    for c in credits_for(conn, photo):
        for kind, value in (("person", c["person_name"]), ("handle", c["handle"])):
            if value and db.one(conn, "SELECT 1 FROM do_not_use WHERE kind=? AND value=?", (kind, value.strip().lower())):
                return f"a person in it ({value}) is on the do-not-use list"
    return None


def is_eligible(conn: sqlite3.Connection, photo_id: int) -> tuple[bool, str]:
    photo = db.one(conn, "SELECT * FROM photos WHERE id=?", (photo_id,))
    if photo is None:
        return False, "photo not in the library"
    if photo["trashed"]:
        return False, "photo is no longer in Drive"
    decision = clearance_of(conn, photo)
    if decision != "cleared":
        return False, {"blocked": "Chris blocked this photo", "excluded": "its folder is excluded",
                       "not_cleared": "not cleared yet"}[decision]
    why = blocked_by_list(conn, photo)
    if why:
        return False, why
    for c in credits_for(conn, photo):
        if c["consent"] == "no":
            return False, "the credits sheet says no consent"
    cls = db.one(conn, "SELECT possible_minor, personal_details FROM classifications WHERE photo_id=?", (photo_id,))
    if cls is None or cls["possible_minor"] is None:
        return False, "not checked for minors yet"
    if cls["possible_minor"] != 0:
        return False, "someone in it may be under 18"
    try:
        details = json.loads(cls["personal_details"] or "[]")
    except ValueError:
        return False, "personal details check unreadable"
    if details:
        return False, "shows personal details: " + ", ".join(map(str, details))
    return True, "ok"


def eligible_photo_ids(conn: sqlite3.Connection, ids) -> list[int]:
    return [i for i in ids if is_eligible(conn, int(i))[0]]


def credit_line(conn: sqlite3.Connection, photo_id: int) -> str:
    """The credit to print, exactly as Chris recorded it: handles first, then names. '' when none."""
    photo = db.one(conn, "SELECT * FROM photos WHERE id=?", (photo_id,))
    if photo is None:
        return ""
    seen, parts = set(), []
    for c in credits_for(conn, photo):
        if c["consent"] == "no":
            continue
        label = (c["handle"] or c["person_name"] or "").strip()
        if label and label.lower() not in seen:
            seen.add(label.lower())
            parts.append(label)
    return " ".join(parts)
