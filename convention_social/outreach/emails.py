"""The organizer's address and the event's dates, read off the event's own website: a person first.

Chris, 2026-10-30: "I haven't received one email to send. Not one outreach email has been sent." The scout had
found eight events and kept an email for none: research keeps an address only when a search citation quotes
it, which almost never happens, and the outreach agent drafts only for an event with an address. "It should
search for these emails, it does on my other suite." This is that step, written for events: the site
is already known and backed by a source, so there is nothing to prove about whose site it is; the pages an
organizer keeps a contact on are read, and an address is kept only when it is on the event's own domain (or
its organizer's: annualmeeting.aha.org prints @aha.org addresses).

Chris, 2026-11-01, when the drafts went to shared inboxes (hello@, info@, register@): "Scrape other avenues to find their
actual emails. Go look at my [other suite's] repo and use how it scrapes and searches for the actual emails when they
find a info@ or contact@" (its name is kept out of this repo). Its way, written for events:
  * the addresses a page hides are read too: Cloudflare's data-cfemail and email-protection links decoded, mailto links
    unquoted ("mailto:%20jane@" is jane@), "%40" read as @; junk dropped (a site builder's, a script library's, no-reply,
    webmaster, privacy, careers, an image name)
  * a named person's address on the event's or organizer's own domain outranks any shared inbox (is_role: info@,
    contact@, hello@, register@, registration@, events@, press@ ..., an event's own inbox like gacinfo@, a mailbox with
    the organization's name like mylegion@); a shared inbox is kept only when no person's address turns up after the
    usual pages (PROBE_PATHS) and the site's own contact, staff, team, people, leadership, press and about pages linked
    from the pages read (same host only, MAX_LINKS an event, in LINK_ORDER)
  * several people named: the first whose words on the page (the name and title before the address) say events,
    meetings, conference, sponsorship, exhibits, partnerships or marketing; otherwise the first one found (pages in the
    order read, a page top to bottom)
  * a second look: an event the earlier walk left with a shared inbox, or with no address, is walked once more
    (person_looked_at); a waiting draft then follows the person's address (agents/outreach.follow_events). An event
    with a note approved or sent is never looked at again.
And its dates (Chris chose "Look up their dates"): an event with an address and no dates has them read off its own page,
once, by one small Claude read (outreach/dates.py), kept only when the page says them word for word.

Precision over recall: a missed address costs a day; a wrong one mails a stranger. One request a second, a
budget of fetches a run, every event walked once, a server that refuses an automated read is left alone and said so.
The do-not-contact list and the never-contact rule are checked on what is found, as everywhere.
"""
from __future__ import annotations

import html as htmllib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional
from urllib.parse import unquote, urljoin, urlsplit

import requests

from ..core import db
from ..core.mail import in_test_process
from . import compliance, dates, keys

# where an organizer prints a contact: the event's own page when the site is the organizer's (terrapinn.com/conference/x),
# then the home page and the usual pages
PROBE_PATHS = ("", "/contact", "/contact-us", "/press", "/media", "/about", "/about-us", "/sponsors", "/exhibit", "/faq")
# the site's own pages worth reading, by the last part of their address, in the order they are read
LINK_ORDER = ("contact", "staff", "team", "people", "leadership", "press", "about")
LINK_WORDS = re.compile("|".join(LINK_ORDER))
MAX_LINKS = 8                     # pages found linked on the pages read, an event
REQUEST_SPACING_S = 1.0
FETCH_TIMEOUT = 8
MAX_FETCHES_PER_RUN = 120         # several events' pages, a few minutes of reading a day at most; the rest wait for tomorrow
LOOKUPS_PER_RUN = 10
DATE_READS_PER_RUN = 10           # small Claude reads a run (well under a cent each), under the AI cap
USER_AGENT = "Mozilla/5.0 (compatible; EventCaliber-Scout/1.0; +https://eventcaliber.com)"
EMAIL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+\-]{0,63}@[A-Za-z0-9][A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}")

