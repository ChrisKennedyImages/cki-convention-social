"""Build and keep the photo inventory: one full pass, then the Changes API.

full_inventory():  record the Changes start token FIRST (so nothing that
                   changes during the pass is missed), list every folder,
                   list every image file Drive can render (not trashed,
                   My Drive and shared drives), and upsert drive_folders and
                   photos. Folder paths are resolved from the parent chain.
incremental():     read the changes since the stored token and apply them:
                   new or edited images are upserted, trashed or removed
                   ones are marked trashed (never deleted from the table, so
                   a clearance decision survives a restore).

RAW camera files are skipped: they cannot be posted as they are, and Drive
does not render most of them. They are counted so the report can say so.
Nothing here writes to Drive; the reader can only GET.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..core import db, settings
from .api import FOLDER_MIME, DriveReader

CHANGES_TOKEN_KEY = "drive.changes_token"
INVENTORY_AT_KEY = "drive.inventory_at"
RAW_EXTENSIONS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".raf", ".orf",
                  ".rw2", ".pef", ".srw", ".x3f", ".3fr", ".erf", ".kdc", ".mrw", ".raw", ".iiq", ".rwl"}
POSTABLE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "image/tiff"}


@dataclass
class ScanStats:
    folders: int = 0
    images: int = 0
    skipped_raw: int = 0
    skipped_unrenderable: int = 0
    trashed: int = 0
    changes: int = 0
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        return (f"folders={self.folders} images={self.images} skipped_raw={self.skipped_raw} "
                f"skipped_unrenderable={self.skipped_unrenderable} trashed={self.trashed} changes={self.changes}")


def skip_reason(f: dict) -> str | None:
    """'raw' | 'unrenderable' | None (keep)."""
    name = str(f.get("name") or "")
    mime = str(f.get("mimeType") or "")
    if PurePosixPath(name.lower()).suffix in RAW_EXTENSIONS or "raw" in mime or mime.startswith("image/x-"):
        return "raw"
    if mime not in POSTABLE_MIMES:
        return "unrenderable"
    if f.get("hasThumbnail") is False:
        return "unrenderable"
    return None


def resolve_paths(folders: dict[str, dict], roots: dict[str, str]) -> dict[str, str]:
    """folder id -> 'Top/Sub/Leaf'. roots maps My Drive's and each shared drive's id to its display name."""
    cache: dict[str, str] = {}

    def path_of(fid: str, depth: int = 0) -> str:
        if fid in cache:
            return cache[fid]
        if fid in roots:
            return roots[fid]
        f = folders.get(fid)
        if f is None or depth > 64:
            return "(outside the library)"
        parents = f.get("parents") or []
        parent = path_of(parents[0], depth + 1) if parents else "(no parent)"
        cache[fid] = f"{parent}/{f.get('name', '')}"
        return cache[fid]

    return {fid: path_of(fid) for fid in folders}


def _meta(f: dict) -> dict:
    m = f.get("imageMediaMetadata") or {}
    try:
        w, h = int(m.get("width") or 0), int(m.get("height") or 0)
    except (TypeError, ValueError):
        w = h = 0
    rot = m.get("rotation")
    if rot in (1, 3):  # quarter turns: the shown photo is the other way round
        w, h = h, w
    camera = " ".join(x for x in (m.get("cameraMake"), m.get("cameraModel")) if x)
    return {"width": w or None, "height": h or None, "rotation": rot, "taken_at": m.get("time") or None,
            "camera": camera or None}


def upsert_folder(conn: sqlite3.Connection, f: dict, path: str | None, now: str) -> None:
    parents = f.get("parents") or []
    conn.execute(
        "INSERT INTO drive_folders (drive_id, name, parent_id, path, modified_time, first_seen_at, last_seen_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(drive_id) DO UPDATE SET name=excluded.name, parent_id=excluded.parent_id, "
        "path=COALESCE(excluded.path, drive_folders.path), modified_time=excluded.modified_time, last_seen_at=excluded.last_seen_at",
        (f["id"], f.get("name") or "", parents[0] if parents else None, path, f.get("modifiedTime"), now, now))


def upsert_photo(conn: sqlite3.Connection, f: dict, now: str) -> None:
    """Insert or refresh one image. Clearance is never touched here: only Chris sets it."""
    parents = f.get("parents") or []
    m = _meta(f)
    conn.execute(
        "INSERT INTO photos (drive_id, name, mime_type, md5, size_bytes, folder_id, width, height, rotation, taken_at, camera, "
        "description, thumbnail_link, modified_time, trashed, first_seen_at, last_seen_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?) ON CONFLICT(drive_id) DO UPDATE SET name=excluded.name, mime_type=excluded.mime_type, "
        "md5=excluded.md5, size_bytes=excluded.size_bytes, folder_id=excluded.folder_id, width=excluded.width, height=excluded.height, "
        "rotation=excluded.rotation, taken_at=excluded.taken_at, camera=excluded.camera, description=excluded.description, "
        "thumbnail_link=excluded.thumbnail_link, modified_time=excluded.modified_time, trashed=0, last_seen_at=excluded.last_seen_at",
        (f["id"], f.get("name") or "", f.get("mimeType"), f.get("md5Checksum"), int(f.get("size") or 0) or None,
         parents[0] if parents else None, m["width"], m["height"], m["rotation"], m["taken_at"], m["camera"],
         f.get("description"), f.get("thumbnailLink"), f.get("modifiedTime"), now, now))


def _ensure_parent_known(conn: sqlite3.Connection, folder_id: str | None, now: str) -> None:
    """photos.folder_id references drive_folders; a folder created after the full pass gets a stub row."""
    if folder_id and not db.one(conn, "SELECT 1 FROM drive_folders WHERE drive_id=?", (folder_id,)):
        conn.execute("INSERT INTO drive_folders (drive_id, name, first_seen_at, last_seen_at) VALUES (?,?,?,?)",
                     (folder_id, "(new folder)", now, now))


def refresh_counts(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE drive_folders SET image_count = (SELECT COUNT(*) FROM photos p WHERE p.folder_id = drive_folders.drive_id AND p.trashed = 0)")


def full_inventory(conn: sqlite3.Connection, reader: DriveReader) -> ScanStats:
    stats = ScanStats()
    token = reader.start_page_token()            # first: changes during the pass are caught next time
    root = reader.root_id()
    roots = {root: "My Drive"}
    try:
        roots.update({d["id"]: f"Shared drive: {d.get('name', '')}" for d in reader.shared_drives()})
    except Exception as e:  # noqa: BLE001 — a personal account may have none; never fatal
        stats.notes.append(f"shared drives not listed: {type(e).__name__}")
    folders = {f["id"]: f for f in reader.folders()}
    paths = resolve_paths(folders, roots)
    # the whole listing is read from Drive BEFORE the transaction opens: walking a large library inside
    # it held SQLite's write lock for the whole walk, so every other agent and the dashboard got
    # "database is locked", and a network error late in the walk threw the pass away (the Mini, 2026-10-10)
    images = list(reader.images())
    now = db.utcnow()
    conn.execute("BEGIN")
    try:
        for fid, f in folders.items():
            upsert_folder(conn, f, paths.get(fid), now)
            stats.folders += 1
        for f in images:
            reason = skip_reason(f)
            if reason == "raw":
                stats.skipped_raw += 1
                continue
            if reason:
                stats.skipped_unrenderable += 1
                continue
            parent = (f.get("parents") or [None])[0]
            if parent in roots:
                parent = None            # a photo loose at the top of My Drive has no folder row
                f = {**f, "parents": []}
            _ensure_parent_known(conn, parent, now)
            upsert_photo(conn, f, now)
            stats.images += 1
        # anything not seen in this pass is gone from Drive (or now RAW-only): mark it trashed
        cur = conn.execute("UPDATE photos SET trashed=1 WHERE last_seen_at < ? AND trashed=0", (now,))
        stats.trashed = cur.rowcount
        refresh_counts(conn)
        settings.set(conn, CHANGES_TOKEN_KEY, token)
        settings.set(conn, INVENTORY_AT_KEY, now)
        settings.set(conn, "drive.inventory_stats", json.dumps(stats.__dict__))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return stats


def incremental(conn: sqlite3.Connection, reader: DriveReader) -> ScanStats:
    stats = ScanStats()
    token = settings.get(conn, CHANGES_TOKEN_KEY)
    if not token:
        return full_inventory(conn, reader)
    changes, new_token = reader.changes(token)
    now = db.utcnow()
    conn.execute("BEGIN")
    try:
        for ch in changes:
            stats.changes += 1
            f = ch.get("file") or {}
            fid = ch.get("fileId") or f.get("id")
            if ch.get("removed") or f.get("trashed"):
                cur = conn.execute("UPDATE photos SET trashed=1, last_seen_at=? WHERE drive_id=?", (now, fid))
                stats.trashed += cur.rowcount
                continue
            mime = str(f.get("mimeType") or "")
            if mime == FOLDER_MIME:
                upsert_folder(conn, f, None, now)
                stats.folders += 1
            elif mime.startswith("image/"):
                reason = skip_reason(f)
                if reason:
                    stats.skipped_raw += reason == "raw"
                    stats.skipped_unrenderable += reason != "raw"
                    continue
                _ensure_parent_known(conn, (f.get("parents") or [None])[0], now)
                upsert_photo(conn, f, now)
                stats.images += 1
        refresh_counts(conn)
        settings.set(conn, CHANGES_TOKEN_KEY, new_token)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return stats
