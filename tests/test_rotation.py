"""Every surface spreads across the whole approved pool, the least recently used photo first (Chris, 2026-10-14:
"You also keep using the same fucking photos for everything when I have approved at least 40 by now")."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from convention_social.agents import content
from convention_social.core import auth, config, db, runner, settings
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import report
from convention_social.render import design_samples
from convention_social.site import build
from tests._base import IsolatedCase
from tests._fakes import add_post
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say
from tests.test_wedding import event_photo

MONDAY = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)       # tomorrow is Tuesday: a single photo
SUNDAY = datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)       # tomorrow is Monday: the spotlight


class Rotate(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.ids = [event_photo(self.conn, f"p{i}", kind="business", final="business", quality=5 - i) for i in range(4)]

    def test_two_uses_inside_one_second_still_tell_which_came_last(self):
        """Seen red under a frozen clock (2026-10-24 audit): db.utcnow() is whole seconds, so two site builds inside
        one second tied on last use and the next build drew among their photos by chance (OnTheSite below)."""
        with mock.patch.object(db, "utcnow", return_value="2026-10-24T12:00:00+00:00"):
            report.record_use(self.conn, "site", [self.ids[0]], ref="site:a")
            report.record_use(self.conn, "site", [self.ids[1]], ref="site:b")
        last = report.last_uses(self.conn)
        self.assertGreater(last[self.ids[1]], last[self.ids[0]])
        order = [r["id"] for r in report.rotate(self.conn, [{"id": i} for i in self.ids], last=last)]
        self.assertEqual(order[-2:], [self.ids[0], self.ids[1]], "the older use comes round before the newer one")

    def test_never_used_first_then_the_oldest_use_on_any_surface(self):
        rows = [{"id": i} for i in self.ids]
        report.record_use(self.conn, "post", [self.ids[0]], ref="post:1", now="2026-10-01T08:00:00+00:00")
        report.record_use(self.conn, "site", [self.ids[2]], ref="site:x", now="2026-10-10T08:00:00+00:00")
        report.record_use(self.conn, "sample", [self.ids[0]], ref="sample:y", now="2026-10-12T08:00:00+00:00")
        order = [r["id"] for r in report.rotate(self.conn, rows)]
        self.assertEqual(sorted(order[:2]), sorted([self.ids[1], self.ids[3]]), "the never used first")
        self.assertEqual(order[2:], [self.ids[2], self.ids[0]], "then the oldest use on any surface, the newest last")

    def test_among_equal_photos_used_alike_chance_not_file_order(self):
        """Chris, 2026-10-23: "I seem to always get the same style and pic in my drafts". Equal photos fell back to
        file order, so the next frame of one big folder led every draft's second slot. Quality still leads."""
        import random
        rows = [{"id": 100 + k, "quality": 5} for k in range(6)] + [{"id": 200 + k, "quality": 2} for k in range(6)]
        orders = set()
        for seed in range(8):
            got = report.rotate(self.conn, rows, last={}, rng=random.Random(seed), alike=lambda r: r["quality"])
            self.assertEqual({r["quality"] for r in got[:6]}, {5}, "the better photos lead")
            orders.add(tuple(r["id"] for r in got))
        self.assertGreater(len(orders), 4, "and among equals the order is not fixed")


    def test_a_use_is_one_row_per_photo_on_a_known_surface(self):
        self.assertEqual(report.record_use(self.conn, "post", [self.ids[0], self.ids[0], self.ids[1]], ref="post:7"), 2)
        rows = db.rows(self.conn, "SELECT photo_id, surface, ref FROM photo_use ORDER BY photo_id")
        self.assertEqual([tuple(r) for r in rows], [(self.ids[0], "post", "post:7"), (self.ids[1], "post", "post:7")])
        with self.assertRaises(ValueError):
            report.record_use(self.conn, "reel", [self.ids[0]])
        self.assertEqual(report.forget_use(self.conn, "post:7"), 2)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM photo_use")["n"], 0)

    def test_the_drafts_made_before_the_table_existed_count_once(self):
        settings.set(self.conn, report.HISTORY_KEY, "done")                       # while the table did not exist
        q1 = add_post(self.conn, [self.ids[0], self.ids[1]], status="published")
        q2 = add_post(self.conn, [self.ids[1], 999], status="draft")              # 999: a photo since removed
        self.conn.execute("UPDATE content_queue SET created_at='2026-09-01T09:00:00+00:00' WHERE id=?", (q1,))
        q3 = add_post(self.conn, [self.ids[2]], status="draft")
        report.record_use(self.conn, "post", [self.ids[2]], ref=f"post:{q3}")       # a draft that recorded its own use first
        settings.set(self.conn, report.HISTORY_KEY, "")                           # as on the Mini the day this lands
        self.assertEqual(report.ensure_use_history(self.conn), 3, "the two old drafts; the one already recorded is not counted twice")
        self.assertEqual(report.ensure_use_history(self.conn), 0, "once")
        last = report.last_uses(self.conn)
        self.assertEqual(last[self.ids[0]], "2026-09-01T09:00:00+00:00")
        self.assertEqual(sorted(last), sorted([self.ids[0], self.ids[1], self.ids[2]]))
        use = report.use_of(self.conn, self.ids)
        self.assertEqual((use[self.ids[1]]["n"], use[self.ids[1]]["surfaces"]), (2, ["post"]))
        self.assertEqual(use[self.ids[2]]["n"], 1)
        self.assertNotIn(self.ids[3], use)
        self.assertEqual(db.one(self.conn, "SELECT ref FROM photo_use WHERE photo_id=? ORDER BY id DESC", (self.ids[1],))["ref"], f"post:{q2}")

    def test_the_line_under_an_approved_photo(self):
        self.assertEqual(report.use_line(None), "never used yet")
        self.assertEqual(report.use_line({"n": 1, "last": "2026-10-14", "surfaces": ["post"]}), "used 1 time, last on 2026-10-14 (post)")
        self.assertEqual(report.use_line({"n": 3, "last": "2026-10-14", "surfaces": ["post", "sample", "site"]}),
                         "used 3 times, last on 2026-10-14 (post, ideas, site)")      # the samples are called ideas (2026-10-15)


