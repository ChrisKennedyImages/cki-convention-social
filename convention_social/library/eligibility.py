"""May this photo ever be posted? One function answers, and it fails closed.

HIS APPROVAL IS FINAL (Chris, 2026-11-08: "NOTHING IS PRIVATE because I have hand approved every photo! No one can
override MY approvals and that is a law"; then "Yes, override everything"). What keeps a photo out is his alone: his
Use (or Never use) on it, an excluded folder, the do-not-use list and the consent in his credits sheet. No model's
answer about what a photo shows keeps it out once he has used it: not the kind of occasion (a wedding, a private
occasion), not a readable detail, not a costume, not what a building frame shows. Those answers are labels: they word a
post, arrange a reel and keep what he is offered on To review (dashboard/app.py) and the contact sheets
(library/report.best) to the work, for the photos he has not decided on.

  is_candidate()  may the daily picker consider it? Rules 1 to 4.
  is_eligible()   may it be POSTED? A candidate Claude's final check has looked at, so the post prints the label Claude
                  gave it on the full photo (library/classify.final_check). The check never vetoes; what it says is the
                  photo's label. The dashboard's Approve and the publisher's door ask this one.

A photo is a candidate only when ALL of these hold:
  1. it is still in Drive (not trashed);
  2. Chris cleared it: his own Use on the photo ('cleared'), and no folder above it excluded. A folder never approves its
     photos (2026-11-02: "MANY of the approved photos, I never approved": two folders approved whole had made 1,648
     photos ready to use that he had never looked at);
  3. nothing on the do-not-use list covers it, and no credit row for it (or its folders) records consent 'no';
  4. a model sorted it (method ollama or vision; the free folder row is a no), so it has a label to print.

The publisher asks again at the door, right before anything leaves, so a takedown added after approval still stops the
post.
"""
from __future__ import annotations

import sqlite3

from ..core import db

MAX_DEPTH = 64
SORTED_METHODS = ("ollama", "vision")    # a model looked at it; 'folder' is the free guess from the path
# The two kinds of work a photo is, wherever photos are drawn (posts, reels, samples, the site, the contact sheets, the
# dashboard's lists): the building work the sorter called architecture, and event work, which is every other photo.
# Chris, 2026-10-11: "Architecture images should be separated from event/convention photos". 2026-11-08 (his approval is
# final): 24 photos he used were "other" to the sorter, a studio headshot on a coloured gradient among them (photo
# 14833), and no event pool reached them; the dashboard had listed them as event work since 2026-10-11. SQL over
# classifications c.
WORK = {"event": "COALESCE(c.subject, '') != 'architecture'", "architecture": "c.subject = 'architecture'"}


def work_of(subject) -> str:
    """'architecture' or 'event', by the rule WORK writes in SQL."""
    return "architecture" if subject == "architecture" else "event"


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


def copies_of(conn: sqlite3.Connection, photo_id: int) -> list[int]:
    """The live photos that are this one's picture (library/copies.py: identical files, 2,916 photos in 1,432 groups on
    2026-10-26, and the same picture saved as another file, 2026-11-02). A decision is on the picture, so it is written
    to every copy; the one photo is always in the list."""
    return [r["id"] for r in db.rows(conn, "SELECT id FROM photos WHERE id = ? OR (trashed = 0 "
                                           "AND picture = (SELECT picture FROM photos WHERE id = ?))", (photo_id, photo_id))]


def clearance_of(conn: sqlite3.Connection, photo: sqlite3.Row) -> str:
    """'cleared' | 'blocked' | 'excluded' | 'not_cleared' — the decision that applies to this photo. Fail
    closed (2026-10-13): Never use on the photo wins over everything; an excluded folder anywhere above it
    wins over a Use on the photo ("kept out, even photos you tapped Use on"); then the photo's own Use."""
    if photo["clearance"] == "blocked":
        return "blocked"
    chain = folder_chain(conn, photo["folder_id"])
    if any(f["clearance"] == "excluded" for f in chain):
        return "excluded"
    return "cleared" if photo["clearance"] == "cleared" else "not_cleared"


