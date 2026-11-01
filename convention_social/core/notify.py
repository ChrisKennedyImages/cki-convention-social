"""Phone push through ntfy.sh on the suite's own topic.

Only fires when NTFY_TOPIC is set and the caller is live; dry runs and test
processes never reach the network. Email remains the alert of record.

What pings Chris (2026-10-11, "I haven't received any ntfy"): a post ready to
approve (the content agent, a designed draft, a photo from the phone), a post
that went out (the publisher), the watchdog's alerts, the morning brief, and
the test button on the Keys page. Each one opens the right dashboard page when
tapped; a draft's ping carries Post now, Follow the pace and Skip (2026-10-15).
"""
from __future__ import annotations

import sys

from . import access, approve_token, config, runner

NTFY_URL = "https://ntfy.sh"


def _ascii(text: str) -> str:
    """HTTP headers are latin-1; a stray middle dot or dash would make the whole push fail silently."""
    return text.replace("·", "-").replace("–", "-").replace("—", "-").encode("ascii", "ignore").decode().strip()


def link(path: str = "/") -> str:
    """The dashboard address Chris opens from his phone (DASHBOARD_PUBLIC_URL), else the Mini's own."""
    cfg = config.get_config()
    base = cfg.dashboard_public_url or f"http://127.0.0.1:{cfg.dashboard_port}"
    return base + path


NOT_A_FAILURE = ("sent", "dry run: nothing sent", "no push from a test")


CHOICES = (("now", "Post now"), ("pace", "Follow the pace"), ("skip", "Skip"))


def token_action(path: str, token: str, label: str) -> str:
    """One of his choices as an ntfy action, at the dashboard `path` that takes it. On the Tailscale address, an `http`
    action: a POST carrying the signed single-use token in its body (a GET on that address decides nothing), in the form
    docs.ntfy.sh/publish documents: `http, <label>, <url>, method=, headers.<h>=, body=, clear=true`. Behind Cloudflare
    Access (2026-10-15) only a browser gets in: the ntfy app's own POST would meet the sign-in and look done when nothing
    was decided, so the button opens the choice page in the browser instead (one more tap there)."""
    if access.through_access(link("/")):
        return f"view, {label}, {link(f'{path}?token={token}')}, clear=true"
    return (f"http, {label}, {link(path)}, method=POST, "
            f"headers.Content-Type=application/x-www-form-urlencoded, body='token={token}', clear=true")


def _choice(qid: int, token: str, how: str, label: str) -> str:
    """A draft's choice (Post now, Follow the pace, Skip) at its own route."""
    return token_action(f"/queue/{qid}/choose-by-token/{how}", token, label)


def choice_actions(qid: int, token: str) -> str:
    """The ntfy `Actions` header for a draft the art director passed (Chris, 2026-10-15): his three choices, the most
    ntfy shows. Post now (posted at once: Buffer's shareNow), Follow the pace (the next open Instagram slot, one post a
    slot) and Skip (set aside, its photos back in the rotation). A tap on the notification itself opens the draft
    (`Click`), where a reel plays with its sound. One token: the first choice made spends it."""
    return "; ".join(_choice(qid, token, how, label) for how, label in CHOICES)


def team_actions(qid: int, token: str) -> str:
    """A photo from Chris's team (2026-10-15, "Ping me, one tap"): Approve (his Post now: a Story, right away) and Skip,
    through the drafts' own choice route (one token; the first choice made spends it), and Open."""
    return f"{_choice(qid, token, 'now', 'Approve')}; {_choice(qid, token, 'skip', 'Skip')}; {open_action(qid)}"


def feed_actions(qid: int, token: str, live_link: str | None) -> str:
    """An instant photo's Story is up: open it, Also post to the feed, the dashboard. On the Tailscale address Also post
    to the feed is an http POST with a signed single-use token; behind Cloudflare Access only a browser gets in, so it
    opens the draft page, where the same button is (the ntfy app's own POST would meet the sign-in, 2026-10-15)."""
    first = f"view, Instagram, {live_link}; " if live_link else ""
    if access.through_access(link("/")):
        feed = f"view, Also post to the feed, {link(f'/queue/{qid}')}"
    else:
        feed = (f"http, Also post to the feed, {link(f'/queue/{qid}/feed-by-token')}, method=POST, "
                f"headers.Content-Type=application/x-www-form-urlencoded, body='token={token}', clear=true")
    return f"{first}{feed}; view, Dashboard, {link(f'/queue/{qid}')}"


