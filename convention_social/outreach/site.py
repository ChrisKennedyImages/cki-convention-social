"""The Mini's side of the opt-out store on the eventcaliber.com Worker.

The opt-out link in every outreach email carries only a random token. The
Worker keeps each token someone confirmed (GET /unsubscribe, then POST
/api/unsubscribe, or a mail client's one-click POST /unsubscribe) until the
Mini pulls it here and acks it; the Mini maps the token to the address and puts
that address on do-not-contact. Same bearer token and same injectable
transport as booking.remote.SiteAPI, so tests never touch the network.
"""
from __future__ import annotations

from typing import Optional

from ..booking.remote import Transport, requests_transport, site_base
from ..core import secrets


class UnsubscribeAPI:
    def __init__(self, token: str, *, base: Optional[str] = None, transport: Optional[Transport] = None):
        self.token = token
        self.base = (base or site_base()).rstrip("/")
        self.transport = transport or requests_transport

    @classmethod
    def from_config(cls) -> Optional["UnsubscribeAPI"]:
        token = secrets.get_secret("MEDIA_UPLOAD_TOKEN")
        return cls(token) if token else None

    def _call(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        r = self.transport(method, self.base + path, {"Authorization": f"Bearer {self.token}"}, payload)
        return r.json()

    def pull(self) -> list[dict]:
        """[{token, received_at}] for every opt-out the site holds."""
        return [u for u in (self._call("GET", "/api/unsubscribes").get("unsubscribes") or []) if isinstance(u, dict)]

    def ack(self, tokens: list[str]) -> int:
        return int(self._call("POST", "/api/unsubscribes/ack", {"tokens": tokens}).get("deleted") or 0) if tokens else 0
