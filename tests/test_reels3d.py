"""The 3D reels (render/reels3d.py): five styles, the props a post gives them, the render run, the stills cut from
the reel, the fillers around the post's photos. Remotion itself is never run here: the run is a seam."""
from __future__ import annotations

import inspect
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from unittest import mock

from PIL import Image

from convention_social.core import db
from convention_social.render import meta as image_meta, motion, reel, reels3d
from tests._base import IsolatedCase
from tests.test_wedding import event_photo


def shots(n: int) -> list[motion.Shot]:
    rooms = [("MAIN STAGE", "The keynote, from the room."), ("THE CROWD", "In the moment."), ("AFTER DARK", "After the last session."),
             ("PORTRAITS", "Speakers and guests, backstage."), ("EXPO FLOOR", "On the exhibition floor."), ("BACKSTAGE", "Before the doors.")]
    return [motion.Shot(Image.new("RGB", (3000, 2000) if k % 2 else (2000, 3000), (40 + 20 * k, 60, 90)), *rooms[k]) for k in range(n)]


class Styles(IsolatedCase):
    def test_five_styles_each_a_remotion_composition(self):
        self.assertEqual(reels3d.STYLES, ("wall", "loop", "ring", "gallery", "orbit"))
        self.assertEqual(reels3d.COMPOSITION["loop"], "Loop")
        src = (reels3d.REELS3D / "src" / "Root.tsx").read_text()
        for style in reels3d.STYLES:
            self.assertIn(f'<Composition id="{reels3d.COMPOSITION[style]}"', src, f"{style} is registered")

    def test_the_cuts_land_on_the_samples_first_and_last_beats_evenly_between(self):
        self.assertEqual(reels3d.cuts_for(6), [8, 72, 135, 199, 262, 326])
        self.assertEqual(reels3d.cuts_for(4), [8, 114, 220, 326])
        for n in (4, 5, 6):
            cuts = reels3d.cuts_for(n)
            self.assertEqual(len(cuts), n)
            self.assertEqual(cuts, sorted(cuts))
            self.assertLess(cuts[-1], reels3d.TOTAL - reels3d.END, "the last photo has time before the close")
        with self.assertRaises(ValueError):
            reels3d.cuts_for(1)

    def test_every_style_has_its_cover_frame_inside_the_reel(self):
        for style in reels3d.STYLES:
            self.assertEqual(reels3d.COVER_MS[style], round(reels3d.COVER_S[style] * 1000))
            self.assertLess(reels3d.COVER_S[style], reels3d.TOTAL / 30, "inside the fifteen seconds")

    def test_every_style_tells_the_art_director_what_it_puts_on_the_frame_on_purpose(self):
        """Post 33 (2026-10-24): a Loop reel turned back for "a large dark circular artifact over the faces", the loop's
        own glass, which Chris approved as the style. The director is told the style and what is there on purpose, and
        is still asked to judge the photos."""
        self.assertEqual(set(reels3d.ON_PURPOSE), set(reels3d.STYLES))
        for style in reels3d.STYLES:
            told = reels3d.brief(style)
            self.assertIn(f"reel in the {style} style", told)
            self.assertIn(reels3d.ON_PURPOSE[style], told)
            self.assertIn("no motion blur, no fade and no transition", told)
            self.assertIn("every photo is shown as Chris shot and approved it, never a fault in itself", told)   # 2026-11-08
            self.assertTrue(told.startswith(f"{2 + len(reels3d.STILLS_S)} pictures of"), "told how many pictures, cover first")
        loop = reels3d.brief("loop")
        for words in ("oval of liquid glass", "magnifies what is under it, faces included", "not a defect",
                      "the held photo at full brightness while the rest of the grid dims"):
            self.assertIn(words, loop)
        for style, words in (("gallery", "A print hangs dark, its frame with no picture"), ("orbit", "shows a dark face")):
            self.assertIn(words, reels3d.brief(style), "what no picture twice leaves dark is the design, not a fault")
        with self.assertRaises(KeyError):
            reels3d.brief("rooms")


