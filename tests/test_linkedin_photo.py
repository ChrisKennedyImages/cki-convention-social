"""On LinkedIn the photo alone (2026-11-01 evening). The coordinator: "On a personal profile, the photo alone with your
caption may read more like you and less like an ad. Instagram would stay as it is." Chris: "Let's do that." LinkedIn is
sent the hero as shot, in its own aspect ratio, no card; the other networks' cards are what they were; the draft page
shows the bare photo for LinkedIn while the lane is on."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from convention_social.agents import publisher
from convention_social.buffer.client import BufferClient
from convention_social.core import auth, config, db
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import meta, photo
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_channels, add_photo, add_post, all_eligible, make_ctx, write_render
from tests._photos import jpeg_bytes

FRIDAY_8AM = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


class AsShot(IsolatedCase):
    def test_the_photo_whole_in_its_own_aspect_clean_and_under_the_limits(self):
        src = Image.open(__import__("io").BytesIO(jpeg_bytes(seed=3, size=(3000, 2000))))
        out = photo.as_shot(src, self.root / "li.jpg", meta=meta.ImageMeta(title="Event photography"))
        with Image.open(out) as im:
            self.assertEqual(im.size, (3000, 2000), "as shot: no crop, no card")
        self.assertEqual(meta.is_clean(out), [])
        self.assertIn(b"Event photography", out.read_bytes(), "our search fields travel in the file")
        self.assertLessEqual(out.stat().st_size, photo.MAX_BYTES)

    def test_a_portrait_keeps_its_orientation_and_aspect(self):
        src = Image.open(__import__("io").BytesIO(jpeg_bytes(seed=4, size=(2000, 3000))))
        with Image.open(photo.as_shot(src, self.root / "p.jpg")) as im:
            self.assertEqual(im.size, (2000, 3000))

    def test_too_many_pixels_shrinks_the_picture_not_its_shape(self):
        with mock.patch.object(photo, "MAX_PIXELS", 1_000_000):
            src = Image.new("RGB", (3000, 2000), (90, 120, 150))
            with Image.open(photo.as_shot(src, self.root / "big.jpg")) as im:
                self.assertLessEqual(im.width * im.height, 1_000_000)
                self.assertAlmostEqual(im.width / im.height, 1.5, places=2, msg="the aspect ratio stands")

    def test_too_many_bytes_lowers_the_quality_then_the_size(self):
        import random
        rng = random.Random(7)
        noisy = Image.frombytes("RGB", (1200, 800), bytes(rng.getrandbits(8) for _ in range(1200 * 800 * 3)))
        with mock.patch.object(photo, "MAX_BYTES", 300_000):
            out = photo.as_shot(noisy, self.root / "noisy.jpg")
            self.assertLessEqual(out.stat().st_size, 300_000)
            with Image.open(out) as im:
                self.assertAlmostEqual(im.width / im.height, 1.5, places=2)


class WhatGoesOut(IsolatedCase):
    """Verified at the consumer: what the publisher uploads and sends for each network."""

    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,facebook,linkedin"
        config.reset()
        p = mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible())
        p.start()
        self.addCleanup(p.stop)
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        add_channels(self.conn, "instagram", "facebook", "linkedin")
        self.pid = add_photo(self.conn, self.root / "photos", seed=1)
        self.conn.execute("UPDATE photos SET prominent_logo=0 WHERE id=?", (self.pid,))
        self.renders = {"4:5": [write_render(self.root / "renders", "card-45.jpg")], "2:3": [write_render(self.root / "renders", "card-23.jpg")],
                        photo.LINKEDIN_PHOTO: [write_render(self.root / "renders", "hero-as-shot.jpg")]}
        self.qid = add_post(self.conn, [self.pid], ("instagram", "facebook", "linkedin"), render_paths=self.renders)

    def test_linkedin_is_sent_the_photo_file_and_the_others_their_cards(self):
        uploads = {}

        def up(path, key):
            uploads[key] = Path(path).name
            return f"https://media.example/m/{key}"
        fake = FakeBuffer()
        stats = publisher.publish_ready(make_ctx(self.conn, dry_run=False), client=BufferClient("test-key", conn=self.conn, transport=fake),
                                        uploader=up, now=FRIDAY_8AM)
        self.assertEqual(stats["scheduled"], 1)
        sent = {c["channelId"]: c for c in fake.created}
        li, ig, fb = sent["ch-li"], sent["ch-ig"], sent["ch-fb"]
        self.assertEqual(len(li["assets"]), 1)
        li_key = li["assets"][0]["image"]["url"].split("/m/", 1)[1]
        self.assertEqual(uploads[li_key], "hero-as-shot.jpg", "the photo as shot, not a card")
        ig_key = ig["assets"][0]["image"]["url"].split("/m/", 1)[1]
        self.assertEqual(uploads[ig_key], "card-45.jpg", "Instagram keeps its 4:5 design")
        self.assertEqual(fb["assets"][0]["image"]["url"], ig["assets"][0]["image"]["url"], "Facebook shares the 4:5 design, as before")
        self.assertNotIn("metadata", li)
        self.assertEqual(publisher.ASPECT_FOR["linkedin"], photo.LINKEDIN_PHOTO)


class Page(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        pid = add_photo(self.conn, self.root / "photos", seed=1)
        renders = {"4:5": [write_render(self.root / "renders", "card-45.jpg")], photo.LINKEDIN_PHOTO: [write_render(self.root / "renders", "hero.jpg")]}
        self.qid = add_post(self.conn, [pid], ("instagram", "linkedin"), status="draft", render_paths=renders)

    def page(self):
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        return client.get(f"/queue/{self.qid}").text

    def test_the_draft_page_shows_the_bare_photo_while_linkedin_is_on(self):
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        page = self.page()
        self.assertIn(f"/media/render/{self.qid}/linkedin/1", page)
        self.assertIn(f"/media/render/{self.qid}/4x5/1", page)
        os.environ["POST_NETWORKS"] = "instagram"
        config.reset()
        self.assertNotIn("/linkedin/1", self.page(), "the lane off: the photo is not shown")
