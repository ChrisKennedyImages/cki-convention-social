"""The Buffer client, request budget, payload shapes, media hosting and the metrics pull. No network."""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone

from convention_social.buffer import budget, media, metrics, payloads
from convention_social.buffer.client import (BufferBudgetExceeded, BufferClient, BufferError, BufferRateLimited)
from convention_social.core import config, db, settings, state_io
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

    def test_the_organization_is_remembered_with_the_channels_so_an_hourly_call_costs_one_request(self):
        """2026-10-24 audit: the watchdog's hourly channel refresh and the publisher's hourly reconcile each asked
        Organizations first: 128 requests in a day of the 200 ceiling, nearly half of them that one question. The
        channel cache keeps the organization with the key's fingerprint; another key is another account, asked afresh."""
        conn = self.connect()
        fake = FakeBuffer()
        ops = lambda f: [re.match(r"\w+ (\w+)", c[0]).group(1) for c in f.calls]  # noqa: E731  the operations' names
        BufferClient("test-key", conn=conn, transport=fake).channels()
        self.assertEqual(ops(fake), ["Organizations", "Channels"], "the first time: who am I, then the channels")
        fake.calls.clear()
        BufferClient("test-key", conn=conn, transport=fake).channels(refresh=True)          # the watchdog, an hour later
        self.assertEqual(ops(fake), ["Channels"])
        fake.calls.clear()
        BufferClient("test-key", conn=conn, transport=fake).posts(status="sent")            # the publisher's reconcile
        self.assertEqual(ops(fake), ["Posts"])
        other = FakeBuffer(api_key="another-key")
        BufferClient("another-key", conn=conn, transport=other).channels(refresh=True)
        self.assertEqual(ops(other), ["Organizations", "Channels"], "another key is another account")
        cached = state_io.load_json(BufferClient.cache_path(), {})
        self.assertNotIn("another-key", json.dumps(cached), "the cache names the key by its fingerprint, never the key")

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
        self.assertEqual((info["status"], info["error"], info["external_link"]), ("error", "Image could not be fetched", None))
        sent = BufferClient("test-key", conn=conn, transport=FakeBuffer(status_sequence=["sent"])).post_info("post-9")
        self.assertEqual(sent["external_link"], "https://www.instagram.com/p/abc123/", "7.1 (2026-10-13): the live link is kept")

    def test_delete_post_reads_the_input_shape_from_the_live_schema(self):
        """7.5: pulling a scheduled post back from Buffer, with the mutation's input read from the schema, never recalled."""
        conn = self.connect()
        fake = FakeBuffer()
        c = BufferClient("test-key", conn=conn, transport=fake)
        self.assertTrue(c.delete_post("post-7"))
        self.assertEqual(fake.deleted, ["post-7"])
        self.assertIn(("DeletePostInput",), [(v.get("name"),) for op, v in fake.calls if "InputType" in op])
        from tests._fakes import SCHEMA, field
        odd = FakeBuffer(schema={**SCHEMA, "DeletePostInput": [field("postId", "PostId", True, "SCALAR")]})
        with self.assertRaises(BufferError):
            BufferClient("test-key", conn=conn, transport=odd).delete_post("post-7")
        self.assertEqual(odd.deleted, [], "a shape we did not expect: nothing is deleted blind")
        gone = FakeBuffer(schema={k: v for k, v in SCHEMA.items() if k != "DeletePostInput"})
        with self.assertRaises(BufferError):
            BufferClient("test-key", conn=conn, transport=gone).delete_post("post-7")
        refused = FakeBuffer(reject_at=("post-8",))
        with self.assertRaises(BufferError):
            BufferClient("test-key", conn=conn, transport=refused).delete_post("post-8")
        self.assertEqual(refused.deleted, [])

    def test_delete_post_reads_its_reply_from_the_live_schema(self):
        """2026-10-16: the pull back asked for a reply Buffer's deletePost never gives (PostActionSuccess; the live
        DeletePostPayload is DeletePostSuccess | VoidMutationError) and Buffer refused every pull back unread. The
        success member of the reply is read from the live schema like the input, never recalled."""
        from tests._fakes import member
        conn = self.connect()
        fake = FakeBuffer()
        self.assertTrue(BufferClient("test-key", conn=conn, transport=fake).delete_post("post-7"))
        self.assertEqual(fake.deleted, ["post-7"])
        self.assertIn("DeletePostPayload", [v.get("name") for op, v in fake.calls if "UnionType" in op])
        renamed = FakeBuffer(unions={"DeletePostPayload": [member("PostRemoved", ["id"]), member("VoidMutationError", ["message"], error=True)]})
        self.assertTrue(BufferClient("test-key", conn=conn, transport=renamed).delete_post("post-7"))
        self.assertEqual(renamed.deleted, ["post-7"], "whatever Buffer calls its success, it is read from the schema")
        for unions, why in (({"DeletePostPayload": [member("VoidMutationError", ["message"], error=True)]}, "no success member"),
                            ({"DeletePostPayload": [member("DeletePostSuccess", []), member("VoidMutationError", ["message"], error=True)]}, "success without the id"),
                            ({"DeletePostPayload": [member("A", ["id"]), member("B", ["id"])]}, "two successes to choose from"),
                            ({}, "no DeletePostPayload at all")):
            odd = FakeBuffer(unions=unions)
            with self.assertRaises(BufferError, msg=why):
                BufferClient("test-key", conn=conn, transport=odd).delete_post("post-7")
            self.assertEqual(odd.deleted, [], f"{why}: nothing is deleted blind")


