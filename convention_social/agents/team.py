"""Chris's photographers, sending photos from the event the moment they take them (2026-10-15).

Chris: "What if I have several photographers that I want to be able to share photos instantly?" His choices: a team
member's photo comes to him as a ping with the card and one tap (Approve, or Skip); every instant photo goes out as an
Instagram Story, and the best can also go to the feed ("Also post to the feed"); at most STORY_CAP Stories and FEED_CAP
feed posts a day from instant photos, everyone together. His own sends keep posting right away (2026-10-15, "Right
away"), as a Story now.

Each photographer has a first name, kept on this Mini only and shown only to Chris (the Team page, the Send page): a
ping never names them (ntfy topics are not private) and nothing public ever does (the captions' rules already refuse
names). Each has a send token of their own, shown to Chris once and kept here only as its SHA-256; the site gets the
hashes, the on/off switch and the one-time phone links' hashes (PUT /api/team), never a name, so a new photographer or
a switch-off takes effect at once, with no redeploy. A phone without Shortcuts opens a one-time link (/join/<code>,
JOIN_DAYS to use it) that sets a cookie for the site's upload page.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets as pysecrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..core import config, db, runner, settings

STORY_CAP = 10
FEED_CAP = 2
CAPS = {"story": (STORY_CAP, "Stories"), "feed": (FEED_CAP, "feed posts")}
JOIN_DAYS = 7
NAME = re.compile(r"^[^\W\d_]+(?:['-][^\W\d_]+)*(?: [^\W\d_]+(?:['-][^\W\d_]+)*)?$")   # a first name: one or two words
NAME_MAX = 24
SHORTCUT_LINK_KEY = "team.shortcut_link"   # the Shortcut's iCloud link Chris shares with the team (Team page)
SHORTCUT_LINK = re.compile(r"^https://www\.icloud\.com/shortcuts/[0-9a-f]{32}$")
COUNTED = ("approved", "scheduled", "published")


class Refused(ValueError):
    pass


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > NAME_MAX or not NAME.match(name):
        raise Refused("a first name only, in letters (one or two words)")
    return name


def members(conn: sqlite3.Connection) -> list[dict]:
    """For the Team page: everyone, with how many photos they sent and when the last one came, in his own time zone."""
    out = []
    for r in db.rows(conn, """SELECT m.*, COUNT(s.id) AS sends, MAX(s.created_at) AS last_send FROM team_members m
                             LEFT JOIN phone_sends s ON s.sender_id = m.id GROUP BY m.id ORDER BY m.active DESC, m.name"""):
        d = dict(r)
        d["last_send_at"] = local_stamp(d["last_send"])
        out.append(d)
    return out


def local_stamp(stamp: Optional[str]) -> str:
    """'Oct 15, 15:02' where he is (TIMEZONE), from a UTC stamp; '' when there is none."""
    try:
        t = datetime.fromisoformat((stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    t = (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo(config.get_config().timezone))
    return f"{t:%b} {t.day}, {t:%H:%M}"


def member_for(conn: sqlite3.Connection, sender: str):
    """The photographer behind a send's sender ("m<number>"), only while they are on; None for anyone else."""
    m = re.fullmatch(r"m(\d+)", sender or "")
    return db.one(conn, "SELECT * FROM team_members WHERE id=? AND active=1", (int(m.group(1)),)) if m else None


def name_of(conn: sqlite3.Connection, member_id) -> str:
    row = db.one(conn, "SELECT name FROM team_members WHERE id=?", (member_id,)) if member_id else None
    return row["name"] if row else ""


def site_body(conn: sqlite3.Connection) -> dict:
    """What the site holds: numbers, hashes, on or off, and the phone links not yet expired. Never a name."""
    now = db.utcnow()
    return {"members": [{"id": r["id"], "token_sha256": r["token_sha256"], "active": bool(r["active"])}
                        for r in db.rows(conn, "SELECT id, token_sha256, active FROM team_members ORDER BY id")],
            "joins": [{"code_sha256": r["code_sha256"], "member_id": r["member_id"], "expires_at": r["expires_at"]}
                      for r in db.rows(conn, "SELECT * FROM team_joins WHERE expires_at > ? ORDER BY id", (now,))]}


def push(conn: sqlite3.Connection, api=None) -> tuple[bool, str]:
    """The team to the site, at once. Fails closed: until the site has it, a new token or link does not work there."""
    from ..booking.remote import SiteAPI
    api = api or SiteAPI.from_config()
    if api is None:
        return False, "not on the site yet: this Mini has no site token (MEDIA_UPLOAD_TOKEN)"
    try:
        api.put_team(site_body(conn))
    except Exception as e:  # noqa: BLE001  said on the page and on the Agents page; the next change tries again
        why = f"not on the site yet: the site did not take the team list ({type(e).__name__})"
        runner.record_error_once(conn, "team", "team_push", f"The team list is {why}. The next change on the Team page sends it again.")
        return False, why
    return True, ""


def add(conn: sqlite3.Connection, name: str, api=None) -> tuple[int, str]:
    """(their number, their send token: shown to Chris once and never kept)."""
    name = clean_name(name)
    token = pysecrets.token_urlsafe(32)
    now = db.utcnow()
    mid = db.insert(conn, "team_members", name=name, token_sha256=_hash(token), active=1, created_at=now, updated_at=now)
    push(conn, api)
    return mid, token


