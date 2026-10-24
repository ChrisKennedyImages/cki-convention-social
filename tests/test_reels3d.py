"""The 3D reels (render/reels3d.py): five styles, the props a post gives them, the render run, the stills cut from
the reel, the fillers around the post's photos. Remotion itself is never run here: the run is a seam."""
from __future__ import annotations

import json
import random
import subprocess
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

    def test_the_next_style_is_random_and_never_the_last(self):
        seen = {reels3d.next_style("loop", random.Random(seed)) for seed in range(40)}
        self.assertEqual(seen, set(reels3d.STYLES) - {"loop"})
        self.assertEqual({reels3d.next_style(None, random.Random(seed)) for seed in range(40)}, set(reels3d.STYLES))

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


class Render(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.track = self.root / "legendary.mp4"
        self.track.write_bytes(b"isom")
        self.grid = []
        for k in range(3):
            p = self.root / f"g{k}.img"
            Image.new("RGB", (3000, 2000), (10 * k, 0, 0)).save(p, "JPEG")
            self.grid.append(p)
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
        got = reels3d.render("loop", shots(5), out=out, audio=self.track, grid=self.grid, run=self.remotion)
        self.assertEqual(got, out)
        self.assertEqual(out.read_bytes(), b"mp4")
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
        self.assertEqual([g["src"] for g in props["grid"]], ["photos/g0.jpg", "photos/g1.jpg", "photos/g2.jpg"])
        self.assertEqual(props["music"], "music.mp4")
        self.assertEqual(self.seen["files"], ["g0.jpg", "g1.jpg", "g2.jpg", "p0.jpg", "p1.jpg", "p2.jpg", "p3.jpg", "p4.jpg"])
        self.assertEqual(self.seen["music"], ["music.mp4"])
        self.assertEqual(self.seen["fonts"], (reels3d.REELS3D / "public" / "fonts").resolve(), "the fonts the styles use")
        self.assertFalse((self.root / "posts" / "7-loop-public").exists(), "the public dir is gone once the mp4 is made")

    def test_a_remotion_failure_is_an_error_that_says_what_remotion_said_and_leaves_nothing_behind(self):
        def failing(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 1, "", "Error: Composition 'Loop' timed out\nat render\n")
        with self.assertRaises(RuntimeError) as e:
            reels3d.render("loop", shots(4), out=self.root / "x.mp4", audio=self.track, grid=self.grid, run=failing)
        self.assertIn("remotion stopped with code 1", str(e.exception))
        self.assertIn("timed out", str(e.exception))
        self.assertFalse((self.root / "x.mp4").exists())
        self.assertFalse((self.root / "x-public").exists())

    def test_a_reel_needs_a_known_style_and_its_track(self):
        with self.assertRaises(ValueError):
            reels3d.render("rooms", shots(4), out=self.root / "x.mp4", audio=self.track, run=self.remotion)
        with self.assertRaises(ValueError):
            reels3d.render("wall", shots(4), out=self.root / "x.mp4", audio=None, run=self.remotion)
        self.assertEqual(self.runs, [])

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
        got = reels3d.fillers(self.conn, exclude=[ids[0]])
        self.assertEqual(len(got), 2, "one folder, two rooms: two fillers")
        self.assertTrue(all(p.is_file() for p in got))
        self.assertNotIn(cache / "f0.img", got, "the post's own photo is not a filler")
        self.assertNotIn(cache / "f7.img", got, "a photo without a copy here cannot be rendered")
