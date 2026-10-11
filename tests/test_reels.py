"""Reels, end to end: the music reaches the mp4, Saturday's draft is a reel once a track is on, the
publisher sends it to Instagram and Facebook as a video by the fields Buffer's live schema names, and
the dashboard plays it. Chris, 2026-10-11: "Let's get the music and everything working (video format too)"."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from convention_social import music
from convention_social.agents import art_director, content, publisher
from convention_social.buffer import media, payloads
from convention_social.buffer.client import BufferClient, BufferError
from convention_social.core import auth, config, db, runner
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import meta, motion, reel
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_channels, add_photo, add_post, field, make_ctx, write_render
from tests._photos import jpeg_bytes
from tests.test_music import RECORD, tone
from tests.test_publisher import PublisherCase

FRIDAY = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)          # tomorrow is Saturday, ISO week 42: face match reel
FIELDS = [{"name": "url", "type": "String", "required": True}, {"name": "thumbnailUrl", "type": "String", "required": False}]


def shots(n=4):
    return [motion.Shot(Image.new("RGB", (900, 700), (40 + 30 * i, 70, 110)), room, "A line about the room.")
            for i, room in zip(range(n), ("MAIN STAGE", "BACKSTAGE", "PORTRAITS", "EXPO FLOOR", "AFTER DARK", "THE CROWD"))]


# ------------------------------------------------------------------ the music reaches the mp4

class Music(IsolatedCase):
    def test_the_track_given_to_a_reel_reaches_the_encoder_with_the_reels_own_length(self):
        track = self.root / "t.wav"
        track.write_bytes(tone(1.0))
        seen = {}

        def encode(frames, out, **kw):
            seen.update(kw, n=len(list(frames)))
            return out
        with mock.patch.object(motion, "encode", encode):
            motion.rooms_reel(shots(), motion.MotionCopy(), out=self.root / "r.mp4", audio=track, only=[0, 1, 2])
        self.assertEqual(seen, {"audio": track, "seconds": 3 / reel.FPS, "n": 3})

    def test_a_reel_with_a_track_comes_out_with_sound(self):
        track = self.root / "t.wav"
        track.write_bytes(tone(2.0))
        out = motion.facematch_reel(shots(), motion.MotionCopy(), out=self.root / "f.mp4", audio=track, only=list(range(8)))
        probe = subprocess.run([reel.ffmpeg_path(), "-hide_banner", "-i", str(out)], capture_output=True, text=True).stderr
        self.assertIn("Video: h264", probe)
        self.assertIn("Audio: aac", probe)

    def test_the_stills_are_the_reels_own_frames_cover_first_with_our_metadata(self):
        got = motion.reel_stills("rooms", shots(), motion.MotionCopy(), out_dir=self.root / "s",
                                 meta=meta.ImageMeta(title="t", description="d", keywords=["k"]))
        self.assertEqual([p.name for p in got], ["rooms-060.jpg", "rooms-090.jpg", "rooms-240.jpg"])
        self.assertFalse((self.root / "s" / "unused.mp4").exists())
        for p in got:
            with Image.open(p) as im:
                self.assertEqual(im.size, (1080, 1920))
            self.assertEqual(meta.is_clean(p), [])
            self.assertIn(b"CKI, LLC", p.read_bytes())


# ------------------------------------------------------------------ Buffer's video format, read live

class Schema(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_the_video_fields_come_from_the_live_schema(self):
        fake = FakeBuffer()
        got = BufferClient("test-key", conn=self.conn, transport=fake).video_asset_fields()
        self.assertEqual([v["name"] for _, v in fake.calls], ["AssetInput", "VideoAssetInput"])
        self.assertEqual(got[:2], FIELDS)
        self.assertEqual(got[2], {"name": "metadata", "type": "VideoMetadataInput", "required": False})

    def test_no_video_member_or_no_type_is_an_error_not_a_guess(self):
        for schema in ({"AssetInput": [field("image", "ImageAssetInput")]}, {}):
            with self.assertRaises(BufferError):
                BufferClient("test-key", conn=self.conn, transport=FakeBuffer(schema=schema)).video_asset_fields()

    def test_a_reel_payload_per_network(self):
        ig = payloads.build_reel("instagram", "ch-ig", "Caption", "https://m/v.mp4", "https://m/c.jpg", FIELDS)
        self.assertEqual(ig["assets"], [{"video": {"url": "https://m/v.mp4", "thumbnailUrl": "https://m/c.jpg"}}])
        self.assertEqual(ig["metadata"], {"instagram": {"type": "reel", "shouldShareToFeed": True}})
        self.assertEqual((ig["channelId"], ig["text"], ig["mode"]), ("ch-ig", "Caption", "shareNow"))
        fb = payloads.build_reel("facebook", "ch-fb", "Caption", "https://m/v.mp4", "", FIELDS, scheduled_for="2026-10-17T10:00")
        self.assertEqual(fb["assets"], [{"video": {"url": "https://m/v.mp4"}}])
        self.assertEqual(fb["metadata"], {"facebook": {"type": "reel"}})
        self.assertEqual((fb["mode"], fb["dueAt"]), ("customScheduled", "2026-10-17T14:00:00Z"))
        with self.assertRaises(payloads.PayloadError):
            payloads.build_reel("pinterest", "ch-pin", "x", "https://m/v.mp4", "", FIELDS)

    def test_a_field_this_code_cannot_fill_stops_the_reel_only_when_required(self):
        extra = FIELDS + [{"name": "durationMs", "type": "Int", "required": False}]
        self.assertNotIn("durationMs", payloads.video_asset(extra, "https://m/v.mp4", ""))
        with self.assertRaises(payloads.PayloadError):
            payloads.video_asset(FIELDS + [{"name": "durationMs", "type": "Int", "required": True}], "https://m/v.mp4", "")
        with self.assertRaises(payloads.PayloadError):
            payloads.video_asset([{"name": "source", "type": "String", "required": False}], "https://m/v.mp4", "")
        required_cover = [{"name": "url", "required": True}, {"name": "thumbnailUrl", "required": True}]
        self.assertEqual(payloads.video_asset(required_cover, "v", "c"), {"url": "v", "thumbnailUrl": "c"})
        with self.assertRaises(payloads.PayloadError):
            payloads.video_asset(required_cover, "v", "")


# ------------------------------------------------------------------ the publisher

class Publish(PublisherCase):
    def reel_post(self, **kw):
        self.seed = getattr(self, "seed", 2) + 1
        pid = add_photo(self.conn, self.root / "photos", seed=self.seed)
        folder = config.get_config().data_root / "renders"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "r.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42 reel")
        renders = {"9:16": [str(folder / "r.mp4")], "cover": [write_render(folder, "cover.jpg")],
                   "2:3": [write_render(folder, "pin-23.jpg")], "stills": [write_render(folder, "still.jpg")]}
        return pid, add_post(self.conn, [pid], render_paths=renders, **kw)

    def uploader(self):
        self.uploads = []

        def up(path, key):
            self.assertTrue(path.exists())
            self.uploads.append((path.name, key))
            return f"https://media.example/m/{key}"
        return up

    def test_dry_run_builds_the_reel_asks_buffer_nothing_and_says_what_it_assumed(self):
        _, qid = self.reel_post()
        fake = FakeBuffer()
        stats = self.publish(make_ctx(self.conn), client=BufferClient("test-key", conn=self.conn, transport=fake))
        self.assertEqual((stats["would_publish"], fake.calls), (1, []))
        row = self.row(qid)
        sent = json.loads(row["payload"])
        self.assertEqual(list(sent), ["instagram", "facebook", "pinterest"])
        base = f"{media.PLACEHOLDER_BASE}/convention-social/reels/{qid}"
        video = {"video": {"url": f"{base}-video.mp4", "thumbnailUrl": f"{base}-cover.jpg"}}
        self.assertEqual((sent["instagram"]["assets"], sent["facebook"]["assets"]), ([video], [video]))
        self.assertEqual(sent["instagram"]["metadata"]["instagram"]["type"], "reel")
        self.assertEqual(sent["facebook"]["metadata"]["facebook"]["type"], "reel")
        self.assertEqual(sent["pinterest"]["assets"], [{"image": {"url": f"{media.PLACEHOLDER_BASE}/convention-social/cards/{qid}-23-1.jpg"}}])
        self.assertIn("url and thumbnailUrl assumed", row["last_error"])

    def test_live_reads_the_schema_once_uploads_the_reel_and_sends_video_posts(self):
        _, qid = self.reel_post()
        _, second = self.reel_post()
        fake = FakeBuffer()
        stats = self.publish(make_ctx(self.conn, dry_run=False), client=BufferClient("test-key", conn=self.conn, transport=fake),
                             uploader=self.uploader())
        self.assertEqual(stats["scheduled"], 2)
        self.assertEqual([op.split("(")[0] for op, _ in fake.calls if "InputType" in op], ["query InputType"] * 2,
                         "the schema is read once a run, not once a post")
        self.assertIn(("r.mp4", f"convention-social/reels/{qid}-video.mp4"), self.uploads)
        self.assertIn(("cover.jpg", f"convention-social/reels/{qid}-cover.jpg"), self.uploads)
        self.assertIn(("pin-23.jpg", f"convention-social/cards/{qid}-23-1.jpg"), self.uploads)
        self.assertNotIn("still.jpg", [n for n, _ in self.uploads])
        self.assertEqual(len(fake.created), 6)
        ig, fb, pin = fake.created[:3]
        url = f"https://media.example/m/convention-social/reels/{qid}"
        self.assertEqual(ig["assets"], [{"video": {"url": f"{url}-video.mp4", "thumbnailUrl": f"{url}-cover.jpg"}}])
        self.assertEqual((ig["channelId"], ig["metadata"]["instagram"]["type"]), ("ch-ig", "reel"))
        self.assertEqual((fb["channelId"], fb["metadata"]["facebook"]["type"]), ("ch-fb", "reel"))
        self.assertEqual((pin["channelId"], list(pin["assets"][0])), ("ch-pin", ["image"]))
        self.assertEqual(json.loads(self.row(qid)["buffer_post_ids"]), {"instagram": "post-1", "facebook": "post-2", "pinterest": "post-3"})

    def test_a_schema_this_code_cannot_fill_fails_the_post_with_nothing_uploaded_or_sent(self):
        _, qid = self.reel_post()
        schema = {"AssetInput": [field("video", "VideoAssetInput")],
                  "VideoAssetInput": [field("url", "String", True, "SCALAR"), field("durationMs", "Int", True, "SCALAR")]}
        fake = FakeBuffer(schema=schema)
        self.publish(make_ctx(self.conn, dry_run=False), client=BufferClient("test-key", conn=self.conn, transport=fake),
                     uploader=self.uploader())
        row = self.row(qid)
        self.assertEqual(row["status"], "failed")
        self.assertIn("durationMs", row["last_error"])
        self.assertEqual((self.uploads, fake.created), ([], []))
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "PayloadError")

    def test_buffer_without_a_video_asset_fails_closed(self):
        _, qid = self.reel_post()
        fake = FakeBuffer(schema={"AssetInput": [field("image", "ImageAssetInput")]})
        self.publish(make_ctx(self.conn, dry_run=False), client=BufferClient("test-key", conn=self.conn, transport=fake),
                     uploader=self.uploader())
        self.assertEqual((self.row(qid)["status"], self.uploads, fake.created), ("failed", [], []))

    def test_a_missing_video_file_fails_the_post(self):
        _, qid = self.reel_post()
        (config.get_config().data_root / "renders" / "r.mp4").unlink()
        fake = FakeBuffer()
        self.publish(make_ctx(self.conn, dry_run=False), client=BufferClient("test-key", conn=self.conn, transport=fake),
                     uploader=self.uploader())
        row = self.row(qid)
        self.assertEqual((row["status"], fake.created), ("failed", []))
        self.assertIn("video is missing", row["last_error"])

    def test_a_reel_only_to_pinterest_never_asks_for_the_video_fields(self):
        _, qid = self.reel_post()
        self.conn.execute("UPDATE content_queue SET targets=? WHERE id=?", (json.dumps(["pinterest"]), qid))
        fake = FakeBuffer()
        self.publish(make_ctx(self.conn, dry_run=False), client=BufferClient("test-key", conn=self.conn, transport=fake),
                     uploader=self.uploader())
        self.assertFalse([op for op, _ in fake.calls if "InputType" in op])
        self.assertEqual([k for _, k in self.uploads], [f"convention-social/cards/{qid}-23-1.jpg"])


# ------------------------------------------------------------------ Saturday's draft

class Saturday(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="fe", name="Con", clearance="cleared", first_seen_at=now, last_seen_at=now)
        self.ids, self.fetched = {}, []
        for did, room, q in (("e1", None, 5), ("e2", None, 4), ("e3", None, 3), ("s1", "stage_panel", 5),
                             ("s2", "stage_panel", 5), ("s3", "backstage", 4), ("s4", "portrait", 3)):
            pid = db.insert(self.conn, "photos", drive_id=did, name=f"{did}.jpg", folder_id="fe", width=3000, height=2000,
                            first_seen_at=now, last_seen_at=now)
            db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name="Awesome Con",
                      is_convention=1, quality=q, possible_minor=0, personal_details="[]", space="exterior", residential=0,
                      empty_room=0, sharp=1, light=4, moment=4, shot_type=room, classified_at=now)
            self.ids[did] = pid
        self.reels = []
        fake = mock.patch.dict(motion.REELS, {"rooms": self.fake_reel("rooms"), "facematch": self.fake_reel("facematch")})
        fake.start()
        self.addCleanup(fake.stop)

    def fake_reel(self, kind, fail=False):
        def job(shots_, copy, *, out, audio=None, only=None, encoder=None, official=False):
            if encoder:                                              # the stills: drawn frames, not the mp4
                return encoder((Image.new("RGB", (1080, 1920), (20, 20, 20)) for _ in only), out)
            self.reels.append((kind, [s.room for s in shots_], audio))
            if fail:
                raise RuntimeError("ffmpeg stopped with code 1; no reel made")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"mp4")
            return out
        return job

    def ctx(self):
        config.get_config().ensure_dirs()
        return runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), True, 0)

    def fetch(self, row):
        self.fetched.append(row["drive_id"])
        return jpeg_bytes(seed=len(self.fetched), size=(3000, 2000))

    def queue(self):
        return db.rows(self.conn, "SELECT * FROM content_queue ORDER BY id")

    def with_music(self):
        music.add(self.conn, "night.wav", tone(), **RECORD)
        return music.current(self.conn)

    def last(self):
        row = self.queue()[-1]
        return row, json.loads(row["rule_report"]), json.loads(row["render_paths"]), json.loads(row["photo_ids"])

    def test_with_a_track_saturday_is_a_reel_with_its_cover_pin_and_stills(self):
        track = self.with_music()
        line = content.draft_one(self.ctx(), self.fetch, now=FRIDAY)
        self.assertIn("reel with", line)
        _, meta_, renders, ids = self.last()
        self.assertEqual((meta_["design"], meta_["reel"], meta_["music"]), ("reel", "facematch", track.name))
        self.assertEqual(len(self.reels), 1)
        kind, rooms, audio = self.reels[0]
        self.assertEqual((kind, audio), ("facematch", track))
        self.assertEqual(sorted(rooms[:4]), ["BACKSTAGE", "MAIN STAGE", "ON THE FLOOR", "PORTRAITS"],
                         "one photo per room first; a room repeats only after every room has had one")
        self.assertEqual(ids[0], self.ids["e1"] if rooms[0] == "ON THE FLOOR" else self.ids["s1"])
        self.assertEqual(sorted(renders), ["2:3", "9:16", "cover", "stills"])
        self.assertTrue(renders["9:16"][0].endswith("-facematch.mp4"))
        self.assertTrue(Path(renders["cover"][0]).name.startswith("facematch-240"))
        self.assertEqual(len(ids), len(rooms))
        self.assertTrue(4 <= len(ids) <= 6)

    def test_without_a_track_saturday_is_a_single_photo_never_a_silent_reel(self):
        content.draft_one(self.ctx(), self.fetch, now=FRIDAY)
        _, meta_, renders, ids = self.last()
        self.assertEqual((meta_["design"], meta_["design_wanted"], len(ids)), ("single", "single", 1))
        self.assertEqual(self.reels, [])
        self.assertEqual(sorted(renders), ["2:3", "4:5"])

    def test_a_reel_that_cannot_be_made_is_a_carousel_of_the_same_photos_and_says_why(self):
        self.with_music()
        motion.REELS["facematch"] = self.fake_reel("facematch", fail=True)
        line = content.draft_one(self.ctx(), self.fetch, now=FRIDAY)
        self.assertIn("the reel could not be made", line)
        _, meta_, renders, ids = self.last()
        self.assertEqual(meta_["design"], "carousel")
        self.assertIn("ffmpeg stopped", meta_["reel_failed"])
        self.assertEqual(len(renders["4:5"]), len(ids) + 3)
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "reel")

    def test_the_two_reels_take_turns_by_week(self):
        self.assertEqual(content.reel_kind(datetime(2026, 10, 17).date()), "facematch")    # ISO week 42
        self.assertEqual(content.reel_kind(datetime(2026, 10, 24).date()), "rooms")        # ISO week 43

    def test_the_art_director_never_gets_the_mp4(self):
        seen = []
        with mock.patch.object(art_director, "look", lambda conn, files, **kw: seen.extend(files) or {"verdict": "pass", "notes": "ok"}):
            art_director.direct(self.conn, lambda f: {"9:16": [str(self.root / "r.mp4")], "cover": [str(self.root / "c.jpg")],
                                                      "2:3": [str(self.root / "p.jpg")], "stills": [str(self.root / "s.jpg")]},
                                dry_run=False, allow_redo=False, max_files=4)
        self.assertEqual([p.name for p in seen], ["c.jpg", "p.jpg", "s.jpg"])


# ------------------------------------------------------------------ the dashboard plays it

class Dashboard(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.conn = db.connect()
        folder = config.get_config().data_root / "renders"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "r.mp4").write_bytes(bytes(range(256)) * 40)
        renders = {"9:16": [str(folder / "r.mp4")], "cover": [write_render(folder, "cover.jpg")],
                   "2:3": [write_render(folder, "pin.jpg")], "stills": [write_render(folder, "still.jpg")]}
        self.qid = add_post(self.conn, [add_photo(self.conn, self.root / "photos")], render_paths=renders, status="draft")

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_the_draft_plays_the_reel_with_its_cover_and_shows_the_pin(self):
        for url in (f"/queue/{self.qid}", "/"):
            page = self.client.get(url).text
            self.assertIn(f'<video class="reel" src="/media/render/{self.qid}/9x16/1" poster="/media/render/{self.qid}/cover/1"', page)
            self.assertIn(f'/media/render/{self.qid}/2x3/1', page)
            self.assertNotIn(f'/media/render/{self.qid}/stills/1', page)

    def test_the_video_is_served_as_video_and_seeks(self):
        r = self.client.get(f"/media/render/{self.qid}/9x16/1")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "video/mp4"))
        part = self.client.get(f"/media/render/{self.qid}/9x16/1", headers={"Range": "bytes=0-99"})
        self.assertEqual((part.status_code, len(part.content)), (206, 100))          # Safari needs ranges to play
        self.assertEqual(self.client.get(f"/media/render/{self.qid}/cover/1").headers["content-type"], "image/jpeg")