def folder_decisions(conn: sqlite3.Connection) -> dict[str, str]:
    """For every folder, the decision that reaches it: 'excluded' when it or any folder above it is
    excluded, else 'not_cleared' (a folder never approves, 2026-11-02). One pass for the whole library, the
    same rule clearance_of follows photo by photo."""
    rows = {r["drive_id"]: (r["parent_id"], r["clearance"]) for r in db.rows(conn, "SELECT drive_id, parent_id, clearance FROM drive_folders")}
    out: dict[str, str] = {}

    def resolve(fid, depth=0):
        if fid is None or fid not in rows or depth > MAX_DEPTH:
            return "not_cleared"
        if fid in out:
            return out[fid]
        parent, own = rows[fid]
        above = resolve(parent, depth + 1)
        out[fid] = "excluded" if own == "excluded" or above == "excluded" else "not_cleared"
        return out[fid]
    for fid in rows:
        resolve(fid)
    return out


def decision_of(photo, decisions: dict[str, str]) -> str:
    """'cleared' | 'blocked' | 'excluded' | 'not_cleared', as clearance_of, from folder_decisions."""
    if photo["clearance"] == "blocked":
        return "blocked"
    folder = decisions.get(photo["folder_id"], "not_cleared")
    if folder == "excluded":
        return "excluded"
    return "cleared" if photo["clearance"] == "cleared" else folder


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
    # Never use on the one card is on every copy of the picture (Chris, 2026-11-02; library/copies.py)
    if photo["picture"] is not None and db.one(conn, "SELECT 1 FROM do_not_use d JOIN photos p ON p.drive_id = d.value "
                                                     "WHERE d.kind='photo' AND p.picture=?", (photo["picture"],)):
        return "another copy of this picture is on the do-not-use list"
    for f in folder_chain(conn, photo["folder_id"]):
        if db.one(conn, "SELECT 1 FROM do_not_use WHERE kind='folder' AND value=?", (f["drive_id"],)):
            return "its folder is on the do-not-use list"
    for c in credits_for(conn, photo):
        for kind, value in (("person", c["person_name"]), ("handle", c["handle"])):
            if value and db.one(conn, "SELECT 1 FROM do_not_use WHERE kind=? AND value=?", (kind, value.strip().lower())):
                return f"a person in it ({value}) is on the do-not-use list"
    return None


def do_not_use_photos(conn: sqlite3.Connection) -> set[int]:
    """The ids of every photo the do-not-use list covers, by the rule blocked_by_list follows photo by photo: the photo
    itself or a copy of its picture, a folder anywhere above it, or a person or handle credited on it or on a folder above
    it. One pass for the whole library (2026-11-02: a photo he had put on the list with Never use still waited on To review)."""
    listed = {(r["kind"], r["value"]) for r in db.rows(conn, "SELECT kind, value FROM do_not_use")}
    if not listed:
        return set()
    photo_ids = {v for k, v in listed if k == "photo"}
    pictures = {r["picture"] for r in db.rows(conn, "SELECT picture FROM photos WHERE picture IS NOT NULL AND drive_id IN "
                                                    "(SELECT value FROM do_not_use WHERE kind='photo')")}
    folder_ids = {v for k, v in listed if k == "folder"}
    if any(k in ("person", "handle") for k, _ in listed):
        for c in db.rows(conn, "SELECT scope, drive_id, person_name, handle FROM credits"):
            if any(v and (k, v.strip().lower()) in listed for k, v in (("person", c["person_name"]), ("handle", c["handle"]))):
                (photo_ids if c["scope"] == "photo" else folder_ids).add(c["drive_id"])
    parents = {r["drive_id"]: r["parent_id"] for r in db.rows(conn, "SELECT drive_id, parent_id FROM drive_folders")}
    memo: dict[str, bool] = {}

    def covered(fid) -> bool:
        """The folder, or one above it, is listed (folder_chain's walk, remembered for the folders it passes)."""
        path, hit = [], False
        while fid and fid in parents and len(path) < MAX_DEPTH:
            if fid in memo:
                hit = memo[fid]
                break
            path.append(fid)
            if fid in folder_ids:
                hit = True
                break
            fid = parents[fid]
        for f in path:
            memo[f] = hit
        return hit
    return {r["id"] for r in db.rows(conn, "SELECT id, drive_id, folder_id, picture FROM photos")
            if r["drive_id"] in photo_ids or r["picture"] in pictures or (folder_ids and covered(r["folder_id"]))}


