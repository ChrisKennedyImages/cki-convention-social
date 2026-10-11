"""The search words every caption is built around.

Chris, 2026-10-11: "Make sure the captions are SEO optimized painstakingly". Where each network looks:

  Instagram  search reads the caption's words, not only its hashtags, and the first line is what shows
             above "more": the search phrase goes in that first line, under 125 characters. Then three to
             five hashtags, specific ones first, chosen here so none names an event or a person.
  Facebook   search reads the post text: the phrase goes in the first sentence, the quote link at the end,
             no hashtags.
  Pinterest  is a search engine: the pin title (the caption's first sentence, under 100 characters) opens
             with the phrase, the description carries the related phrases, the pin links to the quote page.
  The image  carries alt text (Instagram and Pinterest read it, when Buffer takes it) and our search fields
             inside the file (render/meta.py).

A plan comes from what the post shows: the kind of event, the room the photo is from and the design;
never from a name (ai/names.py). It holds one primary phrase, the related phrases, the place when
SERVICE_AREA is set (Keys page), and the hashtags. `finish` puts the hashtags and the link where they
belong; `problems` says what a draft misses. The content agent asks Claude once more with the problems
named, and otherwise uses the template, which meets the plan by construction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..core import config

IG_FOLD = 125            # Instagram shows about this much before "more"
PIN_TITLE_MAX = 100
PIN_DESCRIPTION_MAX = 500
IG_MAX = 2200
IG_TAGS, PIN_TAGS = 5, 3

# the room a photo is from, by the sorter's shot type
ROOM = {"stage_panel": "stage", "stage": "stage", "backstage": "backstage", "portrait": "portrait", "headshot": "portrait",
        "vendor_hall": "floor", "booth": "floor", "dinner_reception": "evening", "dinner": "evening",
        "crowd": "crowd", "candid": "crowd", "group": "crowd"}

PRIMARY = {
    "business": {"stage": "conference photography", "backstage": "backstage event photography", "portrait": "conference headshots",
                 "floor": "trade show photography", "evening": "corporate event photography", "crowd": "conference photography"},
    "fan": {"stage": "convention photography", "backstage": "backstage convention photography", "portrait": "convention portraits",
            "floor": "convention photography", "evening": "event photography", "crowd": "convention photography"},
    "unknown": {"stage": "event photography", "backstage": "backstage event photography", "portrait": "event portraits",
                "floor": "event photography", "evening": "corporate event photography", "crowd": "event photography"},
}
RELATED = {
    "business": ("event photographer", "corporate event photography", "photo delivery by face match"),
    "fan": ("convention photographer", "event photographer", "photo delivery by face match"),
    "unknown": ("event photographer", "corporate event photography", "photo delivery by face match"),
    "architecture": ("architectural photography", "event venue photography", "event photographer"),
    "facematch": ("event photographer", "event photo sharing", "conference photography"),
}
# specific before broad; #eventprofs and #eventplanning reach the people who book photographers
HASHTAGS = {
    "business": ("#conferencephotography", "#corporateeventphotography", "#eventprofs", "#eventphotographer", "#eventphotography"),
    "fan": ("#conventionphotography", "#conventionphotographer", "#eventprofs", "#eventphotographer", "#eventphotography"),
    "unknown": ("#eventphotography", "#eventphotographer", "#eventprofs", "#eventplanning", "#corporateevents"),
    "architecture": ("#venuephotography", "#architecturalphotography", "#eventvenue", "#eventprofs", "#eventphotography"),
    "facematch": ("#eventtech", "#eventprofs", "#eventphotography", "#eventphotographer", "#conferencephotography"),
}
# a phrase for the room, for the template's first line
ROOM_WORDS = {"stage": "from the keynote to the last panel", "backstage": "from the green room to the side of the stage",
              "portrait": "made between sessions in good light", "floor": "across the exhibit floor and every booth",
              "evening": "through the dinners and receptions", "crowd": "in every room of the event"}
KIND_WORDS = {"business": "conference", "fan": "fan convention"}
HASHTAG = re.compile(r"(?<!\w)#\w+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Plan:
    primary: str
    related: tuple[str, ...]
    hashtags: tuple[str, ...]
    area: str = ""
    room: str = "crowd"
    kind: str = "unknown"
    design: str = "single"

    def prompt_lines(self) -> list[str]:
        lines = [f"Search phrase: {self.primary}. Use it word for word in the first sentence of every caption; the Pinterest "
                 "caption opens with it.",
                 f"Related search phrases: {'; '.join(self.related)}. Use one or two of them, word for word and naturally, "
                 "in each caption."]
        if self.area:
            lines.append(f"Place: {self.area}. Say once, naturally, that the work covers events in {self.area}.")
        lines.append("Write no hashtags and no links: the suite adds them.")
        return lines


def service_area() -> str:
    return " ".join((config.getenv("SERVICE_AREA", "") or "").split())


def plan_for(*, subject: str, event_kind: Optional[str], shot_type: Optional[str], design: str = "single") -> Plan:
    kind = event_kind if event_kind in ("business", "fan") else "unknown"
    room = ROOM.get(shot_type or "", "crowd")
    area = service_area()
    if subject == "architecture":
        return Plan("venue photography", RELATED["architecture"], HASHTAGS["architecture"], area, "venue", kind, design)
    if design in ("facematch",):
        return Plan("event photo delivery", RELATED["facematch"], HASHTAGS["facematch"], area, room, kind, design)
    primary = PRIMARY[kind][room]
    if design in ("spotlight", "carousel", "fan", "reel"):          # several rooms in one post: the broad phrase
        primary = {"business": "conference photography", "fan": "convention photography"}.get(kind, "event photography")
    related = tuple(r for r in RELATED[kind] if r != primary)
    return Plan(primary, related, HASHTAGS[kind], area, room, kind, design)


# ------------------------------------------------------------------ putting it together

def body_of(text: str) -> str:
    """The caption's words without hashtags."""
    return " ".join(HASHTAG.sub(" ", text or "").split())


