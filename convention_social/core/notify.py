"""Phone push through ntfy.sh on the suite's own topic.

Only fires when NTFY_TOPIC is set and the caller is live; dry runs and test
processes never reach the network. Email remains the alert of record.

What pings Chris (2026-10-11, "I haven't received any ntfy"): a post ready to
approve (the content agent), a post that went out (the publisher), the
watchdog's alerts, the morning brief, and the test button on the Keys page.
Each one opens the right dashboard page when tapped.
"""
from __future__ import annotations

import sys

from . import config

NTFY_URL = "https://ntfy.sh"


def _ascii(text: str) -> str:
    """HTTP headers are latin-1; a stray middle dot or dash would make the whole push fail silently."""
    return text.replace("·", "-").replace("–", "-").replace("—", "-").encode("ascii", "ignore").decode().strip()


def link(path: str = "/") -> str:
    """The dashboard address Chris opens from his phone (DASHBOARD_PUBLIC_URL), else the Mini's own."""
    cfg = config.get_config()
    base = cfg.dashboard_public_url or f"http://127.0.0.1:{cfg.dashboard_port}"
    return base + path


def push_result(title: str, message: str, *, dry_run: bool = True, priority: str = "high", transport=None,
                click: str | None = None) -> str:
    """Sends, and says what happened: "sent", or why nothing was. `click` is the address the phone
    opens when the notification is tapped."""
    cfg = config.get_config()
    if not cfg.ntfy_topic:
        return "no ntfy topic is set (Keys page, Phone alerts)"
    if dry_run:
        return "dry run: nothing sent"
    if "unittest" in sys.modules and transport is None:
        return "no push from a test"
    try:
        if transport is None:
            import requests
            transport = lambda url, **kw: requests.post(url, timeout=10, **kw)  # noqa: E731
        headers = {"Title": _ascii(title), "Priority": priority}
        if click:
            headers["Click"] = click
        r = transport(f"{NTFY_URL}/{cfg.ntfy_topic}", data=message.encode("utf-8"), headers=headers)
        code = getattr(r, "status_code", 200)
        return "sent" if code < 300 else f"ntfy answered {code}"
    except Exception as e:  # noqa: BLE001
        return f"could not reach ntfy ({type(e).__name__}: {e})"


def push(title: str, message: str, *, dry_run: bool = True, priority: str = "high", transport=None,
         click: str | None = None) -> bool:
    return push_result(title, message, dry_run=dry_run, priority=priority, transport=transport, click=click) == "sent"
