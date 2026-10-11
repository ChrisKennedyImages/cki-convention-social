"""The photos as cards in depth (render/stage.py, render/motion.py) and the design samples the Mini makes
on Chris's own photos (render/design_samples.py, `ccs design`, the Library page)."""
from __future__ import annotations

import io
import os
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image, ImageStat

from convention_social.core import auth, config, db
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import design_samples, meta, motion, posts, stage
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes
from tests.test_edge_designs import cyan_pixels

ROOMS = ("MAIN STAGE", "BACKSTAGE", "PANELS", "PORTRAITS", "EXPO FLOOR", "AFTER DARK")


def shots(photos=True):
    return [motion.Shot(Image.new("RGB", (1600, 1200), (60 + 30 * i, 80, 140 - 15 * i)) if photos else None, room,
                        "One plain line about this room.") for i, room in enumerate(ROOMS)]


class Stage(IsolatedCase):
    def test_a_flat_card_lands_where_it_is_placed_at_its_own_size(self):
        face = Image.new("RGBA", (200, 300), (255, 0, 0, 255))
        canvas = Image.new("RGB", (1000, 1000), (0, 0, 0))
        stage.draw(canvas, [stage.Card(face, x=100, y=-50, shadow=0)])
        box = canvas.getbbox()
        self.assertTrue(box)                                                  # drawn at all
        x0, y0, x1, y1 = box
        self.assertAlmostEqual((x0 + x1) / 2, 600, delta=2)
        self.assertAlmostEqual((y0 + y1) / 2, 450, delta=2)
        self.assertAlmostEqual(x1 - x0, 200, delta=3)
        self.assertAlmostEqual(y1 - y0, 300, delta=3)

    def test_depth_shrinks_a_card_and_a_turned_card_is_narrower(self):
        face = Image.new("RGBA", (200, 300), (255, 255, 255, 255))
        widths = []
        for card in (stage.Card(face, shadow=0), stage.Card(face, z=1500, shadow=0), stage.Card(face, yaw=60, shadow=0)):
            canvas = Image.new("RGB", (1000, 1000))
            stage.draw(canvas, [card])
            x0, _, x1, _ = canvas.getbbox()
            widths.append(x1 - x0)
        self.assertAlmostEqual(widths[1], widths[0] / 2, delta=3)           # twice as far, half the size
        self.assertLess(widths[2], widths[0] * 0.6)

    def test_a_card_behind_the_camera_is_skipped(self):
        canvas = Image.new("RGB", (400, 400))
        stage.draw(canvas, [stage.Card(Image.new("RGBA", (100, 100), (255, 255, 255, 255)), z=-stage.FOCAL - 10)])
        self.assertIsNone(canvas.getbbox())

    def test_the_ring_lights_the_front_and_darkens_the_back(self):
        faces = [Image.new("RGBA", (100, 140), (200, 200, 200, 255))] * 8
        cards = motion.ring(faces, angle=0)
        front = min(cards, key=lambda c: c.z)
        back = max(cards, key=lambda c: c.z)
        self.assertGreater(front.light, 0.95)
        self.assertLess(back.light, 0.3)

    def test_the_fan_lifts_the_focused_card_toward_you(self):
        faces = [Image.new("RGBA", (100, 140), (200, 200, 200, 255))] * 7
        cards = motion.fan(faces, focus=3, lift=1.0)
        self.assertEqual(min(cards, key=lambda c: c.z), cards[3])
        self.assertEqual(min(cards, key=lambda c: c.y), cards[3])


class Pieces(IsolatedCase):
    def test_stills_render_with_the_ask_and_clean_metadata(self):
        copy = motion.MotionCopy()
        for fn in (motion.fan_post, motion.spotlight_post, motion.facematch_post):
            out = fn(shots(), copy, out=self.root / f"{fn.__name__}.jpg")
            with Image.open(out) as im:
                self.assertEqual(im.size, (1080, 1350))
                self.assertGreater(cyan_pixels(im, (0, 1200, 1080, 1350)), 4000, fn.__name__)
            self.assertEqual(meta.is_clean(out), [])

    def test_without_photos_the_cards_are_plain_colour(self):
        face = motion.card_face(motion.Shot(None, "PANELS"), 200, 260, 0, label=False)
        self.assertEqual(face.size, (206, 266))
        self.assertGreater(ImageStat.Stat(face.convert("RGB").crop((60, 20, 140, 60))).stddev[0], 0)

    def test_the_carousel_is_a_cover_a_slide_per_room_face_match_and_the_ask(self):
        paths = motion.carousel(shots(), motion.MotionCopy(), out_dir=self.root / "c")
        self.assertEqual([p.name for p in paths], [f"slide-{i:02d}.jpg" for i in range(1, 10)])
        with Image.open(paths[-1]) as close:
            self.assertGreater(cyan_pixels(close, (0, 900, 1080, 1250)), 30000)

    def test_both_reels_are_fifteen_seconds_of_vertical_frames(self):
        for kind, fn in (("rooms", motion.rooms_reel), ("facematch", motion.facematch_reel)):
            total = motion.total_frames(kind)
            self.assertEqual(total, 15 * 30, kind)
            got = []
            picks = [0, 45, 120, 260, 330, total - 1]
            fn(shots(), motion.MotionCopy(), out=self.root / f"{kind}.mp4", only=picks, encoder=lambda frames, out: got.extend(frames))
            self.assertEqual(len(got), len(picks))
            for im in got:
                self.assertEqual(im.size, (1080, 1920))
            self.assertGreater(cyan_pixels(got[-1], (0, 1000, 1080, 1250)), 30000, kind)   # the ask closes it

    def test_the_rules_stop_every_piece(self):
        bad = shots()
        bad[1] = motion.Shot(None, "BACKSTAGE", "Packages from $300.")
        for fn in (motion.fan_post, motion.spotlight_post, motion.facematch_post):
            with self.assertRaises(posts.CopyRefused):
                fn(bad, motion.MotionCopy(), out=self.root / "x.jpg")
        with self.assertRaises(posts.CopyRefused):
            motion.rooms_reel(bad, motion.MotionCopy(), out=self.root / "r.mp4", encoder=lambda f, o: list(f))
        with self.assertRaises(posts.CopyRefused):
            motion.facematch_reel(shots(), motion.MotionCopy(fm_title="OFFICIAL PHOTOGRAPHER"), out=self.root / "r.mp4",
                                  encoder=lambda f, o: list(f))
        self.assertFalse((self.root / "x.jpg").exists())


