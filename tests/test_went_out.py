"""Went out tells the truth, and the schedule is said in plain words (Chris, 2026-10-15).

"dashboard also says nothing has gone out yet and one did get posted within the last 24hrs. what is even the schedule
for posting auto and why does this seem so messy?" Buffer had sent queue post 2 at 15:30 UTC; the Mini never wrote it
to post_history. The publisher asked Buffer about every scheduled post every ten minutes, a post due tomorrow as much
as one due now: about 14 requests an hour, so the suite's own 24-hour ceiling (200) was reached by 12:34 UTC, and from
then on every Buffer request was refused, the check of the post that went out at 15:30 among them.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import publisher
from convention_social.buffer import metrics
from convention_social.buffer.client import BufferClient
from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._fakes import AgentCase, FakeBuffer, Response, add_channels, make_ctx, write_render

SENT_AT = "2026-10-15T15:30:37Z"
LINK = "https://www.instagram.com/p/SENT0001/"


class SentBuffer(FakeBuffer):
    """Buffer as it stood on 2026-10-15: what it says was sent on this company's channels."""

    def __init__(self, sent=(), **kw):
        super().__init__(**kw)
        self.sent = list(sent)

    def __call__(self, url, payload, headers):
        op = payload["query"].strip().split("\n")[0]
        if "Posts" in op and "PostStatus" not in op:
            self.calls.append((op, payload["variables"]))
            assert payload["variables"]["input"]["filter"]["status"] == ["sent"]
            return Response(200, {}, {"data": {"posts": {"edges": [{"node": n} for n in self.sent],
                                                          "pageInfo": {"hasNextPage": False, "endCursor": None}}}})
        return super().__call__(url, payload, headers)

    def asked(self, name):
        return [c for c in self.calls if name in c[0] and (name != "Posts" or "PostStatus" not in c[0])]


def node(pid, *, channel="ch-ig", service="instagram", sent_at=SENT_AT, link=LINK, text="Backstage, minutes before the keynote."):
    return {"id": pid, "channelId": channel, "channelService": service, "status": "sent", "sentAt": sent_at, "dueAt": sent_at,
            "text": text, "metricsUpdatedAt": None, "externalLink": link, "metrics": []}


class Case(AgentCase):
    def setUp(self):
        super().setUp()
        os.environ["BUFFER_API_KEY"] = "test-key"
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = self.connect()
        add_channels(self.conn, "instagram")
        self.ctx = make_ctx(self.conn, dry_run=False)

    def scheduled(self, buffer_id, due: datetime) -> int:
        folder = config.get_config().data_root / "renders" / "posts"
        now = db.utcnow()
        return db.insert(self.conn, "content_queue", kind="photo", photo_ids="[1]", targets=json.dumps(["instagram", "facebook", "pinterest"]),
                         caption=json.dumps({"instagram": "Backstage."}), status="scheduled",
                         render_paths=json.dumps({"4:5": [write_render(folder, f"{buffer_id}.jpg")]}),
                         buffer_post_ids=json.dumps({"instagram": buffer_id}),
                         payload=json.dumps({"instagram": {"dueAt": due.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}}),
                         rule_report=json.dumps({"for_day": due.date().isoformat(), "design": "single"}), created_at=now, updated_at=now)

    def client(self, fake):
        return BufferClient("test-key", conn=self.conn, transport=fake)

    def page(self) -> str:
        c = TestClient(create_app())
        c.cookies.set(COOKIE, make_token("chris"))
        return c.get("/").text


class TheMiss(Case):
    def test_a_post_not_due_yet_is_not_asked_about(self):
        """The miss: every scheduled post was asked about every ten minutes, whatever its time. Now a post is asked about
        from just before its time, so a post due tomorrow costs nothing today."""
        now = datetime.now(timezone.utc)
        self.scheduled("post-later", now + timedelta(days=1))
        fake = SentBuffer()
        stats = publisher.verify_scheduled(self.ctx, client=self.client(fake))
        self.assertEqual(fake.asked("PostStatus"), [], "not due: not asked")
        self.assertEqual(stats.get("not_due"), 1)
        due = self.scheduled("post-now", now - timedelta(minutes=1))
        publisher.verify_scheduled(self.ctx, client=self.client(fake))
        self.assertEqual([c[1]["input"]["id"] for c in fake.asked("PostStatus")], ["post-now"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (due,))["status"], "scheduled",
                         "Buffer said scheduled (the fake's first answer); asked again on the next run")

    def test_a_day_of_runs_keeps_inside_the_budget_with_a_post_due_tomorrow(self):
        self.scheduled("post-later", datetime.now(timezone.utc) + timedelta(days=1, hours=2))
        fake = SentBuffer(status_sequence=["scheduled"])      # Buffer says scheduled until the post's time
        for _ in range(144):                                  # a day of ten-minute runs
            publisher.verify_scheduled(self.ctx, client=self.client(fake))
        self.assertEqual(len(fake.asked("PostStatus")), 0, "asked every run until the budget ceiling stopped it")


