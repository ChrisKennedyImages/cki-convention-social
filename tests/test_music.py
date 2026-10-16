"""Music for the reels: a track is kept only with its record (where it came from, what that allows),
the newest switched-on track rides the reel with fades, and with none the reel is silent."""
from __future__ import annotations

import io
import math
import os
import re
import struct
import subprocess
import wave
from pathlib import Path
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


def fake_stills(kind, shots, copy, *, out_dir, **kw) -> list[Path]:
    """Stands in for motion.reel_stills: three small frames, the cover first, without drawing the reel."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"{kind}-{i:03d}.jpg" for i in (60, 120, 300)]
    for p in paths:
        Image.new("RGB", (90, 160), (20, 20, 24)).save(p, "JPEG")
    return paths


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

    def test_the_credit_names_the_artist_when_known_else_the_source(self):
        """Chris, 2026-10-14: "i dont ho the artist is. its a meat musics free track": the line under a reel never
        leans on an artist he had to make up."""
        file = db.one(self.conn, "SELECT file FROM music_tracks WHERE id=?", (music.add(self.conn, "one.wav", tone(), **RECORD),))["file"]
        self.assertEqual(music.credit(self.conn, file), "Night Shift, Sample Artist")
        for placeholder in ("-", "--", "?", " . ", "unknown", "Unknown", "NONE", "n/a", "NA"):
            self.conn.execute("UPDATE music_tracks SET artist=? WHERE file=?", (placeholder, file))
            self.assertEqual(music.credit(self.conn, file), "Night Shift (https://example.com/track/123)", placeholder)
            self.assertFalse(music.artist_known(placeholder), placeholder)
        self.assertTrue(music.artist_known("DJ 7"))
        self.assertEqual(music.credit(self.conn, "gone-20261014.mp3"), "gone-20261014", "a record that is gone: the file's own name")
        self.assertEqual(music.credit(self.conn, None), "")
        self.assertEqual(music.credit(self.conn, ""), "")


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

    def test_the_samples_pass_the_current_track_to_the_reel(self):
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
             mock.patch.object(motion, "rooms_reel", fake("rooms")), mock.patch.object(motion, "reel_stills", fake_stills):
            buf = io.BytesIO(); shots[0].photo.save(buf, "JPEG")
            design_samples.make(conn, lambda fid: buf.getvalue(), out_root=self.root / "renders", log=lambda m: None)
        self.assertEqual(seen, {"rooms": music.current(conn)}, "the face match reel is retired; only the rooms reel is made")
        conn.close()


class SamplePage(IsolatedCase):
    """The design samples page (Chris, 2026-10-14, of a reel on it: "where is the music on the insta posts!!!!"): the
    reels played by themselves, which a browser allows only muted. Now a reel plays on a tap, with its sound, and the
    line under it names the track it was made with."""
    def setUp(self):
        super().setUp()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def make(self) -> tuple[Path, str]:
        def fake_reel(shots, copy, *, out, audio=None):
            out.write_bytes(b"mp4")
            return out
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), (40, 60, 90)).save(buf, "JPEG")
        with mock.patch.object(design_samples, "pick", return_value=[{"drive_id": f"d{i}", "shot_type": "stage_panel"} for i in range(3)]), \
             mock.patch.object(motion, "rooms_reel", fake_reel), mock.patch.object(motion, "reel_stills", fake_stills):
            out = design_samples.make(self.conn, lambda fid: buf.getvalue(), out_root=self.root / "renders", log=lambda m: None)
        return out, (out / "index.html").read_text()

    def test_a_sample_reel_plays_on_a_tap_with_its_sound_and_names_the_track(self):
        tid = music.add(self.conn, "one.wav", tone(), **RECORD)
        out, page = self.make()
        tags = re.findall(r"<video[^>]*>", page)
        self.assertEqual(len(tags), 1, page)
        for word in ("muted", "autoplay"):
            self.assertNotIn(word, tags[0])
        for word in ("controls", "playsinline", "loop", f'poster="/library/design/{out.name}/rooms-reel-cover.jpg"'):
            self.assertIn(word, tags[0])
        self.assertTrue((out / "rooms-reel-cover.jpg").is_file(), "the reel's own cover frame is its poster")
        self.assertFalse((out / "stills").exists())
        self.assertIn("Tap a reel to play it with sound", page)
        self.assertLess(page.index("Tap a reel"), page.index("<video"))
        self.assertIn("Music: Night Shift, Sample Artist", page)
        self.assertNotIn("No music", page)
        music.add(self.conn, "free.wav", tone(), **dict(RECORD, title="Free Track", artist="-", source="Meta Sound Collection"))
        _, page = self.make()
        self.assertIn("Music: Free Track (Meta Sound Collection)", page, "an artist Chris does not know: the source instead")
        self.assertNotIn("Free Track, -", page)
        music.set_active(self.conn, tid, False)
        music.set_active(self.conn, tid + 1, False)
        _, page = self.make()
        self.assertNotIn("muted", re.findall(r"<video[^>]*>", page)[0])
        self.assertIn("No music", page)
        self.assertNotIn("Night Shift", page)
        self.assertNotIn("Free Track", page)


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
        page = self.client.get("/music").text          # its own page under Photos since 2026-10-15
        self.assertIn("Night Shift by Sample Artist", page)
        self.assertIn("Music for reels", page)


class Formats(IsolatedCase):
    """Chris sent an audio-only .mp4 (2026-10-11): such a track is taken; a file with no sound is not."""
    def setUp(self):
        super().setUp()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def mp4(self, audio: bool) -> bytes:
        src = self.root / "t.wav"
        src.write_bytes(tone(1.0))
        out = self.root / ("a.mp4" if audio else "v.mp4")
        args = ["-i", str(src), "-c:a", "aac"] if audio else ["-f", "lavfi", "-i", "color=c=black:s=64x64:d=1", "-c:v", "libx264"]
        subprocess.run([reel.ffmpeg_path(), "-y", "-loglevel", "error", *args, str(out)], check=True)
        return out.read_bytes()

    def test_an_audio_only_mp4_is_a_track_and_a_silent_file_is_refused(self):
        tid = music.add(self.conn, "Legendary.mp4", self.mp4(audio=True), **RECORD)
        self.assertTrue(tid)
        self.assertTrue(music.current(self.conn).name.endswith(".mp4"))
        for name, data in (("silent.mp4", self.mp4(audio=False)), ("fake.mp3", b"ID3 not really audio")):
            with self.assertRaises(music.Refused):
                music.add(self.conn, name, data, **dict(RECORD, title=name))
        self.assertEqual([t["id"] for t in music.tracks(self.conn)], [tid])
        self.assertEqual(len(list(music.folder().iterdir())), 1, "a refused file is not kept")
