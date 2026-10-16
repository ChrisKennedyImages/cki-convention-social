"""Publisher agent: approved posts -> Buffer, then verify Buffer actually sent them.

Ready = content_queue status 'approved' (Chris pressed Approve on the
dashboard). Before anything leaves, the door re-checks the row (see door()).
For each targeted network there must be a connected row in `channels`
(service = instagram | facebook | pinterest); a pin also needs
PINTEREST_BOARD_ID. Each network gets its own time from pacing.py unless
Chris chose one on the draft. Media: the rendered design for the network's
aspect (render_paths {aspect: [paths]}: instagram and facebook 4:5,
pinterest 2:3), else the photo's own local copy. A reel (render_paths "9:16"
holds an mp4, "cover" its cover) goes to Instagram and Facebook as a video
post whose fields are read from Buffer's live schema first
(BufferClient.video_asset_fields); Pinterest still gets the 2:3 card.

Dry run (the default): the exact payloads are stored on the row, status
becomes 'would_publish', nothing is uploaded or sent. Live: media uploaded,
createPost per network, status 'scheduled' with the Buffer post ids; the next
runs poll each post until 'sent' (-> 'published', post_history rows) or
'error' (-> 'failed', errors row). Live with no BUFFER_API_KEY or no image
hosting = an errors row and nothing leaves; the rows stay approved.
"""
from __future__ import annotations

import importlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..ai import copy_rules, names
from ..buffer import budget, media, payloads
from ..buffer.client import BufferBudgetExceeded, BufferClient, BufferError, BufferRateLimited
from ..core import config, db, notify, runner, settings
from . import pacing

READY_SQL = "SELECT * FROM content_queue WHERE status = 'approved' ORDER BY COALESCE(approved_at, created_at), id"
TERMINAL_OK = {"sent"}
TERMINAL_BAD = {"error"}
ASPECT_FOR = {"instagram": "4:5", "facebook": "4:5", "pinterest": "2:3"}
POSTABLE_SUFFIXES = {".jpg", ".jpeg", ".png"}
VIDEO_ASPECT = "9:16"
# A dry run asks Buffer nothing: it builds the reel with the fields last read from Buffer (the Buffer
# page's Check, or the last live run), or else with the two a video asset is expected to carry and says
# so on the row. A live run reads the real fields from Buffer before anything is uploaded.
VIDEO_FIELDS_KEY = "buffer.video_fields"
IMAGE_ALT_KEY = "buffer.image_alt"
ASSUMED_VIDEO_FIELDS = [{"name": "url", "type": "String", "required": True},
                        {"name": "thumbnailUrl", "type": "String", "required": False}]
DRY_REEL_NOTE = ("Dry run: the reel was built without asking Buffer for its video fields (url and thumbnailUrl "
                 "assumed). A live run reads them from Buffer before anything is uploaded.")
ELIGIBILITY_MODULE = "convention_social.library.eligibility"

NO_CHANNELS = "No connected Buffer channel for any network on this post. Connect them in Buffer, then this goes out on the next run."
NO_DAY = "No open day in the next {days} days for {nets}. Choose a time on the draft."
CAPTION_BACK = "caption no longer passes the rules"
MEND_AGAIN_AFTER = timedelta(hours=1)      # a caption the suite rewrote this recently and that still breaks goes back, not round again
NUDGE_AFTER = timedelta(hours=8)           # a draft waiting this long gets one push; it is never set aside (Chris, 2026-10-13)
WAITING_SQL = "SELECT * FROM content_queue WHERE status = 'draft' AND kind = 'photo' ORDER BY id"


# ------------------------------------------------------------------ small readers

def _json(value, default):
    try:
        out = json.loads(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return None
    return out


def targets_of(row) -> list[str]:
    out = _json(row["targets"], [])
    return [t for t in out if isinstance(t, str)] if isinstance(out, list) else []


def photo_ids_of(row) -> Optional[list[int]]:
    """The row's photo ids, or None when the list cannot be read."""
    out = _json(row["photo_ids"], [])
    if not isinstance(out, list):
        return None
    try:
        return [int(x) for x in out]
    except (TypeError, ValueError):
        return None


def captions_of(row) -> Optional[dict]:
    out = _json(row["caption"], None)
    return out if isinstance(out, dict) else None


def render_paths_of(row) -> dict[str, list[str]]:
    out = _json(row["render_paths"], {})
    return out if isinstance(out, dict) else {}


def channel_for(conn, network: str) -> Optional[dict]:
    row = db.one(conn, "SELECT * FROM channels WHERE service=? AND connected=1 ORDER BY id LIMIT 1", (network,))
    return dict(row) if row else None


def is_official(conn, convention_id) -> bool:
    """Only True when Chris confirmed the company is this event's photographer."""
    if convention_id is None:
        return False
    row = db.one(conn, "SELECT official FROM conventions WHERE id=?", (convention_id,))
    return bool(row and row["official"] == 1)


def record_once(conn, agent: str, kind: str, message: str) -> None:
    """An errors row, unless the same one is already waiting for the watchdog (a 10 minute agent must not spam)."""
    if db.one(conn, "SELECT id FROM errors WHERE agent=? AND kind=? AND message=? AND notified_at IS NULL",
              (agent, kind, message[:2000])):
        return
    runner.record_error(conn, agent, kind, message)


ASAP_AFTER = pacing.LEAD + timedelta(minutes=5)      # the first time Buffer takes: the lead the slots keep, and a little


def asap_slot(ctx: runner.Context, row, now: Optional[datetime] = None) -> Optional[str]:
    """A photo sent from the phone (agents/phone.py, `rule_report.asap`) goes out as soon as he approves it: the next
    time Buffer takes, never the day's usual slot. None for every other post (the planner finds its day)."""
    if not _json(row["rule_report"], {}).get("asap"):
        return None
    from zoneinfo import ZoneInfo
    local = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(ctx.cfg.timezone)) + ASAP_AFTER
    return pacing.slot_value(local)


