"""Fakes and seeds for the publishing, watchdog and backup tests. Nothing here touches the network.

AgentCase also stops the macOS Keychain from being read: on the Mac mini a real
BUFFER_API_KEY or MEDIA_UPLOAD_TOKEN may live there, and a test must never be
able to pick one up and reach a real service.
"""
from __future__ import annotations

import json
import re
import types
from email import message_from_bytes, policy
from pathlib import Path
from unittest import mock

from convention_social.buffer.client import Response
from convention_social.core import config, db, logs, runner
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

CHANNEL_IDS = {"instagram": "ch-ig", "facebook": "ch-fb", "pinterest": "ch-pin", "linkedin": "ch-li"}


def field(name, type_name, required=False, kind="INPUT_OBJECT", description=None):
    """One inputField as GraphQL introspection gives it (a required field is wrapped in NON_NULL)."""
    named = {"kind": kind, "name": type_name, "ofType": None}
    return {"name": name, "description": description,
            "type": {"kind": "NON_NULL", "name": None, "ofType": named} if required else named}


# Buffer's own words on VideoAssetInput.thumbnailUrl, introspected 2026-10-16, and its refusal of a reel that set it
THUMBNAIL_URL_DOC = ("Do not use: social networks do not accept custom video thumbnail images, and\nthe API rejects video "
                     "assets that set this field. To choose the video\nthumbnail, set `metadata.thumbnailOffset` to select a "
                     "frame from the video\n(supported for Instagram, TikTok, and Pinterest only).")
THUMBNAIL_URL_REFUSED = ("Invalid post: Video thumbnailUrl is not supported: social networks do not accept custom video "
                         "thumbnail images, so this value is never sent to the network. Remove thumbnailUrl from the video "
                         "asset. To pick the video thumbnail, set metadata.thumbnailOffset on the video (offset into the "
                         "video in milliseconds; supported for Instagram, TikTok, and Pinterest only).")


# A stand-in for Buffer's schema, for the tests only: the live one is read by BufferClient.video_asset_fields.
SCHEMA = {
    "AssetInput": [field("image", "ImageAssetInput"), field("video", "VideoAssetInput"), field("document", "DocumentAssetInput")],
    "VideoAssetInput": [field("url", "String", True, "SCALAR", "URL to the file source"),
                        field("thumbnailUrl", "String", False, "SCALAR", THUMBNAIL_URL_DOC),
                        field("metadata", "VideoMetadataInput", description="Video specific metadata")],
    "VideoMetadataInput": [field("thumbnailOffset", "Int", False, "SCALAR", "Offset of the thumbnail chosen for the video, in ms"),
                           field("title", "String", False, "SCALAR", "Video title")],
    "ImageAssetInput": [field("url", "String", True, "SCALAR"), field("thumbnailUrl", "String", False, "SCALAR"),
                        field("metadata", "ImageMetadataInput")],
    "ImageMetadataInput": [field("altText", "String", False, "SCALAR")],
    "DeletePostInput": [field("id", "PostId", True, "SCALAR")],
}


def member(name, fields, error=False):
    """One possibleType of a GraphQL union as introspection gives it."""
    return {"name": name, "fields": [{"name": f} for f in fields], "interfaces": [{"name": "MutationError"}] if error else []}


# The unions the tests read, as Buffer's live schema had them on 2026-10-16 (introspected): deletePost answers
# DeletePostSuccess { id } or VoidMutationError, never PostActionSuccess.
UNIONS = {
    "DeletePostPayload": [member("DeletePostSuccess", ["id"]), member("VoidMutationError", ["message"], error=True)],
}
LIVE_LINK = "https://www.instagram.com/p/abc123/"


