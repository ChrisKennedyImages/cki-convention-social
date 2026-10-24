"""The four bold designs (render/bold.py, render/palette.py) and their place in the daily plan.

Chris, 2026-10-15: "come up with some new designs (like 4 so they arent all exactly the same design everytime) and make
sure you follow strict color theory and proper design and make them super super super dynamic and punchy". He kept
three of the first round (cascade, select, the poster in black and white), asked for one radically different (slit
scan), and on round 2: "perfect! and we still keep the original one we started with on the very first post to insta"
(the spotlight). A room's name is printed only when Claude's final check of the full photo confirms that room."""
from __future__ import annotations

import io
import json
import types
from datetime import date, datetime, timezone

from PIL import Image

from convention_social.agents import content
from convention_social.core import config, db, runner
from convention_social.library import classify
from convention_social.render import bold, design_samples, meta, motion, palette as pal
from convention_social.render.posts import CopyRefused
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

WIDE = (3000, 2000)


def plate(color, size=WIDE, stripe=None):
    """A flat photo stand in, with a stripe of a second colour when asked (a real photo is never made up here)."""
    im = Image.new("RGB", size, color)
    if stripe:
        im.paste(stripe, (0, int(size[1] * 0.45), size[0], int(size[1] * 0.55)))
    return im


def shots(n, colors=((200, 40, 60), (40, 90, 200), (60, 160, 90), (220, 160, 40), (120, 60, 160), (40, 40, 44))):
    rooms = ("MAIN STAGE", "PORTRAITS", "EXPO FLOOR", "THE CROWD", "BACKSTAGE", "EVENT PHOTOGRAPHY")
    return [motion.Shot(plate(colors[i % len(colors)], WIDE if i % 3 else (2000, 3000)), rooms[i % len(rooms)], "In the moment.")
            for i in range(n)]


def ring_background(img, box):
    """The commonest colour in a thin ring just outside a word's box: what the word was set on, read back from pixels."""
    x0, y0, x1, y1 = (int(v) for v in box)
    ring = []
    for a, b, c, e in ((x0 - 6, y0 - 6, x1 + 6, y0 - 3), (x0 - 6, y1 + 3, x1 + 6, y1 + 6), (x0 - 6, y0, x0 - 3, y1), (x1 + 3, y0, x1 + 6, y1)):
        a, b, c, e = max(0, a), max(0, b), min(img.width, c), min(img.height, e)
        if c > a and e > b:
            ring += list(img.crop((a, b, c, e)).getdata())
    return max(set(ring), key=ring.count)


class Drafting(IsolatedCase):
    """The daily draft's own setting (as tests/test_content.py), with no tests of its own: three cleared event photos and
    one building, in dry run unless asked."""

    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        now = db.utcnow()
        for fid, name in (("fe", "Con"), ("fa", "Hotel exteriors")):
            db.insert(self.conn, "drive_folders", drive_id=fid, name=name, clearance="cleared", first_seen_at=now, last_seen_at=now)
        self.ids, self.fetched = {}, []
        for did, folder, subject, q in (("e1", "fe", "event", 5), ("e2", "fe", "event", 4), ("e3", "fe", "event", 3),
                                        ("a1", "fa", "architecture", 5)):
            self.add(did, folder, subject, q)

    def add(self, did, folder="fe", subject="event", q=3):
        now = db.utcnow()
        pid = db.insert(self.conn, "photos", drive_id=did, name=f"{did}.jpg", folder_id=folder, width=3000, height=2000,
                        taken_at="2025:02:14 10:00:00", first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject=subject, convention_name=None,
                  is_convention=int(subject == "event"), quality=q, possible_minor=0, personal_details="[]", space="exterior",
                  residential=0, empty_room=0, sharp=1, light=4, moment=4, shot_type="portrait" if subject == "event" else "building_exterior",
                  classified_at=now)
        self.ids[did] = pid

    def ctx(self, dry=True):
        config.get_config().ensure_dirs()
        return runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), dry, 0)

    def fetch(self, row):
        self.fetched.append(row["drive_id"])
        return jpeg_bytes(seed=len(self.fetched), size=(3000, 2000))

    def last(self):
        row = db.rows(self.conn, "SELECT * FROM content_queue ORDER BY id")[-1]
        return row, json.loads(row["rule_report"]), json.loads(row["render_paths"]), json.loads(row["photo_ids"])


