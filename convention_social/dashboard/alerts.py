"""Every alert with the button that fixes it, where a fix exists (Chris, 2026-10-15: "everything is just very confusing").

The open errors (`errors.alerted = 0`) are shown one card per kind, newest first, on the Errors page and in Needs you
on Today. Each card says what happened in plain words and carries the fix when there is one: a link where the fix
is his to make (Sign in to Drive, add a key, link a channel), a button where the suite can do it (approve a failed
post again, run an agent again), and Dismiss for all of that kind. A fix that runs also dismisses the kind: if it
happens again it is said again (2026-10-13, "every failure is said once, and out loud").

An alert about a network that is off never shows: the publisher leaves an off network out quietly (POST_NETWORKS on
the Keys page, Instagram only by default; buffer.payloads.posting_networks), so "not sent to facebook" is no fault.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from ..agents import AGENTS, is_built
from ..buffer import payloads as buffer_payloads
from ..core import db

TITLES = {
    "drive_auth": "Google Drive is signed out",
    "buffer_key_missing": "No Buffer key",
    "media_missing": "No image hosting",
    "buffer_budget": "Buffer's request limit",
    "no_channel": "No Buffer channel",
    "no_day": "No open day to post",
    "alert_mail": "Alert mail could not be sent",
    "brief_mail": "The morning brief mail could not be sent",
    "ntfy": "A phone ping did not go",
    "page_error": "A dashboard page broke",
    "dashboard_down": "The dashboard was not answering",
    "update_tests": "An update was held back",
    "update_requirements": "An update's requirements",
    "no_draft": "No post was drafted",
    "final_check": "Claude's final check could not run",
    "captions": "The caption writer could not write",
    "art_director": "The art director could not look",
    "mend": "A caption could not be rewritten",
    "door": "A post went back to its draft",
    "post_error": "A post did not go out",
    "BufferError": "Buffer refused a post",
    "MediaError": "A post's picture could not be sent",
    "PayloadError": "A post could not be built for Buffer",
    "verify_failed": "Buffer could not be asked about a post",
    "sample": "An idea was not drafted",
    "designed": "A designed draft could not be made",
    "seo_text": "Search text for a photo",
    "verification_tag": "The Search Console value",
    "reel": "A reel could not be made",
}

# the fix is his to make, on another page
LINKS = {
    "drive_auth": ("Sign in to Drive", "/drive/login"),
    "buffer_key_missing": ("Add the Buffer key", "/keys"),
    "media_missing": ("Set up image hosting", "/keys"),
    "alert_mail": ("Set up mail", "/keys"),
    "brief_mail": ("Set up mail", "/keys"),
    "ntfy": ("Check the phone alerts", "/keys"),
    "no_channel": ("Link the channels", "/buffer"),
    "no_day": ("Open the post", None),
    "verification_tag": ("Fix the value", "/keys"),
}
NO_FIX = {"buffer_budget", "page_error", "dashboard_down"}      # it passes by itself, or there is nothing to press
NOT_RUN_AGAIN = {"sample", "dashboard", "art_director"}          # running these again does nothing for the alert
POST_IN = re.compile(r"\bpost #?(\d+)\b", re.I)
AGENT_WORDS = {"seo": "search agent", "content": "daily draft", "designed": "designed drafts", "scanner": "scanner",
               "publisher": "publisher", "watchdog": "watchdog", "updater": "updater", "inbox": "inbox", "chief": "morning brief",
               "learner": "learner", "scout": "scout", "outreach": "outreach", "phone": "photo from the phone", "backup": "backup"}


def networks_on() -> tuple[str, ...]:
    """The networks posts go to (POST_NETWORKS on the Keys page; Instagram only when blank, 2026-10-15)."""
    return tuple(buffer_payloads.posting_networks())


def about_off_network(message: str, on: tuple[str, ...]) -> bool:
    """True when the message names a network and every network it names is off."""
    named = [n for n in buffer_payloads.NETWORKS if n in (message or "").lower()]
    return bool(named) and not any(n in on for n in named)


def post_of(message: str) -> Optional[int]:
    m = POST_IN.search(message or "")
    return int(m.group(1)) if m else None


def fix_for(conn: sqlite3.Connection, kind: str, agent: str, message: str) -> Optional[dict]:
    """{label, href} for a fix on another page; {label, action} for one the suite does; None when there is none."""
    if kind in LINKS:
        label, href = LINKS[kind]
        if href is None:
            qid = post_of(message)
            return {"label": label, "href": f"/queue/{qid}"} if qid else None
        return {"label": label, "href": href}
    if kind in NO_FIX:
        return None
    qid = post_of(message)
    if qid is not None:
        row = db.one(conn, "SELECT status FROM content_queue WHERE id=?", (qid,))
        if row is not None and row["status"] == "failed":
            return {"label": f"Approve post {qid} again", "action": "retry", "qid": qid}
    if agent in AGENTS and agent not in NOT_RUN_AGAIN and is_built(agent):
        return {"label": f"Run the {AGENT_WORDS.get(agent, agent)} again", "action": "run", "agent": agent}
    return None


def open_alerts(conn: sqlite3.Connection, *, limit: Optional[int] = None) -> list[dict]:
    """One card per kind, newest first: {kind, title, agent, n, ts, message, fix, items}; alerts about networks that
    are off are left out (and not counted)."""
    on = networks_on()
    groups: dict[str, dict] = {}
    for e in db.rows(conn, "SELECT * FROM errors WHERE alerted=0 ORDER BY id DESC LIMIT 500"):
        if about_off_network(e["message"], on):
            continue
        g = groups.get(e["kind"])
        if g is None:
            g = groups[e["kind"]] = {"kind": e["kind"], "title": TITLES.get(e["kind"], e["kind"].replace("_", " ").capitalize()),
                                     "agent": e["agent"], "n": 0, "ts": e["ts"], "message": e["message"], "items": []}
        g["n"] += 1
        if len(g["items"]) < 10:
            g["items"].append({"id": e["id"], "ts": e["ts"], "agent": e["agent"], "message": e["message"]})
    out = list(groups.values())
    for g in out:
        g["fix"] = fix_for(conn, g["kind"], g["agent"], g["message"])
    return out[:limit] if limit else out