class Payloads(AgentCase):
    def test_instagram_and_facebook_shapes(self):
        i = payloads.build("instagram", "ch-ig", "hi", URLS)
        self.assertTrue(i)
        self.assertEqual(i["metadata"], {"instagram": {"type": "post", "shouldShareToFeed": True}})
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

    def test_several_photos_on_instagram_are_a_post_with_several_assets_not_a_carousel(self):
        """2026-10-14, the first live night: Buffer refused post 4, a six-photo carousel, with "Instagram does
        not support the 'carousel' post type. Valid types are post, story, or reel." A carousel is a post."""
        six = [f"https://media.example/{n}.jpg" for n in range(6)]
        for urls in (six[:1], six[:2], six):
            inp = payloads.build("instagram", "ch-ig", "hi", urls)
            self.assertEqual(inp["metadata"]["instagram"]["type"], "post", f"{len(urls)} photo(s)")
            self.assertEqual([a["image"]["url"] for a in inp["assets"]], urls, "every photo still goes")
            self.assertNotIn("carousel", json.dumps(inp))

    def test_pinterest_shape_board_title_and_link(self):
        text = "Portraits in the vendor hall, early on day one. More to come. #portraits #eventphotography"
        p = payloads.build("pinterest", "ch-pin", text, URLS, scheduled_for="2026-12-05T20:30",
                           board_id="board-123", link="https://quote.example/")
        self.assertTrue(p["metadata"])
        pin = p["metadata"]["pinterest"]
        self.assertEqual(set(pin), {"boardServiceId", "title", "url"})
        self.assertEqual(pin["boardServiceId"], "board-123")
        self.assertEqual(pin["title"], "Portraits in the vendor hall, early on day one.")
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

    def test_a_failed_pull_is_not_marked_done_and_is_said_once(self):
        conn, fake = self.seed()

        class Broken:
            def posts(self, **kw):
                raise RuntimeError("rate limited")
        ctx = make_ctx(conn, agent="watchdog")
        today = date(2026, 10, 9)
        stats = metrics.pull(ctx, Broken(), today=today)
        self.assertEqual(stats["errors"], 1)
        self.assertTrue(metrics.due(conn, today), "a pull that failed is tried again, not marked done")
        self.assertEqual(db.one(conn, "SELECT kind FROM errors")["kind"], "metrics_pull")
        metrics.pull(ctx, Broken(), today=today)
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM errors")["n"], 1, "said once while it stands")
        metrics.pull(ctx, fake, today=today)
        self.assertFalse(metrics.due(conn, today))
        conn.close()

    def test_no_channels_no_call(self):
        conn = self.connect()
        fake = FakePosts([])
        stats = metrics.pull(make_ctx(conn, agent="watchdog"), fake, today=date(2026, 10, 9))
        self.assertEqual((fake.calls, stats["channels"]), ([], 0))
        self.assertEqual(settings.get(conn, metrics.PULLED_KEY), "2026-10-09")
        conn.close()
