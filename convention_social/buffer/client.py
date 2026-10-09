"""Buffer GraphQL client. One endpoint, bearer key, every request through the budget.

Query shapes: organizations first, because account.currentOrganization is
forbidden to personal keys; channels(input: {organizationId}); createPost
returns a union (PostActionSuccess or one of the MutationError members) and
only a positive PostActionSuccess with a post id counts; post(input: {id}) for
status; posts(input, first, after) with metrics. These shapes ran against
Buffer's live API in the suite this client was ported from, and every type and
field used here was checked against Buffer's live schema by introspection on
2026-10-09. They have not yet been run against this company's own account.

A 429 raises BufferRateLimited with the Retry-After seconds; GraphQL errors
raise BufferError. The transport is injectable so tests never touch the network.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from ..core import config, secrets, state_io
from . import budget

API_URL = "https://api.buffer.com"
TIMEOUT = 30
USER_AGENT = "cki-convention-social/0.1"

Q_ORGANIZATIONS = """
query Organizations {
  account { organizations { id name } }
}
"""
Q_CHANNELS = """
query Channels($input: ChannelsInput!) {
  channels(input: $input) { id name service displayName isDisconnected isLocked isQueuePaused }
}
"""
# Pinterest boards live on the channel (ChannelMetadata union -> PinterestMetadata.boards).
# A board's serviceId is what PinterestPostMetadataInput.boardServiceId takes.
Q_PINTEREST_BOARDS = """
query PinterestBoards($input: ChannelInput!) {
  channel(input: $input) {
    id service
    metadata { __typename ... on PinterestMetadata { boards { serviceId name } } }
  }
}
"""
M_CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
}
"""
Q_POST_STATUS = """
query PostStatus($input: PostInput!) {
  post(input: $input) { id status sentAt error { message } }
}
"""
Q_POSTS = """
query Posts($input: PostsInput!, $first: Int!, $after: String) {
  posts(input: $input, first: $first, after: $after) {
    edges { node {
      id channelId channelService status sentAt dueAt text metricsUpdatedAt externalLink
      metrics { type name value unit }
    } }
    pageInfo { hasNextPage endCursor }
  }
}
"""


class BufferError(RuntimeError):
    pass


class BufferRateLimited(BufferError):
    def __init__(self, retry_after: int):
        super().__init__(f"Buffer rate limited; retry after {retry_after}s")
        self.retry_after = retry_after


class BufferBudgetExceeded(BufferError):
    pass


@dataclass
class Response:
    status: int
    headers: dict
    body: dict = field(default_factory=dict)


Transport = Callable[[str, dict, dict], Response]


def requests_transport(url: str, payload: dict, headers: dict) -> Response:
    import requests
    r = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    try:
        body = r.json()
    except ValueError:
        body = {}
    return Response(r.status_code, dict(r.headers), body)