class Render(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.track = self.root / "legendary.mp4"
        self.track.write_bytes(b"isom")
        self.fillers = []
        for k in range(3):
            p = self.root / f"g{k}.img"
            Image.new("RGB", (3000, 2000) if k != 1 else (2000, 3000), (10 * k, 0, 0)).save(p, "JPEG")
            self.fillers.append(reels3d.Filler(100 + k, p))
        self.runs = []

    def remotion(self, cmd, **kw):
        """The seam for `npx remotion render`: records what it was asked and writes the mp4, like Remotion would."""
        self.runs.append((cmd, kw))
        public = Path(next(a for a in cmd if a.startswith("--public-dir=")).split("=", 1)[1])
        self.seen = {"props": json.loads((public / "props.json").read_text()), "files": sorted(p.name for p in (public / "photos").iterdir()),
                     "fonts": (public / "fonts").resolve(), "music": sorted(p.name for p in public.iterdir() if p.name.startswith("music"))}
        Path(cmd[5]).write_bytes(b"mp4")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def test_the_render_gets_the_posts_photos_the_fillers_the_track_and_the_beats_in_its_own_public_dir(self):
        out = self.root / "posts" / "7-loop.mp4"
        asked = []

        def laid(props_list):                     # the loop's grid lays two of the three fillers it is offered
            asked.append(json.loads(json.dumps(props_list)))
            return [2]
        got = reels3d.render("loop", shots(5), out=out, audio=self.track, fillers=self.fillers, run=self.remotion, laid=laid)
        self.assertEqual(got, reels3d.Reel(out, tuple(self.fillers[:2])), "the fillers it showed, to be recorded")
        self.assertEqual(out.read_bytes(), b"mp4")
        self.assertEqual([(f["w"], f["h"]) for f in asked[0][0]["fillers"]], [(1400, 933), (933, 1400), (1400, 933)],
                         "the grid is laid on the files as written")
        cmd, kw = self.runs[0]
        self.assertEqual(cmd[1:6], ["remotion", "render", "src/Root.tsx", "Loop", str(out)])
        self.assertIn("--gl=angle", cmd)
        self.assertIn(f"--timeout={reels3d.ASSET_WAIT_MS}", cmd, "two minutes for the fonts and textures, not Remotion's thirty seconds")
        self.assertEqual(kw["cwd"], str(reels3d.REELS3D))
        props = self.seen["props"]
        self.assertEqual([p["room"] for p in props["photos"]], ["MAIN STAGE", "THE CROWD", "AFTER DARK", "PORTRAITS", "EXPO FLOOR"])
        self.assertEqual(props["photos"][0]["line"], "The keynote, from the room.")
        self.assertEqual((props["photos"][0]["w"], props["photos"][0]["h"]), (933, 1400), "a portrait photo, its long edge 1400")
        self.assertEqual((props["photos"][1]["w"], props["photos"][1]["h"]), (1400, 933))
        self.assertEqual(props["cuts"], reels3d.cuts_for(5))
        self.assertEqual([g["src"] for g in props["fillers"]], ["photos/f0.jpg", "photos/f1.jpg"], "only the ones it lays")
        self.assertEqual(props["music"], "music.mp4")
        self.assertEqual(self.seen["files"], ["f0.jpg", "f1.jpg", "p0.jpg", "p1.jpg", "p2.jpg", "p3.jpg", "p4.jpg"],
                         "no file it does not show")
        self.assertEqual(self.seen["music"], ["music.mp4"])
        self.assertEqual(self.seen["fonts"], (reels3d.REELS3D / "public" / "fonts").resolve(), "the fonts the styles use")
        self.assertFalse((self.root / "posts" / "7-loop-public").exists(), "the public dir is gone once the mp4 is made")

    def test_a_remotion_failure_is_an_error_that_says_what_remotion_said_and_leaves_nothing_behind(self):
        def failing(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "Error: Composition 'Loop' timed out\nat render\n")
        with self.assertRaises(RuntimeError) as e:
            reels3d.render("gallery", shots(4), out=self.root / "x.mp4", audio=self.track, run=failing)
        self.assertIn("remotion stopped with code 1", str(e.exception))
        self.assertIn("timed out", str(e.exception))
        self.assertFalse((self.root / "x.mp4").exists())
        self.assertFalse((self.root / "x-public").exists())

    def test_a_style_is_given_exactly_the_fillers_it_shows_or_no_reel_is_made(self):
        """Chris, 2026-11-08, night: no picture twice in a reel. The wall cycled 28 photos over its tiles; a style short of
        a picture would show one again, and one it does not show was taken for nothing: either way, no reel."""
        self.assertEqual({s: reels3d.fillers_wanted(s, 6) for s in reels3d.STYLES},
                         {"wall": 57, "ring": 24, "gallery": 0, "orbit": 9, "loop": None})
        for style, n, given in (("wall", 6, self.fillers), ("ring", 4, self.fillers), ("gallery", 5, self.fillers[:1])):
            with self.assertRaises(ValueError) as e:
                reels3d.render(style, shots(n), out=self.root / f"{style}.mp4", audio=self.track, fillers=given, run=self.remotion)
            self.assertIn("fillers", str(e.exception))
        with self.assertRaises(ValueError) as e:
            reels3d.render("loop", shots(4), out=self.root / "loop.mp4", audio=self.track, fillers=self.fillers,
                           run=self.remotion, laid=lambda props_list: [None])
        self.assertIn("lays more cards than 3 fillers", str(e.exception))
        self.assertEqual(self.runs, [], "Remotion never asked")
        self.assertEqual([p.name for p in self.root.iterdir() if p.name.endswith("-public") or p.name in
                          ("wall.mp4", "ring.mp4", "gallery.mp4", "loop.mp4")], [], "nothing left behind")
        ring = [reels3d.Filler(k, self.fillers[k % 3].path) for k in range(26)]
        made = reels3d.render("ring", shots(4), out=self.root / "ring.mp4", audio=self.track, fillers=ring, run=self.remotion)
        self.assertEqual(len(made.fillers), 26)
        self.assertEqual(len(self.seen["props"]["fillers"]), 26)

    def test_a_reel_needs_a_known_style_and_its_track(self):
        with self.assertRaises(ValueError):
            reels3d.render("rooms", shots(4), out=self.root / "x.mp4", audio=self.track, run=self.remotion)
        with self.assertRaises(ValueError):
            reels3d.render("wall", shots(4), out=self.root / "x.mp4", audio=None, run=self.remotion)
        self.assertEqual(self.runs, [])

    def test_a_render_past_its_time_is_stopped_with_the_browser_it_started(self):
        """2026-10-24 audit: the timeout's kill reached npx alone, and Remotion's browser could stay on, rendering. The
        render runs in a process group of its own and the whole group is stopped: here a shell standing for npx and a
        sleep standing for the browser."""
        pidfile = self.root / "browser.pid"
        cmd = ["/bin/sh", "-c", f"sleep 60 & echo $! > {pidfile}; wait"]
        with self.assertRaises(RuntimeError) as got:
            reels3d.run_remotion(cmd, cwd=str(self.root), timeout=0.5)
        self.assertEqual(str(got.exception), "remotion ran past 0 s and was stopped, with its browser")
        browser = int(pidfile.read_text())
        for _ in range(50):                               # the orphaned sleep is reaped by launchd within a moment
            try:
                os.kill(browser, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            os.kill(browser, signal.SIGKILL)
            self.fail("the browser kept running after the render was stopped")

    def test_the_render_is_run_in_its_own_process_group(self):
        """Pinned where it is consumed: render() hands Remotion to run_remotion unless a test injects its own runner."""
        self.assertIs(inspect.signature(reels3d.render).parameters["run"].default, reels3d.run_remotion)
        self.assertTrue(reels3d.run_remotion(["/bin/sh", "-c", "exit 3"], cwd=str(self.root), timeout=5).returncode == 3)

    def test_without_node_the_reel_fails_closed_and_says_so(self):
        with mock.patch.object(reels3d.shutil, "which", return_value=None), mock.patch.object(reels3d.Path, "exists", return_value=False):
            with self.assertRaises(RuntimeError) as e:
                reels3d.node_tool("npx")
        self.assertIn("Node is not installed", str(e.exception))


class Stills(IsolatedCase):
    def test_the_cover_and_stills_are_cut_from_the_reel_cover_first_with_our_metadata(self):
        video = self.root / "r.mp4"
        subprocess.run([reel.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=13:r=30",
                        "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True, timeout=120)
        m = image_meta.ImageMeta(title="t", description="d", keywords=("a",))
        saved = reels3d.stills("gallery", video, out_dir=self.root / "stills", meta=m)
        self.assertEqual([p.name for p in saved], ["gallery-01600.jpg", "gallery-06000.jpg", "gallery-10500.jpg"])
        for p in saved:
            with Image.open(p) as im:
                self.assertEqual(im.size, (64, 64))
                r, g, b = im.getpixel((5, 5))
                self.assertTrue(r > 200 and g < 40 and b < 40, "the reel's own frame")
        self.assertEqual(saved[0].name, f"gallery-{reels3d.COVER_MS['gallery']:05d}.jpg", "the cover is the frame Instagram shows")


class Fillers(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def test_the_wall_rotates_and_is_recorded_so_the_next_reel_shows_other_photos(self):
        """Chris, 2026-10-26: "it keeps posting the same photos again." The wall took the strongest 28 approved photos
        in a fixed order, so every reel stood on the same wall. The pick now follows the rotation and the ones a reel
        showed count as a use ("grid", record_wall), so a second wall reaches for the photos the first did not show."""
        from convention_social.core import config
        from convention_social.library import report
        cache = config.get_config().data_root / "photos"
        cache.mkdir(parents=True, exist_ok=True)
        ids = []
        for k in range(8):                                             # two shoots, two rooms each, two photos a room
            pid = event_photo(self.conn, f"g{k}", kind="business", final="business", quality=5, folder=["fa", "fb"][k % 2])
            self.conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=?", (["crowd", "stage_panel"][(k // 2) % 2], pid))
            self.conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))
            Image.new("RGB", (30, 20), (k, k, k)).save(cache / f"g{k}.img", "JPEG")
            ids.append(pid)
        picked = reels3d.fillers(self.conn, "wall", 6, exclude=[])
        first = {f.path.name for f in picked}
        self.assertEqual(len(first), 4, "two shoots, two rooms each: four for the wall (too few for a reel: it refuses one)")
        self.assertEqual(db.rows(self.conn, "SELECT photo_id FROM photo_use"), [], "taken is not shown: recorded once made")
        reels3d.record_wall(self.conn, [f.id for f in picked])
        rows = db.rows(self.conn, "SELECT photo_id, surface, ref FROM photo_use")
        self.assertEqual({r["surface"] for r in rows}, {"grid"})
        self.assertEqual(len(rows), 4, "the wall's photos count as shown")
        self.assertTrue(all(r["ref"].startswith("grid:") for r in rows))
        second = {f.path.name for f in reels3d.fillers(self.conn, "ring", 4, exclude=[])}
        self.assertEqual(len(second), 4)
        self.assertFalse(first & second, "the next wall shows the four the first did not")
        self.assertIn("reel wall", report.use_line(report.use_of(self.conn, ids[:1]).get(ids[0]) or report.use_of(self.conn, ids[1:2]).get(ids[1])))

    def test_every_approved_photo_reaches_the_wall_not_only_the_strongest_600_frames_of_the_library(self):
        """2026-11-09: the wall read the strongest 600 frames of the whole library and kept the approved among them, 42 of
        his approved photos with a copy on the Mini, of 206; the rest of his approved work never reached a wall. His
        rotation is every approved photo (2026-10-14), and a look's fillers are drawn the same way (2026-11-08, night)."""
        from convention_social.core import config
        cache = config.get_config().data_root / "photos"
        cache.mkdir(parents=True, exist_ok=True)
        weak = event_photo(self.conn, "weak", kind="business", final="business", quality=1, light=1, moment=1)
        self.conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (weak,))
        Image.new("RGB", (30, 20), (9, 9, 9)).save(cache / "weak.img", "JPEG")
        now = db.utcnow()
        for k in range(601):                                 # stronger frames he has not decided on, in another shoot each
            pid = db.insert(self.conn, "photos", drive_id=f"strong{k}", name=f"strong{k}.jpg", folder_id="fe", width=3000,
                            height=2000, thumbnail_link="t", first_seen_at=now, last_seen_at=now)
            db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name=f"Event {k}",
                      event_kind="business", is_convention=1, quality=5, possible_minor=0, personal_details="[]",
                      space="exterior", residential=0, empty_room=0, sharp=1, light=5, moment=5, shot_type="crowd",
                      classified_at=now)
        self.assertEqual([f.path.name for f in reels3d.fillers(self.conn, "wall", 6, exclude=[])], ["weak.img"])

    def test_fillers_are_approved_cached_photos_one_per_room_per_shoot_never_the_posts_own(self):
        from convention_social.core import config
        cache = config.get_config().data_root / "photos"
        cache.mkdir(parents=True, exist_ok=True)
        ids = []
        for k in range(8):
            pid = event_photo(self.conn, f"f{k}", kind="business", final="business", quality=5)
            self.conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=?", (["crowd", "stage_panel"][k % 2], pid))
            self.conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))      # sorted from a thumbnail, as the library's are
            if k != 7:                                                          # one has no copy on this machine
                Image.new("RGB", (30, 20), (k, k, k)).save(cache / f"f{k}.img", "JPEG")
            ids.append(pid)
        self.conn.execute("UPDATE classifications SET possible_minor=1 WHERE photo_id=?", (ids[1],))     # no age gate (2026-10-15)
        # the wall is in rotation and equals come by chance (2026-10-26), so the flagged photo is made the strongest
        # of its room: if the flag kept it off, nothing else would
        self.conn.execute("UPDATE classifications SET light=5, moment=5 WHERE photo_id=?", (ids[1],))
        got = [f.path for f in reels3d.fillers(self.conn, "loop", 4, exclude=[ids[0]])]
        self.assertEqual(len(got), 2, "one folder, two rooms: two fillers")
        self.assertIn(cache / "f1.img", got, "an age flag written before the ruling keeps no photo off a reel's wall")
        self.assertTrue(all(p.is_file() for p in got))
        self.assertNotIn(cache / "f0.img", got, "the post's own photo is not a filler")
        self.assertNotIn(cache / "f7.img", got, "a photo without a copy here cannot be rendered")
        self.assertEqual(reels3d.fillers(self.conn, "gallery", 4, exclude=[ids[0]]), [], "gallery shows only the post's own")


