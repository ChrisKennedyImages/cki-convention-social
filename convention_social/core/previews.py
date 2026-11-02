"""What a draft shows, everywhere a draft's image appears: Today, the draft page, All posts, the phone ping's card and the
approve-by-token page. One rule for all of them, keyed off what the publisher sends (buffer/payloads.ASPECT_FOR, the
publisher's own map): each network that is ticked, on (POST_NETWORKS) and not held off shows the file it will receive,
labeled by network, in the networks' order; the first of those is the one image a page or a ping shows. A LinkedIn-only
draft shows the photo as shot, never a card. Chris, 2026-11-02, on a LinkedIn-only draft whose page and Today card led
with the Instagram card: "The LinkedIn photo is a completely fully branded photo."
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..buffer import payloads

WORDS = {"instagram": "the card", "facebook": "the card", "pinterest": "the pin card", "linkedin": "the photo as shot"}


@dataclass(frozen=True)
class Preview:
    network: str
    key: str            # the render_paths key the network receives
    count: int          # files under it (a carousel's slides)

    @property
    def words(self) -> str:
        if self.key == "cover":
            return "the reel, by its cover"
        if self.key == "story":
            return "the Story card"
        if self.count > 1:
            return f"the carousel, {self.count} slides"
        return WORDS.get(self.network, "the card")

    @property
    def label(self) -> str:
        return f"{payloads.name_of(self.network)}: {self.words}"

    @property
    def slug(self) -> str:
        return self.key.replace(":", "x")

    def url(self, qid: int, index: int = 1) -> str:
        return f"/media/render/{qid}/{self.slug}/{index}"


def _field(row, name: str, default):
    try:
        value = row[name] if name in row.keys() else None
    except (KeyError, IndexError, TypeError):
        value = None
    try:
        parsed = json.loads(value) if value else default
    except (TypeError, ValueError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def key_for(renders: dict, network: str, meta: Optional[dict] = None) -> str:
    """The render_paths key this network receives, as the publisher sends it: ASPECT_FOR; on a reel row Instagram and
    Facebook get the video, shown by its cover; an instant photo's Story goes to Instagram as its Story card
    (agents/publisher.instant_format)."""
    if network in payloads.REEL_NETWORKS and renders.get("9:16"):
        return "cover"
    if network == "instagram" and (meta or {}).get("instant") and (meta or {}).get("format") == "story" and renders.get("story"):
        return "story"
    return payloads.ASPECT_FOR[network]


def shows(row) -> list[Preview]:
    """What each ticked network will receive, in the networks' order. A network unticked, held off or skipped (rule_report
    skipped), or switched off, shows nothing; so does one with no file yet."""
    renders = _field(row, "render_paths", {})
    targets = _field(row, "targets", [])
    meta = _field(row, "rule_report", {})
    skipped = meta.get("skipped") if isinstance(meta.get("skipped"), dict) else {}
    on = payloads.posting_networks()
    out = []
    for n in payloads.NETWORKS:
        if n not in targets or n not in on or n in skipped:
            continue
        key = key_for(renders, n, meta)
        files = renders.get(key) or []
        if files:
            out.append(Preview(n, key, len(files)))
    return out


def lead(row) -> Optional[Preview]:
    """The one image a surface with room for one shows: the first network's."""
    found = shows(row)
    return found[0] if found else None


def lead_file(row) -> Optional[Path]:
    """The file behind lead(), for the ping's card."""
    first = lead(row)
    if first is None:
        return None
    files = _field(row, "render_paths", {}).get(first.key) or []
    return Path(files[0]) if files else None