class Designs(IsolatedCase):
    def test_every_design_at_both_sizes_with_clean_metadata(self):
        for name, d in bold.DESIGNS.items():
            for aspect, size in (("4:5", (1080, 1350)), ("2:3", (1000, 1500))):
                out = bold.post(name, shots(d.takes), motion.MotionCopy(), out=self.root / f"{name}-{aspect[0]}.jpg", aspect=aspect)
                with Image.open(out) as im:
                    self.assertEqual(im.size, size, (name, aspect))
                self.assertEqual(meta.is_clean(out), [], name)

    def test_every_word_passes_contrast_before_and_after_it_is_drawn(self):
        for name, d in bold.DESIGNS.items():
            for n in sorted({d.needs, d.takes}):
                made = bold.make(name, shots(n), motion.MotionCopy())
                self.assertTrue(made.words, name)
                for w in made.words:
                    self.assertGreaterEqual(w.ratio, w.need, (name, w.text))
                    self.assertGreaterEqual(pal.contrast(w.fill, ring_background(made.image, w.box)), w.need - 0.01, (name, w.text))

    def test_every_photo_whole_and_no_word_over_one(self):
        for name, d in bold.DESIGNS.items():
            given = shots(d.takes)
            made = bold.make(name, given, motion.MotionCopy())
            self.assertEqual(len(made.photos), d.takes)
            for box, sh in zip(made.photos, given):
                self.assertAlmostEqual((box[2] - box[0]) / (box[3] - box[1]), sh.photo.width / sh.photo.height, delta=0.02, msg=name)
                for w in made.words:
                    self.assertFalse(w.box[0] < box[2] and box[0] < w.box[2] and w.box[1] < box[3] and box[1] < w.box[3], (name, w.text))

    def test_the_copy_rules_stop_every_design(self):
        for name, d in bold.DESIGNS.items():
            bad = shots(d.needs)
            bad[0] = motion.Shot(bad[0].photo, "BACKSTAGE", "Packages from $300.")
            with self.assertRaises(CopyRefused, msg=name):
                bold.make(name, bad, motion.MotionCopy())
            with self.assertRaises(CopyRefused, msg=name):
                bold.make(name, shots(d.needs), motion.MotionCopy(kicker="FULL COVERAGE"))

    def test_each_takes_its_own_number_of_photos(self):
        for name, d in bold.DESIGNS.items():
            with self.assertRaises(ValueError):
                bold.make(name, shots(d.takes + 1), motion.MotionCopy())
            if d.needs > 1:
                with self.assertRaises(ValueError):
                    bold.make(name, shots(d.needs - 1), motion.MotionCopy())
            self.assertEqual((content.NEEDS[name], content.TAKES[name]), (d.needs, d.takes), name)

    def test_the_type_is_two_brand_families_at_most(self):
        for name, d in bold.DESIGNS.items():
            self.assertLessEqual(len({bold.FAMILY[f] for f in d.faces}), 2, name)

    def test_a_word_that_would_leave_the_frame_or_a_missing_letter_is_refused(self):
        img = Image.new("RGB", (400, 200), pal.K)
        st = pal.Setter(img)
        with self.assertRaises(pal.Clipped):
            st.text((350, 100), "MAIN STAGE", bold.face(bold.UNBOUNDED, 60), pal.W, pal.K)
        # Michroma has no arrows: a letter the brand face lacks is refused before anything is drawn (the brand faces are
        # not installed in a test's own root, so the face's answer is given here)
        from unittest import mock
        michroma = types.SimpleNamespace(size=30, path="/fonts/Michroma-Regular.ttf")
        with mock.patch.object(pal, "_has", lambda path, size, ch: ch != "↗"):
            with self.assertRaises(ValueError):
                st.check("QUOTE ↗", michroma, pal.W, pal.K)
            self.assertGreater(st.check("QUOTE", michroma, pal.W, pal.K), 4.5)
        fallback = types.SimpleNamespace(size=30, path="/System/Library/Fonts/Helvetica.ttc")
        st.check("QUOTE ↗", fallback, pal.W, pal.K)          # a fallback face is not the brand's: no letter check


