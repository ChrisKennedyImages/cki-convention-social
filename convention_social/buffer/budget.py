"""Buffer request budget: rolling 15-minute, 24-hour and 30-day windows per API key.

Limits from developers.buffer.com/guides/api-limits.html (read 2026-09-16):
Free 100/250/3,000, Essentials 100/250/7,500, Team 100/500/15,000. Every request
this suite makes is one api_usage row (provider='buffer'); `allow()` says no once
any window has used SAFETY of its limit, so the last 20% stays free for Buffer's
own dashboard and for retries. The watchdog reads `snapshot()`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ..core import config, db

LIMITS = {"free": (100, 250, 3_000), "essentials": (100, 250, 7_500), "team": (100, 500, 15_000)}
WINDOWS = (("15m", 900), ("24h", 86_400), ("30d", 30 * 86_400))
SAFETY = 0.8


def plan_limits(plan: str | None = None) -> tuple[int, int, int]:
    plan = (plan or config.get_config().buffer_plan or "essentials").lower()
    return LIMITS.get(plan, LIMITS["essentials"])


def counts(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    out = {}
    for name, seconds in WINDOWS:
        since = (now - timedelta(seconds=seconds)).isoformat()
        out[name] = db.one(conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='buffer' AND ts >= ?", (since,))["n"]
    return out


def snapshot(conn: sqlite3.Connection, plan: str | None = None, now: datetime | None = None) -> list[dict]:
    used = counts(conn, now)
    return [{"window": name, "used": used[name], "limit": limit, "ceiling": int(limit * SAFETY)}
            for (name, _), limit in zip(WINDOWS, plan_limits(plan))]


def allow(conn: sqlite3.Connection, plan: str | None = None, now: datetime | None = None) -> tuple[bool, str]:
    for row in snapshot(conn, plan, now):
        if row["used"] >= row["ceiling"]:
            return False, f"Buffer {row['window']} window at {row['used']}/{row['limit']} (ceiling {row['ceiling']})"
    return True, ""


def record(conn: sqlite3.Connection, agent: str, detail: str) -> None:
    db.insert(conn, "api_usage", ts=db.utcnow(), provider="buffer", agent=agent, units=1, unit_kind="request",
              cost_usd=0.0, detail=detail[:200])