class Drafts(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        config.get_config().ensure_dirs()
        self.data = jpeg_bytes(size=(3000, 2000))

    def ctx(self, dry=True):
        return runner.Context("content", self.conn, logging.getLogger("t"), config.get_config(), dry, 0)

    def draft(self, now=MONDAY, *, keep=False, **kw) -> tuple[str, list[int]]:
        """One draft; the queue row is dropped unless `keep`, so the repeat window cannot be what spreads them."""
        line = content.draft_one(self.ctx(kw.pop("dry", True)), lambda r: self.data, now=now, **kw)
        row = db.one(self.conn, "SELECT id, photo_ids FROM content_queue ORDER BY id DESC LIMIT 1")
        ids = [int(p) for p in __import__("json").loads(row["photo_ids"])] if row else []
        if not keep:
            self.conn.execute("DELETE FROM content_queue")
        return line, ids

    def test_forty_photos_of_the_same_quality_make_forty_different_drafts_before_a_repeat(self):
        pool = [event_photo(self.conn, f"p{i:02d}", kind="business", quality=5) for i in range(40)]
        heroes = [self.draft()[1][0] for _ in range(40)]
        self.assertEqual(len(set(heroes)), 40, "every approved photo had its turn before any came round again")
        self.assertEqual(sorted(heroes), sorted(pool))
        # the use clock is in seconds, so drafts made inside one second are used alike and which leads is chance
        first = db.one(self.conn, "SELECT MIN(used_at) AS t FROM photo_use")["t"]
        oldest = {r["photo_id"] for r in db.rows(self.conn, "SELECT photo_id FROM photo_use WHERE used_at=?", (first,))}
        self.assertIn(self.draft()[1][0], oldest, "the forty-first draft: one used longest ago")

    def test_quality_only_breaks_ties_among_the_never_used(self):
        strong = event_photo(self.conn, "strong", kind="business", quality=5)
        weak = event_photo(self.conn, "weak", kind="business", quality=3)
        middle = event_photo(self.conn, "middle", kind="business", quality=4)
        report.record_use(self.conn, "site", [strong], ref="site:a")                # the site showed the strong one
        self.assertEqual(self.draft()[1], [middle], "the strongest never-used photo, not the strongest photo")
        self.assertEqual(self.draft()[1], [weak])
        self.assertEqual(self.draft()[1], [strong], "its turn once the others had theirs")

    def test_a_draft_in_the_same_second_as_a_site_use_comes_after_it(self):
        """Red on CI (2026-10-25, #126's run): the draft stamped its use with the queue row's whole-second time while
        the site stamps to the microsecond; inside one second the whole second sorts first ('+' before '.'), so the
        draft's photo read as used before the site's and came round again at once."""
        strong = event_photo(self.conn, "strong", kind="business", quality=5)
        weak = event_photo(self.conn, "weak", kind="business", quality=3)
        middle = event_photo(self.conn, "middle", kind="business", quality=4)
        stamps = iter(f"2026-10-25T12:00:00.{n:06d}+00:00" for n in (100, 200, 300, 400))
        with mock.patch.object(db, "utcnow", return_value="2026-10-25T12:00:00+00:00"), \
             mock.patch.object(report, "use_stamp", side_effect=lambda: next(stamps)):
            report.record_use(self.conn, "site", [strong], ref="site:a")
            self.assertEqual(self.draft()[1], [middle])
            self.assertEqual(self.draft()[1], [weak])
            self.assertEqual(self.draft()[1], [strong], "the site's use is the oldest, whole second or not")

    def test_a_draft_records_a_post_use_for_every_photo_on_it_dry_run_included(self):
        for i in range(5):
            event_photo(self.conn, f"p{i}", kind="business", quality=5)
        line, ids = self.draft(SUNDAY, keep=True)
        self.assertIn("spotlight with 5 photo(s)", line)
        qid = db.one(self.conn, "SELECT id FROM content_queue")["id"]
        rows = db.rows(self.conn, "SELECT photo_id, surface, ref, used_at FROM photo_use ORDER BY photo_id")
        self.assertEqual(sorted(r["photo_id"] for r in rows), sorted(ids))
        self.assertEqual({(r["surface"], r["ref"]) for r in rows}, {("post", f"post:{qid}")})
        self.assertEqual(len({r["used_at"] for r in rows}), 1, "one moment for the whole draft, so they tie next time")

    def test_the_art_directors_reject_is_a_use_too(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        for i in range(2):
            event_photo(self.conn, f"p{i}", kind="business", final="business", quality=5)
        from tests.test_content import FinalClient
        art = ArtClientAny([say("reject", notes="Flat light."), say("pass")])
        line, _ = self.draft(MONDAY, keep=True, dry=False, check_client=FinalClient({}), art_client=art)
        self.assertIn("art director turned back photo", line)
        rows = db.rows(self.conn, "SELECT q.status, u.photo_id FROM photo_use u JOIN content_queue q ON q.id = CAST(substr(u.ref, 6) AS INTEGER) ORDER BY u.id")
        self.assertEqual([r["status"] for r in rows], ["rejected", "draft"], "the turned back photo and the drafted one both count")
        self.assertNotEqual(rows[0]["photo_id"], rows[1]["photo_id"])

    def test_the_repeat_window_is_still_the_floor(self):
        """The rotation remembers uses; the window forbids them. With the memory wiped, the window alone still holds."""
        a = event_photo(self.conn, "a", kind="business", quality=5)
        b = event_photo(self.conn, "b", kind="business", quality=4)
        self.conn.execute("UPDATE classifications SET convention_name='Other Con' WHERE photo_id=?", (b,))   # the event rule is not what we test
        self.assertEqual(self.draft(keep=True)[1], [a])
        self.conn.execute("DELETE FROM photo_use")
        settings.set(self.conn, report.HISTORY_KEY, "done")
        tuesday = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)      # the next draft (a building day with no building: event work)
        self.assertEqual(self.draft(tuesday, keep=True)[1], [b], "a sits out for PHOTO_REPEAT_DAYS whatever the rotation says")

    def test_the_run_line_says_which_photo_led_and_why(self):
        for i in range(3):
            event_photo(self.conn, f"p{i}", kind="business", quality=5)
        pool = [r["id"] for r in db.rows(self.conn, "SELECT id FROM photos ORDER BY id")]
        report.record_use(self.conn, "site", [pool[1]], ref="site:x", now="2026-10-01T08:00:00+00:00")  # two were on the site,
        report.record_use(self.conn, "site", [pool[2]], ref="site:y", now="2026-10-02T08:00:00+00:00")  # one a day later
        line, ids = self.draft()
        self.assertEqual(ids, [pool[0]])
        self.assertIn(f"photo {pool[0]} first (never used before; 3 ready, least recently used first)", line)
        line, ids2 = self.draft()
        self.assertEqual(ids2, [pool[1]], "the one used longest ago leads")
        self.assertIn(f"photo {pool[1]} first (last used 2026-10-01; 3 ready, least recently used first)", line)


class OnTheSite(IsolatedCase):
    """2026-10-14, the coverage pages: every usable event photo is on some coverage page on every build (six a room,
    least recently used first), so `photos.ids` is the whole pool and says nothing about rotation. What rotates is
    the home page (`photos.grid_ids`: the hero when it is a library photo, the grid, the venues), and that is what a
    build records in photo_use; the coverage pages are a view of the library, not a pick. Three builds' worth of
    photos and four over, so the home page turns over three times before any comes round again (the strip grew to
    twelve frames on 2026-10-14, so the count follows COVERAGE_ROWS)."""

    N = 3 * (1 + build.COVERAGE_ROWS) + 4

    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.ids = [event_photo(self.conn, f"p{i:02d}", kind="business", final="business", quality=5) for i in range(self.N)]

    def fetch(self, row):
        return Image.new("RGB", (int(row["width"]), int(row["height"])), (80, 60, 120))

    def shown(self, preview=False):
        photos = build.pick_photos(self.conn, self.fetch)
        build.build(self.conn, photos, out=self.root / "dist", preview=preview)
        self.assertEqual(len(photos.ids), self.N, "every usable photo is on the home page or a coverage page")
        self.assertEqual(photos.ids[:len(photos.grid_ids)], photos.grid_ids)
        return photos.grid_ids

    def test_each_publish_shows_the_photos_the_last_one_did_not(self):
        first = self.shown()
        self.assertEqual(len(first), 1 + build.COVERAGE_ROWS, "the hero and the grid")
        rows = db.rows(self.conn, "SELECT photo_id, surface, ref FROM photo_use")
        self.assertEqual(sorted(r["photo_id"] for r in rows), sorted(first), "the home page's photos are the use, not the coverage pages'")
        self.assertTrue(all(r["surface"] == "site" and r["ref"].startswith("site:") for r in rows))
        second = self.shown()
        self.assertEqual(set(first) & set(second), set(), "the home page's photos sit at the back of the line: others next")
        third = self.shown()
        self.assertEqual(set(third) & (set(first) | set(second)), set())
        shown = set(first) | set(second) | set(third)
        self.assertEqual(len(shown), 3 * (1 + build.COVERAGE_ROWS))
        fourth = self.shown()
        self.assertEqual(set(fourth) - shown, set(self.ids) - shown, "the four never shown, then the ones used longest ago")
        self.assertTrue(set(fourth) & shown <= set(first), "then the ones used longest ago: the first build's, used alike")
        self.assertEqual(len(set(fourth) & shown), len(fourth) - 4)

    def test_a_preview_records_nothing(self):
        self.shown(preview=True)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM photo_use")["n"], 0)
        photos = build.pick_photos(self.conn, self.fetch)
        build.build(None, photos, out=self.root / "dist")                           # no database: nothing to record into
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM photo_use")["n"], 0)

    def test_the_hero_chris_picked_is_never_rotated_away(self):
        pick = self.ids[5]
        settings.set(self.conn, build.HERO_KEY, str(pick))
        for _ in range(3):
            self.assertEqual(self.shown()[0], pick)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM photo_use WHERE photo_id=?", (pick,))["n"], 3)

    def test_the_grid_rotates_under_the_uploaded_hero_too(self):
        os.environ["SITE_HERO_SHIPPED"] = str(self.root / "hero.jpg")
        Image.new("RGB", (2400, 1200), (10, 20, 30)).save(self.root / "hero.jpg")
        config.reset()
        first, second = self.shown(), self.shown()
        self.assertEqual(len(first), build.COVERAGE_ROWS, "the grid only: the uploaded hero is not a library photo")
        self.assertEqual(set(first) & set(second), set())
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM photo_use")["n"], 2 * build.COVERAGE_ROWS,
                         "two builds, the grid each time; the coverage pages record nothing")