class DesignSamples(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def photo(self, n, shot_type, *, minor=0, clearance="inherit", details="[]"):
        now = db.utcnow()
        self.conn.execute("INSERT INTO photos (drive_id, name, width, height, clearance, thumbnail_link, first_seen_at, last_seen_at) "
                          "VALUES (?,?,?,?,?,?,?,?)", (f"d{n}", f"{n}.jpg", 3000, 2000, clearance, "https://x/t=s220", now, now))
        pid = db.one(self.conn, "SELECT id FROM photos WHERE drive_id=?", (f"d{n}",))["id"]
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", is_convention=1, possible_minor=minor,
                  personal_details=details, quality=5, sharp=1, light=4, moment=4, shot_type=shot_type,
                  convention_name=f"Con {n}", classified_at=now)
        return pid

    def test_picks_one_frame_per_room_first(self):
        for n, st in enumerate(("stage_panel", "stage_panel", "backstage", "portrait", "vendor_hall", "dinner_reception",
                                "cosplay_portrait")):
            self.photo(n, st)
        picked = design_samples.pick(self.conn, 6)
        rooms = [design_samples.ROOMS.get(r["shot_type"], design_samples.OTHER)[0] for r in picked]
        self.assertEqual(len(picked), 6)
        self.assertEqual(len(set(rooms)), 6)                 # the second stage frame waits for a seventh place

    def test_never_a_minor_a_blocked_a_listed_or_a_detail_photo(self):
        """Fewer good frames than asked for, so anything the filter lets through would be picked."""
        for n, st in enumerate(("stage_panel", "backstage", "portrait")):
            self.photo(n, st)
        self.photo(10, "vendor_hall", minor=1)
        self.photo(11, "candid", clearance="blocked")
        self.photo(12, "crowd")
        db.insert(self.conn, "do_not_use", kind="photo", value="d12", reason="takedown", added_at=db.utcnow())
        self.photo(13, "group", details='["badge_name"]')
        picked = [r["drive_id"] for r in design_samples.pick(self.conn, 6)]
        self.assertEqual(sorted(picked), ["d0", "d1", "d2"])

    def test_makes_every_still_the_carousel_and_one_page(self):
        for n, st in enumerate(("stage_panel", "backstage", "portrait", "vendor_hall")):
            self.photo(n, st)
        fetched = []

        def fetch(fid):
            fetched.append(fid)
            return jpeg_bytes((90, 70, 120), size=(1600, 1066), seed=len(fetched))
        out = design_samples.make(self.conn, fetch, out_root=self.root / "renders", reels=False, log=lambda m: None)
        self.assertRegex(out.name, r"design-\d{8}-\d{4}")
        names = sorted(p.name for p in out.iterdir())
        for want in ("index.html", "about.json", "fan-post.jpg", "spotlight-post.jpg", "facematch-post.jpg", "slide-01.jpg", "slide-07.jpg"):
            self.assertIn(want, names)
        self.assertEqual(sorted(fetched), ["d0", "d1", "d2", "d3"])
        page = (out / "index.html").read_text()
        self.assertIn(f"/library/design/{out.name}/slide-01.jpg", page)
        self.assertIn("nothing here is posted", page)

    def test_too_few_photos_says_so(self):
        self.photo(0, "stage_panel")
        with self.assertRaises(RuntimeError):
            design_samples.make(self.conn, lambda fid: b"", out_root=self.root / "renders", reels=False, log=lambda m: None)


class LibraryPage(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_button_starts_the_designer_and_the_page_serves_only_its_files(self):
        self.assertIn("Make design samples", self.client.get("/library").text)
        with mock.patch("convention_social.dashboard.app.subprocess.Popen") as popen:
            r = self.client.post("/library/design", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(popen.call_args[0][0][-2:], ["convention_social.cli", "design"])
        folder = config.get_config().data_root / "renders" / "design-20261011-1800"
        folder.mkdir(parents=True)
        (folder / "index.html").write_text("<p>samples</p>")
        (folder / "rooms-reel.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
        (folder / "notes.txt").write_text("not a file the designer writes")
        (config.get_config().data_root / "secret.txt").write_text("no")
        r = self.client.get("/library/design", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/library/design/design-20261011-1800/index.html")
        self.assertEqual(self.client.get("/library/design/design-20261011-1800/rooms-reel.mp4").headers["content-type"], "video/mp4")
        for bad in ("/library/design/design-20261011-1800/..%2F..%2Fsecret.txt", "/library/design/renders/index.html",
                    "/library/design/design-20261011-1800/notes.txt"):
            self.assertEqual(self.client.get(bad).status_code, 404, bad)
        self.client.cookies.clear()
        self.assertNotEqual(self.client.get("/library/design/design-20261011-1800/index.html", follow_redirects=False).status_code, 200)
