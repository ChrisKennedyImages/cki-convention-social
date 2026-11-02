"""The Photos tab reads one page from the database instead of the whole library (Chris, 2026-10-11:
"Photos tab is dead"). Pinned against the rules it replaced: on random libraries the pages hold
exactly the photos, in exactly the order, that the old whole-library lists did."""
from __future__ import annotations

import json
import os
import random
import re
from unittest import mock
import time
from pathlib import Path

from fastapi.testclient import TestClient

from convention_social.core import auth, config, db
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import eligibility, report
from tests._base import IsolatedCase

DETAILS = ("[]", "[]", "[]", None, '["badge_name"]', '["house_number"]', '["plate"]', "not json")


def old_lists(conn):
    """The whole-library lists the Photos tab used before, kept here as the reference."""
    decisions = eligibility.folder_decisions(conn)
    rows = db.rows(conn, """SELECT p.*, c.method, c.subject, c.quality, c.sharp, c.light, c.moment, c.possible_minor,
                                   c.personal_details FROM photos p LEFT JOIN classifications c ON c.photo_id = p.id
                            WHERE p.trashed = 0 ORDER BY p.id""")
    srt = lambda r: r["method"] in ("ollama", "vision")  # noqa: E731
    review = []
    for r in rows:
        # 2026-10-15: no age filter (Chris: "If I approve something, it means I checked it"); it was possible_minor != 0
        if not srt(r) or eligibility.decision_of(r, decisions) != "not_cleared":
            continue
        try:
            details = json.loads(r["personal_details"] or "[]")
        except ValueError:
            continue                                       # the old code crashed here; the new one keeps it out
        if eligibility.blocking_details(details, r["subject"]):
            continue
        review.append(r)
    # 2026-11-02: Claude's scores lead; a photo only the old local sorter scored follows them until Claude sorts it again
    review.sort(key=lambda r: (0 if r["method"] == "vision" else 1, -report.strength(r)))
    approved = [r for r in rows if eligibility.decision_of(r, decisions) == "cleared"]
    approved.sort(key=lambda r: (0 if srt(r) else 1, -report.strength(r) if srt(r) else 0))
    return [r["id"] for r in review], [r["id"] for r in approved]


def build_library(conn, rng, n_photos=400, n_folders=30):
    now = db.utcnow()
    ids = [f"f{i}" for i in range(n_folders)]
    for i, fid in enumerate(ids):
        parent = rng.choice(ids[:i]) if i and rng.random() < 0.6 else None
        db.insert(conn, "drive_folders", drive_id=fid, name=f"Folder {i}", parent_id=parent, image_count=10,
                  clearance=rng.choice(("not_cleared", "not_cleared", "cleared", "excluded")), first_seen_at=now, last_seen_at=now)
    for i in range(1, n_photos + 1):
        db.insert(conn, "photos", id=i, drive_id=f"d{i}", name=f"{i}.jpg", folder_id=rng.choice(ids + [None]),
                  trashed=int(rng.random() < 0.05), clearance=rng.choice(("inherit", "inherit", "inherit", "cleared", "blocked")),
                  first_seen_at=now, last_seen_at=now)
        if rng.random() < 0.85:
            db.insert(conn, "classifications", photo_id=i, method=rng.choice(("ollama", "ollama", "vision", "folder")),
                      subject=rng.choice(("event", "event", "architecture", None)), quality=rng.choice((None, 1, 2, 3, 4, 5)),
                      sharp=rng.choice((None, 0, 1, 1)), light=rng.choice((None, 1, 3, 5)), moment=rng.choice((None, 2, 4)),
                      possible_minor=rng.choice((0, 0, 0, 1, None)), personal_details=rng.choice(DETAILS), classified_at=now)


