"""Caption drafting with Claude: a photo goes in, one JSON draft per network comes out.

The model sees one downscaled photo plus the facts the suite knows (event,
whether the company was the official photographer, the credit Chris
recorded, the services) and returns strict JSON through output_config. The
prompt states the rules, but ai/copy_rules.py is the gate, not the prompt.

Model: claude-opus-5-5 (override with AI_MODEL), effort set explicitly, the
server-side refusal fallback on. Every call is metered through ai/spend.py
at the model that actually answered, and no call is made once the monthly
cap is reached. With no ANTHROPIC_API_KEY, or AI_MODEL=template,
`TemplateDrafter` writes plain deterministic captions so the whole pipeline
runs in dry run.
"""
from __future__ import annotations

import base64
import io
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

from PIL import Image, ImageOps

from ..core import config, secrets
from . import spend

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_IMAGE_EDGE = 1024
NETWORKS = ("instagram", "facebook", "pinterest")

SYSTEM_PROMPT = """You write social posts for an event and convention photography company, in the photographer's own voice. The company covers whole events: backstage and green rooms, breakout sessions, before, during and evening events, dinners, portraits, exhibition halls and vendors, and it can deliver approved images to attendees, staff, speakers and presenters right at the event. It works fan conventions (comic, anime, gaming, cosplay) and business and political conferences.

Write plain, short sentences. Use commas and periods, never a dash of any kind. No hype words, no emojis, no exclamation marks in a row. Describe only what the photo shows and what the facts give you.

Hard rules:
1. Never state or hint at a price, a rate, a discount or a package cost. The call to action is to request a quote for an event.
2. Never say or imply the company is a convention's official photographer, partner or sponsor, or affiliated with it, unless the facts say official: yes.
3. Never name a person. If the facts give a credit, use the credit exactly as written and nothing else about who they are. If there is no credit, do not identify anyone.
4. Never mention a badge name, a plate, a screen or any personal detail you can read in the photo.
5. Never promise anything the facts do not list as a service.
6. Hashtags only on Instagram and Pinterest, at most five, relevant to the event type and photography.

Separately, in "privacy", list anything visible that could identify a private person beyond their face: a readable badge name, a vehicle plate, a screen or document with personal details. In "possible_minor", say true if anyone in the photo could be under 18.

Return JSON only, matching the schema you are given."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "photo_summary": {"type": "string", "description": "One sentence: what the photo shows."},
        "captions": {
            "type": "object",
            "properties": {n: {"type": "string"} for n in NETWORKS},
            "required": list(NETWORKS),
            "additionalProperties": False,
        },
        "possible_minor": {"type": "boolean"},
        "privacy": {"type": "array", "items": {"type": "string", "enum": ["badge_name", "vehicle_plate", "screen", "document"]}},
    },
    "required": ["photo_summary", "captions", "possible_minor", "privacy"],
    "additionalProperties": False,
}


@dataclass
class PostFacts:
    brand_name: str
    event_name: str = ""
    event_kind: str = "unknown"          # fan | business | unknown
    official: bool = False               # only True when Chris confirmed it for this event
    credit: str = ""                     # e.g. "@handle", exactly as recorded in the credits sheet
    services: tuple[str, ...] = ()
    shot_type: str = ""
    quote_link: str = ""
    subject: str = "event"               # event | architecture


@dataclass
class Draft:
    captions: dict[str, str]
    photo_summary: str
    model: str
    possible_minor: bool = True          # fail closed until a model says otherwise
    privacy: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict = field(default_factory=dict)


class Drafter(Protocol):
    name: str

    def draft(self, facts: PostFacts, photo: Path) -> Draft: ...


class DraftError(RuntimeError):
    pass


class SpendCapReached(DraftError):
    pass


def image_block(path: Path, edge: int = MAX_IMAGE_EDGE) -> dict:
    """Downscale, re-encode as JPEG with no metadata, base64 for the API."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((edge, edge))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii")}}


