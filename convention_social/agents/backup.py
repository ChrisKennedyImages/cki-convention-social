"""Backup agent: nightly SQLite online backup, 14 kept, a copy off the machine.

Uses sqlite3's backup API so a live WAL database copies consistently. Files
land in DATA_ROOT/backups/convention_social-YYYYMMDD-HHMM.sqlite3; when
BACKUP_COPY_DIR is set the newest file is also copied there (an iCloud Drive
folder, an external disk, anything mounted). Off the machine: a gzipped copy
goes to the company's own bucket through its Worker under private/backups/
(the Worker never serves private/), one file per weekday so there are always
seven and the bucket does not grow.

Restore: stop the agents, copy a backup over DATA_ROOT/db/convention_social.sqlite3,
start them again.
"""
from __future__ import annotations

import gzip
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from ..core import config, runner

KEEP = 14
PREFIX = "convention_social-"
OFFSITE_PREFIX = "private/backups/"


def backup_once(ctx: runner.Context, now: datetime | None = None) -> Path:
    out_dir = ctx.cfg.data_root / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M")
    target = out_dir / f"{PREFIX}{stamp}.sqlite3"
    dest = sqlite3.connect(str(target))
    try:
        ctx.conn.backup(dest)
    finally:
        dest.close()
    return target


def prune(out_dir: Path, keep: int = KEEP) -> int:
    files = sorted(out_dir.glob(f"{PREFIX}*.sqlite3"))
    removed = 0
    for old in files[:-keep] if len(files) > keep else []:
        old.unlink()
        removed += 1
    return removed


def copy_out(target: Path) -> Path | None:
    copy_dir = config.getenv("BACKUP_COPY_DIR", "")
    if not copy_dir:
        return None
    dest_dir = Path(copy_dir).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / target.name
    shutil.copy2(target, dest)
    prune(dest_dir)
    return dest


def offsite_key(now: datetime | None = None) -> str:
    return f"{OFFSITE_PREFIX}{PREFIX}{(now or datetime.now()).strftime('%a').lower()}.sqlite3.gz"


def offsite(ctx: runner.Context, target: Path, now: datetime | None = None, put=None) -> str | None:
    """A gzipped copy in the company's own bucket under private/backups/. None when the Worker is not configured."""
    from ..buffer import media
    w = media.worker()
    if not (w["base"] and w["token"]):
        return None
    key = offsite_key(now)
    if put is None:
        import requests
        put = requests.put
    try:
        r = put(f"{w['base']}/{key}", data=gzip.compress(target.read_bytes()), timeout=120,
                headers={"Authorization": f"Bearer {w['token']}", "Content-Type": "application/gzip"})
        if getattr(r, "status_code", 500) >= 300:
            raise RuntimeError(f"HTTP {getattr(r, 'status_code', '?')}")
    except Exception as e:  # noqa: BLE001
        runner.record_error(ctx.conn, ctx.agent, "backup_offsite", f"off-machine copy failed: {e}")
        return None
    return key


def run(ctx: runner.Context, *, now: datetime | None = None, put=None) -> str:
    target = backup_once(ctx, now)
    removed = prune(target.parent)
    copied = copy_out(target)
    away = offsite(ctx, target, now, put)
    size_kb = target.stat().st_size // 1024
    return (f"backup {target.name} ({size_kb} KB); pruned {removed}; copy: {copied or 'none (BACKUP_COPY_DIR unset)'}; "
            f"off the machine: {away or 'no'}")


if __name__ == "__main__":
    runner.main_for("backup", run)