class SameRules(IsolatedCase):
    def test_pages_hold_exactly_what_the_old_lists_held_in_the_same_order(self):
        for seed in range(6):
            conn = db.connect()
            for t in ("classifications", "photos", "drive_folders"):
                conn.execute(f"DELETE FROM {t}")
            build_library(conn, random.Random(seed))
            review, approved = old_lists(conn)
            self.assertTrue(review and approved, "the reference lists must not be empty")
            dash.prepare_photo_views(conn, eligibility.folder_decisions(conn))
            for view, want in (("review", review), ("approved", approved)):
                self.assertEqual(dash.count_photos(conn, view), len(want))
                got = [p["id"] for page in range(1, len(want) // 7 + 2) for p in dash.photo_page(conn, view, page, size=7)]
                self.assertEqual(got, want, f"seed {seed}, {view}")
            conn.close()


class Fast(IsolatedCase):
    def test_a_big_library_opens_in_well_under_a_second(self):
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        conn = db.connect()
        now = db.utcnow()
        n = 60000
        conn.execute("BEGIN")
        conn.executemany("INSERT INTO drive_folders (drive_id, name, image_count, clearance, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?)",
                         [(f"f{i}", f"F{i}", 400, "cleared" if i % 10 == 0 else "not_cleared", now, now) for i in range(150)])
        conn.executemany("INSERT INTO photos (id, drive_id, name, folder_id, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?)",
                         [(i, f"d{i}", f"{i}.jpg", f"f{i % 150}", now, now) for i in range(1, n + 1)])
        conn.executemany("INSERT INTO classifications (photo_id, method, quality, light, moment, sharp, possible_minor, personal_details, classified_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?)", [(i, "ollama", i % 5 + 1, i % 4 + 1, i % 3 + 1, 1, 0, "[]", now) for i in range(1, n + 1)])
        conn.execute("COMMIT")
        conn.close()
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        for url in ("/library", "/library?view=approved", "/library?page=40"):
            started = time.monotonic()
            r = client.get(url)
            took = time.monotonic() - started
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.text.count('<img src="/media/thumb/'), 48)
            self.assertLess(took, 1.0, f"{url} took {took:.2f}s")


class Visible(IsolatedCase):
    """A page that fails says what failed and leaves it on the Agents page; pictures that cannot load say why."""
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app(), raise_server_exceptions=False)
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_a_broken_page_says_what_broke_and_records_it(self):
        from unittest import mock

        def boom(*a, **k):
            raise RuntimeError("the photo list could not be read")
        with mock.patch.object(dash, "photo_page", boom):
            r = self.client.get("/library")
        self.assertEqual(r.status_code, 500)
        self.assertIn("This page broke", r.text)
        self.assertIn("RuntimeError: the photo list could not be read", r.text)
        err = db.one(self.conn, "SELECT * FROM errors WHERE agent='dashboard'")
        self.assertEqual(err["kind"], "page_error")
        self.assertIn("/library: RuntimeError", err["message"])
        self.assertIn("Traceback", err["traceback"])
        self.assertIn(f"error {err['id']}", r.text)

    def test_with_drive_signed_out_the_photos_tab_says_so(self):
        from convention_social.core import settings
        self.assertIn("The pictures cannot load: Google Drive is not signed in yet", self.client.get("/library").text)
        settings.set(self.conn, "drive.auth_state", "expired")
        self.assertIn("signed out (the sign-in expired)", self.client.get("/library?view=approved").text)
        settings.set(self.conn, "drive.auth_state", "ok")
        self.assertNotIn("The pictures cannot load", self.client.get("/library").text)


