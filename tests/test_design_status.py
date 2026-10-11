"""The design samples ("mock ups") on Chris's approved photos: made by themselves when the approved
photos change, and the Design card always says what happened. Chris, 2026-10-11: "Where are the mock
ups with the approved images"."""
from __future__ import annotations

import contextlib
import io
import json
import os
from datetime import datetime, timedelta
from unittest import mock

from fastapi.testclient import TestClient

from convention_social import cli
from convention_social.core import auth, config, db
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import design_samples
from tests._base import IsolatedCase

ROOMS = ("stage_panel", "backstage", "portrait", "vendor_hall", "dinner_reception", "crowd")


class Case(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        now = db.utcnow()
        for fid, clearance in (("fa", "cleared"), ("fb", "not_cleared")):
            db.insert(self.conn, "drive_folders", drive_id=fid, name=fid, clearance=clearance, first_seen_at=now, last_seen_at=now)
        self.n = 0

    def photo(self, folder="fa", sorted_=True, clearance="inherit", shot=None):
        self.n += 1
        now = db.utcnow()
        pid = db.insert(self.conn, "photos", drive_id=f"d{self.n}", name=f"{self.n}.jpg", folder_id=folder, clearance=clearance,
                        thumbnail_link="https://lh3.example/t", width=3000, height=2000, first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama" if sorted_ else "folder", subject="event",
                  is_convention=1, event_kind="business", quality=4, possible_minor=0 if sorted_ else None, personal_details="[]",
                  sharp=1, light=4, moment=4, shot_type=shot or ROOMS[self.n % len(ROOMS)], classified_at=now)
        return pid


class Auto(Case):
    def test_too_few_says_how_many_are_ready_and_how_many_wait_for_the_sorter(self):
        self.photo()
        self.photo(sorted_=False)
        self.photo(folder="fb", sorted_=False, clearance="cleared")      # approved one by one
        self.photo(folder="fb", sorted_=False)                           # not approved: not counted
        self.photo(sorted_=False, clearance="blocked")                   # Don't use: not counted
        self.assertEqual(design_samples.readiness(self.conn), {"ready": 1, "waiting": 2})
        with mock.patch.object(design_samples, "start_in_background") as start:
            line = design_samples.auto(self.conn)
        self.assertEqual(start.call_count, 0)
        self.assertIn("only 1 approved photo(s) are ready for designs", line)
        self.assertIn("2 more approved are waiting for the sorter", line)

    def test_new_samples_start_by_themselves_when_the_approved_photos_change(self):
        for _ in range(4):
            self.photo()
        with mock.patch.object(design_samples, "start_in_background") as start:
            self.assertIn("started", design_samples.auto(self.conn))
            self.assertIn("being made", design_samples.auto(self.conn), "never two at once")
            design_samples.write_status("done", "made on 4 of your approved photos", folder="design-x")
            self.assertIn("up to date", design_samples.auto(self.conn))
            self.assertEqual(start.call_count, 1)
            self.photo()                                                   # one more approved photo
            self.assertIn("started", design_samples.auto(self.conn))
        self.assertEqual(start.call_count, 2)

    def test_a_run_that_died_is_not_left_saying_running(self):
        design_samples.write_status("running", "x")
        path = config.get_config().data_root / "renders" / design_samples.STATUS_FILE
        st = json.loads(path.read_text())
        st["at"] = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
        path.write_text(json.dumps(st))
        self.assertEqual(design_samples.read_status()["state"], "failed")


class Command(Case):
    def run_design(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["design", "--no-reels"])
        return code, out.getvalue()

    def test_too_few_is_said_on_the_card_and_on_the_agents_page(self):
        self.photo()
        with mock.patch("convention_social.drive.oauth.access_token", return_value="tok"):
            code, _ = self.run_design()
        self.assertEqual(code, 2)
        st = design_samples.read_status()
        self.assertEqual(st["state"], "failed")
        self.assertIn("only 1 approved photo(s) are ready", st["message"])
        err = db.one(self.conn, "SELECT agent, message FROM errors")
        self.assertEqual(err["agent"], "designer")
        self.assertIn("Design samples not made", err["message"])

    def test_drive_signed_out_is_said_too(self):
        from convention_social.drive import oauth
        with mock.patch.object(oauth, "access_token", side_effect=oauth.DriveAuthError("no sign-in yet")):
            self.run_design()
        self.assertIn("Google Drive is signed out", design_samples.read_status()["message"])

    def test_a_good_run_says_ready_on_how_many_photos(self):
        for _ in range(4):
            self.photo()

        def make(conn, fetch, reels=True):
            out = config.get_config().data_root / "renders" / "design-20261011-2000"
            out.mkdir(parents=True)
            (out / "about.json").write_text(json.dumps({"photos": ["a", "b", "c", "d"], "failed": []}))
            (out / "index.html").write_text("<p>x</p>")
            return out
        with mock.patch("convention_social.drive.oauth.access_token", return_value="tok"), \
             mock.patch.object(design_samples, "make", make):
            code, _ = self.run_design()
        self.assertEqual(code, 0)
        self.assertEqual(design_samples.read_status()["message"], "made on 4 of your approved photos")


class Card(Case):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_card_says_ready_failed_or_being_made_and_the_counts(self):
        self.photo()
        self.photo(sorted_=False)
        page = self.client.get("/library?view=design").text
        self.assertIn("1 ready for designs, 1 still being sorted", page)
        self.assertIn("made again by themselves", page)
        design_samples.write_status("failed", "only 1 approved photo(s) are ready for designs")
        self.assertIn("Not made: only 1 approved photo(s) are ready for designs.", self.client.get("/library?view=design").text)
        design_samples.write_status("done", "made on 6 of your approved photos", folder="design-x")
        self.assertIn("Ready: made on 6 of your approved photos", self.client.get("/library?view=design").text)
