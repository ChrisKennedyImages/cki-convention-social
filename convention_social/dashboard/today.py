"""The Today page: everything about today's posts in one place (Chris, 2026-10-15: "we really need to fix this dashboard.
its very difficult to understand the UX and UI. design samples is completely in a different place then todays posts and
today has no sign of design examples").

Three parts, top to bottom: Needs you (every draft waiting on his approve, newest first, each with Post now, Follow
the pace and Skip, a reel playing inline with its sound; then what else needs him, each alert with its fix), This
week (what is scheduled, by day, as thumbnails) and Went out (the last few posts, each with its link on Instagram
when Buffer gave one). The old Queue, Posts and Design pages fold into it and their addresses answer with a redirect.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..core import config, db, settings
from . import alerts

# plain words for each state a post can be in (2026-10-15: "rejected" became Skipped, "would publish" a practice run)
STATUS_WORDS = {"draft": "To approve", "approved": "Approved", "would_publish": "Practice run (posting is off)",
                "scheduled": "Scheduled", "published": "Went out", "failed": "Did not go out", "rejected": "Skipped"}
WEEK_STATUSES = ("approved", "scheduled", "would_publish")
WENT_OUT = 6


def meta_of(row) -> dict:
    try:
        meta = json.loads(row["rule_report"] or "{}")
    except (TypeError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def origin(row) -> str:
    """Where a draft came from, in a few words."""
    meta = meta_of(row)
    source = meta.get("source")
    if source == "designed":
        return "Designed for today"
    if source == "phone":
        return "Your photo from the floor"
    if source == "sample":
        return "From an idea you chose"
    try:
        return f"The daily post for {date.fromisoformat(meta.get('for_day') or ''):%A}"
    except ValueError:
        return "A post"


def choosable(item: dict) -> bool:
    """Post now and Follow the pace show only where the approve would pass: the rules, the photos, a network, and the
    art director passed or did not look (a redo or a turn-back is his to open first)."""
    verdict = (item.get("art") or {}).get("verdict") or ""
    return (item["status"] == "draft" and not item["blocked_networks"] and not item["ineligible"] and bool(item["targets"])
            and verdict in ("pass", "not reviewed", ""))


def card_path(row) -> Optional[str]:
    """The address of a post's first card: a reel's cover, else the 4:5 card, else the 2:3 card."""
    try:
        renders = json.loads(row["render_paths"] or "{}")
    except (TypeError, ValueError):
        return None
    order = ("cover", "4:5", "2:3") if renders.get("9:16") else ("4:5", "2:3", "cover")
    for aspect in order:
        if renders.get(aspect):
            return f"/media/render/{row['id']}/{aspect.replace(':', 'x')}/1"
    return None


def local_now(now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(config.get_config().timezone))


def goes_out_at(conn: sqlite3.Connection, row, *, now: Optional[datetime] = None, publisher_dry: Optional[bool] = None) -> Optional[datetime]:
    """When an approved, scheduled or practice-run post goes out, local time, on the first network that is on."""
    from ..agents import pacing, publisher
    tz = ZoneInfo(config.get_config().timezone)
    on = alerts.networks_on()
    if row["status"] in ("scheduled", "would_publish", "published"):
        times = [t for n, t in pacing.due_times(row, tz).items() if n in on]
        return min(times) if times else None
    if row["status"] != "approved":
        return None
    if meta_of(row).get("asap") and not row["scheduled_for"]:
        return local_now(now) + publisher.ASAP_AFTER
    slot = pace_slot(conn, row, now=now, publisher_dry=publisher_dry)
    return slot.replace(tzinfo=tz) if slot else None


def week(conn: sqlite3.Connection, now: Optional[datetime] = None) -> list[dict]:
    """The next seven days from today, each with what is set to go out on it: [{day, label, items}]."""
    start = local_now(now).date()
    days = [start + timedelta(days=i) for i in range(7)]
    out = {d: [] for d in days}
    dry = settings.dry_run(conn, "publisher")
    for r in db.rows(conn, f"SELECT * FROM content_queue WHERE kind='photo' AND status IN ({','.join('?' * len(WEEK_STATUSES))}) "
                           "ORDER BY id", WEEK_STATUSES):
        when = goes_out_at(conn, r, now=now, publisher_dry=dry)
        if when is None or when.date() not in out:
            continue
        out[when.date()].append({"id": r["id"], "time": clock(when),
                                 "at": when, "status": r["status"], "words": STATUS_WORDS.get(r["status"], r["status"]),
                                 "card": card_path(r), "video": _is_reel(r)})
    return [{"day": d, "label": "Today" if i == 0 else ("Tomorrow" if i == 1 else f"{d:%A}"), "date": f"{d:%b} {d.day}",
             "items": sorted(out[d], key=lambda x: x["at"])} for i, d in enumerate(days)]


def _is_reel(row) -> bool:
    try:
        return any(str(p).lower().endswith(".mp4") for p in json.loads(row["render_paths"] or "{}").get("9:16") or [])
    except (TypeError, ValueError, AttributeError):
        return False


def went_out(conn: sqlite3.Connection, n: int = WENT_OUT) -> list[dict]:
    """The last n posts that went out, newest first: when, where, the card, and the link to each network's post."""
    out = []
    for g in db.rows(conn, "SELECT queue_id, MAX(COALESCE(sent_at, '')) AS sent FROM post_history WHERE queue_id IS NOT NULL "
                           "GROUP BY queue_id ORDER BY sent DESC LIMIT ?", (n,)):
        row = db.one(conn, "SELECT * FROM content_queue WHERE id=?", (g["queue_id"],))
        links = [{"service": h["service"], "href": h["external_link"]}
                 for h in db.rows(conn, "SELECT service, external_link FROM post_history WHERE queue_id=? ORDER BY "
                                        "CASE service WHEN 'instagram' THEN 0 ELSE 1 END, id", (g["queue_id"],))]
        try:
            sent = datetime.fromisoformat((g["sent"] or "").replace("Z", "+00:00")).astimezone(ZoneInfo(config.get_config().timezone))
            when = f"{sent:%A} {sent:%b} {sent.day}, {clock(sent)}"
        except ValueError:
            when = ""
        out.append({"id": g["queue_id"], "when": when, "card": card_path(row) if row else None, "links": links,
                    "video": _is_reel(row) if row else False})
    return out


