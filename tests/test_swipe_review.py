"""The swipe review (Chris, 2026-11-02: "Maybe a swipe left or right to keep or discard of?", then "One photo per card").

Right is his Use; left is Don't use for good ("out of the pool forevwr"); Undo takes back the last swipe only. Nothing is
cleared but by a right swipe. To review leaves out what the do-not-use list covers, and Claude's scores lead it.
Later the same day ("never use and don't use need to just be never use"): left is Never use, and like every Never use
it sets aside a waiting post that holds the photo."""
from __future__ import annotations

import json
import os
import random
import re

from unittest import mock

from fastapi.testclient import TestClient

from convention_social.core import auth, config, db, settings
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import copies, eligibility
from tests._base import IsolatedCase
from tests._fakes import add_post
from tests.test_photos_tab import build_library

JSON = {"Accept": "application/json"}


class Deck(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="f", name="Gala", clearance="not_cleared", first_seen_at=self.now,
                  last_seen_at=self.now)
        db.insert(self.conn, "drive_folders", drive_id="g", name="Expo", clearance="not_cleared", first_seen_at=self.now,
                  last_seen_at=self.now)

    def photo(self, pid, *, method="vision", quality=3, folder="f", subject="event", shot="candid", rejudge=0, md5=None):
        db.insert(self.conn, "photos", id=pid, drive_id=f"d{pid}", name=f"{pid}.jpg", folder_id=folder, md5=md5,
                  thumbnail_link="https://drive.example/t=s220", first_seen_at=self.now, last_seen_at=self.now)
        db.insert(self.conn, "classifications", photo_id=pid, method=method, subject=subject, shot_type=shot, quality=quality,
                  rejudge=rejudge, personal_details="[]", space="exterior", residential=0, empty_room=0, classified_at=self.now)
        self.conn.commit()

    def clearance(self, pid):
        return db.one(self.conn, "SELECT clearance FROM photos WHERE id=?", (pid,))["clearance"]

    def swipe(self, pid, state, subject="event"):
        return self.client.post(f"/library/swipe/{pid}", data={"state": state, "subject": subject}, headers=JSON)

    def deck(self, subject="event"):
        page = self.client.get(f"/library/swipe?subject={subject}").text
        return json.loads(re.search(r'<script type="application/json" id="deck-data">(.*?)</script>', page, re.S).group(1)), page

    # ------------------------------------------------------------------ the swipes
    def test_right_is_his_use(self):
        self.photo(1, quality=5)
        self.photo(2, quality=4)
        self.photo(3, quality=5, md5="same")
        self.photo(4, quality=1, md5="same")          # the same picture twice: one card, both copies decided
        copies.link(self.conn)                         # the scanner's pass after the inventory
        r = self.swipe(1, "cleared")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.clearance(1), "cleared")
        self.assertEqual(eligibility.clearance_of(self.conn, db.one(self.conn, "SELECT * FROM photos WHERE id=1")), "cleared")
        d = r.json()
        self.assertEqual((d["words"], d["left"], d["undo"]), ("Approved.", 2, True))
        self.assertEqual([c["id"] for c in d["next"]], [3, 2])
        self.swipe(3, "cleared")
        self.assertEqual((self.clearance(3), self.clearance(4)), ("cleared", "cleared"), "every copy")
        self.assertEqual(self.clearance(2), "inherit", "nothing else is touched")

    def test_left_is_never_use(self):
        """It was test_left_is_dont_use_for_good. 2026-11-02: Don't use is Never use; the photo is on the Never use list
        (his way back is Put back there), and a waiting draft that holds it is set aside at once."""
        self.photo(1, quality=5)
        self.photo(2, quality=4)
        waiting = add_post(self.conn, [1], ("instagram",), status="draft")
        other = add_post(self.conn, [], ("instagram",), status="draft")
        with mock.patch("convention_social.dashboard.app.start_agent") as start:
            d = self.swipe(1, "blocked").json()
        self.assertEqual(self.clearance(1), "blocked")
        self.assertEqual((d["words"], d["left"], [c["id"] for c in d["next"]]), ("Never use.", 1, [2]))
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        self.assertEqual(dash.count_photos(self.conn, "blocked"), 1, "it is on the Never use list, his way back")
        listed = self.client.get("/library?view=blocked").text
        self.assertIn("/media/thumb/1", listed)
        self.assertIn(">Put back<", listed)
        row = db.one(self.conn, "SELECT status, rule_report FROM content_queue WHERE id=?", (waiting,))
        self.assertEqual((row["status"], json.loads(row["rule_report"])["rejected_by"]), ("rejected", "neveruse"))
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (other,))["status"], "draft")
        self.assertEqual(start.call_args[0], ("content",), "the day is drafted again")

    def test_undo_takes_back_the_last_swipe_only(self):
        for pid, q in ((1, 5), (2, 4), (3, 3)):
            self.photo(pid, quality=q)
        self.swipe(1, "cleared")
        self.swipe(2, "blocked")
        d = self.client.post("/library/swipe/undo", data={"subject": "event"}, headers=JSON).json()
        self.assertEqual((self.clearance(1), self.clearance(2)), ("cleared", "inherit"), "the last swipe, and only it")
        self.assertEqual(d["undone"], 2)
        self.assertEqual([c["id"] for c in d["next"]], [2, 3], "the photo is undecided again, back at the front")
        self.assertEqual((d["left"], d["undo"]), (2, False))
        again = self.client.post("/library/swipe/undo", data={"subject": "event"}, headers=JSON).json()
        self.assertEqual(again["words"], "Nothing to undo.")
        self.assertEqual(self.clearance(1), "cleared", "a second Undo does not reach further back")

    def test_undo_leaves_a_photo_changed_since(self):
        self.photo(1)
        self.swipe(1, "blocked")
        self.client.post("/library/photo/1/clearance", data={"state": "inherit"})        # Put back on the Never use list
        self.client.post("/library/photo/1/clearance", data={"state": "cleared"})        # then Use on To review
        d = self.client.post("/library/swipe/undo", data={"subject": "event"}, headers=JSON).json()
        self.assertEqual(d["words"], "That photo was changed since; nothing undone.")
        self.assertEqual(self.clearance(1), "cleared")

    def test_only_a_photo_waiting_on_to_review_can_be_swiped(self):
        self.photo(1)
        self.photo(2, method="folder")                 # not sorted: never offered
        self.swipe(1, "blocked")
        for pid in (1, 2, 999):
            r = self.swipe(pid, "cleared")
            self.assertEqual(r.status_code, 409, pid)
        self.assertEqual((self.clearance(1), self.clearance(2)), ("blocked", "inherit"), "a refused swipe changes nothing")
        d = self.swipe(1, "cleared").json()
        self.assertEqual((d["words"], d["left"], d["next"]), ("That photo is not waiting for review any more; nothing changed.", 0, []),
                         "the page is told in words, with what is waiting now")
        self.assertEqual(self.client.post("/library/swipe/1", data={"state": "inherit"}).status_code, 400)

    def test_nothing_is_cleared_but_by_a_right_swipe(self):
        for pid in range(1, 6):
            self.photo(pid, quality=pid % 5 + 1)
        self.deck()
        self.client.get("/library?view=review")
        self.client.get("/library/swipe?subject=architecture")
        self.client.post("/library/swipe/undo", data={"subject": "event"})
        self.assertEqual({r["clearance"] for r in db.rows(self.conn, "SELECT clearance FROM photos")}, {"inherit"})

    def test_without_the_script_the_buttons_are_forms_and_the_page_comes_back(self):
        self.photo(1, quality=5)
        self.photo(2)
        deck, page = self.deck()
        self.assertIn('action="/library/swipe/1" class="decide"', page)
        self.assertIn('<button class="danger" type="submit">✕ Never use</button>', page)      # it was Don't use (2026-11-02)
        self.assertIn('<span class="verdict out">Never use</span>', page)
        self.assertIn("Swipe right for Use, left for Never use.", page)
        self.assertNotIn("Don&#39;t use", page)
        self.assertNotIn("Don't use", page)
        r = self.client.post("/library/swipe/1", data={"state": "blocked", "subject": "event"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers["location"], "/library/swipe?subject=event&msg=Never+use.")
        self.assertIn('action="/library/swipe/2" class="decide"', self.client.get(r.headers["location"]).text)

    # ------------------------------------------------------------------ what the deck shows
    def test_the_counter_and_the_cards_follow_to_review(self):
        for pid in range(1, 8):
            self.photo(pid, quality=pid % 5 + 1, subject="architecture" if pid == 7 else "event")
        deck, page = self.deck()
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        want = [p["id"] for p in dash.photo_page(self.conn, "review", 1, size=dash.SWIPE_AHEAD, subject="event")]
        self.assertEqual(deck["left"], 6)
        self.assertEqual(deck["left"], dash.count_photos(self.conn, "review", "event"))
        self.assertIn('id="left">6 left · Events</span>', page)
        self.assertEqual([c["id"] for c in deck["next"]], want)
        self.assertEqual(len(want), dash.SWIPE_AHEAD, "the card on screen and the next ones, their pictures loaded ahead")
        self.assertEqual(deck["next"][0]["big"], f"/media/preview/{want[0]}")
        self.assertEqual(deck["next"][0]["small"], f"/media/thumb/{want[0]}")
        self.assertEqual(self.swipe(want[0], "blocked").json()["left"], 5)
        buildings, _ = self.deck("architecture")
        self.assertEqual((buildings["left"], [c["id"] for c in buildings["next"]]), (1, [7]))

    def test_the_end_of_the_list_says_so(self):
        self.photo(1, subject="architecture")
        _, page = self.deck()
        self.assertIn("Nothing left to review in Events.", page)
        self.assertIn('href="/library/swipe?subject=architecture">Buildings (1 left)</a>', page)
        self.assertIn('<div class="choices2" id="choices" hidden>', page, "no Use or Never use with nothing to decide")
        self.assertIn('<div class="hint" id="hint" hidden>', page)
        self.assertIn(".choices2[hidden],.hint[hidden]{display:none}", page, "hidden stays hidden under the page's own display")

    def test_to_review_has_the_way_in(self):
        self.photo(1)
        self.photo(2)
        page = self.client.get("/library?view=review&subject=event").text
        self.assertIn('<a class="go" href="/library/swipe?subject=event"><strong>Swipe through them</strong>'
                      '<span>One photo at a time, the strongest first. 2 to go.</span></a>', page)
        self.conn.execute("UPDATE photos SET clearance='blocked'")
        self.conn.commit()
        self.assertNotIn("Swipe through them", self.client.get("/library?view=review&subject=event").text)

    def test_the_keys(self):
        """ArrowRight is Use, ArrowLeft is Never use (it was Don't use until 2026-11-02), U is Undo: the page's key
        handler reads this table, and every state in it is one the swipe accepts."""
        self.photo(1)
        deck, page = self.deck()
        self.assertEqual(deck["keys"], {"ArrowRight": "cleared", "ArrowLeft": "blocked", "u": "undo", "U": "undo"})
        self.assertEqual({v for v in deck["keys"].values() if v != "undo"}, set(dash.SWIPE_STATES))
        self.assertIn("var KEYS = data.keys;", page)
        handler = page[page.index("document.addEventListener('keydown'"):]
        handler = handler[:handler.index("});") + 3]
        self.assertIn("var act = KEYS[e.key];", handler)
        self.assertIn("if (act === 'undo') { undo(); } else { decide(act); }", handler)
        self.assertIn("e.metaKey || e.ctrlKey || e.altKey", handler, "a browser shortcut is left alone")
        self.assertIn("INPUT|TEXTAREA|SELECT", handler, "typing in a field is not a swipe")
        decide = page[page.index("function decide(state, front)"):page.index("function undo()")]
        self.assertIn("post('/library/swipe/' + c.id, {state: state, subject: subject})", decide, "the key's state is what is posted")


class ToReviewList(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.now = db.utcnow()
        for fid, parent in (("top", None), ("f", "top"), ("g", None)):
            db.insert(self.conn, "drive_folders", drive_id=fid, name=fid, parent_id=parent, clearance="not_cleared",
                      first_seen_at=self.now, last_seen_at=self.now)

    def photo(self, pid, *, method="vision", quality=3, folder="f", shot="candid", rejudge=0, light=None, moment=None):
        db.insert(self.conn, "photos", id=pid, drive_id=f"d{pid}", name=f"{pid}.jpg", folder_id=folder,
                  first_seen_at=self.now, last_seen_at=self.now)
        db.insert(self.conn, "classifications", photo_id=pid, method=method, subject="event", shot_type=shot, quality=quality,
                  light=light, moment=moment, rejudge=rejudge, personal_details="[]", classified_at=self.now)

    def review(self):
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        return [p["id"] for p in dash.photo_page(self.conn, "review", 1, size=100)]

    def test_nothing_on_the_do_not_use_list_is_offered(self):
        for pid, folder in ((1, "f"), (2, "f"), (3, "g"), (4, "g"), (5, "g")):
            self.photo(pid, folder=folder)
        self.assertEqual(sorted(self.review()), [1, 2, 3, 4, 5])
        db.insert(self.conn, "do_not_use", kind="photo", value="d1", added_at=self.now)          # a row from the old Never use button
        db.insert(self.conn, "do_not_use", kind="folder", value="top", added_at=self.now)        # the folder above f
        db.insert(self.conn, "credits", scope="photo", drive_id="d4", person_name="Jane Roe", synced_at=self.now)
        db.insert(self.conn, "do_not_use", kind="person", value="jane roe", added_at=self.now)
        self.assertEqual(sorted(self.review()), [3, 5])
        self.assertEqual(dash.count_photos(self.conn, "review"), 2)

    def test_the_list_agrees_with_the_photo_by_photo_rule(self):
        for seed in range(5):
            rng = random.Random(seed)
            for t in ("credits", "do_not_use", "classifications", "photos", "drive_folders"):
                self.conn.execute(f"DELETE FROM {t}")
            build_library(self.conn, rng, n_photos=200, n_folders=20)
            for i in rng.sample(range(1, 201), 8):
                db.insert(self.conn, "do_not_use", kind="photo", value=f"d{i}", added_at=self.now)
            for f in rng.sample(range(20), 3):
                db.insert(self.conn, "do_not_use", kind="folder", value=f"f{f}", added_at=self.now)
            for i in rng.sample(range(1, 201), 6):
                db.insert(self.conn, "credits", scope="photo", drive_id=f"d{i}", person_name=rng.choice(("A B", "C D")),
                          handle=rng.choice((None, "@cd")), synced_at=self.now)
            db.insert(self.conn, "credits", scope="folder", drive_id=f"f{rng.randrange(20)}", person_name="A B", synced_at=self.now)
            db.insert(self.conn, "do_not_use", kind="person", value="a b", added_at=self.now)
            db.insert(self.conn, "do_not_use", kind="handle", value="@cd", added_at=self.now)
            want = {r["id"] for r in db.rows(self.conn, "SELECT * FROM photos") if eligibility.blocked_by_list(self.conn, r)}
            self.assertTrue(want, "the reference must not be empty")
            self.assertEqual(eligibility.do_not_use_photos(self.conn), want, f"seed {seed}")

    def test_claude_scores_lead_and_the_old_scores_follow(self):
        self.photo(1, method="ollama", quality=5, light=5, moment=5, rejudge=1)    # the old sorter's 10 of 10
        self.photo(2, method="vision", quality=2)
        self.photo(3, method="vision", quality=4, light=4, moment=4)
        self.photo(4, method="ollama", quality=3)
        self.assertEqual(self.review(), [3, 2, 1, 4])
        self.conn.execute("UPDATE classifications SET method='vision', quality=5, light=5, moment=5, rejudge=0 WHERE photo_id=1")
        self.assertEqual(self.review(), [1, 3, 2, 4], "once Claude has sorted it again, it takes its place")

    def test_a_sorted_photo_with_no_kind_of_shot_is_not_called_unsorted(self):
        self.photo(1, shot=None, rejudge=1, quality=5)
        self.photo(2, shot=None, quality=4)
        self.photo(3, shot="main_stage", quality=3)
        self.conn.commit()
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        page = client.get("/library?view=review").text
        words = re.findall(r'<div class="muted" style="margin-top:6px">([^<]*)</div>', page)
        self.assertEqual(words, ["kind of shot: being sorted again", "kind of shot not named", "main stage"])
        self.assertNotIn("not sorted yet", page)
        self.assertEqual(dash.kind_words({"method": "folder", "shot_type": None}), "not sorted yet")


class Preview(IsolatedCase):
    """The card's picture is Drive's own preview at PREVIEW_EDGE, read only, cached beside the small ones."""

    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        now = db.utcnow()
        db.insert(self.conn, "photos", id=1, drive_id="d1", name="1.jpg", thumbnail_link="https://drive.example/t=s220",
                  first_seen_at=now, last_seen_at=now)
        self.conn.commit()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.asked = []

    def fetcher(self, conn, size=400):
        def fetch(drive_id):
            self.asked.append((drive_id, size))
            return b"\xff\xd8 big" if size == dash.PREVIEW_EDGE else b"\xff\xd8 small"
        return fetch

    def test_the_large_preview_is_fetched_once_and_kept_under_the_previews_cap(self):
        from unittest import mock
        with mock.patch.object(dash, "drive_thumb_fetch", self.fetcher):
            first = self.client.get("/media/preview/1")
            second = self.client.get("/media/preview/1")
        self.assertEqual((first.content, second.content), (b"\xff\xd8 big", b"\xff\xd8 big"))
        self.assertEqual(self.asked, [("d1", 1200)], "fetched once, then from the Mini's disk")
        self.assertTrue(dash.thumb_file("d1", 1200).is_file())
        self.assertEqual(dash.thumb_file("d1", 1200).parent, dash.thumb_file("d1").parent, "the folder the nightly sweep caps")

    def test_without_drive_the_small_one_stands_in(self):
        dash.thumb_file("d1").parent.mkdir(parents=True, exist_ok=True)
        dash.thumb_file("d1").write_bytes(b"\xff\xd8 small")
        self.assertEqual(self.client.get("/media/preview/1").content, b"\xff\xd8 small")

    def test_a_swipe_lets_its_large_preview_go(self):
        now = db.utcnow()
        db.insert(self.conn, "classifications", photo_id=1, method="vision", subject="event", quality=3, personal_details="[]",
                  classified_at=now)
        self.conn.commit()
        dash.thumb_file("d1", dash.PREVIEW_EDGE).parent.mkdir(parents=True, exist_ok=True)
        dash.thumb_file("d1", dash.PREVIEW_EDGE).write_bytes(b"big")
        dash.thumb_file("d1").write_bytes(b"small")
        self.client.post("/library/swipe/1", data={"state": "cleared", "subject": "event"}, headers=JSON)
        self.assertFalse(dash.thumb_file("d1", dash.PREVIEW_EDGE).exists(), "it was for that one card")
        self.assertTrue(dash.thumb_file("d1").exists(), "the lists keep theirs")
        self.assertEqual(settings.get(self.conn, dash.SWIPE_LAST), json.dumps({"id": 1, "state": "cleared"}))