# Shared inboxes, by the word their mailbox starts with (info2027@, events.team@ and pressoffice@ too). When a shared
# inbox is all there is, the ones a photographer would write to come first, in this order.
PREFERRED = ("press", "media", "pr", "communications", "events", "event", "meetings", "meeting", "conference", "conferences",
             "sponsorship", "sponsorships", "sponsors", "sponsor", "exhibit", "exhibits", "exhibitor", "exhibitors",
             "marketing", "partnerships", "partners", "info", "contact", "contacts", "hello", "inquiries", "inquiry",
             "enquiries", "enquiry", "office")
ROLE_LOCAL = PREFERRED + ("register", "registration", "registrations", "registrar", "information", "hi", "news", "comms",
                          "sales", "admin", "administrator", "membership", "members", "member", "service", "services",
                          "cs", "customerservice", "support", "help", "helpdesk", "team", "staff", "general", "mail",
                          "email", "reception", "frontdesk", "programs", "program", "education", "speakers", "housing",
                          "advertising", "operations", "ops", "attendees", "attendee", "expo", "exhibition", "partnership",
                          # an association's departments (read 2026-11-01: advocacy@americascreditunions.org is a desk)
                          "advocacy", "policy", "government", "govt", "governmentaffairs", "legislative", "grassroots", "affairs",
                          "research", "foundation", "development", "compliance", "publications", "newsroom", "awards", "chapters",
                          "volunteer", "volunteers", "alumni", "community", "learning", "training", "certification", "webinars",
                          "outreach", "feedback", "questions", "requests", "booking", "bookings", "travel", "hotel", "abstracts",
                          "submissions", "speaker", "agenda", "onsite", "national", "headquarters", "hq", "web", "digital", "social")
ROLE_TAILS = ("team", "desk", "office", "info", "staff", "dept", "us", "group")       # eventsteam@, infodesk@, contactus@
# an event's own inbox ends in one of these after a short name: gacinfo@, amwaevents@, nabregistration@
ROLE_ENDINGS = ("info", "contact", "contacts", "events", "registration", "register", "sponsorship", "sponsors", "exhibits",
                "exhibitors", "meetings", "inquiries", "helpdesk", "team", "office")
# mailboxes that are never the one to write to about an event's photography: dropped, never kept
BAD_LOCAL = ("noreply", "no-reply", "donotreply", "do-not-reply", "privacy", "abuse", "postmaster", "webmaster",
             "mailer-daemon", "unsubscribe")
WRONG_DESKS = ("careers", "jobs", "hr", "recruiting", "billing", "accounting", "accounts", "legal", "donations", "donate",
               "giving", "accessibility", "security")
BAD_PARTS = ("sentry", "wixpress", "example.", "yourdomain", "domain.com", "email.com", "godaddy", "squarespace", "wordpress",
             "schema.org", "w3.org", "cloudflare", "google.", "gstatic", "jquery", "bootstrap", "fontawesome", "sitelock", "weebly")
VENDOR_DOMAINS = ("wixpress.com", "wix.com", "squarespace.com", "godaddy.com", "sentry.io", "example.com", "domain.com",
                  "email.com", "wordpress.com", "webflow.io", "duda.co", "weebly.com", "cvent.com", "swoogo.com",
                  "eventbrite.com", "hubspot.com", "mailchimp.com", "salesforce.com")
ASSET_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
NOT_PAGES = ASSET_SUFFIX + (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".ics", ".xml", ".mp4")
# the words that mark the person who handles events, when a page names several
EVENTS_WORDS = re.compile(r"\b(?:events?|meetings?|conferences?|sponsor(?:s|ship|ships)?|exhibit(?:s|ion|ions|or|ors)?|"
                          r"partnerships?|marketing)\b", re.I)
