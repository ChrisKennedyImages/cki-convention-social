"""The ten reel looks (render/reel_looks.py, reel-looks/, reel_lines.py): the Remotion project, the words a reel's own
photos give it, the photos each look may take, the props and the render run, the frames cut for the art director, and
the rotation that adds them only while REEL_LOOKS is on. Remotion is never run here: the run is a seam."""
from __future__ import annotations

import contextlib
import io
import json
import os
import random
import re
import subprocess
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from PIL import Image

from convention_social import music, reel_lines
from convention_social.agents import content, learner
from convention_social.core import config, db, notify, runner, settings
from convention_social.render import meta as image_meta, reel, reel_looks, reels3d
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes
from tests.test_content import FinalClient, say
from tests.test_music import RECORD, tone
from tests.test_wedding import event_photo

SRC = reel_looks.REEL_LOOKS / "src"


def photo(room, size=(3000, 2000), focus=reel_looks.DEFAULT_FOCUS):
    return reel_looks.LookPhoto(Image.new("RGB", size, (90, 60, 40)), room, focus)


def track(tmp: Path, *, start=17.986, rate=120 / 114.96) -> music.LookTrack:
    path = tmp / "piano.mp3"
    path.write_bytes(b"ID3")
    return music.LookTrack(path, start, rate)


class Project(IsolatedCase):
    """reel-looks/: the looks Chris approved, each its own composition, its own pinned packages, fonts with their OFL
    texts, and no trace of a staging folder."""
    def test_ten_looks_each_a_composition_of_its_own_length(self):
        self.assertEqual(len(reel_looks.LOOKS), 10)
        root = (SRC / "Root.tsx").read_text()
        registered = re.search(r"export const LOOKS[^{]*\{([^}]*)\}", root).group(1)
        self.assertEqual(sorted(x.strip() for x in registered.split(",") if x.strip()), sorted(reel_looks.COMPOSITION.values()))
        for look, comp in reel_looks.COMPOSITION.items():
            self.assertTrue((SRC / "looks" / f"{comp}.tsx").is_file(), comp)
            self.assertIn(f'import {{ {comp}', root)
        for comp in ("Chiaroscuro", "Axis"):
            self.assertIn(f"export const {comp.upper()}_FRAMES = 750;", (SRC / "looks" / f"{comp}.tsx").read_text())
        self.assertEqual({reel_looks.FRAMES[look] for look in ("chiaroscuro", "axis")}, {750})
        self.assertEqual({reel_looks.FRAMES[look] for look in reel_looks.LOOKS if look not in ("chiaroscuro", "axis")}, {480})
        self.assertIn("export const DURATION = 480;", (SRC / "look.ts").read_text())
        self.assertIn("width={W} height={H} fps={FPS}", root)

    def test_the_packages_are_pinned_to_the_versions_the_looks_were_approved_on(self):
        pkg = json.loads((reel_looks.REEL_LOOKS / "package.json").read_text())
        deps = {**pkg["dependencies"], **pkg["devDependencies"]}
        self.assertTrue(all(re.fullmatch(r"\d+\.\d+\.\d+", v) for v in deps.values()), deps)
        self.assertEqual({deps[k] for k in ("remotion", "@remotion/cli", "@remotion/noise", "@remotion/media-utils")}, {"4.0.538"})
        lock = json.loads((reel_looks.REEL_LOOKS / "package-lock.json").read_text())
        self.assertEqual(lock["packages"][""]["dependencies"], pkg["dependencies"])
        self.assertEqual(lock["packages"]["node_modules/remotion"]["version"], "4.0.538")

    def test_every_face_and_texture_is_in_the_public_dir_and_each_font_has_its_ofl_text(self):
        fonts = (SRC / "fonts.ts").read_text()
        files = re.findall(r'"([A-Za-z-]+[^"]*\.(?:woff2|ttf))"', fonts)
        self.assertEqual(len(files), 9)
        public = reel_looks.REEL_LOOKS / "public"
        for f in files:
            self.assertTrue((public / "fonts" / f).is_file(), f)
            family = re.match(r"[A-Za-z]+", f).group(0)
            self.assertTrue((public / "fonts" / f"{family}-OFL.txt").is_file(), f"{family}-OFL.txt beside {f}")
        for look, names in (("axis", [f"grain-{k}.png" for k in range(6)]),
                            ("chiaroscuro", ["canvas.png", "haze-0.png", "haze-1.png", *[f"grain-{k}.png" for k in range(6)]])):
            for n in names:
                self.assertTrue((public / "textures" / look / n).is_file(), f"{look}/{n}")

    def test_every_slot_is_a_prop_and_every_file_a_look_reads_is_in_its_public_dir(self):
        """A look's pictures are its props, the post's photos and the fillers, each slot its own (2026-11-08, night); it
        reads only the reel's own files (its props name them) and the fonts and textures beside it, never a folder of its
        own."""
        text = "\n".join(p.read_text() for p in SRC.rglob("*.ts*"))
        named = re.findall(r"staticFile\(`([^`$]*)", text)
        self.assertTrue(named)
        self.assertEqual({n.split("/")[0] for n in named}, {"fonts", "textures"})
        self.assertNotIn("isSample", text)
        look = (SRC / "look.ts").read_text()
        for prop in ("photos: Photo[];", "fillers: Photo[];", "wordPhotos: [number, number, number];", "music?: Track"):
            self.assertIn(prop, look)
        for gone in ("climax", "ending", "tiles"):
            self.assertNotRegex(look, rf"\b{gone}\??:", "every picture is a slot of its own: no photo held back, no second list")

    def test_the_powers_of_ten_layout_draws_on_the_looks_frame(self):
        layout = (SRC / "looks" / "powersOfTenLayout.ts").read_text()
        self.assertIn("export const W = 1080, H = 1920;", layout)
        self.assertIn("export const W = 1080, H = 1920;", (SRC / "look.ts").read_text())
        self.assertNotRegex(layout, r"(?m)^import (?!type )", "only type imports: Node runs it as it is")

    def test_the_music_is_the_suites_choice_started_on_its_second_at_its_rate_faded_out_over_half_a_second(self):
        tsx = (SRC / "music.tsx").read_text()
        for words in ("staticFile(track.src)", "track.start * FPS", "playbackRate={track.rate}", "durationInFrames - 15"):
            self.assertIn(words, tsx)
        for look in (SRC / "looks").glob("*.tsx"):
            self.assertIn("<Music track={p.music} />", look.read_text(), look.name)