def posts_now(row) -> bool:
    """Chris, 2026-10-15, asked whether a photo from the share sheet should keep the 35 minutes to pull it back or post at
    once: "Right away". A post approved by his send (agents/phone.py approve_sent: source and approved_by "share") goes
    to Buffer to post now (shareNow), with no slot and no pre-post window, unless he set a time on it himself. So does
    every post he chose Post now on, on Today, the draft page or the ping (`rule_report.approved_how` "now"; his words:
    "an option to post immediately or to follow the pace"). Follow the pace keeps its slot, and a post approved before
    the choices existed keeps asap_slot."""
    meta = _json(row["rule_report"], {})
    if not isinstance(meta, dict) or row["scheduled_for"]:
        return False
    # every instant photo (2026-10-15: his own, his team's once he taps Approve, and its feed post) posts right away, and so
    # does every post he chose Post now on (#80)
    return bool(meta.get("instant")) or (meta.get("source") == "share" and meta.get("approved_by") == "share") \
        or meta.get("approved_how") == "now"


def instant_format(row) -> str:
    """"story" or "feed" for an instant photo (agents/team.py), "" for every other post."""
    meta = _json(row["rule_report"], {})
    return meta.get("format", "") if isinstance(meta, dict) and meta.get("instant") else ""


def for_day_of(row) -> Optional[date]:
    """The day the content agent drafted the post for (rule_report for_day), or None."""
    meta = _json(row["rule_report"], {}) if "rule_report" in row.keys() else {}
    try:
        return date.fromisoformat((meta or {}).get("for_day") or "") if isinstance(meta, dict) else None
    except ValueError:
        return None


def mended_lately(row, now: Optional[datetime] = None) -> bool:
    meta = _json(row["rule_report"], {}) if "rule_report" in row.keys() else {}
    mends = (meta or {}).get("mended") or [] if isinstance(meta, dict) else []
    try:
        last = datetime.fromisoformat(mends[-1]["at"])
    except (IndexError, KeyError, TypeError, ValueError):
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - last < MEND_AGAIN_AFTER


def made_at(row) -> Optional[datetime]:
    try:
        made = datetime.fromisoformat(row["created_at"])
    except (TypeError, ValueError):
        return None
    return made if made.tzinfo else made.replace(tzinfo=timezone.utc)


def tend_drafts(ctx: runner.Context, now: Optional[datetime] = None) -> dict:
    """Chris, 2026-10-13: silence never posts, and a draft is never set aside for it. A draft waiting eight
    hours gets one push that opens it, and `rule_report.nudged_at` keeps it to one. The publisher's dry-run
    switch is about Buffer; the draft waiting for him is real either way, so the nudge goes in dry run too."""
    now = now or datetime.now(timezone.utc)
    stats = {"waiting": 0, "nudged": 0}
    for row in db.rows(ctx.conn, WAITING_SQL):
        stats["waiting"] += 1
        meta = _json(row["rule_report"], {})
        meta = meta if isinstance(meta, dict) else {}
        made = made_at(row)
        if meta.get("nudged_at") or made is None or now - made < NUDGE_AFTER or meta.get("source") == "designed":
            continue            # a designed draft is an idea he may let pass: never chased (2026-10-15)
        day = for_day_of(row)
        what = f"{day:%A}'s post" if day else f"post {row['id']}"
        from . import content
        notify.push(f"{ctx.cfg.brand_name}: still waiting", f"Still waiting: {what}. Nothing goes out unless you approve it. Tap to see it.",
                    dry_run=False, priority="default", click=notify.link(f"/queue/{row['id']}"), conn=ctx.conn, agent=ctx.agent,
                    **content.ping_extras(ctx.conn, row, meta.get("art")))
        meta["nudged_at"] = db.utcnow()
        ctx.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps(meta), row["id"]))
        stats["nudged"] += 1
    return stats


def _set_last_error(conn, row, why: Optional[str]) -> None:
    if row["last_error"] != why:
        conn.execute("UPDATE content_queue SET last_error=?, updated_at=? WHERE id=?", (why, db.utcnow(), row["id"]))


# ------------------------------------------------------------------ the door

def _eligibility_module():
    """Imported at the moment of use, so a test can stand in for it and a broken module fails closed."""
    return importlib.import_module(ELIGIBILITY_MODULE)