SRC = reels3d.REELS3D / "src"
STYLE_FILES = {style: SRC / f"{comp}.tsx" for style, comp in reels3d.COMPOSITION.items()}


def node_run(script: str, *args: str) -> dict:
    """A script run by Node as the styles' own .ts files are (type imports stripped), its JSON answer."""
    import shutil
    node = shutil.which("node")
    assert node, "Node runs the styles; it is on every machine that runs this suite"
    r = subprocess.run([node, "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script, *args],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


class NoPictureTwice(IsolatedCase):
    """Chris, 2026-11-08, night: no picture twice in a reel. Of the five 3D styles the wall cycled 28 photos over its 93
    other tiles, the loop laid about 30 over 77 cells, and the ring's cascade took cards round from the bottom of the
    frame to the top (#76 showed a panel photo at 8.7 s and again at 12.7 s). Pinned here from the sources; proved on a
    render by the card check (`ccs reel-check STYLE`, render/reel_check.py), whose passes CI requires."""

    def test_no_style_cycles_its_pictures_or_draws_one_but_through_its_slot(self):
        for style, path in STYLE_FILES.items():
            text = path.read_text()
            self.assertNotRegex(text, r"%\s*\(?\s*(?:fill|grid|items|tiles)\b|%\s*\w+\.length", f"{path.name} takes its pictures round")
            self.assertNotRegex(text, r"\btex\[|useTextures|\.grid\b|[{,]\s*grid\s*[,}]", f"{path.name} reads a texture but through usePictures")
            self.assertIn("usePictures(", text, path.name)
            self.assertNotRegex(text, r"(?:props|p)\.photos\[", f"{path.name} reads a photo but through photoAt")
        self.assertNotIn("export const useTextures", (SRC / "lib.tsx").read_text(), "the slots are the one way to a texture")
        for style in ("wall", "ring", "gallery", "orbit"):
            self.assertIn("checkFillers(", STYLE_FILES[style].read_text(), f"{style} refuses props of another count")
        self.assertIn("if (laid !== props.photos.length - visit.length + props.fillers.length)", STYLE_FILES["loop"].read_text())

    def test_the_styles_tell_the_check_what_their_geometry_knows(self):
        """A card hidden behind a nearer one while it stays in the frame is one pass, by the style's own geometry (Ring's
        cards, Wall's tiles); Loop's cards keep one cell each on a still grid (the coordinator's ruling, pending Chris)."""
        for style in ("ring", "wall"):
            self.assertIn("reportPresence(p, ", STYLE_FILES[style].read_text(), style)
        self.assertIn("reportCells(props, cards.map(", STYLE_FILES["loop"].read_text())
        wall = STYLE_FILES["wall"].read_text()
        self.assertIn("if (Math.round(f * 2) > FIRST_PASS[s].end) return null;", wall,
                      "a tile gone from the frame once stays dark when the close brings it back")
        gallery = STYLE_FILES["gallery"].read_text()
        self.assertIn('<meshBasicMaterial key="photo"', gallery, "a print's photo never takes on the dark print's colour")
        self.assertIn("n === beat[k] ? {kind: 'photos', index: k} : null", gallery, "a print shows its photo on its own pass only")
        orbit = STYLE_FILES["orbit"].read_text()
        self.assertIn("if (n === beat[k]) return {kind: 'photos', index: k};", orbit)
        self.assertEqual(reels3d.ORBIT_FLASHES, {4: 6, 5: 8, 6: 9}, "each flash of the spin a filler of its own")

    def test_the_ring_never_takes_a_card_round(self):
        """#76: `fall = ((f - OPEN_AT) * 0.028 + k * 0.9) % 14` took a card that had fallen out of the frame back to the
        top of its column, and the hero's drop put it back in view."""
        falls = [line for line in STYLE_FILES["ring"].read_text().splitlines() if "fall" in line and "OPEN_AT" in line]
        self.assertTrue(falls)
        for line in falls:
            self.assertNotIn("%", line, "the cascade falls once")

    def test_the_wall_and_the_ring_show_the_suites_count_of_pictures(self):
        for style in reels3d.PICTURES:
            found = re.search(r"export const PICTURES = (\d+);", STYLE_FILES[style].read_text())
            self.assertIsNotNone(found, style)
            self.assertEqual(int(found.group(1)), reels3d.PICTURES[style], style)
        self.assertIn("const SHOWN_SHARE = 0.001;", (SRC / "loopGrid.ts").read_text())
        self.assertIn("export const SHOWN_PX = 0.001 * W * H;", (SRC / "lib.tsx").read_text(), "one least share for a drawn slot")

    def test_a_slot_the_props_do_not_hold_stops_the_render_and_the_check_draws_each_place_by_its_number(self):
        """reels3d/src/slots.ts, run as the styles run it: a slot past the props, or fillers of another count, stop; the
        probe names each slot and its place; a numbered render draws a place white where the bit is set (its inverse
        where it is not), and a place the probe never heard stops the render."""
        got = node_run("""
const s = await import(process.argv[1]);
const p = { photos: [{ src: "p0.jpg" }, { src: "p1.jpg" }], fillers: [{ src: "f0.jpg" }] };
const out = {};
const tries = { photo: () => s.photoAt(p, 2), filler: () => s.fillerAt(p, 1), fraction: () => s.fillerAt(p, 0.5),
  count: () => s.checkFillers(p, 2, "Wall"), held: () => s.checkFillers(p, 1, "Wall") ?? "held", given: () => s.photoAt(p, 1).src };
for (const [k, f] of Object.entries(tries)) { try { out[k] = f(); } catch (e) { out[k] = "stopped: " + e.message; } }
const at = (q) => s.drawnFrom(q, "photos", 1);            // a style's place: one line asking for photo 1
const heard = [], say = console.log;
let site = "";
const checks = () => [{ probe: true }, ...[1, 2].flatMap((code) => [0, 1].flatMap((bit) => [false, true].map((inverse) =>
  ({ codes: { [`photos 1 ${site}`]: code }, bit, inverse })))), { codes: {}, bit: 0 }, undefined];
const drawn = [];
for (let n = 0; n < 11; n++) {
  console.log = (line) => heard.push(line);
  try { drawn.push(at({ ...p, check: checks()[n] })); } catch (e) { drawn.push("stopped: " + e.message); }  // one place, every time
  console.log = say;
  if (n === 0) site = heard[0].split(" ")[3];
}
Object.assign(out, { probe: drawn[0], heard, drawn: drawn.slice(1, 9), unheard: drawn[9], plain: drawn[10] });
console.log(JSON.stringify(out));
""", str(SRC / "slots.ts"))
        self.assertEqual(got["photo"], "stopped: no photo slot 2: the props hold 2")
        self.assertEqual(got["filler"], "stopped: no filler slot 1: the props hold 1")
        self.assertTrue(got["fraction"].startswith("stopped:"))
        self.assertEqual(got["count"], "stopped: Wall shows 2 photos and 2 fillers; the props hold 1 fillers")
        self.assertEqual((got["held"], got["given"]), ("held", "p1.jpg"))
        self.assertEqual(got["probe"], "p1.jpg")
        self.assertEqual(len(got["heard"]), 1)
        self.assertRegex(got["heard"][0], r"^REELCHECK photos 1 \S+$", "the probe names the slot and its place")
        lit, black = "p1-lit.jpg", "p1.jpg"
        self.assertEqual(got["drawn"], [lit, black, black, lit, black, lit, lit, black],
                         "number 1: white on bit 0 only; number 2: white on bit 1 only; the inverse the other way")
        self.assertTrue(got["unheard"].startswith("stopped: the card check never heard photos 1 asked for at"))
        self.assertEqual(got["plain"], "p1.jpg", "a reel the suite makes is drawn from its own files")

    def test_the_loop_grid_lays_each_picture_once_and_the_same_grid_on_the_fillers_it_laid(self):
        """reels3d/src/loopGrid.ts: a card for each of the post's four visited photos on its spot, the fifth and sixth photo
        and the fillers each on one card, even gaps, as many cards as come into the frame for these shapes; the props
        trimmed to the fillers it laid lay the very same grid (the suite gives it only those: render/reels3d.staged)."""
        got = node_run("""
const g = await import(process.argv[1]);
const shapes = [[1400, 933], [933, 1400], [1120, 1400], [1400, 788], [1400, 1400]];
const out = [];
for (const [n, seed] of [[4, 1], [5, 2], [6, 3], [6, 4], [6, 5]]) {
  let x = seed; const rnd = () => (x = (x * 16807) % 2147483647) / 2147483647;
  const photos = Array.from({ length: n }, (_, k) => { const [w, h] = shapes[Math.floor(rnd() * 5)]; return { src: `p${k}`, w, h }; });
  const fillers = Array.from({ length: 40 }, (_, k) => { const [w, h] = shapes[Math.floor(rnd() * 5)]; return { src: `f${k}`, w, h }; });
  const a = g.layout(photos, fillers);
  const used = a.laid - Math.max(0, n - 4);
  const b = g.layout(photos, fillers.slice(0, used));
  let short = "";
  try { g.layout(photos, fillers.slice(0, used - 1)); } catch (e) { short = e.message; }
  const rows = {};
  for (const c of a.cards) (rows[c.y] ??= []).push(c);
  const gaps = Object.values(rows).flatMap((r) => r.sort((p, q) => p.x - q.x).slice(1).map((c, i) => +(c.x - c.w / 2 - r[i].x - r[i].w / 2).toFixed(6)));
  out.push({ slots: a.cards.map((c) => `${c.slot.kind} ${c.slot.index}`), visits: a.visit.map((c) => `${c.slot.kind} ${c.slot.index}`),
             visitAt: a.visit.map((c) => [+c.x.toFixed(6), +c.y.toFixed(6)]), used, laid: a.laid, same: JSON.stringify(a.cards) === JSON.stringify(b.cards), short,
             gaps: [...new Set(gaps)], n });
}
console.log(JSON.stringify(out));
""", str(SRC / "loopGrid.ts"))
        for grid in got:
            n = grid["n"]
            self.assertEqual(len(grid["slots"]), len(set(grid["slots"])), "each picture on one card")
            self.assertEqual(grid["visits"], [f"photos {k}" for k in range(4)], "the loop visits the post's four photos")
            self.assertEqual(sorted(s for s in grid["slots"] if s.startswith("photos")), sorted(f"photos {k}" for k in range(n)),
                             "the fifth and sixth photo are in the grid, each once")
            self.assertEqual(grid["visitAt"][:3], [[0, 0], [1.6, 1.92], [0.2, 3.84]], "the first three on their spots")
            self.assertEqual(sorted(s for s in grid["slots"] if s.startswith("fillers")), sorted(f"fillers {k}" for k in range(grid["used"])))
            self.assertTrue(12 <= grid["used"] <= 30, grid["used"])
            self.assertTrue(grid["same"], "trimmed to the fillers it laid, the same grid")
            self.assertTrue(grid["short"].startswith("Loop's grid lays more cards than the props hold pictures for"))
            self.assertEqual(grid["gaps"], [0.16], "tight even gaps")

    def test_every_style_has_passed_the_card_check_on_its_sources_as_they_are(self):
        """The card check runs once a style, not for each reel: a style whose code changes is red here until `ccs reel-check
        STYLE --record` passes on the Mini and records the hash of its sources (reels3d/card-checks.json)."""
        from convention_social.render import reel_check
        book = json.loads(reel_check.REGISTRY_3D.read_text())
        for style in reels3d.STYLES:
            self.assertIn(style, book, f"{style} has never passed the card check: run `ccs reel-check {style} --record` on the Mini")
            self.assertEqual(book[style]["source"], reel_check.source_hash(style),
                             f"{style}'s code changed since its card check passed: run `ccs reel-check {style} --record` on the Mini")
            self.assertEqual((book[style]["repeats"], book[style]["twice_at_once"], book[style]["never_shown"]), (0, 0, 0))