class Words(IsolatedCase):
    def test_ten_sets_of_his_lines_each_with_a_hook_two_lines_and_a_marquee(self):
        self.assertEqual(sorted(reel_lines.SETS), list(range(1, 11)))
        for n, s in reel_lines.SETS.items():
            self.assertEqual(len(s.open), 2)
            for text in (*s.open, s.open_sub, *s.line1, *s.line2, s.marquee):
                self.assertTrue(text.strip(), n)
                self.assertNotRegex(text, r"[$\d]", "no price, no number")
        self.assertEqual(reel_lines.SETS[1].open, ("Every", "room."))
        self.assertEqual(reel_lines.COUNTER, {"label": "Every moment", "value": "1", "unit": "take"})

    def test_a_set_comes_round_again_only_after_the_others(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        self.assertEqual(reel_lines.choose(conn), 1)

        def used(n, at):
            db.insert(conn, "content_queue", kind="photo", photo_ids="[]", targets="[]", caption="{}", status="draft",
                      rule_report=json.dumps({"design": "reel", "lines": n}), created_at=at, updated_at=at)
        for n in range(1, 11):
            used(n, f"2026-11-{n:02d}T10:00:00+00:00")
        self.assertEqual(reel_lines.choose(conn), 1, "every set used: the one used longest ago")
        used(1, "2026-11-20T10:00:00+00:00")
        self.assertEqual(reel_lines.choose(conn), 2)
        picks = []
        for k in range(10):
            n = reel_lines.choose(conn)
            picks.append(n)
            used(n, f"2026-12-{k + 1:02d}T10:00:00+00:00")
        self.assertEqual(sorted(picks), list(range(1, 11)), "ten reels in a row: ten different sets")

    def test_each_beat_word_is_its_own_photos_confirmed_room(self):
        """Chris, 2026-11-08: "The screen shot says each award and they are portraits"."""
        b = reel_lines.beats([None, "main_stage", "portrait", None, "reception", "candid"])
        self.assertEqual(b.photos, (1, 2, 4))
        self.assertEqual(b.words, ("Main stage.", "Portraits.", "Reception."))          # his labels (2026-11-08)
        self.assertEqual(b.stack, "Main stage · portraits · reception")
        b = reel_lines.beats(["main_stage", "main_stage", "backstage", "main_stage", "breakout"])
        self.assertEqual((b.photos, b.words), ((0, 2, 4), ("Main stage.", "Backstage.", "Breakouts.")), "three different words first")
        b = reel_lines.beats(["portrait"] * 5)
        self.assertEqual((b.photos, b.words, b.stack), ((0, 1, 2), ("Portraits.",) * 3, "Portraits"), "the same room: its word again")
        with self.assertRaises(reel_lines.TooFewRooms):
            reel_lines.beats(["main_stage", None, "portrait", None, "not_a_room"])

    def test_axis_says_chriss_own_three_words_on_its_first_three_portraits(self):
        """Chris, 2026-11-08: "Poise." "Light." "Presence." for every Axis reel: it is all portraits, and the room words
        would all be "Portraits."."""
        b = reel_lines.beats(["portrait", None, "portrait", "portrait", "portrait"], "axis")
        self.assertEqual((b.photos, b.words, b.stack), ((0, 1, 2), ("Poise.", "Light.", "Presence."), "Portraits"))
        b = reel_lines.beats(["portrait", "main_stage", None, "reception"], "axis")
        self.assertEqual((b.words, b.stack), (("Poise.", "Light.", "Presence."), "Portraits · main stage"),
                         "the stack label is still the rooms of its three photos, a photo with none adding nothing")
        self.assertEqual(reel_lines.beats([None, None, None, "portrait", None], "axis").stack, "Portraits", "else the rest's")
        with self.assertRaises(reel_lines.TooFewRooms):
            reel_lines.beats([None] * 5, "axis")            # nothing confirmed: the label says nothing it does not know
        self.assertEqual(reel_lines.beats(["portrait"] * 3).words, ("Portraits.",) * 3, "every other look keeps the room words")
        from convention_social import house_brief
        self.assertEqual(set(reel_lines.BEAT_WORDS), set(house_brief.KEYS))


class Photos(IsolatedCase):
    """Chris, 2026-11-08: "it's event photography mainly - the gallery in the last one should remain all portraits. It's
    also fine to have one or two portrait other ones"."""
    def test_two_portraits_at_most_in_any_look_but_axis_which_takes_portraits_only(self):
        p, s = {"shot_type": "portrait"}, {"shot_type": "main_stage"}
        for look in reel_looks.LOOKS:
            rule = reel_looks.photo_rule(look)
            if look == "axis":
                self.assertTrue(rule(p, [p] * 6))
                self.assertFalse(rule(s, []))
            else:
                self.assertTrue(rule(p, [s, p]))
                self.assertFalse(rule(p, [p, s, p]), look)
                self.assertTrue(rule(s, [p, p, s]))
        self.assertTrue(reel_looks.fits("darkroom", [s, p, s, p]))
        self.assertFalse(reel_looks.fits("darkroom", [p, s, p, p]))
        self.assertFalse(reel_looks.fits("darkroom", [s, s, s]), "fewer than the look's least")
        self.assertFalse(reel_looks.fits("darkroom", [s] * 7), "more than the look shows: a photo it would never show")
        self.assertTrue(reel_looks.fits("axis", [p] * 6))
        self.assertFalse(reel_looks.fits("axis", [p] * 5), "the doorway, three words and the burst of two at least")
        self.assertFalse(reel_looks.fits("axis", [p] * 5 + [s]))
        self.assertTrue(reel_looks.can_fill("axis", [p] * 8 + [s]))
        self.assertFalse(reel_looks.can_fill("axis", [p] * 7 + [s] * 9), "Axis needs its eight portraits in the pool")

    def test_the_picker_keeps_a_looks_rule_and_takes_its_count(self):
        rows = [{"id": k, "folder_id": f"f{k}", "taken_at": None, "shot_type": "portrait" if k % 2 else "candid"} for k in range(20)]
        picker = content.Picker(rows, "reel", style="darkroom")
        for r in picker.candidates():
            picker.take(r)
        self.assertEqual(len(picker.taken), reel_looks.TAKES["darkroom"])
        self.assertEqual(sum(1 for r in picker.taken if r["shot_type"] == "portrait"), 2)
        picker = content.Picker(rows, "reel", style="axis")
        for r in picker.candidates():
            picker.take(r)
        self.assertEqual([r["shot_type"] for r in picker.taken], ["portrait"] * 8)
        picker = content.Picker(rows, "reel", style="loop")
        self.assertEqual((picker.need, picker.rule), (content.TAKES["reel"], None), "a 3D style: no rule, as before")


def filler_files(root: Path, n: int, shapes=((3000, 2000),), tag="f") -> list[reel_looks.Filler]:
    """`n` approved photos with a copy here, as reel_looks.fillers gives them: JPEG files, each its own colour."""
    out = []
    for k in range(n):
        path = root / f"{tag}{k}.img"
        Image.new("RGB", shapes[k % len(shapes)], (0, 100 + k % 100, k // 100)).save(path, "JPEG")
        out.append(reel_looks.Filler(1000 + k, path))
    return out


class Props(IsolatedCase):
    """Every slot a picture of its own (Chris, 2026-11-08, night): the post's photos in the look's photo slots, fillers in
    the rest, exactly as many as the look shows."""
    def setUp(self):
        super().setUp()
        self.plan = reel_looks.Plan(4, track(self.root))

    def props(self, look, photos, fillers=None):
        public = self.root / f"{look}-public"
        if fillers is None:
            fillers = filler_files(self.root, reel_looks.SLOTS[look].fillers + reel_looks.TAKES[look] - len(photos))
        return reel_looks.props(look, photos, plan=self.plan, fillers=fillers, public=public), public

    def test_too_few_or_too_many_photos_or_fillers_stop_the_reel(self):
        shots = [photo(r) for r in ("main_stage", "candid", "reception", None, "breakout", "backstage")]
        with self.assertRaises(ValueError, msg="a filler short"):
            self.props("darkroom", shots, filler_files(self.root, reel_looks.SLOTS["darkroom"].fillers - 1))
        with self.assertRaises(ValueError, msg="a filler over"):
            self.props("weather", shots, filler_files(self.root, 2))
        with self.assertRaises(ValueError, msg="more of the post's photos than the look shows"):
            self.props("section", shots)
        with self.assertRaises(ValueError, msg="fewer than its least"):
            self.props("manifesto", shots[:3])

    def test_the_words_sit_on_the_photos_whose_rooms_they_name_word_photos_first(self):
        rooms = [None, "main_stage", None, "portrait", "reception", "candid"]
        p, public = self.props("darkroom", [photo(r, focus=(0.3, 0.2) if k == 0 else reel_looks.DEFAULT_FOCUS)
                                            for k, r in enumerate(rooms)])
        self.assertEqual(p["words"], ["Main stage.", "Portraits.", "Reception."])
        self.assertEqual(p["wordPhotos"], [0, 1, 2], "in Darkroom the first word's photo is the print: the word photos lead")
        self.assertEqual([(x["fx"], x["fy"]) for x in p["photos"]][3], (0.3, 0.2),
                         "the post's hero, with no confirmed room, follows them with the art director's focus")
        self.assertEqual({(x["fx"], x["fy"]) for x in p["photos"][:3]}, {reel_looks.DEFAULT_FOCUS})
        self.assertEqual(p["stackLabel"], "Main stage · portraits · reception")
        self.assertEqual(p["counter"], reel_lines.COUNTER)
        s = reel_lines.SETS[4]
        self.assertEqual((p["open"], p["openSub"], p["line1"], p["line2"], p["marquee"]),
                         (list(s.open), s.open_sub, list(s.line1), list(s.line2), s.marquee))
        for k, key in (("business", "Event Caliber"), ("town", "DC · MD · VA"), ("phone", "eventcaliber.com"),
                       ("cta", "Request a quote"), ("accent", "#00E1FF"), ("accent2", "#F3F3F1"),
                       ("kicker", "event & conference photography")):
            self.assertEqual(p[k], key)
        for gone in ("climax", "ending", "tiles"):
            self.assertNotIn(gone, p)
        self.assertEqual((p["photos"][0]["w"], p["photos"][0]["h"]), (1400, 933))
        self.assertEqual(len(p["fillers"]), reel_looks.SLOTS["darkroom"].fillers, "the contact sheet's other frames")
        self.assertTrue(all((public / x["src"]).is_file() for x in p["photos"] + p["fillers"]))
        self.assertEqual(p["music"], {"src": "music.mp3", "start": 17.986, "rate": 120 / 114.96})
        self.assertEqual((public / "fonts").resolve(), (reel_looks.REEL_LOOKS / "public" / "fonts").resolve())
        self.assertEqual((public / "textures").resolve(), (reel_looks.REEL_LOOKS / "public" / "textures").resolve())

    def test_no_word_without_a_confirmed_room(self):
        with self.assertRaises(reel_lines.TooFewRooms):
            self.props("titles", [photo(r) for r in ("main_stage", None, None, "portrait", None, None)])

    def test_a_look_that_opens_on_the_hero_puts_its_words_on_the_three_after_it(self):
        """Chiaroscuro's calling is the hero alone; seen again under an arch it would be shown twice."""
        def coloured(k, room):
            return reel_looks.LookPhoto(Image.new("RGB", (3000, 2000), (30 * k, 0, 0)), room)
        rooms = ("main_stage", "candid", None, "reception", None, "portrait", "backstage")
        p, public = self.props("chiaroscuro", [coloured(k, r) for k, r in enumerate(rooms)])

        def mark(x):
            with Image.open(public / x["src"]) as im:
                return round(im.getpixel((im.width // 2, im.height // 2))[0] / 30)
        self.assertEqual(p["wordPhotos"], [1, 2, 3])
        self.assertEqual([mark(x) for x in p["photos"]], [0, 1, 3, 5, 2, 4, 6], "the hero, its three word photos, then the rest")
        self.assertEqual(len(p["fillers"]), reel_looks.SLOTS["chiaroscuro"].fillers, "the studies and the montage")

    def test_axis_is_eight_portraits_its_last_two_the_burst_and_thirteen_fillers(self):
        shots = [reel_looks.LookPhoto(Image.new("RGB", (2000, 3000) if k % 2 else (3000, 2000), (30 * k, 0, 0)), "portrait")
                 for k in range(8)]
        p, public = self.props("axis", shots)

        def mark(x):                      # which of the eight a written photo is, by its colour
            with Image.open(public / x["src"]) as im:
                return round(im.getpixel((im.width // 2, im.height // 2))[0] / 30)
        self.assertEqual([mark(x) for x in p["photos"]], list(range(8)),
                         "the hero in the doorway, the words on the next three, the first and last doors, the burst of two")
        self.assertEqual(p["wordPhotos"], [1, 2, 3], "Poise, Light and Presence on three portraits besides the hero")
        self.assertEqual(p["words"], ["Poise.", "Light.", "Presence."], "Chris's own three for every Axis reel")
        self.assertEqual(p["stackLabel"], "Portraits")
        self.assertEqual(len(p["fillers"]), 13, "the gallery's eleven walls and the two middle doors")
        self.assertEqual((p["photos"][7]["w"], p["photos"][7]["h"]), (933, 1400))

    def test_a_photo_slot_the_post_had_no_photo_for_takes_a_filler_axiss_burst_stays_last(self):
        shots = [reel_looks.LookPhoto(Image.new("RGB", (2000, 3000), (30 * k, 0, 0)), "portrait") for k in range(7)]
        p, public = self.props("axis", shots, filler_files(self.root, 14, ((2000, 3000),)))

        def mark(x):
            with Image.open(public / x["src"]) as im:
                r, g, _ = im.getpixel((im.width // 2, im.height // 2))
                return "filler" if g > 50 else round(r / 30)
        self.assertEqual([mark(x) for x in p["photos"]], [0, 1, 2, 3, 4, "filler", 5, 6])
        self.assertEqual(len(p["fillers"]), 13)

    def test_the_mosaic_is_given_only_the_fillers_it_places(self):
        """It lays as many rings as cover the frame: on tall photos it places 38 of 40, and with fewer it may lay a ring
        less, so it is laid out again on the ones it placed until it shows every filler it is given."""
        asked = []

        def placed(props_list):
            k = len(props_list[0]["fillers"])
            asked.append(k)
            return [{40: 30, 30: 28}.get(k, k)]
        self.assertEqual(reel_looks.fit_mosaic({"fillers": list(range(40))}, placed), 28)
        self.assertEqual(asked, [40, 30, 28])
        shots = [photo(r) for r in ("main_stage", "candid", "reception", None, "breakout", "backstage")]
        p, public = self.props("powersoften", shots, filler_files(self.root, 40, ((1000, 2000),)))
        self.assertLess(len(p["fillers"]), 40, "tall fillers: fewer fit")
        self.assertEqual(reel_looks.mosaic_fillers([p]), [len(p["fillers"])], "each one it keeps is on the mosaic")
        self.assertEqual(len(list((public / "photos").glob("f*.jpg"))), len(p["fillers"]), "and no file of one it left off")
        with self.assertRaises(ValueError, msg="too thin a mosaic for every word to hold"):
            reel_looks.props("powersoften", shots, plan=self.plan, fillers=filler_files(self.root, 40),
                             public=self.root / "thin-public", placed=lambda ps: [5])

    def test_powers_of_ten_rings_its_mosaic_with_the_fillers_it_places_with_their_shapes(self):
        shapes = ((3000, 2000), (2000, 3000))
        p, public = self.props("powersoften", [photo(r) for r in ("main_stage", "candid", "reception", None, "breakout", "backstage")],
                               filler_files(self.root, 40, shapes))
        kept = len(p["fillers"])
        self.assertGreaterEqual(kept, reel_looks.SLOTS["powersoften"].fillers_from)
        self.assertEqual([(t["w"], t["h"]) for t in p["fillers"]], ([(1400, 933), (933, 1400)] * 20)[:kept], "in order, each its shape")
        self.assertTrue(all((public / t["src"]).is_file() for t in p["fillers"]))


class Render(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.plan = reel_looks.Plan(2, track(self.root, start=9.5, rate=1.0))
        self.runs = []

    def remotion(self, cmd, **kw):
        """The seam for `npx remotion render`: records what it was asked and writes the mp4, like Remotion would."""
        self.runs.append((cmd, kw))
        public = Path(next(a for a in cmd if a.startswith("--public-dir=")).split("=", 1)[1])
        self.seen = {"props": json.loads((public / "props.json").read_text()), "files": sorted(p.name for p in (public / "photos").iterdir()),
                     "public": sorted(p.name for p in public.iterdir())}
        Path(cmd[5]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def test_the_render_runs_the_looks_composition_on_its_own_public_dir_and_leaves_the_mp4_alone(self):
        out = self.root / "posts" / "7-reel-weather.mp4"
        got = reel_looks.render("weather", [photo(r) for r in ("main_stage", "candid", "reception", None, "backstage", None, None)],
                                plan=self.plan, out=out, run=self.remotion)
        self.assertEqual(got, reel_looks.Reel(out, reel_looks.STILL_FRAMES["weather"]))
        cmd, kw = self.runs[0]
        self.assertEqual(cmd[1:6], ["remotion", "render", "src/index.ts", "Weather", str(out)])
        for flag in (f"--timeout={reel_looks.ASSET_WAIT_MS}", f"--concurrency={reel_looks.CONCURRENCY}", "--log=error"):
            self.assertIn(flag, cmd)
        self.assertEqual(kw, {"cwd": str(reel_looks.REEL_LOOKS), "timeout": reel_looks.RENDER_TIMEOUT})
        self.assertEqual(self.seen["files"], [f"p{k}.jpg" for k in range(7)], "Weather's seven photo slots; it takes no fillers")
        self.assertEqual(self.seen["props"]["fillers"], [])
        self.assertEqual(self.seen["public"], ["fonts", "music.mp3", "photos", "props.json", "textures"])
        self.assertEqual(self.seen["props"]["music"], {"src": "music.mp3", "start": 9.5, "rate": 1.0})
        self.assertEqual(out.read_bytes(), b"mp4")
        self.assertFalse((self.root / "posts" / "7-reel-weather-public").exists(), "the public dir is gone once the mp4 is made")

    def test_the_reel_says_which_fillers_it_showed(self):
        fill = filler_files(self.root, 3)
        got = reel_looks.render("manifesto", [photo(r) for r in ("main_stage", "candid", "reception", "breakout", None, None)],
                                plan=self.plan, out=self.root / "m.mp4", fillers=fill, run=self.remotion)
        self.assertEqual(got.fillers, tuple(fill), "the seventh photo slot's and the photomontage's two: to the wall's record")
        self.assertEqual((len(self.seen["props"]["photos"]), len(self.seen["props"]["fillers"])), (7, 2))

    def test_the_reel_says_only_the_fillers_its_mosaic_placed(self):
        """Powers of Ten's mosaic places 30 of its 40 here: the reel shows (and the wall records) the photo slot's filler
        and those 30, never the ten it left off."""
        fill = filler_files(self.root, 41)
        got = reel_looks.render("powersoften", [photo(r) for r in ("main_stage", "candid", "reception", None, "breakout")],
                                plan=self.plan, out=self.root / "p.mp4", fillers=fill, run=self.remotion,
                                windows=lambda ps: [[[0, 100], [100, 200], [200, 300]]],
                                placed=lambda ps: [min(len(ps[0]["fillers"]), 30)])
        self.assertEqual(len(self.seen["props"]["fillers"]), 30)
        self.assertEqual(got.fillers, tuple(fill[:31]), "the sixth photo slot's filler and the 30 placed, not the ten left off")

    def test_a_remotion_failure_says_what_it_said_and_leaves_nothing_behind(self):
        def failing(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "Error: Composition 'Axis' timed out\nat render\n")
        with self.assertRaises(RuntimeError) as e:
            reel_looks.render("axis", [photo("portrait") for _ in range(8)], plan=self.plan, out=self.root / "x.mp4",
                              fillers=filler_files(self.root, 13), run=failing)
        self.assertIn("remotion stopped with code 1", str(e.exception))
        self.assertIn("timed out", str(e.exception))
        self.assertFalse((self.root / "x.mp4").exists())
        self.assertFalse((self.root / "x-public").exists())

    def test_a_reel_needs_a_known_look_its_track_and_its_words_and_runs_nothing_without_them(self):
        shots = [photo(r) for r in ("main_stage", "candid", "reception", None)]
        with self.assertRaises(ValueError):
            reel_looks.render("loop", shots, plan=self.plan, out=self.root / "x.mp4", run=self.remotion)
        with self.assertRaises(ValueError):
            reel_looks.render("titles", shots, plan=None, out=self.root / "x.mp4", run=self.remotion)
        with self.assertRaises(reel_lines.TooFewRooms):
            reel_looks.render("titles", [photo(None)] * 4, plan=self.plan, out=self.root / "x.mp4", fillers=filler_files(self.root, 5),
                              run=self.remotion)
        with self.assertRaises(ValueError):
            reel_looks.render("axis", [photo("portrait")] * 4, plan=self.plan, out=self.root / "x.mp4", run=self.remotion)
        self.assertEqual(self.runs, [])
        self.assertFalse((self.root / "x-public").exists())

    def test_the_render_is_run_in_its_own_process_group(self):
        import inspect
        self.assertIs(inspect.signature(reel_looks.render).parameters["run"].default, reels3d.run_remotion)

    def test_a_reel_made_before_is_taken_as_it_is(self):
        given = self.root / "made" / "02-manifesto.mp4"
        given.parent.mkdir()
        given.write_bytes(b"finished")
        out = reel_looks.take_video(given, self.root / "posts" / "9-reel-manifesto.mp4")
        self.assertEqual(out.read_bytes(), b"finished")
        self.assertEqual(reel_looks.take_video(out, out), out, "taken again in place: left as it is")
        with self.assertRaises(RuntimeError):
            reel_looks.take_video(self.root / "nothing.mp4", self.root / "posts" / "x.mp4")


class Frames(IsolatedCase):
    def test_the_cover_is_frame_zero_and_the_stills_the_frames_its_words_are_on(self):
        for look in reel_looks.LOOKS:
            self.assertEqual((reel_looks.COVER_FRAME[look], reel_looks.COVER_MS[look]), (0, 0))
            self.assertTrue(reel_looks.STILL_FRAMES[look])
            self.assertTrue(all(0 < f < reel_looks.FRAMES[look] for f in reel_looks.STILL_FRAMES[look]))
        self.assertEqual(reel_looks.STILL_FRAMES["axis"], (188, 203, 218), "one word a beat, each across its own portrait")

    def test_the_cover_and_stills_are_cut_from_the_reel_with_our_metadata(self):
        video = self.root / "r.mp4"
        subprocess.run([reel.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=8:r=30",
                        "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True, timeout=120)
        m = image_meta.ImageMeta(title="t", description="d", keywords=("a",))
        saved = reel_looks.stills("axis", video, out_dir=self.root / "stills", meta=m)
        self.assertEqual([p.name for p in saved], ["axis-000.jpg", "axis-188.jpg", "axis-203.jpg", "axis-218.jpg"])
        with Image.open(saved[0]) as im:
            self.assertEqual(im.size, (64, 64))


class PowersOfTenWords(IsolatedCase):
    """Chris, 2026-11-08: no word is ever left off. Powers of Ten shows a word in a band beside its own photo while the band
    can be read; on an end-to-end reel one word never came on screen. Each of the three must hold at least WORD_HOLD frames
    (1.5 s), whatever the photos' shapes: checked on the layout the look draws with, by Node (reel-looks/word-windows.mjs)."""
    SHAPES = (1 / 2, 9 / 16, 2 / 3, 3 / 4, 4 / 5, 1, 5 / 4, 4 / 3, 3 / 2, 16 / 9, 2)      # every camera format, 1:2 to 2:1

    def case(self, rng):
        def shaped(name):
            a = rng.choice(self.SHAPES)
            return {"src": name, "w": 1400, "h": round(1400 / a)} if a >= 1 else {"src": name, "w": round(1400 * a), "h": 1400}
        slots = reel_looks.SLOTS["powersoften"]
        return {"photos": [shaped(f"photos/p{k}.jpg") for k in range(slots.photos)],
                "fillers": [shaped(f"photos/f{k}.jpg") for k in range(slots.fillers)], "wordPhotos": [0, 1, 2]}

    def test_every_word_holds_a_second_and_a_half_beside_its_photo_for_any_photo_shapes(self):
        rng = random.Random(20261108)
        cases = [self.case(rng) for _ in range(400)]
        found = reel_looks.word_windows(cases)
        self.assertEqual(len(found), len(cases))
        short = [(c, w) for c, w in zip(cases, found) if len(w) < 3 or any(b - a < reel_looks.WORD_HOLD for a, b in w[:3])]
        self.assertEqual(short, [], "a word that would not hold 1.5 s beside its photo")

    def test_the_art_director_sees_each_word_in_the_middle_of_its_time_and_a_word_that_would_not_hold_stops_the_reel(self):
        props_ = {"photos": [], "fillers": [], "wordPhotos": [0, 1, 2]}
        self.assertEqual(reel_looks.frames_of("powersoften", props_, lambda ps: [[[0, 100], [45, 160], [90, 300]]]), (50, 102, 195))
        with self.assertRaises(RuntimeError):
            reel_looks.frames_of("powersoften", props_, lambda ps: [[[0, 100], [45, 80], [90, 300]]])
        with self.assertRaises(RuntimeError):
            reel_looks.frames_of("powersoften", props_, lambda ps: [[[0, 100], [45, 160]]])
        self.assertEqual(reel_looks.frames_of("titles", props_, lambda ps: 1 / 0), reel_looks.STILL_FRAMES["titles"])


class Briefs(IsolatedCase):
    def test_the_art_director_is_told_the_look_and_that_each_word_must_match_its_photo(self):
        for look in reel_looks.LOOKS:
            told = reel_looks.brief(look)
            self.assertIn(reel_looks.ON_PURPOSE[look], told)
            if look == "axis":
                self.assertIn("Its three beat words (Poise. Light. Presence.) are the photographer's own", told)
                self.assertNotIn(reel_looks.BRIEF_WORDS, told, "Chris's own words, not a room: never a fault for not naming one")
                continue
            self.assertIn("each beat word must name what its own photo plainly shows; a word that does not match its photo is "
                          "a fault", told.lower())
            self.assertIn(f"in the {reel_looks.NAMES[look]} look", told)
            self.assertTrue(told.startswith(f"{2 + len(reel_looks.STILL_FRAMES[look])} pictures of"), told[:40])
            graded = "The grade and the light on the photos are the look" in told
            self.assertEqual(graded, look in ("chiaroscuro", "axis"), "only the two looks Chris named grade and light his photos")
        self.assertTrue(reel_looks.brief("titles", card=False).startswith("2 pictures of a 16 second reel"))
        self.assertTrue(reel_looks.brief("powersoften", stills=3).startswith("5 pictures of"), "told the frames it gets")
        self.assertIn("25 second reel", reel_looks.brief("axis"))


class Fillers(IsolatedCase):
    """A look's other slots take more of his approved photos with a copy here, drawn as a 3D reel's wall is
    (reels3d.fillers): in rotation, one per room per shoot, never the post's own, a copy of its pictures or a frame of
    its moments (Chris, 2026-11-08, night: no picture twice in a reel)."""
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        cache = config.get_config().data_root / "photos"
        cache.mkdir(parents=True, exist_ok=True)
        self.ids = {}
        for k in range(12):                                   # twelve shoots, a portrait and a stage photo in each
            for room in ("portrait", "main_stage"):
                pid = event_photo(self.conn, f"t{k}{room}", kind="business", final="business", quality=5, folder=f"f{k}")
                self.conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=?", (room, pid))
                self.conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))
                Image.new("RGB", (30, 20), (k, 0, 0)).save(cache / f"t{k}{room}.img", "JPEG")
                self.ids[(k, room)] = pid
        # a frame of the post's own moment: the same shoot, five minutes after the post's photo
        sibling = event_photo(self.conn, "t0moment", kind="business", final="business", quality=5, folder="f0")
        self.conn.execute("UPDATE classifications SET shot_type='candid' WHERE photo_id=?", (sibling,))
        then = datetime.strptime(db.one(self.conn, "SELECT taken_at FROM photos WHERE id=?", (self.ids[(0, "portrait")],))["taken_at"],
                                 "%Y:%m:%d %H:%M:%S")
        self.conn.execute("UPDATE photos SET thumbnail_link='t', taken_at=? WHERE id=?",
                          ((then + timedelta(minutes=5)).strftime("%Y:%m:%d %H:%M:%S"), sibling))
        Image.new("RGB", (30, 20), (0, 9, 0)).save(cache / "t0moment.img", "JPEG")

    def rows(self, *keys):
        return [{"id": self.ids[key], "shot_type": key[1]} for key in keys]

    def test_the_mosaic_takes_approved_photos_mostly_not_portraits_never_the_posts_own(self):
        with mock.patch.object(reel_looks, "MOSAIC_PORTRAITS", 3):
            got = reel_looks.fillers(self.conn, "powersoften", self.rows((0, "portrait")))
        names = [f.path.name for f in got]
        self.assertEqual(sum(1 for n in names if "portrait" in n), 3, "at most MOSAIC_PORTRAITS portraits")
        self.assertEqual(len(got), 3 + 12, "every stage photo and three portraits")
        self.assertNotIn("t0portrait.img", names, "never the post's own photo")
        self.assertNotIn("t0moment.img", names, "nor a frame of its moment")
        self.assertEqual(db.rows(self.conn, "SELECT * FROM photo_use"), [], "recorded once a reel shows them (Drafts)")

    def test_axiss_fillers_are_portraits_one_a_shoot_never_the_posts_own(self):
        own = self.rows(*[(k, "portrait") for k in range(8)])
        got = reel_looks.fillers(self.conn, "axis", own)
        self.assertEqual(sorted(f.path.name for f in got), sorted(f"t{k}portrait.img" for k in range(8, 12)),
                         "the four portraits the post does not hold, one a shoot; fewer than Axis needs stop the reel")

    def test_any_other_look_keeps_the_reel_at_two_portraits_and_asks_for_a_slot_the_post_has_no_photo_for(self):
        own = self.rows((0, "main_stage"), (1, "portrait"), (2, "main_stage"), (3, "main_stage"), (4, "main_stage"), (5, "main_stage"))
        got = reel_looks.fillers(self.conn, "manifesto", own)
        self.assertEqual(len(got), reel_looks.SLOTS["manifesto"].fillers + 1, "the photomontage's two and the seventh photo slot")
        self.assertLessEqual(sum(1 for f in got if "portrait" in f.path.name), 1, "one portrait in the post: one more at most")
        self.assertEqual(reel_looks.fillers(self.conn, "weather", own + self.rows((6, "main_stage"))), [], "Weather takes none")

    def test_with_no_camera_time_a_sitting_cannot_be_told_so_its_shoot_and_shot_type_stay_off(self):
        """A moment is told by the camera's clock. A post photo with none keeps fillers off its whole shoot and shot type,
        and a photo with none never fills beside a post photo of its shoot and shot type: either could be another frame
        of the same sitting."""
        cache = config.get_config().data_root / "photos"
        own_untimed, own_timed = self.ids[(3, "portrait")], self.ids[(5, "portrait")]
        self.conn.execute("UPDATE photos SET taken_at=NULL WHERE id=?", (own_untimed,))
        for name, folder, timed in (("t3sitting", "f3", True), ("t5untimed", "f5", False)):
            pid = event_photo(self.conn, name, kind="business", final="business", quality=5, folder=folder)
            self.conn.execute("UPDATE classifications SET shot_type='portrait' WHERE photo_id=?", (pid,))
            self.conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))
            if not timed:
                self.conn.execute("UPDATE photos SET taken_at=NULL WHERE id=?", (pid,))
            Image.new("RGB", (20, 30), (9, 0, 0)).save(cache / f"{name}.img", "JPEG")
        own = [{"id": own_untimed, "shot_type": "portrait"}, {"id": own_timed, "shot_type": "portrait"}]
        names = {f.path.name for f in reel_looks.fillers(self.conn, "axis", own)}
        self.assertNotIn("t3sitting.img", names, "the post's photo of that shoot has no time: its sitting cannot be told")
        self.assertNotIn("t5untimed.img", names, "no time of its own, beside the post's photo of that shoot")
        self.assertIn("t6portrait.img", names, "another shoot's portrait still fills")

    def test_a_photo_another_post_still_to_go_out_holds_never_fills(self):
        """#90's tiles held photos of #80, #85 and #86, all scheduled (2026-11-09): that post would show them again."""
        now = db.utcnow()
        for status, key in (("scheduled", (6, "main_stage")), ("draft", (7, "main_stage")), ("published", (8, "main_stage"))):
            db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps([self.ids[key]]), targets="[]", caption="{}",
                      status=status, rule_report="{}", created_at=now, updated_at=now)
        names = {f.path.name for f in reel_looks.fillers(self.conn, "powersoften", self.rows((0, "portrait")))}
        self.assertNotIn("t6main_stage.img", names, "in a scheduled post")
        self.assertNotIn("t7main_stage.img", names, "in a draft")
        self.assertIn("t8main_stage.img", names, "a post that has gone out is the rotation's to bring round again")

    def test_a_copy_of_the_posts_picture_filed_in_another_shoot_never_fills(self):
        shown = self.ids[(5, "main_stage")]
        self.conn.execute("UPDATE photos SET picture=? WHERE id=?", (shown, shown))
        copy = event_photo(self.conn, "export-of-5", kind="business", final="business", quality=5, folder="exports")
        self.conn.execute("UPDATE photos SET picture=?, thumbnail_link='t' WHERE id=?", (shown, copy))
        got = reel_looks.fillers(self.conn, "powersoften", [{"id": copy, "shot_type": "main_stage"}])
        self.assertNotIn("t5main_stage.img", [f.path.name for f in got], "the post's picture, by another file")


class Rotation(IsolatedCase):
    """content.reel_style: the five 3D styles as before while REEL_LOOKS is off; on, the ten looks join, each with a track
    that suits it, never the same look or style twice in a row, the learner's weights leaning the chance."""
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def suits(self, *looks):
        for look in looks:
            music.add(self.conn, f"{look}.wav", tone(), **dict(RECORD, title=look), looks=[look])

    def styles(self, last=None, n=300, **kw):
        seen = []
        for seed in range(n):
            if last is None:
                self.conn.execute("DELETE FROM settings WHERE key=?", (content.REEL_STYLE_KEY,))
            else:
                settings.set(self.conn, content.REEL_STYLE_KEY, last)
            seen.append(content.reel_style(self.conn, random.Random(seed), **kw))
        return seen

    def test_switched_off_only_the_five_3d_styles(self):
        self.suits(*reel_looks.LOOKS)
        self.assertFalse(reel_looks.enabled())
        self.assertEqual(set(self.styles()), set(reels3d.STYLES))
        for value in ("off", "yes", "1", "true"):
            os.environ["REEL_LOOKS"] = value
            config.reset()
            self.assertFalse(reel_looks.enabled(), value)

    def test_switched_on_the_looks_with_a_track_join_and_never_the_same_twice(self):
        os.environ["REEL_LOOKS"] = "on"
        config.reset()
        self.suits("darkroom", "axis", "weather")
        self.assertEqual(set(self.styles()), {*reels3d.STYLES, "darkroom", "axis", "weather"}, "a look with no track never")
        self.assertEqual(set(self.styles("darkroom")), {*reels3d.STYLES, "axis", "weather"})
        self.assertEqual(set(self.styles("loop")), {*reels3d.STYLES, "darkroom", "axis", "weather"} - {"loop"})
        self.assertEqual(set(self.styles(fits=lambda look: look != "axis")), {*reels3d.STYLES, "darkroom", "weather"},
                         "a look the photos do not allow is left out")
        last = None
        for seed in range(60):
            style = content.reel_style(self.conn, random.Random(seed))
            self.assertNotEqual(style, last)
            last = style

    def test_a_learned_weight_leans_the_choice_and_never_removes_a_look(self):
        os.environ["REEL_LOOKS"] = "on"
        config.reset()
        self.suits("darkroom", "titles")
        settings.set(self.conn, learner.WEIGHTS_KEY, json.dumps({"reel_look": {"darkroom": 1.5, "titles": 0.5, "wall": 9.0}}))

        class Dice:
            def choices(self, population, weights):
                self.seen = dict(zip(population, weights))
                return [population[0]]
        dice = Dice()
        content.reel_style(self.conn, dice)
        self.assertEqual(dice.seen, {"wall": 1.5, "loop": 1.0, "ring": 1.0, "gallery": 1.0, "orbit": 1.0, "darkroom": 1.5,
                                     "titles": 0.5}, "each its learned weight, held to 1.5; none left out")
        seen = self.styles(n=2000)
        self.assertEqual(set(seen), {*reels3d.STYLES, "darkroom", "titles"})
        self.assertGreater(seen.count("darkroom"), 2 * seen.count("titles"))


# ------------------------------------------------------------------ a reel in a look, drafted on the daily road

FRIDAY = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)          # tomorrow is Saturday: an event day
# the photos of the drafts below: (drive id, the sorter's shot type, the room the final check confirmed)
LIBRARY = [("s1", "main_stage", "main_stage"), ("s2", "reception", "reception"), ("s3", "candid", "candid"),
           ("s4", "breakout", "breakout"), ("s5", "backstage", None), ("s6", "stage_panel", None),
           *[(f"p{k}", "portrait", "portrait") for k in range(1, 9)]]


class RoomsClient(FinalClient):
    """Claude's final check, answering each photo's own room and shot type (`current`: the photo being read)."""
    def create(self, **kw):
        self.calls += 1
        shot, room = next((s, r) for d, s, r in LIBRARY if d == self.current)
        t = types.SimpleNamespace(type="text", text=json.dumps({"possible_minor": False, "personal_details": [], "summary": "ok",
                                                                "shot_type": shot, "event_kind": "business", "room": room or "none"}))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=1500, output_tokens=100))


class LookCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,facebook,pinterest,linkedin"
        os.environ["REEL_LOOKS"] = "on"
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="fe", name="Con", first_seen_at=now, last_seen_at=now)
        self.ids = {}
        for k, (did, shot, room) in enumerate(LIBRARY):
            pid = db.insert(self.conn, "photos", drive_id=did, name=f"{did}.jpg", folder_id="fe", width=3000, height=2000,
                            clearance="cleared", clearance_at=now, first_seen_at=now, last_seen_at=now)
            db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name="Liberty Summit",
                      is_convention=1, quality=5 - k % 3, possible_minor=0, personal_details="[]", space="exterior", residential=0,
                      empty_room=0, sharp=1, light=4, moment=4, shot_type=shot, classified_at=now)
            db.insert(self.conn, "final_checks", photo_id=pid, possible_minor=0, summary="ok", model="t",
                      checked_at=now, shot_type=shot, room=room)
            self.ids[did] = pid
        self.tracks = {look: self.conn.execute("SELECT file FROM music_tracks WHERE id=?", (
            music.add(self.conn, f"{look}.wav", tone(), **dict(RECORD, title=look), looks=[look], start_s=2.0),)).fetchone()[0]
            for look in ("darkroom", "axis", "manifesto")}
        self.made, self.fetched = [], []
        for fake in (mock.patch.object(reel_looks, "render", self.fake_render()), mock.patch.object(reel_looks, "stills", self.fake_stills),
                     mock.patch.object(reels3d, "render", side_effect=AssertionError("a look is never a 3D reel"))):
            fake.start()
            self.addCleanup(fake.stop)

    def fake_render(self, fail=False):
        def job(look, photos, *, plan, out, fillers=()):
            self.made.append({"look": look, "rooms": [p.room for p in photos], "focus": [p.focus for p in photos], "plan": plan,
                              "fillers": list(fillers)})
            if fail:
                raise RuntimeError("remotion stopped with code 1: no reel made")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"mp4")
            return reel_looks.Reel(out, reel_looks.STILL_FRAMES[look], tuple(fillers))
        return job

    def fake_stills(self, look, video, *, out_dir, meta=None, frames=None):   # the cover first, then the word frames
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = [out_dir / f"{look}-{f:03d}.jpg" for f in (reel_looks.COVER_FRAME[look], *(frames or reel_looks.STILL_FRAMES[look]))]
        for p in paths:
            Image.new("RGB", (1080, 1920), (20, 20, 20)).save(p)
        return paths

    def ctx(self, live=False):
        if live:
            os.environ["AI_MONTHLY_CAP_USD"] = "5"
            os.environ["AI_MODEL"] = "template"
            config.reset()
        config.get_config().ensure_dirs()
        return runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), not live, 0)

    def fetch(self, row):
        self.fetched.append(row["drive_id"])
        if getattr(self, "client", None) is not None:
            self.client.current = row["drive_id"]
        return jpeg_bytes(seed=len(self.fetched), size=(3000, 2000))

    def last(self):
        row = db.rows(self.conn, "SELECT * FROM content_queue ORDER BY id")[-1]
        return row, json.loads(row["rule_report"]), json.loads(row["render_paths"]), json.loads(row["photo_ids"])

    def shot_types(self, ids):
        return [db.one(self.conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (i,))["shot_type"] for i in ids]


class Drafts(LookCase):
    def draft(self, look, **kw):
        with mock.patch.object(content, "reel_style", lambda conn, rng=None, **k: look):
            return content.draft_one(self.ctx(**kw), self.fetch, now=FRIDAY, **({"check_client": self.client} if kw else {}),
                                     **({"art_client": self.eye} if kw else {}))

    def test_a_reel_in_a_look_takes_its_rule_its_track_and_its_words_and_says_so_on_the_draft(self):
        asked, wall = [], reel_looks.Filler(self.ids["s6"], Path("f.img"))

        def fill(conn, look, rows, n=None, candidates=None):
            if n is not None:                      # Supply.enough: is there enough for the look
                return [wall] * n
            asked.append((look, [r["id"] for r in rows]))
            return [wall]
        with mock.patch.object(reel_looks, "fillers", fill):
            line = self.draft("darkroom")
        self.assertIn("reel with", line)
        row, meta_, renders, ids = self.last()
        self.assertEqual((meta_["design"], meta_["reel"], meta_["music"], meta_["lines"]), ("reel", "darkroom", self.tracks["darkroom"], 1))
        self.assertEqual(len(ids), reel_looks.TAKES["darkroom"])
        self.assertLessEqual(self.shot_types(ids).count("portrait"), 2, "two portraits at most (Chris, 2026-11-08)")
        [made] = self.made
        self.assertEqual(made["look"], "darkroom")
        rooms = content.checked_rooms(self.conn, ids)
        self.assertEqual(made["rooms"], [rooms[i] for i in ids], "each photo carries the room its final check confirmed")
        self.assertEqual(made["focus"][0], (0.5, 0.42), "the hero at the art director's focus")
        self.assertEqual((made["plan"].lines, made["plan"].track.file, made["plan"].track.start), (1, self.tracks["darkroom"], 2.0))
        self.assertEqual(asked, [("darkroom", ids)], "the look's fillers, for the post's own photos")
        self.assertEqual(made["fillers"], [wall], "and the render is given them")
        self.assertEqual([r["photo_id"] for r in db.rows(self.conn, "SELECT photo_id FROM photo_use WHERE surface='grid'")],
                         [wall.id], "the fillers it showed, recorded on the wall so they rotate")
        self.assertEqual(sorted(renders), ["2:3", "9:16", "cover", "linkedin", "stills"])
        self.assertEqual(Path(renders["cover"][0]).name, "darkroom-000.jpg", "the cover is the look's first frame")
        self.assertEqual([Path(p).name for p in renders["stills"]], ["darkroom-352.jpg"])

    def test_axis_takes_portraits_only_eight_of_them(self):
        self.draft("axis")
        _, meta_, _, ids = self.last()
        self.assertEqual((meta_["design"], meta_["reel"]), ("reel", "axis"))
        self.assertEqual(self.shot_types(ids), ["portrait"] * 8)
        self.assertEqual(self.made[0]["rooms"], ["portrait"] * 8)

    def test_a_look_that_cannot_be_made_is_a_carousel_of_the_same_photos_and_says_why(self):
        with mock.patch.object(reel_looks, "render", self.fake_render(fail=True)):
            line = self.draft("manifesto")
        self.assertIn("the reel could not be made", line)
        _, meta_, renders, ids = self.last()
        self.assertEqual(meta_["design"], "carousel")
        self.assertIn("remotion stopped", meta_["reel_failed"])
        self.assertNotIn("reel", meta_, "no look to learn from: the post went out as a carousel")
        self.assertEqual(len(renders["4:5"]), len(ids) + 2)

    def test_the_art_director_is_told_the_look_and_sees_the_cover_the_card_and_each_words_frame(self):
        from tests.test_reels import Eye
        self.client, self.eye = RoomsClient({}), Eye([say("pass", notes="Each word matches its photo.")])
        self.draft("axis", live=True)
        row, meta_, _, _ = self.last()
        self.assertEqual((row["status"], meta_["reel"], meta_["art"]["verdict"]), ("draft", "axis", "pass"))
        [(images, told)] = self.eye.looks
        self.assertEqual(len(images), 5, "the cover, the 2:3 card and the three frames Axis's words are on")
        self.assertEqual(told, reel_looks.brief("axis") + "\n\nReview this post.")

    def test_the_look_and_its_lines_are_kept_when_the_draft_is_drawn_again(self):
        self.draft("darkroom")
        row, meta_, _, _ = self.last()
        paths, _ = content.redraw(self.conn, row, dict(meta_))
        self.assertEqual([m["look"] for m in self.made], ["darkroom", "darkroom"], "never re-rendered as another style")
        self.assertEqual(self.made[1]["plan"].lines, meta_["lines"])
        self.assertEqual(self.made[1]["plan"].track.file, meta_["music"])
        self.assertIn("9:16", paths)


class QueueReel(LookCase):
    """Chris, 2026-11-08, of the ten finished preview reels: "You can use those as posts. The images were fine"."""
    DAY = date(2026, 11, 12)

    def setUp(self):
        super().setUp()
        self.video = self.root / "made" / "02-manifesto.mp4"
        self.video.parent.mkdir()
        self.video.write_bytes(b"the finished reel")
        mock.patch.object(reel_looks, "render", side_effect=AssertionError("a queued reel is never rendered again")).start()
        self.addCleanup(mock.patch.stopall)

    def queue(self, photos=("s1", "s2", "s3", "p1"), day=None, **kw):
        return content.queue_reel(self.ctx(), self.fetch, video=self.video, look="manifesto", photo_ids=[self.ids[d] for d in photos],
                                  day=day or self.DAY, track_file=self.tracks["manifesto"], **kw)

    def test_a_finished_reel_is_queued_as_the_days_post_on_the_daily_road(self):
        with mock.patch.object(notify, "push") as push:
            qid, line = self.queue()
        self.assertTrue(qid, line)
        self.assertEqual(push.call_count, 1, "pinged like any draft")
        row, meta_, renders, ids = self.last()
        self.assertEqual((row["id"], row["status"]), (qid, "draft"))
        self.assertEqual(ids, [self.ids[d] for d in ("s1", "s2", "s3", "p1")], "the photos in his order, the hero first")
        self.assertEqual((meta_["for_day"], meta_["design"], meta_["reel"], meta_["music"], meta_["reel_given"]),
                         (self.DAY.isoformat(), "reel", "manifesto", self.tracks["manifesto"], str(self.video)))
        self.assertNotIn("source", meta_, "it is the day's post")
        self.assertEqual(Path(renders["9:16"][0]).read_bytes(), b"the finished reel")
        self.assertNotEqual(Path(renders["9:16"][0]), self.video, "copied in beside the post's other renders")
        self.assertEqual(Path(renders["cover"][0]).name, "manifesto-000.jpg")
        self.assertEqual([Path(p).name for p in renders["stills"]], ["manifesto-295.jpg"])
        for key in ("2:3", "linkedin"):
            self.assertTrue(Path(renders[key][0]).is_file(), key)
        used = {r["photo_id"] for r in db.rows(self.conn, "SELECT photo_id FROM photo_use WHERE surface='post'")}
        self.assertEqual(used, set(ids), "the rotation's record, as for any post")
        self.assertEqual(content.already_drafted(self.conn, self.DAY), True)

    def test_a_day_that_has_its_post_is_refused_and_nothing_is_queued(self):
        self.queue(quiet=True)
        qid, line = self.queue(photos=("s4", "p2", "p3", "p4"), quiet=True)
        self.assertIsNone(qid)
        self.assertEqual(line, f"not queued: a post for {self.DAY} is already drafted")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) AS n FROM content_queue")["n"], 1)

    def test_a_photo_that_fails_stops_it_with_the_reason_and_nothing_is_queued(self):
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (self.ids["s3"],))
        qid, line = self.queue(quiet=True)
        self.assertIsNone(qid)
        self.assertTrue(line.startswith(f"not queued: photo {self.ids['s3']} is "), line)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) AS n FROM content_queue")["n"], 0)
        for kw, said in (({"look": "loop"}, "no reel look 'loop'"), ({"track_file": "gone.mp3"}, "no music track 'gone.mp3'"),
                         ({"video": self.root / "none.mp4"}, "no reel at")):
            args = {**dict(video=self.video, look="manifesto", photo_ids=[self.ids["s1"]], day=self.DAY,
                           track_file=self.tracks["manifesto"]), **kw}
            self.assertIn(said, content.queue_reel(self.ctx(), self.fetch, **args)[1])

    def test_quiet_sends_no_ping(self):
        with mock.patch.object(notify, "push") as push:
            qid, _ = self.queue(quiet=True)
        self.assertTrue(qid)
        push.assert_not_called()

    def test_a_queued_reel_drawn_again_is_the_same_file_and_the_same_look(self):
        self.queue(quiet=True)
        row, meta_, renders, _ = self.last()
        paths, _ = content.redraw(self.conn, row, dict(meta_))
        self.assertEqual(paths["9:16"], renders["9:16"])
        self.assertEqual(Path(paths["9:16"][0]).read_bytes(), b"the finished reel")
        self.assertEqual(meta_["reel"], "manifesto")

    def test_the_publisher_gives_instagram_each_looks_first_frame_as_the_cover(self):
        from convention_social.agents import publisher
        self.queue(quiet=True)
        row, _, _, _ = self.last()
        self.assertEqual(publisher.reel_cover_ms(row), 0)
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"design": "reel", "reel": "ring"}), row["id"]))
        self.assertEqual(publisher.reel_cover_ms(db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (row["id"],))),
                         reels3d.COVER_MS["ring"])

    def test_the_command_queues_it_and_says_what_it_did(self):
        from convention_social import cli
        local = lambda ctx: self.fetch            # noqa: E731  the photos as they would come from Drive
        out = io.StringIO()
        args = ["queue-reel", str(self.video), "manifesto", "--photos", ",".join(str(self.ids[d]) for d in ("s1", "s2", "s3", "p1")),
                "--day", self.DAY.isoformat(), "--track", self.tracks["manifesto"], "--quiet"]
        with mock.patch.object(cli, "drive_fetch", local), contextlib.redirect_stdout(out):
            code = cli.main(args)
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("drafted post #", out.getvalue())
        out = io.StringIO()
        with mock.patch.object(cli, "drive_fetch", local), contextlib.redirect_stdout(out):
            code = cli.main(args)
        self.assertEqual(code, 1)
        self.assertIn(f"not queued: a post for {self.DAY} is already drafted", out.getvalue())


class Designed(LookCase):
    def test_a_designed_reel_chooses_its_look_first_and_takes_the_looks_photos(self):
        from zoneinfo import ZoneInfo
        from convention_social.agents import designed
        from convention_social.ai import claude
        from tests.test_content import ArtClientAny
        self.client = RoomsClient({})
        settings.set_dry_run(self.conn, "content", False)          # the designed lane follows the content lane's switch
        ten = datetime.now(ZoneInfo(config.get_config().timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        with mock.patch.object(content, "reel_style", lambda conn, rng=None, **k: "axis"), \
                mock.patch.object(designed, "next_design", lambda conn, has_music: "reel"), \
                mock.patch.object(content.notify, "push_result", return_value="sent"):
            line = designed.draft(self.ctx(live=True), self.fetch, now=ten, check_client=self.client,
                                  art_client=ArtClientAny([say("pass")] * 3), drafter=claude.TemplateDrafter())
        self.assertIn("reel with 8 photo(s)", line)
        _, meta_, _, ids = self.last()
        self.assertEqual((meta_["source"], meta_["reel"], meta_["music"]), ("designed", "axis", self.tracks["axis"]))
        self.assertEqual(self.shot_types(ids), ["portrait"] * 8, "Axis takes portraits only")