class Samples(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.ids = []
        for i in range(9):
            pid = event_photo(self.conn, f"s{i}", kind="business", final="business", quality=5)
            self.conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))
            self.conn.execute("UPDATE classifications SET shot_type=?, convention_name=? WHERE photo_id=?",
                              (("stage_panel", "crowd", "backstage")[i % 3], f"Event {i % 3}", pid))
            self.ids.append(pid)

    def test_each_set_of_samples_is_on_photos_the_last_set_was_not(self):
        first = design_samples.make(self.conn, lambda fid: jpeg_bytes(size=(1600, 1000)), out_root=self.root / "r", n=3, reels=False)
        rows = db.rows(self.conn, "SELECT photo_id, surface, ref FROM photo_use")
        self.assertEqual(len(rows), 3)
        self.assertEqual({(r["surface"], r["ref"]) for r in rows}, {("sample", f"sample:{first.name}")})
        used = {r["photo_id"] for r in rows}
        again = [r["id"] for r in design_samples.pick(self.conn, 3)]
        self.assertEqual(set(again) & used, set(), "the next three: one per room and event, among the never used")

    def test_a_remake_comes_when_the_approved_photos_change_not_when_the_six_rotate(self):
        with mock.patch.object(design_samples, "start_in_background") as start:
            self.assertIn("started", design_samples.auto(self.conn))
            design_samples.write_status("done", "made", folder="design-x")
            design_samples.made(self.conn)
            report.record_use(self.conn, "sample", self.ids[:6], ref="sample:design-x")     # what `ccs design` records
            self.assertIn("up to date", design_samples.auto(self.conn), "the six rotated; the approved photos did not change")
            report.record_use(self.conn, "post", self.ids[6:], ref="post:1")
            self.assertIn("up to date", design_samples.auto(self.conn))
            self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (self.ids[0],))
            self.assertIn("started", design_samples.auto(self.conn), "one taken away: made again")
        self.assertEqual(start.call_count, 2)


