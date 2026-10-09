"""Sorting the library, cheapest first.

1. folder_pass(): every photo gets a 'folder' row from its folder path and
   date (free). possible_minor stays NULL, so nothing is eligible from this.
2. vision_pass(): a small Drive thumbnail (512 px, never the original) goes to
   Claude with a strict JSON schema: convention or not, which event if
   signage shows it, shot type, technical quality, orientation, how many
   people, readable personal details, and whether anyone could be a minor.
   Order: photos Chris already cleared, then event-looking folders. Results
   are cached in `classifications` (method 'vision') and never redone unless
   asked. Every call passes the monthly spend cap first and is recorded.

Model: claude-haiku-5-5 by default (CLASSIFY_MODEL overrides). The brief asks
for cheap classification on small thumbnails; this is a sorting pass Chris
reviews, not copy that goes out. A refusal or an unreadable answer leaves the
photo unchecked (never eligible).
"""
from __future__ import annotations

import base64
import io
import json
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from PIL import Image, ImageOps

from ..ai import spend
from ..core import config, db, secrets
from . import heuristics

DEFAULT_MODEL = "claude-haiku-5-5"
THUMB_EDGE = 512
SHOT_TYPES = ("cosplay_portrait", "portrait", "group", "candid", "stage_panel", "vendor_hall", "booth",
              "backstage", "dinner_reception", "headshot", "crowd", "venue", "other")

SYSTEM = """You sort a photographer's archive. For each photo, say what it shows, factually and briefly.
Judge only what is visible. When unsure whether anyone could be under 18, answer true.
List personal details only when they are actually readable: a name on a badge, a vehicle plate, a screen or document with personal information.
Return JSON only, matching the schema."""

SCHEMA = {
    "type": "object",
    "properties": {
        "is_convention": {"type": "boolean", "description": "a convention, conference, expo, gala or similar organised event"},
        "event_kind": {"type": "string", "enum": ["fan", "business", "unknown"]},
        "event_name_seen": {"type": "string", "description": "an event name readable on signage or badges; empty if none"},
        "shot_type": {"type": "string", "enum": list(SHOT_TYPES)},
        "quality": {"type": "integer", "description": "technical quality 1 (unusable) to 5 (portfolio)"},
        "people_count": {"type": "integer"},
        "possible_minor": {"type": "boolean"},
        "personal_details": {"type": "array", "items": {"type": "string", "enum": ["badge_name", "vehicle_plate", "screen", "document"]}},
        "summary": {"type": "string", "description": "one short sentence"},
    },
    "required": ["is_convention", "event_kind", "event_name_seen", "shot_type", "quality", "people_count",
                 "possible_minor", "personal_details", "summary"],
    "additionalProperties": False,
}


@dataclass
class PassStats:
    done: int = 0
    failed: int = 0
    stopped: str = ""


def orientation(w, h) -> Optional[str]:
    if not w or not h:
        return None
    r = w / h
    return "square" if 0.95 <= r <= 1.05 else ("landscape" if r > 1 else "portrait")


def folder_pass(conn: sqlite3.Connection) -> int:
    """A free 'folder' row for every photo that has no row yet."""
    rows = db.rows(conn, "SELECT p.id, p.taken_at, p.width, p.height, f.path FROM photos p "
                         "LEFT JOIN drive_folders f ON f.drive_id = p.folder_id "
                         "WHERE p.trashed=0 AND p.id NOT IN (SELECT photo_id FROM classifications)")
    now = db.utcnow()
    for r in rows:
        g = heuristics.guess(r["path"] or "", r["taken_at"])
        conn.execute("INSERT INTO classifications (photo_id, method, is_convention, convention_name, event_kind, orientation, "
                     "classified_at) VALUES (?,?,?,?,?,?,?)",
                     (r["id"], "folder", None if g.is_event is None else int(g.is_event), g.event_name or None,
                      g.event_kind, orientation(r["width"], r["height"]), now))
    return len(rows)