def repeat_of(conn, row, ids: list[int], days: int, *, include_dry: bool = False) -> Optional[tuple[int, int]]:
    """(photo id, post id) when one of these photos went out within `days`: a post scheduled or published,
    or any post with a sent network in post_history (a post that half failed still went out).
    `include_dry` also counts dry-run rows (would_publish), so a dry run turns back what a live one would."""
    if not ids or days <= 0:
        return None
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    statuses = ("scheduled", "published") + (("would_publish",) if include_dry else ())
    marks = ",".join("?" for _ in statuses)
    wanted = set(ids)
    meta = _json(row["rule_report"], {}) if "rule_report" in row.keys() else {}
    story_of = meta.get("feed_of") if isinstance(meta, dict) else None     # a feed post's own Story is not a repeat (2026-10-15)
    for other in db.rows(conn, f"SELECT id, photo_ids FROM content_queue WHERE id != ? AND ("
                               f"(status IN ({marks}) AND COALESCE(published_at, updated_at) >= ?) "
                               "OR id IN (SELECT queue_id FROM post_history WHERE sent_at >= ?)) ORDER BY id DESC",
                         (row["id"], *statuses, cutoff, cutoff)):
        hit = wanted & set(photo_ids_of(other) or [])
        if hit and other["id"] != story_of:
            return min(hit), other["id"]
    return None


def door(ctx: runner.Context, row) -> Optional[tuple[str, str]]:
    """The last check before anything leaves. None to pass; else (action, why).
    'back' returns the row to Chris's drafts; 'hold' keeps it approved because the check itself could not run."""
    captions = captions_of(row)
    if captions is None:
        return "back", "The caption could not be read. Open the draft, fix it and approve again."
    official = is_official(ctx.conn, row["convention_id"])
    known_names = names.public_names(ctx.conn)          # no event or person is named (ai/names.py)
    for net in targets_of(row):
        report = copy_rules.check(captions.get(net, ""), official=official, names=known_names, social=True)
        if not report.ok:
            return "back", f"The {net} {CAPTION_BACK}: {report.blocks[0].message}."
    ids = photo_ids_of(row)
    if ids is None:
        return "back", "The photo list on this post could not be read. Pick the photo again."
    if ids:
        try:
            is_eligible = _eligibility_module().is_eligible
        except Exception as e:  # noqa: BLE001  fail closed: no check, no post
            return "hold", f"The photo check could not run ({type(e).__name__}: {e}). Nothing was sent."
        for pid in ids:
            try:
                ok, why = is_eligible(ctx.conn, pid)
            except Exception as e:  # noqa: BLE001
                return "hold", f"The photo check could not run for photo {pid} ({type(e).__name__}: {e}). Nothing was sent."
            if not ok:
                return "back", f"Photo {pid} can no longer be used: {why}. Pick another photo."
    days = config.repeat_window(ctx.cfg)          # the longer of PHOTO_REPEAT_DAYS and VARIETY_DAYS (2026-10-15)
    repeat = repeat_of(ctx.conn, row, ids, days, include_dry=ctx.dry_run)
    if repeat:
        pid, qid = repeat
        return "back", f"Photo {pid} already went out as post #{qid} in the last {days} days. Pick another photo."
    return None


def check_in(ctx: runner.Context, row) -> tuple[Optional[tuple[str, str]], object]:
    """The door, with the suite's own rewrite first. Chris, 2026-10-12: "I don't want to change any captions": a
    caption that breaks a rule now is rewritten here (agents/content.mend_captions, the template in dry run so
    nothing is spent) and checked again; one rewritten within the hour that still breaks goes back to him.
    Returns (stop, row): the row is reloaded after a rewrite so what goes out is the rewrite."""
    stop = door(ctx, row)
    if not (stop and stop[0] == "back" and CAPTION_BACK in stop[1]):
        return stop, row
    if mended_lately(row):
        return ("back", f"The suite rewrote the captions within the hour and one still breaks a rule. {stop[1]}"), row
    from ..ai import claude
    from . import content
    try:
        mend = content.mend_captions(ctx.conn, row, drafter=claude.TemplateDrafter() if ctx.dry_run else None, agent=ctx.agent)
    except Exception as e:  # noqa: BLE001  the rewrite could not run: said once; the row goes back as before
        runner.record_error_once(ctx.conn, ctx.agent, "mend", f"post {row['id']}: the captions could not be rewritten at the door: "
                                                              f"{type(e).__name__}: {e}")
        mend = None
    if mend is None:
        return stop, row
    row = db.one(ctx.conn, "SELECT * FROM content_queue WHERE id=?", (row["id"],))
    stop = door(ctx, row)
    if stop and stop[0] == "back" and CAPTION_BACK in stop[1]:
        stop = ("back", f"The suite rewrote the captions and one still breaks a rule. {stop[1]}")
    return stop, row


# ------------------------------------------------------------------ media

def clean_copy(ctx: runner.Context, src: Path, pid: int) -> Path:
    """A JPEG re-encoded from the pixels only (orientation applied): no camera data, no GPS,
    only the company's creator and copyright fields (render/meta.py)."""
    from PIL import Image, ImageOps
    from ..render.meta import save_jpeg
    dest = ctx.cfg.data_root / "renders" / "clean" / f"photo-{pid}.jpg"
    with Image.open(src) as im:
        save_jpeg(ImageOps.exif_transpose(im), dest, quality=92)
    return dest


