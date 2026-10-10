"""Pasting the sign-in return page: the phone's Safari copies it without "http://" (2026-10-10, the
first real sign-in failed on exactly that); only the Mini's own loopback page is ever accepted."""
from __future__ import annotations

from unittest import mock

from convention_social.core import db, settings
from convention_social.drive import oauth
from tests._base import IsolatedCase


class FakeFlow:
    def __init__(self):
        self.fetched = None
        self.credentials = object()

    def authorization_url(self, **kw):
        return "https://accounts.google.com/o/oauth2/auth?x=1", "state"

    def fetch_token(self, authorization_response):
        self.fetched = authorization_response


class PasteBack(IsolatedCase):
    def login(self, pasted):
        flow = FakeFlow()
        conn = db.connect()
        with mock.patch.object(oauth, "make_flow", return_value=flow), \
             mock.patch.object(oauth, "save_credentials") as saved:
            oauth.login(conn, prompt=lambda _q: pasted, out=lambda *_a: None)
        return flow, saved, conn

    def test_the_address_safari_copies_is_accepted(self):
        pasted = "127.0.0.1:4611/?state=s&iss=https://accounts.google.com&code=4/abc&scope=https://www.googleapis.com/auth/drive.readonly"
        flow, saved, conn = self.login(pasted)
        self.assertEqual(flow.fetched, "http://" + pasted)
        saved.assert_called_once_with(flow.credentials)
        self.assertEqual(settings.get(conn, oauth.STATE_KEY), "ok")

    def test_the_full_address_and_stray_quotes_still_work(self):
        flow, _, _ = self.login('  "http://localhost:4611/?state=s&code=4/abc"  ')
        self.assertEqual(flow.fetched, "http://localhost:4611/?state=s&code=4/abc")

    def test_any_other_address_is_refused(self):
        for pasted in ("example.org/?code=4/abc", "https://evil.example/?code=4/abc", "", "127.0.0.1.evil.example/?code=1"):
            with self.subTest(pasted=pasted), self.assertRaises(oauth.DriveAuthError):
                self.login(pasted)