def queue(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Photos waiting for the vision pass: cleared first, then event-looking folders, newest first."""
    return db.rows(conn, """
        SELECT p.*, c.convention_name AS folder_event, c.event_kind AS folder_kind,
               (p.clearance = 'cleared' OR EXISTS (SELECT 1 FROM drive_folders f WHERE f.drive_id = p.folder_id AND f.clearance='cleared')) AS cleared_hint
        FROM photos p JOIN classifications c ON c.photo_id = p.id
        WHERE p.trashed = 0 AND c.method = 'folder' AND p.thumbnail_link IS NOT NULL
          AND (c.is_convention = 1 OR p.clearance = 'cleared'
               OR EXISTS (SELECT 1 FROM drive_folders f WHERE f.drive_id = p.folder_id AND f.clearance = 'cleared'))
        ORDER BY cleared_hint DESC, COALESCE(p.taken_at, p.modified_time) DESC
        LIMIT ?""", (limit,))


def jpeg_block(data: bytes, edge: int = THUMB_EDGE) -> dict:
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((edge, edge))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


class VisionClassifier:
    def __init__(self, conn: sqlite3.Connection, *, agent: str = "scanner", client=None, model: str | None = None):
        self.conn = conn
        self.agent = agent
        self.model = model or config.getenv("CLASSIFY_MODEL") or DEFAULT_MODEL
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
        self.client = client

    def classify(self, thumb: bytes, hint: str) -> Optional[dict]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [jpeg_block(thumb), {"type": "text", "text": hint}]}],
        )
        u = response.usage
        spend.record(self.conn, self.agent, getattr(response, "model", None) or self.model,
                     int(u.input_tokens or 0), int(u.output_tokens or 0), "classify")
        if response.stop_reason == "refusal":
            return None
        text = next((b.text for b in response.content if b.type == "text"), None)
        return json.loads(text) if text else None


def save_vision(conn: sqlite3.Connection, photo: sqlite3.Row, data: dict, model: str) -> None:
    q = data.get("quality")
    conn.execute(
        "UPDATE classifications SET method='vision', is_convention=?, convention_name=COALESCE(NULLIF(?, ''), convention_name), "
        "event_kind=CASE WHEN ?='unknown' THEN event_kind ELSE ? END, shot_type=?, quality=?, people_count=?, personal_details=?, "
        "possible_minor=?, summary=?, model=?, classified_at=? WHERE photo_id=?",
        (int(bool(data.get("is_convention"))), (data.get("event_name_seen") or "").strip(), data.get("event_kind"),
         data.get("event_kind"), data.get("shot_type"), max(1, min(5, int(q))) if isinstance(q, int) else None,
         int(data.get("people_count") or 0), json.dumps(data.get("personal_details") or []),
         1 if data.get("possible_minor", True) else 0, (data.get("summary") or "")[:300], model, db.utcnow(), photo["id"]))


def vision_pass(conn: sqlite3.Connection, fetch_thumb: Callable[[str], bytes], *, limit: int = 200,
                classifier: Optional[VisionClassifier] = None, log=None) -> PassStats:
    stats = PassStats()
    if classifier is None:
        if not secrets.get_secret("ANTHROPIC_API_KEY"):
            stats.stopped = "no ANTHROPIC_API_KEY"
            return stats
        classifier = VisionClassifier(conn)
    for photo in queue(conn, limit):
        if spend.cap_reached(conn):
            stats.stopped = "monthly AI spend cap reached"
            break
        hint = f"Folder suggests: {photo['folder_event'] or 'nothing'} ({photo['folder_kind'] or 'unknown'})."
        try:
            data = classifier.classify(fetch_thumb(photo["thumbnail_link"]), hint)
        except Exception as e:  # noqa: BLE001 — one bad photo never stops the pass
            stats.failed += 1
            if log:
                log.warning("classify %s failed: %s", photo["drive_id"], e)
            continue
        if not data:
            stats.failed += 1
            continue
        save_vision(conn, photo, data, classifier.model)
        stats.done += 1
    return stats