def photo_urls(ctx: runner.Context, row, *, live: bool, uploader=None) -> list[str]:
    urls = []
    for pid in photo_ids_of(row) or []:
        photo = db.one(ctx.conn, "SELECT * FROM photos WHERE id=?", (pid,))
        if not photo:
            raise media.MediaError(f"photo {pid} is not in the library")
        if photo["public_url"]:
            urls.append(photo["public_url"])
            continue
        local = photo["local_path"]
        suffix = Path(local).suffix.lower() if local else ".jpg"
        if suffix not in POSTABLE_SUFFIXES:
            raise media.MediaError(f"photo {pid} is {suffix}, not a JPEG or PNG; it needs a rendered design")
        key = media.photo_key(photo["drive_id"], photo["md5"], ".jpg")
        if live:
            if not local or not Path(local).exists():
                raise media.MediaError(f"photo {pid} has no local copy to upload")
            # never the original file: a fresh copy from pixels, so no EXIF or GPS leaves the Mini
            url = (uploader or media.upload)(clean_copy(ctx, Path(local), pid), key)
            ctx.conn.execute("UPDATE photos SET public_url=? WHERE id=?", (url, pid))
            urls.append(url)
        else:
            urls.append(media.public_url(key))
    return urls


def media_urls(ctx: runner.Context, row, networks: list[str], *, live: bool, uploader=None,
               aspect_for: Optional[dict] = None) -> dict[str, list[str]]:
    """{network: [image url]}: the rendered design for the network's aspect when every file of it
    exists, else the photo's own copy. Each file is uploaded once per run, even when two networks share it."""
    rendered = render_paths_of(row)
    by_aspect: dict[str, list[str]] = {}
    raw: Optional[list[str]] = None
    out = {}
    for net in networks:
        aspect = (aspect_for or ASPECT_FOR).get(net, "4:5")
        paths = [p for p in (rendered.get(aspect) or []) if isinstance(p, str)]
        if paths and all(Path(p).exists() for p in paths):
            if aspect not in by_aspect:
                urls = []
                for i, path in enumerate(paths, start=1):
                    key = media.card_key(row["id"], aspect, i)
                    urls.append((uploader or media.upload)(Path(path), key) if live else media.public_url(key))
                by_aspect[aspect] = urls
            out[net] = by_aspect[aspect]
        else:
            if raw is None:
                raw = photo_urls(ctx, row, live=live, uploader=uploader)
            out[net] = raw
        if not out[net]:
            raise media.MediaError(f"no image for {net}: no rendered {aspect} design and no photo on the post")
    return out


def reel_files(row) -> Optional[tuple[Path, Optional[Path]]]:
    """(the reel's mp4, its cover or None) when the row is a reel, else None."""
    rendered = render_paths_of(row)
    videos = [p for p in rendered.get(VIDEO_ASPECT) or [] if isinstance(p, str) and p.lower().endswith(".mp4")]
    if not videos:
        return None
    covers = [p for p in rendered.get("cover") or [] if isinstance(p, str)]
    return Path(videos[0]), (Path(covers[0]) if covers else None)


def reel_urls(row, fields: list[dict], *, live: bool, uploader=None) -> tuple[str, str]:
    """(video url, cover url or ""): uploaded when live, else the URLs a live run would produce. The
    asset is checked against `fields` with those URLs first, so a refusal uploads nothing."""
    video, cover = reel_files(row)
    if not video.exists():
        raise media.MediaError(f"the reel's video is missing ({video.name}); draft it again")
    if cover is not None and not cover.exists():
        cover = None
    keys = (media.reel_key(row["id"], "video"), media.reel_key(row["id"], "cover"))
    would = (media.public_url(keys[0]), media.public_url(keys[1]) if cover else "")
    payloads.video_asset(fields, *would)
    if not live:
        return would
    up = uploader or media.upload
    return up(video, keys[0]), (up(cover, keys[1]) if cover else "")


# ------------------------------------------------------------------ publishing

def usable_networks(ctx: runner.Context, row) -> tuple[dict[str, dict], dict[str, str]]:
    """({network: channel row} that can go, {network: why not} for the rest). A network switched off on the Keys
    page (POST_NETWORKS; Instagram only by default, 2026-10-15) is left out quietly: no channel is expected for it."""
    active, skipped = {}, {}
    on = payloads.posting_networks()
    for net in targets_of(row):
        if net not in payloads.NETWORKS:
            skipped[net] = "not a network this suite posts to"
            continue
        if net not in on:
            continue
        ch = channel_for(ctx.conn, net)
        if not ch:
            skipped[net] = "no connected Buffer channel"
            continue
        if net == "pinterest" and not payloads.pinterest_board_id():
            skipped[net] = "PINTEREST_BOARD_ID is not set"
            continue
        active[net] = ch
    return active, skipped


def alt_text_of(row) -> str:
    """The alt text the content agent wrote for the post (rule_report alt_text), never a name."""
    meta = _json(row["rule_report"], {}) if "rule_report" in row.keys() else {}
    return (meta or {}).get("alt_text") or "" if isinstance(meta, dict) else ""


def build_payloads(ctx: runner.Context, row, channels: dict[str, dict], urls: dict[str, list[str]],
                   when: dict[str, Optional[str]], alt_path: Optional[list[str]] = None) -> dict[str, dict]:
    captions = captions_of(row) or {}
    built = {}
    for net, ch in channels.items():
        built[net] = payloads.build(net, ch["buffer_channel_id"], captions.get(net, ""), urls[net],
                                    scheduled_for=when.get(net), board_id=payloads.pinterest_board_id() or None,
                                    link=payloads.pinterest_link() or None, alt_text=alt_text_of(row), alt_path=alt_path)
    return built


