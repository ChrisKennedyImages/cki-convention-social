"""How every agent runs: one lock, one agent_runs row, one place errors land.

`run(agent, fn)` is the launchd entrypoint for each agent. It takes a
non-blocking flock so two copies never overlap, records the start in
agent_runs, calls fn(ctx), and records the result. An exception becomes an
errors row (message + traceback) and a non-zero exit; the watchdog reads
errors and agent_runs to know what broke and what never ran.

Exit codes: 0 ok, 1 the agent raised, 75 another copy holds the lock.
"""
from __future__ import annotations

import fcntl
import os
import sqlite3
import sys
import traceback
from dataclasses import dataclass
from typing import Callable, Optional

from . import config, db, logs, settings

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LOCKED = 75


@dataclass
class Context:
    agent: str
    conn: sqlite3.Connection
    log: "logs.logging.Logger"
    cfg: config.Config
    dry_run: bool
    run_id: int


class Lock:
    def __init__(self, agent: str):
        cfg = config.get_config()
        cfg.locks_dir.mkdir(parents=True, exist_ok=True)
        self.path = cfg.locks_dir / f"{agent}.lock"
        self.handle = None

    def acquire(self) -> bool:
        handle = open(self.path, "w")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.write(str(os.getpid()))
        handle.flush()
        self.handle = handle
        return True

    def release(self) -> None:
        if self.handle is not None:
            try:
                self.handle.close()
            finally:
                self.handle = None


def record_error(conn: sqlite3.Connection, agent: str, kind: str, message: str,
                 tb: Optional[str] = None) -> int:
    return db.insert(conn, "errors", ts=db.utcnow(), agent=agent, kind=kind,
                     message=message[:2000], traceback=tb, alerted=0)


def run(agent: str, fn: Callable[[Context], Optional[str]], *, force_dry_run: Optional[bool] = None) -> int:
    """Run one agent invocation under lock; return the process exit code."""
    cfg = config.get_config()
    cfg.ensure_dirs()
    log = logs.get_logger(agent)
    lock = Lock(agent)
    if not lock.acquire():
        log.warning("%s: another copy holds %s; exiting", agent, lock.path.name)
        return EXIT_LOCKED
    conn = db.connect()
    try:
        dry = settings.dry_run(conn, agent) if force_dry_run is None else force_dry_run
        run_id = db.insert(conn, "agent_runs", agent=agent, started_at=db.utcnow(), dry_run=1 if dry else 0)
        ctx = Context(agent=agent, conn=conn, log=log, cfg=cfg, dry_run=dry, run_id=run_id)
        log.info("%s: start (run %d, dry_run=%s)", agent, run_id, dry)
        try:
            summary = fn(ctx)
        except Exception as e:  # noqa: BLE001 — the whole point is to record it
            tb = traceback.format_exc()
            record_error(conn, agent, type(e).__name__, str(e), tb)
            conn.execute("UPDATE agent_runs SET finished_at=?, ok=0, summary=? WHERE id=?",
                         (db.utcnow(), f"{type(e).__name__}: {e}"[:500], run_id))
            log.error("%s: failed: %s\n%s", agent, e, tb)
            return EXIT_FAILED
        conn.execute("UPDATE agent_runs SET finished_at=?, ok=1, summary=? WHERE id=?",
                     (db.utcnow(), (summary or "")[:500], run_id))
        log.info("%s: done: %s", agent, summary or "")
        return EXIT_OK
    finally:
        conn.close()
        lock.release()


def main_for(agent: str, fn: Callable[[Context], Optional[str]]) -> None:
    """`python -m convention_social.agents.<agent>` -> run once and exit."""
    force = None
    if "--dry-run" in sys.argv:
        force = True
    elif "--live" in sys.argv:
        force = False
    sys.exit(run(agent, fn, force_dry_run=force))
