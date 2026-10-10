"""The Drive v3 calls this suite makes. GET ONLY.

`get()` is the single door to the network and it only ever issues GET.
There is no create, update, copy, move, share, trash or delete code here,
and tests/test_drive_readonly.py fails if any appears. Every request is
counted in api_usage (provider 'drive').
"""
from __future__ import annotations

import sqlite3
import time
from typing import Callable, Iterator, Optional, Union

from ..core import db

API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
PAGE_SIZE = 1000
TIMEOUT = 60
TOKEN_MAX_AGE = 300        # how long a token is reused before the provider is asked again

FILE_FIELDS = ("id,name,mimeType,md5Checksum,size,parents,modifiedTime,description,trashed,"
               "thumbnailLink,hasThumbnail,driveId,"
               "imageMediaMetadata(width,height,rotation,time,cameraMake,cameraModel)")

Transport = Callable[[str, dict, dict, bool], object]   # (url, params, headers, stream) -> response


def unauthorized(error: object) -> bool:
    """True when Drive answered 401: the access token has expired or been revoked."""
    return getattr(getattr(error, "response", None), "status_code", None) == 401


def requests_get(url: str, params: dict, headers: dict, stream: bool = False):
    import requests
    r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT, stream=stream)
    r.raise_for_status()
    return r


class NoThumbnail(RuntimeError):
    """Drive offers no preview for this photo, so it cannot be sorted or put on a sheet."""


class DriveReader:
    def __init__(self, token: Union[str, Callable[[], str]], *, conn: Optional[sqlite3.Connection] = None,
                 agent: str = "scanner", transport: Optional[Transport] = None):
        """`token` is a bearer string, or a callable that returns a currently valid one.

        Pass the callable for any pass that can outlive an access token. Google's last about an
        hour, and a reader built from a fixed string keeps sending the same dead one: on
        2026-10-10 a sort pass managed 42 photos, then every one of the remaining 208 failed 401
        within twenty four seconds of the token's expiry. The hourly scanner had it worse, since
        CLASSIFY_PER_RUN of 500 photos is about four hours of local sorting.

        `oauth.access_token` refreshes whenever the stored credentials have expired, so the
        callable is asked again every TOKEN_MAX_AGE seconds, and immediately on any 401.
        """
        self._token_source = token
        self._token: Optional[str] = token if isinstance(token, str) else None
        self._token_at = 0.0
        self.conn = conn
        self.agent = agent
        self.transport = transport or requests_get

    @property
    def token(self) -> str:
        if not callable(self._token_source):
            return self._token_source
        if self._token is None or (time.monotonic() - self._token_at) > TOKEN_MAX_AGE:
            self._token = self._token_source()
            self._token_at = time.monotonic()
        return self._token

    def _drop_token(self) -> bool:
        """Forget the cached token so the next read asks the provider. False when there is none."""
        if not callable(self._token_source):
            return False
        self._token, self._token_at = None, 0.0
        return True

    def _send(self, url: str, params: dict, stream: bool, detail: str):
        if self.conn is not None:
            db.insert(self.conn, "api_usage", ts=db.utcnow(), provider="drive", agent=self.agent, units=1,
                      unit_kind="request", cost_usd=0.0, detail=detail[:120])
        return self.transport(url, dict(params), {"Authorization": "Bearer " + self.token}, stream)

    def get(self, path: str, params: Optional[dict] = None, *, stream: bool = False, absolute: bool = False):
        url = path if absolute else API + path
        params = dict(params or {})
        try:
            return self._send(url, params, stream, path)
        except Exception as e:  # noqa: BLE001 — only a 401 is handled; everything else is re-raised
            if not (unauthorized(e) and self._drop_token()):
                raise
            return self._send(url, params, stream, path)   # counted again: it is a second request

    def _pages(self, path: str, params: dict, key: str) -> Iterator[dict]:
        page = None
        while True:
            p = dict(params)
            if page:
                p["pageToken"] = page
            data = self.get(path, p).json()
            for item in data.get(key) or []:
                yield item
            page = data.get("nextPageToken")
            if not page:
                return

    def list_files(self, q: str, fields: str = FILE_FIELDS) -> Iterator[dict]:
        """Every file matching q, across My Drive and shared drives."""
        return self._pages("/files", {"q": q, "fields": f"nextPageToken,files({fields})", "pageSize": PAGE_SIZE,
                                      "corpora": "allDrives", "includeItemsFromAllDrives": "true",
                                      "supportsAllDrives": "true", "spaces": "drive"}, "files")

    def folders(self) -> Iterator[dict]:
        return self.list_files(f"mimeType = '{FOLDER_MIME}' and trashed = false", "id,name,parents,modifiedTime,driveId")

    def images(self) -> Iterator[dict]:
        return self.list_files("mimeType contains 'image/' and trashed = false")

    def shared_drives(self) -> Iterator[dict]:
        return self._pages("/drives", {"pageSize": 100, "fields": "nextPageToken,drives(id,name)"}, "drives")

    def root_id(self) -> str:
        return str(self.get("/files/root", {"fields": "id"}).json().get("id") or "root")

    def start_page_token(self) -> str:
        return str(self.get("/changes/startPageToken", {"supportsAllDrives": "true"}).json()["startPageToken"])

    def changes(self, token: str) -> tuple[list[dict], str]:
        """All changes since `token`; returns (changes, the token to store for next time)."""
        out: list[dict] = []
        page = token
        while True:
            data = self.get("/changes", {"pageToken": page, "pageSize": PAGE_SIZE, "spaces": "drive",
                                         "includeItemsFromAllDrives": "true", "supportsAllDrives": "true",
                                         "includeRemoved": "true",
                                         "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({FILE_FIELDS}))"}).json()
            out.extend(data.get("changes") or [])
            if data.get("nextPageToken"):
                page = data["nextPageToken"]
                continue
            return out, str(data.get("newStartPageToken") or page)

    def thumbnail(self, link: str, size: int = 512) -> bytes:
        """A small preview of one photo (Drive's own thumbnail; the original is never touched)."""
        import re
        url = re.sub(r"=s\d+$", f"=s{size}", link) if re.search(r"=s\d+$", link) else link
        return self.get(url, {}, absolute=True).content

    def thumbnail_for(self, file_id: str, size: int = 512) -> bytes:
        """A small preview of one photo, with its link resolved fresh.

        Drive's thumbnailLink is a signed URL that stops working about an hour after Drive
        issues it. A link stored during the inventory is therefore already dead by the time a
        slow sort pass reaches it, and every fetch returns 403 at once (2026-10-10: 158 photos
        sorted, the remaining 342 failed inside forty seconds). Asking for the current link
        costs one extra GET per photo and is the only thing that makes a long pass possible.
        The original file is never touched.
        """
        got = self.get(f"/files/{file_id}", {"fields": "thumbnailLink", "supportsAllDrives": "true"}).json()
        link = got.get("thumbnailLink")
        if not link:
            raise NoThumbnail(f"{file_id} has no thumbnail in Drive")
        return self.thumbnail(link, size)

    def export_csv(self, file_id: str) -> str:
        """A Google Sheet's first tab as CSV (files.export, a read)."""
        return self.get(f"/files/{file_id}/export", {"mimeType": "text/csv"}).content.decode("utf-8-sig")

    def download(self, file_id: str) -> bytes:
        """The full-size original, read only. Used only once a photo is chosen."""
        return self.get(f"/files/{file_id}", {"alt": "media", "supportsAllDrives": "true"}).content