def build_all(ctx: runner.Context, row, channels: dict[str, dict], when: dict[str, Optional[str]], *, live: bool,
              uploader=None, video_fields=None, alt_path=None) -> dict[str, dict]:
    """Every network's CreatePostInput, in channel order. On a reel row Instagram and Facebook get the
    video; `video_fields()` returns the video asset's fields (live: read from Buffer) and is asked before
    any upload, so a schema this code cannot fill stops the post with nothing uploaded."""
    reel_nets = [n for n in channels if n in payloads.REEL_NETWORKS] if reel_files(row) else []
    image_nets = {n: ch for n, ch in channels.items() if n not in reel_nets}
    if reel_nets:
        fields = video_fields()
        video_url, cover_url = reel_urls(row, fields, live=live, uploader=uploader)
    built = build_payloads(ctx, row, image_nets, media_urls(ctx, row, list(image_nets), live=live, uploader=uploader),
                           when, alt_path() if alt_path else None) if image_nets else {}
    if reel_nets:
        captions = captions_of(row) or {}
        for net in reel_nets:
            built[net] = payloads.build_reel(net, channels[net]["buffer_channel_id"], captions.get(net, ""),
                                             video_url, cover_url, fields, scheduled_for=when.get(net))
    return {n: built[n] for n in channels}


