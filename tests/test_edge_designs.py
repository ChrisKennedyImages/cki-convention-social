"""The second generation post designs (render/edge.py, render/reel.py): every piece renders at its
sizes, carries the ask, refuses copy the rules stop, and leaves no camera data; the carousel is one
strip cut at the seams; the reel is 15 seconds of 1080 x 1920 and fails closed without ffmpeg."""
from __future__ import annotations

import io
import sys
from unittest import mock

from PIL import Image, ImageChops, ImageStat

from convention_social.render import edge, meta, posts, reel
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

COPY = edge.EdgeCopy(service="Backstage", headline=["BACKSTAGE.", "BEFORE DOORS."],
                     line="Green rooms and the minutes before the doors open.", kicker="On assignment")


def photo(seed=0, size=(2400, 1600)):
    return Image.open(io.BytesIO(jpeg_bytes((90, 60 + seed * 20, 120), size=size, seed=seed)))


def cyan_pixels(im: Image.Image, box) -> int:
    """How many pixels in `box` are the brand cyan (the ask block is the only large cyan area)."""
    r, g, b = im.convert("RGB").crop(box).split()
    near = [ImageChops.invert(ImageChops.difference(ch, Image.new("L", ch.size, v))).point(lambda x: 255 if x > 215 else 0)
            for ch, v in zip((r, g, b), edge.C)]
    both = ImageChops.multiply(ImageChops.multiply(near[0], near[1]), near[2])
    return int(ImageStat.Stat(both).sum[0] / 255)


class SinglePosts(IsolatedCase):
    def test_every_design_renders_at_both_feed_sizes_with_the_ask_and_no_camera_data(self):
        for fn in (edge.lockon, edge.slash, edge.iris):
            for aspect, size in (("4:5", (1080, 1350)), ("2:3", (1000, 1500))):
                out = fn(photo(), COPY, out=self.root / f"{fn.__name__}-{aspect.replace(':', '')}.jpg", aspect=aspect)
                with Image.open(out) as im:
                    self.assertEqual(im.size, size, fn.__name__)
                    lower = (0, int(size[1] * 0.8), size[0], size[1])
                    self.assertGreater(cyan_pixels(im, lower), 4000, f"{fn.__name__} {aspect}: no ask block")
                self.assertEqual(meta.is_clean(out), [], fn.__name__)

    def test_the_rules_stop_every_design_before_anything_is_drawn(self):
        bad = (edge.EdgeCopy(service="Portraits", line="Packages from $150 a day."),
               edge.EdgeCopy(service="Portraits", headline=["OFFICIAL PHOTOGRAPHER"]),
               edge.EdgeCopy(service="Portraits", line="Fast — and sharp."))
        for fn in (edge.lockon, edge.slash, edge.iris):
            for i, copy in enumerate(bad):
                out = self.root / f"{fn.__name__}-bad{i}.jpg"
                with self.assertRaises(posts.CopyRefused):
                    fn(photo(), copy, out=out)
                self.assertFalse(out.exists())


class Carousel(IsolatedCase):
    COLOURS = ((200, 40, 40), (40, 200, 40), (40, 40, 200), (200, 200, 40), (200, 40, 200), (40, 200, 200))

    def slides(self):
        return [edge.Slide(Image.new("RGB", (2400, 1600), colour), name, "One plain line about this part of the event.")
                for colour, name in zip(self.COLOURS, ("MAIN STAGE", "BACKSTAGE", "PANELS", "PORTRAITS", "EXPO FLOOR", "AFTER DARK"))]

    def test_a_cover_one_slide_per_room_and_a_close(self):
        paths = edge.carousel(self.slides(), edge.CarouselCopy(), out_dir=self.root / "c")
        self.assertEqual(len(paths), 8)
        for p in paths:
            with Image.open(p) as im:
                self.assertEqual(im.size, (1080, 1350))
            self.assertEqual(meta.is_clean(p), [])
        with Image.open(paths[-1]) as close:
            self.assertGreater(cyan_pixels(close, (0, 900, 1080, 1200)), 20000)

    def test_the_photos_run_across_the_seams(self):
        """Each slide's last column and the next slide's first column are the same photo."""
        paths = edge.carousel(self.slides(), edge.CarouselCopy(), out_dir=self.root / "c")
        for left, right in zip(paths[1:6], paths[2:7]):
            with Image.open(left) as a, Image.open(right) as b:
                edge_a = a.convert("RGB").crop((1079, 200, 1080, 800))
                edge_b = b.convert("RGB").crop((0, 200, 1, 800))
                self.assertGreater(max(ImageStat.Stat(edge_a).mean), 60)      # a photo, not black
                self.assertLess(max(ImageStat.Stat(ImageChops.difference(edge_a, edge_b)).mean), 12)

    def test_the_rules_stop_the_carousel(self):
        slides = self.slides()
        slides[2] = edge.Slide(photo(), "PANELS", "Rates start at $99.")
        with self.assertRaises(posts.CopyRefused):
            edge.carousel(slides, edge.CarouselCopy(), out_dir=self.root / "c")
        self.assertFalse((self.root / "c").exists())


class Reel(IsolatedCase):
    def clips(self, line="One plain line about this part of the event."):
        return [reel.Clip(photo(i, (1600, 2400) if i % 2 else (2400, 1600)), word, line, af=(0.5, 0.3 if i % 2 else 0.7))
                for i, word in enumerate(("MAIN STAGE", "BACKSTAGE", "PANELS", "PORTRAITS", "EXPO FLOOR", "AFTER DARK"))]

    def test_fifteen_seconds_of_vertical_frames(self):
        self.assertEqual(reel.total_frames(), 15 * reel.FPS)
        got = []
        picks = [0, 31, 36, 60, 116, 117, 156, 300, 330, reel.total_frames() - 1]
        reel.make(self.clips(), reel.ReelCopy(), out=self.root / "r.mp4", only=picks,
                  encoder=lambda frames, out: got.extend(frames))
        self.assertEqual(len(got), len(picks))
        for im in got:
            self.assertEqual((im.mode, im.size), ("RGB", (1080, 1920)))
        flash = ImageStat.Stat(got[picks.index(116)].convert("L")).mean[0]
        self.assertGreater(flash, 200)                                  # the strobe cut
        end = got[-1]
        self.assertGreater(cyan_pixels(end, (0, 1000, 1080, 1250)), 40000)  # the ask on the end card
        self.assertEqual(cyan_pixels(end, (0, reel.SAFE_BOTTOM + 100, 1080, 1920)), 0)

    def test_the_rules_and_the_clip_count_stop_the_reel(self):
        with self.assertRaises(posts.CopyRefused):
            reel.make(self.clips("Book now, only $200."), reel.ReelCopy(), out=self.root / "r.mp4",
                      encoder=lambda frames, out: list(frames))
        with self.assertRaises(ValueError):
            reel.make(self.clips()[:4], reel.ReelCopy(), out=self.root / "r.mp4", encoder=lambda frames, out: list(frames))

    def test_no_ffmpeg_means_no_reel(self):
        with mock.patch("convention_social.render.reel.shutil.which", return_value=None), \
             mock.patch.dict(sys.modules, {"imageio_ffmpeg": None}):
            with self.assertRaises(RuntimeError) as cm:
                reel.ffmpeg_path()
        self.assertIn("ffmpeg is not installed", str(cm.exception))
