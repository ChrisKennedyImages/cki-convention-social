"""Telling search engines the site changed: IndexNow (Chris, 2026-10-12: "no site map or Google search
indexing").

IndexNow (indexnow.org) is the open protocol Bing, Yandex, Naver, Seznam and others share: the site
hosts a key file at /<key>.txt and, after a publish, POSTs the pages that changed to one endpoint,
which passes them to every engine in the protocol. Google is not in it: Google is told through
Search Console (the verification tag, site/build.py, and the sitemap submitted there once) and
reads the sitemap's lastmod dates after that.

The key is made here on the first publish and kept in .env as INDEXNOW_KEY (it is public by
design, the file on the site proves ownership). A ping that fails never fails a publish: the site
is live either way, and the Website card says the engines were not told and why.
"""
from __future__ import annotations

import secrets as pysecrets
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..core import config, secrets

KEY_NAME = "INDEXNOW_KEY"
ENDPOINT = "https://api.indexnow.org/indexnow"
TIMEOUT = 20
USER_AGENT = "cki-convention-social/0.1 (publish)"

Poster = Callable[[str, dict], tuple[int, str]]      # (url, json body) -> (status, response text)


def key() -> str:
    return (secrets.get_secret(KEY_NAME) or "").strip()


def valid(value: str) -> bool:
    """IndexNow keys: 8 to 128 characters, letters, digits and dashes only."""
    return 8 <= len(value) <= 128 and all(c.isalnum() or c == "-" for c in value)


def ensure_key() -> str:
    """The key, made and kept in .env on the first publish."""
    current = key()
    if current and valid(current):
        return current
    made = pysecrets.token_hex(16)
    config.write_env({KEY_NAME: made})
    return made


def key_file_name(value: str) -> str:
    return f"{value}.txt"


def write_key_file(out: Path, value: str) -> Path:
    """The file at the site's root that proves the key is ours: its content is the key itself."""
    path = out / key_file_name(value)
    path.write_text(value)
    return path


def _post(url: str, body: dict) -> tuple[int, str]:
    import requests
    r = requests.post(url, json=body, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    return r.status_code, r.text or ""


def ping(base_url: str, paths: Iterable[str], *, value: Optional[str] = None, post: Optional[Poster] = None) -> tuple[bool, str]:
    """Tell the IndexNow engines these pages changed. (told, note)."""
    value = value if value is not None else key()
    if not value:
        return False, "no IndexNow key yet (it is made on the first publish)"
    host = base_url.split("://", 1)[-1].strip("/")
    urls = [base_url.rstrip("/") + "/" + p.lstrip("/") for p in paths]
    if not urls:
        return False, "no pages to tell them about"
    body = {"host": host, "key": value, "keyLocation": f"{base_url.rstrip('/')}/{key_file_name(value)}", "urlList": urls}
    try:
        status, text = (post or _post)(ENDPOINT, body)
    except Exception as e:  # noqa: BLE001  the engines not hearing is a note, never a crash
        return False, f"IndexNow could not be reached ({type(e).__name__})"
    if status in (200, 202):
        return True, f"IndexNow told about {len(urls)} page(s) (Bing, Yandex and the others; Google reads the sitemap)"
    return False, f"IndexNow answered {status}: {(text or '').strip()[:120] or 'no detail'}"
