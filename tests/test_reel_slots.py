"""No picture twice in a reel (Chris, 2026-11-08, night, on the Axis reel: "there are duplicates! The women in red at the
end you just used is also in the gallery on the left side! The masters wouldt be this sloppy!"). The rule pinned where
CI can see it, from the sources: no look cycles its photos, each look shows exactly the slots the suite gives it, and a
slot it was not given stops its render. The renders that prove it frame by frame run on the Mini (`ccs reel-check`,
render/reel_check.py); here, the check's own arithmetic."""
from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest import mock

from PIL import Image

from convention_social import music
from convention_social.render import reel_check, reel_looks, reels3d
from tests._base import IsolatedCase

SRC = reel_looks.REEL_LOOKS / "src"
LOOK_FILES = {look: SRC / "looks" / f"{comp}.tsx" for look, comp in reel_looks.COMPOSITION.items()}
# a photo list (or a list drawn from one) indexed round and round: `p.photos[i % p.photos.length]`, `others[k % others.length]`
CYCLING = re.compile(r"%\s*\(?\s*(?:p\.)?(?:photos|fillers|pics|others|order|ending|tiles|shots|roll)\b[\w.]*\.length")
DECLARED = re.compile(r"export const SLOTS: Slots = \{ photos: (\d+), fillers: (\d+)(?:, fillersFrom: (\d+))? \};")


class NoLookCyclesItsPhotos(IsolatedCase):
    def test_no_look_source_cycles_photos_or_reads_a_slot_but_through_its_accessor(self):
        sources = [*(SRC / "looks").glob("*.ts*"), SRC / "look.ts", SRC / "slots.ts"]
        self.assertEqual(len(sources), 13)
        for path in sources:
            text = path.read_text()
            self.assertNotRegex(text, CYCLING, f"{path.name} cycles its photos: a slot short of a picture shows one again")
            self.assertNotRegex(text, r"(?:photoAt|fillerAt)\(p,[^)]*%", f"{path.name}: a slot index taken round")
            for gone in ("heldForClimax", "climaxIndex", "p.climax", "p.ending", "p.tiles"):
                self.assertNotIn(gone, text, f"{path.name}: every picture is a slot of its own, none held back or listed twice")
        for look, path in LOOK_FILES.items():
            self.assertNotRegex(path.read_text(), r"p\.(?:photos|fillers)(?!\.length)\b",
                                f"{path.name} reads a picture without photoAt or fillerAt, which stop the render on a missing slot")

    def test_the_mosaics_layout_reads_only_the_slots_it_is_given(self):
        layout = (SRC / "looks" / "powersOfTenLayout.ts").read_text()
        self.assertIn("if (!Number.isInteger(i) || i < 0 || i >= p.photos.length) throw new Error(", layout)
        self.assertIn("p.fillers.map(", layout, "every filler once, in the mosaic's outer rings")


