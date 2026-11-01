"""Search Console, read only, in the morning brief (Chris, 2026-10-31: "Search Console in the digest").

A sign-in of its own with one permission; the Drive sign-in and its token are never touched (the photo library law);
the weekly read and the line the brief carries; nothing is read in dry run."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import chief, seo
from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.drive import oauth as drive_oauth
from convention_social.seo import search_console as gsc
from tests._base import IsolatedCase
from tests._fakes import make_ctx

READ_ONLY = ["https://www.googleapis.com/auth/webmasters.readonly"]


class FakeCreds:
    def __init__(self, scopes):
        self.scopes = scopes

    def to_json(self):
        return json.dumps({"token": "t", "refresh_token": "r", "scopes": self.scopes, "client_id": "c", "client_secret": "s",
                           "token_uri": drive_oauth.TOKEN_URI})


class FakeFlow:
    made: list = []
    granted = READ_ONLY

    def __init__(self, client_config, scopes, **kw):
        self.scopes, self.kw = scopes, kw
        self.code_verifier = kw.get("code_verifier")
        FakeFlow.made.append(self)

    def authorization_url(self, **kw):
        self.code_verifier = self.code_verifier or "verifier-1"
        return "https://accounts.google.com/o/oauth2/auth?client_id=c&state=st-9", "st-9"

    def fetch_token(self, **kw):
        self.fetched = kw

    @property
    def credentials(self):
        return FakeCreds(FakeFlow.granted)


class Google:
    """The Search Console API, recorded: the sites list, then the four queries."""
    def __init__(self, sites=None):
        self.calls = []
        self.sites = sites if sites is not None else [{"siteUrl": "sc-domain:eventcaliber.com", "permissionLevel": "siteOwner"}]

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        if url.endswith("/sites"):
            return 200, {"siteEntry": self.sites}
        dims = (body or {}).get("dimensions")
        before = body["startDate"] < "2026-10-01"
        if not dims:
            return 200, {"rows": [{"clicks": 2 if before else 12, "impressions": 90 if before else 340, "ctr": 0.03, "position": 24.37}]}
        if dims == ["query"]:
            return 200, {"rows": [{"keys": ["event caliber"], "clicks": 5, "impressions": 40, "position": 1.2},
                                  {"keys": ["convention photographer dc"], "clicks": 1, "impressions": 30, "position": 18.0}]}
        return 200, {"rows": [{"keys": ["https://eventcaliber.com/"], "clicks": 9, "impressions": 200, "position": 12.0}]}


class SignIn(IsolatedCase):
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
        self.addCleanup(self.conn.close)
        FakeFlow.made, FakeFlow.granted = [], READ_ONLY
        p = mock.patch("google_auth_oauthlib.flow.Flow.from_client_config", side_effect=lambda cfg, scopes, **kw: FakeFlow(cfg, scopes, **kw))
        p.start()
        self.addCleanup(p.stop)

    def test_its_own_sign_in_one_read_only_permission_and_drive_untouched(self):
        page = self.c.get("/drive").text
        self.assertIn('<form method="post" action="/search-console/login"', page)
        self.assertIn("not signed in", page)
        r = self.c.post("/search-console/login", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["location"].startswith("https://accounts.google.com/"))
        self.assertEqual(FakeFlow.made[0].scopes, READ_ONLY, "one permission, read only, never Drive's")
        self.assertIn("Paste the address of the page Google sent you to", self.c.get("/drive").text)
        r = self.c.post("/search-console/login/finish", data={"address": "127.0.0.1:4611/?state=st-9&code=abc"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/drive?msg=gsc_signed_in")
        self.assertEqual(json.loads(gsc.token_path().read_text())["scopes"], READ_ONLY)
        self.assertEqual(oct(gsc.token_path().stat().st_mode & 0o777), "0o600")
        self.assertFalse(drive_oauth.token_path().exists(), "the Drive token is never written by this sign-in")
        self.assertNotEqual(gsc.token_path(), drive_oauth.token_path())
        self.assertEqual(settings.get(self.conn, gsc.STATE_KEY), "ok")
        self.assertIsNone(settings.get(self.conn, drive_oauth.STATE_KEY), "nor its state")

    def test_any_other_scope_and_a_foreign_return_page_are_refused(self):
        self.c.post("/search-console/login", follow_redirects=False)
        FakeFlow.granted = READ_ONLY + ["https://www.googleapis.com/auth/drive.readonly"]
        r = self.c.post("/search-console/login/finish", data={"address": "http://127.0.0.1:4611/?state=st-9&code=abc"}, follow_redirects=False)
        self.assertIn("only+accepts", r.headers["location"])
        self.assertFalse(gsc.token_path().exists())
        self.c.post("/search-console/login", follow_redirects=False)
        r = self.c.post("/search-console/login/finish", data={"address": "https://evil.example/?code=abc"}, follow_redirects=False)
        self.assertIn("not+the+sign-in+return+page", r.headers["location"])


class Reading(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["BRAND_DOMAIN"] = "eventcaliber.com"
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def test_the_last_28_days_against_the_28_before_and_one_line(self):
        g = Google()
        r = gsc.read(self.conn, transport=g, today=date(2026, 11, 2), token="tok")
        self.assertEqual((r["property"], r["start"], r["end"]), ("sc-domain:eventcaliber.com", "2026-10-03", "2026-10-30"))
        self.assertEqual(g.calls[0][:2], ("GET", gsc.API + "/sites"))
        self.assertEqual(g.calls[1][1], gsc.API + "/sites/sc-domain%3Aeventcaliber.com/searchAnalytics/query")
        self.assertEqual(g.calls[1][3], {"Authorization": "Bearer tok"})
        self.assertEqual(g.calls[2][2], {"startDate": "2026-09-05", "endDate": "2026-10-02"}, "the 28 days before")
        self.assertEqual(g.calls[3][2]["dimensions"], ["query"])
        self.assertEqual(r["now"], {"clicks": 12, "impressions": 340, "position": 24.4})
        self.assertEqual(gsc.line(r), "Google search, Oct 3 to Oct 30: 12 clicks from 340 showings, average place 24.4 "
                                      "(the 28 days before: 2 from 90). Top searches: event caliber (40); convention photographer dc (30).")
        self.assertEqual(json.loads(settings.get(self.conn, gsc.LAST_KEY))["pages"][0]["key"], "https://eventcaliber.com/")

    def test_the_property_is_found_and_a_missing_one_is_said(self):
        self.assertEqual(gsc.property_for([{"siteUrl": "https://eventcaliber.com/", "permissionLevel": "siteOwner"}], "eventcaliber.com"),
                         "https://eventcaliber.com/")
        self.assertIsNone(gsc.property_for([{"siteUrl": "sc-domain:eventcaliber.com", "permissionLevel": "siteUnverifiedUser"}], "eventcaliber.com"))
        with self.assertRaises(gsc.SearchConsoleError) as cm:
            gsc.read(self.conn, transport=Google(sites=[]), today=date(2026, 11, 2), token="tok")
        self.assertIn("no Search Console property for eventcaliber.com", str(cm.exception))

    def test_the_weekly_run_reads_it_live_says_why_not_otherwise_and_the_brief_carries_it(self):
        line = seo.run(make_ctx(self.conn, agent="seo", dry_run=True))
        self.assertIn("Search Console not read in dry run", line)
        with mock.patch.object(gsc, "access_token", side_effect=gsc.SearchConsoleError("Search Console is not signed in yet")):
            with mock.patch.object(seo.site_check, "run_check", return_value={"checked": 1, "failed": 0}):
                line = seo.run(make_ctx(self.conn, agent="seo", dry_run=False))
        self.assertIn("Search Console not read: Search Console is not signed in yet", line)
        with mock.patch.object(gsc, "access_token", return_value="tok"), \
                mock.patch.object(seo.site_check, "run_check", return_value={"checked": 1, "failed": 0}):
            line = seo.run(make_ctx(self.conn, agent="seo", dry_run=False), console=Google())
        self.assertIn("Google search, ", line)
        now = datetime.now(timezone.utc)
        self.assertTrue(gsc.fresh_line(self.conn, now).startswith("Google search, "))
        self.assertEqual(gsc.fresh_line(self.conn, now + timedelta(hours=31)), "", "only the brief after the weekly read")
        b = chief.gather(make_ctx(self.conn, agent="chief", dry_run=True), now)
        self.assertTrue(any(w.startswith("Google search, ") for w in b["watching"]), b["watching"])
