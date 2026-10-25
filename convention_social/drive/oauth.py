"""Signing in to Google Drive as Chris: installed-app OAuth, `drive.readonly` only.

Why OAuth and not a service account: a service account cannot see a personal
My Drive unless every folder is shared with it, and the library is a flat set
of about 150 job folders. Signing in as Chris lets the scanner read the whole
Drive, read only.

The client comes from this suite's own Google Cloud project (a "Desktop app"
OAuth client): GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET. The
refresh token lands in DATA_ROOT/cache/google_token.json (mode 600), never in
the repo.

The token-death trap: a consent screen left in "Testing" issues refresh tokens
that expire after 7 days. The project's consent screen must be set to
"In production" (docs/SETUP.md). Even then a token can die (revoked, unused
for months), so every refresh failure sets settings `drive.auth_state` to
"expired", and the watchdog tells Chris on his phone and by email.

Sign-in on a machine with no screen: `bin/ccs drive login` prints the Google
link. Chris opens it on any device and approves. Google then sends the
browser to http://127.0.0.1:<LOGIN_PORT>/ ; if the browser runs on the Mini
(or the port is forwarded with ssh -L) the CLI catches it, otherwise the page
fails to load and Chris pastes that page's address into the terminal. Either
way the code is exchanged in the same process that made the link (PKCE).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional
from urllib.parse import urlparse

from ..core import config, db, secrets, settings, state_io

SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
LOGIN_PORT = 4611
STATE_KEY = "drive.auth_state"        # ok | expired | missing
STATE_DETAIL_KEY = "drive.auth_detail"
PENDING_KEY = "drive.login_pending"   # JSON {state, verifier, at}: a sign-in started, waiting for the return page
PENDING_MINUTES = 15


class DriveAuthError(RuntimeError):
    """No usable sign-in. The message is written for Chris."""


def token_path():
    return config.get_config().data_root / "cache" / "google_token.json"


def client_config() -> Optional[dict]:
    cid = config.getenv("GOOGLE_OAUTH_CLIENT_ID")
    secret = secrets.get_secret("GOOGLE_OAUTH_CLIENT_SECRET")
    if not (cid and secret):
        return None
    return {"installed": {"client_id": cid, "client_secret": secret, "auth_uri": AUTH_URI, "token_uri": TOKEN_URI,
                          "redirect_uris": [f"http://127.0.0.1:{LOGIN_PORT}/"]}}


def set_state(conn: Optional[sqlite3.Connection], state: str, detail: str = "") -> None:
    if conn is None:
        return
    settings.set(conn, STATE_KEY, state)
    settings.set(conn, STATE_DETAIL_KEY, f"{db.utcnow()} {detail}".strip())


def save_credentials(creds) -> None:
    data = json.loads(creds.to_json())
    granted = set(data.get("scopes") or [])
    if granted and granted != set(SCOPES):
        raise DriveAuthError(f"Google granted {sorted(granted)}; this suite only accepts {list(SCOPES)}")
    state_io.save_json(token_path(), data, indent=2, private=True)


def load_credentials():
    """The stored credentials, or None. Refuses a token carrying any scope but drive.readonly."""
    data = state_io.load_json(token_path(), None)
    if not data:
        return None
    from google.oauth2.credentials import Credentials
    if set(data.get("scopes") or SCOPES) != set(SCOPES):
        raise DriveAuthError("the stored Google token carries scopes other than drive.readonly; sign in again")
    return Credentials.from_authorized_user_info(data, scopes=list(SCOPES))


def access_token(conn: Optional[sqlite3.Connection] = None, *, refresh_fn: Optional[Callable] = None) -> str:
    """A fresh access token. Any failure records the state (for the watchdog) and raises DriveAuthError."""
    creds = load_credentials()
    if creds is None:
        set_state(conn, "missing", "no Google sign-in yet")
        raise DriveAuthError("Google Drive is not signed in yet. Run `bin/ccs drive login`.")
    if not creds.valid:
        try:
            if refresh_fn is not None:
                refresh_fn(creds)
            else:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
        except Exception as e:  # noqa: BLE001 — RefreshError (invalid_grant), network
            name = type(e).__name__
            # google-auth tries Google's token endpoint again itself on a 500, 503, 504, 408 or 429, and marks the
            # RefreshError it raises when that still fails `retryable`: Google's fault, not a dead sign-in (open since the
            # 10-16 audit: such a day would have read "sign in again")
            dead = (name == "RefreshError" and not getattr(e, "retryable", False)) or "invalid_grant" in str(e)
            set_state(conn, "expired" if dead else "ok", f"{name}: {str(e)[:200]}")
            if dead:
                raise DriveAuthError("Google Drive sign-in has expired. Run `bin/ccs drive login` again.") from e
            raise
        save_credentials(creds)
    set_state(conn, "ok")
    return creds.token


def make_flow():
    cfg = client_config()
    if cfg is None:
        raise DriveAuthError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set (docs/SETUP.md)")
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(cfg, scopes=list(SCOPES), redirect_uri=f"http://127.0.0.1:{LOGIN_PORT}/")


def _catch_redirect(timeout: float) -> Optional[str]:
    """Wait on 127.0.0.1:LOGIN_PORT for Google's redirect; return the full URL or None."""
    got: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            got["url"] = f"http://127.0.0.1:{LOGIN_PORT}{self.path}"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab.")

        def log_message(self, *a):  # quiet
            pass

    try:
        server = HTTPServer(("127.0.0.1", LOGIN_PORT), Handler)
    except OSError:
        return None
    server.timeout = timeout
    server.handle_request()
    server.server_close()
    return got.get("url")