CONTEXT_BEFORE = 100             # the words before an address (a name and a title, in a staff list) that say whose it is
REFUSED = (401, 403, 406, 429)
BUDGET_SPENT = "the run's fetch budget is spent; next run"
REFUSED_NOTE = "the site refused an automated read"

CF_TAG = re.compile(r"<[^>]*\bdata-cfemail\s*=\s*[\"']([0-9a-fA-F]+)[\"'][^>]*>", re.I)
CF_HREF = re.compile(r"<a\b[^>]*href\s*=\s*[\"'][^\"']*/cdn-cgi/l/email-protection#([0-9a-fA-F]+)[\"'][^>]*>", re.I)
MAILTO = re.compile(r"<a\b[^>]*href\s*=\s*[\"']\s*mailto:([^\"'?>\s]+)[^>]*>", re.I)
HIDDEN = re.compile(r"<(script|style|noscript|template)\b.*?</\1\s*>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
HREF = re.compile(r"href\s*=\s*[\"']([^\"'#]+)", re.I)


@dataclass
class Found:
    email: str = ""
    page: str = ""
    note: str = ""            # why there is no email, in plain words, when there is none
    person: bool = False      # a named person's address, not a shared inbox
    text: str = ""            # the words of the first page of the event's site that answered, for its dates
    text_url: str = ""


@dataclass
class Candidate:
    email: str
    page: str
    person: bool
    events_word: bool = False


@dataclass
class Walk:
    """What one event's walk has collected so far."""
    found: list = field(default_factory=list)          # every Candidate that may be written to, in the order found
    refused: list = field(default_factory=list)        # (address, why) found but not to be written to


def host_of(url: str) -> str:
    host = (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def registered(host: str) -> str:
    """aha.org for annualmeeting.aha.org; the last two labels (good enough for .com/.org/.net, which is what events use)."""
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def own_host(host: str, site: str) -> bool:
    return bool(host and site) and (host == site or host.endswith("." + site) or registered(host) == registered(site))


def own_address(email: str, site: str) -> bool:
    return own_host(email.rsplit("@", 1)[-1], site)


def _head(email: str) -> str:
    """The mailbox's first word: 'info' for info2027@ and info.dc@."""
    return re.split(r"[^a-z]", (email or "").lower().partition("@")[0])[0]


def _org_words(domain: str) -> set[str]:
    """The organization's own name in its domain: {'legion'} for legion.org, {'amwadoc', 'amwa'} for amwa-doc.org."""
    label = registered(domain.lower()).split(".")[0]
    return {w for w in {re.sub(r"[^a-z]", "", label), *re.split(r"[^a-z]+", label)} if len(w) >= 4}


def is_role(email: str) -> bool:
    """A shared inbox, not a named person's address: a desk's word (info@, contact@, hello@, register@, registration@,
    events@, press@, eventsteam@ ...), an event's own inbox (gacinfo@), or a mailbox carrying the organization's own name
    (mylegion@legion.org)."""
    local, _, domain = (email or "").lower().partition("@")
    head = _head(email)
    if head in ROLE_LOCAL or any(head == r + t for r in ROLE_LOCAL for t in ROLE_TAILS):
        return True
    if any(head.endswith(e) and 0 < len(head) - len(e) <= 6 for e in ROLE_ENDINGS):
        return True
    letters = re.sub(r"[^a-z]", "", local)
    return any(w in letters for w in _org_words(domain))


def role_rank(email: str) -> int:
    head = _head(email)
    for i, word in enumerate(PREFERRED):
        if head == word or any(head == word + t for t in ROLE_TAILS):
            return i
    return len(PREFERRED)


def _cf_decode(hex_str: str) -> str:
    """Cloudflare's email protection: the first byte is the key every other byte is XORed with."""
    try:
        data = bytes.fromhex(hex_str)
    except ValueError:
        return ""
    return "".join(chr(b ^ data[0]) for b in data[1:]) if data else ""


def page_text(page: str) -> str:
    """The words a reader sees, every address the page hides written back in its place: Cloudflare's data-cfemail and
    email-protection links decoded, a mailto link's address unquoted, %40 read as @. Scripts and styles left out."""
    def put(address: str) -> str:
        return f" {address} " if address else " "
    s = CF_TAG.sub(lambda m: m.group(0) + put(_cf_decode(m.group(1))), page or "")
    s = CF_HREF.sub(lambda m: m.group(0) + put(_cf_decode(m.group(1))), s)
    s = MAILTO.sub(lambda m: m.group(0) + put(unquote(htmllib.unescape(m.group(1))).strip()), s)
    s = TAG.sub(" ", HIDDEN.sub(" ", s))
    return " ".join(htmllib.unescape(s).replace("%40", "@").split())


def _clean(raw: str) -> str:
    """One address as found, tidied, or '' for junk."""
    e = raw.strip().strip(".,;:").lower()
    # an address glued to a zip code or an encoded space in front of it: "20004info@x.org", "20office@x.org"
    e = re.sub(r"^(?:\d{5}|20)(?=(?:" + "|".join(ROLE_LOCAL) + r")@)", "", e)
    if not EMAIL_RE.fullmatch(e):
        return ""
    local = e.partition("@")[0]
    if (any(b in e for b in BAD_PARTS) or any(local.startswith(b) for b in BAD_LOCAL) or _head(e) in WRONG_DESKS
            or e.endswith(ASSET_SUFFIX) or len(local) > 40):
        return ""
    return e


JS_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def markup_text(page: str) -> str:
    """The markup with what escapes an address undone: HTML entities, %-escapes and a script's \\u003e, so
    "\\u003ehello@x.org" in a page's data reads as ">hello@x.org", never as the address "u003ehello@x.org"."""
    return unquote(htmllib.unescape(JS_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), page or "")))


