"""Chris's own picks for the website's gallery (2026-10-29: "Can we also add a tab for the approved photos that I can
click to add to the site's gallery (we already have the button to make any photo the site hero)")."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient
from PIL import Image

from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.site import build, deploy
from convention_social.site import hero as hero_upload
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes
from tests.test_wedding import event_photo

ADDED = "Added to the site's gallery. The site publishes itself with the change in a few minutes."
REFUSED = "Not on the site's gallery: the photo is not approved."


def pick_at(conn, pid, stamp):
    conn.execute("UPDATE photos SET site_pick_at=? WHERE id=?", (stamp, pid))


class TheControl(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.pid = event_photo(self.conn, "g1", kind="business", final="business")

    def stamp(self, pid):
        return db.one(self.conn, "SELECT site_pick_at FROM photos WHERE id=?", (pid,))["site_pick_at"]

    def test_one_tap_adds_the_next_takes_off_and_the_card_shows_it(self):
        page = self.client.get("/library?view=approved").text
        self.assertIn("Site gallery</button>", page)
        self.assertNotIn("site gallery</span>", page)
        r = self.client.post(f"/library/photo/{self.pid}/gallery", data={"back": "/library?view=approved"}, headers={"Accept": "application/json"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"id": self.pid, "picked": True, "words": ADDED})
        self.assertTrue(self.stamp(self.pid))
        self.assertTrue(settings.get(self.conn, deploy.PHOTOS_CHANGED_KEY), "the site follows the pick by itself")
        page = self.client.get("/library?view=approved").text
        self.assertIn("Site gallery: added</button>", page)
        self.assertIn('site-gallery">site gallery</span>', page)
        r = self.client.post(f"/library/photo/{self.pid}/gallery", data={"back": f"/library?view=approved&page=1#p{self.pid}"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["location"].startswith("/library?view=approved&page=1&msg=Taken+off+the+site%27s+gallery."), r.headers["location"])
        self.assertTrue(r.headers["location"].endswith(f"#p{self.pid}"))
        self.assertIsNone(self.stamp(self.pid))
        self.assertNotIn("site gallery</span>", self.client.get("/library?view=approved").text)

    def test_every_copy_of_the_picture_takes_the_pick(self):
        twin = event_photo(self.conn, "g1-copy", kind="business", final="business")
        self.conn.execute("UPDATE photos SET md5='same' WHERE id IN (?, ?)", (self.pid, twin))
        self.client.post(f"/library/photo/{self.pid}/gallery", data={}, headers={"Accept": "application/json"})
        self.assertTrue(self.stamp(twin))
        self.assertEqual(self.stamp(self.pid), self.stamp(twin))
        self.client.post(f"/library/photo/{twin}/gallery", data={}, headers={"Accept": "application/json"})
        self.assertIsNone(self.stamp(self.pid))
        self.assertIsNone(self.stamp(twin))

    def test_a_photo_not_approved_is_refused(self):
        blocked = event_photo(self.conn, "g2", kind="business", final="business")
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (blocked,))
        undecided = event_photo(self.conn, "g3", kind="business", final="business", folder="raw")
        self.conn.execute("UPDATE drive_folders SET clearance='not_cleared' WHERE drive_id='raw'")
        for pid in (blocked, undecided):
            r = self.client.post(f"/library/photo/{pid}/gallery", data={}, headers={"Accept": "application/json"})
            self.assertEqual(r.status_code, 409)
            self.assertEqual(r.json(), {"id": pid, "picked": False, "words": REFUSED})
            r = self.client.post(f"/library/photo/{pid}/gallery", data={"back": "/library?view=approved"}, follow_redirects=False)
            self.assertEqual(r.status_code, 303)
            self.assertTrue(r.headers["location"].startswith("/library?view=approved&msg=Not+on+the+site%27s+gallery"), r.headers["location"])
            self.assertIsNone(self.stamp(pid))
        self.assertFalse(settings.get(self.conn, deploy.PHOTOS_CHANGED_KEY), "nothing changed, so nothing to publish")
        self.assertEqual(self.client.post("/library/photo/999/gallery", data={}).status_code, 404)
        anon = TestClient(create_app())
        self.assertNotEqual(anon.post(f"/library/photo/{self.pid}/gallery", data={}, follow_redirects=False).status_code, 303)
        self.assertIsNone(self.stamp(self.pid))


class TheGallery(IsolatedCase):
    """The home page's strip: his picks first, in his order, then the pool as before (build.site_picks, lead_with_picks)."""

    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.colours = {}

    def add(self, drive_id, shade, *, event="CPAC 2025", kind="business", **kw):
        pid = event_photo(self.conn, drive_id, kind=kind, final=kind, **kw)
        self.conn.execute("UPDATE classifications SET shot_type='crowd', convention_name=? WHERE photo_id=?", (event, pid))
        self.colours[drive_id] = (shade, shade, shade)
        return pid

    def fetch(self, row):
        return Image.new("RGB", (int(row["width"]), int(row["height"])), self.colours[row["drive_id"]])

    def shades(self, photos):
        return [im.getpixel((0, 0))[0] for im, _ in photos.coverage]

    def hero_shade(self, photos):
        return photos.hero[0][0].getpixel((0, 0))[0]

    def test_his_picks_lead_in_his_order_then_the_pool_fills_as_before(self):
        cpac = [self.add(f"cpac{i}", 100 + i, quality=5, light=5, moment=5) for i in range(6)]
        katsu = self.add("katsu", 90, quality=4, light=4, moment=4, event="Katsucon 2025", kind="fan")
        summit = self.add("summit", 80, quality=3, light=3, moment=3, event="Liberty Summit")
        for n, pid in enumerate((summit, cpac[4], katsu)):                   # tapped in this order
            pick_at(self.conn, pid, f"2026-10-29T10:0{n}:00+00:00")
        photos = build.pick_photos(self.conn, self.fetch)
        shades = self.shades(photos)
        self.assertEqual(shades[:3], [80, 104, 90], "his picks first, in the order he tapped them")
        hero = self.hero_shade(photos)
        self.assertIn(hero, (100, 101, 102, 103, 105), "the build's hero is a strong frame he did not pick for the gallery")
        self.assertEqual(sorted(shades[3:] + [hero]), [100, 101, 102, 103, 105], "then the rest of the pool, as before")
        self.assertEqual(photos.grid_ids[1:4], [summit, cpac[4], katsu], "the picks are recorded as used with the rest of the grid")
        self.assertEqual(photos.grid_note, f"your Site gallery picks lead the gallery, in your order: photos {summit}, {cpac[4]}, {katsu}")

    def test_a_pick_no_longer_usable_is_left_out_and_said(self):
        self.add("lead", 70, quality=5, light=5, moment=5)
        kept = self.add("kept", 80, quality=3, light=3, moment=3, event="Liberty Summit")
        blocked = self.add("blocked", 81, quality=5, light=5, moment=5, event="Katsucon 2025", kind="fan")
        gone = self.add("gone", 82, quality=5, light=5, moment=5, event="Summit 2024")
        for n, pid in enumerate((blocked, gone, kept)):
            pick_at(self.conn, pid, f"2026-10-29T10:0{n}:00+00:00")
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (blocked,))
        self.conn.execute("UPDATE photos SET trashed=1 WHERE id=?", (gone,))
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(self.hero_shade(photos), 70)
        self.assertEqual(self.shades(photos), [80], "the pick still usable leads; the two others are not shown")
        self.assertEqual(photos.grid_note,
                         f"your Site gallery picks lead the gallery, in your order: photos {kept}; "
                         f"your Site gallery pick (photo {blocked}) could not be used: Chris blocked this photo; "
                         f"your Site gallery pick (photo {gone}) could not be used: photo is no longer in Drive")

    def test_the_hero_is_never_in_the_gallery_as_well(self):
        best = self.add("best", 100, quality=5, light=5, moment=5)
        other = self.add("other", 90, quality=4, light=4, moment=4, event="Liberty Summit")
        pick_at(self.conn, best, "2026-10-29T10:00:00+00:00")
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(self.hero_shade(photos), 90, "the build's hero leaves his gallery pick to the gallery")
        self.assertEqual(self.shades(photos), [100])
        settings.set(self.conn, build.HERO_KEY, str(best))
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(self.hero_shade(photos), 100, "his hero pick wins")
        self.assertEqual(self.shades(photos), [90])
        self.assertEqual(photos.grid_note, f"your Site gallery pick (photo {best}) is the hero, so the gallery does not show it again")
        settings.set(self.conn, build.HERO_KEY, "")
        pick_at(self.conn, other, "2026-10-29T10:01:00+00:00")           # every usable frame picked: the hero still comes from them
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(self.hero_shade(photos), 100)
        self.assertEqual(self.shades(photos), [90])
        self.assertEqual(photos.grid_note, f"your Site gallery picks lead the gallery, in your order: photos {other}; "
                                           f"your Site gallery pick (photo {best}) is the hero, so the gallery does not show it again")

    def test_the_same_picture_under_two_ids_is_one_pick(self):
        self.add("stage", 70, quality=5, light=5, moment=5, event="Liberty Summit")
        a = self.add("a", 100, quality=4, light=4, moment=4)
        b = self.add("a-copy", 100, quality=4, light=4, moment=4)
        self.conn.execute("UPDATE photos SET md5='same', site_pick_at='2026-10-29T10:00:00+00:00' WHERE id IN (?, ?)", (a, b))
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(self.hero_shade(photos), 70)
        self.assertEqual(self.shades(photos), [100], "once")
        self.assertIn(photos.grid_note, {f"your Site gallery picks lead the gallery, in your order: photos {a}",
                                         f"your Site gallery picks lead the gallery, in your order: photos {b}"})

    def test_with_the_photo_he_sent_as_the_hero_his_picks_still_lead(self):
        self.add("best", 100, quality=5, light=5, moment=5)
        mine = self.add("mine", 80, quality=3, light=3, moment=3, event="Liberty Summit")
        pick_at(self.conn, mine, "2026-10-29T10:00:00+00:00")
        hero_upload.save(jpeg_bytes(size=(1600, 1000)))
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(photos.hero[0][0].size, (1600, 1000))
        self.assertEqual(self.shades(photos), [80, 100])
        self.assertEqual(photos.grid_note, f"your Site gallery picks lead the gallery, in your order: photos {mine}")