def return_address(pasted: str) -> str:
    """The pasted return page as a full address. Safari on the phone copies it without "http://"
    (2026-10-10), so a bare 127.0.0.1 / localhost address gets it back; anything else is left as is
    and still has to pass the loopback check."""
    text = (pasted or "").strip().strip('"\'<>').strip()
    if text.startswith(("127.0.0.1", "localhost")):
        text = "http://" + text
    return text


def start_login(conn: Optional[sqlite3.Connection]) -> tuple[str, dict]:
    """The Google link, and the flow's state and PKCE verifier the finish needs. With `conn` they wait in
    settings for PENDING_MINUTES, so the dashboard can finish in another request (Chris, 2026-10-13: the
    sign-in from the phone, no terminal)."""
    flow = make_flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="false")
    pending = {"state": state, "verifier": flow.code_verifier, "at": db.utcnow()}
    if conn is not None:
        settings.set(conn, PENDING_KEY, json.dumps(pending))
    return url, pending


def pending_login(conn: Optional[sqlite3.Connection]) -> Optional[dict]:
    """The sign-in waiting for its return page, or None (none, or older than PENDING_MINUTES)."""
    if conn is None:
        return None
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
    if datetime.now(timezone.utc) - started > timedelta(minutes=PENDING_MINUTES):
        return None
    return data


def finish_login(conn: Optional[sqlite3.Connection], pasted: str, pending: Optional[dict] = None,
                 detail: str = "signed in") -> None:
    """The pasted return page completes the sign-in start_login began. Refuses a foreign host, a sign-in that
    is not waiting any more, and (save_credentials) any scope but drive.readonly."""
    pending = pending or pending_login(conn)
    if pending is None:
        raise DriveAuthError("no sign-in is waiting (it lasts 15 minutes): press Sign in to Google Drive again")
    redirected = return_address(pasted)
    if urlparse(redirected).hostname not in ("127.0.0.1", "localhost"):
        raise DriveAuthError("that address is not the sign-in return page")
    cfg = client_config()
    if cfg is None:
        raise DriveAuthError("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set (docs/SETUP.md)")
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(cfg, scopes=list(SCOPES), redirect_uri=f"http://127.0.0.1:{LOGIN_PORT}/",
                                   state=pending["state"], code_verifier=pending["verifier"])
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # the loopback redirect is plain http by design
    flow.fetch_token(authorization_response=redirected)
    save_credentials(flow.credentials)
    if conn is not None:
        settings.set(conn, PENDING_KEY, "")
    set_state(conn, "ok", detail)


def login(conn: Optional[sqlite3.Connection] = None, *, prompt=input, out=print, wait_seconds: float = 0) -> None:
    """Interactive sign-in (bin/ccs drive login). Prints the link; takes the redirect from the local
    listener (when wait_seconds > 0) or from a pasted address. The same two steps as the dashboard's."""
    url, pending = start_login(conn)
    out("Open this link, sign in as the Google account that holds the photos, and approve read-only Drive access:\n")
    out(url + "\n")
    redirected = None
    if wait_seconds > 0:
        holder: dict = {}
        t = threading.Thread(target=lambda: holder.setdefault("url", _catch_redirect(wait_seconds)), daemon=True)
        t.start()
        t.join(wait_seconds + 1)
        redirected = holder.get("url")
    if not redirected:
        redirected = prompt("After approving, the browser lands on a page that may not load. "
                            "Paste that page's full address here: ")
    finish_login(conn, redirected, pending=pending)
    out("Google Drive is signed in, read only.")
