"""The offer file: what the company sells, in Chris's words. The only source of offer copy.

offer.json at the repo root (OFFER_FILE overrides). No prices: every event is
quoted on its own (Chris, 2026-10-09), and a test fails if a price appears.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .core import config


def path() -> Path:
    override = config.getenv("OFFER_FILE")
    return Path(override).expanduser() if override else config.REPO_ROOT / "offer.json"


@lru_cache(maxsize=4)
def _load(p: str, mtime: float) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def load() -> dict:
    p = path()
    return _load(str(p), p.stat().st_mtime)


def coverage_labels(keys=None) -> list[str]:
    items = load().get("coverage") or []
    if keys is None:
        return [c["label"] for c in items]
    wanted = set(keys)
    return [c["label"] for c in items if c["key"] in wanted]


def coverage_keys() -> list[str]:
    return [c["key"] for c in load().get("coverage") or []]


def coverage_page(key: str) -> str:
    return f"/coverage/{key}/"


def public_pages() -> tuple[str, ...]:
    """Every public page, in sitemap order (2026-10-14): the home page, About, the coverage index and one page per
    coverage item, the quote form, Contact, Privacy. The build, the sitemap, IndexNow and the outside check all read
    this one list. No Availability page since 2026-10-31 (Chris, 2026-10-15: empty calendars, "a very bad look"): the
    booked dates are a line on the quote form, and the Worker sends /availability/ there."""
    return ("/", "/about/", "/coverage/") + tuple(coverage_page(k) for k in coverage_keys()) + ("/book/", "/contact/", "/privacy/")
