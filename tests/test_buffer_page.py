"""The Buffer page: the plumbing that turns a Buffer key into linked channels, a Pinterest board and a
checked reel format. Chris, 2026-10-11: "get the plumbing in so we can just add it quickly when I do".
Nothing is linked by itself, and a key that sees several organizations posts nowhere until one is chosen."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import publisher
from convention_social.buffer.client import BufferClient, BufferError
from convention_social.core import auth, config, db, settings
from convention_social.dashboard import app as app_module
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_photo, add_post, all_eligible, field, make_ctx, write_render


class Page(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        os.environ["BUFFER_API_KEY"] = "test-key"
        os.environ["POST_NETWORKS"] = "instagram,facebook,pinterest"     # each network's Use is pinned; Instagram only by default since 2026-10-15
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.fake = FakeBuffer()
        patcher = mock.patch.object(app_module, "buffer_client",
                                    lambda conn: BufferClient("test-key", conn=conn, transport=self.fake, agent="dashboard"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def post(self, url, **data):
        r = self.client.post(url, data=data, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        return self.client.get(r.headers["location"]).text

    def linked(self):
        return {r["service"]: r["buffer_channel_id"] for r in db.rows(self.conn, "SELECT * FROM channels")}

    def ops(self):
        return [op.split("(")[0].split()[-1] for op, _ in self.fake.calls]

    def test_with_no_key_the_page_says_how_to_start(self):
        os.environ.pop("BUFFER_API_KEY")
        with mock.patch.object(app_module, "buffer_client", lambda conn: None):
            page = self.client.get("/buffer").text
            self.assertIn("Set up, once", page)
            self.assertIn("publish.buffer.com/settings/api", page)
            self.assertIn("Paste the Buffer API key on the Keys page first.", self.post("/buffer/find"))
        self.assertEqual(self.fake.calls, [])

    def test_find_lists_the_channels_and_links_none_by_itself(self):
        page = self.post("/buffer/find")
        self.assertIn("Found 3 channel(s) in Buffer.", page)
        for svc in ("Instagram", "Facebook", "Pinterest"):
            self.assertIn(f"Use for {svc}", page)
        self.assertEqual(self.linked(), {}, "nothing is linked until Chris taps Use")

    def test_use_links_one_channel_per_network_and_the_publisher_posts_there(self):
        self.fake.channels.append(("instagram", "ch-ig-2", "Someone else's Instagram"))
        self.post("/buffer/find")
        page = self.post("/buffer/link", channel_id="ch-ig")
        self.assertIn("Instagram posts go to Event Caliber instagram.", page)
        self.post("/buffer/link", channel_id="ch-fb")
        self.assertEqual(self.linked(), {"instagram": "ch-ig", "facebook": "ch-fb"})
        self.post("/buffer/link", channel_id="ch-ig-2")
        self.assertEqual(self.linked()["instagram"], "ch-ig-2", "one channel per network: the new choice replaces the old")
        self.post("/buffer/link", channel_id="ch-ig")
        self.assertIn("not one Buffer listed", self.post("/buffer/link", channel_id="ch-made-up"))
        self.assertEqual(self.linked(), {"instagram": "ch-ig", "facebook": "ch-fb"})
        # verified at the consumer: an approved post now goes to exactly the channels linked here
        pid = add_photo(self.conn, self.root / "photos")
        qid = add_post(self.conn, [pid], ("instagram", "facebook"), render_paths={"4:5": [write_render(self.root / "data" / "r", "a.jpg")]})
        with mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible()):
            publisher.publish_ready(make_ctx(self.conn), now=datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
        sent = json.loads(db.one(self.conn, "SELECT payload FROM content_queue WHERE id=?", (qid,))["payload"])
        self.assertEqual({n: p["channelId"] for n, p in sent.items()}, {"instagram": "ch-ig", "facebook": "ch-fb"})
        self.assertIn("Nothing goes to facebook now.", self.post("/buffer/unlink", service="facebook"))
        self.assertEqual(self.linked(), {"instagram": "ch-ig"})

    def test_a_key_that_sees_two_organizations_posts_nowhere_until_one_is_chosen(self):
        self.fake.orgs = [{"id": "org-a", "name": "Another company"}, {"id": "org-b", "name": "Event Caliber"}]
        page = self.post("/buffer/find")
        self.assertIn("This key sees 2 Buffer organizations", page)
        self.assertNotIn("Channels", self.ops(), "no channel is listed before the choice")
        self.assertNotIn("Use for", page)
        self.assertIn("Which Buffer organization is this company", page)
        self.assertIn("Using Event Caliber.", self.post("/buffer/org", org_id="org-b"))
        self.assertEqual(config.getenv("BUFFER_ORGANIZATION_ID"), "org-b")
        self.post("/buffer/find")
        asked = [v for op, v in self.fake.calls if "Channels" in op]
        self.assertEqual(asked[-1], {"input": {"organizationId": "org-b"}})
        self.post("/buffer/link", channel_id="ch-ig")
        self.assertIn("not one this key sees", self.post("/buffer/org", org_id="org-made-up"))
        self.post("/buffer/org", org_id="org-a")
        self.assertEqual(self.linked(), {}, "channels linked under another organization are unlinked")

    def test_the_client_refuses_to_guess_between_organizations(self):
        fake = FakeBuffer(orgs=[{"id": "org-a", "name": "A"}, {"id": "org-b", "name": "B"}])
        with self.assertRaises(BufferError):
            BufferClient("test-key", conn=self.conn, transport=fake).channels(refresh=True)
        config.write_env({"BUFFER_ORGANIZATION_ID": "org-b"})
        fake.calls.clear()
        BufferClient("test-key", conn=self.conn, transport=fake).channels(refresh=True)
        self.assertEqual([v for _, v in fake.calls], [{"input": {"organizationId": "org-b"}}], "the choice, without asking again")

    def test_the_pinterest_board_comes_from_buffers_own_list(self):
        self.post("/buffer/find")
        self.post("/buffer/link", channel_id="ch-pin")
        self.assertIn("Found 1 board(s).", self.post("/buffer/boards"))
        self.assertIn("not one Buffer listed", self.post("/buffer/board", board_id="board-made-up"))
        self.assertIsNone(config.getenv("PINTEREST_BOARD_ID"))
        self.assertIn("Pins go to the board Conventions.", self.post("/buffer/board", board_id="board-123"))
        self.assertEqual(config.getenv("PINTEREST_BOARD_ID"), "board-123")

    def test_the_video_check_feeds_the_publishers_dry_run(self):
        self.fake.schema = {"AssetInput": [field("video", "VideoAssetInput")],
                            "VideoAssetInput": [field("url", "String", True, "SCALAR"), field("thumbnail", "String", False, "SCALAR")]}
        self.assertIn("Reels can post", self.post("/buffer/video"))
        self.assertIn("url (required), thumbnail", self.client.get("/buffer").text)
        # the dry run builds the reel by what Buffer said, and no longer says it assumed
        self.post("/buffer/find")
        self.post("/buffer/link", channel_id="ch-ig")
        folder = config.get_config().data_root / "r"
        folder.mkdir(parents=True)
        (folder / "v.mp4").write_bytes(b"mp4")
        pid = add_photo(self.conn, self.root / "photos")
        qid = add_post(self.conn, [pid], ("instagram",), render_paths={"9:16": [str(folder / "v.mp4")], "cover": [write_render(folder, "c.jpg")]})
        with mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible()):
            publisher.publish_ready(make_ctx(self.conn), now=datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
        row = db.one(self.conn, "SELECT payload, last_error FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(sorted(json.loads(row["payload"])["instagram"]["assets"][0]["video"]), ["thumbnail", "url"])
        self.assertIsNone(row["last_error"])

    def test_a_video_format_this_suite_cannot_fill_is_said_plainly(self):
        self.fake.schema = {"AssetInput": [field("video", "VideoAssetInput")],
                            "VideoAssetInput": [field("url", "String", True, "SCALAR"), field("durationMs", "Int", True, "SCALAR")]}
        self.assertIn("needs something this suite does not fill yet", self.post("/buffer/video"))
        self.assertIn("durationMs", json.loads(settings.get(self.conn, "buffer.video_fields"))["problem"])
        self.assertIn("needs a change", self.client.get("/buffer").text)

    def test_buffer_refusing_is_shown_not_crashed(self):
        self.fake.http_status = 401
        self.assertIn("Buffer said: Buffer HTTP 401", self.post("/buffer/find"))

    def test_the_page_is_on_the_more_tab(self):
        self.assertIn('href="/buffer"', self.client.get("/more").text)
        self.assertEqual(self.client.get("/buffer", follow_redirects=False).status_code, 200)
        anon = TestClient(create_app())
        self.assertNotEqual(anon.get("/buffer", follow_redirects=False).status_code, 200)
        self.assertNotEqual(anon.post("/buffer/link", data={"channel_id": "ch-ig"}, follow_redirects=False).status_code, 303)
