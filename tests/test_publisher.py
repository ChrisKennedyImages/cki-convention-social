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
        # all three networks switched on, as when Chris turns Facebook and Pinterest back on (POST_NETWORKS, Keys page):
        # since 2026-10-15 the default is Instagram only (tests/test_no_minor_gate.py pins that default)
        os.environ["POST_NETWORKS"] = "instagram,facebook,pinterest"
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

    def test_a_draft_for_monday_goes_out_monday_on_every_network(self):
        _, qid = self.rendered_post()
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"for_day": "2026-10-12"}), qid))
        self.assertEqual(self.publish(make_ctx(self.conn))["would_publish"], 1)
        payload = json.loads(self.row(qid)["payload"])
        self.assertEqual(payload["instagram"]["dueAt"], "2026-10-12T15:30:00Z")
        self.assertEqual(payload["facebook"]["dueAt"], "2026-10-12T13:30:00Z")
        self.assertEqual(payload["pinterest"]["dueAt"], "2026-10-13T00:30:00Z")
        _, other = self.rendered_post(seed=2)
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"for_day": "turned back"}), other))
        self.assertEqual(self.publish(make_ctx(self.conn))["would_publish"], 1)
        self.assertEqual(json.loads(self.row(other)["payload"])["instagram"]["dueAt"], "2026-10-09T15:30:00Z", "no day: today")

    def test_a_pinterest_card_is_needed_when_the_photo_copy_is_not_a_jpeg(self):
        """The photo copies on the Mini are .img files; a post with no 2:3 card has nothing Pinterest can take."""
        pid = add_photo(self.conn, self.root / "photos", seed=5, suffix=".img")
        bare = add_post(self.conn, [pid], render_paths={"4:5": [write_render(self.root / "renders", "bare-45.jpg")]})
        self.publish(make_ctx(self.conn))
        self.assertEqual(self.row(bare)["status"], "failed")
        self.assertIn("needs a rendered design", self.row(bare)["last_error"])
        full = add_post(self.conn, [pid], render_paths={"4:5": [write_render(self.root / "renders", "full-45.jpg")],
                                                        "2:3": [write_render(self.root / "renders", "full-23.jpg")]})
        self.publish(make_ctx(self.conn))
        self.assertEqual(self.row(full)["status"], "would_publish")
        self.assertEqual(set(json.loads(self.row(full)["payload"])), {"instagram", "facebook", "pinterest"})

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
        errs = db.rows(self.conn, "SELECT kind, message FROM errors")
        self.assertEqual([e["kind"] for e in errs], ["no_channel"], "said once on the Agents page, never per run")
        self.assertIn(f"post {qid}", errs[0]["message"])

    def test_no_open_day_is_said_once(self):
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn)
        with mock.patch.object(publisher.pacing, "plan", return_value={"instagram": None, "facebook": None, "pinterest": None}):
            self.publish(ctx)
            self.publish(ctx)
        row = self.row(qid)
        self.assertEqual(row["status"], "approved")
        self.assertIn("No open day", row["last_error"])
        errs = db.rows(self.conn, "SELECT kind FROM errors")
        self.assertEqual([e["kind"] for e in errs], ["no_day"])

    def test_full_run_through_the_runner(self):
        self.rendered_post()
        self.assertEqual(runner.run("publisher", publisher.run), runner.EXIT_OK)
        summary = db.one(self.conn, "SELECT summary FROM agent_runs WHERE agent='publisher' ORDER BY id DESC LIMIT 1")["summary"]
        self.assertTrue(summary)
        self.assertIn("DRY RUN would_publish=1", summary)


