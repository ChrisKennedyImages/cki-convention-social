"""SQLite access: one file under DATA_ROOT/db, WAL mode, numbered migrations.

`connect()` opens (and creates) the database and applies any migration in
core/migrations/ that is not yet recorded in schema_migrations. Rows come
back as sqlite3.Row so callers can use column names.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import config

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied_versions(conn: sqlite3.Connection) -> set[str]:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return set()
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations in order; return the versions applied."""
    done = applied_versions(conn)
    applied: list[str] = []
    for path in migration_files():
        version = path.stem
        if version in done:
            continue
        conn.executescript(path.read_text())
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, utcnow()),
        )
        conn.commit()
        applied.append(version)
    return applied


def connect(path: Optional[Path] = None, *, apply_migrations: bool = True) -> sqlite3.Connection:
    cfg = config.get_config()
    db_path = Path(path) if path else cfg.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the dashboard runs sync dependencies in a worker thread;
    # each request still uses its connection sequentially.
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    if apply_migrations:
        migrate(conn)
    return conn


def table_names(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]


def insert(conn: sqlite3.Connection, table: str, **values) -> int:
    cols = ", ".join(values)
    marks = ", ".join("?" for _ in values)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
    return int(cur.lastrowid)


def rows(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)))


def one(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> Optional[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchone()
