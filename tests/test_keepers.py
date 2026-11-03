"""Pick the keepers (Chris, 2026-11-03: "this is the most time consuming shitty way of doing things"; he keeps about 1 photo
in 7). To review a page of 12 at a time, the strongest first: the ticked photos are his Use, the rest of the page Never use,
in one tap; Undo takes the whole last page back."""
from __future__ import annotations

import os
import re

from fastapi.testclient import TestClient

from convention_social.core import auth, config, db, settings
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import copies
from tests._base import IsolatedCase
from tests._fakes import add_post


class Keepers(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="f", name="Gala", first_seen_at=self.now, last_seen_at=self.now)

    def photo(self, pid, *, quality=3, md5=None):
        db.insert(self.conn, "photos", id=pid, drive_id=f"d{pid}", name=f"{pid}.jpg", folder_id="f", md5=md5,
                  thumbnail_link="https://drive.example/t=s220", first_seen_at=self.now, last_seen_at=self.now)
        db.insert(self.conn, "classifications", photo_id=pid, method="vision", subject="event", shot_type="candid",
                  quality=quality, personal_details="[]", space="exterior", residential=0, empty_room=0, classified_at=self.now)
        self.conn.commit()

    def clearance(self, pid):
        return db.one(self.conn, "SELECT clearance FROM photos WHERE id=?", (pid,))["clearance"]

    def shown(self, page):
        return [int(x) for x in re.findall(r'<input type="hidden" name="shown" value="(\d+)">', page)]

    def test_a_page_of_twelve_the_strongest_first_and_to_review_leads_to_it(self):
        for pid in range(1, 16):
            self.photo(pid, quality=1 + pid % 5)
        page = self.client.get("/library/keepers").text
        self.assertEqual(len(self.shown(page)), dash.KEEPERS_PAGE)
        self.assertEqual(self.shown(page)[:3], [4, 9, 14], "the strongest first, as To review")
        self.assertIn("15 left · Events", page)
        self.assertIn('<button class="small" type="submit" disabled>Undo page</button>', page, "nothing to undo yet")
        self.assertIn('href="/library/keepers?subject=event"><strong>Pick the keepers</strong>',
                      self.client.get("/library?view=review").text)
        self.assertEqual({self.clearance(p) for p in range(1, 16)}, {"inherit"}, "opening the page decides nothing")

    def test_the_ticked_are_use_the_rest_never_use_on_every_copy(self):
        for pid in range(1, 6):
            self.photo(pid, quality=5)
        self.photo(6, quality=1, md5="same")
        self.photo(7, quality=1, md5="same")              # one picture twice: one tile, both copies decided
        copies.link(self.conn)                            # the scanner's pass makes them one picture
        waiting = add_post(self.conn, [3], status="draft")
        self.client.post("/library/photo/5/clearance", data={"state": "cleared"})     # decided elsewhere meanwhile
        r = self.client.post("/library/keepers", data={"subject": "event", "shown": ["1", "2", "3", "5", "6"], "keep": ["2"]},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("1+Use%2C+3+Never+use.+1+were+no+longer+waiting", r.headers["location"])
        self.assertEqual([self.clearance(p) for p in (1, 2, 3, 5, 6, 7)],
                         ["blocked", "cleared", "blocked", "cleared", "blocked", "blocked"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (waiting,))["status"], "rejected",
                         "a Never use sets aside the waiting post holding it, as everywhere")
        self.assertTrue(settings.get(self.conn, "site.photos_changed_at"), "the site follows")
        self.assertEqual(self.shown(self.client.get("/library/keepers").text), [4], "the next page: what is still waiting")

    def test_undo_takes_the_whole_last_page_back(self):
        for pid in range(1, 5):
            self.photo(pid)
        self.client.post("/library/keepers", data={"subject": "event", "shown": ["1", "2", "3"], "keep": ["1"]})
        self.client.post("/library/photo/3/clearance", data={"state": "cleared"})   # changed since: left as it is
        r = self.client.post("/library/keepers/undo", data={"subject": "event"}, follow_redirects=False)
        self.assertIn("Undone%3A+the+last+page%27s+2+photos", r.headers["location"])
        self.assertEqual([self.clearance(p) for p in (1, 2, 3)], ["inherit", "inherit", "cleared"])
        r = self.client.post("/library/keepers/undo", data={"subject": "event"}, follow_redirects=False)
        self.assertIn("Nothing+to+undo", r.headers["location"], "one page back, not two")

    def test_nothing_left_says_so(self):
        page = self.client.get("/library/keepers").text
        self.assertIn("Nothing left to review in Events.", page)
        self.assertNotIn('id="page"', page)
