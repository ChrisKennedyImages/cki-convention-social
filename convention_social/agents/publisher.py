"""Publisher agent: approved posts -> Buffer, then verify Buffer actually sent them.

Ready = content_queue status 'approved' (Chris pressed Approve on the
dashboard). Before anything leaves, the door re-checks the row (see door()).
For each targeted network there must be a connected row in `channels`
(service = instagram | facebook | pinterest); a pin also needs
PINTEREST_BOARD_ID. Each network gets its own time from pacing.py unless
Chris chose one on the draft. Media: the rendered design for the network's
aspect (render_paths {aspect: [paths]}: instagram and facebook 4:5,
pinterest 2:3), else the photo's own local copy.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from ..ai import copy_rules
from ..buffer import budget, media, payloads
from ..buffer.client import BufferBudgetExceeded, BufferClient, BufferError, BufferRateLimited
from ..core import db, runner
from . import pacing

READY_SQL = "SELECT * FROM content_queue WHERE status = 'approved' ORDER BY COALESCE(approved_at, created_at), id"
TERMINAL_OK = {"sent"}
TERMINAL_BAD = {"error"}
ASPECT_FOR = {"instagram": "4:5", "facebook": "4:5", "pinterest": "2:3"}
POSTABLE_SUFFIXES = {".jpg", ".jpeg", ".png"}
ELIGIBILITY_MODULE = "convention_social.library.eligibility"

NO_CHANNELS = "No connected Buffer channel for any network on this post. Connect them in Buffer, then this goes out on the next run."
NO_DAY = "No open day in the next {days} days for {nets}. Choose a time on the draft."


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
    for other in db.rows(conn, f"SELECT id, photo_ids FROM content_queue WHERE id != ? AND ("
                               f"(status IN ({marks}) AND COALESCE(published_at, updated_at) >= ?) "
                               "OR id IN (SELECT queue_id FROM post_history WHERE sent_at >= ?)) ORDER BY id DESC",
                         (row["id"], *statuses, cutoff, cutoff)):
        hit = wanted & set(photo_ids_of(other) or [])
        if hit:
            return min(hit), other["id"]
    return None


def door(ctx: runner.Context, row) -> Optional[tuple[str, str]]:
    """The last check before anything leaves. None to pass; else (action, why).
    'back' returns the row to Chris's drafts; 'hold' keeps it approved because the check itself could not run."""
    captions = captions_of(row)
    if captions is None:
        return "back", "The caption could not be read. Open the draft, fix it and approve again."
    official = is_official(ctx.conn, row["convention_id"])
    for net in targets_of(row):
        report = copy_rules.check(captions.get(net, ""), official=official)
        if not report.ok:
            return "back", f"The {net} caption no longer passes the rules: {report.blocks[0].message}. Fix it and approve again."
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
    days = ctx.cfg.photo_repeat_days
    repeat = repeat_of(ctx.conn, row, ids, days, include_dry=ctx.dry_run)
    if repeat:
        pid, qid = repeat
        return "back", f"Photo {pid} already went out as post #{qid} in the last {days} days. Pick another photo."
    return None


# ------------------------------------------------------------------ media

def clean_copy(ctx: runner.Context, src: Path, pid: int) -> Path:
    """A JPEG re-encoded from the pixels only (orientation applied), with no metadata at all."""
    from PIL import Image, ImageOps
    dest = ctx.cfg.data_root / "renders" / "clean" / f"photo-{pid}.jpg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        ImageOps.exif_transpose(im).convert("RGB").save(dest, format="JPEG", quality=92, optimize=True)
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


def media_urls(ctx: runner.Context, row, networks: list[str], *, live: bool, uploader=None) -> dict[str, list[str]]:
    """{network: [image url]}: the rendered design for the network's aspect when every file of it
    exists, else the photo's own copy. Each file is uploaded once per run, even when two networks share it."""
    rendered = render_paths_of(row)
    by_aspect: dict[str, list[str]] = {}
    raw: Optional[list[str]] = None
    out = {}
    for net in networks:
        aspect = ASPECT_FOR.get(net, "4:5")
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


# ------------------------------------------------------------------ publishing

def usable_networks(ctx: runner.Context, row) -> tuple[dict[str, dict], dict[str, str]]:
    """({network: channel row} that can go, {network: why not} for the rest)."""
    active, skipped = {}, {}
    for net in targets_of(row):
        if net not in payloads.NETWORKS:
            skipped[net] = "not a network this suite posts to"
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


