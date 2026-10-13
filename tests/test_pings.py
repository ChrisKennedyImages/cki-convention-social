"""The pings to Chris's phone (2026-10-11: "I haven't received any ntfy"): a post ready to approve, a
post that went out, and the test button on the Keys page, each saying what happened."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import content, publisher
from convention_social.buffer.client import BufferClient
from convention_social.core import auth, config, db, notify, runner
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, make_ctx
from tests._photos import jpeg_bytes
from tests.test_names import library
from tests.test_publisher import PublisherCase


class Result(IsolatedCase):
    def test_push_says_what_happened(self):
        self.assertEqual(notify.push_result("t", "m", dry_run=False), "no ntfy topic is set (Keys page, Phone alerts)")
        os.environ["NTFY_TOPIC"] = "event-caliber-abc"
        os.environ["DASHBOARD_PUBLIC_URL"] = "https://mac-mini.example:8443"
        config.reset()
        self.assertEqual(notify.push_result("t", "m", dry_run=True), "dry run: nothing sent")
        self.assertEqual(notify.push_result("t", "m", dry_run=False), "no push from a test")
        seen = {}

        def ok(url, **kw):
            seen.update(url=url, **kw)
            return mock.Mock(status_code=200)
        self.assertEqual(notify.push_result("Event Caliber: a post to approve", "m", dry_run=False, transport=ok,
                                            click=notify.link("/queue/7")), "sent")
        self.assertEqual(seen["url"], "https://ntfy.sh/event-caliber-abc")
        self.assertEqual(seen["headers"]["Click"], "https://mac-mini.example:8443/queue/7")
        self.assertEqual(seen["headers"]["Title"], "Event Caliber: a post to approve")
        self.assertEqual(notify.push_result("t", "m", dry_run=False, transport=lambda url, **kw: mock.Mock(status_code=500)),
                         "ntfy answered 500")

        def down(url, **kw):
            raise ConnectionError("no route")
        self.assertIn("could not reach ntfy", notify.push_result("t", "m", dry_run=False, transport=down))
        self.assertFalse(notify.push("t", "m", dry_run=False, transport=down))

    def test_a_ping_that_did_not_go_is_recorded_once(self):
        """A failed push used to be a False nobody read. Failures are said out loud: one errors row per reason."""
        os.environ["NTFY_TOPIC"] = "event-caliber-abc"
        config.reset()
        conn = db.connect()

        def down(url, **kw):
            raise ConnectionError("no route")
        self.assertFalse(notify.push("t", "m", dry_run=False, transport=down, conn=conn, agent="content"))
        self.assertFalse(notify.push("t", "m", dry_run=False, transport=down, conn=conn, agent="content"))
        rows = db.rows(conn, "SELECT * FROM errors")
        self.assertEqual(len(rows), 1, "said once while it stands")
        self.assertEqual((rows[0]["agent"], rows[0]["kind"]), ("content", "ntfy"))
        self.assertIn("could not reach ntfy", rows[0]["message"])
        notify.push("t", "m", dry_run=True, transport=down, conn=conn, agent="content")
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM errors")["n"], 1, "a dry run sends nothing and that is not a failure")
        os.environ.pop("NTFY_TOPIC")
        config.reset()
        notify.push("t", "m", dry_run=False, conn=conn, agent="publisher")
        self.assertEqual(db.one(conn, "SELECT kind FROM errors WHERE agent='publisher'")["kind"], "ntfy", "live with no topic is a failure too")
        conn.close()


class Draft(IsolatedCase):
    def test_a_new_draft_pings_the_phone_with_a_link_to_it(self):
        conn = db.connect()
        library(conn)
        os.environ["DASHBOARD_PUBLIC_URL"] = "https://mac-mini.example:8443"
        config.reset()
        config.get_config().ensure_dirs()
        ctx = runner.Context("content", conn, __import__("logging").getLogger("t"), config.get_config(), True, 0)
        with mock.patch.object(content.notify, "push") as push:
            content.draft_one(ctx, lambda row: jpeg_bytes(seed=1, size=(3000, 2000)), now=datetime(2026, 10, 13, 10, tzinfo=timezone.utc))
        qid = db.one(conn, "SELECT id FROM content_queue")["id"]
        self.assertEqual(push.call_count, 1)
        args, kw = push.call_args
        self.assertEqual(args[0], "Event Caliber: a post to approve")
        self.assertIn("single with 1 photo(s) for Wednesday", args[1])
        self.assertEqual((kw["click"], kw["dry_run"]), (f"https://mac-mini.example:8443/queue/{qid}", True))
        self.assertIs(kw["conn"], conn, "a ping that fails is recorded as an error")
        conn.close()


class Posted(PublisherCase):
    def test_a_post_that_went_out_pings_the_phone(self):
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=False)
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(status_sequence=["sent"]))
        with mock.patch.object(publisher.notify, "push") as push:
            self.publish(ctx, client=client, uploader=lambda path, key: f"https://media.example/m/{key}")
            self.assertEqual(push.call_count, 0, "not before Buffer has sent it")
            publisher.verify_scheduled(ctx, client=client)
        self.assertEqual(push.call_count, 1)
        args, kw = push.call_args
        self.assertEqual(args[0], "Event Caliber: posted")
        self.assertIn(f"Post {qid} went out on instagram, facebook, pinterest", args[1])
        self.assertEqual(kw["dry_run"], False)
        self.assertTrue(kw["click"].endswith(f"/queue/{qid}"))
        self.assertIs(kw["conn"], self.conn, "a ping that fails is recorded as an error")

    def test_a_post_buffer_could_not_send_never_says_posted(self):
        _, qid = self.rendered_post()
        ctx = make_ctx(self.conn, dry_run=False)
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(status_sequence=["error"]))
        with mock.patch.object(publisher.notify, "push") as push:
            self.publish(ctx, client=client, uploader=lambda path, key: f"https://media.example/m/{key}")
            publisher.verify_scheduled(ctx, client=client)
        self.assertEqual(self.row(qid)["status"], "failed")
        self.assertEqual(push.call_count, 0, "the watchdog reports failures; this ping is only for a post that went out")


class TestButton(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_button_says_sent_or_why_not(self):
        page = self.client.get("/keys").text
        self.assertIn("Send a test ping", page)
        r = self.client.post("/keys/test-alert", follow_redirects=False)
        self.assertIn("No+ping%3A+no+ntfy+topic+is+set", r.headers["location"])
        os.environ["NTFY_TOPIC"] = "event-caliber-abc"
        config.reset()
        with mock.patch.object(notify, "push_result", return_value="sent") as sent:
            r = self.client.post("/keys/test-alert", follow_redirects=False)
        self.assertEqual(sent.call_args[1]["dry_run"], False)
        self.assertIn("Test+ping+sent", r.headers["location"])
        with mock.patch.object(notify, "push_result", return_value="ntfy answered 500"):
            r = self.client.post("/keys/test-alert", follow_redirects=False)
        self.assertIn("No+ping%3A+ntfy+answered+500", r.headers["location"])
        anon = TestClient(create_app())
        self.assertNotEqual(anon.post("/keys/test-alert", follow_redirects=False).status_code, 303)