def extract_emails(page: str) -> list[str]:
    """Every address on the page, hidden ones too, in the order a reader meets them (then any only in the markup)."""
    out: list[str] = []
    for raw in EMAIL_RE.findall(page_text(page)) + EMAIL_RE.findall(markup_text(page)):
        e = _clean(raw)
        if e and e not in out:
            out.append(e)
    return out


def around(text: str, email: str) -> str:
    """The words just before an address on the page, back to the address before it: in a staff list the name and the
    title come first ("Jane Doe, Director of Meetings, jane@..."), and the words after an address are the next person's."""
    low = text.lower()
    i = low.find(email)
    if i < 0:
        return ""
    window = max(0, i - CONTEXT_BEFORE)
    return text[max([window] + [m.end() for m in EMAIL_RE.finditer(low, window, i)]):i]


def addresses(body: str, site: str) -> list[str]:
    """Published addresses on the event's own domain, junk and other companies' left out, in page order."""
    out = []
    for addr in extract_emails(body):
        domain = addr.rsplit("@", 1)[-1]
        if any(domain == v or domain.endswith("." + v) for v in VENDOR_DOMAINS):
            continue
        if own_address(addr, site) and keys.valid_email(addr):
            out.append(addr)
    return out


def candidates(body: str, site: str, url: str) -> list[Candidate]:
    text = page_text(body)
    return [Candidate(email=a, page=url, person=not is_role(a), events_word=bool(EVENTS_WORDS.search(around(text, a))))
            for a in addresses(body, site)]


def choose(found: list) -> Optional[Candidate]:
    """A person's address before any shared inbox. Of several people, the first whose words on the page say events,
    meetings, conference, sponsorship, exhibits, partnerships or marketing; otherwise the first found. Of shared
    inboxes only, the one a photographer would write to first (PREFERRED), then the first found."""
    people = [c for c in found if c.person]
    if people:
        return next((c for c in people if c.events_word), people[0])
    if not found:
        return None
    return min(found, key=lambda c: (role_rank(c.email), found.index(c)))


