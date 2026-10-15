"""The Mini's side of the eventcaliber.com Worker's booking API.

The Mini sits behind Tailscale, so the site cannot reach it: the Mini pulls.
Every call carries the same bearer token the image uploads use
(MEDIA_UPLOAD_TOKEN), and the transport is injectable so tests never touch
the network.
"""
from __future__ import annotations

from typing import Callable, Optional

from ..core import config, secrets

Transport = Callable[[str, str, dict, Optional[dict]], object]   # (method, url, headers, json) -> response


def site_base() -> str:
    return (config.getenv("SITE_BASE_URL") or f"https://{config.get_config().brand_domain}").rstrip("/")


def requests_transport(method: str, url: str, headers: dict, payload: Optional[dict]):
    import requests
    r = requests.request(method, url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    return r


class SiteAPI:
    def __init__(self, token: str, *, base: Optional[str] = None, transport: Optional[Transport] = None):
        self.token = token
        self.base = (base or site_base()).rstrip("/")
        self.transport = transport or requests_transport

    @classmethod
    def from_config(cls) -> Optional["SiteAPI"]:
        token = secrets.get_secret("MEDIA_UPLOAD_TOKEN")
        return cls(token) if token else None

    def _call(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        r = self.transport(method, self.base + path, {"Authorization": f"Bearer {self.token}"}, payload)
        return r.json()

    def pull(self) -> list[dict]:
        return list(self._call("GET", "/api/inquiries").get("inquiries") or [])

    def ack(self, ids: list[str]) -> int:
        return int(self._call("POST", "/api/inquiries/ack", {"ids": ids}).get("deleted") or 0) if ids else 0

    def put_availability(self, days: list[str]) -> int:
        return int(self._call("PUT", "/api/availability", {"booked": days}).get("booked") or 0)

    def heartbeat(self) -> dict:
        """The Mini checks in (7.4, 2026-10-13): the site's cron rings the phone when these stop."""
        return self._call("POST", "/api/heartbeat", {})

    def test_watch(self) -> dict:
        """Sends the outside watch's alert at once, marked as a test. {ok, sent}."""
        return self._call("POST", "/api/heartbeat/test", {})

    # Post to Event Caliber (2026-10-15): the photos the iPhone's share sheet sent, waiting at the site (agents/phone.py)
    def sends(self) -> list[dict]:
        """[{id, note, type, size, received_at}], oldest first."""
        return list(self._call("GET", "/api/sends").get("sends") or [])

    def send_bytes(self, send_id: str) -> bytes:
        r = self.transport("GET", f"{self.base}/api/sends/{send_id}", {"Authorization": f"Bearer {self.token}"}, None)
        return r.content

    def ack_sends(self, ids: list[str]) -> int:
        """Kept on the Mini: deleted at the site."""
        return int(self._call("POST", "/api/sends/ack", {"ids": ids}).get("deleted") or 0) if ids else 0
