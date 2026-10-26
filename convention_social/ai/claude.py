"""Caption drafting with Claude: a photo goes in, one JSON draft per network comes out.

The model sees one downscaled photo plus the facts the suite knows (the kind
of event, never which one or who is in it; whether the company was the
official photographer) and returns strict JSON through
output_config. The
prompt states the rules, but ai/copy_rules.py is the gate, not the prompt.

Model: claude-opus-5 (override with AI_MODEL), effort set explicitly, the
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
from typing import TYPE_CHECKING, Optional, Protocol, Sequence

from PIL import Image, ImageOps

from ..core import config, secrets
from . import spend

if TYPE_CHECKING:
    from . import seo_plan

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "medium"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_IMAGE_EDGE = 1024
NETWORKS = ("instagram", "facebook", "pinterest")
# what kind of event, said instead of which one (ai/names.py: no event or person is ever named)
KIND_WORDS = {"fan": "a convention", "business": "a conference"}        # never "fan convention" in public (Chris, 2026-10-12)

SYSTEM_PROMPT = """You write social posts for an event and convention photography company, in the photographer's own voice. A post is about the photo: what it shows, where in the event it was made, the moment. It is never about the company's services, what it offers, how it works or what a client gets; that is between the photographer and the client. The company photographs business, corporate and association conferences, conventions, galas and award dinners.

Write plain, short sentences. Use commas and periods, never a dash of any kind. No hype words, no emojis, no exclamation marks in a row. Describe only what the photo shows and what the facts give you.

Hard rules:
1. Never state or hint at a price, a rate, a discount or a package cost. The call to action is to request a quote for an event.
2. Never say or imply the company is a convention's official photographer, partner or sponsor, or affiliated with it, unless the facts say official: yes.
3. Never name the event, the conference or convention, the organization that runs it, or any person, and never tag anyone with an @handle, even when a banner, a badge, a sign, a podium or a stage screen in the photo shows the name. Say what kind of event it was (a business conference, an association conference, a convention) and what the photo shows, never which event or who is in it. No hashtag names an event, an organization or a person.
4. Never mention a badge name, a plate, a screen or any personal detail you can read in the photo.
5. Never describe the company's services or what it offers: not what it covers, includes or comes with, not how a shoot is set up, how photos are delivered, how long anything takes, or what anyone leaves with. The words include, coverage, service, offer and delivery never appear. The caption describes the photo; the one ask is a quote.
6. Write no hashtags and no links. The suite adds the hashtags and the quote link.
7. Search: each caption is found through its words. Use the search phrase you are given word for word in the first sentence, and one or two of the related phrases word for word in the body, written as a person would say them, never as a list of keywords. The Instagram caption's first line is under 125 characters. The Pinterest caption opens with the search phrase in a first sentence under 100 characters: that sentence is the pin's title.
8. alt_text: one plain sentence, under 125 characters, saying literally what the photo shows for someone who cannot see it. No names, no event, no handles.

Return JSON only, matching the schema you are given."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "photo_summary": {"type": "string", "description": "One sentence: what kind of picture it is. No person's name, title or identity; no company or venue name."},
        "captions": {
            "type": "object",
            "properties": {n: {"type": "string"} for n in NETWORKS},
            "required": list(NETWORKS),
            "additionalProperties": False,
        },
        "alt_text": {"type": "string", "description": "Literal, under 125 characters, no names."},
    },
    "required": ["photo_summary", "captions", "alt_text"],
    "additionalProperties": False,
}


@dataclass
class PostFacts:
    """No event name and no credit, by design: a caption never says which event or who (ai/names.py)."""
    brand_name: str
    event_kind: str = "unknown"          # fan | business | unknown
    official: bool = False               # only True when Chris confirmed it for this event
    shot_type: str = ""
    quote_link: str = ""
    subject: str = "event"               # event | architecture
    plan: Optional["seo_plan.Plan"] = None   # the search words this post is built around (ai/seo_plan.py)
    note: str = ""                       # what the photographer said about the moment (a photo sent from the phone), no name in it


@dataclass
class Draft:
    captions: dict[str, str]
    photo_summary: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict = field(default_factory=dict)
    alt_text: str = ""