class Subjects(IsolatedCase):
    """Chris, 2026-10-11: "Architecture images should be separated from event/convention photos"."""

    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="f", name="F", clearance="not_cleared", first_seen_at=now, last_seen_at=now)
        for i, subject in enumerate(("event", "event", "architecture", None), start=1):
            db.insert(self.conn, "photos", id=i, drive_id=f"d{i}", name=f"{i}.jpg", folder_id="f", first_seen_at=now, last_seen_at=now,
                      clearance="cleared" if i == 4 else "inherit")
            db.insert(self.conn, "classifications", photo_id=i, method="ollama" if subject else "folder", subject=subject, quality=3,
                      possible_minor=0, personal_details="[]", space="exterior", residential=0, empty_room=0, classified_at=now)

    def test_each_list_is_shown_as_events_and_buildings(self):
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        self.assertEqual((dash.count_photos(self.conn, "review", "event"), dash.count_photos(self.conn, "review", "architecture")), (2, 1))
        self.assertEqual(dash.count_photos(self.conn, "review"), 3, "no subject: the whole list, as before")
        self.assertEqual([p["id"] for p in dash.photo_page(self.conn, "review", 1, subject="architecture")], [3])
        self.assertEqual(dash.count_photos(self.conn, "approved", "event"), 1, "an approved photo the sorter has not placed counts as event work")
        page = self.client.get("/library").text
        self.assertIn("Events (2)", page)
        self.assertIn("Buildings (1)", page)
        self.assertIn("/media/thumb/1", page)
        self.assertNotIn("/media/thumb/3", page)
        buildings = self.client.get("/library?view=review&subject=architecture").text
        self.assertIn("/media/thumb/3", buildings)
        self.assertNotIn("/media/thumb/1", buildings)
        self.assertIn("subject=architecture&amp;page=1#p3", buildings, "a tap comes back to the same list")
        self.assertIn("No building photos approved yet", self.client.get("/library?view=approved&subject=architecture").text)
        self.assertEqual(self.client.get("/library?subject=nonsense").status_code, 200)


class Schedule(IsolatedCase):
    def test_the_daily_draft_is_at_eight(self):
        from convention_social.agents import AGENTS
        self.assertEqual(AGENTS["content"]["schedule"], "daily 08:00")
        plist = (Path(config.REPO_ROOT) / "launchd" / "com.chriskennedyimages.conventionsocial.content.plist.template").read_text()
        self.assertIn("<key>Hour</key><integer>8</integer>", plist)


class ReadyAhead(IsolatedCase):
    """Chris, 2026-10-21: "They take awhile to load and it's 40+ pages". Opening a page gets the next pages'
    previews from Drive in the background, so the next page opens from the Mini's disk."""
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        build_library(self.conn, random.Random(3))
        self.conn.execute("UPDATE photos SET thumbnail_link='https://drive.example/thumb'")
        self.conn.commit()
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        self.fetched = []

    def fetch(self, drive_id):
        self.fetched.append(drive_id)
        return b"\xff\xd8 a preview"

    def page_ids(self, page, size=5):
        return [p["drive_id"] for p in dash.photo_page(self.conn, "review", page, size=size)]

    def test_the_next_pages_are_fetched_not_the_one_on_screen(self):
        t = dash.warm_ahead("review", 1, None, size=5, fetcher=self.fetch)
        t.join(10)
        self.assertEqual(sorted(self.fetched), sorted(self.page_ids(2) + self.page_ids(3)))
        for did in self.fetched:
            self.assertTrue((config.get_config().data_root / "thumbs" / f"{did}.jpg").is_file())
        before = list(self.fetched)
        dash.warm_ahead("review", 1, None, size=5, fetcher=self.fetch).join(10)
        self.assertEqual(self.fetched, before, "a preview already on the Mini is never fetched again")

    def test_opening_a_page_starts_it_for_that_page(self):
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        with mock.patch.object(dash, "warm_ahead") as warm:
            self.assertEqual(client.get("/library").status_code, 200)
        warm.assert_called_once()
        self.assertEqual(warm.call_args.args[:2], ("review", 1))

    def test_the_previews_stay_under_500_mb(self):
        from convention_social import storage
        self.assertEqual(storage.THUMBS_CAP_MB, 500, "Chris was told 500 MB at most (2026-10-21)")