class Reconcile(Case):
    def test_a_post_buffer_sent_is_written_down_even_when_the_check_never_ran(self):
        qid = self.scheduled("6ad00a04117064a577d1469f", datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc))
        fake = SentBuffer(sent=[node("6ad00a04117064a577d1469f")])
        with mock.patch.object(publisher.notify, "push") as push:
            stats = publisher.reconcile_sent(self.ctx, client=self.client(fake), now=datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc))
        self.assertEqual((stats["recorded"], stats["published"]), (1, 1))
        h = db.one(self.conn, "SELECT * FROM post_history WHERE buffer_post_id='6ad00a04117064a577d1469f'")
        self.assertEqual((h["queue_id"], h["service"], h["sent_at"], h["external_link"]), (qid, "instagram", SENT_AT, LINK))
        row = db.one(self.conn, "SELECT status, published_at FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "published", "the networks that are off were never sent and are not waited for")
        self.assertEqual(push.call_args[1]["click"], LINK, "the posted ping opens the post itself")
        page = self.page()
        went = page[page.index('id="went-out"'):]
        self.assertIn(f'href="{LINK}"', went)
        self.assertNotIn("Nothing has gone out yet", went)

    def test_a_post_sent_in_buffer_itself_still_shows_on_today(self):
        fake = SentBuffer(sent=[node("made-in-buffer", link="https://www.instagram.com/p/BYHAND01/", text="A post made in Buffer.")])
        publisher.reconcile_sent(self.ctx, client=self.client(fake), now=datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc))
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM post_history"), "not the suite's post: nothing written for it")
        went = self.page()
        went = went[went.index('id="went-out"'):]
        self.assertIn('href="https://www.instagram.com/p/BYHAND01/"', went)
        self.assertIn("A post made in Buffer.", went)
        self.assertIn("Sent from Buffer", went)

    def test_buffer_is_asked_at_most_once_an_hour_and_never_past_the_budget(self):
        fake = SentBuffer(sent=[node("x")])
        t = datetime(2026, 10, 15, 21, 0, tzinfo=timezone.utc)
        publisher.reconcile_sent(self.ctx, client=self.client(fake), now=t)
        publisher.reconcile_sent(self.ctx, client=self.client(fake), now=t + timedelta(minutes=50))
        self.assertEqual(len(fake.asked("Posts")), 1)
        publisher.reconcile_sent(self.ctx, client=self.client(fake), now=t + timedelta(minutes=61))
        self.assertEqual(len(fake.asked("Posts")), 2)
        with mock.patch("convention_social.buffer.budget.allow", return_value=(False, "Buffer 24h window at 200/250 (ceiling 200)")):
            publisher.reconcile_sent(self.ctx, client=self.client(fake), now=t + timedelta(hours=3))
        self.assertEqual(len(fake.asked("Posts")), 2, "at the ceiling: not asked, said once")
        self.assertTrue(db.one(self.conn, "SELECT 1 FROM errors WHERE kind='buffer_budget'"))

    def test_the_numbers_count_a_post_from_the_queue_as_ours(self):
        self.scheduled("6ad00a04117064a577d1469f", datetime(2026, 10, 15, 15, 30, tzinfo=timezone.utc))
        fake = SentBuffer(sent=[node("6ad00a04117064a577d1469f")])
        metrics.pull(self.ctx, self.client(fake))
        self.assertEqual(db.one(self.conn, "SELECT ours FROM post_metrics WHERE buffer_post_id='6ad00a04117064a577d1469f'")["ours"], 1,
                         "a post the suite scheduled is ours even before post_history has it")


class Schedule(Case):
    def test_the_schedule_is_on_today_in_plain_words(self):
        page = re.sub(r"\s+", " ", self.page())
        sched = page[page.index('id="schedule"'):page.index('id="went-out"')]
        for words in ("8:00", "the daily post is drafted for the next day", "Instagram", "11:30 am on weekdays", "10:00 am on weekends",
                      "Monday spotlight", "Thursday carousel", "Friday fan", "Wednesday single photo of a building",
                      "Saturday reel", "Next daily draft"):
            self.assertIn(words, sched, words)
        os.environ["POST_TIMES"] = "instagram=12:15/09:45"
        config.reset()
        sched = re.sub(r"\s+", " ", self.page())
        self.assertIn("12:15 pm on weekdays", sched)
        self.assertIn("9:45 am on weekends", sched)