class FakeBuffer:
    """Canned GraphQL responses keyed by operation name; records every request."""

    def __init__(self, *, status_sequence=None, reject_at=(), http_status=200, retry_after=None,
                 disconnected=(), error_message="Image could not be fetched", schema=None, orgs=None, channels=None,
                 unions=None, raise_on_create=(), create_http=None, posts_nodes=None, raise_on_posts=False,
                 reject_message="board not found", api_key="test-key"):
        """`raise_on_create`: 1-based createPost calls on which the transport raises (Buffer did not answer);
        `create_http`: {call: HTTP status} answered instead; `posts_nodes`: what the Posts query lists when set;
        `raise_on_posts`: the transport raises on the Posts query; `reject_message`: Buffer's words on a refusal;
        `api_key`: the one key this account answers to."""
        self.api_key = api_key
        self.schema = schema if schema is not None else SCHEMA
        self.unions = unions if unions is not None else UNIONS
        self.orgs = orgs if orgs is not None else [{"id": "org-1", "name": "Event Caliber"}]
        self.channels = channels if channels is not None else [(svc, cid, f"Event Caliber {svc}") for svc, cid in CHANNEL_IDS.items()]
        self.calls = []
        self.created = []
        self.deleted = []
        self.status_sequence = list(status_sequence or ["scheduled", "sent"])
        self.reject_at = set(reject_at)          # 1-based createPost calls to refuse
        self.http_status = http_status
        self.retry_after = retry_after
        self.disconnected = set(disconnected)
        self.error_message = error_message
        self.n_status = 0
        self.n_create = 0
        self.raise_on_create = set(raise_on_create)
        self.create_http = dict(create_http or {})
        self.posts_nodes = posts_nodes
        self.raise_on_posts = raise_on_posts
        self.reject_message = reject_message

    def __call__(self, url, payload, headers):
        op = payload["query"].strip().split("\n")[0]
        self.calls.append((op, payload["variables"]))
        assert url == "https://api.buffer.com"
        assert headers["Authorization"] == f"Bearer {self.api_key}"
        assert headers["User-Agent"] == "cki-convention-social/0.1"
        if self.http_status == 429:
            return Response(429, {"Retry-After": str(self.retry_after or 42)}, {})
        if self.http_status >= 400:
            return Response(self.http_status, {}, {"message": "boom"})
        if "InputType" in op:
            name = payload["variables"]["name"]
            fields = self.schema.get(name)
            return Response(200, {}, {"data": {"__type": None if fields is None else {"name": name, "inputFields": fields}}})
        if "UnionType" in op:
            name = payload["variables"]["name"]
            members = self.unions.get(name)
            return Response(200, {}, {"data": {"__type": None if members is None else {"name": name, "possibleTypes": members}}})
        if "Organizations" in op:
            return Response(200, {}, {"data": {"account": {"organizations": self.orgs}}})
        if "PinterestBoards" in op:
            return Response(200, {}, {"data": {"channel": {"id": payload["variables"]["input"]["id"], "service": "pinterest",
                                                           "metadata": {"__typename": "PinterestMetadata",
                                                                        "boards": [{"serviceId": "board-123", "name": "Conventions"}]}}}})
        if "Channels" in op:
            return Response(200, {}, {"data": {"channels": [
                {"id": cid, "name": svc, "service": svc, "displayName": name,
                 "isDisconnected": svc in self.disconnected, "isLocked": False, "isQueuePaused": False}
                for svc, cid, name in self.channels]}})
        if "CreatePost" in op:
            self.n_create += 1
            if self.n_create in self.raise_on_create:
                raise ConnectionError("read timed out")            # the transport: Buffer did not answer at all
            if self.n_create in self.create_http:
                return Response(self.create_http[self.n_create], {}, {"message": "bad gateway"})
            if self.n_create in self.reject_at:
                return Response(200, {}, {"data": {"createPost": {"__typename": "InvalidInputError", "message": self.reject_message}}})
            if any("thumbnailUrl" in (a.get("video") or {}) for a in payload["variables"]["input"].get("assets") or []):
                # live Buffer refuses a reel that names a cover image, whatever its schema lists (2026-10-16, post 7)
                return Response(200, {}, {"data": {"createPost": {"__typename": "InvalidInputError", "message": THUMBNAIL_URL_REFUSED}}})
            self.created.append(payload["variables"]["input"])
            return Response(200, {}, {"data": {"createPost": {"__typename": "PostActionSuccess", "post": {"id": f"post-{len(self.created)}"}}}})
        if "PostStatus" in op:
            status = self.status_sequence[min(self.n_status, len(self.status_sequence) - 1)]
            self.n_status += 1
            post = {"id": payload["variables"]["input"]["id"], "status": status,
                    "sentAt": "2026-10-09T15:30:05Z" if status == "sent" else None,
                    "externalLink": LIVE_LINK if status == "sent" else None,
                    "error": {"message": self.error_message} if status == "error" else None}
            return Response(200, {}, {"data": {"post": post}})
        if "DeletePost" in op:
            # Buffer validates the reply fragments before it runs anything: a type that is not a DeletePostPayload
            # member (or the MutationError interface its errors share) is refused whole, nothing deleted (2026-10-16)
            members = self.unions.get("DeletePostPayload") or []
            allowed = {m["name"] for m in members} | {i["name"] for m in members for i in m.get("interfaces") or []}
            for spread in re.findall(r"\.\.\.\s*on\s+(\w+)", payload["query"]):
                if spread not in allowed:
                    return Response(200, {}, {"errors": [{"message": f'Fragment cannot be spread here as objects of type "DeletePostPayload" can never be of type "{spread}".',
                                                          "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"}}]})
            pid = payload["variables"]["input"]["id"]
            if pid in self.reject_at:
                return Response(200, {}, {"data": {"deletePost": {"__typename": "VoidMutationError", "message": "post already sent"}}})
            self.deleted.append(pid)
            ok = next((m["name"] for m in members if not m.get("interfaces")), "DeletePostSuccess")
            return Response(200, {}, {"data": {"deletePost": {"__typename": ok, "id": pid}}})
        if "Posts" in op:
            if self.raise_on_posts:
                raise ConnectionError("read timed out")
            if self.posts_nodes is not None:
                return Response(200, {}, {"data": {"posts": {"edges": [{"node": n} for n in self.posts_nodes],
                                                             "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
            return Response(200, {}, {"data": {"posts": {"edges": [{"node": {
                "id": "post-1", "channelId": "ch-ig", "channelService": "instagram", "status": "sent",
                "sentAt": "2026-10-01T15:30:00Z", "dueAt": None, "text": "hi", "metricsUpdatedAt": "2026-10-02T00:00:00Z",
                "metrics": [{"type": "likes", "name": "Likes", "value": 4, "unit": "count"}]}}],
                "pageInfo": {"hasNextPage": False, "endCursor": "c1"}}}})
        return Response(200, {}, {"errors": [{"message": f"unknown op {op}"}]})


class AgentCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        self._conns = []
        keychain = mock.patch("convention_social.core.secrets._keychain", return_value=None)
        keychain.start()
        self.addCleanup(keychain.stop)

    def connect(self):
        """A database connection closed before the test's data root is removed."""
        conn = db.connect()
        self._conns.append(conn)
        return conn

    def tearDown(self):
        for conn in self._conns:
            conn.close()
        super().tearDown()


def make_ctx(conn, agent="publisher", dry_run=True) -> runner.Context:
    cfg = config.get_config()
    cfg.ensure_dirs()
    run_id = db.insert(conn, "agent_runs", agent=agent, started_at=db.utcnow(), dry_run=1 if dry_run else 0)
    return runner.Context(agent=agent, conn=conn, log=logs.get_logger(agent, to_stderr=False), cfg=cfg,
                          dry_run=dry_run, run_id=run_id)


def add_channels(conn, *services, connected=1):
    for s in services:
        db.insert(conn, "channels", buffer_channel_id=CHANNEL_IDS[s], service=s, display_name=f"Event Caliber {s}",
                  connected=connected)


def add_photo(conn, folder: Path, seed: int = 1, suffix: str = ".jpg") -> int:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"photo-{seed}{suffix}"
    path.write_bytes(jpeg_bytes(seed=seed))
    now = db.utcnow()
    return db.insert(conn, "photos", drive_id=f"drive-{seed}", name=path.name, mime_type="image/jpeg", md5=f"md5-{seed}",
                     local_path=str(path), first_seen_at=now, last_seen_at=now)


def write_render(folder: Path, name: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(jpeg_bytes(seed=len(name)))
    return str(path)


CLEAN = {"instagram": "Backstage before the keynote. Request a quote for your event.\n\n#eventphotography",
         "facebook": "Backstage before the keynote. Request a quote for your event.",
         "pinterest": "Backstage before the keynote, calm and ready. #eventphotography #conventionphotography",
         "linkedin": "Backstage before the keynote. I was in the room before the doors opened. Request a quote for your event.\n\n#eventphotography"}


def add_post(conn, photo_ids, targets=("instagram", "facebook", "pinterest"), *, captions=None, status="approved",
             convention_id=None, scheduled_for=None, render_paths=None, kind="photo") -> int:
    now = db.utcnow()
    caps = captions if captions is not None else {t: CLEAN[t] for t in targets}
    return db.insert(conn, "content_queue", kind=kind, photo_ids=json.dumps(list(photo_ids)), convention_id=convention_id,
                     targets=json.dumps(list(targets)), caption=json.dumps(caps), status=status,
                     scheduled_for=scheduled_for, render_paths=json.dumps(render_paths) if render_paths else None,
                     approved_at=now if status == "approved" else None, created_at=now, updated_at=now)


def eligibility(verdict):
    """A stand-in for convention_social.library.eligibility: is_eligible(conn, photo_id) -> (bool, why)."""
    module = types.ModuleType("fake_eligibility")
    module.calls = []

    def is_eligible(conn, photo_id):
        module.calls.append(photo_id)
        return verdict(photo_id)

    module.is_eligible = is_eligible
    return module


def all_eligible():
    return eligibility(lambda pid: (True, "cleared"))


def outbox(cfg) -> list[Path]:
    return sorted((cfg.data_root / "outbox-dry").glob("*.eml"))


def read_mail(path: Path):
    """(message, html body text, plain body text) of an .eml written by core.mail."""
    msg = message_from_bytes(path.read_bytes(), policy=policy.default)
    html_part = msg.get_body(preferencelist=("html",))
    plain_part = msg.get_body(preferencelist=("plain",))
    return msg, html_part.get_content() if html_part else "", plain_part.get_content() if plain_part else ""
