"""The organizer's email, read off the event's own website.

Chris, 2026-10-30: "I haven't received one email to send. Not one outreach email has been sent." The scout had
found eight events and kept an email for none: research keeps an address only when a search citation quotes
it, which almost never happens, and the outreach agent drafts only for an event with an address. "It should
search for these emails, it does on my other suite." This is that step, written for events: the site
is already known and backed by a source, so there is nothing to prove about whose site it is; the pages an
organizer keeps a contact on are read, and an address is kept only when it is on the event's own domain (or
its organizer's: annualmeeting.aha.org prints @aha.org addresses).

Precision over recall: a missed address costs a day; a wrong one mails a stranger. One request a second, a
budget of fetches a run, every event probed once (scout_events.email_checked_at), a server that refuses an
automated read is left alone and said so. The do-not-contact rule is checked on what is found, as everywhere.
"""
from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests

from ..core import db
from . import compliance, keys

# where an organizer prints a contact: the home page, then the usual pages, press and sponsors first for an event
PROBE_PATHS = ("", "/contact", "/contact-us", "/press", "/media", "/about", "/about-us", "/sponsors", "/exhibit", "/faq")
REQUEST_SPACING_S = 1.0
FETCH_TIMEOUT = 8
MAX_FETCHES_PER_RUN = 40          # ten events' worth of pages a day at most; the rest wait for tomorrow
LOOKUPS_PER_RUN = 10
USER_AGENT = "Mozilla/5.0 (compatible; EventCaliber-Scout/1.0; +https://eventcaliber.com)"
# the addresses an organizer means for the public, in the order a photographer would write to them
PREFERRED = ("press", "media", "pr", "communications", "events", "event", "sponsorship", "sponsors", "sponsor", "exhibit",
             "exhibitors", "marketing", "info", "contact", "hello", "inquiries", "enquiries", "office")
VENDOR_DOMAINS = ("wixpress.com", "wix.com", "squarespace.com", "godaddy.com", "sentry.io", "example.com", "domain.com",
                  "email.com", "wordpress.com", "webflow.io", "duda.co", "weebly.com", "cvent.com", "swoogo.com",
                  "eventbrite.com", "hubspot.com", "mailchimp.com", "salesforce.com")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
REFUSED = (401, 403, 406, 429)


@dataclass
class Found:
    email: str = ""
    page: str = ""
    note: str = ""            # why there is no email, in plain words, when there is none


def host_of(url: str) -> str:
    host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def registered(host: str) -> str:
    """aha.org for annualmeeting.aha.org; the last two labels (good enough for .com/.org/.net, which is what events use)."""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def own_address(email: str, site: str) -> bool:
    domain = email.rsplit("@", 1)[-1]
    return bool(domain and site) and (domain == site or domain.endswith("." + site) or registered(domain) == registered(site))


def addresses(body: str, site: str) -> list[str]:
    """Published addresses on the event's own domain, vendor noise and images dropped, the public-facing ones first."""
    out: list[str] = []
    for raw in EMAIL_RE.findall(body or ""):
        addr = raw.strip().strip(".").lower()
        if addr.rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "gif", "webp", "svg", "js", "css"):
            continue
        domain = addr.rsplit("@", 1)[-1]
        if any(domain == v or domain.endswith("." + v) for v in VENDOR_DOMAINS):
            continue
        if not own_address(addr, site) or not keys.valid_email(addr) or addr in out:
            continue
        out.append(addr)

    def rank(addr: str) -> tuple:
        local = addr.split("@", 1)[0]
        hits = [i for i, p in enumerate(PREFERRED) if local == p or local.startswith(p)]
        return (hits[0] if hits else len(PREFERRED), len(addr))
    return sorted(out, key=rank)


def fetch(url: str) -> tuple[Optional[str], str, bool]:
    """(body, final url, refused): https then http (expired certificates are common and the redirect still lands)."""
    for candidate in (url, url.replace("https://", "http://", 1)):
        try:
            resp = requests.get(candidate, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        except requests.RequestException:
            continue
        final = getattr(resp, "url", candidate) or candidate
        if resp.status_code in REFUSED:
            return None, final, True
        if resp.status_code == 200:
            return resp.text[:250_000], final, False
        return None, final, False
    return None, url, False


def discover(website: str, *, budget: list[int], fetch: Callable = fetch, sleep: Callable = time.sleep) -> Found:
    """Walk the event site's usual pages for a public address. `budget` is a one-element counter shared by a run."""
    site = host_of(website)
    if not site:
        return Found(note="no website to read")
    for path in PROBE_PATHS:
        if budget[0] <= 0:
            return Found(note="the run's fetch budget is spent; next run")
        budget[0] -= 1
        body, final_url, refused = fetch(f"https://{site}{path}")
        sleep(REQUEST_SPACING_S)
        if refused:
            return Found(note=f"the site refused an automated read ({final_url}); open it by hand")
        if body is None:
            if path == "":
                return Found(note="the website did not answer")
            continue
        found = addresses(body, site)
        if found:
            return Found(email=found[0], page=final_url)
    return Found(note="no public address on the pages read; the site may use a form")


def lookup_missing(conn: sqlite3.Connection, *, limit: int = LOOKUPS_PER_RUN, budget: Optional[list[int]] = None,
                   fetch: Callable = fetch, sleep: Callable = time.sleep) -> dict:
    """Read an address for the scout's events that have a website and no email, each once, soonest event first."""
    stats = {"looked": 0, "found": 0, "refused": 0}
    budget = budget if budget is not None else [MAX_FETCHES_PER_RUN]
    rows = db.rows(conn, "SELECT * FROM scout_events WHERE status IN ('new', 'added') AND COALESCE(organizer_email, '') = '' "
                         "AND COALESCE(website, '') != '' AND email_checked_at IS NULL ORDER BY COALESCE(start_date, '9999'), id LIMIT ?",
                   (limit,))
    for ev in rows:
        if budget[0] <= 0:
            break
        found = discover(ev["website"], budget=budget, fetch=fetch, sleep=sleep)
        stats["looked"] += 1
        now = db.utcnow()
        if found.email:
            never = compliance.never_contact(email=found.email, names=(ev["name"], ev["organizer"] or ""), urls=(ev["website"], found.page))
            if never:
                found = Found(note=never)
        if found.email:
            stats["found"] += 1
            conn.execute("UPDATE scout_events SET organizer_email=?, email_source_url=?, email_checked_at=?, email_note=NULL, updated_at=? WHERE id=?",
                         (found.email, found.page, now, now, ev["id"]))
        else:
            if "refused" in found.note:
                stats["refused"] += 1
            conn.execute("UPDATE scout_events SET email_checked_at=?, email_note=?, updated_at=? WHERE id=?", (now, found.note, now, ev["id"]))
    return stats