def _page_key(url: str) -> str:
    return host_of(url) + urlsplit(url if "://" in url else f"https://{url}").path.rstrip("/").lower()


def contact_links(body: str, base: str, site: str) -> list[str]:
    """The site's own contact, staff, team, people, leadership, press and about pages linked from this page (same host),
    by the last part of their address (/about-us/leadership, not /about-us/financials), in LINK_ORDER."""
    found: list[tuple[int, str]] = []
    hosts = {site, host_of(base)}
    for m in HREF.finditer(body or ""):
        href = htmllib.unescape(m.group(1)).strip()
        if href.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        parts = urlsplit(urljoin(base, href))
        last = ([seg for seg in parts.path.lower().split("/") if seg] or [""])[-1]
        if parts.scheme not in ("http", "https") or host_of(parts.geturl()) not in hosts or not LINK_WORDS.search(last):
            continue
        if last.endswith(NOT_PAGES):
            continue
        url = parts._replace(fragment="").geturl()
        if url not in [u for _, u in found]:
            found.append((next(i for i, w in enumerate(LINK_ORDER) if w in last), url))
    return [u for _, u in sorted(found, key=lambda pair: pair[0])]


def probes(website: str, site: str) -> list[str]:
    """The pages to read, in order: the event's own page first when the website has a path, then the usual ones."""
    path = urlsplit(website if "://" in website else f"https://{website}").path.rstrip("/")
    urls = [f"https://{site}{p}" for p in PROBE_PATHS]
    return [f"https://{site}{path}", *urls] if path else urls


