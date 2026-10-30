"""Sorting the library, cheapest first, and the last look before a photo is posted.

1. folder_pass(): every photo gets a 'folder' row from its folder path and
   date (free): event work, architecture work, other, or no signal.
   method stays 'folder', so nothing is postable from this.
2. sort_pass(): a small Drive thumbnail (512 px, never the original) goes to
   a vision model with a strict JSON schema: event or building or other,
   which event if signage shows it, shot type, inside or outside, technical
   quality, how many people, readable personal details. Order: photos Chris already cleared, then event and
   architecture folders, newest first. Results are cached.
   The sorter is Ollama on the Mini when it has a vision model (free; Chris
   2026-10-09), otherwise Claude (claude-haiku-4-5, CLASSIFY_MODEL) under the
   monthly spend cap.
3. final_check(): Claude (claude-opus-5) looks once more at the one photo
   picked for a post, for personal details and the kind of occasion. Only a
   passing final check makes a photo postable (eligibility.py). No model judges
   anyone's age (Chris, 2026-10-15: his Approve is the check).

A refusal or an unreadable answer leaves the photo unchecked (never postable).
"""
from __future__ import annotations

import base64
import io
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Optional

from PIL import Image, ImageOps

from ..ai import spend
from ..core import config, db, secrets
from . import heuristics

DEFAULT_MODEL = "claude-haiku-4-5"
FINAL_MODEL = "claude-opus-5"
CAP_MESSAGE = ("The monthly AI cap is reached, or the next call would pass it (Keys page, AI, AI_MONTHLY_CAP_USD): Claude "
               "cannot look at a photo or write a caption until the cap is raised or the month turns, so nothing is drafted.")
FALLBACK_BETA = "server-side-fallback-2026-07-01"
OLLAMA_URL = "http://127.0.0.1:11434"
VISION_HINTS = ("llava", "vision", "-vl", "vl:", "qwen2.5vl", "qwen3-vl", "gemma3", "minicpm-v", "moondream", "bakllava", "granite3.2-vision", "mistral-small3")
THUMB_EDGE = 512
# portraits and headshots are one thing (Chris, 2026-10-12); rows sorted "headshot" before then read as portrait
# exhibition halls, vendors and booths are one thing too (Chris, 2026-10-12): rows sorted "booth" read as vendor_hall
# Chris, 2026-10-29: "It's only one of these: main stage, stage panel, stage, breakout, portrait, backstage, candid (if you
# can't identify where) and reception." The two building frames are the architecture subject's own. One vocabulary:
# the sorter's shot type, the final check's room and the title printed on a post are the same word.
# 2026-10-30, Chris: on a stage it is "Main Stage and stage panel (both)": every stage photo is main_stage unless it
# is a panel, which "typically are on the main stage, but need to be identified as a stage panel".
EVENT_SHOTS = ("main_stage", "stage_panel", "breakout", "portrait", "backstage", "candid", "reception")
SHOT_TYPES = EVENT_SHOTS + ("building_exterior", "building_interior")
DETAILS = ("badge_name", "vehicle_plate", "screen", "document", "house_number", "street_sign")
# What an architecture frame shows. Chris, 2026-10-10, after the first building sheet: the
# building work is buildings, never rooms. The library's architecture is largely commissioned
# real estate photography of apartments, so empty rooms, bathrooms, closets and residential
# interiors all have to be named to be kept out.
SPACES = ("exterior", "lobby", "atrium", "ballroom_or_event_space", "office", "retail", "bar",
          "corridor", "bathroom", "closet_or_utility", "none")
# Chris, 2026-10-10: nothing residential, and no empty rooms. Bars are fine anywhere. A bathroom
# or a closet is not a building frame wherever it is, so those two go by space; everything else
# turns on the `residential` answer, which catches a flat's hallway as surely as its bedroom.
BANNED_SPACES = frozenset({"bathroom", "closet_or_utility"})

