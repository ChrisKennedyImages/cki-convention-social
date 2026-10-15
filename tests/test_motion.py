"""The photos as cards in depth (render/stage.py, render/motion.py) and the design samples the Mini makes
on Chris's own photos (render/design_samples.py, `ccs design`, the Library page)."""
from __future__ import annotations

import io
import os
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageStat

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


REAL_START = design_samples.start_in_background       # the real one; the test base stubs it in every test

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
        for fn in (motion.fan_post, motion.spotlight_post):
            out = fn(shots(), copy, out=self.root / f"{fn.__name__}.jpg")
            with Image.open(out) as im:
                self.assertEqual(im.size, (1080, 1350))
                self.assertGreater(cyan_pixels(im, (0, 1200, 1080, 1350)), 4000, fn.__name__)
            self.assertEqual(meta.is_clean(out), [])

    def test_without_photos_the_cards_are_plain_colour(self):
        face = motion.card_face(motion.Shot(None, "PANELS"), 200, 260, 0, label=False)
        self.assertEqual(face.size, (206, 266))
        self.assertGreater(ImageStat.Stat(face.convert("RGB").crop((60, 20, 140, 60))).stddev[0], 0)

    def test_the_carousel_is_a_cover_a_slide_per_room_and_the_ask(self):
        paths = motion.carousel(shots(), motion.MotionCopy(), out_dir=self.root / "c")
        self.assertEqual([p.name for p in paths], [f"slide-{i:02d}.jpg" for i in range(1, 9)])
        with Image.open(paths[-1]) as close:
            self.assertGreater(cyan_pixels(close, (0, 900, 1080, 1250)), 30000)

    def test_the_reel_is_fifteen_seconds_of_vertical_frames(self):
        for kind, fn in (("rooms", motion.rooms_reel),):
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
        for fn in (motion.fan_post, motion.spotlight_post):
            with self.assertRaises(posts.CopyRefused):
                fn(bad, motion.MotionCopy(), out=self.root / "x.jpg")
        with self.assertRaises(posts.CopyRefused):
            motion.rooms_reel(bad, motion.MotionCopy(), out=self.root / "r.mp4", encoder=lambda f, o: list(f))
        self.assertFalse((self.root / "x.jpg").exists())

    def test_service_talk_stops_every_piece(self):
        """Chris, 2026-10-11: a card or a reel never talks about what is offered; the old words are refused."""
        selling = [motion.MotionCopy(hook=("EVERY ROOM", "OF YOUR EVENT.")), motion.MotionCopy(covered="COVERED."),
                   motion.MotionCopy(kicker="FULL COVERAGE")]
        for copy in selling:
            with self.assertRaises(posts.CopyRefused):
                motion.fan_post(shots(), copy, out=self.root / "x.jpg")
            with self.assertRaises(posts.CopyRefused):
                motion.rooms_reel(shots(), copy, out=self.root / "r.mp4", encoder=lambda f, o: list(f))
        bad = shots()
        bad[2] = motion.Shot(None, "EXPO FLOOR", "Your vendors and exhibitors get their shots too.")
        with self.assertRaises(posts.CopyRefused):
            motion.spotlight_post(bad, motion.MotionCopy(), out=self.root / "x.jpg")
        for room, line in design_samples.ROOMS.values():
            motion.check_copy(room, line, social=True)
            for word in ("your", "we ", "get ", "lit ", "properly", "every", "covered", "too"):
                self.assertNotIn(word, line.lower(), (room, line))
            self.assertLessEqual(len(line.split()), 6, (room, line))
        self.assertEqual(design_samples.ROOMS["portrait"], ("PORTRAITS", "Speakers and guests, backstage."))
        motion.check_copy(*design_samples.OTHER, motion.MotionCopy().words(), social=True)
        self.assertFalse((self.root / "x.jpg").exists())


def near_pixels(im: Image.Image, box, colour, tol: int = 18) -> Image.Image:
    """A mask of the pixels in `box` within `tol` of `colour` on every channel."""
    chans = im.convert("RGB").crop(box).split()
    near = [ImageChops.invert(ImageChops.difference(ch, Image.new("L", ch.size, v))).point(lambda x: 255 if x > 255 - tol else 0)
            for ch, v in zip(chans, colour)]
    return ImageChops.multiply(ImageChops.multiply(near[0], near[1]), near[2])


def widest_row(mask: Image.Image) -> float:
    """The largest share of any one row the mask covers."""
    rows = mask.resize((1, mask.height), Image.BOX)
    return ImageStat.Stat(rows).extrema[0][1] / 255


