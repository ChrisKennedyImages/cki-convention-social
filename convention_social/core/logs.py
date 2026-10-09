"""One rotating log file per agent under DATA_ROOT/logs, plus stderr.

10 MB x 5 files per agent. Idempotent: calling get_logger twice for the same
agent returns the same logger without doubling handlers.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import config

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5


def get_logger(agent: str, *, to_stderr: bool = True) -> logging.Logger:
    logger = logging.getLogger(f"ccs.{agent}")
    cfg = config.get_config()
    target = cfg.logs_dir / f"{agent}.log"
    if getattr(logger, "_ccs_path", None) == str(target):
        return logger
    for h in list(logger.handlers):  # reconfigure (a test moved the data root)
        logger.removeHandler(h)
        h.close()
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(target, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(handler)
    if to_stderr:
        err = logging.StreamHandler(sys.stderr)
        err.setFormatter(logging.Formatter(FORMAT))
        logger.addHandler(err)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._ccs_path = str(target)  # type: ignore[attr-defined]
    return logger
