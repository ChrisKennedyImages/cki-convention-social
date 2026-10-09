"""Runtime settings stored in the `settings` table, toggled from the dashboard.

The one rule that matters: `dry_run(agent)` is True unless a row explicitly
says otherwise. A missing row, an unreadable value or a missing database all
mean "do not send". Keys are `<agent>.dry_run`; other keys are free-form
strings read by their owners.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from . import db

FALSE_WORDS = {"0", "false", "off", "no", "n"}
TRUE_WORDS = {"1", "true", "on", "yes", "y"}

AGENTS_WITH_DRY_RUN = ("scanner", "content", "publisher", "inbox", "watchdog", "chief")


def get(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = db.one(conn, "SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set(conn: sqlite3.Connection, key: str, value: str) -> None:  # noqa: A001 — mirrors get()
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, str(value), db.utcnow()),
    )


def all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in db.rows(conn, "SELECT key, value FROM settings ORDER BY key")}


def parse_bool(value: Optional[str], *, default: bool) -> bool:
    if value is None:
        return default
    word = str(value).strip().lower()
    if word in FALSE_WORDS:
        return False
    if word in TRUE_WORDS:
        return True
    return default


def dry_run(conn: sqlite3.Connection, agent: str) -> bool:
    """True unless `<agent>.dry_run` is explicitly a false word. Fails closed."""
    try:
        return parse_bool(get(conn, f"{agent}.dry_run"), default=True)
    except sqlite3.Error:
        return True


def set_dry_run(conn: sqlite3.Connection, agent: str, value: bool) -> None:
    set(conn, f"{agent}.dry_run", "true" if value else "false")


def dry_run_table(conn: sqlite3.Connection) -> dict[str, bool]:
    return {agent: dry_run(conn, agent) for agent in AGENTS_WITH_DRY_RUN}
