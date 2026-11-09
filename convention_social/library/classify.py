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
3. final_check(): Claude (claude-opus-5) looks once more, at the full photo, at each photo picked for a post: its
   label, the room the post prints, the kind of occasion and any readable detail. It labels; it never keeps out a
   photo Chris used (2026-11-08: "No one can override MY approvals and that is a law"; "Yes, override everything").
   A refusal or an empty answer is a check with no labels, not a veto. No model judges anyone's age.

Both read the house brief first (house_brief.py): what the company photographs and the labels, in one place.
"""
from __future__ import annotations

import base64
import io
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from PIL import Image, ImageOps

from .. import house_brief
from ..ai import names, spend
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
# Chris, 2026-11-08: "Candid, Backstage, Green room, Panels, Portraits, Main stage, Breakouts, Awards, Event building, and
# Reception kept." The labels, their words and what each shows live in the house brief (house_brief.LABELS), which every
# model is told before its task. One vocabulary: the sorter's shot type, the final check's room and the label printed on
# a post are the same key. It replaces the eight titles of 2026-10-29.
SHOT_TYPES = house_brief.KEYS
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

# What kind of occasion a photo is from, for the sorter and the final check alike. Chris, 2026-11-08: a studio or backstage
# portrait is the company's own work, never private for being a portrait ("we provide portraits at many of our events for
# LinkedIn profiles or backstage for speakers or many reasons"), and a nonprofit's public event is the company's event (a
# charity walk the final check had called private; "a great heart walk photo"). "private" had also taken in "a portrait
# session with no event around it", a line no ruling of his said.
KIND_RULE = ("fan for a fan convention (comics, anime, gaming); business for a business, trade, association or political "
             "conference, a corporate gala, reception or award dinner, a nonprofit's public event (a charity walk or run, a "
             "fundraiser, a heart walk or an Alzheimer's walk), and the company's own portrait work: a studio or backstage "
             "portrait or headshot (a person posed for the camera and lit for it on a backdrop, often with colored gels, no "
             "event in view) is business unless the photo itself shows a wedding, never private for being a portrait; "
             "wedding for a wedding or its reception (a bride, a groom, a wedding party, a first dance, a cake, a wedding "
             "dress); private for a family or personal occasion (a family gathering, a birthday), a private party or a "
             "religious ceremony; unknown only when nothing visible tells. A wedding "
             "is never business.")

SYSTEM = f"""You sort the company's photo archive of event and architecture work. For each photo, say what it shows, factually and briefly.
subject: "event" for conventions, conferences, galas, expos, fundraisers, charity walks and similar gatherings, and for every posed portrait or headshot, which is the company's portrait work at events; "architecture" for a building, its exterior or its interior shown as architecture; "other" for anything else.
event_kind: {KIND_RULE}
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
shot_type: the label the photo shows, by its key, one of the labels in the brief above and nothing else.
costume: true when a person in the frame is in costume (cosplay).
summary: one short sentence saying what kind of picture this is and what is happening, in general terms (a
speaker at a podium; attendees at an expo booth; a building's entrance at dusk). Never a person's name, title
or identity, even when it is readable on a badge, a screen or a sign, and never the name of a company, a sponsor
or a venue: write "a speaker", "a politician", "a sponsor's logo". The event's name belongs only in
event_name_seen.
Return JSON only, matching the schema."""

KINDS = ("fan", "business", "wedding", "private", "unknown")
# What the sorter keeps off To review and the contact sheets (is_convention 0), for the photos Chris has not decided on;
# never a reason to keep out a photo he used (2026-11-08: his approval is final).
NOT_OFFERED_KINDS = ("wedding", "private")

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

# the label a post may print (render/design_samples.ROOMS gives each its words); Claude says which one a photo plainly
# shows, or none (2026-10-15: the sorter's shot type had put "After Dark" on a sunny garden). Every label is a room since
# 2026-11-08, Event building included: the venue with no event in it is no longer the architecture subject's alone.
ROOMS = SHOT_TYPES

FINAL_SYSTEM = f"""You look at a photo Chris approved, before the company posts it, and label it. Your answers word and arrange the post; none keeps the photo out.
Answer from what is visible:
personal_details: anything readable that identifies a private person or a home: a name on a badge, a vehicle plate, a screen or document with private information (a message, an email, a form, a medical or financial paper), a house number, a street sign. A book cover, a program, a slide, signage, a title or a name on its own is not private information. Empty when none.
shot_type: the label the photo shows, by its key, one of the labels in the brief above and nothing else.
event_kind: what kind of occasion the photo is from. {KIND_RULE}
room: the label the photo plainly shows, by its key, printed on the post as its title; none unless it is plain from the photo itself. A speech at a reception with no stage is reception, not main_stage; when in doubt, none.
summary: one short sentence on what kind of picture it is; never a person's name, title or identity, and no company, sponsor or venue name.
Return JSON only, matching the schema."""

FINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "personal_details": {"type": "array", "items": {"type": "string", "enum": list(DETAILS)}},
        "shot_type": {"type": "string", "enum": list(SHOT_TYPES)},
        "event_kind": {"type": "string", "enum": list(KINDS)},
        "room": {"type": "string", "enum": [*ROOMS, "none"]},
        "summary": {"type": "string", "description": "the kind of picture; no person's name, title or identity, no company or venue name"},
    },
    "required": ["personal_details", "shot_type", "event_kind", "room", "summary"],
    "additionalProperties": False,
}


def set_shot_type(conn: sqlite3.Connection, photo_id: int, shot_type: str) -> bool:
    """Chris's word for what the photo shows, everywhere it is read: the sorting row (the Photos tab, the candidates,
    the design labels) and the final check, the room printed on a post with it. It is his (shot_by 'chris'), so a later
    look by a model keeps it (2026-11-02: "Most backstage images are called candid"). False for a word that is not a
    shot type."""
    if shot_type not in SHOT_TYPES:
        return False
    conn.execute("UPDATE classifications SET shot_type=?, shot_by='chris' WHERE photo_id=?", (shot_type, photo_id))
    conn.execute("UPDATE final_checks SET shot_type=?, room=? WHERE photo_id=?",
                 (shot_type, shot_type if shot_type in ROOMS else None, photo_id))
    return True


def his_shot_type(conn: sqlite3.Connection, photo_id: int) -> Optional[str]:
    """The kind of shot Chris set on this photo, if he set one."""
    row = db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=? AND shot_by='chris'", (photo_id,))
    return row["shot_type"] if row else None


# Chris, 2026-11-08, after an award plaque came out as a portrait: the photos labelled before Awards and Green room were
# labels are judged again ("yes" to re-labelling, about $4). Found by what the sorter or the final check already said a
# photo shows; a photo whose label he set himself is never touched.
RELABEL_WORDS = re.compile(r"\b(?:awards?|plaques?|troph(?:y|ies)|certificates?|green ?rooms?)\b", re.I)


@dataclass
class Relabel:
    ids: list
    by_label: dict
    checked: int                    # how many of them carry a final check, which --mark clears
    per_photo_usd: Optional[float]
    undercounts: bool               # the price comes from rows that did not count the cached prompt (before 2026-11-09)
    marked: bool = False

    @property
    def usd(self) -> Optional[float]:
        return None if self.per_photo_usd is None else round(len(self.ids) * self.per_photo_usd, 2)


def relabel(conn: sqlite3.Connection, *, mark: bool = False) -> Relabel:
    """The photos whose sort or final check mentions an award, a plaque, a trophy, a certificate or a green room, by the
    label they carry now, and what judging them again would cost at the sorter's own measured price (its rows in the
    till over the last two weeks): from the sorts that read the cached prompt when the till has any, else from the older
    rows, which under-count it (ai/spend.py). `mark` sends them to the sorter's queue (classifications.rejudge, the road
    the 2026-10-29 re-sort took), approved photos first, through the till and CLASSIFY_BUDGET like any sort, and clears
    their final checks: the sorter sees a 512-pixel thumbnail and would overwrite the label the final check gave from the
    full photo, so the next draft that picks one, or the next site build, checks it again on the full photo."""
    rows = db.rows(conn, "SELECT c.photo_id, c.shot_type, c.summary, f.summary AS checked, f.photo_id AS has_check "
                         "FROM classifications c JOIN photos p ON p.id = c.photo_id LEFT JOIN final_checks f "
                         "ON f.photo_id = c.photo_id WHERE p.trashed = 0 AND c.method IN ('ollama', 'vision') "
                         "AND COALESCE(c.shot_by, '') != 'chris' AND c.rejudge = 0")
    hits = [r for r in rows if RELABEL_WORDS.search(f"{r['summary'] or ''} {r['checked'] or ''}")]
    by_label: dict = {}
    for r in hits:
        by_label[r["shot_type"] or "none"] = by_label.get(r["shot_type"] or "none", 0) + 1
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    sorts = "FROM api_usage WHERE provider = 'anthropic' AND agent = 'scanner' AND detail LIKE '% classify' AND cost_usd > 0 AND ts >= ?"
    # a sort that read the cached prompt: the steady price, a pass being one sort after another (one that wrote it, after a
    # pause of five minutes, costs about four times as much and comes once a pass)
    counted = db.one(conn, f"SELECT AVG(cost_usd) AS a {sorts} AND detail LIKE '% cache_read=%' "
                           "AND detail NOT LIKE '% cache_read=0 %'", (since,))["a"]
    older = db.one(conn, f"SELECT AVG(cost_usd) AS a {sorts}", (since,))["a"]
    price = counted if counted is not None else older
    found = Relabel([r["photo_id"] for r in hits], by_label, sum(1 for r in hits if r["has_check"] is not None),
                    None if price is None else float(price), counted is None and older is not None)
    if mark and found.ids:
        conn.executemany("UPDATE classifications SET rejudge = 1 WHERE photo_id = ?", [(i,) for i in found.ids])
        conn.executemany("DELETE FROM final_checks WHERE photo_id = ?", [(i,) for i in found.ids])
        found.marked = True
    return found


# 2026-11-06: sorting every folder is about $88, more than was left of the month's cap. The paid sorter always stops with a
# tenth of the cap left ($15 of $150), so the daily drafts, captions and the scout keep running.
SORT_RESERVE_SHARE = 0.10
# CLASSIFY_BUDGET: what the paid sorter may spend in a stretch of days, as "20 from 2026-11-06 until 2026-11-19" (Chris,
# 2026-11-06: Nic's and the shared galleries first, then up to $20, "and then until the 19th"). Blank: no such limit.
BUDGET = re.compile(r"^\s*\$?(\d+(?:\.\d+)?)\s+from\s+(\d{4}-\d{2}-\d{2})\s+until\s+(\d{4}-\d{2}-\d{2})\s*$", re.I)


def sort_reserve() -> float:
    return max(0.0, config.get_config().ai_monthly_cap_usd) * SORT_RESERVE_SHARE


def budget_stop(conn: sqlite3.Connection, today: Optional[date] = None) -> Optional[str]:
    """Why the paid sorter stops for CLASSIFY_BUDGET now, or None. Inside its days it spends at most the amount, counted
    from the sorter's own rows in the till; after them the limit is gone. A value it cannot read stops the sorting (fail
    closed) and says so."""
    raw = (config.getenv("CLASSIFY_BUDGET") or "").strip()
    if not raw:
        return None
    m = BUDGET.match(raw)
    if not m:
        return f'CLASSIFY_BUDGET is not readable ("{raw}"); write it as "20 from 2026-11-06 until 2026-11-19". Nothing sorted.'
    usd, since, until = float(m.group(1)), date.fromisoformat(m.group(2)), date.fromisoformat(m.group(3))
    today = today or datetime.now(timezone.utc).date()
    if not since <= today < until:
        return None
    spent = db.one(conn, "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM api_usage WHERE provider = 'anthropic' "
                         "AND agent = 'scanner' AND ts >= ?", (since.isoformat(),))["c"]
    if spent >= usd:
        return f"the ${usd:.0f} for sorting from {since.isoformat()} is spent (${spent:.2f}); sorting goes on {until.isoformat()}"
    return None


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
    """Photos waiting for the sort pass: the ones Chris approved first, then a round robin across
    events, newest first inside each.

    Strict newest-first ordering meant a bounded pass only ever saw the newest folders. On
    2026-10-10 the next 400 photos came from five events, all 2022 or later, while the 6,065
    photo CPAC 2016 and 2017 archive sat behind 52,000 others. A contact sheet of the best
    frames cannot come from a pool that narrow: report.PER_EVENT_CAP allows four per event,
    so five events can never yield thirty picks. Taking the newest from every event, then the
    second newest from every event, reaches the same photos in the end and gives a
    representative sample at any cut-off.

    Every folder is sorted (Chris, 2026-11-06: "Every folder should have been sorted as discussed (not phone
    folders)"). The queue used to take only photos whose folder name the folder pass read as event or building work,
    so 18,374 pictures sat unsorted and never reached To review, among them every one of Nic's shared galleries
    ("Event photography/Speakers" names no conference). The phone backup is not in the inventory at all (drive/scan).
    The galleries shared with the account come first after his approved photos (2026-11-06: "the shared folders from my
    brother never are in the sorting").
    """
    return db.rows(conn, """
        SELECT * FROM (
            SELECT p.*, c.convention_name AS folder_event, c.event_kind AS folder_kind, c.subject AS folder_subject,
                   (p.clearance = 'cleared') AS cleared_hint, (f.shared_by IS NOT NULL) AS shared_hint,
                   ROW_NUMBER() OVER (PARTITION BY COALESCE(NULLIF(c.convention_name, ''), p.folder_id)
                                      ORDER BY COALESCE(p.taken_at, p.modified_time) DESC) AS rank_in_event
            FROM photos p JOIN classifications c ON c.photo_id = p.id LEFT JOIN drive_folders f ON f.drive_id = p.folder_id
            WHERE p.trashed = 0 AND (c.method = 'folder' OR c.rejudge = 1) AND p.thumbnail_link IS NOT NULL
        )
        ORDER BY cleared_hint DESC, shared_hint DESC, rank_in_event ASC, COALESCE(taken_at, modified_time) DESC
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
            system=house_brief.system(SYSTEM, cache=True),
            messages=[{"role": "user", "content": [jpeg_block(thumb), {"type": "text", "text": hint}]}],
        )
        spend.record_response(self.conn, self.agent, response, self.model, "classify")
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
            "messages": [{"role": "system", "content": house_brief.prompt(SYSTEM)},
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
    return None if name.lower() in NO_NAME or not names.is_name(name) else name


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
        "event_kind=CASE WHEN ?='unknown' THEN event_kind ELSE ? END, shot_type=CASE WHEN shot_by='chris' THEN shot_type ELSE ? END, "
        "costume=?, rejudge=0, quality=?, people_count=?, personal_details=?, "
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
        if sorter.paid() and spend.cap_reached(conn, about_to_spend=sort_reserve()):
            stats.stopped = (f"stopped with ${sort_reserve():.2f} of the monthly AI cap left for drafts and captions; "
                             "the rest is sorted when the cap resets")
            break
        if sorter.paid() and (why := budget_stop(conn)):
            stats.stopped = why
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
# what a refusal or an empty answer leaves: no detail, no label, no room, the kind not told
NO_LABELS = {"personal_details": [], "shot_type": None, "event_kind": "unknown", "room": "none", "summary": ""}


def look(conn: sqlite3.Connection, image: bytes, *, client=None, agent: str = "content") -> Optional[dict]:
    """Claude's final look at one picture: the answer (personal_details, shot_type, event_kind, room, summary), or None
    when it could not look (no key, the cap reached). A refusal or an empty answer is NO_LABELS: Claude said nothing,
    which labels nothing and vetoes nothing (2026-11-08: his approval is final). Paid through the one till.
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
            system=house_brief.system(FINAL_SYSTEM, cache=True),   # the brief and the task, the same on every check: cached
            messages=[{"role": "user", "content": [jpeg_block(image, 1568), {"type": "text", "text": "Check this photo."}]}],
        )
    except Exception:
        spend.release(conn, held)
        raise
    answered, _ = spend.record_response(conn, agent, response, model, "final check", reservation=held)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return {**NO_LABELS, "model_used": answered, "refused": True}
    data = json.loads(text)
    data["model_used"] = answered
    return data


def final_check(conn: sqlite3.Connection, photo_id: int, image: bytes, *, client=None, agent: str = "content") -> Optional[dict]:
    """Claude's last look at one photo before it is posted: its labels, written to final_checks, and the answer. None
    when Claude could not look (no key, the cap reached): then the photo waits for a check, as a post waits for its
    caption. What the answer says never keeps the photo out (eligibility.py)."""
    data = look(conn, image, client=client, agent=agent)
    if data is None:
        return None
    answered = data.get("model_used") or config.getenv("FINAL_CHECK_MODEL") or FINAL_MODEL
    shot = data.get("shot_type") if data.get("shot_type") in SHOT_TYPES else None
    kind = data.get("event_kind") if data.get("event_kind") in KINDS else "unknown"
    room = data.get("room") if data.get("room") in ROOMS else None        # "none", missing or unknown: no room is printed
    his = his_shot_type(conn, photo_id)
    if his:                                    # Chris set the kind of shot: his word stands, and is the room printed
        shot, room = his, (his if his in ROOMS else None)
    # the check's own row: what it saw, the label and the room the post prints. Its readable details and kind of occasion
    # are words for the photo, kept where they are read (classifications; the hero's card), not here (migration 0102).
    # possible_minor is a NOT NULL column from before 2026-10-15; no model is asked and nothing reads it (no age gate)
    conn.execute("INSERT INTO final_checks (photo_id, possible_minor, summary, model, checked_at, shot_type, room) "
                 "VALUES (?,?,?,?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET possible_minor=excluded.possible_minor, "
                 "summary=excluded.summary, model=excluded.model, checked_at=excluded.checked_at, "
                 "shot_type=excluded.shot_type, room=excluded.room",
                 (photo_id, 0, (data.get("summary") or "")[:300], answered, db.utcnow(), shot, room))
    if shot:
        # Claude's word beats the local sorter's guess (2026-10-11: a stage shot called a portrait)
        conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=? AND COALESCE(shot_type, '') != ? "
                     "AND COALESCE(shot_by, '') != 'chris'", (shot, photo_id, shot))
    if kind != "unknown":
        # and what kind of occasion it is, a label: it words the post and keeps To review to the work, and never keeps out a
        # photo Chris used (2026-11-08)
        conn.execute("UPDATE classifications SET event_kind=?, is_convention=? WHERE photo_id=?",
                     (kind, 0 if kind in NOT_OFFERED_KINDS else 1, photo_id))
    return data
