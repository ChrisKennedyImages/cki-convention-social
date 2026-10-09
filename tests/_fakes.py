"""Fakes and seeds for the publishing, watchdog and backup tests. Nothing here touches the network.

AgentCase also stops the macOS Keychain from being read: on the Mac mini a real
BUFFER_API_KEY or MEDIA_UPLOAD_TOKEN may live there, and a test must never be
able to pick one up and reach a real service.
"""
from __future__ import annotations

import json
import types
from email import message_from_bytes, policy
from pathlib import Path
from unittest import mock

from convention_social.buffer.client import Response
from convention_social.core import config, db, logs, runner
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

CHANNEL_IDS = {"instagram": "ch-ig", "facebook": "ch-fb", "pinterest": "ch-pin"}


class FakeBuffer:
    """Canned GraphQL responses keyed by operation name; records every request."""

    def __init__(self, *, status_sequence=None, reject_at=(), http_status=200, retry_after=None,
                 disconnected=(), error_message="Image could not be fetched"):
        self.calls = []
        self.created = []
        self.status_sequence = list(status_sequence or ["scheduled", "sent"])
        self.reject_at = set(reject_at)          # 1-based createPost calls to refuse
        self.http_status = http_status
        self.retry_after = retry_after
        self.disconnected = set(disconnected)
        self.error_message = error_message
        self.n_status = 0
        self.n_create = 0

    def __call__(self, url, payload, headers):
        op = payload["query"].strip().split("\n")[0]
        self.calls.append((op, payload["variables"]))
        assert url == "https://api.buffer.com"
        assert headers["Authorization"] == "Bearer test-key"
        assert headers["User-Agent"] == "cki-convention-social/0.1"
        if self.http_status == 429:
            return Response(429, {"Retry-After": str(self.retry_after or 42)}, {})
        if self.http_status >= 400:
            return Response(self.http_status, {}, {"message": "boom"})
        if "Organizations" in op:
            return Response(200, {}, {"data": {"account": {"organizations": [{"id": "org-1", "name": "Event Caliber"}]}}})
        if "PinterestBoards" in op:
            return Response(200, {}, {"data": {"channel": {"id": payload["variables"]["input"]["id"], "service": "pinterest",
                                                           "metadata": {"__typename": "PinterestMetadata",
                                                                        "boards": [{"serviceId": "board-123", "name": "Conventions"}]}}}})
        if "Channels" in op:
            return Response(200, {}, {"data": {"channels": [
                {"id": cid, "name": svc, "service": svc, "displayName": f"Event Caliber {svc}",
                 "isDisconnected": svc in self.disconnected, "isLocked": False, "isQueuePaused": False}
                for svc, cid in CHANNEL_IDS.items()]}})
        if "CreatePost" in op:
            self.n_create += 1
            if self.n_create in self.reject_at:
                return Response(200, {}, {"data": {"createPost": {"__typename": "InvalidInputError", "message": "board not found"}}})
            self.created.append(payload["variables"]["input"])
            return Response(200, {}, {"data": {"createPost": {"__typename": "PostActionSuccess", "post": {"id": f"post-{len(self.created)}"}}}})
        if "PostStatus" in op:
            status = self.status_sequence[min(self.n_status, len(self.status_sequence) - 1)]
            self.n_status += 1
            post = {"id": payload["variables"]["input"]["id"], "status": status,
                    "sentAt": "2026-10-09T15:30:05Z" if status == "sent" else None,
                    "error": {"message": self.error_message} if status == "error" else None}
            return Response(200, {}, {"data": {"post": post}})
        if "Posts" in op:
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
         "pinterest": "Backstage before the keynote, calm and ready. #eventphotography #conventionphotography"}


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