def new_token(conn: sqlite3.Connection, member_id: int, api=None) -> str:
    """A new token for them; the old one stops working once the site has the list."""
    token = pysecrets.token_urlsafe(32)
    conn.execute("UPDATE team_members SET token_sha256=?, updated_at=? WHERE id=?", (_hash(token), db.utcnow(), member_id))
    push(conn, api)
    return token


def set_active(conn: sqlite3.Connection, member_id: int, active: bool, api=None) -> tuple[bool, str]:
    conn.execute("UPDATE team_members SET active=?, updated_at=? WHERE id=?", (1 if active else 0, db.utcnow(), member_id))
    return push(conn, api)


def phone_link(conn: sqlite3.Connection, member_id: int, api=None) -> str:
    """A one-time link for a phone without Shortcuts: it opens the site's upload page on that phone, once."""
    from ..booking.remote import site_base
    code = pysecrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(days=JOIN_DAYS)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    db.insert(conn, "team_joins", member_id=member_id, code_sha256=_hash(code), expires_at=expires, created_at=db.utcnow())
    push(conn, api)
    return f"{site_base()}/join/{code}"


def shortcut_link(conn: sqlite3.Connection) -> str:
    return settings.get(conn, SHORTCUT_LINK_KEY) or ""


def set_shortcut_link(conn: sqlite3.Connection, link: str) -> None:
    link = (link or "").strip()
    if not SHORTCUT_LINK.match(link):
        raise Refused("that is not a Shortcut's iCloud link (https://www.icloud.com/shortcuts/...)")
    settings.set(conn, SHORTCUT_LINK_KEY, link)


# ------------------------------------------------------------------ the day's cap on instant photos

def today(cfg=None) -> str:
    return datetime.now(ZoneInfo((cfg or config.get_config()).timezone)).date().isoformat()


def _local_day(stamp: Optional[str]) -> str:
    try:
        t = datetime.fromisoformat((stamp or "").replace("Z", "+00:00"))
    except ValueError:
        return ""
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(ZoneInfo(config.get_config().timezone)).date().isoformat()


def used_today(conn: sqlite3.Connection, fmt: str, *, include_dry: bool = False, exclude: Optional[int] = None) -> int:
    """Instant photos of this format today, everyone together: handed to Buffer today, or approved today and on the way."""
    statuses = COUNTED + (("would_publish",) if include_dry else ())
    day, n = today(), 0
    for r in db.rows(conn, f"SELECT id, status, rule_report, approved_at FROM content_queue WHERE status IN ({','.join('?' * len(statuses))})",
                     statuses):
        if r["id"] == exclude:
            continue
        try:
            meta = json.loads(r["rule_report"] or "{}")
        except ValueError:
            continue
        if not isinstance(meta, dict) or not meta.get("instant") or meta.get("format") != fmt:
            continue
        if meta.get("sent_on") == day or (r["status"] == "approved" and _local_day(r["approved_at"]) == day):
            n += 1
    return n


def room_for(conn: sqlite3.Connection, fmt: str, *, include_dry: bool = False, exclude: Optional[int] = None) -> tuple[bool, str]:
    """(room for one more today, why not). The plain line the dashboard and the ping carry when there is none."""
    cap, words = CAPS[fmt]
    if used_today(conn, fmt, include_dry=include_dry, exclude=exclude) < cap:
        return True, ""
    return False, (f"Today's {cap} {words} from instant photos are used, everyone together. It waits here; "
                   "approve it again tomorrow if you still want it")


# ------------------------------------------------------------------ Also post to the feed

def also_feed(conn: sqlite3.Connection, qid: int) -> tuple[Optional[int], str]:
    """A feed post of an instant photo's Story, on the same road: the same photo, its captions and its 4:5 card, approved
    by his press, posted right away; once per photo, and inside the day's FEED_CAP. (new post id, why not)."""
    row = db.one(conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
    try:
        meta = json.loads(row["rule_report"] or "{}") if row else {}
    except ValueError:
        meta = {}
    if not row or not meta.get("instant") or meta.get("format") != "story":
        return None, "only an instant photo's Story can also go to the feed"
    if row["status"] not in ("approved", "scheduled", "published", "would_publish"):
        return None, "the Story is not approved"
    for other in db.rows(conn, "SELECT rule_report FROM content_queue WHERE status != 'rejected'"):
        try:
            if json.loads(other["rule_report"] or "{}").get("feed_of") == qid:
                return None, "this photo is already on its way to the feed"
        except (ValueError, AttributeError):
            continue
    ok, why = room_for(conn, "feed")
    if not ok:
        return None, why
    renders = {k: v for k, v in json.loads(row["render_paths"] or "{}").items() if k != "story"}
    now = db.utcnow()
    feed_meta = {**{k: v for k, v in meta.items() if k not in ("sent_on", "approved_by", "nudged_at")},
                 "format": "feed", "feed_of": qid, "approved_by": "chris"}
    new = db.insert(conn, "content_queue", kind="photo", photo_ids=row["photo_ids"], targets=row["targets"], caption=row["caption"],
                    render_paths=json.dumps(renders), rule_report=json.dumps(feed_meta), status="approved", approved_at=now,
                    created_at=now, updated_at=now)
    runner.start_agent("publisher", wait=True)
    return new, ""
