"""Chris, 2026-10-15: "on the dashboard the thumbnail says 31 meg's per file or close to that. make sure nothing is
being stored that large on the mini - it cant handle the memory with many large files and 3 suites running".

A photo comes from Drive no larger than storage.MAX_EDGE on its long side, as a fresh JPEG with its orientation in the
pixels; the Drive original is never touched. The nightly sweep shrinks copies kept before this, phone photos included.
A photo from the phone is kept at that size."""
from __future__ import annotations

import io
import os
import time
import types

from PIL import Image

from convention_social import storage
from convention_social.core import db
from convention_social.drive.api import DriveReader
from tests._base import IsolatedCase


def jpeg(w, h, orientation=None, quality=95) -> bytes:
    im = Image.effect_noise((w, h), 60).convert("RGB")
    buf = io.BytesIO()
    kw = {}
    if orientation:
        ex = Image.Exif()
        ex[0x0112] = orientation
        kw["exif"] = ex
    im.save(buf, "JPEG", quality=quality, **kw)
    return buf.getvalue()


class SmallCopy(IsolatedCase):
    def test_a_big_original_comes_back_small_and_upright(self):
        big = jpeg(6000, 4000, orientation=6)                     # a portrait photo stored sideways with a rotate tag
        small = storage.small_copy(big)
        with Image.open(io.BytesIO(small)) as im:
            self.assertEqual(max(im.size), storage.MAX_EDGE)
            self.assertEqual(im.size, (2000, 3000), "the rotation is in the pixels")
            self.assertNotIn(0x0112, im.getexif(), "no rotate tag left to apply twice")
        self.assertLess(len(small), len(big))

    def test_a_small_picture_and_a_non_picture_are_left_alone(self):
        small = jpeg(1600, 1000)
        self.assertIs(storage.small_copy(small), small)
        self.assertEqual(storage.small_copy(b"not a picture"), b"not a picture")

    def test_the_drive_download_is_shrunk_before_anyone_keeps_it(self):
        big = jpeg(5000, 3500)
        reader = DriveReader("tok")
        reader.get = lambda *a, **kw: types.SimpleNamespace(content=big)
        got = reader.download("file-1")
        with Image.open(io.BytesIO(got)) as im:
            self.assertEqual(max(im.size), storage.MAX_EDGE)


class Sweep(IsolatedCase):
    def test_the_sweep_shrinks_big_copies_kept_before_and_keeps_them(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        root = self.root / "data"
        (root / "photos").mkdir(parents=True)
        (root / "phone").mkdir(parents=True)
        cached, phone = root / "photos" / "d1.img", root / "phone" / "20261014-1-aa.jpg"
        cached.write_bytes(jpeg(6000, 4000))
        phone.write_bytes(jpeg(4032, 3024))
        before = cached.stat().st_size + phone.stat().st_size
        now = db.utcnow()
        db.insert(conn, "photos", drive_id="d1", name="d1.jpg", first_seen_at=now, last_seen_at=now)
        result = storage.sweep(conn, now=time.time())              # both are new: shrunk, not deleted
        for f in (cached, phone):
            self.assertTrue(f.exists(), f.name)
            with Image.open(f) as im:
                self.assertLessEqual(max(im.size), storage.MAX_EDGE, f.name)
        self.assertLess(cached.stat().st_size + phone.stat().st_size, before)
        self.assertGreater(result["freed_mb"]["shrunk"], 0)
        self.assertIn("shrank kept photos by", storage.summary(result))
