"""The pings to Chris's phone (2026-10-11: "I haven't received any ntfy"): a post ready to approve, a
post that went out, and the test button on the Keys page, each saying what happened."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient

import json
import time

from convention_social.agents import content, publisher
from convention_social.buffer.client import BufferClient
from convention_social.core import approve_token, auth, config, db, notify, runner, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_photo, add_post, make_ctx, write_render
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
        self.assertIn("A scan on 1 of your photos for Wednesday. Post now, follow the pace or skip.", args[1])   # the building day's slit scan (2026-10-15)
        self.assertEqual((kw["click"], kw["dry_run"]), (f"https://mac-mini.example:8443/queue/{qid}", True))
        self.assertIs(kw["conn"], conn, "a ping that fails is recorded as an error")
        # 2026-10-13: the ping carries the card; the Approve button only when the art director passed it
        token = settings.get(conn, approve_token.nonce_key(qid))
        self.assertTrue(token, "a nonce for the ping's token")
        self.assertTrue(kw["attach"].startswith(f"https://mac-mini.example:8443/media/card/{qid}/"), kw["attach"])
        self.assertTrue(kw["attach"].endswith(".jpg"))
        self.assertIn(f"view, Open, https://mac-mini.example:8443/queue/{qid}", kw["actions"])
        self.assertNotIn("Post now", kw["actions"], "dry run: the art director did not look, so he looks himself")
        self.assertNotIn("Follow the pace", kw["actions"])
        conn.close()

    def test_a_draft_the_art_director_passed_carries_the_approve_button(self):
        """2026-10-15: the one Approve became his three choices, Post now, Follow the pace and Skip, one token for all."""
        conn = db.connect()
        library(conn)
        os.environ["DASHBOARD_PUBLIC_URL"] = "https://mac-mini.example:8443"
        config.reset()
        config.get_config().ensure_dirs()
        ctx = runner.Context("content", conn, __import__("logging").getLogger("t"), config.get_config(), True, 0)
        real = content.art_director.direct

        def passed(*a, **kw):
            paths, _ = real(*a, **kw)
            return paths, {"verdict": "pass", "notes": "Fine.", "rounds": 1}
        with mock.patch.object(content.notify, "push") as push, mock.patch.object(content.art_director, "direct", passed):
            content.draft_one(ctx, lambda row: jpeg_bytes(seed=1, size=(3000, 2000)), now=datetime(2026, 10, 13, 10, tzinfo=timezone.utc))
        qid = db.one(conn, "SELECT id FROM content_queue")["id"]
        kw = push.call_args[1]
        nonce = settings.get(conn, approve_token.nonce_key(qid))
        for how, label in (("now", "Post now"), ("pace", "Follow the pace"), ("skip", "Skip")):
            self.assertIn(f"http, {label}, https://mac-mini.example:8443/queue/{qid}/choose-by-token/{how}, method=POST, "
                          f"headers.Content-Type=application/x-www-form-urlencoded, body='token=", kw["actions"])
        self.assertIn(f".{nonce}.", kw["actions"], "the token in the buttons is the one the nonce backs")
        self.assertNotIn("view, Open", kw["actions"], "three choices are the most ntfy shows; a tap on the ping opens the draft")
        token = kw["actions"].split("body='token=", 1)[1].split("'", 1)[0]
        self.assertEqual(kw["attach"], f"https://mac-mini.example:8443/media/card/{qid}/{token}.jpg")
        conn.close()


class ApproveFromThePing(IsolatedCase):
    """Chris, 2026-10-13: the morning ping carries the card and an Approve button: signed, single use, never on a GET."""

    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        os.environ["DASHBOARD_PUBLIC_URL"] = "https://mac-mini.example:8443"
        config.reset()
        config.get_config().ensure_dirs()
        self.client = TestClient(create_app())          # no cookie: the phone's ntfy app is not signed in
        self.conn = db.connect()
        folder = config.get_config().data_root / "renders"
        self.qid = add_post(self.conn, [add_photo(self.conn, self.root / "photos")], status="draft",
                            render_paths={"4:5": [write_render(folder, "card.jpg")], "2:3": [write_render(folder, "pin.jpg")]})
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?",
                          (json.dumps({"for_day": "2026-10-14", "art": {"verdict": "pass"}}), self.qid))
        from convention_social.dashboard import app as app_module
        p = mock.patch.object(app_module.eligibility, "is_eligible", lambda conn, pid: (True, "cleared"))
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def row(self):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (self.qid,))

    def approve(self, token, **kw):
        return self.client.post(f"/queue/{self.qid}/approve-by-token", data={"token": token}, **kw)

    def test_nothing_is_approved_on_a_get(self):
        token = approve_token.issue(self.conn, self.row())
        r = self.client.get(f"/queue/{self.qid}/approve-by-token?token={token}")
        self.assertEqual(r.status_code, 200)
        self.assertIn('method="post"', r.text)
        self.assertIn(token, r.text, "the page offers the button; the tap is the POST")
        self.assertEqual(self.row()["status"], "draft")
        self.assertEqual(self.client.get(f"/queue/{self.qid}/approve-by-token").status_code, 200)
        self.assertEqual(self.row()["status"], "draft")

    def test_a_good_token_approves_once(self):
        token = approve_token.issue(self.conn, self.row())
        r = self.approve(token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(f"Approved post {self.qid}", r.text)
        self.assertIn("goes out", r.text)
        self.assertEqual(self.row()["status"], "approved")
        self.assertEqual(settings.get(self.conn, approve_token.nonce_key(self.qid)), "", "spent")
        r = self.approve(token)
        self.assertEqual(r.status_code, 409)
        self.assertIn("already used", r.text)
        self.assertEqual(self.row()["status"], "approved")

    def test_the_body_as_ntfy_sends_it(self):
        token = approve_token.issue(self.conn, self.row())
        r = self.client.post(f"/queue/{self.qid}/approve-by-token", content=f"token={token}",
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.row()["status"], "approved")

    def test_wrong_expired_stale_or_superseded_tokens_are_refused(self):
        row = self.row()
        good = approve_token.issue(self.conn, row)
        self.assertEqual(self.approve(good[:-4] + "0000").status_code, 409)
        self.assertEqual(self.approve("nonsense").status_code, 409)
        self.assertEqual(self.approve("").status_code, 409)
        expired = approve_token.issue(self.conn, row, now=time.time() - 40 * 3600)
        r = self.approve(expired)
        self.assertEqual(r.status_code, 409)
        self.assertIn("expired", r.text)
        fresh = approve_token.issue(self.conn, row)
        self.conn.execute("UPDATE content_queue SET updated_at=? WHERE id=?", ("2026-10-13T00:00:00+00:00", self.qid))
        r = self.approve(fresh)
        self.assertEqual(r.status_code, 409)
        self.assertIn("changed", r.text)
        first = approve_token.issue(self.conn, self.row())
        second = approve_token.issue(self.conn, self.row())
        self.assertEqual(self.approve(first).status_code, 409, "an older ping's button dies when a new ping goes")
        self.assertEqual(self.row()["status"], "draft")
        self.assertEqual(self.approve(second).status_code, 200)
        self.assertEqual(self.row()["status"], "approved")

    def test_the_gates_hold_on_the_token_path_too(self):
        from convention_social.dashboard import app as app_module
        token = approve_token.issue(self.conn, self.row())
        with mock.patch.object(app_module.eligibility, "is_eligible", lambda conn, pid: (False, "not cleared")):
            r = self.approve(token)
        self.assertEqual(r.status_code, 409)
        self.assertIn("photo", r.text)
        self.assertEqual(self.row()["status"], "draft")
        self.assertEqual(self.approve(token).status_code, 200, "the token itself still stands once the photo is usable")

    def test_the_card_is_served_without_a_cookie_only_with_a_valid_token(self):
        token = approve_token.issue(self.conn, self.row())
        r = self.client.get(f"/media/card/{self.qid}/{token}.jpg")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/jpeg"))
        self.assertEqual(self.client.get(f"/media/card/{self.qid}/nonsense.jpg").status_code, 404)
        self.assertEqual(self.client.get(f"/media/card/{self.qid}/{token[:-4]}0000.jpg").status_code, 404)
        self.assertNotEqual(self.client.get(f"/media/render/{self.qid}/4x5/1", follow_redirects=False).status_code, 200,
                            "the signed-in route stays signed in")
        self.approve(token)
        self.assertEqual(self.client.get(f"/media/card/{self.qid}/{token}.jpg").status_code, 404, "single use covers the card")

    def test_the_header_forms_are_the_ones_ntfy_documents(self):
        os.environ["NTFY_TOPIC"] = "event-caliber-abc"
        config.reset()
        seen = {}

        def ok(url, **kw):
            seen.update(url=url, **kw)
            return mock.Mock(status_code=200)
        actions = notify.choice_actions(7, "1.2.3")
        self.assertEqual(notify.push_result("t", "m", dry_run=False, transport=ok, actions=actions,
                                            attach=notify.card_link(7, "1.2.3"), filename="post-7.jpg"), "sent")
        self.assertEqual(seen["headers"]["Actions"], "; ".join(
            f"http, {label}, https://mac-mini.example:8443/queue/7/choose-by-token/{how}, method=POST, "
            "headers.Content-Type=application/x-www-form-urlencoded, body='token=1.2.3', clear=true"
            for how, label in (("now", "Post now"), ("pace", "Follow the pace"), ("skip", "Skip"))))
        self.assertEqual(seen["headers"]["Attach"], "https://mac-mini.example:8443/media/card/7/1.2.3.jpg")
        self.assertEqual(seen["headers"]["Filename"], "post-7.jpg")
        seen.clear()
        notify.push_result("t", "m", dry_run=False, transport=ok)
        self.assertNotIn("Actions", seen["headers"])
        self.assertNotIn("Attach", seen["headers"])


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
        self.assertEqual(kw["click"], "https://www.instagram.com/p/abc123/", "7.1 (2026-10-13): the ping opens the live post")
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