SYSTEM = """You sort a photographer's archive of event and architecture work. For each photo, say what it shows, factually and briefly.
subject: "event" for conventions, conferences, galas, expos and similar gatherings; "architecture" for a building, its exterior or its interior shown as architecture; "other" for anything else.
event_kind: "fan" for a fan convention (comics, anime, gaming), "business" for a business, trade or political conference or a corporate gala; "wedding" for a wedding or its reception (a bride, a groom, a wedding party, a first dance, a cake); "private" for a party, a family or personal occasion, a religious ceremony or a portrait session with no event around it; "unknown" when the kind of gathering cannot be told.
Judge only what is visible.

Read the picture for text before you answer about it. Look at signs above doors, numbers on
facades, street signs, name badges, screens and papers. house_number means any street number on a
building, however small. street_sign means any road or street name. screen and document mean private
information readable on them (a message, an email, a form), never a book cover, a program, a slide,
signage or a title. Report them whenever they are readable; what is done with them is decided later.

space says which part of a building the photo shows, and it matters only when subject is
"architecture". When subject is "architecture" you must pick a real space and never "none": use
"exterior" for a building seen from outside, which is what most building photos are, and
otherwise name the room you are standing in. Use "none" only when subject is not "architecture".
residential: true when the space is somebody's home: a flat or house, inside or its own private
rooms. A hotel, an office, a shop, a bar or a venue is not residential.
empty_room: true when a room has no people in it and is unfurnished or nearly so.

Then judge the picture as a photographer would:
sharp: true when the main subject is in focus.
light: 1 (flat, blown or muddy) to 5 (light that makes the picture).
moment: 1 (nothing happening, a blink, a turned back) to 5 (a real expression or a moment worth
keeping). For a building, judge the composition instead.
shot_type: one of these, and nothing else (Chris, 2026-10-29):
main_stage: anyone on a stage, at a podium or performing: a speaker, a keynote, a performer, the full room; every stage
photo is main_stage unless it is a panel.
stage_panel: several people seated on a stage in conversation, a moderator and panelists; a panel is usually on the
main stage and is still stage_panel.
breakout: a session in a smaller room: an audience at tables or in rows, a presenter without a main stage.
portrait: a professional posed portrait only: the subject posed for the camera and lit for it, on a backdrop or in a
deliberate setting; a headshot or a posed group. A face in a frame is never a portrait; an unposed person is candid.
backstage: green room, wings, prep, rehearsal, mic check.
reception: dinner, drinks, networking, the gala floor, the dance floor.
candid: anything else at the event, when the place cannot be told.
building_exterior or building_interior: a building with no event in it (subject architecture).
costume: true when a person in the frame is in costume (cosplay).
summary: one short sentence saying what kind of picture this is and what is happening, in general terms (a
speaker at a podium; attendees at an expo booth; a building's entrance at dusk). Never a person's name, title
or identity, even when it is readable on a badge, a screen or a sign, and never the name of a company, a sponsor
or a venue: write "a speaker", "a politician", "a sponsor's logo". The event's name belongs only in
event_name_seen.
Return JSON only, matching the schema."""

KINDS = ("fan", "business", "wedding", "private", "unknown")
NOT_OFFERED_KINDS = ("wedding", "private")     # Event Caliber photographs conventions and conferences (Chris, 2026-10-11)

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "enum": ["event", "architecture", "other"]},
        "event_kind": {"type": "string", "enum": list(KINDS)},
        "event_name_seen": {"type": "string", "description": "an event name readable on signage or badges; empty if none"},
        "shot_type": {"type": "string", "enum": list(SHOT_TYPES)},
        "costume": {"type": "boolean", "description": "a person in the frame is in costume (cosplay)"},
        "view": {"type": "string", "enum": ["exterior", "interior", "none"]},
        "quality": {"type": "integer", "description": "technical quality 1 (unusable) to 5 (portfolio)"},
        "space": {"type": "string", "enum": list(SPACES), "description": "what an architecture frame shows"},
        "residential": {"type": "boolean", "description": "the space is somebody's home"},
        "empty_room": {"type": "boolean", "description": "a room with no people, unfurnished or nearly so"},
        "sharp": {"type": "boolean", "description": "the main subject is in focus"},
        "light": {"type": "integer", "description": "1 flat or blown, 5 light that makes the picture"},
        "moment": {"type": "integer", "description": "1 nothing happening, 5 a real moment; for a building, composition"},
        "people_count": {"type": "integer"},
        "personal_details": {"type": "array", "items": {"type": "string", "enum": list(DETAILS)}},
        "summary": {"type": "string", "description": "one short sentence on the kind of picture; no person's name, title or identity, no company or venue name"},
    },
    "required": ["subject", "event_kind", "event_name_seen", "shot_type", "costume", "view", "quality", "space",
                 "residential", "empty_room", "sharp", "light", "moment", "people_count",
                 "personal_details", "summary"],
    "additionalProperties": False,
}

