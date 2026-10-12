"""The website's main photo from Chris's phone (2026-10-12: "That photo is just on my phone I think").

An upload on the Photos tab (Approved: Site hero from your phone) is kept under DATA_ROOT/site, re-encoded
so it carries no camera data, and IS the hero of the next site build: his own photo, chosen by him, for his
own site (2026-10-12: "That's still not the ... landing page photo I uploaded on the dashboard"). Claude
looks at it once per file, for the alt text and a note on the card (anyone who may be under 18, a readable
plate, a wedding), and never holds it back. It wins over a library pick while it is here; Remove hands the
choice back. Sending, removing or picking a hero on the dashboard publishes the site by itself.

The same evening ("the home page image is not the correct photo ... do what you can without needing me to
respond") the photo he had sent in the chat, a wide stage panorama, was re-encoded the same way and shipped
with the code as site/hero.jpg. It is the hero whenever nothing has been sent from the phone, checked by
Claude in the same way. A phone upload wins over it; Remove takes the upload away and the shipped photo is
the hero again. SITE_HERO_SHIPPED points elsewhere (the tests point it at nothing).
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from ..core import config, db, settings

FILE = "hero-upload.jpg"
SHIPPED_FILE = "hero.jpg"
CHECK_KEY = "site.hero_upload_check"
MIN_WIDTH = 1200
MAX_BYTES = 40 * 1024 * 1024


class Refused(ValueError):
    pass


def path() -> Path:
    return config.get_config().data_root / "site" / FILE


def shipped() -> Path:
    """The photo that came with the code (site/hero.jpg, the panorama Chris sent on 2026-10-12)."""
    override = config.getenv("SITE_HERO_SHIPPED")
    return Path(override).expanduser() if override else config.REPO_ROOT / "site" / SHIPPED_FILE


def _uploaded() -> bool:
    return path().is_file() and path().stat().st_size > 0


def source() -> Optional[Path]:
    """The file in use: the one sent from the phone, else the one shipped with the code, else none."""
    if _uploaded():
        return path()
    if shipped().is_file():
        return shipped()
    return None


def present() -> bool:
    return source() is not None


def save(data: bytes) -> Path:
    """Keep the upload as a plain JPEG of its pixels only (no camera data, no GPS). The old verdict goes."""
    if not data:
        raise Refused("the file is empty")
    if len(data) > MAX_BYTES:
        raise Refused("the file is over 40 MB")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except (UnidentifiedImageError, OSError, ValueError):
        raise Refused("not a photo file (send a JPEG or PNG)")
    im = ImageOps.exif_transpose(im).convert("RGB")
    if im.width < MIN_WIDTH:
        raise Refused(f"too small for the hero: {im.width} pixels wide, {MIN_WIDTH} or more needed (send the original, not a preview)")
    out = path()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    im.save(tmp, "JPEG", quality=92, optimize=True)
    tmp.replace(out)
    return out


def remove(conn: sqlite3.Connection) -> bool:
    """Take the phone upload away (the shipped photo, if any, is the hero again). Its verdict goes
    with it; one verdict is kept at a time, so Claude looks at the shipped photo again on the next build."""
    was = _uploaded()
    if was:
        path().unlink()
        settings.set(conn, CHECK_KEY, "")
    return was


def image() -> Image.Image:
    return Image.open(source()).convert("RGB")


def _sha() -> str:
    return hashlib.sha256(source().read_bytes()).hexdigest()


def record(conn: sqlite3.Connection) -> Optional[dict]:
    """Claude's verdict on the file that is here now, or None when it has not looked at this one."""
    raw = settings.get(conn, CHECK_KEY)
    if not raw or not present():
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    return rec if rec.get("sha") == _sha() else None


def checked(conn: sqlite3.Connection, look: Optional[Callable[[bytes], Optional[dict]]] = None) -> tuple[bool, str]:
    """(usable, note). Chris, 2026-10-12: "That's still not the ... landing page photo I uploaded on the
    dashboard." The photo he sends is the hero, full stop: his own photo, chosen by him, for his own
    site. Claude's look is still asked once per file, for the alt text and a note on the card (what it
    saw; anyone who may be under 18, a readable plate), never to hold the photo back. Without a look
    (no key, the cap) the photo is used all the same and the card says Claude has not looked yet."""
    from ..library import classify, eligibility
    if not present():
        return False, "no upload"
    rec = record(conn)
    if rec is None and look is not None:
        data = look(source().read_bytes())
        if data is not None:
            details = eligibility.blocking_details(list(data.get("personal_details") or []), "event")
            kind = data.get("event_kind") if data.get("event_kind") in classify.KINDS else "unknown"
            notes = []
            if data.get("possible_minor", True):
                notes.append("someone in it may be under 18")
            if details:
                notes.append("it shows " + ", ".join(map(str, details)))
            if kind in classify.NOT_OFFERED_KINDS:
                notes.append(eligibility.NOT_OFFERED_KIND_WHY)
            why = "your photo; Claude notes: " + "; ".join(notes) if notes else "your photo, seen by Claude"
            rec = {"sha": _sha(), "why": why, "kind": kind, "shot_type": data.get("shot_type") or "",
                   "summary": (data.get("summary") or "")[:200], "at": db.utcnow(), "notes": notes}
            settings.set(conn, CHECK_KEY, json.dumps(rec))
    if rec is None:
        return True, "your photo; Claude has not looked at it yet"
    return True, rec["why"]


def status(conn: sqlite3.Connection) -> dict:
    """For the Photos tab: whether an upload is here, its size, and what Claude said about it."""
    if not present():
        return {"present": False, "source": ""}
    with Image.open(source()) as im:
        size = im.size
    rec = record(conn)
    return {"present": True, "source": "phone" if _uploaded() else "code", "width": size[0], "height": size[1],
            "checked": rec is not None, "notes": list((rec or {}).get("notes") or []),
            "why": rec["why"] if rec else "the site's hero; Claude looks at it during the publish, for the alt text and a note here"}
