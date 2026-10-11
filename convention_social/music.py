"""Music for the reels: the tracks Chris adds on the dashboard, each with where it came from.

Chris, 2026-10-11: "we need to find good music". Nothing here fetches music: Chris picks a track
from a source he has the right to use for posts on Instagram and Facebook, uploads it on the
Library page and records the source and what it allows. A reel uses the newest active track
with a complete record; with none, the reel is silent. Fails closed: no record, no music.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

from .core import config, db

ALLOWED = (".mp3", ".m4a", ".aac", ".wav", ".mp4")    # .mp4: phones and Macs save audio-only tracks that way too
MAX_BYTES = 25 * 1024 * 1024
FIELDS = ("title", "artist", "source", "terms")


class Refused(ValueError):
    pass


def folder() -> Path:
    return config.get_config().data_root / "music"


def add(conn: sqlite3.Connection, filename: str, data: bytes, *, title: str, artist: str, source: str, terms: str) -> int:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise Refused(f"only {', '.join(ALLOWED)} files")
    if not data:
        raise Refused("the file is empty")
    if len(data) > MAX_BYTES:
        raise Refused("the file is over 25 MB")
    record = {"title": title, "artist": artist, "source": source, "terms": terms}
    missing = [k for k in FIELDS if not (record[k] or "").strip()]
    if missing:
        raise Refused("every track needs " + ", ".join(missing) + " before a reel can use it")
    stem = re.sub(r"[^a-z0-9]+", "-", f"{artist} {title}".lower()).strip("-")[:60] or "track"
    name = f"{stem}-{db.utcnow()[:19].replace(':', '').replace('-', '')}{ext}"
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / name).write_bytes(data)
    if not has_sound(folder() / name):
        (folder() / name).unlink()
        raise Refused("ffmpeg finds no sound in that file")
    return db.insert(conn, "music_tracks", file=name, added_at=db.utcnow(), **{k: v.strip() for k, v in record.items()})


def has_sound(path: Path) -> bool:
    """True when ffmpeg reads an audio stream in the file (the encoder that mixes it into reels)."""
    import subprocess
    from .render.reel import ffmpeg_path
    try:
        probe = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60).stderr
    except (OSError, subprocess.SubprocessError):
        return False
    return "Audio:" in probe


def tracks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return db.rows(conn, "SELECT * FROM music_tracks ORDER BY id DESC")


def current(conn: sqlite3.Connection) -> Optional[Path]:
    """The newest active track whose record is complete and whose file is still there."""
    for t in db.rows(conn, "SELECT * FROM music_tracks WHERE active=1 ORDER BY id DESC"):
        if all((t[k] or "").strip() for k in FIELDS) and (folder() / t["file"]).is_file():
            return folder() / t["file"]
    return None


def set_active(conn: sqlite3.Connection, tid: int, active: bool) -> None:
    conn.execute("UPDATE music_tracks SET active=? WHERE id=?", (1 if active else 0, tid))
