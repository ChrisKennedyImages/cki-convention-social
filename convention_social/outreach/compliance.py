"""What every outreach email carries, and every reason one may not leave. Enforced here, in code.

An outreach email is refused (at Approve on the dashboard and again at send) unless:
  sender     BRAND_FROM_EMAIL is set and is an address on BRAND_DOMAIN: an accurate From
  address    BRAND_POSTAL_ADDRESS is set; it is printed in every footer, and with none nothing sends
  subject    present, not dressed up as a reply or a forward, and it passes ai.copy_rules
  body       present, passes ai.copy_rules (price, dash, affiliation, promise) and CLAIMS below
  contact    a valid address
  never      not CPAC, the ACU or an affiliate (Chris, 2026-10-13; the rule is code, no page removes it)
  blocked    the address is not on the do-not-contact list
  token      the row carries its own random opt-out token
  follow_up  at most one, only after the first note was sent, and not sooner than
             FOLLOW_UP_DAYS after it (follow_up_wait: approved, waiting for the day)

Every message built here carries the footer (company, legal name, postal address,
the one-click opt-out link and a reply STOP line) and the List-Unsubscribe
(mailto and https) and List-Unsubscribe-Post headers. The opt-out link carries
only the row's token, never the address.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlsplit

from ..ai import copy_rules, names
from ..core import config, db
from . import keys

FOLLOW_UP_DAYS = 7
OPEN_STATUSES = ("queued", "draft", "approved", "would_send", "failed")

# Claims the company cannot make: there are no past clients and no official roles (FOUNDER_DECISIONS.md).
# ai.copy_rules already blocks "clients include", "trusted by", "hired by" and "official ...".
CLAIMS = re.compile(
    r"\b(?:past|previous|former|our|my|happy|existing)\s+clients?\b|\bclient\s+list\b|\bportfolio\s+of\s+(?:your|the)\b"
    r"|\bworked\s+with\b|\b(?:photographed|shot|covered|worked)\s+(?:your|this|the)\s+(?:event|show|convention|conference|con|gala)\b",
    re.IGNORECASE,
)
REPLY_PREFIX = re.compile(r"^\s*(?:re|fw|fwd|aw|sv)\s*:", re.IGNORECASE)

# Chris, 2026-10-13: "never outreach to CPAC or the ACU or any affiliates! NEVER and that's a hard rule."
# The rule lives here, in code: no page can remove it. The names are the ones he gave (ai/names.ALWAYS); the
# domains are the ACU's own site (which also hosts CPAC), cpac.org and the ACU Foundation; any host with "cpac" in it
# is how the state CPACs are named; an affiliate named after the parent carries one of the NEVER_NAME_WORDS.
# The domain list could not be read from the sites themselves from the build sandbox (its network is closed); the
# names and the "cpac" host word are the gate that needs no list.
NEVER_DOMAINS = ("conservative.org", "cpac.org", "acuf.org")
NEVER_HOST_WORDS = ("cpac",)
NEVER_NAME_WORDS = ("conservative union", "conservative political action")
NEVER_MESSAGE = "CPAC, the ACU and their affiliates are never contacted (Chris, 2026-10-13)"

HOLD_CODES = {"sender", "address", "token", "follow_up", "follow_up_wait"}   # fix the setting or wait: stays approved
REDRAFT_CODES = {"subject", "body", "claims", "contact"}                     # the words or the address: back to draft


@dataclass
class Problem:
    code: str
    message: str


# ---------------------------------------------------------------------- never: CPAC, the ACU, affiliates
def never_host(host: str) -> bool:
    host = (host or "").lower().strip().rstrip(".")
    if not host:
        return False
    if any(host == d or host.endswith("." + d) for d in NEVER_DOMAINS):
        return True
    return any(word in host for word in NEVER_HOST_WORDS)


def never_name(text: str) -> bool:
    """A name that is, or names, CPAC or the ACU: on letter boundaries, so "vacuum" and "acupuncture" are not the ACU."""
    text = text or ""
    low = text.lower()
    if any(words in low for words in NEVER_NAME_WORDS):
        return True
    return any(re.search(r"(?<![A-Za-z])" + re.escape(n) + r"(?![A-Za-z])", text, re.IGNORECASE) for n in names.ALWAYS)


def _host_of_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    return (urlsplit(url).hostname or "").lower()


def never_contact(*, email: str = "", names: tuple = (), urls: tuple = ()) -> Optional[str]:
    """The reason this prospect is never contacted, or None. Checked at the scout, the drafter, the send and the hand add."""
    email = keys.normalize_email(email or "")
    if "@" in email and never_host(email.rsplit("@", 1)[1]):
        return f"{NEVER_MESSAGE}: the address is at {email.rsplit('@', 1)[1]}."
    for name in names:
        if name and never_name(str(name)):
            return f"{NEVER_MESSAGE}: {str(name).strip()[:80]!r} names them."
    for url in urls:
        host = _host_of_url(str(url or ""))
        if host and never_host(host):
            return f"{NEVER_MESSAGE}: a source is on {host}."
    return None


def _field(row, key: str):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def never_for_row(row) -> Optional[str]:
    """For an outreach row or the facts a draft is made from."""
    return never_contact(email=_field(row, "email") or "", names=(_field(row, "event_name"), _field(row, "organizer")),
                         urls=(_field(row, "website"),))


def never_for_event(ev) -> Optional[str]:
    """For a scout find (a vetted candidate dict or a scout_events row): name, organizer, address, site and every source."""
    sources = _field(ev, "sources") or []
    if isinstance(sources, str):
        try:
            sources = json.loads(sources or "[]")
        except ValueError:
            sources = []
    return never_contact(email=_field(ev, "organizer_email") or "", names=(_field(ev, "name"), _field(ev, "organizer")),
                         urls=(_field(ev, "website"), _field(ev, "email_source_url"), *sources))


# ---------------------------------------------------------------------- do not contact
def blocked(conn: sqlite3.Connection, email: str) -> bool:
    return db.one(conn, "SELECT 1 FROM do_not_contact WHERE email=?", (keys.normalize_email(email),)) is not None


def block(conn: sqlite3.Connection, email: str, *, source: str = "manual", reason: str = "") -> int:
    """Put an address on the list and close every open row for it. Returns the rows closed."""
    email = keys.normalize_email(email)
    if not email:
        return 0
    now = db.utcnow()
    conn.execute("INSERT OR IGNORE INTO do_not_contact (email, source, reason, added_at) VALUES (?,?,?,?)",
                 (email, source, reason or None, now))
    marks = ",".join("?" for _ in OPEN_STATUSES)
    cur = conn.execute(f"UPDATE outreach SET status='opted_out', notes=?, updated_at=? WHERE email=? AND status IN ({marks})",
                       ("On the do-not-contact list.", now, email, *OPEN_STATUSES))
    return cur.rowcount or 0


# ---------------------------------------------------------------------- the parts every email carries
def unsubscribe_url(token: str, cfg: Optional[config.Config] = None) -> str:
    cfg = cfg or config.get_config()
    return f"https://{cfg.brand_domain}/unsubscribe?t={token}"


def footer_lines(token: str, cfg: Optional[config.Config] = None) -> list[str]:
    cfg = cfg or config.get_config()
    return [f"{cfg.brand_name}, a brand of {cfg.legal_name}", cfg.brand_postal_address.strip(), cfg.brand_domain, "",
            f"To stop getting email from {cfg.brand_name}, open {unsubscribe_url(token, cfg)}",
            "You can also reply STOP."]


def list_headers(token: str, cfg: Optional[config.Config] = None) -> dict[str, str]:
    cfg = cfg or config.get_config()
    return {"List-Unsubscribe": f"<mailto:{cfg.brand_from_email}?subject=unsubscribe>, <{unsubscribe_url(token, cfg)}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


@dataclass
class Built:
    subject: str
    plain: str
    html: str
    headers: dict[str, str]


def build(row, cfg: Optional[config.Config] = None) -> Built:
    """The exact message: Chris's words, then the footer; the headers that let a mail client opt out in one click."""
    cfg = cfg or config.get_config()
    token = row["token"]
    body = (row["body"] or "").rstrip()
    foot = footer_lines(token, cfg)
    plain = body + "\n\n" + "\n".join(foot) + "\n"
    url = unsubscribe_url(token, cfg)
    esc = htmllib.escape
    foot_html = "<br>".join(esc(line) for line in foot[:3] if line) + "<br><br>" + \
        f"To stop getting email from {esc(cfg.brand_name)}, <a href=\"{esc(url)}\">unsubscribe here</a>.<br>You can also reply STOP."
    page = ("<div style=\"font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;white-space:pre-wrap\">" + esc(body) + "</div>"
            "<div style=\"font:12px/1.5 -apple-system,Helvetica,Arial,sans-serif;color:#66666b;margin-top:24px\">" + foot_html + "</div>")
    return Built(subject=(row["subject"] or "").strip(), plain=plain, html=page, headers=list_headers(token, cfg))


