"""Public URLs for post images (Buffer takes media by URL only).

Two hosts, either one enough: the company's own Worker (worker/index.js:
PUT/GET <MEDIA_BASE_URL>/<key>, backed by its own bucket, upload needs
MEDIA_UPLOAD_TOKEN) or the bucket's S3 API directly (the R2_* keys plus
R2_PUBLIC_BASE). Every public key starts with KEY_PREFIX, the only prefix the
Worker serves; private/ (backups) is written with the token and never served.

In a dry run nothing is uploaded; the URL the live run *would* produce is
returned so the recorded payload is exact. With no host configured, dry runs
still work (placeholder host) and live runs refuse.
"""
from __future__ import annotations

import hashlib
import mimetypes
import time
from pathlib import Path
from typing import Callable, Optional

from ..core import config, secrets

PLACEHOLDER_BASE = "https://media-not-configured.invalid"
KEY_PREFIX = "convention-social"


class MediaError(RuntimeError):
    pass


class NotReadable(MediaError):
    """The upload answered well, but a read of the file's address does not give the whole file back yet."""


READ_TRIES = 3          # looks at the address before a file is called not readable this run
READ_WAIT = 3           # seconds between looks, times the look's number


def settings() -> dict:
    return {"endpoint": config.getenv("R2_ENDPOINT", ""), "bucket": config.getenv("R2_BUCKET", ""),
            "public_base": (config.getenv("R2_PUBLIC_BASE", "") or "").rstrip("/"),
            "key": secrets.get_secret("R2_KEY") or "", "secret": secrets.get_secret("R2_SECRET") or ""}


def worker() -> dict:
    """The company's own image host: PUT/GET <MEDIA_BASE_URL>/<key>."""
    return {"base": (config.getenv("MEDIA_BASE_URL", "") or "").rstrip("/"), "token": secrets.get_secret("MEDIA_UPLOAD_TOKEN") or ""}


def worker_configured() -> bool:
    w = worker()
    return bool(w["base"] and w["token"])


def configured() -> bool:
    s = settings()
    return worker_configured() or all(s.values())


def photo_key(drive_id: str, md5: str | None = None, suffix: str = ".jpg") -> str:
    """A stable key per photo that does not expose its Drive id."""
    digest = hashlib.sha256(f"{drive_id}:{md5 or ''}".encode()).hexdigest()[:16]
    return f"{KEY_PREFIX}/photos/{digest}{suffix}"


def card_key(queue_id: int, aspect: str, index: int = 1) -> str:
    """Rendered design <index> of a draft's set; re-renders overwrite the same objects."""
    return f"{KEY_PREFIX}/cards/{queue_id}-{aspect.replace(':', '')}-{index}.jpg"


def reel_key(queue_id: int, what: str = "video") -> str:
    """A draft's reel (mp4) or its cover (jpg)."""
    return f"{KEY_PREFIX}/reels/{queue_id}-{what}{'.mp4' if what == 'video' else '.jpg'}"


def public_url(key: str) -> str:
    base = worker()["base"] or settings()["public_base"] or PLACEHOLDER_BASE
    return f"{base}/{key}"


def _client():
    import boto3
    from botocore.config import Config
    s = settings()
    return boto3.client("s3", endpoint_url=s["endpoint"], aws_access_key_id=s["key"],
                        aws_secret_access_key=s["secret"], config=Config(signature_version="s3v4", region_name="auto"))


def upload(path: Path, key: str, *, client=None, put=None) -> str:
    """Upload one file; return its public URL. Raises MediaError when no host is configured.
    `put` (the Worker path) and `client` (the S3 path) are injectable for tests."""
    if not key.startswith(KEY_PREFIX + "/"):
        raise MediaError(f"refusing to upload outside {KEY_PREFIX}/: {key}")
    if not configured():
        raise MediaError("image hosting is not configured (MEDIA_BASE_URL + MEDIA_UPLOAD_TOKEN, or the R2_* keys)")
    content_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    if worker_configured() and client is None:
        if put is None:
            import requests
            put = requests.put
        w = worker()
        r = put(f"{w['base']}/{key}", data=Path(path).read_bytes(), timeout=60,
                headers={"Authorization": f"Bearer {w['token']}", "Content-Type": content_type})
        if getattr(r, "status_code", 500) not in (200, 201):
            raise MediaError(f"image upload refused: HTTP {getattr(r, 'status_code', '?')} {str(getattr(r, 'text', ''))[:120]}")
        return public_url(key)
    s = settings()
    client = client or _client()
    client.upload_file(str(path), s["bucket"], key, ExtraArgs={"ContentType": content_type})
    return public_url(key)


def _ranged_get(url: str):
    import requests
    return requests.get(url, headers={"Range": "bytes=0-0"}, timeout=30, stream=True)


def verify_readable(url: str, path: Path, *, get: Optional[Callable] = None, sleep: Callable[[float], None] = time.sleep,
                    tries: int = READ_TRIES) -> None:
    """The file is really at its address before Buffer is told about it. Buffer refused post 28 on 2026-10-24 with
    "Video could not be read from its URL" and took the same address eight hours later: an upload's 200 is not a read.
    A one-byte range GET must answer 200 or 206 with the file's kind of type and its whole size (Content-Range's total,
    or Content-Length when the host ignores the range). READ_TRIES looks a few seconds apart, then NotReadable."""
    size = path.stat().st_size
    want = (mimetypes.guess_type(str(path))[0] or "image/jpeg").split("/")[0] + "/"
    get = get or _ranged_get
    why = ""
    for n in range(max(1, tries)):
        if n:
            sleep(READ_WAIT * n)
        try:
            r = get(url)
            try:
                code = int(getattr(r, "status_code", 0) or 0)
                headers = {str(k).lower(): str(v) for k, v in dict(getattr(r, "headers", None) or {}).items()}
            finally:
                close = getattr(r, "close", None)
                if callable(close):
                    close()
        except Exception as e:  # noqa: BLE001  the network: not readable this look
            why = f"{type(e).__name__}: {e}"
            continue
        ctype = headers.get("content-type", "").split(";")[0].strip()
        length = headers.get("content-range") or headers.get("content-length") or ""
        try:
            total = int(length.rsplit("/", 1)[-1]) if length else None
        except ValueError:
            total = None
        if code in (200, 206) and ctype.startswith(want) and total == size:
            return
        why = f"HTTP {code}, {ctype or 'no type'}, {'no' if total is None else total} bytes where the file is {size}"
    raise NotReadable(f"{url} is not readable yet ({why}); nothing is sent to Buffer for it this run")


def upload_checked(path: Path, key: str, **kw) -> str:
    """upload, then verify_readable: the publisher's own uploader (a test's uploader stands in for both)."""
    url = upload(path, key, **kw)
    verify_readable(url, path)
    return url