# the rooms a post may name (render/design_samples.ROOM_WORDS gives each its words); Claude says which one a photo plainly
# shows, or none (2026-10-15: the sorter's shot type had put "After Dark" on a sunny garden)
ROOMS = EVENT_SHOTS                      # the room the final check names is the title printed on the post: the same eight words

FINAL_SYSTEM = """You are the last check before a photographer posts a photo publicly.
Answer four things about the photo only from what is visible:
personal_details: anything readable that identifies a private person or a home: a name on a badge, a vehicle plate, a screen or document with private information (a message, an email, a form, a medical or financial paper), a house number, a street sign. A book cover, a program, a slide, signage, a title or a name on its own is not private information. Empty when none.
shot_type: one of these, and nothing else (Chris, 2026-10-29):
main_stage: anyone on a stage, at a podium or performing: a speaker, a keynote, a performer, the full room; every stage
photo is main_stage unless it is a panel.
stage_panel: several people seated on a stage in conversation, a moderator and panelists; a panel is usually on the
main stage and is still stage_panel.
breakout: a session in a smaller room: an audience at tables or in rows, a presenter without a main stage.
portrait: a professional posed portrait only: the subject posed for the camera and lit for it, on a backdrop or in a
deliberate setting; a headshot or a posed group. A face in a frame is never a portrait; an unposed person is candid.
backstage: green room, wings, prep, rehearsal, mic check.
reception: dinner, drinks, networking, the gala floor, the dance floor.
candid: anything else at the event, when the place cannot be told.
building_exterior or building_interior: a building with no event in it (subject architecture).
costume: true when a person in the frame is in costume (cosplay).
event_kind: what kind of occasion the photo is from. fan for a fan convention (comics, anime, gaming); business for a business, trade or political conference or a corporate gala; wedding for a wedding or its reception (a bride, a groom, a wedding party, a first dance, a cake, wedding dress); private for a party, a family or personal occasion, a religious ceremony or a portrait session with no event around it; unknown only when nothing visible tells. A wedding is never business.
room: the one room of an event the photo plainly shows, printed on the post as its title; none unless it is plain from the photo itself. main_stage for someone speaking or presenting on a stage with the stage in view; backstage for behind the scenes of an event (the wings, the crew, the preparation); portraits for a posed, lit portrait of a speaker or guest; expo_floor for an exhibition hall, its booths or a vendor at one; after_dark for a reception, dinner or party that is plainly in the evening or at night; the_crowd for an audience or a room full of people in the moment; the_venue for the room or the building itself with no event in it. A daytime garden reception is not after_dark; a speech at a reception with no stage is not main_stage; when in doubt, none.
summary: one short sentence on what kind of picture it is; never a person's name, title or identity, and no company, sponsor or venue name.
Return JSON only, matching the schema."""

FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "personal_details": {"type": "array", "items": {"type": "string", "enum": list(DETAILS)}},
        "shot_type": {"type": "string", "enum": list(SHOT_TYPES)},
        "costume": {"type": "boolean", "description": "a person in the frame is in costume (cosplay)"},
        "event_kind": {"type": "string", "enum": list(KINDS)},
        "room": {"type": "string", "enum": [*ROOMS, "none"]},
        "summary": {"type": "string", "description": "the kind of picture; no person's name, title or identity, no company or venue name"},
    },
    "required": ["personal_details", "shot_type", "costume", "event_kind", "room", "summary"],
    "additionalProperties": False,
}


def set_shot_type(conn: sqlite3.Connection, photo_id: int, shot_type: str) -> bool:
    """One word for what the photo shows, everywhere it is read: the sorting row (the Photos tab,
    the candidates, the design labels) and the final check. False for a word that is not a shot type."""
    if shot_type not in SHOT_TYPES:
        return False
    conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=?", (shot_type, photo_id))
    conn.execute("UPDATE final_checks SET shot_type=? WHERE photo_id=?", (shot_type, photo_id))
    return True


@dataclass
class PassStats:
    done: int = 0
    failed: int = 0
    stopped: str = ""
    sorter: str = ""


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
                     "subject, classified_at) VALUES (?,?,?,?,?,?,?,?)",
                     (r["id"], "folder", None if g.is_event is None else int(g.is_event), g.event_name or None,
                      g.event_kind, orientation(r["width"], r["height"]), g.subject, now))
    return len(rows)