def pace_slot(conn: sqlite3.Connection, row, *, now: Optional[datetime] = None, publisher_dry: Optional[bool] = None) -> Optional[datetime]:
    """Where the pace puts a post (local, naive): the next open slot on the first network that is on, from the day it
    was drafted for; a time he set on the draft wins."""
    from ..agents import pacing, publisher
    cfg = config.get_config()
    targets = [t for t in json.loads(row["targets"] or "[]") if t in alerts.networks_on()]
    dry = settings.dry_run(conn, "publisher") if publisher_dry is None else publisher_dry
    try:
        plan = pacing.plan(conn, targets, row["scheduled_for"], now, cfg, include_dry=dry, not_before=publisher.for_day_of(row))
    except Exception:  # noqa: BLE001  the time is a courtesy on this page
        return None
    slots = sorted(v for v in plan.values() if v)
    return datetime.fromisoformat(slots[0]) if slots else None


def clock(when: datetime) -> str:
    return f"{(when.hour % 12) or 12}:{when.minute:02d} {'am' if when.hour < 12 else 'pm'}"


def day_words(when: datetime, now: Optional[datetime] = None) -> str:
    today_ = local_now(now).date()
    d = when.date()
    return "today" if d == today_ else ("tomorrow" if d == today_ + timedelta(days=1) else f"{d:%A}")


def local_words(ts: str, now: Optional[datetime] = None) -> str:
    """A stored UTC time in his own words: "today 3:09 pm", "yesterday 9:40 am", "Oct 13, 3:09 pm"."""
    try:
        when = datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return ts or ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    when = when.astimezone(ZoneInfo(config.get_config().timezone))
    today_ = local_now(now).date()
    day = ("today" if when.date() == today_ else "yesterday" if when.date() == today_ - timedelta(days=1)
           else f"{when:%b} {when.day}")
    return f"{day} {clock(when)}"


def practice(conn: Optional[sqlite3.Connection]) -> Optional[dict]:
    """The banner: what is in practice run (dry run) and so not going out, or None. Fail closed: a switch that cannot
    be read is a practice run."""
    try:
        pub = settings.dry_run(conn, "publisher") if conn is not None else True
        con = settings.dry_run(conn, "content") if conn is not None else True
    except Exception:  # noqa: BLE001
        pub = con = True
    if not (pub or con):
        return None
    lines = []
    if pub:
        lines.append("The publisher is in practice run, so nothing you approve goes out to Instagram. It waits as a practice "
                     "run and goes out when the publisher is switched on.")
    if con:
        lines.append("The content lane is in practice run: no designed drafts are made, and the daily draft has the "
                     "template's captions and no final check, so it cannot post.")
    return {"headline": "Posts are not going out." if pub else "New drafts cannot go out.", "lines": lines}
