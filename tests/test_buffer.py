"""The Buffer client, request budget, payload shapes, media hosting and the metrics pull. No network."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from convention_social.buffer import budget, media, metrics, payloads
from convention_social.buffer.client import (BufferBudgetExceeded, BufferClient, BufferError, BufferRateLimited)
from convention_social.core import config, db, settings
from tests._fakes import AgentCase, FakeBuffer, add_channels, make_ctx
from tests._photos import jpeg_bytes

URLS = ["https://media.example/a.jpg", "https://media.example/b.jpg"]


class Client(AgentCase):
    def test_discovery_caches_channels_and_meters_requests(self):
        conn = self.connect()
        fake = FakeBuffer()
        chans = BufferClient("test-key", conn=conn, transport=fake).channels()
        self.assertTrue(chans)
        self.assertEqual([c["service"] for c in chans], ["instagram", "facebook", "pinterest"])
        self.assertEqual(len(fake.calls), 2)  # organizations + channels
        self.assertEqual(len(BufferClient("test-key", conn=conn, transport=fake).channels()), 3)
        self.assertEqual(len(fake.calls), 2, "the cache served the second lookup")
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='buffer'")["n"], 2)

    def test_create_post_needs_a_positive_success_shape(self):
        conn = self.connect()
        c = BufferClient("test-key", conn=conn, transport=FakeBuffer())
        self.assertEqual(c.create_post({"channelId": "ch-ig", "text": "x", "assets": [], "mode": "shareNow",
                                        "schedulingType": "automatic", "tagIds": [], "needsApproval": False}), "post-1")
        with self.assertRaises(BufferError) as cm:
            BufferClient("test-key", conn=conn, transport=FakeBuffer(reject_at={1})).create_post({"channelId": "x"})
        self.assertIn("board not found", str(cm.exception))

    def test_429_and_http_errors_raise_typed_errors(self):
        conn = self.connect()
        with self.assertRaises(BufferRateLimited) as cm:
            BufferClient("test-key", conn=conn, transport=FakeBuffer(http_status=429, retry_after=77)).organization_id()
        self.assertEqual(cm.exception.retry_after, 77)
        with self.assertRaises(BufferError):
            BufferClient("test-key", conn=conn, transport=FakeBuffer(http_status=500)).organization_id()

    def test_budget_stops_at_80_percent_of_the_smallest_window(self):
        conn = self.connect()
        os.environ["BUFFER_PLAN"] = "free"
        config.reset()
        for _ in range(79):
            budget.record(conn, "test", "x")
        self.assertTrue(budget.allow(conn)[0])
        budget.record(conn, "test", "x")
        ok, why = budget.allow(conn)
        self.assertFalse(ok)
        self.assertIn("15m", why)
        with self.assertRaises(BufferBudgetExceeded):
            BufferClient("test-key", conn=conn, transport=FakeBuffer()).organization_id()
        snap = budget.snapshot(conn)
        self.assertTrue(snap)
        self.assertEqual([s["limit"] for s in snap], [100, 250, 3000])
        old = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
        conn.execute("UPDATE api_usage SET ts=?", (old,))
        self.assertTrue(budget.allow(conn)[0], "old requests age out of the 15m window")

    def test_posts_boards_and_post_info(self):
        conn = self.connect()
        c = BufferClient("test-key", conn=conn, transport=FakeBuffer(status_sequence=["error"]))
        nodes, page = c.posts(status="sent")
        self.assertTrue(nodes)
        self.assertEqual(nodes[0]["metrics"][0]["value"], 4)
        self.assertFalse(page["hasNextPage"])
        boards = c.pinterest_boards("ch-pin")
        self.assertTrue(boards)
        self.assertEqual(boards[0]["serviceId"], "board-123")
        info = c.post_info("post-9")
        self.assertEqual((info["status"], info["error"]), ("error", "Image could not be fetched"))


class Payloads(AgentCase):
    def test_instagram_and_facebook_shapes(self):
        i = payloads.build("instagram", "ch-ig", "hi", URLS)
        self.assertTrue(i)
        self.assertEqual(i["metadata"], {"instagram": {"type": "carousel", "shouldShareToFeed": True}})
        self.assertEqual(i["mode"], "shareNow")
        self.assertNotIn("dueAt", i)
        self.assertEqual(i["assets"], [{"image": {"url": u}} for u in URLS])
        self.assertEqual(payloads.build("instagram", "ch-ig", "hi", URLS[:1])["metadata"]["instagram"]["type"], "post")
        f = payloads.build("facebook", "ch-fb", "hi", URLS[:1], scheduled_for="2026-10-09T09:30")
        self.assertEqual(f["mode"], "customScheduled")
        self.assertEqual(f["dueAt"], "2026-10-09T13:30:00Z")  # New York EDT -> UTC
        self.assertEqual(f["metadata"], {"facebook": {"type": "post"}})
        for p in (i, f):
            self.assertEqual((p["schedulingType"], p["needsApproval"], p["tagIds"]), ("automatic", False, []))

    def test_pinterest_shape_board_title_and_link(self):
        text = "Cosplay portraits in the vendor hall, early on day one. More to come. #cosplay #eventphotography"
        p = payloads.build("pinterest", "ch-pin", text, URLS, scheduled_for="2026-12-05T20:30",
                           board_id="board-123", link="https://quote.example/")
        self.assertTrue(p["metadata"])
        pin = p["metadata"]["pinterest"]
        self.assertEqual(set(pin), {"boardServiceId", "title", "url"})
        self.assertEqual(pin["boardServiceId"], "board-123")
        self.assertEqual(pin["title"], "Cosplay portraits in the vendor hall, early on day one.")
        self.assertEqual(pin["url"], "https://quote.example/")
        self.assertEqual(len(p["assets"]), 1, "one image per pin")
        self.assertEqual(p["dueAt"], "2026-12-06T01:30:00Z")  # EST in December
        self.assertNotIn("url", payloads.build("pinterest", "ch-pin", text, URLS, board_id="b")["metadata"]["pinterest"])
        with self.assertRaises(payloads.PayloadError):
            payloads.build("pinterest", "ch-pin", text, URLS)
        with self.assertRaises(payloads.PayloadError):
            payloads.build("googlebusiness", "ch-x", text, URLS)

    def test_pin_title_is_short_and_has_no_hashtags(self):
        long = "word " * 60 + "#tag"
        title = payloads.pin_title(long)
        self.assertTrue(title)
        self.assertLessEqual(len(title), payloads.PIN_TITLE_MAX)
        self.assertNotIn("#", title)
        self.assertEqual(payloads.pin_title("#only #tags", "Event Caliber"), "Event Caliber")


class Media(AgentCase):
    def test_without_a_host_dry_urls_use_a_placeholder_and_live_refuses(self):
        self.assertFalse(media.configured())
        key = media.photo_key("drive-1", "md5-1")
        self.assertTrue(key.startswith("convention-social/photos/"))
        self.assertNotIn("drive-1", key, "the Drive id is not exposed in a public URL")
        self.assertTrue(media.public_url(key).startswith(media.PLACEHOLDER_BASE))
        with self.assertRaises(media.MediaError):
            media.upload(self.root / "x.jpg", key)
        with self.assertRaises(media.MediaError):
            media.upload(self.root / "x.jpg", "private/backups/x")

    def test_worker_upload_sends_the_token_and_the_type(self):
        os.environ.update({"MEDIA_BASE_URL": "https://media.example/m/", "MEDIA_UPLOAD_TOKEN": "tok"})
        config.reset()
        f = self.root / "p.jpg"
        f.write_bytes(jpeg_bytes(seed=3))
        calls = []

        class Ok:
            status_code = 201

        def put(url, data=None, timeout=None, headers=None):
            calls.append((url, len(data), headers))
            return Ok()
        url = media.upload(f, media.card_key(7, "4:5"), put=put)
        self.assertTrue(calls)
        self.assertEqual(url, "https://media.example/m/convention-social/cards/7-45-1.jpg")
        self.assertEqual(calls[0][0], url)
        self.assertEqual(calls[0][2], {"Authorization": "Bearer tok", "Content-Type": "image/jpeg"})

    def test_bucket_upload_uses_bucket_and_public_base(self):
        os.environ.update({"R2_ENDPOINT": "https://acct.r2.example", "R2_BUCKET": "bucket-x",
                           "R2_PUBLIC_BASE": "https://pub.example/", "R2_KEY": "k", "R2_SECRET": "s"})
        config.reset()
        calls = []

        class FakeS3:
            def upload_file(self, path, bucket, key, ExtraArgs=None):
                calls.append((bucket, key, ExtraArgs))
        f = self.root / "p.png"
        f.write_bytes(b"\x89PNG")
        url = media.upload(f, "convention-social/photos/abc.png", client=FakeS3())
        self.assertTrue(calls)
        self.assertEqual(url, "https://pub.example/convention-social/photos/abc.png")
        self.assertEqual(calls[0], ("bucket-x", "convention-social/photos/abc.png", {"ContentType": "image/png"}))


def node(pid, channel, service, sent_days_ago, **m):
    sent = (datetime.now(timezone.utc) - timedelta(days=sent_days_ago)).isoformat()
    return {"id": pid, "channelId": channel, "channelService": service, "status": "sent", "sentAt": sent, "text": f"post {pid}",
            "metricsUpdatedAt": sent, "metrics": [{"type": k, "name": k, "value": v, "unit": "count"} for k, v in m.items()]}


class FakePosts:
    def __init__(self, nodes):
        self.nodes = nodes
        self.calls = []

    def posts(self, *, status="sent", channel_ids=None, first=50, after=None):
        self.calls.append(sorted(channel_ids or []))
        return [n for n in self.nodes if n["channelId"] in (channel_ids or [])], {"hasNextPage": False, "endCursor": None}


class Metrics(AgentCase):
    def seed(self):
        conn = self.connect()
        add_channels(conn, "instagram", "facebook", "pinterest")
        db.insert(conn, "post_history", buffer_post_id="p-ours", service="instagram", sent_at=db.utcnow(), caption="ours")
        fake = FakePosts([node("p-ours", "ch-ig", "instagram", 3, likes=40, comments=5, saves=2, reach=1200, impressions=1500),
                          node("p-old", "ch-fb", "facebook", 200, reactions=3, reach=90),
                          node("p-pin", "ch-pin", "pinterest", 1, saves=12, impressions=2600, clicks=31)])
        return conn, fake

    def test_one_pull_over_every_channel_flags_ours(self):
        conn, fake = self.seed()
        ctx = make_ctx(conn, agent="watchdog")
        today = date(2026, 10, 9)
        self.assertTrue(metrics.due(conn, today))
        stats = metrics.pull(ctx, fake, today=today)
        self.assertEqual(fake.calls, [["ch-fb", "ch-ig", "ch-pin"]], "one query over every channel in the table")
        self.assertEqual((stats["channels"], stats["posts"], stats["ours"], stats["errors"]), (3, 3, 1, 0))
        rows = {r["buffer_post_id"]: dict(r) for r in db.rows(conn, "SELECT * FROM post_metrics")}
        self.assertTrue(rows)
        self.assertEqual((rows["p-ours"]["ours"], rows["p-old"]["ours"]), (1, 0))
        self.assertEqual(rows["p-pin"]["service"], "pinterest")
        self.assertEqual(json.loads(rows["p-pin"]["metrics"])["saves"], 12.0)
        self.assertEqual(json.loads(db.one(conn, "SELECT metrics FROM post_history WHERE buffer_post_id='p-ours'")["metrics"])["reach"], 1200.0)
        self.assertFalse(metrics.due(conn, today))
        metrics.pull(ctx, fake, today=today)
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM post_metrics")["n"], 3, "a second pull the same day updates in place")
        conn.close()

    def test_summary_and_trend_count_only_our_posts(self):
        conn, fake = self.seed()
        db.insert(conn, "post_history", buffer_post_id="p-pin", service="pinterest", sent_at=db.utcnow(), caption="ours too")
        metrics.pull(make_ctx(conn, agent="watchdog"), fake)
        s = metrics.summary(conn, days=30)
        self.assertEqual(s["totals"]["posts"], 2)
        self.assertEqual(s["totals"]["engagement"], 40 + 5 + 2 + 12)
        self.assertEqual(s["totals"]["clicks"], 31.0)
        self.assertEqual(set(s["per_network"]), {"instagram", "pinterest"})
        self.assertEqual(s["best"]["buffer_post_id"], "p-ours")
        weeks = metrics.trend(conn)
        self.assertEqual(len(weeks), 12)
        self.assertEqual(sum(w["posts"] for w in weeks), 2)
        conn.close()

    def test_no_channels_no_call(self):
        conn = self.connect()
        fake = FakePosts([])
        stats = metrics.pull(make_ctx(conn, agent="watchdog"), fake, today=date(2026, 10, 9))
        self.assertEqual((fake.calls, stats["channels"]), ([], 0))
        self.assertEqual(settings.get(conn, metrics.PULLED_KEY), "2026-10-09")
        conn.close()