class OnThePage(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.a = event_photo(self.conn, "a", kind="business", final="business")
        self.b = event_photo(self.conn, "b", kind="business", final="business", quality=4)

    def test_the_approved_view_says_how_often_each_photo_was_used(self):
        report.record_use(self.conn, "post", [self.a], ref="post:1", now="2026-10-01T08:00:00+00:00")
        report.record_use(self.conn, "site", [self.a], ref="site:x", now="2026-10-14T08:00:00+00:00")
        page = self.client.get("/library?view=approved").text
        self.assertIn("used 2 times, last on 2026-10-14 (post, site)", page)
        self.assertIn("never used yet", page)
        self.assertIn("the least recently used first", page)
        self.assertNotIn("use-line", self.client.get("/library?view=review").text)

    def test_fixing_a_shot_word_gives_the_draft_its_photos_back(self):
        """The draft is set aside and made again with the right words: the same photo should lead it, so its use is undone."""
        qid = add_post(self.conn, [self.a], status="draft")
        report.record_use(self.conn, "post", [self.a], ref=f"post:{qid}")
        report.record_use(self.conn, "post", [self.b], ref="post:other")
        with mock.patch.object(dash, "start_agent"):
            r = self.client.post(f"/queue/{qid}/photo/{self.a}/shot", data={"shot_type": "stage_panel"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual([r["ref"] for r in db.rows(self.conn, "SELECT ref FROM photo_use")], ["post:other"])
        self.assertEqual([r["id"] for r in report.rotate(self.conn, [{"id": self.b}, {"id": self.a}])], [self.a, self.b])


class OneShootAPost(IsolatedCase):
    """2026-10-23: post 27 took four frames of one folder ("Texas Sunday"). A post takes one photo per shoot before any
    repeats; CPAC and the ACU may still fill several places, from different shoots ("You can use more than one")."""
    def test_the_daily_post_takes_one_photo_per_shoot_before_any_repeat(self):
        from convention_social.agents import content
        big = [{"id": k, "folder_id": "texas-sunday", "convention_name": "", "shot_type": "stage_panel"} for k in range(8)]
        other = [{"id": 50 + k, "folder_id": f"f{k}", "convention_name": "", "shot_type": "stage_panel"} for k in range(5)]
        got = content.order_pool(big + other, "reel")[:6]
        self.assertEqual(len({r["folder_id"] for r in got}), 6, [r["folder_id"] for r in got])