class Nudge(PublisherCase):
    """Chris, 2026-10-13: silence never posts, and a draft is never set aside for it. A draft waiting eight hours
    gets one push that opens it."""

    def waiting(self, hours, for_day="2026-10-13", status="draft"):
        pid, qid = self.rendered_post(seed=hours, status=status)
        made = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
        self.conn.execute("UPDATE content_queue SET created_at=?, rule_report=? WHERE id=?", (made, json.dumps({"for_day": for_day}), qid))
        return qid

    def pushes(self):
        p = mock.patch.object(publisher.notify, "_push", return_value="sent")
        self.addCleanup(p.stop)
        return p.start()

    def test_a_draft_waiting_eight_hours_is_nudged_once_and_never_set_aside(self):
        push = self.pushes()
        old, young = self.waiting(9), self.waiting(2)
        self.waiting(12, status="approved")          # approved is not waiting on him
        ctx = make_ctx(self.conn, dry_run=True)
        self.assertEqual(publisher.tend_drafts(ctx), {"waiting": 2, "nudged": 1})
        self.assertEqual(push.call_count, 1, "the dry-run switch is about Buffer; a draft waiting for him is real")
        args, kw = push.call_args
        self.assertIn("still waiting", args[0].lower())
        self.assertIn("Tuesday's post", args[1])
        self.assertIn("Nothing goes out unless you approve it", args[1])
        self.assertTrue(kw["click"].endswith(f"/queue/{old}"))
        self.assertFalse(kw["dry_run"])
        self.assertTrue(json.loads(self.row(old)["rule_report"])["nudged_at"])
        self.assertNotIn("nudged_at", self.row(young)["rule_report"])
        # once, not twice; and still a draft, not set aside
        self.assertEqual(publisher.tend_drafts(ctx), {"waiting": 2, "nudged": 0})
        self.assertEqual(push.call_count, 1)
        self.assertEqual([self.row(q)["status"] for q in (old, young)], ["draft", "draft"])
        # a day later the young one has waited its eight hours; the old one is not nudged again
        later = datetime.now(timezone.utc) + timedelta(hours=30)
        self.assertEqual(publisher.tend_drafts(ctx, now=later), {"waiting": 2, "nudged": 1})
        self.assertTrue(push.call_args[1]["click"].endswith(f"/queue/{young}"))
        self.assertEqual([self.row(q)["status"] for q in (old, young)], ["draft", "draft"])

    def test_the_nudge_rides_the_publishers_ten_minute_run(self):
        push = self.pushes()
        self.waiting(9)
        line = publisher.run(make_ctx(self.conn, dry_run=True))
        self.assertIn("nudged=1", line)
        self.assertEqual(push.call_count, 1)
        self.assertIn("nudged=0", publisher.run(make_ctx(self.conn, dry_run=True)))


