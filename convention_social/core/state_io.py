"""Atomic JSON writes with corrupt-evidence preservation.

A save lands whole or not at all (tmp + os.replace), the last good version
survives as a rolling <name>.bak, and an unparsable file is copied to a
.corrupt-<ts> sidecar before anything may overwrite it. Used for small JSON
caches (Buffer channel ids, the Drive token); everything relational lives in SQLite.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("ccs.state_io")


def _bak_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def preserve_corrupt(path: Path) -> Path | None:
    try:
        path = Path(path)
        if not path.exists():
            return None
        blob = path.read_bytes()
        for prior in path.parent.glob(path.name + ".corrupt-*"):
            try:
                if prior.read_bytes() == blob:
                    return prior
            except OSError:
                continue
        sidecar = path.with_name(path.name + ".corrupt-" + datetime.now().strftime("%Y%m%dT%H%M%S"))
        sidecar.write_bytes(blob)
        log.warning("preserved corrupt %s -> %s", path.name, sidecar.name)
        return sidecar
    except Exception as e:  # noqa: BLE001
        log.warning("could not preserve corrupt %s: %s", path, e)
        return None


def load_json(path, default: Any, *, bak_fallback: bool = True) -> Any:
    path = Path(path)
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        log.warning("%s unreadable (%s)", path.name, e)
        preserve_corrupt(path)
    if bak_fallback:
        try:
            data = json.loads(_bak_path(path).read_text())
            log.warning("recovered %s from .bak", path.name)
            return data
        except Exception:  # noqa: BLE001
            pass
    return default


def save_json(path, obj: Any, *, indent=None, sort_keys: bool = False, private: bool = False) -> None:
    """`private` writes the file (and its .bak) mode 600, for anything holding a token."""
    path = Path(path)
    text = json.dumps(obj, indent=indent, sort_keys=sort_keys)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            json.loads(path.read_text())
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            preserve_corrupt(path)
        else:
            try:
                bak = _bak_path(path)
                bak.write_bytes(path.read_bytes())
                if private:
                    bak.chmod(0o600)
            except OSError as e:
                log.warning("could not refresh %s.bak: %s", path.name, e)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    if private:
        tmp.chmod(0o600)
    os.replace(tmp, path)