def queue(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Photos waiting for the sort pass: cleared folders first, then a round robin across
    events, newest first inside each.

    Strict newest-first ordering meant a bounded pass only ever saw the newest folders. On
    2026-10-10 the next 400 photos came from five events, all 2022 or later, while the 6,065
    photo CPAC 2016 and 2017 archive sat behind 52,000 others. A contact sheet of the best
    frames cannot come from a pool that narrow: report.PER_EVENT_CAP allows four per event,
    so five events can never yield thirty picks. Taking the newest from every event, then the
    second newest from every event, reaches the same photos in the end and gives a
    representative sample at any cut-off.
    """
    return db.rows(conn, """
        SELECT * FROM (
            SELECT p.*, c.convention_name AS folder_event, c.event_kind AS folder_kind, c.subject AS folder_subject,
                   (p.clearance = 'cleared' OR EXISTS (SELECT 1 FROM drive_folders f WHERE f.drive_id = p.folder_id AND f.clearance='cleared')) AS cleared_hint,
                   ROW_NUMBER() OVER (PARTITION BY COALESCE(NULLIF(c.convention_name, ''), p.folder_id)
                                      ORDER BY COALESCE(p.taken_at, p.modified_time) DESC) AS rank_in_event
            FROM photos p JOIN classifications c ON c.photo_id = p.id
            WHERE p.trashed = 0 AND (c.method = 'folder' OR c.rejudge = 1) AND p.thumbnail_link IS NOT NULL
              AND (c.subject IN ('event', 'architecture') OR p.clearance = 'cleared'
                   OR EXISTS (SELECT 1 FROM drive_folders f WHERE f.drive_id = p.folder_id AND f.clearance = 'cleared'))
        )
        ORDER BY cleared_hint DESC, rank_in_event ASC, COALESCE(taken_at, modified_time) DESC
        LIMIT ?""", (limit,))


def jpeg_bytes(data: bytes, edge: int = THUMB_EDGE) -> bytes:
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((edge, edge))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def jpeg_block(data: bytes, edge: int = THUMB_EDGE) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(jpeg_bytes(data, edge)).decode("ascii")}}


# ------------------------------------------------------------------------ sorters
class ClaudeSorter:
    method = "vision"

    def __init__(self, conn: sqlite3.Connection, *, agent: str = "scanner", client=None, model: str | None = None):
        self.conn = conn
        self.agent = agent
        self.model = model or config.getenv("CLASSIFY_MODEL") or DEFAULT_MODEL
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
        self.client = client

    def paid(self) -> bool:
        return True

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


VisionClassifier = ClaudeSorter   # the name the first build used


class OllamaSorter:
    """A local vision model through Ollama's HTTP API on the Mini. Free; read only on the photo bytes it is given."""
    method = "ollama"

    def __init__(self, model: str, *, base: str | None = None, post=None):
        self.model = model
        self.base = (base or config.getenv("OLLAMA_URL") or OLLAMA_URL).rstrip("/")
        if post is None:
            import requests
            post = lambda url, **kw: requests.post(url, timeout=300, **kw)  # noqa: E731
        self.post = post

    def paid(self) -> bool:
        return False

    def classify(self, thumb: bytes, hint: str) -> Optional[dict]:
        r = self.post(f"{self.base}/api/chat", json={
            "model": self.model, "stream": False, "format": SCHEMA, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": hint, "images": [base64.b64encode(jpeg_bytes(thumb)).decode("ascii")]}]})
        if getattr(r, "status_code", 200) >= 300:
            return None
        text = ((r.json() or {}).get("message") or {}).get("content") or ""
        data = json.loads(text) if text.strip() else None
        if not isinstance(data, dict) or any(k not in data for k in SCHEMA["required"]):
            return None
        return data


def ollama_model(get=None, *, base: str | None = None) -> Optional[str]:
    """The vision model to sort with: OLLAMA_MODEL if set, else the first installed model whose
    capabilities (or name) say it can see. None when Ollama is not answering or has none."""
    chosen = (config.getenv("OLLAMA_MODEL") or "").strip()
    if chosen:
        return chosen
    base = (base or config.getenv("OLLAMA_URL") or OLLAMA_URL).rstrip("/")
    try:
        if get is None:
            import requests
            get = lambda url, **kw: requests.get(url, timeout=5, **kw)  # noqa: E731
        names = [m.get("name") or m.get("model") for m in (get(f"{base}/api/tags").json().get("models") or [])]
    except Exception:  # noqa: BLE001 — Ollama off or absent: no local sorter
        return None
    for n in names:
        if n and any(h in n.lower() for h in VISION_HINTS):
            return n
    return None


def pick_sorter(conn: sqlite3.Connection, *, agent: str = "scanner"):
    """Ollama when a local vision model answers; else Claude when a key is set; else None."""
    if (config.getenv("CLASSIFY_BACKEND") or "auto").lower() in ("auto", "ollama"):
        model = ollama_model()
        if model:
            return OllamaSorter(model)
        if (config.getenv("CLASSIFY_BACKEND") or "").lower() == "ollama":
            return None
    if secrets.get_secret("ANTHROPIC_API_KEY"):
        return ClaudeSorter(conn, agent=agent)
    return None


NO_NAME = {"", "none", "null", "n/a", "na", "unknown", "false", "true", "nothing", "no name", "not visible"}


def event_name_seen(value) -> Optional[str]:
    """The event name the model actually read off signage, or None.

    A local model asked for "an event name readable on signage, empty if none" answers with the
    word rather than an empty string: 44 rows said "false", 8 said "none". Those were stored as
    the event name, so the contact sheet of 2026-10-10 had cells titled "false 2022", and
    report.best counted each junk string as its own event, defeating the per event cap.
    """
    name = str(value or "").strip()
    return None if name.lower() in NO_NAME else name


def _score_1_5(value) -> Optional[int]:
    return max(1, min(5, int(value))) if isinstance(value, int) else None


def _flag(value, default: bool) -> int:
    """A missing or unreadable answer takes the default, and every default here is the safe one."""
    return 1 if (default if not isinstance(value, bool) else value) else 0


def space_of(data: dict, subject: Optional[str]) -> Optional[str]:
    """Which part of a building the frame shows.

    The model answers shot_type reliably and space badly: asked both, it called two plain
    apartment exteriors "building_exterior" and then said the space was not a building at all
    (2026-10-10). Where shot_type and view agree that this is an outside view of a building, that
    is taken over a "none" from the space question. The correction only ever produces "exterior",
    which cannot smuggle in a bathroom, a closet or a living room: those still have to be named,
    and `residential` is asked separately anyway.
    """
    space = data.get("space") if data.get("space") in SPACES else None
    if subject != "architecture" or (space and space != "none"):
        return space
    if data.get("shot_type") == "building_exterior" or data.get("view") == "exterior":
        return "exterior"
    return space


def save_sort(conn: sqlite3.Connection, photo: sqlite3.Row, data: dict, method: str, model: str) -> None:
    subject = data.get("subject") if data.get("subject") in ("event", "architecture", "other") else None
    view = data.get("view") if data.get("view") in ("exterior", "interior") else None
    space = space_of(data, subject)
    conn.execute(
        "UPDATE classifications SET method=?, is_convention=?, subject=?, view=?, "
        "convention_name=COALESCE(?, convention_name), "
        "event_kind=CASE WHEN ?='unknown' THEN event_kind ELSE ? END, shot_type=?, costume=?, rejudge=0, quality=?, people_count=?, personal_details=?, "
        "space=?, residential=?, empty_room=?, sharp=?, light=?, moment=?, "
        "summary=?, model=?, classified_at=? WHERE photo_id=?",
        (method, int(subject == "event" and data.get("event_kind") not in NOT_OFFERED_KINDS), subject, view,
         event_name_seen(data.get("event_name_seen")),
         data.get("event_kind"), data.get("event_kind"), data.get("shot_type") if data.get("shot_type") in SHOT_TYPES else None,
         _flag(data.get("costume"), False), _score_1_5(data.get("quality")), int(data.get("people_count") or 0),
         json.dumps(data.get("personal_details") or []),
         space, _flag(data.get("residential"), True),   # unreadable counts as residential, so it is kept out
         _flag(data.get("empty_room"), True),      # and as empty, likewise
         _flag(data.get("sharp"), False),          # and as not sharp, so it does not rank
         _score_1_5(data.get("light")), _score_1_5(data.get("moment")),
         (data.get("summary") or "")[:300], model, db.utcnow(), photo["id"]))


save_vision = lambda conn, photo, data, model: save_sort(conn, photo, data, "vision", model)  # noqa: E731


def sort_pass(conn: sqlite3.Connection, fetch_thumb: Callable[[str], bytes], *, limit: int = 200,
              sorter=None, classifier=None, log=None, budget_seconds: Optional[float] = None,
              clock: Callable[[], float] = time.monotonic) -> PassStats:
    """`budget_seconds` ends the pass in time for the next hourly run (the free sorter takes about
    half a minute a photo, so 500 photos was four hours in which nothing else of the scanner's ran,
    2026-10-11); what is left is sorted next hour, approved folders first."""
    stats = PassStats()
    sorter = sorter or classifier or pick_sorter(conn)
    if sorter is None:
        stats.stopped = "no sorter: Ollama has no vision model and no ANTHROPIC_API_KEY is set"
        return stats
    stats.sorter = f"{sorter.method}:{sorter.model}"
    started = clock()
    for photo in queue(conn, limit):
        if sorter.paid() and spend.cap_reached(conn):
            stats.stopped = "monthly AI spend cap reached"
            break
        if budget_seconds is not None and clock() - started >= budget_seconds:
            stats.stopped = f"the {int(budget_seconds // 60)} minute budget for this run; the rest next hour"
            break
        hint = (f"Folder suggests: {photo['folder_subject'] or 'nothing'}, "
                f"{photo['folder_event'] or 'no event name'} ({photo['folder_kind'] or 'unknown'}).")
        try:
            data = sorter.classify(fetch_thumb(photo["drive_id"]), hint)
        except Exception as e:  # noqa: BLE001 — one bad photo never stops the pass
            stats.failed += 1
            if log:
                log.warning("sort %s failed: %s", photo["drive_id"], e)
            continue
        if not data:
            stats.failed += 1
            continue
        save_sort(conn, photo, data, sorter.method, sorter.model)
        stats.done += 1
    return stats


vision_pass = sort_pass   # the name the first build used


# ------------------------------------------------------------------------ the final check
def look(conn: sqlite3.Connection, image: bytes, *, client=None, agent: str = "content") -> Optional[dict]:
    """Claude's final look at one picture: the answer (personal_details, shot_type,
    event_kind, summary), or None (no key, cap reached, refused, unreadable). Paid through the one till.
    final_check stores it for a library photo; the website's uploaded hero (site/hero.py) keeps its own."""
    from ..core import runner
    if spend.cap_reached(conn):
        # 2026-10-12: a silent None here left a morning with no draft and nothing said; the Agents page says it now
        runner.record_error_once(conn, agent, "ai_cap", CAP_MESSAGE)
        return None
    model = config.getenv("FINAL_CHECK_MODEL") or FINAL_MODEL
    if client is None:
        if not secrets.get_secret("ANTHROPIC_API_KEY"):
            runner.record_error_once(conn, agent, "no_ai_key", "No Anthropic key (Keys page, AI): Claude cannot look at a photo, so nothing is drafted.")
            return None
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    held = spend.reserve(conn, agent, model)       # 8.2 (2026-10-13): the cap is held while the call is in flight
    if held is None:
        runner.record_error_once(conn, agent, "ai_cap", CAP_MESSAGE)
        return None
    try:
        response = client.beta.messages.create(
            model=model, max_tokens=4000, betas=[FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": FINAL_SCHEMA}},
            system=[{"type": "text", "text": FINAL_SYSTEM}],
            messages=[{"role": "user", "content": [jpeg_block(image, 1568), {"type": "text", "text": "Check this photo."}]}],
        )
    except Exception:
        spend.release(conn, held)
        raise
    u = response.usage
    answered = getattr(response, "model", None) or model
    spend.record(conn, agent, answered, int(u.input_tokens or 0), int(u.output_tokens or 0), "final check", reservation=held)
    if response.stop_reason == "refusal":
        return None
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        return None
    data = json.loads(text)
    data["model_used"] = answered
    return data


def final_check(conn: sqlite3.Connection, photo_id: int, image: bytes, *, client=None, agent: str = "content") -> Optional[dict]:
    """Claude's last look at one photo before it may be posted. Writes final_checks and returns the
    answer, or None (refused, cap reached, unreadable): then the photo stays unpostable."""
    data = look(conn, image, client=client, agent=agent)
    if data is None:
        return None
    answered = data.get("model_used") or config.getenv("FINAL_CHECK_MODEL") or FINAL_MODEL
    shot = data.get("shot_type") if data.get("shot_type") in SHOT_TYPES else None
    kind = data.get("event_kind") if data.get("event_kind") in KINDS else "unknown"
    room = data.get("room") if data.get("room") in ROOMS else None        # "none", missing or unknown: no room is printed
    # possible_minor is a NOT NULL column from before 2026-10-15; no model is asked and nothing reads it (no age gate)
    conn.execute("INSERT INTO final_checks (photo_id, possible_minor, personal_details, summary, model, checked_at, shot_type, event_kind, room) "
                 "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET possible_minor=excluded.possible_minor, "
                 "personal_details=excluded.personal_details, summary=excluded.summary, model=excluded.model, "
                 "checked_at=excluded.checked_at, shot_type=excluded.shot_type, event_kind=excluded.event_kind, room=excluded.room",
                 (photo_id, 0, json.dumps(data.get("personal_details") or []),
                  (data.get("summary") or "")[:300], answered, db.utcnow(), shot, kind, room))
    if shot:
        # Claude's word beats the local sorter's guess (2026-10-11: a stage shot called a portrait)
        conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=? AND COALESCE(shot_type, '') != ?", (shot, photo_id, shot))
    if kind != "unknown":
        # and what kind of occasion it is (2026-10-11: a wedding on the website as the hero)
        conn.execute("UPDATE classifications SET event_kind=?, is_convention=? WHERE photo_id=?",
                     (kind, 0 if kind in NOT_OFFERED_KINDS else 1, photo_id))
    return data