class PagePicker(IsolatedCase):
    """Chris, 2026-11-02: "I'd like to be able to skip to any page I want - like a page picker at the top to jump too"."""

    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="f", name="F", clearance="not_cleared", first_seen_at=now, last_seen_at=now)
        # five pages of event photos to review (the strongest first), and one building
        self.n = dash.PAGE * 4 + 3
        for i in range(1, self.n + 2):
            db.insert(self.conn, "photos", id=i, drive_id=f"d{i}", name=f"{i}.jpg", folder_id="f", first_seen_at=now, last_seen_at=now)
            db.insert(self.conn, "classifications", photo_id=i, method="vision", subject="architecture" if i > self.n else "event",
                      quality=5 - i * 5 // (self.n + 2), personal_details="[]", space="exterior", residential=0, empty_room=0,
                      classified_at=now)
        self.conn.commit()
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))

    @staticmethod
    def pickers(page: str) -> list[str]:
        return [chunk.split("</form>")[0] for chunk in page.split('<form class="row pager"')[1:]]

    def test_the_picker_is_above_the_photos_and_lists_every_page(self):
        page = self.client.get("/library?view=review&subject=event&page=3").text
        pickers = self.pickers(page)
        self.assertEqual(len(pickers), 2, "one above the photos, one under them")
        self.assertLess(page.index('<form class="row pager"'), page.index('<div class="grid">'), "the first is at the top")
        top = pickers[0]
        self.assertIn('method="get" action="/library"', top)
        self.assertIn('name="view" value="review"', top)
        self.assertIn('name="subject" value="event"', top)
        self.assertEqual([int(v) for v in re.findall(r'<option value="(\d+)"', top)], [1, 2, 3, 4, 5])
        self.assertEqual(re.findall(r'<option value="(\d+)" selected>', top), ["3"], "the page on screen is the one picked")
        self.assertIn("of 5", top)
        self.assertIn('onchange="this.form.submit()"', top, "picking a page opens it")
        self.assertIn('<noscript><button class="small" type="submit">Go</button></noscript>', top, "and without a script, Go does")
        self.assertIn('href="/library?view=review&subject=event&page=2">Previous</a>', top)
        self.assertIn('href="/library?view=review&subject=event&page=4">Next</a>', top)

    def test_a_picked_page_shows_that_page(self):
        want = [p["id"] for p in dash.photo_page(self.conn, "review", 4, subject="event")]
        page = self.client.get("/library", params={"view": "review", "subject": "event", "page": "4"}).text
        self.assertEqual([int(i) for i in re.findall(r'<img src="/media/thumb/(\d+)"', page)], want)
        self.assertEqual(re.findall(r'<option value="(\d+)" selected>', page), ["4", "4"])

    def test_the_first_and_last_pages_have_no_way_off_the_end(self):
        first = self.pickers(self.client.get("/library?view=review&subject=event").text)[0]
        self.assertNotIn("Previous", first)
        self.assertIn("page=2\">Next</a>", first)
        last = self.pickers(self.client.get("/library?view=review&subject=event&page=99").text)[0]
        self.assertNotIn("Next", last)
        self.assertIn('<option value="5" selected>', last, "a page past the end opens the last one")

    def test_one_page_needs_no_picker(self):
        page = self.client.get("/library?view=review&subject=architecture").text
        self.assertIn(f"/media/thumb/{self.n + 1}", page)
        self.assertEqual(self.pickers(page), [])

    def test_every_list_has_it(self):
        self.conn.execute("UPDATE photos SET clearance='cleared'")
        self.conn.commit()
        page = self.client.get("/library?view=approved&subject=event&page=2").text
        top = self.pickers(page)[0]
        self.assertIn('name="view" value="approved"', top)
        self.assertEqual(re.findall(r'<option value="(\d+)" selected>', top), ["2"])


class SentenceBadges(IsolatedCase):
    """A badge holding a sentence wraps (2026-11-02: the site's reason and the hero's note, each one unbroken line in a
    badge, pushed the Approved page 380 px past a 393 px phone screen)."""

    def test_the_badges_that_say_a_sentence_can_wrap(self):
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        conn = db.connect()
        self.addCleanup(conn.close)
        now = db.utcnow()
        db.insert(conn, "drive_folders", drive_id="f", name="F", clearance="not_cleared", first_seen_at=now, last_seen_at=now)
        db.insert(conn, "photos", id=1, drive_id="d1", name="1.jpg", folder_id="f", clearance="cleared", first_seen_at=now, last_seen_at=now)
        conn.commit()
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        page = client.get("/library?view=approved&subject=event").text
        self.assertIn(".badge.says{white-space:normal;overflow-wrap:anywhere}", page)
        self.assertIn('<span class="badge says blocked">not sorted yet</span>', page, "a photo's reason")
        self.assertRegex(page, r'<span class="badge blocked says">[^<]{40,}</span>', "the reason the site is not published from here")
