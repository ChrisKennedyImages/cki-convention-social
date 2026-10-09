"""The Drive v3 calls this suite makes. GET ONLY.

`get()` is the single door to the network and it only ever issues GET.
There is no create, update, copy, move, share, trash or delete code here,
and tests/test_drive_readonly.py fails if any appears. Every request is
counted in api_usage (provider 'drive').
"""
from __future__ import annotations

import sqlite3
from typing import Callable, Iterator, Optional

from ..core import db

API = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
PAGE_SIZE = 1000
TIMEOUT = 60

FILE_FIELDS = ("id,name,mimeType,md5Checksum,size,parents,modifiedTime,description,trashed,"
               "thumbnailLink,hasThumbnail,driveId,"
               "imageMediaMetadata(width,height,rotation,time,cameraMake,cameraModel)")

Transport = Callable[[str, dict, dict, bool], object]   # (url, params, headers, stream) -> response


def requests_get(url: str, params: dict, headers: dict, stream: bool = False):
    import requests
    r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT, stream=stream)
    r.raise_for_status()
    return r


class DriveReader:
    def __init__(self, token: str, *, conn: Optional[sqlite3.Connection] = None, agent: str = "scanner",
                 transport: Optional[Transport] = None):
        self.token = token
        self.conn = conn
        self.agent = agent
        self.transport = transport or requests_get

    def get(self, path: str, params: Optional[dict] = None, *, stream: bool = False, absolute: bool = False):
        if self.conn is not None:
            db.insert(self.conn, "api_usage", ts=db.utcnow(), provider="drive", agent=self.agent, units=1,
                      unit_kind="request", cost_usd=0.0, detail=path[:120])
        url = path if absolute else API + path
        return self.transport(url, dict(params or {}), {"Authorization": "Bearer " + self.token}, stream)

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

    def export_csv(self, file_id: str) -> str:
        """A Google Sheet's first tab as CSV (files.export, a read)."""
        return self.get(f"/files/{file_id}/export", {"mimeType": "text/csv"}).content.decode("utf-8-sig")

    def download(self, file_id: str) -> bytes:
        """The full-size original, read only. Used only once a photo is chosen."""
        return self.get(f"/files/{file_id}", {"alt": "media", "supportsAllDrives": "true"}).content