class Drafter(Protocol):
    name: str

    def draft(self, facts: PostFacts, photo: Path, notes: Sequence[str] = ()) -> Draft: ...


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
        f"Event type: {KIND_WORDS.get(facts.event_kind, 'an event')} (never name which event, or anyone in the photo)",
        f"Official photographer for this event: {'yes' if facts.official else 'no'}",
        f"Shot type: {facts.shot_type or 'unknown'}",
        ("Subject: a building or venue from the photographer's architecture work. Say what the building shows, never name "
         "the owner, the address or the client."
         if facts.subject == "architecture" else "Subject: event photography"),
        # Chris, 2026-10-12: portraits are backstage, for the speakers and the people the event is about, lit on site
        *(["A portrait here is made backstage, for a speaker or a guest of honor, lit on site with professional lights and "
           "color gels and finished in the camera. Say that plainly when it fits the photo; never say that every attendee gets one."]
          if facts.shot_type in ("portrait", "headshot") else []),
        *([f"The photographer, who took it minutes ago, says of this moment: {facts.note}. Use that, in your own words; "
           "it names no event and no person, and neither do you."] if facts.note else []),
        *(facts.plan.prompt_lines() if facts.plan else []),
        "Write one caption per network: instagram (a first line under 125 characters that carries the search phrase, then "
        "two or three short sentences), facebook (one or two short paragraphs), pinterest (a first sentence under 100 "
        "characters that opens with the search phrase, then one or two descriptive sentences). Each caption ends by "
        "asking for a quote.",
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

    def draft(self, facts: PostFacts, photo: Path, notes: Sequence[str] = ()) -> Draft:
        if spend.cap_reached(self.conn):
            raise SpendCapReached("monthly AI spend cap reached; no caption drafted")
        held = spend.reserve(self.conn, self.agent, self.model)       # 8.2: the cap is held while the call is in flight
        if held is None:
            raise SpendCapReached("monthly AI spend cap reached; no caption drafted")
        try:
            response = self._create(facts, photo, notes)
        except DraftError:
            spend.release(self.conn, held)
            raise
        except Exception as e:  # noqa: BLE001  the API or the network: a DraftError the caller handles (the template writes), never a dead run
            spend.release(self.conn, held)
            raise DraftError(f"{type(e).__name__}: {e}") from e
        usage = response.usage
        answered_by = getattr(response, "model", None) or self.model
        spend.record(self.conn, self.agent, answered_by, int(usage.input_tokens or 0), int(usage.output_tokens or 0), "caption", reservation=held)
        if response.stop_reason == "refusal":
            raise DraftError("model refused this photo")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise DraftError(f"no text block (stop_reason={response.stop_reason})")
        data = json.loads(text)
        captions = {net: tidy(words) for net, words in data["captions"].items()}
        return Draft(captions=captions, photo_summary=data["photo_summary"], model=answered_by,
                     input_tokens=int(usage.input_tokens or 0), output_tokens=int(usage.output_tokens or 0), raw=data,
                     alt_text=tidy(data.get("alt_text") or ""))

    def _create(self, facts: PostFacts, photo: Path, notes: Sequence[str]):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [image_block(photo), {"type": "text", "text": user_text(facts) + (
                "\n\nYour last draft missed these; fix them and change nothing else that was right:\n- " + "\n- ".join(notes)
                if notes else "")}]}],
        )


class TemplateDrafter:
    """Deterministic captions so dry runs work with no key. Marked model='template'. It cannot see the photo."""
    name = "template"
    model = "template"

    def draft(self, facts: PostFacts, photo: Path, notes: Sequence[str] = ()) -> Draft:
        if facts.plan is not None:
            from . import seo_plan
            captions = seo_plan.template_captions(facts.plan, facts.quote_link, facts.brand_name)
            return Draft(captions=captions, photo_summary="template caption; the photo was not looked at", model=self.model)
        where = "a building we photographed" if facts.subject == "architecture" else KIND_WORDS.get(facts.event_kind, "an event")
        ask = f" Request a quote for your event. {facts.quote_link}".rstrip()
        body = f"A moment from {where}.{ask}"
        tags = "#eventphotography #conventionphotography"
        captions = {"instagram": f"{body}\n\n{tags}", "facebook": body, "pinterest": f"{body} {tags}"}
        return Draft(captions={k: tidy(v) if k == "facebook" else v for k, v in captions.items()},
                     photo_summary="template caption; the photo was not looked at", model=self.model)


def available() -> bool:
    return bool(secrets.get_secret("ANTHROPIC_API_KEY"))


def get_drafter(conn: sqlite3.Connection, agent: str = "content") -> Drafter:
    if (config.getenv("AI_MODEL") or "").lower() == "template" or not available():
        return TemplateDrafter()
    return ClaudeDrafter(conn, agent=agent)