# ---------------------------------------------------------------------- the checks
def sender_ok(cfg: config.Config) -> bool:
    sender = keys.normalize_email(cfg.brand_from_email)
    domain = (cfg.brand_domain or "").lower().strip()
    if not keys.valid_email(sender) or not domain:
        return False
    host = sender.split("@", 1)[1]
    return host == domain or host.endswith("." + domain)


def text_problems(subject: str, body: str) -> list[Problem]:
    """The words alone: what the drafter must pass and what Chris's edits must keep passing."""
    out: list[Problem] = []
    subject, body = (subject or "").strip(), (body or "").strip()
    if not subject:
        out.append(Problem("subject", "The email needs a subject."))
    elif REPLY_PREFIX.match(subject):
        out.append(Problem("subject", "The subject may not look like a reply or a forward."))
    else:
        rep = copy_rules.check(subject)
        if not rep.ok:
            out.append(Problem("subject", f"Subject: {rep.blocks[0].message}."))
    if not body:
        out.append(Problem("body", "The email needs a message."))
    else:
        rep = copy_rules.check(body)
        if not rep.ok:
            out.append(Problem("body", f"Message: {rep.blocks[0].message}."))
        m = CLAIMS.search(body + "\n" + subject)
        if m:
            out.append(Problem("claims", f"Message claims past work or clients ({m.group(0)!r}); there are none to claim."))
    return out


