"""Google Search Console, read only: what people searched to find eventcaliber.com, for the morning brief.

Chris, 2026-10-31, asked for SEO tools without a $129 a month subscription ("I'm not paying anyone $129 a month!"),
and chose "Search Console in the digest": Google's own numbers for the site, every week, free. The weekly SEO agent
reads the last 28 days (clicks, how often the site was shown, its average place, the top searches and pages) against
the 28 days before, and the chief of staff puts it in the next morning's brief.

Its own Google sign-in, separate from Drive's: one permission, webmasters.readonly, its own token file
(DATA_ROOT/cache/google_search_console_token.json, mode 600) and its own settings. The Drive sign-in stays
drive.readonly only and untouched (the photo library law, CLAUDE.md); a token here with any other scope is refused,
exactly as Drive's is. The same OAuth client (GOOGLE_OAUTH_CLIENT_ID) and the same phone-friendly paste-back as the
Drive sign-in (drive/oauth.py), on the Drive page. The Google Cloud project needs the Search Console API enabled and
the webmasters.readonly scope added (docs/SETUP.md 8a).

Search Console's numbers lag about three days, so the window ends three days ago. Searches can name events or people;
this is private mail to Chris and never public copy.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import quote, urlparse

import requests

from ..core import config, db, settings, state_io
from ..drive import oauth as google        # the client, the loopback address and the paste-back, shared with Drive's sign-in

SCOPES = ("https://www.googleapis.com/auth/webmasters.readonly",)
API = "https://www.googleapis.com/webmasters/v3"
STATE_KEY = "search_console.auth_state"         # ok | expired | missing
STATE_DETAIL_KEY = "search_console.auth_detail"
PENDING_KEY = "search_console.login_pending"
LAST_KEY = "search_console.last"                 # JSON: the last read, for the brief
WINDOW_DAYS = 28
LAG_DAYS = 3
TOP = 5
TIMEOUT = 30

# (method, url, json body or None, headers) -> (status, parsed json or None)
Transport = Callable[[str, str, Optional[dict], dict], tuple[int, Optional[dict]]]


class SearchConsoleError(RuntimeError):
    """No usable sign-in, or Google refused. The message is written for Chris."""


def token_path():
    return config.get_config().data_root / "cache" / "google_search_console_token.json"


def set_state(conn: Optional[sqlite3.Connection], state: str, detail: str = "") -> None:
    if conn is None:
        return
    settings.set(conn, STATE_KEY, state)
    settings.set(conn, STATE_DETAIL_KEY, f"{db.utcnow()} {detail}".strip())


def save_credentials(creds) -> None:
    data = json.loads(creds.to_json())
    granted = set(data.get("scopes") or [])
    if granted and granted != set(SCOPES):
        raise SearchConsoleError(f"Google granted {sorted(granted)}; the Search Console sign-in only accepts {list(SCOPES)}")
    state_io.save_json(token_path(), data, indent=2, private=True)


def load_credentials():
    data = state_io.load_json(token_path(), None)
    if not data:
        return None
    from google.oauth2.credentials import Credentials
    if set(data.get("scopes") or SCOPES) != set(SCOPES):
        raise SearchConsoleError("the stored Search Console token carries other scopes; sign in again")
    return Credentials.from_authorized_user_info(data, scopes=list(SCOPES))


def access_token(conn: Optional[sqlite3.Connection] = None, *, refresh_fn: Optional[Callable] = None) -> str:
    creds = load_credentials()
    if creds is None:
        set_state(conn, "missing", "not signed in yet")
        raise SearchConsoleError("Search Console is not signed in yet: Drive page, Sign in to Search Console.")
    if not creds.valid:
        try:
            if refresh_fn is not None:
                refresh_fn(creds)
            else:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
        except Exception as e:  # noqa: BLE001 — RefreshError (invalid_grant), the network
            name = type(e).__name__
            dead = (name == "RefreshError" and not getattr(e, "retryable", False)) or "invalid_grant" in str(e)
            set_state(conn, "expired" if dead else "ok", f"{name}: {str(e)[:200]}")
            if dead:
                raise SearchConsoleError("the Search Console sign-in has expired: Drive page, Sign in to Search Console.") from e
            raise
        save_credentials(creds)
    set_state(conn, "ok")
    return creds.token


def _flow(**kw):
    cfg = google.client_config()
    if cfg is None:
        raise SearchConsoleError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set (docs/SETUP.md)")
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(cfg, scopes=list(SCOPES), redirect_uri=f"http://127.0.0.1:{google.LOGIN_PORT}/", **kw)


def start_login(conn: sqlite3.Connection) -> str:
    """The Google link; the flow's state and PKCE verifier wait in settings for the paste-back."""
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false")
    settings.set(conn, PENDING_KEY, json.dumps({"state": state, "verifier": flow.code_verifier, "at": db.utcnow()}))
    return url


def pending_login(conn: sqlite3.Connection) -> Optional[dict]:
    try:
        data = json.loads(settings.get(conn, PENDING_KEY) or "null")
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get("state") or not data.get("verifier"):
        return None
    try:
        started = datetime.fromisoformat(data["at"])
    except (KeyError, TypeError, ValueError):
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - started > timedelta(minutes=google.PENDING_MINUTES):
        return None
    return data


