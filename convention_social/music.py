"""Music for the reels: the tracks Chris adds on the dashboard, each with where it came from.

Chris, 2026-10-11: "we need to find good music". Nothing here fetches music: Chris picks a track
from a source he has the right to use for posts on Instagram and Facebook, uploads it on the
Library page and records the source and what it allows. A 3D reel uses the newest active track
with a complete record; with none, the reel is silent. Fails closed: no record, no music.

Chris, 2026-11-08: "We will always just grab new music with its docs from pixabay moving forward". A track is added
only with its pixabay.com page as its source (from_pixabay), its terms still recorded. A reel in one of the ten looks
(render/reel_looks.py) takes an active track that suits its look (music_tracks.looks), the one the reels used least
lately first, started on its own second (start_s) and, when it is locked to the looks' beat, played at grid/bpm
(for_look); what the learner found about each track breaks a tie.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence
from urllib.parse import urlparse

from .core import config, db

ALLOWED = (".mp3", ".m4a", ".aac", ".wav", ".mp4")    # .mp4: phones and Macs save audio-only tracks that way too
MAX_BYTES = 25 * 1024 * 1024
FIELDS = ("title", "artist", "source", "terms")
PIXABAY = "pixabay.com"


class Refused(ValueError):
    pass


def from_pixabay(source: str) -> bool:
    """True for a link to a page on pixabay.com, the one place new tracks come from (Chris, 2026-11-08)."""
    u = urlparse((source or "").strip())
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and (host == PIXABAY or host.endswith("." + PIXABAY)) and len(u.path) > 1


def folder() -> Path:
    return config.get_config().data_root / "music"


def add(conn: sqlite3.Connection, filename: str, data: bytes, *, title: str, artist: str, source: str, terms: str,
        looks: Sequence[str] = (), start_s: float = 0.0, bpm: float = 0.0, grid: float = 0.0) -> int:
    """A track kept with its record. `looks`, `start_s`, `bpm` and `grid`: what a reel look needs of it (the migration
    of 2026-11-08 set them for the Pixabay tracks then on the Mini); a track with no looks suits none."""
    from .render import reel_looks
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
    if not from_pixabay(source):
        raise Refused("every track comes from Pixabay: its source must be the track's pixabay.com page")
    unknown = [look for look in looks if look not in reel_looks.LOOKS]
    if unknown:
        raise Refused(f"no reel look named {', '.join(unknown)}")
    stem = re.sub(r"[^a-z0-9]+", "-", f"{artist} {title}".lower()).strip("-")[:60] or "track"
    name = f"{stem}-{db.utcnow()[:19].replace(':', '').replace('-', '')}{ext}"
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / name).write_bytes(data)
    if not has_sound(folder() / name):
        (folder() / name).unlink()
        raise Refused("ffmpeg finds no sound in that file")
    return db.insert(conn, "music_tracks", file=name, added_at=db.utcnow(), **{k: v.strip() for k, v in record.items()},
                     looks=json.dumps(list(looks)), start_s=float(start_s), bpm=float(bpm), grid=float(grid))


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


def usable(t) -> bool:
    """The track's record is complete and its file is still there."""
    return all((t[k] or "").strip() for k in FIELDS) and (folder() / t["file"]).is_file()


def current(conn: sqlite3.Connection) -> Optional[Path]:
    """The newest active track whose record is complete and whose file is still there."""
    for t in db.rows(conn, "SELECT * FROM music_tracks WHERE active=1 ORDER BY id DESC"):
        if usable(t):
            return folder() / t["file"]
    return None


@dataclass(frozen=True)
class LookTrack:
    """A track as a reel look plays it: the file, the second it starts on, and the rate (grid/bpm for a track locked to
    the looks' beat, else 1)."""
    path: Path
    start: float
    rate: float

    @property
    def file(self) -> str:
        return self.path.name


def looks_of(t) -> list[str]:
    """The looks a track suits (music_tracks.looks); none when the record cannot be read."""
    try:
        looks = json.loads(t["looks"] or "[]")
    except (TypeError, ValueError):
        return []
    return [str(x) for x in looks] if isinstance(looks, list) else []


def as_played(t) -> LookTrack:
    """The track as a look plays it: from its own start second, at grid/bpm when it is locked to the looks' beat."""
    grid, bpm = float(t["grid"] or 0), float(t["bpm"] or 0)
    return LookTrack(folder() / t["file"], float(t["start_s"] or 0), grid / bpm if grid > 0 and bpm > 0 else 1.0)


def last_used(conn: sqlite3.Connection) -> dict[str, str]:
    """{track file: when a draft last carried it} from the drafts themselves (rule_report.music), every road."""
    return {r["music"]: r["at"] or "" for r in db.rows(conn, "SELECT json_extract(rule_report, '$.music') AS music, MAX(created_at) AS at "
                                                            "FROM content_queue WHERE json_extract(rule_report, '$.music') IS NOT NULL "
                                                            "GROUP BY music")}


def for_look(conn: sqlite3.Connection, look: str, weight: Callable[[str], float] = lambda file: 1.0) -> Optional[LookTrack]:
    """The track a reel in `look` takes: an active, complete track that suits the look, the one the drafts carried least
    lately first (a track never carried before any other); between equals, the one the learner weighs higher
    (`weight(file)`), then the newest. None when no track suits the look."""
    fits = [t for t in db.rows(conn, "SELECT * FROM music_tracks WHERE active=1 ORDER BY id DESC") if usable(t) and look in looks_of(t)]
    if not fits:
        return None
    last = last_used(conn)
    best = min(fits, key=lambda t: (last.get(t["file"], ""), -weight(t["file"]), -t["id"]))
    return as_played(best)


def played_as(conn: sqlite3.Connection, file: Optional[str]) -> Optional[LookTrack]:
    """The track a reel was made with, by its file (a draft's rule_report.music), while its record and file are here."""
    t = db.one(conn, "SELECT * FROM music_tracks WHERE file=?", (file or "",))
    return as_played(t) if t is not None and usable(t) else None


UNKNOWN_ARTIST = ("unknown", "none", "n/a", "na")


def artist_known(artist: Optional[str]) -> bool:
    """False for what Chris types when he has no artist (every field must be filled before a track is used):
    nothing, a dash or other punctuation, "unknown", "none", "n/a". Chris, 2026-10-14: "i dont ho the artist is.
    its a meat musics free track" (a free track from Meta's Sound Collection)."""
    a = (artist or "").strip().lower()
    return a not in UNKNOWN_ARTIST and any(ch.isalnum() for ch in a)


def credit(conn: sqlite3.Connection, file: Optional[str]) -> str:
    """The words under a reel that name its track, from the record of the file the reel was made with (a draft's
    rule_report.music, the samples' about.json music): "title, artist" when the artist is known, else
    "title (source)" with the source as Chris recorded it. The file's own name when its record is gone; "" when
    the reel was made with no track. Chris, 2026-10-14, of a reel the dashboard played muted: "where is the music
    on the insta posts!!!!": the line says what plays, so a silent player is never mistaken for a silent reel."""
    if not file:
        return ""
    t = db.one(conn, "SELECT title, artist, source FROM music_tracks WHERE file=?", (file,))
    if t is None:
        return Path(file).stem
    return f"{t['title']}, {t['artist']}" if artist_known(t["artist"]) else f"{t['title']} ({t['source']})"


def set_active(conn: sqlite3.Connection, tid: int, active: bool) -> None:
    conn.execute("UPDATE music_tracks SET active=? WHERE id=?", (1 if active else 0, tid))