def publish_ready(ctx: runner.Context, client: Optional[BufferClient] = None, uploader=None,
                  now: Optional[datetime] = None) -> dict:
    live = not ctx.dry_run
    stats = {"would_publish": 0, "scheduled": 0, "failed": 0, "turned_back": 0, "held": 0, "skipped_networks": 0}
    rows = db.rows(ctx.conn, READY_SQL)
    if not rows:
        return stats
    if live:
        client = client or BufferClient.from_config(ctx.conn, ctx.agent)
        if client is None:
            record_once(ctx.conn, ctx.agent, "buffer_key_missing", "publisher is LIVE but BUFFER_API_KEY is not set; nothing sent")
            return stats
        if uploader is None and not media.configured():
            record_once(ctx.conn, ctx.agent, "media_missing", "publisher is LIVE but image hosting is not configured; nothing sent")
            return stats
    fields_read: list = []
    assumed: list = []

    def video_fields() -> list[dict]:
        """Live: Buffer's video asset fields, read once per run (two schema requests) and kept for the
        Buffer page and dry runs. Dry run: the fields last read, else the assumed two."""
        if not fields_read:
            if live:
                fields_read.append(client.video_asset_fields())
                settings.set(ctx.conn, VIDEO_FIELDS_KEY, json.dumps({"fields": fields_read[0], "checked_at": db.utcnow()}))
            else:
                try:
                    known = (json.loads(settings.get(ctx.conn, VIDEO_FIELDS_KEY) or "null") or {}).get("fields")
                except (ValueError, AttributeError):
                    known = None
                if not known:
                    assumed.append(True)
                fields_read.append(known or ASSUMED_VIDEO_FIELDS)
        return fields_read[0]

    alt_read: list = []

    def alt_path() -> Optional[list[str]]:
        """Where Buffer takes an image's alt text: read live once a run (and kept for dry runs and the
        Buffer page), else the last reading. None: Buffer offers no field, so no alt text is sent."""
        if not alt_read:
            if live:
                path = client.image_alt_path()
                settings.set(ctx.conn, IMAGE_ALT_KEY, json.dumps({"path": path, "checked_at": db.utcnow()}))
                alt_read.append(path)
            else:
                try:
                    alt_read.append((json.loads(settings.get(ctx.conn, IMAGE_ALT_KEY) or "null") or {}).get("path"))
                except (ValueError, AttributeError):
                    alt_read.append(None)
        return alt_read[0]

    for row in rows:
        stop, row = check_in(ctx, row)
        if stop:
            action, why = stop
            if action == "back":
                ctx.conn.execute("UPDATE content_queue SET status='draft', last_error=?, updated_at=? WHERE id=?",
                                 (why, db.utcnow(), row["id"]))
                runner.record_error(ctx.conn, ctx.agent, "door", f"post {row['id']} went back to drafts: {why}")
                stats["turned_back"] += 1
            else:
                _set_last_error(ctx.conn, row, why)
                record_once(ctx.conn, ctx.agent, "door_check", why)
                stats["held"] += 1
            continue
        fmt = instant_format(row)
        if fmt:
            from . import team
            room, why = team.room_for(ctx.conn, fmt, include_dry=not live, exclude=row["id"])
            if not room:                               # the day's cap on instant photos, everyone together (2026-10-15)
                ctx.conn.execute("UPDATE content_queue SET status='draft', last_error=?, updated_at=? WHERE id=?",
                                 (why, db.utcnow(), row["id"]))
                notify.push(f"{ctx.cfg.brand_name}: a photo waits", f"Post {row['id']} waits: {why}. Tap to see it.", dry_run=False,
                            priority="default", click=notify.link(f"/queue/{row['id']}"), conn=ctx.conn, agent=ctx.agent)
                stats["held"] += 1
                continue
        channels, skipped = usable_networks(ctx, row)
        if fmt == "story":
            skipped.update({n: "a Story goes to Instagram only" for n in channels if n != "instagram"})
            channels = {n: ch for n, ch in channels.items() if n == "instagram"}
        stats["skipped_networks"] += len(skipped)
        skip_note = ("Not sent to " + "; ".join(f"{n} ({why})" for n, why in skipped.items()) + ".") if skipped else None
        if not channels:
            _set_last_error(ctx.conn, row, NO_CHANNELS + (" " + skip_note if skip_note else ""))
            record_once(ctx.conn, ctx.agent, "no_channel", f"post {row['id']}: {NO_CHANNELS}")     # said once, not per run
            stats["waiting_for_channels"] = stats.get("waiting_for_channels", 0) + 1
            continue
        if skipped:
            record_once(ctx.conn, ctx.agent, "no_channel", f"post {row['id']}: {skip_note}")
        if posts_now(row):
            when = {net: None for net in channels}            # no time: the payload's mode is shareNow
        else:
            when = pacing.plan(ctx.conn, list(channels), row["scheduled_for"] or asap_slot(ctx, row, now), now, ctx.cfg,
                               include_dry=not live, not_before=for_day_of(row))
        no_day = [] if posts_now(row) else [n for n, v in when.items() if v is None]
        if no_day:
            why = NO_DAY.format(days=pacing.HORIZON_DAYS, nets=", ".join(no_day))
            _set_last_error(ctx.conn, row, why)
            record_once(ctx.conn, ctx.agent, "no_day", f"post {row['id']}: {why}")
            continue
        post_ids: dict[str, str] = {}
        built: dict[str, dict] = {}
        try:
            if fmt == "story":
                urls = media_urls(ctx, row, ["instagram"], live=live, uploader=uploader, aspect_for={"instagram": "story"})
                built = {"instagram": payloads.build("instagram", channels["instagram"]["buffer_channel_id"], "", urls["instagram"],
                                                     scheduled_for=when.get("instagram"), story=True)}
            else:
                built = build_all(ctx, row, channels, when, live=live, uploader=uploader, video_fields=video_fields,
                                  alt_path=alt_path)
            if fmt:                                        # the day it was handed to Buffer counts toward that day's cap
                from . import team
                meta = _json(row["rule_report"], {})
                meta["sent_on"] = team.today(ctx.cfg)
                ctx.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps(meta), row["id"]))
            if not live:
                note = " ".join(x for x in (skip_note, DRY_REEL_NOTE if assumed and reel_files(row)
                                            and any(n in payloads.REEL_NETWORKS for n in built) else None) if x) or None
                ctx.conn.execute("UPDATE content_queue SET status='would_publish', payload=?, dry_run=1, last_error=?, updated_at=? WHERE id=?",
                                 (json.dumps(built), note, db.utcnow(), row["id"]))
                stats["would_publish"] += 1
                ctx.log.info("DRY RUN post %s -> %s (not sent)", row["id"], ", ".join(built))
                continue
            for net, inp in built.items():
                post_ids[net] = client.create_post(inp)
                ctx.log.info("Buffer accepted post %s for %s: %s", row["id"], net, post_ids[net])
            ctx.conn.execute("UPDATE content_queue SET status='scheduled', payload=?, buffer_post_ids=?, dry_run=0, last_error=?, updated_at=? WHERE id=?",
                             (json.dumps(built), json.dumps(post_ids), skip_note, db.utcnow(), row["id"]))
            stats["scheduled"] += 1
        except (BufferBudgetExceeded, BufferRateLimited, BufferError, media.MediaError, payloads.PayloadError, OSError) as e:
            kind = "buffer_budget" if isinstance(e, (BufferBudgetExceeded, BufferRateLimited)) else type(e).__name__
            runner.record_error(ctx.conn, ctx.agent, kind, f"post {row['id']}: {e}")
            if post_ids:
                # some networks already have a real Buffer post: track those, say what did not go
                failed_nets = [n for n in built if n not in post_ids]
                why = f"Sent to {', '.join(post_ids)}; not sent to {', '.join(failed_nets)}: {e}"[:500]
                ctx.conn.execute("UPDATE content_queue SET status='scheduled', payload=?, buffer_post_ids=?, dry_run=0, last_error=?, updated_at=? WHERE id=?",
                                 (json.dumps({n: built[n] for n in post_ids}), json.dumps(post_ids), why, db.utcnow(), row["id"]))
                stats["scheduled"] += 1
            elif isinstance(e, (BufferBudgetExceeded, BufferRateLimited)):
                pass   # nothing left; the row stays approved for the next run
            else:
                ctx.conn.execute("UPDATE content_queue SET status='failed', last_error=?, updated_at=? WHERE id=?",
                                 (str(e)[:500], db.utcnow(), row["id"]))
                stats["failed"] += 1
            if isinstance(e, (BufferBudgetExceeded, BufferRateLimited)):
                ctx.log.warning("stopping this run: %s", e)
                break
    return stats


# Chris, 2026-10-15: "dashboard also says nothing has gone out yet and one did get posted within the last 24hrs". Every
# scheduled post was asked about every ten minutes, one due tomorrow as much as one due now: about 14 requests an hour,
# so the suite's own 24-hour Buffer ceiling (200) was reached by 12:34 UTC, every request after that was refused, and
# the post Buffer sent at 15:30 was never written down. A post is now asked about from just before its time, and once
# an hour one request reads what Buffer says was sent and writes down whatever the ten-minute check missed.
VERIFY_EARLY = timedelta(minutes=5)
RECONCILE_EVERY = timedelta(hours=1)
SENT_CHECKED_KEY = "buffer.sent_checked_at"
SENT_CACHE_KEY = "buffer.sent"          # what Buffer last said was sent on this company's channels (the Today page reads it)
SENT_KEEP = 20


