"""Credits and consent, from the one Google Sheet Chris keeps.

The sheet (CREDITS_SHEET_ID in .env) has a header row and these columns, in
any order, matched by header name (case does not matter):

  Photo or folder   a Drive link or id of one photo, or of a whole folder
  Name              the person's name (used only for the do-not-use list)
  Handle            the credit to print, exactly as written, e.g. @handle
  Consent           yes / no (blank means not recorded)
  Notes             anything; ignored by the suite

The sheet is read through Drive's export (a read; the sheet is never
edited). Each sync replaces the credits table with what the sheet says, so
the sheet stays the single source. A row whose link matches nothing in the
library is reported back, not guessed at.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass, field

from ..core import db

ID_IN_LINK = re.compile(r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_-]{2,})")
BARE_ID = re.compile(r"^[A-Za-z0-9_-]{2,}$")   # any id-shaped cell; the library lookup is the real check
HEADERS = {"photo or folder": "ref", "photo": "ref", "folder": "ref", "link": "ref", "name": "name",
           "handle": "handle", "credit": "handle", "consent": "consent"}


@dataclass
class SyncResult:
    rows: int = 0
    matched: int = 0
    unmatched: list[str] = field(default_factory=list)


def drive_id_of(cell: str) -> str | None:
    cell = (cell or "").strip()
    m = ID_IN_LINK.search(cell)
    if m:
        return m.group(1)
    return cell if BARE_ID.match(cell) else None


def parse(text: str) -> list[dict]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    cols = {i: HEADERS.get(h.strip().lower()) for i, h in enumerate(rows[0])}
    out = []
    for n, raw in enumerate(rows[1:], start=2):
        rec = {"sheet_row": n}
        for i, val in enumerate(raw):
            key = cols.get(i)
            if key and key not in rec:
                rec[key] = val.strip()
        if any(rec.get(k) for k in ("ref", "name", "handle")):
            out.append(rec)
    return out


def consent_word(value: str) -> str:
    v = (value or "").strip().lower()
    return "yes" if v in ("yes", "y", "true", "1", "x") else ("no" if v in ("no", "n", "false", "0") else "unknown")


def sync(conn: sqlite3.Connection, csv_text: str) -> SyncResult:
    res = SyncResult()
    records = parse(csv_text)
    now = db.utcnow()
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM credits")
        for r in records:
            res.rows += 1
            did = drive_id_of(r.get("ref", ""))
            scope = None
            if did and db.one(conn, "SELECT 1 FROM photos WHERE drive_id=?", (did,)):
                scope = "photo"
            elif did and db.one(conn, "SELECT 1 FROM drive_folders WHERE drive_id=?", (did,)):
                scope = "folder"
            if not scope:
                res.unmatched.append(f"row {r['sheet_row']}: {r.get('ref') or '(no link)'}")
                continue
            db.insert(conn, "credits", scope=scope, drive_id=did, person_name=r.get("name") or None,
                      handle=r.get("handle") or None, consent=consent_word(r.get("consent", "")),
                      sheet_row=r["sheet_row"], synced_at=now)
            res.matched += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return res