def problems(conn: sqlite3.Connection, row, *, subject: Optional[str] = None, body: Optional[str] = None,
             now: Optional[datetime] = None, cfg: Optional[config.Config] = None) -> list[Problem]:
    """Every reason this row may not be approved or sent. Empty means it may go."""
    cfg = cfg or config.get_config()
    now = now or datetime.now(timezone.utc)
    out: list[Problem] = []
    never = never_for_row(row)
    if never:
        out.append(Problem("never", never))
    if not sender_ok(cfg):
        out.append(Problem("sender", f"Set BRAND_FROM_EMAIL on the Keys page to an address on {cfg.brand_domain or 'BRAND_DOMAIN'}."))
    if not cfg.brand_postal_address.strip():
        out.append(Problem("address", "Set BRAND_POSTAL_ADDRESS on the Keys page: every outreach email prints it, and none sends without it."))
    out += text_problems(row["subject"] if subject is None else subject, row["body"] if body is None else body)
    email = keys.normalize_email(row["email"])
    if not keys.valid_email(email):
        out.append(Problem("contact", f"{email or 'The address'} is not a valid email address."))
    elif blocked(conn, email):
        out.append(Problem("blocked", "This address is on the do-not-contact list."))
    if not keys.TOKEN.match(row["token"] or ""):
        out.append(Problem("token", "This email has no opt-out token."))
    if row["kind"] == "follow_up":
        parent = db.one(conn, "SELECT status, sent_at FROM outreach WHERE id=?", (row["parent_id"],)) if row["parent_id"] else None
        if parent is None or parent["status"] != "sent" or not parent["sent_at"]:
            out.append(Problem("follow_up", "A follow-up goes only after the first note was sent."))
        else:
            due = datetime.fromisoformat(parent["sent_at"]) + timedelta(days=FOLLOW_UP_DAYS)
            if now < due:
                out.append(Problem("follow_up_wait", f"A follow-up may go on {due.date().isoformat()} at the earliest, "
                                                     f"{FOLLOW_UP_DAYS} days after the first note."))
    return out


def follow_up_allowed(conn: sqlite3.Connection, row, *, now: Optional[datetime] = None) -> Optional[str]:
    """None when Chris may start the one follow-up to this sent first note; else the reason."""
    now = now or datetime.now(timezone.utc)
    if row["kind"] != "first" or row["status"] != "sent" or not row["sent_at"]:
        return "Only a first note that was really sent can have a follow-up."
    never = never_for_row(row)
    if never:
        return never
    if db.one(conn, "SELECT 1 FROM outreach WHERE email=? AND event_key=? AND kind='follow_up'", (row["email"], row["event_key"])):
        return "This note already has its one follow-up."
    if blocked(conn, row["email"]):
        return "This address is on the do-not-contact list."
    due = datetime.fromisoformat(row["sent_at"]) + timedelta(days=FOLLOW_UP_DAYS)
    if now < due:
        return f"A follow-up can be drafted from {due.date().isoformat()}, {FOLLOW_UP_DAYS} days after the first note."
    return None
