"""CreatePostInput builders per network: instagram, facebook, pinterest.

Field names were checked against Buffer's live GraphQL schema by introspection
on 2026-10-09 (schema only; no post was created):

  CreatePostInput: channelId!, text, assets: [AssetInput!]! (oneOf image | video |
  document; ImageAssetInput {url!, thumbnailUrl, metadata}), mode: ShareMode!
  (addToQueue | customScheduled | shareNext | shareNow), schedulingType:
  SchedulingType! (automatic | notification), dueAt: DateTime, tagIds: [TagId!],
  needsApproval: Boolean! (default false), metadata: PostInputMetaData.
  Instagram: metadata.instagram {type: PostType! (post | carousel | reel | story ...),
  shouldShareToFeed: Boolean!}.
  Facebook: metadata.facebook {type: PostTypeFacebook! (post | reel | story)}.
  Pinterest: metadata.pinterest {boardServiceId: String, title: String, url: String}
  (PinterestPostMetadataInput). A board's serviceId is listed on the Pinterest
  channel (PinterestMetadata.boards); BufferClient.pinterest_boards(channel_id)
  reads it, and it goes in PINTEREST_BOARD_ID.

REELS (2026-10-11): a reel is assets [{video: {...}}] with metadata type "reel" on Instagram and
Facebook. The video asset's fields are not written here from memory: the publisher asks the live
schema (BufferClient.video_asset_fields) before building one, and build_reel refuses any required
field it does not know how to fill. Pinterest gets the reel's cover as an image pin.

BEFORE ARMING PINTEREST: the field NAMES above match the live schema, but no pin
has been created through this code yet. Whether Buffer requires boardServiceId
in practice, how it treats a title over Pinterest's 100 characters, and whether
it accepts more than one image per pin were not live-verified. Re-run the
schema introspection, then make one real test pin with the publisher live and
confirm it on Pinterest before leaving the lane on.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..core import config

NETWORKS = ("instagram", "facebook", "pinterest")
PIN_TITLE_MAX = 100          # Pinterest's own title limit


class PayloadError(ValueError):
    pass


def due_at_utc(local_value: Optional[str]) -> Optional[str]:
    """'YYYY-MM-DDTHH:MM' (local time, TIMEZONE) -> ISO-8601 UTC with Z, or None."""
    if not local_value:
        return None
    tz = ZoneInfo(config.get_config().timezone)
    dt = datetime.fromisoformat(local_value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pinterest_board_id() -> str:
    return config.getenv("PINTEREST_BOARD_ID", "") or ""


def pinterest_link() -> str:
    """Optional: the page a pin opens (the quote page, once the site exists)."""
    return config.getenv("PINTEREST_LINK", "") or ""


_HASHTAG = re.compile(r"(?:^|\s)#\w+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")


def pin_title(text: str, fallback: str = "") -> str:
    """A short pin title from the caption: hashtags dropped, the first sentence, at most 100 characters."""
    plain = " ".join(_HASHTAG.sub(" ", text or "").split())
    first = _SENTENCE_END.split(plain, maxsplit=1)[0].strip() if plain else ""
    if len(first) > PIN_TITLE_MAX:
        cut = first[:PIN_TITLE_MAX + 1].rsplit(" ", 1)[0].rstrip(",;: ")
        first = cut if cut else first[:PIN_TITLE_MAX]
    return first or (fallback or "")[:PIN_TITLE_MAX]


def build(network: str, channel_id: str, text: str, image_urls: list[str], *,
          scheduled_for: Optional[str] = None, board_id: Optional[str] = None,
          title: Optional[str] = None, link: Optional[str] = None) -> dict:
    """One CreatePostInput. `scheduled_for` is local 'YYYY-MM-DDTHH:MM'; with none the post goes now."""
    if network not in NETWORKS:
        raise PayloadError(f"unknown network {network!r}")
    due = due_at_utc(scheduled_for)
    urls = list(image_urls)
    if network == "pinterest":
        urls = urls[:1]          # one image per pin (more than one per pin was not verified)
    inp: dict = {
        "channelId": channel_id,
        "text": text,
        "assets": [{"image": {"url": u}} for u in urls],
        "schedulingType": "automatic",
        "mode": "customScheduled" if due else "shareNow",
        "tagIds": [],
        "needsApproval": False,
    }
    if due:
        inp["dueAt"] = due
    if network == "instagram":
        # InstagramPostMetadataInput.type is required; several images are a carousel
        inp["metadata"] = {"instagram": {"type": "carousel" if len(urls) > 1 else "post", "shouldShareToFeed": True}}
    elif network == "facebook":
        # FacebookPostMetadataInput.type is required (post | reel | story)
        inp["metadata"] = {"facebook": {"type": "post"}}
    elif network == "pinterest":
        if not board_id:
            raise PayloadError("PINTEREST_BOARD_ID is not set; a pin needs a board")
        pin = {"boardServiceId": board_id, "title": pin_title(title or text, config.get_config().brand_name)}
        if link:
            pin["url"] = link
        inp["metadata"] = {"pinterest": pin}
    return inp


REEL_NETWORKS = ("instagram", "facebook")
# what this code can fill in a video asset, by the field names the live schema uses
VIDEO_FILLS = {"url": "video", "thumbnailUrl": "cover", "thumbnail": "cover", "coverUrl": "cover"}


def video_asset(fields: list[dict], video_url: str, cover_url: str) -> dict:
    """The video asset, filled by the field names the live schema gives ([{name, required}]). A
    required field this code cannot fill, or no url field at all, stops the reel."""
    names = {f["name"]: f for f in fields}
    if "url" not in names:
        raise PayloadError("Buffer's video asset has no url field; no reel can be built")
    asset = {}
    for name, f in names.items():
        what = VIDEO_FILLS.get(name)
        if what == "video":
            asset[name] = video_url
        elif what == "cover" and cover_url:
            asset[name] = cover_url
        elif f.get("required"):
            raise PayloadError(f"Buffer's video asset needs {name!r}, which this code does not fill; the reel stays unposted")
    return asset


def build_reel(network: str, channel_id: str, text: str, video_url: str, cover_url: str, fields: list[dict], *,
               scheduled_for: Optional[str] = None) -> dict:
    """One CreatePostInput for a reel. `fields` is the video asset's input type as the live schema
    gives it (BufferClient.video_asset_fields)."""
    if network not in REEL_NETWORKS:
        raise PayloadError(f"{network} takes no reel here")
    asset = video_asset(fields, video_url, cover_url)
    due = due_at_utc(scheduled_for)
    inp: dict = {"channelId": channel_id, "text": text, "assets": [{"video": asset}], "schedulingType": "automatic",
                 "mode": "customScheduled" if due else "shareNow", "tagIds": [], "needsApproval": False}
    if due:
        inp["dueAt"] = due
    if network == "instagram":
        inp["metadata"] = {"instagram": {"type": "reel", "shouldShareToFeed": True}}
    else:
        inp["metadata"] = {"facebook": {"type": "reel"}}
    return inp
