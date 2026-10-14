"""An in-memory Drive for tests: answers the GET paths drive/api.py uses and records every call."""
from __future__ import annotations

import io
import json
import re
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
        self.shared: dict[str, str] = {}   # items shared directly with the account: id -> who shared it

    def folder(self, fid, name, parent=None):
        self.folders[fid] = {"id": fid, "name": name, "parents": [parent or self.root], "mimeType": FOLDER}
        return fid

    def shared_folder(self, fid, name, by="Mike Kennedy", parent="unreadable"):
        """A folder someone else owns, shared with the account (2026-10-14). Its parent is one the account
        cannot see (Drive then gives an id it cannot read, or none at all: parent=None), unless it sits
        inside a folder the account can see."""
        f = {"id": fid, "name": name, "mimeType": FOLDER, "ownedByMe": False,
             "sharingUser": {"displayName": by}, "owners": [{"displayName": by}]}
        if parent is not None:
            f["parents"] = [parent]
        self.folders[fid] = f
        self.shared[fid] = by
        return fid

    def image(self, fid, name, parent, *, mime="image/jpeg", w=6000, h=4000, time="2024:03:02 10:00:00", thumb=True, by=None):
        self.files[fid] = {"id": fid, "name": name, "mimeType": mime, "md5Checksum": "m" + fid,
                           "size": "1234", "modifiedTime": "2024-03-02T10:00:00Z", "hasThumbnail": thumb,
                           "thumbnailLink": f"https://thumbs.example/stale/{fid}=s220" if thumb else None,
                           "imageMediaMetadata": {"width": w, "height": h, "time": time, "cameraMake": "Canon", "cameraModel": "R5"}}
        if parent is not None:
            self.files[fid]["parents"] = [parent]
        if by:                                   # a single photo shared directly with the account
            self.files[fid].update({"ownedByMe": False, "owners": [{"displayName": by}], "sharingUser": {"displayName": by}})
            self.shared[fid] = by
        return fid

    def _sharer(self, item) -> str | None:
        """Who shared the folder this item sits in, walking up; None for the account's own items."""
        seen = set()
        while item is not None and item["id"] not in seen:
            seen.add(item["id"])
            if item["id"] in self.shared:
                return self.shared[item["id"]]
            parent = (item.get("parents") or [None])[0]
            if parent is None or parent == self.root:
                return None
            item = self.folders.get(parent)
        return None

    def _as_seen(self, item) -> dict:
        """What Drive answers for an item inside a shared gallery: not owned by the account, the sharer as owner."""
        by = self._sharer(item)
        if by and "ownedByMe" not in item:
            return {**item, "ownedByMe": False, "owners": [{"displayName": by}]}
        return item

    def _own(self, item) -> bool:
        """Whether the account's own My Drive holds the item (the chain reaches the root)."""
        seen = set()
        while item is not None and item["id"] not in seen:
            seen.add(item["id"])
            parent = (item.get("parents") or [None])[0]
            if parent == self.root:
                return True
            if parent is None:
                return False
            item = self.folders.get(parent)
        return False

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
            # like Drive: a flat listing holds the account's own items and what was shared with it directly;
            # what sits inside a shared folder comes back only when that folder is asked for its children
            q = params["q"]
            m = re.search(r"'([^']+)' in parents", q)
            everything = list(self.folders.values()) + list(self.files.values())
            if m:
                items = [self._as_seen(f) for f in everything if (f.get("parents") or [None])[0] == m.group(1)]
            elif "sharedWithMe" in q:
                items = [self._as_seen(f) for f in everything if f["id"] in self.shared]
            else:
                pool = list(self.folders.values()) if "folder" in q else list(self.files.values())
                items = [self._as_seen(f) for f in pool if self._own(f) or f["id"] in self.shared]
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