def user_text(facts: PostFacts) -> str:
    return "\n".join([
        f"Company name: {facts.brand_name}",
        f"Event: {facts.event_name or 'unknown, do not name one'}",
        f"Event type: {facts.event_kind}",
        f"Official photographer for this event: {'yes' if facts.official else 'no'}",
        f"Credit: {facts.credit or 'none, identify no one'}",
        f"Shot type: {facts.shot_type or 'unknown'}",
        ("Subject: a building or venue from the photographer's architecture work. Say what the building shows, never name "
         "the owner, the address or the client, and connect it to how carefully events in buildings like it get covered."
         if facts.subject == "architecture" else "Subject: event photography"),
        f"Services: {'; '.join(facts.services) or 'event photography'}",
        f"Quote link: {facts.quote_link or 'none'}",
        "Write one caption per network: instagram (short, up to five hashtags at the end), "
        "facebook (one or two short paragraphs, no hashtags), pinterest (one descriptive sentence plus up to five hashtags).",
    ])


_DASH_SPELLED = re.compile(r"[ \t]*(?:(?:&|\\)[nm]dash;?|\n[nm]?dash\b)[ \t]*")
_DASH = re.compile(r"[ \t]*[‐-―−][ \t]*|\s+-{1,2}\s+")


def tidy(caption: str) -> str:
    """A caption as a person would type it: any dash between words becomes a comma."""
    out = _DASH_SPELLED.sub(", ", caption or "")
    out = _DASH.sub(", ", out)
    return re.sub(r" ,", ",", re.sub(r",\s*,", ",", out)).strip()


class ClaudeDrafter:
    name = "claude"

    def __init__(self, conn: sqlite3.Connection, *, agent: str = "content", model: str | None = None, client=None):
        self.conn = conn
        self.agent = agent
        self.model = model or config.getenv("AI_MODEL") or DEFAULT_MODEL
        self.effort = config.getenv("AI_EFFORT") or DEFAULT_EFFORT
        if client is None:
            import anthropic  # imported here so the template path needs no key or SDK
            client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
        self.client = client

    def draft(self, facts: PostFacts, photo: Path) -> Draft:
        if spend.cap_reached(self.conn):
            raise SpendCapReached("monthly AI spend cap reached; no caption drafted")
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [image_block(photo), {"type": "text", "text": user_text(facts)}]}],
        )
        usage = response.usage
        answered_by = getattr(response, "model", None) or self.model
        spend.record(self.conn, self.agent, answered_by, int(usage.input_tokens or 0), int(usage.output_tokens or 0), "caption")
        if response.stop_reason == "refusal":
            raise DraftError("model refused this photo")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise DraftError(f"no text block (stop_reason={response.stop_reason})")
        data = json.loads(text)
        captions = {net: tidy(words) for net, words in data["captions"].items()}
        return Draft(captions=captions, photo_summary=data["photo_summary"], model=answered_by,
                     possible_minor=bool(data.get("possible_minor", True)), privacy=tuple(data.get("privacy") or ()),
                     input_tokens=int(usage.input_tokens or 0), output_tokens=int(usage.output_tokens or 0), raw=data)


class TemplateDrafter:
    """Deterministic captions so dry runs work with no key. Marked model='template'.
    It cannot see the photo, so it never clears the minor check (possible_minor stays True)."""
    name = "template"
    model = "template"

    def draft(self, facts: PostFacts, photo: Path) -> Draft:
        where = f" at {facts.event_name}" if facts.event_name else ""
        credit = f" {facts.credit}." if facts.credit else ""
        ask = f" Request a quote for your event. {facts.quote_link}".rstrip()
        body = f"A moment{where}.{credit}{ask}"
        tags = "#eventphotography #conventionphotography" + (" #cosplay" if facts.event_kind == "fan" else "")
        captions = {"instagram": f"{body}\n\n{tags}", "facebook": body, "pinterest": f"{body} {tags}"}
        return Draft(captions={k: tidy(v) if k == "facebook" else v for k, v in captions.items()},
                     photo_summary="template caption; the photo was not looked at", model=self.model)


def available() -> bool:
    return bool(secrets.get_secret("ANTHROPIC_API_KEY"))


def get_drafter(conn: sqlite3.Connection, agent: str = "content") -> Drafter:
    if (config.getenv("AI_MODEL") or "").lower() == "template" or not available():
        return TemplateDrafter()
    return ClaudeDrafter(conn, agent=agent)
