"""The weekly look at the public site: read-only GETs, one site_checks row per page.

Pages: /, /book/, /availability/, /privacy/ (each must answer 200 with a page
title, a meta description, an h1, alt text on every image, and no noindex
left over from a preview build), /sitemap.xml (must parse as a sitemap with
at least one page) and /robots.txt (must name the sitemap and must not shut
the whole site off). A page that fails gets an errors row, which the
watchdog mails to Chris.

Only GET, only https://BRAND_DOMAIN, nothing is sent. The transport is
injectable (url -> (status code, body text)) so tests never touch the network.
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Callable, Optional

from ..core import config, db, runner

HTML_PATHS = ("/", "/book/", "/availability/", "/privacy/")
PATHS = HTML_PATHS + ("/sitemap.xml", "/robots.txt")
USER_AGENT = "cki-convention-social/0.1 (weekly site check)"
TIMEOUT = 20

Transport = Callable[[str], tuple[int, str]]


def requests_transport(url: str) -> tuple[int, str]:
    import requests
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
    return r.status_code, r.text


def base_url(cfg: Optional[config.Config] = None) -> str:
    cfg = cfg or config.get_config()
    return f"https://{cfg.brand_domain}"


def urls(cfg: Optional[config.Config] = None) -> list[str]:
    base = base_url(cfg)
    return [base + p for p in PATHS]


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def _hidden(a: dict) -> bool:
    return a.get("aria-hidden", "").strip().lower() == "true" or a.get("role", "").strip().lower() in ("presentation", "none")


class PageScan(HTMLParser):
    """Title, meta description, h1s, images, noindex. An image fails with no alt attribute, or with an
    empty alt unless it is decorative (aria-hidden or role presentation, on it or around it)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self._open: list[tuple[str, bool]] = []      # (tag, hidden) for every element still open
        self.description: Optional[str] = None
        self.h1 = 0
        self.images = 0
        self.images_without_alt = 0
        self.noindex = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag not in VOID:
            self._open.append((tag, _hidden(a)))
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = a.get("name", "").strip().lower()
            if name == "description":
                self.description = a.get("content", "").strip()
            elif name == "robots" and "noindex" in a.get("content", "").lower():
                self.noindex = True
        elif tag == "h1":
            self.h1 += 1
        elif tag == "img":
            self.images += 1
            decorative = _hidden(a) or any(h for _, h in self._open)
            if "alt" not in a or (not a["alt"].strip() and not decorative):
                self.images_without_alt += 1

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self._open and self._open[-1][0] == tag:
            self._open.pop()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                del self._open[i:]
                break

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def check_html(status: int, text: str) -> dict:
    scan = PageScan()
    try:
        scan.feed(text or "")
        scan.close()
    except Exception:  # noqa: BLE001  a page the parser chokes on fails every check
        pass
    r = {"title_ok": bool(scan.title.strip()), "description_ok": bool(scan.description),
         "h1_ok": scan.h1 > 0, "alt_ok": scan.images_without_alt == 0, "problems": []}
    if status != 200:
        r["problems"].append(f"answered {status or 'nothing'}")
    if not r["title_ok"]:
        r["problems"].append("no page title")
    if not r["description_ok"]:
        r["problems"].append("no meta description")
    if not r["h1_ok"]:
        r["problems"].append("no h1 heading")
    if not r["alt_ok"]:
        r["problems"].append(f"{scan.images_without_alt} of {scan.images} images have no alt text")
    if scan.noindex:
        r["problems"].append("tells search engines not to list it (noindex)")
    r["ok"] = not r["problems"]
    return r


def check_sitemap(status: int, text: str) -> dict:
    problems = [] if status == 200 else [f"answered {status or 'nothing'}"]
    if status == 200:
        try:
            root = ET.fromstring((text or "").encode("utf-8"))
            if not root.tag.endswith("urlset"):
                problems.append("is not a sitemap (no urlset)")
            elif not [e for e in root.iter() if e.tag.endswith("}loc") and (e.text or "").strip()]:
                problems.append("lists no pages")
        except ET.ParseError as e:
            problems.append(f"is not valid XML ({e})")
    return {"title_ok": None, "description_ok": None, "h1_ok": None, "alt_ok": None, "problems": problems, "ok": not problems}


def check_robots(status: int, text: str) -> dict:
    problems = [] if status == 200 else [f"answered {status or 'nothing'}"]
    if status == 200:
        lines = [ln.split("#", 1)[0].strip().lower() for ln in (text or "").splitlines()]
        if not any(ln.startswith("sitemap:") for ln in lines):
            problems.append("does not name the sitemap")
        if any(ln.replace(" ", "") == "disallow:/" for ln in lines):
            problems.append("blocks the whole site (Disallow: /)")
    return {"title_ok": None, "description_ok": None, "h1_ok": None, "alt_ok": None, "problems": problems, "ok": not problems}


def _flag(value) -> Optional[int]:
    return None if value is None else int(bool(value))


def check_all(cfg: Optional[config.Config] = None, *, transport: Optional[Transport] = None) -> list[dict]:
    """GET every page once and judge it; writes nothing (`ccs site check` retries this while a new
    domain comes up). Each result: path, url, status, ok, problems and the per-check flags."""
    cfg = cfg or config.get_config()
    transport = transport or requests_transport
    results = []
    for path in PATHS:
        url = base_url(cfg) + path
        try:
            status, text = transport(url)
        except Exception as e:  # noqa: BLE001  unreachable is a failure, not a crash
            status, text = 0, ""
            reach = f"could not be reached ({type(e).__name__})"
        else:
            reach = ""
        if path == "/sitemap.xml":
            r = check_sitemap(status, text)
        elif path == "/robots.txt":
            r = check_robots(status, text)
        else:
            r = check_html(status, text)
        if reach:
            r["problems"] = [reach] + [p for p in r["problems"] if not p.startswith("answered")]
            r["ok"] = False
        results.append({"path": path, "url": url, "status": status, **r})
    return results


def run_check(conn: sqlite3.Connection, cfg: Optional[config.Config] = None, *, transport: Optional[Transport] = None,
              run_id: Optional[int] = None, agent: str = "seo") -> dict:
    """GET every page once, store a row each, and an errors row for each page that fails."""
    checked_at = db.utcnow()
    results = check_all(cfg, transport=transport)
    for r in results:
        db.insert(conn, "site_checks", run_id=run_id, checked_at=checked_at, path=r["path"], url=r["url"],
                  status_code=r["status"], ok=int(r["ok"]), title_ok=_flag(r["title_ok"]),
                  description_ok=_flag(r["description_ok"]), h1_ok=_flag(r["h1_ok"]), alt_ok=_flag(r["alt_ok"]),
                  problems=json.dumps(r["problems"]))
        if not r["ok"]:
            runner.record_error(conn, agent, "site_check", f"{r['url']}: {'; '.join(r['problems'])}")
    return {"checked": len(results), "failed": sum(1 for r in results if not r["ok"]), "results": results,
            "checked_at": checked_at}


def latest(conn: sqlite3.Connection) -> list[dict]:
    """The rows of the most recent check, in page order, problems as a list."""
    rows = db.rows(conn, "SELECT * FROM site_checks WHERE checked_at = (SELECT MAX(checked_at) FROM site_checks) ORDER BY id")
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["problems"] = json.loads(r["problems"] or "[]")
        except ValueError:
            d["problems"] = [r["problems"]]
        out.append(d)
    return out
