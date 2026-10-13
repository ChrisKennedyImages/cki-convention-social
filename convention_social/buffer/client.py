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
  post(input: $input) { id status sentAt externalLink error { message } }
}
"""
M_DELETE_POST = """
mutation DeletePost($input: DeletePostInput!) {
  deletePost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id } }
    ... on MutationError { message }
  }
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


# Read, don't recall: the shape of a video asset is asked of the live schema before a reel is built,
# never written from memory (the 2026-10-09 introspection named AssetInput's members, not their fields).
Q_INPUT_TYPE = """
query InputType($name: String!) {
  __type(name: $name) { name inputFields { name type { kind name ofType { kind name ofType { kind name } } } } }
}
"""


def _named(t: dict) -> tuple[str, bool]:
    """(the named type under any NON_NULL / LIST wrappers, whether the outermost is NON_NULL)."""
    required = (t or {}).get("kind") == "NON_NULL"
    while t and not t.get("name"):
        t = t.get("ofType") or {}
    return (t or {}).get("name") or "", required


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
    def organizations(self) -> list[dict]:
        """[{id, name}] every Buffer organization this key can see."""
        data = self._gql(Q_ORGANIZATIONS, op="Organizations")
        return [o for o in ((data.get("account") or {}).get("organizations")) or [] if o.get("id")]

    def organization_id(self) -> str:
        """The organization chosen on the dashboard's Buffer page (BUFFER_ORGANIZATION_ID), or the only
        one the key sees. A key that sees several and none chosen fails closed: posting to the wrong
        account's channels is the one mistake this must never make."""
        if self._org:
            return self._org
        chosen = config.getenv("BUFFER_ORGANIZATION_ID", "") or ""
        if chosen:
            self._org = chosen
            return self._org
        orgs = self.organizations()
        if not orgs:
            raise BufferError("no Buffer organization visible to this key")
        if len(orgs) > 1:
            raise BufferError(f"this Buffer key sees {len(orgs)} organizations; choose this company's on the Buffer page")
        self._org = orgs[0]["id"]
        return self._org

    @staticmethod
    def cache_path():
        return config.get_config().data_root / "cache" / "buffer_channels.json"

    def channels(self, refresh: bool = False) -> list[dict]:
        cached = state_io.load_json(self.cache_path(), {})
        chosen = config.getenv("BUFFER_ORGANIZATION_ID", "") or ""
        if not refresh and isinstance(cached, dict) and cached.get("channels") and (not chosen or cached.get("organizationId") == chosen):
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

    def input_fields(self, type_name: str) -> list[dict]:
        """[{name, type, required}] of one GraphQL input type, from the live schema (read once per client)."""
        cache = self.__dict__.setdefault("_types", {})
        if type_name in cache:
            return cache[type_name]
        data = self._gql(Q_INPUT_TYPE, {"name": type_name}, op=f"Schema {type_name}")
        t = data.get("__type") or {}
        if not t:
            raise BufferError(f"Buffer's schema has no type {type_name}")
        out = []
        for f in t.get("inputFields") or []:
            name, required = _named(f.get("type") or {})
            out.append({"name": f.get("name"), "type": name, "required": required})
        cache[type_name] = out
        return out

    ALT_NAMES = ("altText", "alt", "altTextDescription")

    def image_alt_path(self) -> Optional[list[str]]:
        """Where an image's alt text goes in AssetInput.image, read from the live schema: [field] or
        ["metadata", field]. None when Buffer offers no alt text field (then no alt text is sent)."""
        member = next((f for f in self.input_fields("AssetInput") if f["name"] == "image"), None)
        if member is None or not member["type"]:
            return None
        try:
            fields = self.input_fields(member["type"])
        except BufferError:
            return None
        direct = next((f["name"] for f in fields if f["name"] in self.ALT_NAMES), None)
        if direct:
            return [direct]
        meta = next((f for f in fields if f["name"] == "metadata" and f["type"]), None)
        if meta is None:
            return None
        try:
            inner = self.input_fields(meta["type"])
        except BufferError:
            return None
        found = next((f["name"] for f in inner if f["name"] in self.ALT_NAMES), None)
        return ["metadata", found] if found else None

    def video_asset_fields(self) -> list[dict]:
        """The fields of the input type behind AssetInput.video, both read from the live schema."""
        member = next((f for f in self.input_fields("AssetInput") if f["name"] == "video"), None)
        if member is None or not member["type"]:
            raise BufferError("Buffer's AssetInput has no video member")
        return self.input_fields(member["type"])

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
        """{status: lowercased or None, error: Buffer's publishing error message or None, sent_at: or None,
        external_link: the live post's address once sent (7.1, 2026-10-13), or None}."""
        data = self._gql(Q_POST_STATUS, {"input": {"id": post_id}}, op="PostStatus")
        post = data.get("post") or {}
        status = post.get("status")
        return {"status": str(status).lower() if status else None,
                "error": (post.get("error") or {}).get("message"),
                "sent_at": post.get("sentAt"), "external_link": post.get("externalLink") or None}

    def delete_post(self, post_id: str) -> bool:
        """Pull a post back from Buffer (7.5, 2026-10-13). The mutation's input is read from the live schema
        first (DeletePostInput must take an id), never recalled; a refusal is a BufferError with Buffer's words."""
        fields = {f["name"] for f in self.input_fields("DeletePostInput")}
        if "id" not in fields:
            raise BufferError(f"Buffer's DeletePostInput has no id field (it has {sorted(fields)}); not deleting blind")
        data = self._gql(M_DELETE_POST, {"input": {"id": post_id}}, op="DeletePost")
        result = data.get("deletePost") or {}
        if result.get("__typename") != "PostActionSuccess":
            raise BufferError(f"deletePost refused ({result.get('__typename')}): {result.get('message') or json.dumps(result)[:200]}")
        return True

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
