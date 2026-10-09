"""The dashboard: fail-closed login, clearance, do-not-use, calendar, approve gates."""
from __future__ import annotations

import json
import os

from fastapi.testclient import TestClient

from convention_social.core import auth, config, db
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.drive import scan
from convention_social.drive.api import DriveReader
from convention_social.library import classify
from tests._base import IsolatedCase
from tests.fake_drive import FakeDrive


class Dashboard(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def signed_in(self):
        self.client.cookies.set(COOKIE, make_token("chris"))
        return self.client

    def seed_library(self):
        d = FakeDrive()
        d.folder("fcon", "Katsucon 2025")
        d.image("p1", "a.jpg", "fcon")
        scan.full_inventory(self.conn, DriveReader("t", conn=self.conn, transport=d))
        classify.folder_pass(self.conn)
        self.conn.execute("UPDATE classifications SET method='vision', possible_minor=0, personal_details='[]'")
        return db.one(self.conn, "SELECT id FROM photos")["id"]

    def draft(self, caption="Green room before the keynote. Request a quote for your event.", photo_ids=(), convention_id=None):
        now = db.utcnow()
        return db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps(list(photo_ids)), convention_id=convention_id,
                         targets=json.dumps(["instagram"]), caption=json.dumps({"instagram": caption, "facebook": caption, "pinterest": caption}),
                         created_at=now, updated_at=now)

    def test_no_password_means_503(self):
        os.environ.pop("DASHBOARD_PASSWORD_HASH")
        config.reset()
        self.assertEqual(TestClient(create_app()).get("/login").status_code, 503)

    def test_pages_need_sign_in(self):
        r = self.client.get("/library", follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertEqual(self.client.post("/donotuse/add", data={"kind": "handle", "value": "@x"}).status_code, 401)

    def test_login(self):
        bad = self.client.post("/login", data={"password": "nope"}, follow_redirects=False)
        self.assertIn("bad=1", bad.headers["location"])
        good = self.client.post("/login", data={"password": "correct horse", "next": "//evil.example"}, follow_redirects=False)
        self.assertEqual(good.headers["location"], "/")
        self.assertIn(COOKIE, good.cookies)

    def test_every_page_renders(self):
        c = self.signed_in()
        self.seed_library()
        qid = self.draft()
        for path in ("/", "/library", "/library?show=all", "/library/folder/fcon", "/donotuse", "/calendar", "/drive",
                     "/agents", "/keys", f"/queue/{qid}"):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("<main>", r.text, path)

    def test_folder_clearance_and_photo_block(self):
        c = self.signed_in()
        pid = self.seed_library()
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM drive_folders WHERE drive_id='fcon'")["clearance"], "cleared")
        self.assertIn("usable", c.get("/library/folder/fcon").text)
        c.post(f"/library/photo/{pid}/clearance", data={"state": "blocked"})
        self.assertIn("Chris blocked this photo", c.get("/library/folder/fcon").text)
        self.assertEqual(c.post("/library/folder/fcon/clearance", data={"state": "weird"}).status_code, 400)

    def test_approve_refuses_rule_break_and_ineligible_photo(self):
        c = self.signed_in()
        pid = self.seed_library()
        q1 = self.draft("Coverage from $500 a day.")
        r = c.post(f"/queue/{q1}/approve", follow_redirects=False)
        self.assertIn("msg=blocked", r.headers["location"])
        q2 = self.draft(photo_ids=[pid])
        self.assertIn("msg=ineligible", c.post(f"/queue/{q2}/approve", follow_redirects=False).headers["location"])
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        self.assertIn("msg=approved", c.post(f"/queue/{q2}/approve", follow_redirects=False).headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q2,))["status"], "approved")

    def test_official_claim_needs_the_calendar_flag(self):
        c = self.signed_in()
        c.post("/calendar/save", data={"name": "Big Con", "kind": "fan", "attending": "on"})
        cid = db.one(self.conn, "SELECT id, official FROM conventions")
        self.assertEqual(cid["official"], 0)
        q = self.draft("Proud to be the official photographer here.", convention_id=cid["id"])
        self.assertIn("msg=blocked", c.post(f"/queue/{q}/approve", follow_redirects=False).headers["location"])
        c.post("/calendar/save", data={"id": cid["id"], "name": "Big Con", "kind": "fan", "official": "on"})
        self.assertIn("msg=approved", c.post(f"/queue/{q}/approve", follow_redirects=False).headers["location"])

    def test_do_not_use_pulls_an_approved_post_back(self):
        c = self.signed_in()
        pid = self.seed_library()
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        q = self.draft(photo_ids=[pid])
        c.post(f"/queue/{q}/approve")
        c.post("/donotuse/add", data={"kind": "photo", "value": "https://drive.google.com/file/d/p1/view"})
        self.assertEqual(db.one(self.conn, "SELECT value FROM do_not_use")["value"], "p1")
        row = db.one(self.conn, "SELECT status, last_error FROM content_queue WHERE id=?", (q,))
        self.assertEqual(row["status"], "draft")
        self.assertIn("do-not-use", row["last_error"])

    def test_keys_page_writes_env_and_never_shows_secrets(self):
        c = self.signed_in()
        c.post("/keys", data={"ANTHROPIC_API_KEY": "sk-secret-value", "BRAND_NAME": "New Name",
                              "CREDITS_SHEET_ID": "https://docs.google.com/spreadsheets/d/sheet123/edit"})
        config.reset()
        self.assertEqual(config.getenv("BRAND_NAME"), "New Name")
        self.assertEqual(config.getenv("CREDITS_SHEET_ID"), "sheet123")
        page = c.get("/keys").text
        self.assertNotIn("sk-secret-value", page)
        self.assertIn("New Name", page)