# What keeps a photo off what Chris is offered to decide on (To review, the contact sheets), never off what he used
# (2026-11-08: his approval is final). A street number or a street name on a building he photographed is not a personal
# detail: they are public buildings and he holds releases for them (Chris, 2026-10-10). On a photo of people it is,
# because there the number says where somebody lives.
ADDRESS_DETAILS = frozenset({"house_number", "street_sign"})
# Chris, 2026-10-12: "If they're wearing a name badge or there's a name in the photo it's fine to
# use." A name badge, and the screens and documents the sorter flags at an event (a book cover, a
# program, a slide, signage: a name or a title), are not one. A plate, a house number or a street sign
# on a photo of people is: those say where somebody lives.
NAME_DETAILS = frozenset({"badge_name", "document", "screen"})


def blocking_details(details: list, subject: str | None) -> list:
    """The readable details that keep a photo he has not decided on off what he is offered: never a name
    (NAME_DETAILS); addresses are kept out of the answer for architecture, and only for architecture."""
    out = [d for d in details if d not in NAME_DETAILS]
    if subject != "architecture":
        return out
    return [d for d in out if d not in ADDRESS_DETAILS]


def building_blocked(cls: sqlite3.Row) -> str:
    """Why this building frame is not offered to him on a contact sheet, or "" (once he uses one, it is his).

    Chris, 2026-10-10, after the first building sheet: the architecture work is buildings, never
    rooms. No empty room, no bathroom, no closet, nothing residential. Bars are fine anywhere.
    The library's building work is largely commissioned real estate photography of apartments, so
    most of it is exactly what he ruled out. Fails closed: a frame sorted before these questions
    existed has space NULL and is not offered until it is sorted again.
    """
    from . import classify
    space = cls["space"]
    if space is None:
        return "not sorted for what the building frame shows"
    if cls["residential"] != 0:
        return "a building frame may not show somebody's home"
    if space in classify.BANNED_SPACES:
        return f"a building frame may not show a {space.replace('_', ' ')}"
    if space == "none":
        return "sorted as architecture but the frame names no part of a building"
    if cls["empty_room"] != 0:
        return "an empty room is not a building frame"
    return ""


def is_candidate(conn: sqlite3.Connection, photo_id: int) -> tuple[bool, str]:
    photo = db.one(conn, "SELECT * FROM photos WHERE id=?", (photo_id,))
    if photo is None:
        return False, "photo not in the library"
    if photo["trashed"]:
        return False, "photo is no longer in Drive"
    decision = clearance_of(conn, photo)
    if decision != "cleared":
        return False, {"blocked": "Chris marked it Never use", "excluded": "its folder is excluded",
                       "not_cleared": "not cleared yet"}[decision]
    why = blocked_by_list(conn, photo)
    if why:
        return False, why
    for c in credits_for(conn, photo):
        if c["consent"] == "no":
            return False, "the credits sheet says no consent"
    cls = db.one(conn, "SELECT method FROM classifications WHERE photo_id=?", (photo_id,))
    if cls is None or cls["method"] not in SORTED_METHODS:
        return False, "not sorted yet"
    return True, "ok"


def is_eligible(conn: sqlite3.Connection, photo_id: int) -> tuple[bool, str]:
    ok, why = is_candidate(conn, photo_id)
    if not ok:
        return ok, why
    if db.one(conn, "SELECT 1 FROM final_checks WHERE photo_id=?", (photo_id,)) is None:
        return False, "not given the final check yet"
    return True, "ok"


def needs_final_check(conn: sqlite3.Connection, photo_id: int) -> bool:
    """True when Claude's final check has not looked at this photo yet: the site build asks then, up to its limit."""
    return db.one(conn, "SELECT 1 FROM final_checks WHERE photo_id=?", (photo_id,)) is None


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