def open_action(qid: int) -> str:
    """Open only: the draft page (the doctor's ping after it remade a reel: he looks before he chooses)."""
    return f"view, Open, {link(f'/queue/{qid}')}"


def look_actions(qid: int, token: str) -> str:
    """The art director did not pass the draft (or did not look): Open, so he looks himself before anything can go
    out, and Skip."""
    return f"{open_action(qid)}; " + _choice(qid, token, "skip", "Skip")


def card_link(row, token: str) -> str | None:
    """The rendered card, served by the dashboard to the phone with no login (`Attach`), under the token's card key, never
    the token itself (core/approve_token). None behind Cloudflare Access: the ntfy app fetches it itself, without the
    browser's sign-in, and would get the sign-in page."""
    if access.through_access(link("/")):
        return None
    return link(f"/media/card/{row['id']}/{approve_token.card_key(row, token)}.jpg")


def push_result(title: str, message: str, *, dry_run: bool = True, priority: str = "high", transport=None,
                click: str | None = None, conn=None, agent: str = "suite", actions: str | None = None,
                attach: str | None = None, filename: str | None = None) -> str:
    """Sends, and says what happened: "sent", or why nothing was. `click` is the address the phone
    opens when the notification is tapped; `actions` the ntfy Actions header (choice_actions); `attach`
    a picture's address the phone fetches itself (nothing is copied to ntfy). With `conn`, a push that did
    not go (live, and not from a test) is recorded once as an `ntfy` error for the Agents page and the
    watchdog's mail: a failed ping used to be a False nobody read (2026-10-13)."""
    result = _push(title, message, dry_run=dry_run, priority=priority, transport=transport, click=click,
                   actions=actions, attach=attach, filename=filename)
    if conn is not None and result not in NOT_A_FAILURE:
        runner.record_error_once(conn, agent, "ntfy", f"No phone ping: {result}")
    return result


def _push(title: str, message: str, *, dry_run: bool, priority: str, transport, click: str | None,
          actions: str | None = None, attach: str | None = None, filename: str | None = None) -> str:
    cfg = config.get_config()
    if dry_run:
        return "dry run: nothing sent"
    if not cfg.ntfy_topic:
        return "no ntfy topic is set (Keys page, Phone alerts)"
    if "unittest" in sys.modules and transport is None:
        return "no push from a test"
    try:
        if transport is None:
            import requests
            transport = lambda url, **kw: requests.post(url, timeout=10, **kw)  # noqa: E731
        headers = {"Title": _ascii(title), "Priority": priority}
        if click:
            headers["Click"] = click
        if actions:
            headers["Actions"] = _ascii(actions)
        if attach:
            headers["Attach"] = attach
        if attach and filename:                  # a Filename alone makes ntfy take the words as a file
            headers["Filename"] = _ascii(filename)
        r = transport(f"{NTFY_URL}/{cfg.ntfy_topic}", data=message.encode("utf-8"), headers=headers)
        code = getattr(r, "status_code", 200)
        return "sent" if code < 300 else f"ntfy answered {code}"
    except Exception as e:  # noqa: BLE001
        return f"could not reach ntfy ({type(e).__name__}: {e})"


def push(title: str, message: str, *, dry_run: bool = True, priority: str = "high", transport=None,
         click: str | None = None, conn=None, agent: str = "suite", actions: str | None = None,
         attach: str | None = None, filename: str | None = None) -> bool:
    return push_result(title, message, dry_run=dry_run, priority=priority, transport=transport, click=click,
                       conn=conn, agent=agent, actions=actions, attach=attach, filename=filename) == "sent"