def build_payloads(ctx: runner.Context, row, channels: dict[str, dict], urls: dict[str, list[str]],
                   when: dict[str, Optional[str]]) -> dict[str, dict]:
    captions = captions_of(row) or {}
    built = {}
    for net, ch in channels.items():
        built[net] = payloads.build(net, ch["buffer_channel_id"], captions.get(net, ""), urls[net],
                                    scheduled_for=when.get(net), board_id=payloads.pinterest_board_id() or None,
                                    link=payloads.pinterest_link() or None)
    return built


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
    for row in rows:
        stop = door(ctx, row)
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
        channels, skipped = usable_networks(ctx, row)
        stats["skipped_networks"] += len(skipped)
        skip_note = ("Not sent to " + "; ".join(f"{n} ({why})" for n, why in skipped.items()) + ".") if skipped else None
        if not channels:
            _set_last_error(ctx.conn, row, NO_CHANNELS + (" " + skip_note if skip_note else ""))
            stats["waiting_for_channels"] = stats.get("waiting_for_channels", 0) + 1
            continue
        if skipped:
            record_once(ctx.conn, ctx.agent, "no_channel", f"post {row['id']}: {skip_note}")
        when = pacing.plan(ctx.conn, list(channels), row["scheduled_for"], now, ctx.cfg, include_dry=not live)
        no_day = [n for n, v in when.items() if v is None]
        if no_day:
            _set_last_error(ctx.conn, row, NO_DAY.format(days=pacing.HORIZON_DAYS, nets=", ".join(no_day)))
            continue
        post_ids: dict[str, str] = {}
        built: dict[str, dict] = {}
        try:
            urls = media_urls(ctx, row, list(channels), live=live, uploader=uploader)
            built = build_payloads(ctx, row, channels, urls, when)
            if not live:
                ctx.conn.execute("UPDATE content_queue SET status='would_publish', payload=?, dry_run=1, last_error=?, updated_at=? WHERE id=?",
                                 (json.dumps(built), skip_note, db.utcnow(), row["id"]))
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


def verify_scheduled(ctx: runner.Context, client: Optional[BufferClient] = None) -> dict:
    """Poll every scheduled row's Buffer posts. A row settles once every network is sent or errored."""
    stats = {"published": 0, "failed": 0, "pending": 0}
    rows = db.rows(ctx.conn, "SELECT * FROM content_queue WHERE status='scheduled' AND buffer_post_ids IS NOT NULL ORDER BY id")
    if not rows:
        return stats
    client = client or BufferClient.from_config(ctx.conn, ctx.agent)
    if client is None:
        return stats
    for row in rows:
        ids = _json(row["buffer_post_ids"], {}) or {}
        infos: dict[str, dict] = {}
        try:
            for net, pid in ids.items():
                infos[net] = client.post_info(pid)
        except (BufferBudgetExceeded, BufferRateLimited) as e:
            record_once(ctx.conn, ctx.agent, "buffer_budget", str(e))
            break
        except BufferError as e:
            runner.record_error(ctx.conn, ctx.agent, "verify_failed", f"post {row['id']}: {e}")
            continue
        bad = {net: i for net, i in infos.items() if i["status"] in TERMINAL_BAD}
        if bad:
            why = "Buffer could not send it: " + "; ".join(f"{net}: {i['error'] or i['status']}" for net, i in bad.items())
            if row["last_error"] != why:
                runner.record_error(ctx.conn, ctx.agent, "post_error", f"post {row['id']}: {why}")
                ctx.conn.execute("UPDATE content_queue SET last_error=?, updated_at=? WHERE id=?", (why[:500], db.utcnow(), row["id"]))
        if not all(i["status"] in TERMINAL_OK | TERMINAL_BAD for i in infos.values()):
            stats["pending"] += 1
            continue
        now = db.utcnow()
        captions = captions_of(row) or {}
        for net, info in infos.items():
            if info["status"] in TERMINAL_OK and not db.one(ctx.conn, "SELECT id FROM post_history WHERE buffer_post_id=?", (ids[net],)):
                db.insert(ctx.conn, "post_history", buffer_post_id=ids[net], queue_id=row["id"], service=net,
                          sent_at=info["sent_at"] or now, caption=captions.get(net, ""))
        if bad:
            ctx.conn.execute("UPDATE content_queue SET status='failed', updated_at=? WHERE id=?", (now, row["id"]))
            stats["failed"] += 1
        else:
            ctx.conn.execute("UPDATE content_queue SET status='published', published_at=?, updated_at=? WHERE id=?", (now, now, row["id"]))
            stats["published"] += 1
    return stats


def run(ctx: runner.Context) -> str:
    p = publish_ready(ctx)
    v = verify_scheduled(ctx)
    snap = budget.snapshot(ctx.conn)
    used = "/".join(str(s["used"]) for s in snap)
    return (f"{'DRY RUN ' if ctx.dry_run else ''}would_publish={p['would_publish']} scheduled={p['scheduled']} failed={p['failed']} "
            f"turned_back={p['turned_back']} held={p['held']} skipped_networks={p['skipped_networks']}; "
            f"verified published={v['published']} failed={v['failed']} pending={v['pending']}; "
            f"buffer requests 15m/24h/30d={used}")


if __name__ == "__main__":
    runner.main_for("publisher", run)
