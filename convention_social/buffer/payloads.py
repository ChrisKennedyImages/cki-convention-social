"""CreatePostInput builders per network: instagram, facebook, pinterest.

Field names were checked against Buffer's live GraphQL schema by introspection
on 2026-10-09 (schema only; no post was created):

  CreatePostInput: channelId!, text, assets: [AssetInput!]! (oneOf image | video |
  document; ImageAssetInput {url!, thumbnailUrl, metadata}), mode: ShareMode!
  (addToQueue | customScheduled | shareNext | shareNow), schedulingType:
  SchedulingType! (automatic | notification), dueAt: DateTime, tagIds: [TagId!],
  needsApproval: Boolean! (default false), metadata: PostInputMetaData.
  Instagram: metadata.instagram {type: PostType!, shouldShareToFeed: Boolean!}. PostType is one
  enum for every network (2026-10-14: carousel, event, ghost_post, offer, post, reel, short, story,
  thread, whats_new); Instagram takes only post, story or reel, and a carousel is a "post" with
  several image assets. Buffer refused "carousel" on the first live night, 2026-10-14: "Instagram
  does not support the 'carousel' post type. Valid types are post, story, or reel."
  Facebook: metadata.facebook {type: PostTypeFacebook! (post | reel | story)}.
  Pinterest: metadata.pinterest {boardServiceId: String, title: String, url: String}
  (PinterestPostMetadataInput). A board's serviceId is listed on the Pinterest
  channel (PinterestMetadata.boards); BufferClient.pinterest_boards(channel_id)
  reads it, and it goes in PINTEREST_BOARD_ID.

REELS (2026-10-11): a reel is assets [{video: {...}}] with metadata type "reel" on Instagram and
Facebook. The video asset's fields are not written here from memory: the publisher asks the live
schema (BufferClient.video_asset_fields) before building one, and build_reel refuses any required
field it does not know how to fill. Pinterest gets the reel's cover as an image pin.
No network takes a cover image for a video (2026-10-16: Buffer refused post 7 for setting
VideoAssetInput.thumbnailUrl, which the schema lists and its own description says never to set): the
cover is a frame of the reel, named by metadata.thumbnailOffset in milliseconds. A field the live
schema's description says not to use is never filled; if one is required, the reel stops.

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
INSTAGRAM_IMAGE_TYPE = "post"   # one photo or a carousel of several; Instagram takes post, story or reel


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


POSTING_KEY = "POST_NETWORKS"
POSTING_DEFAULT = ("instagram",)   # Chris, 2026-10-15: "we are ONLY using Insta now"


def posting_networks() -> tuple[str, ...]:
    """The networks posts go to (Keys page, Posting: POST_NETWORKS, comma separated). Blank is Instagram only;
    a network left out is not posted to and not reported as missing a channel."""
    raw = config.getenv(POSTING_KEY, "") or ""
    picked = tuple(n for n in (w.strip().lower() for w in raw.split(",")) if n in NETWORKS)
    return picked or POSTING_DEFAULT


def pinterest_board_id() -> str:
    return config.getenv("PINTEREST_BOARD_ID", "") or ""


def pinterest_link() -> str:
    """The page a pin opens: PINTEREST_LINK, else the site's quote page (a pin with a link is what sends
    searchers to the site; 2026-10-11)."""
    domain = config.get_config().brand_domain
    return config.getenv("PINTEREST_LINK", "") or (f"https://{domain}/book/" if domain else "")


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


def image_asset(url: str, alt_text: str = "", alt_path: Optional[list[str]] = None) -> dict:
    """{"image": {...}}: the url, and the alt text where the live schema put its field (alt_path)."""
    asset: dict = {"url": url}
    if alt_text and alt_path:
        node = asset
        for name in alt_path[:-1]:
            node = node.setdefault(name, {})
        node[alt_path[-1]] = alt_text
    return {"image": asset}


def build(network: str, channel_id: str, text: str, image_urls: list[str], *,
          scheduled_for: Optional[str] = None, board_id: Optional[str] = None,
          title: Optional[str] = None, link: Optional[str] = None, alt_text: str = "",
          alt_path: Optional[list[str]] = None, story: bool = False) -> dict:
    """One CreatePostInput. `scheduled_for` is local 'YYYY-MM-DDTHH:MM'; with none the post goes now. `story`: an Instagram
    Story (2026-10-15, instant photos): type "story", the 9:16 card, no caption, not shared to the feed."""
    if network not in NETWORKS:
        raise PayloadError(f"unknown network {network!r}")
    due = due_at_utc(scheduled_for)
    urls = list(image_urls)
    if network == "pinterest":
        urls = urls[:1]          # one image per pin (more than one per pin was not verified)
    inp: dict = {
        "channelId": channel_id,
        "text": text,
        "assets": [image_asset(u, alt_text, alt_path) for u in urls],
        "schedulingType": "automatic",
        "mode": "customScheduled" if due else "shareNow",
        "tagIds": [],
        "needsApproval": False,
    }
    if due:
        inp["dueAt"] = due
    if story:
        if network != "instagram":
            raise PayloadError(f"a Story goes to Instagram only, not {network}")
        inp["text"] = ""
        inp["metadata"] = {"instagram": {"type": "story", "shouldShareToFeed": False}}
    elif network == "instagram":
        # InstagramPostMetadataInput.type is required and is "post" however many images there are: a
        # carousel is a post with several assets (Buffer refused "carousel" for Instagram, 2026-10-14)
        inp["metadata"] = {"instagram": {"type": INSTAGRAM_IMAGE_TYPE, "shouldShareToFeed": True}}
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
# what this code can fill in a video asset, by the field names the live schema uses: the video, and inside
# metadata the cover frame. Never a cover image (no network accepts one).
VIDEO_FILLS = {"url": "video"}
COVER_OFFSET = "thumbnailOffset"
DO_NOT_USE = re.compile(r"^\s*do not use\b", re.I)


def _told_not_to_use(f: dict) -> bool:
    return bool(DO_NOT_USE.match(f.get("description") or ""))


def video_asset(fields: list[dict], video_url: str, cover_ms: Optional[int] = None) -> dict:
    """The video asset, filled by the field names the live schema gives ([{name, required, description, fields}]):
    the url, and the cover frame in metadata.thumbnailOffset when the schema has it. A required field this code
    cannot fill, a field it would fill that the schema says not to use, or no url field at all, stops the reel."""
    names = {f["name"]: f for f in fields}
    if "url" not in names:
        raise PayloadError("Buffer's video asset has no url field; no reel can be built")
    asset = {}
    for name, f in names.items():
        if _told_not_to_use(f):
            if f.get("required") or VIDEO_FILLS.get(name):
                raise PayloadError(f"Buffer's schema says not to use the video's {name!r}, which a reel needs; the reel stays unposted")
            continue
        if VIDEO_FILLS.get(name) == "video":
            asset[name] = video_url
        elif name == "metadata" and cover_ms is not None:
            inner = {g["name"]: g for g in f.get("fields") or []}
            offset = inner.get(COVER_OFFSET)
            others_required = [g for n, g in inner.items() if n != COVER_OFFSET and g.get("required")]
            if offset and not _told_not_to_use(offset) and not others_required:
                asset[name] = {COVER_OFFSET: int(cover_ms)}
            elif f.get("required"):
                raise PayloadError("Buffer's video metadata needs fields this code does not fill; the reel stays unposted")
        elif f.get("required"):
            raise PayloadError(f"Buffer's video asset needs {name!r}, which this code does not fill; the reel stays unposted")
    return asset


def build_reel(network: str, channel_id: str, text: str, video_url: str, cover_ms: Optional[int], fields: list[dict], *,
               scheduled_for: Optional[str] = None) -> dict:
    """One CreatePostInput for a reel. `fields` is the video asset's input type as the live schema
    gives it (BufferClient.video_asset_fields); `cover_ms` is the cover's frame, in ms into the video."""
    if network not in REEL_NETWORKS:
        raise PayloadError(f"{network} takes no reel here")
    asset = video_asset(fields, video_url, cover_ms)
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