def first_sentence(text: str) -> str:
    return SENTENCE_END.split(body_of(text).strip(), maxsplit=1)[0]


def finish(captions: dict, plan: Plan, link: str) -> dict:
    """The hashtags and the link where each network wants them, whatever the writer did with them."""
    out = {}
    for net, text in captions.items():
        body = body_of(text)
        if link and net in ("facebook", "pinterest") and link.lower() not in body.lower():
            body = f"{body} {link}".strip()
        if net == "instagram":
            out[net] = f"{body}\n\n{' '.join(plan.hashtags[:IG_TAGS])}"
        elif net == "pinterest":
            out[net] = f"{body} {' '.join(plan.hashtags[:PIN_TAGS])}"
        else:
            out[net] = body
    return out


def problems(captions: dict, plan: Plan) -> list[str]:
    """What a finished draft misses of its plan; empty when it meets it."""
    out = []
    p = plan.primary.lower()
    for net, text in captions.items():
        body, first = body_of(text), first_sentence(text)
        if p not in first.lower():
            out.append(f"the {net} caption's first sentence does not say \"{plan.primary}\"")
        if not any(r.lower() in body.lower() for r in plan.related):
            out.append(f"the {net} caption uses none of the related phrases ({'; '.join(plan.related)})")
        if plan.area and plan.area.lower() not in body.lower():
            out.append(f"the {net} caption does not mention {plan.area}")
        if net == "instagram":
            if p not in body[:IG_FOLD].lower():
                out.append(f"on Instagram \"{plan.primary}\" falls below the fold (the first {IG_FOLD} characters)")
            if len(text) > IG_MAX:
                out.append(f"the Instagram caption is over {IG_MAX} characters")
        if net == "pinterest":
            if len(first) > PIN_TITLE_MAX:
                out.append(f"the Pinterest title (its first sentence) is over {PIN_TITLE_MAX} characters")
            elif p not in first.lower()[:60]:
                out.append(f"the Pinterest title does not open with \"{plan.primary}\"")
            if len(text) > PIN_DESCRIPTION_MAX:
                out.append(f"the Pinterest caption is over {PIN_DESCRIPTION_MAX} characters")
    return out


def alt_text(plan: Plan, shot_words: str, brand: str) -> str:
    """A plain description for the image's alt text when the writer gave none (never a name)."""
    if plan.room == "venue":
        return f"Venue photography of an event space, by {brand}"[:125]
    where = KIND_WORDS.get(plan.kind, "event")
    return f"{shot_words or 'Event photography'} at a {where}, photographed by {brand}"[:125]


def template_captions(plan: Plan, link: str, brand: str) -> dict:
    """Captions that meet the plan by construction, for dry runs and when the writer misses twice."""
    cap = plan.primary[0].upper() + plan.primary[1:]
    if plan.room == "venue":
        first = f"{cap} of the rooms where events happen."
        second = f"Architectural photography and event venue photography by {brand}."
    elif plan.design == "facematch":
        first = f"{cap} by face match, with no wires."
        second = ("Guests scan their badge, add a selfie, and every photo they are in comes straight to them. "
                  "Your event photographer and event photo sharing in one.")
    else:
        first = f"{cap}, {ROOM_WORDS.get(plan.room, ROOM_WORDS['crowd'])}."
        second = "Your event photographer for every room you need, with photo delivery by face match while the event is on."
    place = f" Covering events in {plan.area} and beyond." if plan.area else ""
    ask = f" Request a quote at {link}." if link else " Request a quote for your event."
    body = f"{first} {second}{place}{ask}".strip()
    return finish({"instagram": body, "facebook": body, "pinterest": body}, plan, link)