class RoomsReelLayout(IsolatedCase):
    """Chris, 2026-10-14, on the reel at phone width: "photos need to be more prominent in the reel frame".
    In every room section the lifted card takes most of the frame's width, under the room's title and line."""

    def room_frame(self, n: int = 6, k: int = 0) -> Image.Image:
        deal, room, _, _, _ = motion.ROOMS_TIMING
        got = []
        motion.rooms_reel(shots()[:n], motion.MotionCopy(), out=self.root / "r.mp4", only=[deal + room * k + 20],
                          encoder=lambda frames, out: got.extend(frames))
        return got[0]

    def test_the_lifted_photo_spans_at_least_three_quarters_of_the_frame(self):
        """Measured on the drawn cover frame (the first room, lifted), not on the geometry."""
        sh = shots()[0]
        colour = motion.card_face(sh, 400, 540, 0, label=False).convert("RGB").getpixel((200, 120))
        frame = self.room_frame()
        share = widest_row(near_pixels(frame, (0, 0, 1080, 1920), colour))
        self.assertGreaterEqual(share, 0.75, f"the photo spans {share:.2f} of the frame's width")

    def test_the_lifted_card_sits_inside_the_frame_under_the_room_type_for_four_to_six_rooms(self):
        for n in (4, 5, 6):
            for k in range(n):
                x0, y0, x1, y1 = motion.room_card_box(n, k)
                self.assertGreaterEqual((x1 - x0) / motion.RW, 0.75, (n, k))
                self.assertTrue(40 <= x0 and x1 <= motion.RW - 40, (n, k, x0, x1))            # whole, with a margin
                self.assertGreater(y0, motion.ROOMS_TYPE["line"] + 60, (n, k, y0))             # under a two line caption
                self.assertLessEqual(y1, motion.RH - 120, (n, k, y1))                          # above the frame's foot
        self.assertEqual(motion.still_frames("rooms", 6)[0], motion.ROOMS_TIMING[0] + 20)     # the cover is this frame

    def test_the_room_title_and_line_are_drawn_clear_of_the_card(self):
        frame = self.room_frame(k=1)
        x0, y0, x1, y1 = motion.room_card_box(6, 1)
        band = (0, 200, 1080, int(y0) - 4)
        white = ImageStat.Stat(near_pixels(frame, band, motion.W, 40)).sum[0] / 255
        self.assertGreater(white, 12000, "the title is not above the card")
        colour = motion.card_face(shots()[1], 400, 540, 1, label=False).convert("RGB").getpixel((200, 120))
        self.assertEqual(widest_row(near_pixels(frame, band, colour)), 0.0, "the card reaches into the type")
        self.assertGreater(widest_row(near_pixels(frame, (0, int(y0) + 20, 1080, int(y0) + 200), colour)), 0.7)

    def test_the_posts_keep_the_small_lift(self):
        """fan_post and the carousel cover are unchanged: only the reel's hand lifts the card this far."""
        faces = [Image.new("RGBA", (100, 140), (200, 200, 200, 255))] * 7
        card = motion.fan(faces, focus=3, lift=1.0)[3]
        self.assertEqual((card.z, round(card.scale, 4)), (-220, round(0.78 * 1.14, 4)))
        self.assertEqual((motion.ROOMS_HAND["lift_z"], motion.ROOMS_HAND["lift_scale"]), (460, 0.49))


class DesignSamples(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def photo(self, n, shot_type, *, minor=0, clearance="cleared", details="[]"):
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
                                "crowd")):
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
        self.photo(14, "dinner_reception", clearance="inherit")     # never approved: Chris, "don't use it yet or at all"
        self.photo(12, "crowd")
        db.insert(self.conn, "do_not_use", kind="photo", value="d12", reason="takedown", added_at=db.utcnow())
        self.photo(13, "group", details='["vehicle_plate"]')          # a name badge would be fine (2026-10-12); a plate is not
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
        for want in ("index.html", "about.json", "fan-post.jpg", "spotlight-post.jpg", "slide-01.jpg", "slide-06.jpg"):
            self.assertNotIn("facematch-post.jpg", names)
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
        self.assertIn("Make design samples", self.client.get("/library?view=design").text)
        with mock.patch.object(design_samples, "start_in_background") as start:
            r = self.client.post("/library/design", follow_redirects=False)
        self.assertEqual((r.status_code, start.call_count), (303, 1))
        self.assertIn("Being made now", self.client.get(r.headers["location"]).text)
        with mock.patch("subprocess.Popen") as popen:
            REAL_START()
        self.assertEqual(popen.call_args[0][0][-2:], ["convention_social.cli", "design"])
        self.assertTrue(popen.call_args[1]["start_new_session"])
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


class ApprovedOnly(IsolatedCase):
    """Chris, 2026-10-11: "I only want to choose what I approve and if it's not approved then don't use it
    yet or at all". The samples take a photo cleared by itself or by its folder, and nothing else."""

    def test_a_folder_clear_counts_and_an_undecided_photo_never_does(self):
        conn = db.connect()
        now = db.utcnow()
        for fid, name, state in (("fy", "Cleared shoot", "cleared"), ("fn", "Not yet", "not_cleared")):
            conn.execute("INSERT INTO drive_folders (drive_id, name, clearance, first_seen_at, last_seen_at) VALUES (?,?,?,?,?)",
                         (fid, name, state, now, now))
        for n, folder in enumerate(("fy", "fy", "fn", "fn")):
            conn.execute("INSERT INTO photos (drive_id, name, width, height, clearance, folder_id, thumbnail_link, first_seen_at, last_seen_at) "
                         "VALUES (?,?,?,?, 'inherit', ?, 'https://x/t=s220', ?, ?)", (f"a{n}", f"{n}.jpg", 3000, 2000, folder, now, now))
            pid = db.one(conn, "SELECT id FROM photos WHERE drive_id=?", (f"a{n}",))["id"]
            db.insert(conn, "classifications", photo_id=pid, method="ollama", subject="event", is_convention=1, possible_minor=0,
                      personal_details="[]", quality=5, sharp=1, light=4, moment=4, shot_type="portrait", classified_at=now)
        self.assertEqual(sorted(r["drive_id"] for r in design_samples.pick(conn, 6)), ["a0", "a1"])
        conn.close()
