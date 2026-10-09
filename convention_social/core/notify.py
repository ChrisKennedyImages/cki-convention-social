"""Phone push through ntfy.sh on the suite's own topic.

Only fires when NTFY_TOPIC is set and the caller is live; dry runs and test
processes never reach the network. Email remains the alert of record.
"""
from __future__ import annotations

import sys

from . import config

NTFY_URL = "https://ntfy.sh"


def _ascii(text: str) -> str:
    """HTTP headers are latin-1; a stray middle dot or dash would make the whole push fail silently."""
    return text.replace("·", "-").replace("–", "-").replace("—", "-").encode("ascii", "ignore").decode().strip()


def push(title: str, message: str, *, dry_run: bool = True, priority: str = "high", transport=None,
         click: str | None = None) -> bool:
    """`click` is the address the phone opens when the notification is tapped."""
    cfg = config.get_config()
    if not cfg.ntfy_topic or dry_run or ("unittest" in sys.modules and transport is None):
        return False
    try:
        if transport is None:
            import requests
            transport = lambda url, **kw: requests.post(url, timeout=10, **kw)  # noqa: E731
        headers = {"Title": _ascii(title), "Priority": priority}
        if click:
            headers["Click"] = click
        r = transport(f"{NTFY_URL}/{cfg.ntfy_topic}", data=message.encode("utf-8"), headers=headers)
        return getattr(r, "status_code", 200) < 300
    except Exception:  # noqa: BLE001
        return False