def due_at(row) -> Optional[datetime]:
    """The earliest time Buffer holds one of this row's posts for (its payload's dueAt, on the networks Buffer has), or
    None when no time can be read: then the row is asked about, never left unchecked."""
    payload = _json(row["payload"], {}) or {}
    ids = _json(row["buffer_post_ids"], {}) or {}
    times = []
    for net in ids if isinstance(ids, dict) else []:
        try:
            dt = datetime.fromisoformat(str((payload.get(net) or {}).get("dueAt") or "").replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        times.append(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))
    return min(times) if times else None


def record_sent(conn, row, net: str, pid: str, sent_at: str, link: Optional[str], captions: dict) -> bool:
    """One network of a post went out: its post_history row (the Today page's Went out, the numbers). True when new."""
    if db.one(conn, "SELECT id FROM post_history WHERE buffer_post_id=?", (pid,)):
        if link:
            conn.execute("UPDATE post_history SET external_link=COALESCE(external_link, ?) WHERE buffer_post_id=?", (link, pid))
        return False
    db.insert(conn, "post_history", buffer_post_id=pid, queue_id=row["id"], service=net, sent_at=sent_at,
              caption=captions.get(net, ""), external_link=link)
    return True


def posted(ctx: runner.Context, row, nets: list[str]) -> None:
    """The row went out on every network it was sent to: published, and the ping that opens the post itself."""
    now = db.utcnow()
    ctx.conn.execute("UPDATE content_queue SET status='published', published_at=?, updated_at=? WHERE id=?", (now, now, row["id"]))
    links = {h["service"]: h["external_link"] for h in db.rows(ctx.conn, "SELECT service, external_link FROM post_history WHERE queue_id=?",
                                                              (row["id"],)) if h["external_link"]}
    live = next((links[n] for n in ("instagram", "facebook", "pinterest") if links.get(n)), next(iter(links.values()), None))
    meta = _json(row["rule_report"], {})
    if instant_format(row) == "story":
        # an instant photo's Story is up (2026-10-15): open it, Also post to the feed with one tap, the dashboard
        from ..core import approve_token
        fresh = db.one(ctx.conn, "SELECT * FROM content_queue WHERE id=?", (row["id"],))
        notify.push(f"{ctx.cfg.brand_name}: your photo is up as a Story",
                    f"Post {row['id']} is up as an Instagram Story. Tap to open it. Also post to the feed puts it on the grid "
                    "too. To take it down, open it there, tap the three dots, then Delete.",
                    dry_run=ctx.dry_run, priority="default", click=live or notify.link(f"/queue/{row['id']}"), conn=ctx.conn,
                    agent=ctx.agent, actions=notify.feed_actions(row["id"], approve_token.issue(ctx.conn, fresh), live))
        return
    if isinstance(meta, dict) and meta.get("source") in ("share", "team"):
        # Post to Event Caliber (2026-10-15): his send was his approval, so the ping is where it lives and how it comes down
        page = notify.link(f"/queue/{row['id']}")
        where = " and ".join(n.capitalize() for n in nets)
        notify.push(f"{ctx.cfg.brand_name}: your photo is on {where}",
                    f"Post {row['id']}, the photo you sent, is on {where}. Tap to open it. To take it down, open it there, "
                    "tap the three dots, then Delete. The dashboard has the post too.",
                    dry_run=ctx.dry_run, priority="default", click=live or page, conn=ctx.conn, agent=ctx.agent,
                    actions=(f"view, Instagram, {live}; " if live else "") + f"view, Dashboard, {page}")
        return
    notify.push(f"{ctx.cfg.brand_name}: posted", f"Post {row['id']} went out on {', '.join(nets)}. Tap to see it.",
                dry_run=ctx.dry_run, priority="default", click=live or notify.link(f"/queue/{row['id']}"), conn=ctx.conn, agent=ctx.agent)


def verify_scheduled(ctx: runner.Context, client: Optional[BufferClient] = None, now: Optional[datetime] = None) -> dict:
    """Ask Buffer about each scheduled row that is due (from VERIFY_EARLY before its time on). A network Buffer says went
    out is written down at once; the row settles once every network is sent or errored."""
    stats = {"published": 0, "failed": 0, "pending": 0, "not_due": 0}
    now_dt = now or datetime.now(timezone.utc)
    due_rows = []
    for row in db.rows(ctx.conn, "SELECT * FROM content_queue WHERE status='scheduled' AND buffer_post_ids IS NOT NULL ORDER BY id"):
        due = due_at(row)
        if due is not None and due > now_dt + VERIFY_EARLY:
            stats["not_due"] += 1                 # not its time yet: no request spent on it
            continue
        due_rows.append(row)
    if not due_rows:
        return stats
    client = client or BufferClient.from_config(ctx.conn, ctx.agent)
    if client is None:
        return stats
    for row in due_rows:
        ids = _json(row["buffer_post_ids"], {}) or {}
        infos: dict[str, dict] = {}
        try:
            for net, pid in ids.items():
                try:
                    infos[net] = client.post_info(pid)
                except (BufferBudgetExceeded, BufferRateLimited):
                    raise
                except BufferError as e:          # one network unreadable: the others are still written down
                    runner.record_error_once(ctx.conn, ctx.agent, "verify_failed", f"post {row['id']}, {net}: {e}")
        except (BufferBudgetExceeded, BufferRateLimited) as e:
            record_once(ctx.conn, ctx.agent, "buffer_budget", str(e))
            break
        stamp = db.utcnow()
        captions = captions_of(row) or {}
        for net, info in infos.items():
            if info["status"] in TERMINAL_OK:
                record_sent(ctx.conn, row, net, ids[net], info["sent_at"] or stamp, info.get("external_link"), captions)
        bad = {net: i for net, i in infos.items() if i["status"] in TERMINAL_BAD}
        if bad:
            why = "Buffer could not send it: " + "; ".join(f"{net}: {i['error'] or i['status']}" for net, i in bad.items())
            if row["last_error"] != why:
                runner.record_error(ctx.conn, ctx.agent, "post_error", f"post {row['id']}: {why}")
                ctx.conn.execute("UPDATE content_queue SET last_error=?, updated_at=? WHERE id=?", (why[:500], stamp, row["id"]))
        if len(infos) < len(ids) or not all(i["status"] in TERMINAL_OK | TERMINAL_BAD for i in infos.values()):
            stats["pending"] += 1
            continue
        if bad:
            ctx.conn.execute("UPDATE content_queue SET status='failed', updated_at=? WHERE id=?", (stamp, row["id"]))
            stats["failed"] += 1
        else:
            posted(ctx, row, list(infos))
            stats["published"] += 1
    return stats


