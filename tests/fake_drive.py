"""An in-memory Drive for tests: answers the GET paths drive/api.py uses and records every call."""
from __future__ import annotations

import io
import json
from urllib.parse import urlparse

from PIL import Image

FOLDER = "application/vnd.google-apps.folder"


class StaleThumbnailLink(Exception):
    """What Drive does to a thumbnailLink about an hour after it issues it: 403."""


class Resp:
    def __init__(self, data=None, content: bytes = b""):
        self._data = data
        self.content = content if content else json.dumps(data or {}).encode()
        self.status_code = 200

    def json(self):
        return self._data


def thumb_bytes(color=(90, 120, 160)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), color).save(buf, format="JPEG")
    return buf.getvalue()


class FakeDrive:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.root = "rootid"
        self.folders: dict[str, dict] = {}
        self.files: dict[str, dict] = {}
        self.changes: list[dict] = []
        self.sheet_csv = ""
        self.page_size = 2   # force paging

    def folder(self, fid, name, parent=None):
        self.folders[fid] = {"id": fid, "name": name, "parents": [parent or self.root], "mimeType": FOLDER}
        return fid

    def image(self, fid, name, parent, *, mime="image/jpeg", w=6000, h=4000, time="2024:03:02 10:00:00", thumb=True):
        self.files[fid] = {"id": fid, "name": name, "mimeType": mime, "parents": [parent], "md5Checksum": "m" + fid,
                           "size": "1234", "modifiedTime": "2024-03-02T10:00:00Z", "hasThumbnail": thumb,
                           "thumbnailLink": f"https://thumbs.example/stale/{fid}=s220" if thumb else None,
                           "imageMediaMetadata": {"width": w, "height": h, "time": time, "cameraMake": "Canon", "cameraModel": "R5"}}
        return fid

    def _page(self, items, params):
        start = int(params.get("pageToken") or 0)
        chunk = items[start:start + self.page_size]
        nxt = start + self.page_size
        return chunk, (str(nxt) if nxt < len(items) else None)

    def __call__(self, url, params, headers, stream=False):
        assert headers.get("Authorization", "").startswith("Bearer ")
        self.calls.append((url, dict(params)))
        u = urlparse(url)
        path = u.path.replace("/drive/v3", "")
        if u.netloc == "thumbs.example":
            if u.path.startswith("/stale/"):   # a link captured at inventory time: Drive now 403s it
                raise StaleThumbnailLink(url)
            return Resp(content=thumb_bytes())
        if path == "/changes/startPageToken":
            return Resp({"startPageToken": "100"})
        if path == "/files/root":
            return Resp({"id": self.root})
        if path == "/drives":
            return Resp({"drives": []})
        if path == "/changes":
            return Resp({"changes": self.changes, "newStartPageToken": "200"})
        if path.endswith("/export"):
            return Resp(content=self.sheet_csv.encode())
        if path == "/files":
            q = params["q"]
            items = list(self.folders.values()) if "folder" in q else list(self.files.values())
            chunk, nxt = self._page(items, params)
            data = {"files": chunk}
            if nxt:
                data["nextPageToken"] = nxt
            return Resp(data)
        if path.startswith("/files/") and params.get("alt") == "media":
            return Resp(content=thumb_bytes((200, 10, 10)))
        if path.startswith("/files/") and params.get("fields") == "thumbnailLink":
            fid = path.split("/files/", 1)[1]
            if fid not in self.files:
                raise AssertionError(f"thumbnailLink asked for unknown file {fid}")
            # Drive signs a new link each time it is asked; the one stored earlier is dead
            fresh = f"https://thumbs.example/fresh/{fid}=s220" if self.files[fid]["thumbnailLink"] else None
            return Resp({"thumbnailLink": fresh})
        raise AssertionError(f"unexpected Drive call {url} {params}")
