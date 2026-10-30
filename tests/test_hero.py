"""The website's main photo and the spread across events (Chris, 2026-10-11: "The main photo needs to be the
most colorful and dynamic photo - a wide stage panorama shot or a very powerful trump shot. And we need to not
have CPAC and ACU the first thing on everything")."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient
from PIL import Image

from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import design_samples
from convention_social.site import build
from tests._base import IsolatedCase
from tests.test_wedding import event_photo

RED, GREY = (230, 30, 40), (120, 120, 120)


def picture(colour, size=(600, 400)):
    return Image.new("RGB", size, colour)


class Score(IsolatedCase):
    def test_colour_and_punch_are_measured_from_the_picture(self):
        self.assertGreater(build.colorfulness(picture(RED)), 0.8)
        self.assertLess(build.colorfulness(picture(GREY)), 0.05)
        half = Image.new("RGB", (600, 400), (20, 20, 20))
        half.paste((240, 240, 240), (0, 0, 300, 400))
        self.assertGreater(build.colorfulness(half), 0.4, "a punchy frame counts even without colour")

    def test_a_wide_colourful_stage_shot_outscores_a_grey_one_of_the_same_strength(self):
        stage = {"quality": 5, "sharp": 1, "light": 5, "moment": 5, "shot_type": "stage_panel", "width": 3000, "height": 1500}
        grey = {**stage, "shot_type": "candid", "width": 3000, "height": 2400}
        self.assertGreater(build.hero_score(stage, picture(RED)), build.hero_score(grey, picture(GREY)) + 1.0)
        self.assertAlmostEqual(build.hero_score(stage, picture(GREY)) - build.hero_score({**stage, "shot_type": "candid", "width": 3000, "height": 2400}, picture(GREY)), 0.75)

    def test_spread_puts_one_of_each_before_any_repeats(self):
        rows = [{"e": "cpac", "n": 1}, {"e": "cpac", "n": 2}, {"e": "katsu", "n": 3}, {"e": "cpac", "n": 4}, {"e": "summit", "n": 5}]
        self.assertEqual([r["n"] for r in build.spread(rows, lambda r: r["e"])], [1, 3, 5, 2, 4])


class Hero(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.colours, self.fetched = {}, []

    def add(self, drive_id, colour, *, event="CPAC 2025", shot="candid", width=3000, height=2000, kind="business", **kw):
        pid = event_photo(self.conn, drive_id, kind=kind, final=kind, width=width, height=height, **kw)
        self.conn.execute("UPDATE classifications SET shot_type=?, convention_name=? WHERE photo_id=?", (shot, event, pid))
        self.colours[drive_id] = colour
        return pid

    def fetch(self, row):
        self.fetched.append(row["drive_id"])
        return picture(self.colours[row["drive_id"]], (int(row["width"]), int(row["height"])))

    def test_the_hero_is_the_colourful_wide_stage_shot_not_the_strongest_grey_one(self):
        self.add("grey-best", GREY, quality=5, light=5, moment=5)
        self.add("stage", RED, quality=4, light=4, moment=4, shot="stage_panel", width=3000, height=1600)
        self.add("red-crowd", RED, quality=4, light=4, moment=4)
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(photos.hero[0][0].getpixel((5, 5)), RED)
        self.assertEqual(photos.hero[0][1], "Stage panel")
        self.assertEqual(len(photos.coverage), 2)
        self.assertRegex(photos.hero_note, r"^the build's choice: photo \d+ \(stage panel, score \d\.\d\d of 3 looked at\)$")

    def test_chris_own_pick_wins_while_it_is_usable(self):
        self.add("grey-best", GREY, quality=5, light=5, moment=5)
        pick = self.add("mine", GREY, quality=3, light=3, moment=3, width=2000, height=3000)
        settings.set(self.conn, build.HERO_KEY, str(pick))
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(photos.hero[0][0].size, (2000, 3000), "his pick, portrait or not")
        self.assertEqual(photos.hero_note, f"your Site hero pick (photo {pick}, candid moment)")
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (pick,))
        self.fetched.clear()
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(photos.hero[0][0].size, (3000, 2000), "a pick he since blocked is not used")
        self.assertIn(f"your Site hero pick (photo {pick}) could not be used: Chris blocked this photo; the build chose instead; "
                      "the build's choice: photo", photos.hero_note)
        settings.set(self.conn, build.HERO_KEY, "999")
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(photos.hero[0][0].size, (3000, 2000), "a pick that is no photo is ignored")
        self.assertIn("is not an event photo in the library", photos.hero_note)

    def test_the_grid_never_leads_with_one_event_on_everything(self):
        for i in range(5):                                                   # five strong CPAC frames, grey, told apart by shade
            self.add(f"cpac{i}", (100 + i, 100 + i, 100 + i), quality=5, light=5, moment=5, event="CPAC 2025")
        self.add("katsu", (90, 90, 90), quality=4, light=4, moment=4, event="Katsucon 2025", kind="fan")
        self.add("summit", (80, 80, 80), quality=3, light=3, moment=3, event="Liberty Summit")
        photos = build.pick_photos(self.conn, self.fetch)
        hero = photos.hero[0][0].getpixel((0, 0))[0]
        self.assertIn(hero, range(100, 105), "one of the strongest frames is the hero; which of the equals is chance")
        shades = [im.getpixel((0, 0))[0] for im, _ in photos.coverage]
        self.assertIn(shades[0], range(100, 105), "the grid: one of each event first, strongest first inside a round")
        self.assertEqual(shades[1:3], [90, 80])
        self.assertEqual(sorted([hero, shades[0], *shades[3:]]), [100, 101, 102, 103, 104], "then the other CPAC frames")


class ThePick(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.pid = event_photo(self.conn, "h1", kind="business", final="business")

    def test_the_button_on_approved_sets_and_unsets_the_hero(self):
        page = self.client.get("/library?view=approved").text
        self.assertIn("Site hero</button>", page)
        self.assertNotIn("site hero</span>", page)
        r = self.client.post(f"/library/photo/{self.pid}/hero", data={"back": f"/library?view=approved&page=1#p{self.pid}"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["location"].startswith(f"/library?view=approved&page=1&msg=Site+hero%3A+this+photo."), r.headers["location"])
        self.assertTrue(r.headers["location"].endswith(f"#p{self.pid}"))
        self.assertEqual(settings.get(self.conn, build.HERO_KEY), str(self.pid))
        page = self.client.get("/library?view=approved").text
        self.assertIn("Site hero: chosen", page)
        self.assertIn("site hero</span>", page)
        r = self.client.post(f"/library/photo/{self.pid}/hero", data={"back": "/library?view=approved"}, follow_redirects=False)
        self.assertIn("the+build+chooses+again", r.headers["location"])
        self.assertEqual(settings.get(self.conn, build.HERO_KEY), "")
        anon = TestClient(create_app())
        self.assertNotEqual(anon.post(f"/library/photo/{self.pid}/hero", data={}, follow_redirects=False).status_code, 303)


class Samples(IsolatedCase):
    def test_the_samples_take_one_event_and_one_room_before_any_repeats(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        for i in range(4):
            pid = event_photo(conn, f"c{i}", kind="business", final="business", quality=5, light=5, moment=5)
            conn.execute("UPDATE classifications SET shot_type='stage_panel', convention_name='CPAC 2025' WHERE photo_id=?", (pid,))
            conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))
        pid = event_photo(conn, "k0", kind="fan", final="fan", quality=3, light=3, moment=3)
        conn.execute("UPDATE classifications SET shot_type='stage_panel', convention_name='Katsucon' WHERE photo_id=?", (pid,))
        conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))
        picked = [r["drive_id"] for r in design_samples.pick(conn, 3)]
        self.assertTrue(picked[0].startswith("c"), "a CPAC frame first (the strongest); which of the four equals is chance")
        self.assertEqual(picked[1], "k0", "the second pick is the other event, not another CPAC frame")