class Door(PublisherCase):
    def assert_back(self, qid, stats, words):
        self.assertEqual((stats["would_publish"], stats["turned_back"]), (0, 1))
        row = self.row(qid)
        self.assertEqual(row["status"], "draft")
        self.assertTrue(row["last_error"])
        self.assertIn(words, row["last_error"])
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "door")

    def test_a_caption_that_breaks_a_rule_now_is_rewritten_at_the_door_not_bounced(self):
        """Chris, 2026-10-12: "I don't want to change any captions." The door rewrites, then checks again."""
        _, qid = self.rendered_post(captions={"instagram": "Event coverage from $500 a day.", "facebook": "Fine.", "pinterest": "Fine."})
        stats = self.publish(make_ctx(self.conn))
        self.assertEqual((stats["would_publish"], stats["turned_back"]), (1, 0))
        row = self.row(qid)
        self.assertEqual(row["status"], "would_publish")
        captions = json.loads(row["caption"])
        self.assertNotIn("$500", captions["instagram"])
        self.assertIn("$500", json.loads(row["rule_report"])["mended"][0]["was"]["instagram"], "the old words are kept")
        self.assertNotIn("$500", json.loads(row["payload"])["instagram"]["text"], "what goes out is the rewrite")
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM errors WHERE kind='door'"))

    def test_a_caption_rewritten_within_the_hour_that_still_breaks_goes_back(self):
        from convention_social.core import db as db_mod
        _, qid = self.rendered_post(captions={"instagram": "Event coverage from $500 a day.", "facebook": "Fine.", "pinterest": "Fine."})
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?",
                          (json.dumps({"mended": [{"at": db_mod.utcnow(), "by": "template", "fixed": {}, "was": {}}]}), qid))
        self.assert_back(qid, self.publish(make_ctx(self.conn)), "price")
        self.assertIn("rewrote", self.row(qid)["last_error"])

    def assert_rewritten(self, qid, stats, rule, bad_words):
        """The door rewrote it (2026-10-13), the record names the rule, what goes out carries none of the old words."""
        self.assertEqual((stats["would_publish"], stats["turned_back"]), (1, 0))
        row = self.row(qid)
        self.assertEqual(row["status"], "would_publish")
        mend = json.loads(row["rule_report"])["mended"][-1]
        self.assertIn(rule, json.dumps(mend["fixed"]))
        out = json.dumps(json.loads(row["payload"])) + json.dumps(json.loads(row["caption"]))
        for word in bad_words:
            self.assertNotIn(word, out)
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM errors WHERE kind='door'"))

    def test_a_caption_that_says_what_the_company_includes_is_rewritten(self):
        """Chris, 2026-10-11: "NOTHING INCLUDES ANYTHING": an approved post is still caught at the door, and rewritten."""
        _, qid = self.rendered_post(captions={"instagram": "Conference photography includes portraits, shot in a few minutes.",
                                              "facebook": "Fine.", "pinterest": "Fine."})
        self.assert_rewritten(qid, self.publish(make_ctx(self.conn)), "nothing includes anything", ["includes portraits"])

    def test_a_caption_that_talks_about_a_service_is_rewritten(self):
        """Chris, 2026-10-11: "not talk about what is offered or what is a service, specifically in captions"."""
        _, qid = self.rendered_post(captions={"instagram": "Fine.", "facebook": "Photo delivery by face match while the event is on.",
                                              "pinterest": "Fine."})
        self.assert_rewritten(qid, self.publish(make_ctx(self.conn)), "what is offered", ["face match"])

    def test_a_caption_with_a_dash_is_rewritten(self):
        _, qid = self.rendered_post(captions={"instagram": "Fine.", "facebook": "Backstage, calm.", "pinterest": "Backstage — calm."})
        self.assert_rewritten(qid, self.publish(make_ctx(self.conn)), "dash", ["—"])

    def test_affiliation_passes_only_for_a_confirmed_official_event(self):
        now = db.utcnow()
        loose = db.insert(self.conn, "conventions", name="A Con", official=0, created_at=now, updated_at=now)
        ours = db.insert(self.conn, "conventions", name="B Con", official=1, created_at=now, updated_at=now)
        words = {"instagram": "Official photographer for the weekend.", "facebook": "Fine.", "pinterest": "Fine."}
        _, qid = self.rendered_post(seed=1, captions=words, convention_id=loose)
        self.assert_rewritten(qid, self.publish(make_ctx(self.conn)), "tie to the event", ["Official photographer"])
        _, ok_qid = self.rendered_post(seed=2, captions=words, convention_id=ours)
        self.assertEqual(self.publish(make_ctx(self.conn))["would_publish"], 1)
        row = self.row(ok_qid)
        self.assertEqual(row["status"], "would_publish")
        self.assertIn("Official photographer", json.loads(row["caption"])["instagram"], "Chris marked it official: left as it is")

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
        os.environ["POST_NETWORKS"] = "facebook"         # this door test posts to Facebook; since 2026-10-15 it is off by default
        config.reset()
        add_channels(self.conn, "facebook")
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="f-1", name="Con 2026", clearance="not_cleared",
                  first_seen_at=now, last_seen_at=now)
        self.pid = add_photo(self.conn, self.root / "photos", seed=4)
        self.conn.execute("UPDATE photos SET folder_id='f-1' WHERE id=?", (self.pid,))
        db.insert(self.conn, "classifications", photo_id=self.pid, method="vision", possible_minor=0,
                  personal_details="[]", classified_at=now)
        db.insert(self.conn, "final_checks", photo_id=self.pid, possible_minor=0, personal_details="[]",
                  model="claude-opus-5", checked_at=now)

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
        self.assertEqual(publisher.verify_scheduled(ctx, client=client), {"published": 0, "failed": 0, "pending": 1, "not_due": 0})
        self.assertEqual(publisher.verify_scheduled(ctx, client=client)["published"], 1)
        self.assertEqual(self.row(qid)["status"], "published")
        history = db.rows(self.conn, "SELECT service, sent_at, external_link FROM post_history ORDER BY id")
        self.assertTrue(history)
        self.assertEqual([h["service"] for h in history], ["instagram", "facebook", "pinterest"])
        self.assertEqual(history[0]["sent_at"], "2026-10-09T15:30:05Z")
        self.assertEqual({h["external_link"] for h in history}, {"https://www.instagram.com/p/abc123/"}, "7.1: the live link is kept")

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
        from convention_social.render import meta
        self.assertEqual(meta.is_clean(sent[0]), [])
        self.assertIn(b"CKI, LLC", sent[0].read_bytes())

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
