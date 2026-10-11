"""Music for the reels: a track is kept only with its record (where it came from, what that allows),
the newest switched-on track rides the reel with fades, and with none the reel is silent."""
from __future__ import annotations

import io
import math
import os
import struct
import subprocess
import wave
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from convention_social import music
from convention_social.core import auth, config, db
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import design_samples, motion, reel
from tests._base import IsolatedCase

RECORD = dict(title="Night Shift", artist="Sample Artist", source="https://example.com/track/123",
              terms="free for business posts on Instagram and Facebook")


def tone(seconds=2.0, rate=22050) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(seconds * rate))))
    return buf.getvalue()


class Tracks(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_no_record_no_track(self):
        for missing in RECORD:
            with self.assertRaises(music.Refused):
                music.add(self.conn, "a.mp3", b"ID3", **dict(RECORD, **{missing: "  "}))
        with self.assertRaises(music.Refused):
            music.add(self.conn, "a.exe", b"MZ", **RECORD)
        with self.assertRaises(music.Refused):
            music.add(self.conn, "a.mp3", b"", **RECORD)
        self.assertEqual(music.tracks(self.conn), [])
        self.assertIsNone(music.current(self.conn))

    def test_the_newest_switched_on_track_with_its_file_is_used(self):
        first = music.add(self.conn, "one.wav", tone(), **RECORD)
        second = music.add(self.conn, "two.wav", tone(), **dict(RECORD, title="Second"))
        self.assertEqual(music.current(self.conn).name, db.one(self.conn, "SELECT file FROM music_tracks WHERE id=?", (second,))["file"])
        music.set_active(self.conn, second, False)
        self.assertEqual(music.current(self.conn).name, db.one(self.conn, "SELECT file FROM music_tracks WHERE id=?", (first,))["file"])
        (music.folder() / music.current(self.conn).name).unlink()
        self.assertIsNone(music.current(self.conn))


class Encode(IsolatedCase):
    def test_the_track_rides_the_video_faded_in_and_out(self):
        track = self.root / "t.wav"
        track.write_bytes(tone(3.0))
        out = self.root / "r.mp4"
        frames = [Image.new("RGB", (64, 64), (i * 8, 0, 0)) for i in range(30)]
        reel.encode(iter(frames), out, size=(64, 64), fps=30, audio=track, seconds=1.0)
        self.assertGreater(out.stat().st_size, 0)
        probe = subprocess.run([reel.ffmpeg_path(), "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
        self.assertIn("Video: h264", probe)
        self.assertIn("Audio: aac", probe)
        silent = self.root / "s.mp4"
        reel.encode(iter(frames), silent, size=(64, 64), fps=30)
        probe = subprocess.run([reel.ffmpeg_path(), "-hide_banner", "-i", str(silent)], capture_output=True, text=True).stderr
        self.assertIn("Video: h264", probe)
        self.assertNotIn("Audio:", probe)

    def test_the_samples_pass_the_current_track_to_both_reels(self):
        conn = db.connect()
        music.add(conn, "one.wav", tone(), **RECORD)
        seen = {}
        shots = [motion.Shot(Image.new("RGB", (800, 600), (40 * i, 60, 90)), "PANELS", "A line.") for i in range(3)]

        def fake(name):
            def job(s, c, *, out, audio=None):
                seen[name] = audio
                return out
            return job
        with mock.patch.object(design_samples, "pick", return_value=[{"drive_id": f"d{i}", "shot_type": "stage_panel"} for i in range(3)]), \
             mock.patch.object(motion, "rooms_reel", fake("rooms")), mock.patch.object(motion, "facematch_reel", fake("facematch")):
            buf = io.BytesIO(); shots[0].photo.save(buf, "JPEG")
            design_samples.make(conn, lambda fid: buf.getvalue(), out_root=self.root / "renders", log=lambda m: None)
        self.assertEqual(seen["rooms"], music.current(conn))
        self.assertEqual(seen["facematch"], music.current(conn))
        conn.close()


class Page(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_upload_needs_the_rights_box_and_the_record(self):
        files = {"file": ("night.wav", tone(), "audio/wav")}
        r = self.client.post("/library/music", data=dict(RECORD), files=files, follow_redirects=False)
        self.assertIn("Tick+that+you+have+the+right", r.headers["location"])
        r = self.client.post("/library/music", data=dict(RECORD, source="", rights="yes"), files=files, follow_redirects=False)
        self.assertIn("Track+not+added", r.headers["location"])
        r = self.client.post("/library/music", data=dict(RECORD, rights="yes"), files=files, follow_redirects=False)
        self.assertIn("Track+added", r.headers["location"])
        page = self.client.get("/library").text
        self.assertIn("Night Shift by Sample Artist", page)
        self.assertIn("Music for reels", page)
