"""One rotating log file per agent under DATA_ROOT/logs, and stderr when someone is watching.

10 MB x 5 files per agent. The lines go to stderr as well only when stderr is a terminal (`ccs run
<agent>` typed by hand). Under launchd they do not: launchd keeps whatever an agent writes to stderr in
<agent>.launchd.log, a second copy of the same lines that never rotates (2026-10-24 audit: 6.8 MB in two
weeks, the dashboard's access log among it). What reaches that file now is only what Python says before
or outside logging: a crash at start. Idempotent: calling get_logger twice for the same agent returns the
same logger without doubling handlers.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import config

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5


def watched() -> bool:
    """True when stderr is a terminal: someone typed the command and reads the lines there."""
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def handlers(agent: str, *, to_stderr: bool = True) -> list[logging.Handler]:
    """The rotating file for `agent`, and stderr when `to_stderr` and someone is watching."""
    cfg = config.get_config()
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    out: list[logging.Handler] = [RotatingFileHandler(cfg.logs_dir / f"{agent}.log", maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                                     encoding="utf-8")]
    if to_stderr and watched():
        out.append(logging.StreamHandler(sys.stderr))
    for h in out:
        h.setFormatter(logging.Formatter(FORMAT))
    return out


def get_logger(agent: str, *, to_stderr: bool = True) -> logging.Logger:
    logger = logging.getLogger(f"ccs.{agent}")
    target = config.get_config().logs_dir / f"{agent}.log"
    if getattr(logger, "_ccs_path", None) == str(target):
        return logger
    for h in list(logger.handlers):  # reconfigure (a test moved the data root)
        logger.removeHandler(h)
        h.close()
    for h in handlers(agent, to_stderr=to_stderr):
        logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._ccs_path = str(target)  # type: ignore[attr-defined]
    return logger
