"""Signing in to Google Drive from the phone (Chris, 2026-10-13): no terminal, no Google console change,
drive.readonly only. The flow is Google's installed-app flow with PKCE; its state and verifier wait in the
settings table between the two taps."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.drive import oauth
from tests._base import IsolatedCase

READONLY = ["https://www.googleapis.com/auth/drive.readonly"]


class FakeCreds:
    def __init__(self, scopes):
        self.scopes = scopes

    def to_json(self):
        return json.dumps({"token": "t", "refresh_token": "r", "scopes": self.scopes, "client_id": "c", "client_secret": "s",
                           "token_uri": oauth.TOKEN_URI})


class FakeFlow:
    made: list = []
    granted = READONLY

    def __init__(self, client_config, scopes, **kw):
        self.client_config, self.scopes, self.kw = client_config, scopes, kw
        self.code_verifier = kw.get("code_verifier")
        self.fetched = None
        FakeFlow.made.append(self)

    def authorization_url(self, **kw):
        self.code_verifier = self.code_verifier or "verifier-123"
        self.auth_kw = kw
        return "https://accounts.google.com/o/oauth2/auth?client_id=c&state=st-1", "st-1"

    def fetch_token(self, **kw):
        self.fetched = kw

    @property
    def credentials(self):
        return FakeCreds(FakeFlow.granted)


class DriveLogin(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "client-id"
        os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = "client-secret"
        config.reset()
        config.get_config().ensure_dirs()
        self.c = TestClient(create_app())
        self.c.cookies.set(COOKIE, make_token("chris"))
        self.conn = db.connect()
        FakeFlow.made = []
        FakeFlow.granted = READONLY
        p = mock.patch("google_auth_oauthlib.flow.Flow.from_client_config", side_effect=lambda cfg, scopes, **kw: FakeFlow(cfg, scopes, **kw))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def start(self):
        return self.c.post("/drive/login", follow_redirects=False)

    def finish(self, address):
        return self.c.post("/drive/login/finish", data={"address": address}, follow_redirects=False)

    def test_sign_in_from_the_phone_round_trip(self):
        page = self.c.get("/drive").text
        self.assertIn('<form method="post" action="/drive/login"', page)
        self.assertNotIn("bin/ccs drive login", page, "no terminal for Chris")
        self.assertEqual(self.c.get("/drive/login", follow_redirects=False).status_code, 405, "a GET starts nothing (2026-10-24 audit)")
        self.assertIsNone(settings.get(self.conn, oauth.PENDING_KEY))
        r = self.start()
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["location"].startswith("https://accounts.google.com/o/oauth2/auth?"), r.headers["location"])
        flow = FakeFlow.made[0]
        self.assertEqual(flow.scopes, READONLY)
        self.assertEqual(flow.kw["redirect_uri"], f"http://127.0.0.1:{oauth.LOGIN_PORT}/")
        self.assertEqual((flow.auth_kw["access_type"], flow.auth_kw["prompt"], flow.auth_kw["include_granted_scopes"]), ("offline", "consent", "false"))
        pending = json.loads(settings.get(self.conn, oauth.PENDING_KEY))
        self.assertEqual((pending["state"], pending["verifier"]), ("st-1", "verifier-123"))
        page = self.c.get("/drive").text
        self.assertIn('action="/drive/login/finish"', page)
        self.assertIn("Paste", page)
        r = self.finish("127.0.0.1:4611/?state=st-1&code=abc")      # as Safari copies it, without http://
        self.assertEqual(r.headers["location"], "/drive?msg=signed_in", r.headers["location"])
        again = FakeFlow.made[1]
        self.assertEqual((again.kw["state"], again.kw["code_verifier"], again.kw["redirect_uri"]),
                         ("st-1", "verifier-123", f"http://127.0.0.1:{oauth.LOGIN_PORT}/"))
        self.assertEqual(again.fetched, {"authorization_response": "http://127.0.0.1:4611/?state=st-1&code=abc"})
        self.assertEqual(json.loads(oauth.token_path().read_text())["scopes"], READONLY)
        self.assertEqual(settings.get(self.conn, oauth.STATE_KEY), "ok")
        self.assertFalse(settings.get(self.conn, oauth.PENDING_KEY))
        self.assertIn("signed in, read only", self.c.get("/drive").text)

    def test_a_foreign_return_address_is_refused(self):
        self.start()
        r = self.finish("https://evil.example/?state=st-1&code=abc")
        self.assertIn("not+the+sign-in+return+page", r.headers["location"])
        self.assertFalse(oauth.token_path().exists())
        self.assertIsNone(FakeFlow.made[-1].fetched)
        self.assertEqual(self.finish("http://127.0.0.1:4611/?state=st-1&code=abc").headers["location"], "/drive?msg=signed_in",
                         "the sign-in still waits after a bad paste")

    def test_other_scopes_are_refused(self):
        FakeFlow.granted = ["https://www.googleapis.com/auth/drive"]
        self.start()
        r = self.finish("http://127.0.0.1:4611/?state=st-1&code=abc")
        self.assertIn("drive.readonly", r.headers["location"])
        self.assertFalse(oauth.token_path().exists())
        self.assertNotEqual(settings.get(self.conn, oauth.STATE_KEY), "ok")

    def test_a_stale_or_missing_sign_in_is_refused(self):
        r = self.finish("http://127.0.0.1:4611/?state=st-1&code=abc")
        self.assertIn("no+sign-in+is+waiting", r.headers["location"])
        self.start()
        old = (datetime.now(timezone.utc) - timedelta(minutes=oauth.PENDING_MINUTES + 1)).isoformat()
        settings.set(self.conn, oauth.PENDING_KEY, json.dumps({"state": "st-1", "verifier": "verifier-123", "at": old}))
        r = self.finish("http://127.0.0.1:4611/?state=st-1&code=abc")
        self.assertIn("no+sign-in+is+waiting", r.headers["location"])
        self.assertFalse(oauth.token_path().exists())

    def test_without_a_client_the_page_says_what_is_missing(self):
        os.environ.pop("GOOGLE_OAUTH_CLIENT_ID")
        config.reset()
        r = self.start()
        self.assertEqual(r.status_code, 303)
        self.assertIn("GOOGLE_OAUTH_CLIENT_ID", r.headers["location"])
        self.assertEqual(FakeFlow.made, [])

    def test_the_cli_login_uses_the_same_two_steps(self):
        """bin/ccs drive login still works on the Mini, through the same start and finish."""
        out = []
        oauth.login(self.conn, prompt=lambda q: "http://127.0.0.1:4611/?state=st-1&code=abc", out=out.append)
        self.assertTrue(any("accounts.google.com" in line for line in out))
        self.assertEqual(FakeFlow.made[-1].fetched, {"authorization_response": "http://127.0.0.1:4611/?state=st-1&code=abc"})
        self.assertEqual(settings.get(self.conn, oauth.STATE_KEY), "ok")
