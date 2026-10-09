"""The publisher: dry run payloads for all three networks, the door, live publish and verify. No network."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest import mock

from convention_social.agents import publisher
from convention_social.buffer import budget, media
from convention_social.buffer.client import BufferClient
from convention_social.core import config, db, runner
from tests._fakes import (AgentCase, FakeBuffer, add_channels, add_photo, add_post, all_eligible, eligibility, make_ctx,
                          write_render)

FRIDAY_8AM = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)      # 08:00 New York


class PublisherCase(AgentCase):
    def setUp(self):
        super().setUp()
        os.environ["PINTEREST_BOARD_ID"] = "board-123"
        config.reset()
        self.elig = all_eligible()
        self.use_eligibility(self.elig)
        self.conn = self.connect()
        add_channels(self.conn, "instagram", "facebook", "pinterest")

    def use_eligibility(self, module):
        p = mock.patch.object(publisher, "_eligibility_module", return_value=module)
        p.start()
        self.addCleanup(p.stop)

    def row(self, qid):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))

    def rendered_post(self, seed=1, **kw):
        pid = add_photo(self.conn, self.root / "photos", seed=seed)
        renders = {"4:5": [write_render(self.root / "renders", f"r{seed}-45.jpg")],
                   "2:3": [write_render(self.root / "renders", f"r{seed}-23.jpg")]}
        return pid, add_post(self.conn, [pid], render_paths=renders, **kw)

    def publish(self, ctx, **kw):
        return publisher.publish_ready(ctx, now=FRIDAY_8AM, **kw)


class DryRun(PublisherCase):
    def test_exact_payloads_for_all_three_networks_and_nothing_sent(self):
        pid, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=True)
        fake = FakeBuffer()
        stats = self.publish(ctx, client=BufferClient("test-key", conn=self.conn, transport=fake))
        self.assertEqual(stats["would_publish"], 1)
        self.assertEqual(fake.calls, [], "a dry run never calls Buffer")
        row = self.row(qid)
        self.assertEqual(row["status"], "would_publish")
        self.assertEqual(row["dry_run"], 1)
        payload = json.loads(row["payload"])
        self.assertTrue(payload)
        self.assertEqual(set(payload), {"instagram", "facebook", "pinterest"})
        ig, fb, pin = payload["instagram"], payload["facebook"], payload["pinterest"]
        self.assertEqual((ig["channelId"], fb["channelId"], pin["channelId"]), ("ch-ig", "ch-fb", "ch-pin"))
        self.assertEqual(ig["metadata"], {"instagram": {"type": "post", "shouldShareToFeed": True}})
        self.assertEqual(fb["metadata"], {"facebook": {"type": "post"}})
        self.assertEqual(pin["metadata"]["pinterest"]["boardServiceId"], "board-123")
        self.assertEqual(pin["metadata"]["pinterest"]["title"], "Backstage before the keynote, calm and ready.")
        # each network at its own time, one per day: 11:30, 09:30 and 20:30 New York
        self.assertEqual((ig["mode"], ig["dueAt"]), ("customScheduled", "2026-10-09T15:30:00Z"))
        self.assertEqual(fb["dueAt"], "2026-10-09T13:30:00Z")
        self.assertEqual(pin["dueAt"], "2026-10-10T00:30:00Z")
        # rendered designs: 4:5 to Instagram and Facebook, 2:3 to Pinterest, at the URL a live run would upload to
        self.assertEqual(ig["assets"], [{"image": {"url": f"{media.PLACEHOLDER_BASE}/convention-social/cards/{qid}-45-1.jpg"}}])
        self.assertEqual(fb["assets"], ig["assets"])
        self.assertEqual(pin["assets"], [{"image": {"url": f"{media.PLACEHOLDER_BASE}/convention-social/cards/{qid}-23-1.jpg"}}])
        self.assertIn("Request a quote", ig["text"])
        self.assertIsNone(db.one(self.conn, "SELECT public_url FROM photos WHERE id=?", (pid,))["public_url"], "no upload in dry run")
        self.assertEqual(self.elig.calls, [pid], "the door asked about the photo")

    def test_without_designs_the_photo_itself_goes(self):
        pid = add_photo(self.conn, self.root / "photos", seed=2)
        qid = add_post(self.conn, [pid], ("instagram",))
        self.publish(make_ctx(self.conn))
        payload = json.loads(self.row(qid)["payload"])
        self.assertTrue(payload)
        key = media.photo_key("drive-2", "md5-2", ".jpg")
        self.assertEqual(payload["instagram"]["assets"], [{"image": {"url": f"{media.PLACEHOLDER_BASE}/{key}"}}])

    def test_a_time_on_the_draft_wins(self):
        _, qid = self.rendered_post(scheduled_for="2026-10-12T14:00")
        self.publish(make_ctx(self.conn))
        payload = json.loads(self.row(qid)["payload"])
        self.assertTrue(payload)
        self.assertEqual({p["dueAt"] for p in payload.values()}, {"2026-10-12T18:00:00Z"})

    def test_a_second_post_takes_the_next_day_on_each_network(self):
        _, first = self.rendered_post(seed=1)
        _, second = self.rendered_post(seed=2)
        stats = self.publish(make_ctx(self.conn))
        self.assertEqual(stats["would_publish"], 2)
        payload = json.loads(self.row(second)["payload"])
        self.assertTrue(payload)
        self.assertEqual(payload["instagram"]["dueAt"], "2026-10-10T14:00:00Z")   # Saturday 10:00, the weekend time
        self.assertEqual(payload["facebook"]["dueAt"], "2026-10-10T13:30:00Z")
        self.assertEqual(payload["pinterest"]["dueAt"], "2026-10-11T00:30:00Z")

    def test_no_pinterest_board_skips_pinterest_and_says_so(self):
        os.environ.pop("PINTEREST_BOARD_ID")
        config.reset()
        _, qid = self.rendered_post()
        stats = self.publish(make_ctx(self.conn))
        self.assertEqual((stats["would_publish"], stats["skipped_networks"]), (1, 1))
        row = self.row(qid)
        self.assertEqual(set(json.loads(row["payload"])), {"instagram", "facebook"})
        self.assertIn("PINTEREST_BOARD_ID is not set", row["last_error"])
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "no_channel")

    def test_no_connected_channel_waits_without_spam(self):
        self.conn.execute("UPDATE channels SET connected=0")
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn)
        self.assertEqual(self.publish(ctx)["waiting_for_channels"], 1)
        self.publish(ctx)
        row = self.row(qid)
        self.assertEqual(row["status"], "approved")
        self.assertIn(publisher.NO_CHANNELS, row["last_error"])
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors")["n"], 0)

    def test_full_run_through_the_runner(self):
        self.rendered_post()
        self.assertEqual(runner.run("publisher", publisher.run), runner.EXIT_OK)
        summary = db.one(self.conn, "SELECT summary FROM agent_runs WHERE agent='publisher' ORDER BY id DESC LIMIT 1")["summary"]
        self.assertTrue(summary)
        self.assertIn("DRY RUN would_publish=1", summary)


class Door(PublisherCase):
    def assert_back(self, qid, stats, words):
        self.assertEqual((stats["would_publish"], stats["turned_back"]), (0, 1))
        row = self.row(qid)
        self.assertEqual(row["status"], "draft")
        self.assertTrue(row["last_error"])
        self.assertIn(words, row["last_error"])
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "door")

    def test_a_caption_with_a_price_goes_back(self):
        _, qid = self.rendered_post(captions={"instagram": "Event coverage from $500 a day.", "facebook": "Fine.", "pinterest": "Fine."})
        self.assert_back(qid, self.publish(make_ctx(self.conn)), "price")

    def test_a_caption_with_a_dash_goes_back(self):
        _, qid = self.rendered_post(captions={"instagram": "Fine.", "facebook": "Backstage, calm.", "pinterest": "Backstage — calm."})
        self.assert_back(qid, self.publish(make_ctx(self.conn)), "pinterest caption")

    def test_affiliation_passes_only_for_a_confirmed_official_event(self):
        now = db.utcnow()
        loose = db.insert(self.conn, "conventions", name="A Con", official=0, created_at=now, updated_at=now)
        ours = db.insert(self.conn, "conventions", name="B Con", official=1, created_at=now, updated_at=now)
        words = {"instagram": "Official photographer for the weekend.", "facebook": "Fine.", "pinterest": "Fine."}
        _, qid = self.rendered_post(seed=1, captions=words, convention_id=loose)
        self.assert_back(qid, self.publish(make_ctx(self.conn)), "tie to the event")
        _, ok_qid = self.rendered_post(seed=2, captions=words, convention_id=ours)
        self.assertEqual(self.publish(make_ctx(self.conn))["would_publish"], 1)
        self.assertEqual(self.row(ok_qid)["status"], "would_publish")

    def test_a_photo_that_is_no_longer_eligible_goes_back(self):
        pid, qid = self.rendered_post()
        self.use_eligibility(eligibility(lambda p: (False, "its folder is no longer cleared")))
        self.assert_back(qid, self.publish(make_ctx(self.conn)), f"Photo {pid} can no longer be used: its folder is no longer cleared")

    def test_a_check_that_cannot_run_holds_and_sends_nothing(self):
        _, qid = self.rendered_post()
        p = mock.patch.object(publisher, "_eligibility_module", side_effect=ModuleNotFoundError("no module"))
        p.start()
        self.addCleanup(p.stop)
        ctx = make_ctx(self.conn)
        stats = self.publish(ctx)
        self.assertEqual((stats["would_publish"], stats["held"]), (0, 1))
        self.publish(ctx)
        row = self.row(qid)
        self.assertEqual(row["status"], "approved", "a broken check is not the photo's fault")
        self.assertIn("could not run", row["last_error"])
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE kind='door_check'")["n"], 1)

    def test_the_same_photo_inside_the_repeat_window_goes_back(self):
        pid, first = self.rendered_post()
        self.conn.execute("UPDATE content_queue SET status='published', published_at=? WHERE id=?",
                          ((datetime.now(timezone.utc) - timedelta(days=20)).isoformat(), first))
        again = add_post(self.conn, [pid])
        self.assert_back(again, self.publish(make_ctx(self.conn)), f"already went out as post #{first}")

    def test_a_photo_from_a_post_that_half_failed_still_counts_as_gone_out(self):
        pid, first = self.rendered_post()
        self.conn.execute("UPDATE content_queue SET status='failed' WHERE id=?", (first,))
        db.insert(self.conn, "post_history", buffer_post_id="post-77", queue_id=first, service="instagram",
                  sent_at=(datetime.now(timezone.utc) - timedelta(days=3)).isoformat())
        again = add_post(self.conn, [pid])
        self.assert_back(again, self.publish(make_ctx(self.conn)), f"already went out as post #{first}")

    def test_the_same_photo_after_the_window_is_fine(self):
        pid, first = self.rendered_post()
        self.conn.execute("UPDATE content_queue SET status='published', published_at=? WHERE id=?",
                          ((datetime.now(timezone.utc) - timedelta(days=200)).isoformat(), first))
        again = add_post(self.conn, [pid])
        self.assertEqual(self.publish(make_ctx(self.conn))["would_publish"], 1)
        self.assertEqual(self.row(again)["status"], "would_publish")


class RealEligibility(AgentCase):
    """The door wired to the real library.eligibility module, no stand-in: verified where it is consumed."""

    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        add_channels(self.conn, "facebook")
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="f-1", name="Con 2026", clearance="not_cleared",
                  first_seen_at=now, last_seen_at=now)
        self.pid = add_photo(self.conn, self.root / "photos", seed=4)
        self.conn.execute("UPDATE photos SET folder_id='f-1' WHERE id=?", (self.pid,))
        db.insert(self.conn, "classifications", photo_id=self.pid, method="vision", possible_minor=0,
                  personal_details="[]", classified_at=now)
        db.insert(self.conn, "final_checks", photo_id=self.pid, possible_minor=0, personal_details="[]",
                  model="claude-opus-5-5", checked_at=now)

    def test_not_cleared_goes_back_and_cleared_goes_through(self):
        held = add_post(self.conn, [self.pid], ("facebook",))
        stats = publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        self.assertEqual(stats["turned_back"], 1)
        row = db.one(self.conn, "SELECT status, last_error FROM content_queue WHERE id=?", (held,))
        self.assertEqual(row["status"], "draft")
        self.assertTrue(row["last_error"])
        self.assertIn("not cleared yet", row["last_error"])
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='f-1'")
        ok = add_post(self.conn, [self.pid], ("facebook",))
        self.assertEqual(publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)["would_publish"], 1)
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (ok,))["status"], "would_publish")


class Live(PublisherCase):
    def uploader(self):
        self.uploads = []

        def up(path, key):
            self.assertTrue(path.exists())
            self.uploads.append(key)
            return f"https://media.example/m/{key}"
        return up

    def test_publish_then_verify_to_published(self):
        pid, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=False)
        fake = FakeBuffer(status_sequence=["scheduled"] * 3 + ["sent"] * 3)
        client = BufferClient("test-key", conn=self.conn, transport=fake)
        stats = self.publish(ctx, client=client, uploader=self.uploader())
        self.assertEqual(stats["scheduled"], 1)
        self.assertEqual(len(fake.created), 3)
        self.assertEqual(sorted(self.uploads), sorted([f"convention-social/cards/{qid}-45-1.jpg", f"convention-social/cards/{qid}-23-1.jpg"]),
                         "each design uploaded once, even though two networks share the 4:5 one")
        row = self.row(qid)
        self.assertEqual(row["status"], "scheduled")
        self.assertEqual(json.loads(row["buffer_post_ids"]), {"instagram": "post-1", "facebook": "post-2", "pinterest": "post-3"})
        self.assertEqual(publisher.verify_scheduled(ctx, client=client), {"published": 0, "failed": 0, "pending": 1})
        self.assertEqual(publisher.verify_scheduled(ctx, client=client)["published"], 1)
        self.assertEqual(self.row(qid)["status"], "published")
        history = db.rows(self.conn, "SELECT service, sent_at FROM post_history ORDER BY id")
        self.assertTrue(history)
        self.assertEqual([h["service"] for h in history], ["instagram", "facebook", "pinterest"])
        self.assertEqual(history[0]["sent_at"], "2026-10-09T15:30:05Z")

    def test_a_raw_photo_is_uploaded_without_any_metadata(self):
        from PIL import Image
        pid = add_photo(self.conn, self.root / "photos", seed=7)
        with Image.open(db.one(self.conn, "SELECT local_path FROM photos WHERE id=?", (pid,))["local_path"]) as orig:
            self.assertIn(0x8825, orig.getexif())          # the original really carries GPS
        add_post(self.conn, [pid], ("facebook",))
        ctx = make_ctx(self.conn, dry_run=False)
        sent = []

        def up(path, key):
            sent.append(path)
            return f"https://media.example/m/{key}"
        self.publish(ctx, client=BufferClient("test-key", conn=self.conn, transport=FakeBuffer()), uploader=up)
        self.assertEqual(len(sent), 1)
        self.assertNotEqual(str(sent[0]), db.one(self.conn, "SELECT local_path FROM photos WHERE id=?", (pid,))["local_path"])
        with Image.open(sent[0]) as im:
            self.assertEqual(len(im.getexif()), 0)

    def test_buffer_error_marks_failed_with_buffers_reason(self):
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=False)
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(status_sequence=["error"]))
        self.publish(ctx, client=client, uploader=self.uploader())
        publisher.verify_scheduled(ctx, client=client)
        row = self.row(qid)
        self.assertEqual(row["status"], "failed")
        self.assertTrue(row["last_error"])
        self.assertIn("Image could not be fetched", row["last_error"])
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "post_error")

    def test_a_refusal_after_one_network_went_keeps_what_went_and_says_what_did_not(self):
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=False)
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(reject_at={2}))
        stats = self.publish(ctx, client=client, uploader=self.uploader())
        self.assertEqual(stats["scheduled"], 1)
        row = self.row(qid)
        self.assertEqual(row["status"], "scheduled")
        self.assertEqual(json.loads(row["buffer_post_ids"]), {"instagram": "post-1"})
        self.assertIn("not sent to facebook, pinterest", row["last_error"])

    def test_live_without_key_or_hosting_sends_nothing_and_says_why(self):
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=False)
        self.assertEqual(self.publish(ctx)["scheduled"], 0)                # no BUFFER_API_KEY
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "buffer_key_missing")
        self.assertEqual(self.row(qid)["status"], "approved")
        fake = FakeBuffer()
        self.assertEqual(self.publish(ctx, client=BufferClient("test-key", conn=self.conn, transport=fake))["scheduled"], 0)
        self.assertEqual(db.rows(self.conn, "SELECT kind FROM errors ORDER BY id")[-1]["kind"], "media_missing")
        self.assertEqual((fake.created, self.row(qid)["status"]), ([], "approved"))

    def test_budget_exhaustion_stops_the_run_and_leaves_rows_approved(self):
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=False)
        for _ in range(80):
            budget.record(self.conn, "test", "x")
        self.publish(ctx, client=BufferClient("test-key", conn=self.conn, transport=FakeBuffer()), uploader=self.uploader())
        self.assertEqual(self.row(qid)["status"], "approved")
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "buffer_budget")