class Colour(IsolatedCase):
    def test_the_accent_turns_the_photos_own_hue_by_the_rule(self):
        red = [plate((210, 30, 40))]
        hue = pal.dominant(pal.swatches(red)).h
        for rule, turns in (("complementary", (180,)), ("split", (150, 210)), ("triadic", (120, 240)), ("analogous", (30, -30))):
            p = pal.choose(red, rule, lightness=0.74)
            self.assertEqual(p.rule, rule)
            self.assertTrue(any(pal.hue_gap(p.accent_hue, hue + t) < 1 for t in turns), (rule, p.accent_hue, hue))
            self.assertGreaterEqual(pal.lch(p.accent)[1], pal.MIN_ACCENT_CHROMA, rule)
        self.assertGreater(pal.hue_gap(pal.choose([plate((30, 60, 210))], "complementary", lightness=0.74).accent_hue,
                                       pal.choose(red, "complementary", lightness=0.74).accent_hue), 60)

    def test_a_photo_with_no_hue_takes_the_brand_cyan_and_a_muddy_accent_is_not_used(self):
        grey = [plate((120, 120, 124))]
        self.assertIsNone(pal.dominant(pal.swatches(grey)))
        self.assertEqual(pal.choose(grey, "split", lightness=0.76).accent, pal.C)
        self.assertTrue(pal.choose([plate((210, 30, 40))], "complementary", lightness=0.995).fallback)

    def test_a_palette_that_fails_contrast_is_drawn_in_black_and_white(self):
        bad = pal.Palette("complementary", pal.K, pal.W, pal.G5, (24, 24, 26), (20, 20, 22))
        made = bold.make("select", shots(4), motion.MotionCopy(), palette=bad)
        self.assertIn("needed", made.fell_back)
        self.assertEqual(made.palette.rule, "black and white")
        self.assertTrue(all(w.ratio >= w.need for w in made.words))

    def test_the_poster_and_the_slit_scan_add_no_colour_of_their_own(self):
        self.assertEqual(bold.make("poster", shots(1), motion.MotionCopy()).palette.accent, pal.K)
        self.assertEqual(bold.make("scan", shots(1), motion.MotionCopy()).palette.accent, pal.W)

    def test_the_slit_scan_draws_out_the_photos_most_colourful_line(self):
        im = plate((90, 90, 94), stripe=(230, 40, 120))
        made = bold.make("scan", [motion.Shot(im, "PORTRAITS", "Speakers and guests, backstage.")], motion.MotionCopy())
        x0, y0, x1, _ = made.photos[0]
        streak = made.image.getpixel(((x0 + x1) // 2, y0 - 20))
        self.assertGreater(streak[0], streak[1] + 60, "the streak over the photo is the stripe's magenta, not its grey")


class Plan(IsolatedCase):
    def test_the_week_and_no_design_two_days_running(self):
        week = [content.DESIGNS[d] for d in content.WEEKDAYS]
        self.assertEqual(set(week), {"spotlight", "poster", "scan", "cascade", "select", "reel"})
        self.assertNotIn("single", week)
        for i in range(7):
            self.assertNotEqual(week[i], week[(i + 1) % 7], content.WEEKDAYS[i])
        monday = date(2026, 10, 19)
        for i in range(7):
            day = date.fromordinal(monday.toordinal() + i)
            fb = content.fallback_for(day)
            self.assertEqual(content.NEEDS[fb], 1)
            for near in (-1, 1):
                self.assertNotEqual(fb, content.DESIGNS[content.WEEKDAYS[(i + near) % 7]], (content.WEEKDAYS[i], near))

    def test_a_building_day_and_a_silent_saturday_take_a_one_photo_design(self):
        wednesday, saturday = date(2026, 10, 21), date(2026, 10, 24)
        self.assertEqual(content.design_for(wednesday, "architecture"), "scan")
        self.assertEqual(content.design_for(date(2026, 10, 22), "architecture"), content.fallback_for(date(2026, 10, 22)))
        self.assertEqual(content.design_for(saturday, "event", has_music=True), "reel")
        self.assertEqual(content.design_for(saturday, "event", has_music=False), content.fallback_for(saturday))

    def test_mostly_reels_every_day_with_music_is_a_reel(self):
        """Chris, 2026-10-23: "Mostly reels". Every day with a music track is a reel; a day without music, or a building
        day, keeps the week's still design (a reel never goes out silent)."""
        monday = date(2026, 10, 19)
        for i in range(7):
            day = date.fromordinal(monday.toordinal() + i)
            self.assertEqual(content.design_for(day, "event", has_music=True), "reel", day)
            self.assertNotEqual(content.design_for(day, "event", has_music=False), "reel", day)
            self.assertNotEqual(content.design_for(day, "architecture", has_music=True), "reel", day)


class Rooms(Drafting):
    """A room is printed only when Claude's final check of the full photo confirms it; otherwise EVENT PHOTOGRAPHY."""

    def confirm(self, did, room):
        db.insert(self.conn, "final_checks", photo_id=self.ids[did], possible_minor=0, personal_details="[]", summary="ok",
                  model="test", checked_at=db.utcnow(), shot_type="portrait", event_kind="business", room=room)

    def test_the_final_check_is_asked_for_the_room_and_keeps_it(self):
        self.assertIn("room", classify.FINAL_SCHEMA["required"])
        self.assertIn("none", classify.FINAL_SCHEMA["properties"]["room"]["enum"])
        self.assertIn("plainly", classify.FINAL_SYSTEM)

        class Look:
            def __init__(self, room):
                self.room, self.beta, self.messages = room, self, self

            def create(self, **kw):
                t = types.SimpleNamespace(type="text", text=json.dumps({"personal_details": [], "shot_type": "portrait",
                                                                         "event_kind": "business", "room": self.room, "summary": "ok"}))
                return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                             usage=types.SimpleNamespace(input_tokens=10, output_tokens=10))
        import os
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        classify.final_check(self.conn, self.ids["e1"], jpeg_bytes(), client=Look("portraits"))
        classify.final_check(self.conn, self.ids["e2"], jpeg_bytes(seed=1), client=Look("a made up room"))
        rooms = {r["photo_id"]: r["room"] for r in db.rows(self.conn, "SELECT photo_id, room FROM final_checks")}
        self.assertEqual(rooms[self.ids["e1"]], "portraits")
        self.assertIsNone(rooms[self.ids["e2"]])

    def test_only_a_confirmed_room_is_printed(self):
        self.confirm("e1", "portraits")
        self.confirm("e2", "none")
        words = content.confirmed_rooms(self.conn, [self.ids["e1"], self.ids["e2"], self.ids["e3"]])
        self.assertEqual(words[self.ids["e1"]], design_samples.ROOM_WORDS["portraits"])
        self.assertEqual(words[self.ids["e2"]], design_samples.UNCONFIRMED)
        self.assertEqual(words[self.ids["e3"]], design_samples.UNCONFIRMED)
        self.assertEqual(design_samples.UNCONFIRMED[0], "EVENT PHOTOGRAPHY")

    def test_the_drafts_print_the_confirmed_room_and_never_say_event_photography_twice(self):
        self.confirm("e1", "portraits")
        seen = []
        real = bold.make

        def spy(name, shots_, copy, **kw):
            seen.append((name, [s.room for s in shots_], copy.kicker))
            return real(name, shots_, copy, **kw)
        from unittest import mock
        with mock.patch.object(bold, "make", spy):
            content.draft_one(self.ctx(), self.fetch, now=datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc))   # tomorrow Tuesday: poster
        self.assertEqual(seen[0], ("poster", ["PORTRAITS"], "EVENT PHOTOGRAPHY"))
        self.conn.execute("DELETE FROM final_checks")
        self.conn.execute("DELETE FROM content_queue")
        seen.clear()
        with mock.patch.object(bold, "make", spy):
            content.draft_one(self.ctx(), self.fetch, now=datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(seen[0][1], ["EVENT PHOTOGRAPHY"])
        self.assertEqual(seen[0][2], "EVENT CALIBER", "the small line never repeats the title")


class Drafts(Drafting):
    def test_each_new_design_drafts_at_4_5_with_its_own_2_3_card(self):
        for did in ("e4", "e5", "e6"):
            self.add(did)
        for now, design in ((datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc), "poster"),
                            (datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc), "scan"),
                            (datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc), "cascade"),
                            (datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc), "select")):
            self.conn.execute("DELETE FROM content_queue")
            self.conn.execute("DELETE FROM photo_use")
            content.draft_one(self.ctx(), self.fetch, now=now)
            _, meta_, renders, ids = self.last()
            self.assertEqual(meta_["design"], design)
            self.assertEqual(len(ids), bold.DESIGNS[design].takes if design != "select" else min(6, len(ids)))
            self.assertGreaterEqual(len(ids), bold.DESIGNS[design].needs)
            self.assertEqual(sorted(renders), ["2:3", "4:5"])
            for aspect, size in (("4:5", (1080, 1350)), ("2:3", (1000, 1500))):
                with Image.open(renders[aspect][0]) as im:
                    self.assertEqual(im.size, size, (design, aspect))
                self.assertEqual(meta.is_clean(__import__("pathlib").Path(renders[aspect][0])), [])