class EachLookShowsItsSlots(IsolatedCase):
    def test_each_looks_declared_slots_are_the_suites(self):
        for look, path in LOOK_FILES.items():
            text = path.read_text()
            found = DECLARED.search(text)
            self.assertIsNotNone(found, f"{path.name} declares its SLOTS")
            least = int(found.group(3)) if found.group(3) else None
            self.assertEqual(reel_looks.Slots(int(found.group(1)), int(found.group(2)), least), reel_looks.SLOTS[look], path.name)
            self.assertIn(f'checkSlots(p, SLOTS, "{reel_looks.COMPOSITION[look]}");', text, f"{path.name} checks its props first")
        self.assertEqual(set(reel_looks.SLOTS), set(reel_looks.LOOKS))
        for look in reel_looks.LOOKS:
            self.assertEqual(reel_looks.TAKES[look], reel_looks.SLOTS[look].photos, "a look takes as many photos as it shows")
            self.assertLessEqual(reel_looks.LEAST[look], reel_looks.TAKES[look])

    def test_reel_looks_props_hands_each_look_exactly_its_slots(self):
        plan = reel_looks.Plan(1, music.LookTrack(reel_check.silence(self.root / "s.wav", 1), 0.0, 1.0))
        for look in reel_looks.LOOKS:
            photos, n_fillers = reel_check.cards(look)
            for own in (reel_looks.LEAST[look], reel_looks.TAKES[look]):
                fillers = []
                for k in range(n_fillers + reel_looks.TAKES[look] - own):
                    path = self.root / f"{look}-{own}-f{k}.jpg"
                    Image.new("RGB", (30, 20) if k % 4 != 3 else (20, 30), "black").save(path, "JPEG")
                    fillers.append(reel_looks.Filler(k, path))
                public = self.root / f"{look}-{own}"
                p = reel_looks.props(look, photos[:own], plan=plan, fillers=fillers, public=public)
                slots = reel_looks.SLOTS[look]
                self.assertEqual(len(p["photos"]), slots.photos, (look, own))
                self.assertTrue((slots.fillers_from or n_fillers) <= len(p["fillers"]) <= n_fillers, (look, own))
                self.assertEqual(sorted(f.name for f in (public / "photos").iterdir()),
                                 sorted(x["src"].split("/")[1] for x in p["photos"] + p["fillers"]), "no file it does not show")
                self.assertEqual(len(set(p["wordPhotos"])), 3)
                self.assertTrue(all(0 <= i < len(p["photos"]) for i in p["wordPhotos"]), look)
                self.assertNotIn("check", p, "the card check's seam is never in a reel the suite makes")
                files = [x["src"] for x in p["photos"] + p["fillers"]]
                self.assertEqual(len(set(files)), len(files), "every slot its own file")
                shutil.rmtree(public)

    def test_a_slot_a_look_was_not_given_stops_its_render(self):
        """reel-looks/src/slots.ts, run as the looks run it: a slot past the props, or props of another count, throw."""
        script = """
const s = await import(process.argv[1]);
const p = { photos: [{ src: "a" }, { src: "b" }, { src: "c" }], fillers: [{ src: "f" }], wordPhotos: [0, 1, 2] };
const tries = { photo: () => s.photoAt(p, 3), filler: () => s.fillerAt(p, 1), below: () => s.photoAt(p, -1),
  fraction: () => s.photoAt(p, 1.5), given: () => s.photoAt(p, 2).src, count: () => s.checkSlots(p, { photos: 4, fillers: 1 }, "Look"),
  words: () => s.checkSlots({ ...p, wordPhotos: [0, 0, 1] }, { photos: 3, fillers: 1 }, "Look"),
  exact: () => s.checkSlots(p, { photos: 3, fillers: 1 }, "Look") ?? "held" };
const out = {};
for (const [k, f] of Object.entries(tries)) { try { out[k] = f(); } catch (e) { out[k] = "stopped: " + e.message; } }
// the card check: the probe says where slot 2 is asked for; lit at that place it is its white card, elsewhere as given
const heard = [], say = console.log;
const jpg = { ...p, photos: [{ src: "p0.jpg" }, { src: "p1.jpg" }, { src: "p2.jpg" }] };
let site = "";
out.checked = [];
for (const mode of ["probe", "light", "plain"]) {
  const check = mode === "probe" ? { probe: true } : mode === "light" ? { light: { kind: "photos", index: 2, site } } : undefined;
  console.log = (line) => heard.push(line);
  out.checked.push(s.photoAt({ ...jpg, check }, 2).src);   // asked for from this one place each time
  console.log = say;
  if (mode === "probe") site = heard[0].split(" ")[3];
}
out.elsewhere = s.photoAt({ ...jpg, check: { light: { kind: "photos", index: 2, site } } }, 2).src;
out.heard = heard;
console.log(JSON.stringify(out));
"""
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node runs the looks; it is on every machine that runs this suite")
        r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script,
                            str(SRC / "slots.ts")], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["photo"], "stopped: no photo slot 3: the props hold 3")
        self.assertEqual(got["filler"], "stopped: no filler slot 1: the props hold 1")
        self.assertTrue(got["below"].startswith("stopped:") and got["fraction"].startswith("stopped:"))
        self.assertEqual(got["given"], "c")
        self.assertEqual(got["count"], "stopped: Look shows 4 photos and 1 fillers; the props hold 3 and 1")
        self.assertTrue(got["words"].startswith("stopped: Look: the three words go on three different photos"))
        self.assertEqual(got["exact"], "held")
        self.assertEqual(len(got["heard"]), 1)
        self.assertRegex(got["heard"][0], r"^REELCHECK photos 2 \S+$", "the probe names the slot and its place")
        self.assertEqual(got["checked"], ["p2.jpg", "p2-lit.jpg", "p2.jpg"], "lit only where the probe heard it")
        self.assertEqual(got["elsewhere"], "p2.jpg", "another place asking for the same slot stays as given")

    def test_every_look_has_passed_the_card_check_on_its_sources_as_they_are(self):
        """The card check runs once a look, not for each reel: a look added, or one whose code changes, is red here until
        `ccs reel-check LOOK --record` passes on the Mini and records the hash of its sources (reel-looks/card-checks.json)."""
        book = json.loads(reel_check.REGISTRY.read_text())
        for look in reel_looks.LOOKS:
            self.assertIn(look, book, f"{look} has never passed the card check: run `ccs reel-check {look} --record` on the Mini")
            self.assertEqual(book[look]["source"], reel_check.source_hash(look),
                             f"{look}'s code changed since its card check passed: run `ccs reel-check {look} --record` on the Mini")
            self.assertEqual((book[look]["repeats"], book[look]["twice_at_once"], book[look]["never_shown"]), (0, 0, 0))

    def test_only_a_pass_on_unchanged_sources_is_recorded(self):
        book = self.root / "card-checks.json"
        source = reel_check.source_hash("weather")
        found = {"look": "weather", "ok": True, "slots": 7, "back_with_nothing_between": []}
        self.assertFalse(reel_check.record({**found, "ok": False}, source, registry=book), "a failed check")
        self.assertFalse(reel_check.record(found, "another hash", registry=book), "sources changed while it ran")
        self.assertFalse(book.exists())
        self.assertTrue(reel_check.record(found, source, registry=book, on="2026-11-09"))
        self.assertEqual(json.loads(book.read_text())["weather"]["source"], source)
        self.assertIn("slots.ts", [p.name for p in reel_check.sources("weather")])
        self.assertIn("powersOfTenLayout.ts", [p.name for p in reel_check.sources("powersoften")])

    def test_the_suite_refuses_a_look_too_few_or_too_many_pictures(self):
        plan = reel_looks.Plan(1, music.LookTrack(reel_check.silence(self.root / "s.wav", 1), 0.0, 1.0))
        photos, n = reel_check.cards("axis")
        with self.assertRaises(ValueError):
            reel_looks.props("axis", photos, plan=plan, fillers=[], public=self.root / "short")
        with self.assertRaises(ValueError):
            reel_looks.props("axis", photos * 2, plan=plan, fillers=[], public=self.root / "over")


