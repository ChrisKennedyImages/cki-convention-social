"""A post goes out once, and only while it is approved (the 2026-11-09 audit's "can post wrongly" findings)."""
from __future__ import annotations

import json
import os
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import publisher
from convention_social.buffer.client import BufferClient, BufferUnknownOutcome, Response
from convention_social.core import auth, config, db
from convention_social.dashboard import app as dashboard
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, make_ctx
from tests.test_publisher import PublisherCase


def up(path, key):
    return f"https://media.example/m/{key}"


class OnceAndOnlyWhileApproved(PublisherCase):
    def client(self, fake):
        return BufferClient("test-key", conn=self.conn, transport=fake)

    def test_a_post_approved_again_goes_only_to_the_networks_that_did_not_get_it(self):
        """Approve again on a post marked failed for one network sent it to the others a second time."""
        _, qid = self.rendered_post()
        db.insert(self.conn, "post_history", buffer_post_id="post-old", queue_id=qid, service="instagram",
                  sent_at="2026-10-09T15:30:05Z")
        fake = FakeBuffer()
        self.publish(make_ctx(self.conn, dry_run=False), client=self.client(fake), uploader=up)
        self.assertEqual(len(fake.created), 2)
        self.assertNotIn("ch-ig", [c["channelId"] for c in fake.created], "Instagram already has it")
        self.assertEqual(set(json.loads(self.row(qid)["buffer_post_ids"])), {"facebook", "pinterest"})

    def test_a_post_skipped_while_the_run_was_at_work_is_not_sent(self):
        _, qid = self.rendered_post()

        def skipped_meanwhile(path, key):
            self.conn.execute("UPDATE content_queue SET status='rejected' WHERE id=?", (qid,))
            return up(path, key)
        fake = FakeBuffer()
        stats = self.publish(make_ctx(self.conn, dry_run=False), client=self.client(fake), uploader=skipped_meanwhile)
        self.assertEqual(fake.created, [], "nothing reaches Buffer once he has skipped it")
        self.assertEqual(self.row(qid)["status"], "rejected")
        self.assertEqual(stats["scheduled"], 0)

    def test_an_approve_taken_back_while_the_run_was_at_work_is_not_sent(self):
        _, qid = self.rendered_post()

        def taken_back(path, key):
            self.conn.execute("UPDATE content_queue SET status='draft', approved_at=NULL WHERE id=?", (qid,))
            return up(path, key)
        fake = FakeBuffer()
        self.publish(make_ctx(self.conn, dry_run=False), client=self.client(fake), uploader=taken_back)
        self.assertEqual(fake.created, [])
        self.assertEqual(self.row(qid)["status"], "draft")

    def test_an_unexpected_error_mid_send_keeps_what_buffer_took_and_marks_the_rest_unknown(self):
        _, qid = self.rendered_post()
        client = self.client(FakeBuffer())
        with mock.patch.object(client, "create_post", side_effect=["post-1", RuntimeError("boom")]):
            stats = self.publish(make_ctx(self.conn, dry_run=False), client=client, uploader=up)
        row = self.row(qid)
        self.assertEqual(row["status"], "scheduled", "never left approved: the next run would send Instagram again")
        self.assertEqual(json.loads(row["buffer_post_ids"]), {"instagram": "post-1"})
        self.assertIn("facebook", json.loads(row["rule_report"])[publisher.UNKNOWN_KEY])
        self.assertEqual(stats["held"], 1)
        self.assertTrue(db.one(self.conn, "SELECT 1 FROM errors WHERE kind='RuntimeError'"))

    def test_an_unexpected_error_on_the_first_send_is_asked_about_before_any_resend(self):
        _, qid = self.rendered_post()
        client = self.client(FakeBuffer())
        with mock.patch.object(client, "create_post", side_effect=RuntimeError("boom")):
            self.publish(make_ctx(self.conn, dry_run=False), client=client, uploader=up)
        row = self.row(qid)
        self.assertEqual(row["status"], "approved")
        self.assertIn("instagram", publisher.unknown_of(row), "marked, so settle_unknown asks Buffer first")

    def test_an_unexpected_error_before_anything_is_sent_fails_the_post_aloud(self):
        _, qid = self.rendered_post()
        fake = FakeBuffer()
        with mock.patch.object(publisher, "build_all", side_effect=ValueError("no such thing")):
            stats = self.publish(make_ctx(self.conn, dry_run=False), client=self.client(fake), uploader=up)
        row = self.row(qid)
        self.assertEqual((row["status"], stats["failed"]), ("failed", 1))
        self.assertIn("no such thing", row["last_error"])
        self.assertEqual(fake.created, [])

    def test_an_unreadable_answer_to_createpost_is_an_unknown_outcome(self):
        client = BufferClient("test-key", transport=lambda url, payload, headers: Response(200, {}, {}))
        with self.assertRaises(BufferUnknownOutcome):
            client.create_post({"channelId": "ch-ig", "text": "x"})


class TheDashboardLeavesWhatBufferHoldsAlone(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(dashboard.create_app())
        self.client.cookies.set(dashboard.COOKIE, dashboard.make_token("chris"))
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def post(self, status="draft", targets=("instagram",)):
        now = db.utcnow()
        caps = {"instagram": "Green room before the keynote.", "facebook": "Facebook words.", "pinterest": "Pinterest words."}
        return db.insert(self.conn, "content_queue", kind="photo", photo_ids="[]", targets=json.dumps(list(targets)),
                         caption=json.dumps(caps), status=status, created_at=now, updated_at=now)

    def row(self, qid):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))

    def test_save_is_refused_on_a_post_buffer_holds_or_has_sent(self):
        for status in ("scheduled", "published"):
            qid = self.post(status)
            r = self.client.post(f"/queue/{qid}/save", data={"caption_instagram": "Other words.", "target_facebook": "on"},
                                 follow_redirects=False)
            self.assertIn("msg=not_editable", r.headers["location"], status)
            row = self.row(qid)
            self.assertEqual(json.loads(row["caption"])["instagram"], "Green room before the keynote.")
            self.assertEqual(json.loads(row["targets"]), ["instagram"])

    def test_save_keeps_the_caption_of_a_network_whose_box_is_not_on_the_page(self):
        qid = self.post("draft")
        r = self.client.post(f"/queue/{qid}/save", data={"caption_instagram": "New words.", "target_instagram": "on"},
                             follow_redirects=False)
        self.assertIn("msg=saved", r.headers["location"])
        caps = json.loads(self.row(qid)["caption"])
        self.assertEqual(caps["instagram"], "New words.")
        self.assertEqual(caps["facebook"], "Facebook words.", "a held network's caption had been saved as nothing")

    def test_a_skip_does_not_mark_a_post_the_publisher_handed_to_buffer_meanwhile(self):
        qid = self.post("approved")
        seen = self.row(qid)                                        # what the Skip saw
        self.conn.execute("UPDATE content_queue SET status='scheduled' WHERE id=?", (qid,))
        self.assertFalse(dashboard.set_aside(self.conn, seen, by="chris", why="Skipped by you."))
        self.assertEqual(self.row(qid)["status"], "scheduled")
        fresh = self.post("draft")
        self.assertTrue(dashboard.set_aside(self.conn, self.row(fresh), by="chris", why="Skipped by you."))
        self.assertEqual(self.row(fresh)["status"], "rejected")
