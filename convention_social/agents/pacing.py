"""When an approved post goes out: one post a day per network, at that network's time.

Starting times, local to TIMEZONE (Eastern by default; FOUNDER_DECISIONS.md
2026-10-09, from general industry data, not this account's own numbers):
Instagram 11:30 on weekdays and 10:00 on weekends, Facebook 09:30, Pinterest
20:30. POST_TIMES overrides any of them, e.g.
"instagram=11:30,facebook=09:30,pinterest=20:30" (that time every day) or
"instagram=11:30/10:00" (weekdays/weekends). Unknown networks and unreadable
times in POST_TIMES are ignored and the default stands.

A post with no time chosen takes, for each network it targets, the first
local day from today on where that network has nothing out or queued, at that
network's time, at least LEAD from now. A time Chris sets on the draft always
wins, for every network on it.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..core import config, db
from . import learner

DEFAULT_TIMES: dict[str, tuple[time, time]] = {      # network: (weekdays, weekends)
    "instagram": (time(11, 30), time(10, 0)),
    "facebook": (time(9, 30), time(9, 30)),
    "pinterest": (time(20, 30), time(20, 30)),
}
FALLBACK_TIME = time(12, 0)
LEAD = timedelta(minutes=30)
HORIZON_DAYS = 90
TAKEN_STATUSES = ("scheduled", "published")


def parse_clock(text: str) -> Optional[time]:
    try:
        hh, mm = text.strip().split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def times_table() -> dict[str, tuple[time, time]]:
    """The defaults with POST_TIMES applied."""
    table = dict(DEFAULT_TIMES)
    for part in (config.getenv("POST_TIMES", "") or "").split(","):
        if "=" not in part:
            continue
        net, _, value = part.partition("=")
        net = net.strip().lower()
        if net not in DEFAULT_TIMES:
            continue
        weekday_s, slash, weekend_s = value.partition("/")
        weekday = parse_clock(weekday_s)
        weekend = parse_clock(weekend_s) if slash else weekday
        if weekday and weekend:
            table[net] = (weekday, weekend)
    return table


def time_for(network: str, day: date) -> time:
    weekday, weekend = times_table().get(network, (FALLBACK_TIME, FALLBACK_TIME))
    return weekend if day.weekday() >= 5 else weekday


def _clock(t: time) -> str:
    return f"{(t.hour % 12) or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def describe() -> str:
    """'Instagram 11:30 am weekdays, 10:00 am weekends. Facebook 9:30 am. Pinterest 8:30 pm.' for the dashboard."""
    parts = []
    for net, (weekday, weekend) in times_table().items():
        when = _clock(weekday) if weekday == weekend else f"{_clock(weekday)} weekdays, {_clock(weekend)} weekends"
        parts.append(f"{net.capitalize()} {when}.")
    return " ".join(parts)


def _local(value: Optional[str], tz: ZoneInfo, *, naive_is_local: bool) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz if naive_is_local else timezone.utc)
    return dt.astimezone(tz)


def due_times(row, tz: ZoneInfo) -> dict[str, datetime]:
    """{network: local time} a scheduled or published row goes out at, from its stored payload
    (dueAt per network), else its chosen time, else when it was published or last updated."""
    try:
        targets = json.loads(row["targets"] or "[]")
    except (TypeError, ValueError):
        targets = []
    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    out = {}
    for net in targets:
        dt = None
        if isinstance(payload, dict) and isinstance(payload.get(net), dict):
            dt = _local(payload[net].get("dueAt"), tz, naive_is_local=False)
        dt = dt or _local(row["scheduled_for"], tz, naive_is_local=True)
        dt = dt or _local(row["published_at"] or row["updated_at"], tz, naive_is_local=False)
        if dt:
            out[net] = dt
    return out


def taken_days(conn, network: str, tz: ZoneInfo, *, include_dry: bool = False) -> set[date]:
    """Local days this network already has something out or queued.
    `include_dry` also counts dry-run rows (would_publish), so a dry run paces the way a live one would."""
    statuses = TAKEN_STATUSES + (("would_publish",) if include_dry else ())
    marks = ",".join("?" for _ in statuses)
    days = set()
    for r in db.rows(conn, f"SELECT targets, payload, scheduled_for, published_at, updated_at FROM content_queue "
                           f"WHERE status IN ({marks})", statuses):
        dt = due_times(r, tz).get(network)
        if dt:
            days.add(dt.date())
    for r in db.rows(conn, "SELECT sent_at FROM post_history WHERE service=?", (network,)):
        dt = _local(r["sent_at"], tz, naive_is_local=False)
        if dt:
            days.add(dt.date())
    return days


def next_slot(conn, network: str, now: Optional[datetime] = None, cfg: Optional[config.Config] = None, *,
              include_dry: bool = False) -> Optional[datetime]:
    """The local time this network's next unscheduled post should go out, or None if every day
    in the next HORIZON_DAYS is taken."""
    cfg = cfg or config.get_config()
    tz = ZoneInfo(cfg.timezone)
    local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
    taken = taken_days(conn, network, tz, include_dry=include_dry)
    for i in range(HORIZON_DAYS):
        day = local_now.date() + timedelta(days=i)
        if day in taken:
            continue
        slot = datetime.combine(day, learner.post_time_for(conn, network, time_for(network, day), day), tz)
        if slot > local_now + LEAD:
            return slot
    return None


def slot_value(slot: datetime) -> str:
    """The form the dashboard and the payload builder use: local 'YYYY-MM-DDTHH:MM'."""
    return slot.strftime("%Y-%m-%dT%H:%M")


def plan(conn, targets: list[str], chosen: Optional[str], now: Optional[datetime] = None,
         cfg: Optional[config.Config] = None, *, include_dry: bool = False) -> dict[str, Optional[str]]:
    """{network: local 'YYYY-MM-DDTHH:MM' or None}. A time chosen on the draft wins for every network;
    None means no open day was found in the horizon."""
    if chosen:
        return {net: chosen for net in targets}
    out = {}
    for net in targets:
        slot = next_slot(conn, net, now, cfg, include_dry=include_dry)
        out[net] = slot_value(slot) if slot else None
    return out