def fetch(url: str) -> tuple[Optional[str], str, bool]:
    """(body, final url, refused): https then http (expired certificates are common and the redirect still lands), each
    request followed by the polite pause. A test process never reaches the network: the tests hand their own fetcher."""
    if in_test_process():
        return None, url, False
    for candidate in (url, url.replace("https://", "http://", 1)):
        try:
            resp = requests.get(candidate, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        except requests.RequestException:
            time.sleep(REQUEST_SPACING_S)
            continue
        time.sleep(REQUEST_SPACING_S)
        final = getattr(resp, "url", candidate) or candidate
        if resp.status_code in REFUSED:
            return None, final, True
        if resp.status_code == 200:
            return resp.text[:250_000], final, False
        return None, final, False
    return None, url, False


def discover(website: str, *, budget: list[int], fetch: Callable = fetch,
             refuse: Callable[[str], Optional[str]] = lambda email: None) -> Found:
    """Walk the event site's pages for a person's address, a shared inbox only when no person turns up. `budget` is a
    one-element counter shared by a run; `refuse(email)` says why an address may not be written to (do not contact).

    The walk ends early only on a person whose surrounding words say events: there is no better. A server that refuses
    an automated read ends it too, and is left alone; what was found before stands. A page that redirects to another
    site is not the event's and is skipped (the AHA meeting's /press landed on an affiliate's site; its address was
    that affiliate's). A walk the budget cuts short says so, and the event is walked from the start on the next run."""
    site = host_of(website)
    if not site:
        return Found(note="no website to read")
    queue = probes(website, site)
    seen = {_page_key(u) for u in queue}         # every page queued
    landed: set[str] = set()                     # every page read, where the redirects landed
    links = 0
    walk = Walk()
    answered = sent_elsewhere = text = text_url = ""
    stopped = ""
    i = 0
    while i < len(queue):
        url = queue[i]
        i += 1
        if _page_key(url) in landed:             # /about and /about-us often land on one page: read it once
            continue
        if budget[0] <= 0:
            return Found(note=BUDGET_SPENT)
        budget[0] -= 1
        body, final_url, refused = fetch(url)
        if refused:
            stopped = f"{REFUSED_NOTE} ({final_url}); open it by hand"
            break
        if body is None:
            continue
        landed.add(_page_key(final_url))
        if not own_host(host_of(final_url), site):
            sent_elsewhere = final_url
            continue
        answered = answered or final_url
        if not text:
            text, text_url = page_text(body), final_url
        for c in candidates(body, site, final_url):
            if any(c.email == x.email for x in walk.found) or any(c.email == a for a, _ in walk.refused):
                continue
            why = refuse(c.email)
            if why:
                walk.refused.append((c.email, why))
            else:
                walk.found.append(c)
        if any(c.person and c.events_word for c in walk.found):
            break
        for link in contact_links(body, final_url, site):
            if links >= MAX_LINKS:
                break
            if _page_key(link) not in seen | landed:
                seen.add(_page_key(link))
                queue.append(link)
                links += 1
    best = choose(walk.found)
    if best:
        return Found(email=best.email, page=best.page, person=best.person, text=text, text_url=text_url)
    if stopped:
        return Found(note=stopped, text=text, text_url=text_url)
    if walk.refused:
        return Found(note="the only addresses found are not to be written to: "
                          + "; ".join(f"{a} ({why})" for a, why in walk.refused[:3]), text=text, text_url=text_url)
    if not answered:
        if sent_elsewhere:
            return Found(note=f"the website sends readers to another site ({sent_elsewhere}); open it by hand")
        return Found(note="the website did not answer")
    return Found(note="no public address on the pages read; the site may use a form", text=text, text_url=text_url)


def event_page(website: str, *, budget: list[int], fetch: Callable = fetch) -> tuple[str, str]:
    """(words, url) of the event's own page, for its dates; ('', '') when it does not answer or is another site's."""
    site = host_of(website)
    budget[0] -= 1
    body, final_url, refused = fetch(probes(website, site)[0])
    if refused or body is None or not own_host(host_of(final_url), site):
        return "", ""
    return page_text(body), final_url


def wants_walk(ev) -> bool:
    """Walked once with this walk: an event with no address yet, or only a shared inbox; never one whose server refused
    an earlier read, nor one with a note approved or sent (that address is Chris's choice)."""
    email = keys.normalize_email(ev["organizer_email"] or "")
    return (ev["person_looked_at"] is None and not ev["gone"] and not (ev["email_note"] or "").startswith(REFUSED_NOTE)
            and (not email or is_role(email)))


def _refusal(conn: sqlite3.Connection, ev) -> Callable[[str], Optional[str]]:
    def refuse(email: str) -> Optional[str]:
        never = compliance.never_contact(email=email, names=(ev["name"], ev["organizer"] or ""), urls=(ev["website"],))
        if never:
            return never
        return "on the do-not-contact list" if compliance.blocked(conn, email) else None
    return refuse


def _keep_address(conn: sqlite3.Connection, ev, had: str, found: Found, stats: dict) -> str:
    """Record the walk on the event. A first find is kept, a person's or a shared inbox; a second look (the event held a
    shared inbox) changes the address only for a person's. Returns the address the event holds now."""
    now = db.utcnow()
    stats["looked"] += 1
    if found.note.startswith(REFUSED_NOTE):
        stats["refused"] += 1
    if not had:
        if found.email:
            stats["found"] += 1
            stats["people"] += found.person
            conn.execute("UPDATE scout_events SET organizer_email=?, email_source_url=?, email_checked_at=COALESCE(email_checked_at, ?), "
                         "person_looked_at=?, email_note=NULL, updated_at=? WHERE id=?",
                         (found.email, found.page, now, now, now, ev["id"]))
            return found.email
        conn.execute("UPDATE scout_events SET email_checked_at=COALESCE(email_checked_at, ?), person_looked_at=?, email_note=?, "
                     "updated_at=? WHERE id=?", (now, now, found.note, now, ev["id"]))
        return ""
    stats["second_looks"] += 1
    if found.email and found.person and found.email != had:
        stats["people"] += 1
        conn.execute("UPDATE scout_events SET organizer_email=?, email_source_url=?, person_looked_at=?, email_note=?, updated_at=? WHERE id=?",
                     (found.email, found.page, now, f"a person's address, found on a second look, instead of the shared inbox {had}",
                      now, ev["id"]))
        return found.email
    why = found.note if found.note.startswith(REFUSED_NOTE) else "a second look found no person's address; the shared inbox stays"
    conn.execute("UPDATE scout_events SET person_looked_at=?, email_note=?, updated_at=? WHERE id=?", (now, why, now, ev["id"]))
    return had


def look_up(conn: sqlite3.Connection, *, today: date, earliest: date, reader: Optional[dates.Reader] = None,
            date_reads: int = DATE_READS_PER_RUN, limit: int = LOOKUPS_PER_RUN, budget: Optional[list[int]] = None,
            fetch: Callable = fetch) -> dict:
    """The scout's events that can still get a note (dated `earliest` or later, or not dated yet): a person's address for
    those with none or only a shared inbox, then the dates of those with an address and none (with `reader`; no reader,
    no read). Events with a waiting draft first, then the soonest."""
    stats = {"events": 0, "looked": 0, "found": 0, "people": 0, "second_looks": 0, "refused": 0, "dates_read": 0, "dated": 0}
    budget = budget if budget is not None else [MAX_FETCHES_PER_RUN]
    rows = db.rows(conn, """
        SELECT e.*, (SELECT COUNT(*) FROM outreach o WHERE o.scout_event_id = e.id AND o.status = 'draft') AS waiting,
               (SELECT COUNT(*) FROM outreach o WHERE o.scout_event_id = e.id
                 AND o.status IN ('approved', 'sent', 'would_send', 'failed')) AS gone
        FROM scout_events e
        WHERE e.status IN ('new', 'added') AND COALESCE(e.website, '') != '' AND (e.start_date IS NULL OR e.start_date >= ?)
        ORDER BY waiting DESC, COALESCE(e.start_date, '9999'), e.id""", (earliest.isoformat(),))
    for ev in rows:
        walk = wants_walk(ev)
        undated = not ev["start_date"] and ev["dates_checked_at"] is None and not ev["gone"]
        if not walk and not (undated and ev["organizer_email"] and reader is not None):
            continue
        if stats["events"] >= limit or budget[0] <= 0:
            break
        email, text, text_url = keys.normalize_email(ev["organizer_email"] or ""), "", ""
        if walk:
            found = discover(ev["website"], budget=budget, fetch=fetch, refuse=_refusal(conn, ev))
            if found.note == BUDGET_SPENT:
                break                      # not looked at: the row stays unmarked and is first in line next run
            email = _keep_address(conn, ev, email, found, stats)
            text, text_url = found.text, found.text_url
        stats["events"] += 1
        if not (undated and email and reader is not None) or stats["dates_read"] >= date_reads:
            continue
        if not text:
            if budget[0] <= 0:
                break
            text, text_url = event_page(ev["website"], budget=budget, fetch=fetch)
        now = db.utcnow()
        if not text:
            conn.execute("UPDATE scout_events SET dates_checked_at=?, dates_note=?, updated_at=? WHERE id=?",
                         (now, "the event's page did not answer, so its dates could not be read", now, ev["id"]))
            continue
        found_dates = reader.read(text, text_url, today)
        if found_dates.later:              # the cap or the API: not read, no more reads this run, read on a later run
            conn.execute("UPDATE scout_events SET dates_note=?, updated_at=? WHERE id=?", (found_dates.note, now, ev["id"]))
            reader = None
            continue
        stats["dates_read"] += 1
        stats["dated"] += bool(found_dates.start)
        conn.execute("UPDATE scout_events SET start_date=COALESCE(?, start_date), end_date=COALESCE(?, end_date), "
                     "dates_checked_at=?, dates_note=?, updated_at=? WHERE id=?",
                     (found_dates.start or None, found_dates.end or None, now, found_dates.note, now, ev["id"]))
    return stats