def finish_login(conn: sqlite3.Connection, pasted: str) -> None:
    pending = pending_login(conn)
    if pending is None:
        raise SearchConsoleError("no Search Console sign-in is waiting (it lasts 15 minutes): press Sign in to Search Console again")
    redirected = google.return_address(pasted)
    if urlparse(redirected).hostname not in ("127.0.0.1", "localhost"):
        raise SearchConsoleError("that address is not the sign-in return page")
    flow = _flow(state=pending["state"], code_verifier=pending["verifier"])
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # the loopback redirect is plain http by design
    flow.fetch_token(authorization_response=redirected)
    save_credentials(flow.credentials)
    settings.set(conn, PENDING_KEY, "")
    set_state(conn, "ok", "signed in from the dashboard")


# ------------------------------------------------------------------ reading

def _requests_transport(method: str, url: str, body: Optional[dict], headers: dict) -> tuple[int, Optional[dict]]:
    r = requests.request(method, url, json=body, headers=headers, timeout=TIMEOUT)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, None


def _call(transport: Transport, token: str, method: str, path: str, body: Optional[dict] = None) -> dict:
    status, data = transport(method, API + path, body, {"Authorization": "Bearer " + token})
    if status != 200 or not isinstance(data, dict):
        message = ((data or {}).get("error") or {}).get("message", "") if isinstance(data, dict) else ""
        raise SearchConsoleError(f"Search Console answered {status}{': ' + message[:160] if message else ''}")
    return data


def property_for(sites: list[dict], domain: str) -> Optional[str]:
    """The site's property: the Domain property (sc-domain:) first, then the https URL prefix, then any that holds it."""
    urls = [s.get("siteUrl", "") for s in sites if s.get("permissionLevel") != "siteUnverifiedUser"]
    for want in (f"sc-domain:{domain}", f"https://{domain}/", f"https://www.{domain}/"):
        if want in urls:
            return want
    return next((u for u in urls if domain in u), None)


def window(today: date, days: int = WINDOW_DAYS) -> tuple[date, date]:
    end = today - timedelta(days=LAG_DAYS)
    return end - timedelta(days=days - 1), end


def _totals(transport, token, prop, start: date, end: date) -> dict:
    data = _call(transport, token, "POST", f"/sites/{quote(prop, safe='')}/searchAnalytics/query",
                 {"startDate": start.isoformat(), "endDate": end.isoformat()})
    row = (data.get("rows") or [{}])[0]
    return {"clicks": int(row.get("clicks") or 0), "impressions": int(row.get("impressions") or 0),
            "position": round(float(row.get("position") or 0), 1)}


def _top(transport, token, prop, start: date, end: date, dimension: str) -> list[dict]:
    data = _call(transport, token, "POST", f"/sites/{quote(prop, safe='')}/searchAnalytics/query",
                 {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": [dimension], "rowLimit": TOP})
    return [{"key": (r.get("keys") or [""])[0], "clicks": int(r.get("clicks") or 0), "impressions": int(r.get("impressions") or 0),
             "position": round(float(r.get("position") or 0), 1)} for r in data.get("rows") or []]


def read(conn: sqlite3.Connection, cfg=None, *, transport: Optional[Transport] = None, today: Optional[date] = None,
         token: Optional[str] = None) -> dict:
    """The last 28 days against the 28 before, stored for the brief. Raises SearchConsoleError when it cannot."""
    cfg = cfg or config.get_config()
    transport = transport or _requests_transport
    token = token or access_token(conn)
    domain = (cfg.brand_domain or "").strip().lower()
    prop = property_for(_call(transport, token, "GET", "/sites").get("siteEntry") or [], domain)
    if prop is None:
        raise SearchConsoleError(f"this Google account holds no Search Console property for {domain}")
    today = today or datetime.now(timezone.utc).date()
    start, end = window(today)
    before = (start - timedelta(days=WINDOW_DAYS), start - timedelta(days=1))
    out = {"at": db.utcnow(), "property": prop, "start": start.isoformat(), "end": end.isoformat(),
           "now": _totals(transport, token, prop, start, end), "before": _totals(transport, token, prop, *before),
           "queries": _top(transport, token, prop, start, end, "query"), "pages": _top(transport, token, prop, start, end, "page")}
    settings.set(conn, LAST_KEY, json.dumps(out))
    return out


def line(r: dict) -> str:
    """One plain sentence for the brief and the SEO agent's summary."""
    now, was = r["now"], r["before"]
    start, end = date.fromisoformat(r["start"]), date.fromisoformat(r["end"])
    head = (f"Google search, {start:%b} {start.day} to {end:%b} {end.day}: {now['clicks']} click{'s' if now['clicks'] != 1 else ''} "
            f"from {now['impressions']} showing{'s' if now['impressions'] != 1 else ''}")
    if now["impressions"]:
        head += f", average place {now['position']:g}"
    head += f" (the 28 days before: {was['clicks']} from {was['impressions']})."
    if r["queries"]:
        head += " Top searches: " + "; ".join(f"{q['key']} ({q['impressions']})" for q in r["queries"][:3]) + "."
    return head


def fresh_line(conn: sqlite3.Connection, now: Optional[datetime] = None, hours: int = 30) -> str:
    """The line when the last read is from the past `hours` (the weekly run lands in the next morning's brief), else ''."""
    try:
        r = json.loads(settings.get(conn, LAST_KEY) or "null")
        at = datetime.fromisoformat(r["at"])
    except (TypeError, ValueError, KeyError):
        return ""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if (now or datetime.now(timezone.utc)) - at > timedelta(hours=hours):
        return ""
    return line(r)