def reconcile_sent(ctx: runner.Context, client: Optional[BufferClient] = None, now: Optional[datetime] = None) -> dict:
    """Once an hour, one request: what Buffer says was sent on this company's connected channels. Each of the suite's
    posts among them is written to post_history and a scheduled row whose every network went out is published, whatever
    the ten-minute check managed; the list itself is kept (SENT_CACHE_KEY) so a post sent from Buffer directly shows on
    Today too. Never past the budget: at the ceiling it asks nothing and says so once."""
    stats = {"seen": 0, "recorded": 0, "published": 0}
    now_dt = now or datetime.now(timezone.utc)
    try:
        last = datetime.fromisoformat(settings.get(ctx.conn, SENT_CHECKED_KEY) or "")
        if now_dt - last < RECONCILE_EVERY:
            return stats
    except ValueError:
        pass
    channels = {r["buffer_channel_id"]: r["service"] for r in db.rows(ctx.conn, "SELECT buffer_channel_id, service FROM channels WHERE connected=1")}
    if not channels:
        return stats
    client = client or BufferClient.from_config(ctx.conn, ctx.agent)
    if client is None:
        return stats
    try:
        nodes, _ = client.posts(status="sent", channel_ids=list(channels), first=SENT_KEEP)
    except (BufferBudgetExceeded, BufferRateLimited) as e:
        record_once(ctx.conn, ctx.agent, "buffer_budget", str(e))
        return stats
    except BufferError as e:
        runner.record_error_once(ctx.conn, ctx.agent, "sent_check", f"Buffer's list of sent posts could not be read: {e}")
        return stats
    settings.set(ctx.conn, SENT_CHECKED_KEY, now_dt.isoformat(timespec="seconds"))
    sent = {n["id"]: n for n in nodes if n.get("id") and str(n.get("status") or "sent").lower() in TERMINAL_OK}
    settings.set(ctx.conn, SENT_CACHE_KEY, json.dumps([
        {"id": pid, "service": channels.get(n.get("channelId")) or str(n.get("channelService") or "").lower(),
         "sent_at": n.get("sentAt"), "link": n.get("externalLink"), "text": (n.get("text") or "")[:280]} for pid, n in sent.items()]))
    stats["seen"] = len(sent)
    for row in db.rows(ctx.conn, "SELECT * FROM content_queue WHERE buffer_post_ids IS NOT NULL AND status IN ('scheduled', 'failed', 'published')"):
        ids = _json(row["buffer_post_ids"], {}) or {}
        captions = captions_of(row) or {}
        for net, pid in ids.items():
            n = sent.get(pid)
            if n and record_sent(ctx.conn, row, net, pid, n.get("sentAt") or db.utcnow(), n.get("externalLink"), captions):
                stats["recorded"] += 1
        if row["status"] == "scheduled" and ids and all(db.one(ctx.conn, "SELECT 1 FROM post_history WHERE buffer_post_id=?", (pid,))
                                                         for pid in ids.values()):
            posted(ctx, row, list(ids))
            stats["published"] += 1
    return stats


def run(ctx: runner.Context) -> str:
    t = tend_drafts(ctx)
    p = publish_ready(ctx)
    v = verify_scheduled(ctx)
    r = reconcile_sent(ctx)
    snap = budget.snapshot(ctx.conn)
    used = "/".join(str(s["used"]) for s in snap)
    return (f"{'DRY RUN ' if ctx.dry_run else ''}would_publish={p['would_publish']} scheduled={p['scheduled']} failed={p['failed']} "
            f"turned_back={p['turned_back']} held={p['held']} skipped_networks={p['skipped_networks']}; "
            f"drafts waiting={t['waiting']} nudged={t['nudged']}; "
            f"verified published={v['published']} failed={v['failed']} pending={v['pending']} not_due={v['not_due']}; "
            f"sent per Buffer seen={r['seen']} recorded={r['recorded']} published={r['published']}; "
            f"buffer requests 15m/24h/30d={used}")


if __name__ == "__main__":
    runner.main_for("publisher", run)