class BufferClient:
    def __init__(self, api_key: str, *, conn: Optional[sqlite3.Connection] = None, agent: str = "publisher",
                 transport: Optional[Transport] = None, plan: Optional[str] = None):
        self.api_key = api_key
        self.conn = conn
        self.agent = agent
        self.transport = transport or requests_transport
        self.plan = plan
        self._org: Optional[str] = None

    @classmethod
    def from_config(cls, conn: sqlite3.Connection, agent: str = "publisher") -> Optional["BufferClient"]:
        key = secrets.get_secret("BUFFER_API_KEY")
        return cls(key, conn=conn, agent=agent) if key else None

    # ------------------------------------------------------------------ transport
    def _gql(self, query: str, variables: Optional[dict] = None, *, op: str = "") -> dict:
        if self.conn is not None:
            ok, why = budget.allow(self.conn, self.plan)
            if not ok:
                raise BufferBudgetExceeded(why)
            budget.record(self.conn, self.agent, op or query.strip().split("\n")[0][:60])
        resp = self.transport(API_URL, {"query": query, "variables": variables or {}},
                              {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                               "User-Agent": USER_AGENT})
        if resp.status == 429:
            try:
                retry = int(resp.headers.get("Retry-After") or resp.headers.get("retry-after") or 60)
            except (TypeError, ValueError):
                retry = 60
            raise BufferRateLimited(max(1, min(retry, 900)))
        if resp.status >= 400:
            raise BufferError(f"Buffer HTTP {resp.status}: {json.dumps(resp.body)[:300]}")
        if resp.body.get("errors"):
            raise BufferError(f"Buffer GraphQL: {json.dumps(resp.body['errors'])[:400]}")
        return resp.body.get("data") or {}

    # ------------------------------------------------------------------ discovery
    def organization_id(self) -> str:
        if self._org:
            return self._org
        data = self._gql(Q_ORGANIZATIONS, op="Organizations")
        orgs = ((data.get("account") or {}).get("organizations")) or []
        if not orgs or not orgs[0].get("id"):
            raise BufferError("no Buffer organization visible to this key")
        self._org = orgs[0]["id"]
        return self._org

    @staticmethod
    def cache_path():
        return config.get_config().data_root / "cache" / "buffer_channels.json"

    def channels(self, refresh: bool = False) -> list[dict]:
        cached = state_io.load_json(self.cache_path(), {})
        if not refresh and isinstance(cached, dict) and cached.get("channels"):
            self._org = self._org or cached.get("organizationId")
            return cached["channels"]
        org = self.organization_id()
        data = self._gql(Q_CHANNELS, {"input": {"organizationId": org}}, op="Channels")
        chans = data.get("channels") or []
        state_io.save_json(self.cache_path(), {"organizationId": org, "channels": chans,
                                               "fetched_at": datetime.now(timezone.utc).isoformat()}, indent=2)
        return chans

    def pinterest_boards(self, channel_id: str) -> list[dict]:
        """[{serviceId, name}] for a Pinterest channel: where PINTEREST_BOARD_ID comes from."""
        data = self._gql(Q_PINTEREST_BOARDS, {"input": {"id": channel_id}}, op="PinterestBoards")
        meta = ((data.get("channel") or {}).get("metadata")) or {}
        return list(meta.get("boards") or [])

    # ------------------------------------------------------------------ posting
    def create_post(self, post_input: dict) -> str:
        data = self._gql(M_CREATE_POST, {"input": post_input}, op="CreatePost")
        result = data.get("createPost") or {}
        if result.get("__typename") != "PostActionSuccess" and result.get("message"):
            raise BufferError(f"createPost rejected ({result.get('__typename')}): {result.get('message')}")
        post_id = (result.get("post") or {}).get("id")
        if result.get("__typename") != "PostActionSuccess" or not post_id:
            raise BufferError(f"createPost returned unrecognized shape: {json.dumps(result)[:200]}")
        return post_id

    def post_info(self, post_id: str) -> dict:
        """{status: lowercased or None, error: Buffer's publishing error message or None, sent_at: or None}."""
        data = self._gql(Q_POST_STATUS, {"input": {"id": post_id}}, op="PostStatus")
        post = data.get("post") or {}
        status = post.get("status")
        return {"status": str(status).lower() if status else None,
                "error": (post.get("error") or {}).get("message"),
                "sent_at": post.get("sentAt")}

    def post_status(self, post_id: str) -> Optional[str]:
        return self.post_info(post_id)["status"]

    def posts(self, *, status: str = "sent", channel_ids: Optional[list[str]] = None, first: int = 50,
              after: Optional[str] = None) -> tuple[list[dict], dict]:
        inp = {"organizationId": self.organization_id(), "filter": {"status": [status]}}
        if channel_ids:
            inp["filter"]["channelIds"] = channel_ids
        data = self._gql(Q_POSTS, {"input": inp, "first": first, "after": after}, op="Posts")
        block = data.get("posts") or {}
        nodes = [e.get("node") for e in (block.get("edges") or []) if e.get("node")]
        return nodes, block.get("pageInfo") or {}