def slot(name: str, *places: str) -> reel_check.Slot:
    """A slot from a strip of frames for each place in the look that draws it: "#" on screen, "." off."""
    return reel_check.Slot(name, {f"site{n}": [c == "#" for c in frames] for n, frames in enumerate(places)})


def checked(*slots: reel_check.Slot, flicker: int = 2) -> reel_check.Report:
    report = reel_check.Report("look", list(slots))
    reel_check.find_repeats(report.slots, flicker=flicker)
    return report


class TheCheck(IsolatedCase):
    """render/reel_check.py's arithmetic: a picture's passes on screen, a repeat, twice at once, a slot never shown, and
    a picture back with nothing between (listed for Chris, not failed)."""
    def test_a_pass_sliding_past_the_frames_edge_is_one_pass_but_a_cut_to_another_picture_and_back_is_two(self):
        alone = checked(slot("photo 0", "##..##"), slot("photo 1", "......"))
        self.assertEqual(alone.slots[0].stretches, [(0, 5)], "a gap no wider than FLICKER with nothing on: one pass")
        cut = checked(slot("photo 0", "##..##"), slot("photo 1", "..##.."))
        self.assertEqual(cut.slots[0].stretches, [(0, 1), (4, 5)])
        self.assertEqual(cut.repeats, [("photo 0", 4)], "Chiaroscuro's montage: A, B for a few frames, A again")
        self.assertFalse(cut.ok)
        walls = checked(slot("filler 2", "###.###"), slot("filler 1", "#######"), slot("filler 3", "....###"))
        self.assertEqual((walls.slots[0].stretches, walls.repeats), ([(0, 6)], []),
                         "Axis's wall flickering at the fog's edge while the others stay on, one entering: one pass")
        # Powers of Ten: two neighbouring tiles shrinking past the threshold blink in turn; each still shows a little
        tile = reel_check.Slot("filler 17", {"p": [c == "#" for c in "###.#.."]}, {"p": [.006, .005, .005, .003, .0041, 0, 0]})
        other = reel_check.Slot("filler 20", {"p": [c == "#" for c in "##.#..."]}, {"p": [.006, .005, .002, .0041, 0, 0, 0]})
        blink = checked(tile, other)
        self.assertEqual((blink.slots[0].stretches, blink.repeats), ([(0, 4)], []), "never left the screen: one pass")
        gone = reel_check.Slot("photo 0", {"p": [c == "#" for c in "##..##"]}, {"p": [.5, .5, 0, 0, .5, .5]})
        self.assertEqual(checked(gone, slot("photo 1", "..##..")).repeats, [("photo 0", 4)], "gone, a cut, back: a repeat")

    def test_a_picture_back_after_another_is_a_repeat_after_a_card_or_black_it_is_listed(self):
        report = checked(slot("photo 0", "###............###"), slot("photo 1", "......####........"),
                         slot("photo 2", ".................."), slot("filler 0", "####..........####"))
        self.assertEqual(report.repeats, [("photo 0", 15), ("filler 0", 14)], "photo 1 was shown between")
        self.assertEqual(report.never_shown, ["photo 2"])
        self.assertFalse(report.ok)
        alone = checked(slot("photo 0", "###......###"), slot("photo 1", "...........#"))
        self.assertEqual(alone.repeats, [], "nothing between its two passes: a title card, then the same picture")
        self.assertEqual(alone.back_alone, [("photo 0", 9)], "listed for Chris to rule on")
        self.assertTrue(alone.ok)
        self.assertIn("for Chris: photo 0 back at", reel_check.table([alone]))

    def test_a_picture_on_screen_from_two_places_at_once_fails_and_one_place_cut_by_a_band_does_not(self):
        both = checked(slot("photo 0", "####....", "..####.."), slot("photo 1", "......##"))
        self.assertEqual(both.twice, [("photo 0", (2, 3))], "the triptych and the resolve while the strip moves")
        self.assertFalse(both.ok)
        apart = checked(slot("photo 0", "###.....", ".....###"), slot("photo 1", "...##..."))
        self.assertEqual((apart.twice, apart.repeats), ([], [("photo 0", 5)]), "two places one after another: a repeat")
        banded = checked(slot("photo 0", "######.."), slot("photo 1", "......##"))
        self.assertTrue(banded.ok, "one place, however it is cut, is one picture")

    def test_a_look_that_will_not_render_fails_the_check(self):
        def broken(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "Error: no photo slot 6: the props hold 6\n")
        [report] = reel_check.run_checks(["weather"], work=self.root / "check", run=broken, log=lambda line: None)
        self.assertFalse(report.ok)
        self.assertIn("no photo slot 6", report.error)
        self.assertIn("FAIL", reel_check.table([report]))
        saved = json.loads((self.root / "check" / "reel-check.json").read_text())
        self.assertEqual((saved[0]["look"], saved[0]["ok"]), ("weather", False))
        self.assertFalse((self.root / "check" / "weather").exists(), "the renders go once the look is checked")

    def renders(self, look, places, lit_frames):
        """A render seam: the probe says `places` ({(kind, slot): [site, ...]}) on the console; a light render paints
        white the frames `lit_frames(kind, slot, site)` gives; the black render paints nothing. What each was asked."""
        asked = []

        def fake(cmd, **kw):
            given = json.loads(Path(next(a for a in cmd if a.startswith("--props=")).split("=", 1)[1]).read_text())
            check_ = given.get("check")
            asked.append(check_)
            out = Path(cmd[5])
            out.mkdir(parents=True)
            if check_ and check_.get("probe"):
                said = "\n".join(f"[browser] REELCHECK {kind} {k} {site}" for (kind, k), sites in places.items() for site in sites)
                return subprocess.CompletedProcess(cmd, 0, said, "")
            light = (check_ or {}).get("light")
            on = lit_frames(light["kind"], light["index"], light["site"]) if light else ()
            for f in range(reel_looks.FRAMES[look]):
                Image.new("L", (8, 8), 255 if f in on else 0).save(out / f"element-{f:03d}.png")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return fake, asked

    def test_each_slot_is_rendered_white_at_each_place_the_look_asks_for_it(self):
        frames = reel_looks.FRAMES["section"]
        names = [("photos", k) for k in range(5)] + [("fillers", k) for k in range(3)]
        places = {name: ["10:5<3:1"] for name in names}
        places[("photos", 0)] = ["10:5<3:1", "22:9<7:2"]          # the hero's room, and the exploded view's top plate

        def lit(kind, k, site):
            n = names.index((kind, k)) * 2 + (site == "22:9<7:2")
            return range(frames * n // 16, frames * (n + 1) // 16)
        fake, asked = self.renders("section", places, lit)
        [report] = reel_check.run_checks(["section"], work=self.root / "check", run=fake, log=lambda line: None)
        self.assertTrue(report.ok, reel_check.table([report]))
        self.assertEqual(asked[:2], [{"probe": True}, None], "the probe, then the black look")
        self.assertEqual([a["light"]["site"] for a in asked[2:4]], ["10:5<3:1", "22:9<7:2"], "the hero at each of its places")
        self.assertEqual(len(asked), 2 + 9)
        self.assertEqual(report.as_dict()["places"]["photo 0"], 2)
        self.assertEqual(report.slots[0].stretches, [(0, frames * 2 // 16 - 1)], "its two places one straight after the other: one pass")

    def test_a_slot_the_probe_never_heard_is_never_shown_and_a_silent_probe_fails(self):
        names = [("photos", k) for k in range(7)]
        fake, _ = self.renders("weather", {name: ["1:1"] for name in names[1:]}, lambda kind, k, site: range(k * 60, k * 60 + 30))
        [report] = reel_check.run_checks(["weather"], work=self.root / "a", run=fake, log=lambda line: None)
        self.assertEqual(report.never_shown, ["photo 0"])
        self.assertFalse(report.ok)
        fake, _ = self.renders("weather", {}, lambda kind, k, site: ())
        [report] = reel_check.run_checks(["weather"], work=self.root / "b", run=fake, log=lambda line: None)
        self.assertIn("the probe heard from no slot", report.error)

    def test_the_command_fails_closed(self):
        from convention_social import cli
        passed = reel_check.Report("weather", [reel_check.Slot("photo 0", {"1:1": [True]}, stretches=[(0, 0)])])
        broken = reel_check.Report("axis", [], "remotion stopped with code 1")
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            with mock.patch.object(reel_check, "run_checks", return_value=[passed, broken]):
                self.assertEqual(cli.main(["reel-check", "weather", "axis", "--out", str(self.root / "c")]), 1)
            with mock.patch.object(reel_check, "run_checks", return_value=[passed]) as ran:
                self.assertEqual(cli.main(["reel-check", "weather", "--out", str(self.root / "c")]), 0)
            self.assertEqual(ran.call_args.args[0], ["weather"])
            self.assertEqual(cli.main(["reel-check", "spiral"]), 2, "a look it does not know")
        self.assertIn("FAIL", said.getvalue())

    def test_the_command_names_looks_and_3d_styles_it_knows(self):
        self.assertEqual(reel_check.looks_named([]), [*reel_looks.LOOKS, *reels3d.STYLES])
        self.assertEqual(reel_check.looks_named(["axis", "loop"]), ["axis", "loop"])
        with self.assertRaises(ValueError):
            reel_check.looks_named(["spiral"])
        self.assertEqual(reel_check.registry_of("wall"), reel_check.REGISTRY_3D)
        self.assertEqual(reel_check.registry_of("axis"), reel_check.REGISTRY)
        self.assertEqual([p.name for p in reel_check.sources("loop")], ["Loop.tsx", "lib.tsx", "slots.ts", "Root.tsx", "loopGrid.ts"])


class The3DCheck(IsolatedCase):
    """The 3D styles' card check (render/reel_check.check_style): every slot numbered at every place the probe heard, a
    render for each bit of the numbers and one for its inverse, each pixel read back to its place."""

    def test_a_pixel_reads_its_place_from_the_bits_and_two_places_half_and_half_read_as_none(self):
        def frame(*values):
            im = Image.new("L", (3, 1))
            im.putdata(values)
            return im
        codes, valid = [Image.new("L", (3, 1), 0)], [Image.new("L", (3, 1), 255)]
        # pixel 0: place 2 (bits 0, 1); pixel 1: no card (black in both); pixel 2: places 1 and 2 half and half
        reel_check.bit_planes([frame(0, 0, 128)], [frame(255, 0, 128)], 0, codes, valid)
        reel_check.bit_planes([frame(255, 0, 255)], [frame(0, 0, 0)], 1, codes, valid)
        self.assertEqual(codes[0].getpixel((0, 0)), 2)
        self.assertEqual([valid[0].getpixel((x, 0)) for x in range(3)], [255, 0, 0], "no card, or two cards half and half: no place")
        dim = [Image.new("L", (1, 1), 0)], [Image.new("L", (1, 1), 255)]
        reel_check.bit_planes([Image.new("L", (1, 1), 32)], [Image.new("L", (1, 1), 0)], 0, *dim)
        self.assertEqual(dim[1][0].getpixel((0, 0)), 255, "the loop's grid dimmed to an eighth is still on screen")

    def fake_style(self, places, boxes):
        """A render seam for a 3D style: the probe says `places`; a numbered render paints each place's box white or black
        by its number's bit (the other way round in the inverse), on the frames `boxes` gives for it."""
        asked = []

        def run(cmd, **kw):
            given = json.loads(Path(next(a for a in cmd if a.startswith("--props=")).split("=", 1)[1]).read_text())
            check_ = given["check"]
            asked.append(check_)
            out = Path(cmd[5])
            out.mkdir(parents=True)
            if check_.get("probe"):
                said = "\n".join(f"[browser] REELCHECK {kind} {k} {site}" for (kind, k), sites in places.items() for site in sites)
                return subprocess.CompletedProcess(cmd, 0, said, "")
            for f in range(reels3d.TOTAL):
                im = Image.new("L", (20, 10), 0)
                for (kind, k, site), (frames, box) in boxes.items():
                    white = (check_["codes"][f"{kind} {k} {site}"] >> check_["bit"]) & 1
                    if f in frames and bool(white) != bool(check_.get("inverse")):
                        im.paste(255, box)
                im.save(out / f"element-{f:03d}.png")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return run, asked

    def test_a_3d_style_is_seen_place_by_place_in_twice_its_bits_renders(self):
        places = {("photos", k): ["8:3<2:1"] for k in range(6)}
        places[("photos", 0)] = ["8:3<2:1", "9:7<2:1"]           # a second line drawing the first photo
        boxes = {("photos", k, "8:3<2:1"): (range(k * 60, k * 60 + 50), (k * 3, 0, k * 3 + 3, 10)) for k in range(6)}
        boxes[("photos", 0, "9:7<2:1")] = (range(400, 430), (18, 0, 20, 10))   # back, after the others were shown
        run, asked = self.fake_style(places, boxes)
        [report] = reel_check.run_checks(["gallery"], work=self.root / "check", run=run, log=lambda line: None)
        self.assertEqual(asked[0], {"probe": True})
        self.assertEqual(len(asked), 1 + 2 * 3, "seven places: three bits, each rendered and inverted")
        self.assertEqual(sorted(asked[1]["codes"].values()), list(range(7)))
        self.assertEqual(report.repeats, [("photo 0", 400)])
        self.assertEqual((report.never_shown, report.twice), ([], []))
        self.assertFalse(report.ok)
        self.assertEqual(report.slots[1].stretches, [(60, 109)])
        del boxes[("photos", 0, "9:7<2:1")]
        places[("photos", 0)] = ["8:3<2:1"]
        del places[("photos", 5)], boxes[("photos", 5, "8:3<2:1")]
        run, _ = self.fake_style(places, boxes)
        [report] = reel_check.run_checks(["gallery"], work=self.root / "again", run=run, log=lambda line: None)
        self.assertEqual((report.repeats, report.never_shown), ([], ["photo 5"]), "a slot the probe never heard: never shown")
        self.assertFalse(report.ok)
        self.assertFalse((self.root / "again" / "gallery").exists(), "the renders go once the style is checked")

    def test_a_card_covered_in_the_frame_is_one_pass_and_one_that_left_and_came_back_is_two(self):
        """In 3D a card hides behind a nearer one without leaving the frame (Ring's next card sliding over it, Wall's tiles
        behind the lifted photo): one pass, by the style's own geometry. Ring's old cascade took a card that had fallen
        out of the frame round to the top: out of the frame in the gap, so two passes, a repeat (#76, 12.7 s)."""
        def card(name, frames, inside):
            return reel_check.Slot(name, {"s": [c == "#" for c in frames]}, {"s": [0.01 if c == "#" else 0 for c in frames]},
                                   present=[c == "#" for c in inside])
        other = card("filler 1", "....##....", "##########")
        covered = card("photo 0", "###....###", "##########")
        reel_check.find_repeats([covered, other], flicker=2, still_there=reel_check.STILL_THERE_3D)
        self.assertEqual((covered.stretches, covered.back_at), ([(0, 9)], []), "behind another card, never out of the frame")
        wrapped = card("photo 0", "###....###", "###....###")
        reel_check.find_repeats([wrapped, other], flicker=2, still_there=reel_check.STILL_THERE_3D)
        self.assertEqual(wrapped.back_at, [7], "out of the frame and back: a repeat")

    def test_on_a_still_grid_one_cell_is_one_picture_in_one_place_and_two_cells_fail(self):
        """Loop's grid is one still plane (the coordinator's ruling, 2026-11-09, pending Chris): the camera passing back
        over a card's unchanged cell is one picture in one place; a picture in two cells is shown twice."""
        one = reel_check.Slot("photo 0", {"s": [c == "#" for c in "##....##"]}, {"s": [0.01 if c == "#" else 0 for c in "##....##"]},
                              cells={"0.000,0.000"})
        other = reel_check.Slot("filler 0", {"s": [c == "#" for c in "..####.."]}, cells={"2.410,0.000"})
        report = reel_check.Report("loop", [one, other])
        reel_check.find_repeats(report.slots, flicker=2, still_there=reel_check.STILL_THERE_3D)
        self.assertEqual((one.stretches, report.repeats, report.ok), ([(0, 7)], [], True))
        two = reel_check.Slot("filler 3", {"s": [c == "#" for c in "##......"]}, cells={"0.000,1.920", "2.410,1.920"})
        report = reel_check.Report("loop", [one, other, two])
        reel_check.find_repeats(report.slots, flicker=2, still_there=reel_check.STILL_THERE_3D)
        self.assertEqual(report.in_two_cells, ["filler 3"])
        self.assertFalse(report.ok)
        self.assertIn("filler 3 in two cells of the grid", reel_check.table([report]))
        said = "[browser] REELIN photos 0 0110\n[browser] REELCELL fillers 2 1.250,-1.920\n[browser] REELCELL fillers 2 1.250,-1.920"
        self.assertEqual(reel_check.presence_of(said), {("photos", 0): [False, True, True, False]})
        self.assertEqual(reel_check.cells_of(said), {("fillers", 2): {"1.250,-1.920"}})

    def test_a_3d_style_that_will_not_render_fails_the_check(self):
        def broken(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "Error: Wall shows 6 photos and 57 fillers; the props hold 28 fillers\n")
        [report] = reel_check.run_checks(["wall"], work=self.root / "check", run=broken, log=lambda line: None)
        self.assertFalse(report.ok)
        self.assertIn("the props hold 28 fillers", report.error)
