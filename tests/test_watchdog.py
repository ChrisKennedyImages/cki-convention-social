"""Watchdog: Drive sign-in, channels, posts, spend, missed runs, one alert email, the daily digest. No network."""
from __future__ import annotations

import os
import re
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from unittest import mock

from convention_social.agents import watchdog
from convention_social.ai import copy_rules
from convention_social.buffer import budget, metrics
from convention_social.buffer.client import BufferClient
from convention_social.core import config, db, runner, settings
from convention_social.drive import oauth
from tests._fakes import AgentCase, FakeBuffer, add_channels, make_ctx, outbox, read_mail

NOON_UTC = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)          # 12:00 New York
DIGEST_UTC = datetime(2026, 10, 9, 11, 30, tzinfo=timezone.utc)       # 07:30 New York
Usage = namedtuple("Usage", "total used free")


def ok_probe(url):
    return 200


def alert_mails(cfg):
    return [m for m in outbox(cfg) if "alert" in m.name]


def digest_mails(cfg):
    return [m for m in outbox(cfg) if "daily-digest" in m.name]


class WatchCase(AgentCase):
    def setUp(self):
        super().setUp()
        os.environ["ALERT_EMAIL"] = "owner@example.org"
        config.reset()
        disk = mock.patch.object(watchdog.shutil, "disk_usage", return_value=Usage(10**12, 10**11, 9 * 10**11))
        disk.start()
        self.addCleanup(disk.stop)
        self.conn = self.connect()
        self.ctx = make_ctx(self.conn, agent="watchdog")

    def fresh_runs(self, now):
        """Every watched agent ran a minute ago, so no missed-run alert muddies the test."""
        for name in watchdog.MAX_GAP:
            db.insert(self.conn, "agent_runs", agent=name, started_at=(now - timedelta(minutes=1)).isoformat(), ok=1, dry_run=1)

    def run_at(self, now, **kw):
        self.fresh_runs(now)
        kw.setdefault("client", None)
        kw.setdefault("probe", ok_probe)
        kw.setdefault("force_digest", False)
        return watchdog.run(self.ctx, now=now, **kw)


class Drive(WatchCase):
    def test_the_key_is_the_one_the_sign_in_code_writes(self):
        self.assertEqual(watchdog.DRIVE_STATE_KEY, oauth.STATE_KEY)

    def test_expired_sign_in_alerts_loudly_once_a_day(self):
        oauth.set_state(self.conn, "expired", "invalid_grant")
        with mock.patch.object(watchdog.notify, "push", return_value=False) as push:
            summary = self.run_at(NOON_UTC)
        self.assertIn("1 sent", summary)
        mails = alert_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 1)
        msg, body, plain = read_mail(mails[0])
        self.assertIn("Google Drive sign-in has expired", msg["Subject"])
        self.assertEqual(msg["To"], "owner@example.org")
        self.assertIn("Google Drive sign-in has expired. Open the dashboard&#x27;s Drive page and sign in again.", body)
        self.assertIn(watchdog.DRIVE_EXPIRED, plain)
        self.assertTrue(push.call_args_list)
        self.assertEqual(push.call_args.kwargs["priority"], "urgent")
        # an hour later, and seven hours later (past the usual six hour pause): still the same day, still quiet
        self.assertIn("0 sent", self.run_at(NOON_UTC + timedelta(hours=1)))
        self.assertIn("0 sent", self.run_at(NOON_UTC + timedelta(hours=7)))
        self.assertEqual(len(alert_mails(self.ctx.cfg)), 1)
        # the next day it goes out again
        self.assertIn("1 sent", self.run_at(NOON_UTC + timedelta(days=1)))
        self.assertEqual(len(alert_mails(self.ctx.cfg)), 2)
        # signed in again: nothing
        oauth.set_state(self.conn, "ok")
        self.assertIn("alerts: 0 found", self.run_at(NOON_UTC + timedelta(days=2)))

    def test_never_signed_in_is_a_note_not_an_alert(self):
        oauth.set_state(self.conn, "missing", "no Google sign-in yet")
        summary = self.run_at(DIGEST_UTC)
        self.assertIn("alerts: 0 found", summary)
        self.assertIn("digest: sent", summary)
        mails = digest_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 1)
        _, body, _ = read_mail(mails[0])
        self.assertIn("Google Drive is not signed in yet.", body)


class Checks(WatchCase):
    def test_disconnected_channel_flips_the_flag_and_alerts_every_six_hours_at_most(self):
        add_channels(self.conn, "instagram", "facebook", "pinterest")
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(disconnected={"facebook"}))
        summary = self.run_at(NOON_UTC, client=client)
        self.assertIn("1 sent", summary)
        flags = {r["service"]: r["connected"] for r in db.rows(self.conn, "SELECT service, connected FROM channels")}
        self.assertEqual(flags, {"instagram": 1, "facebook": 0, "pinterest": 1})
        mails = alert_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 1)
        _, body, _ = read_mail(mails[0])
        self.assertIn("DISCONNECTED", body)
        self.assertIn("0 sent", self.run_at(NOON_UTC + timedelta(hours=1), client=client))
        self.run_at(NOON_UTC + timedelta(hours=7), client=client)
        self.assertEqual(len(alert_mails(self.ctx.cfg)), 2)

    def test_missed_agent_failed_post_and_new_errors_make_one_email(self):
        db.insert(self.conn, "agent_runs", agent="publisher", started_at=(NOON_UTC - timedelta(hours=3)).isoformat(), ok=1, dry_run=1)
        db.insert(self.conn, "content_queue", kind="photo", photo_ids="[]", targets='["facebook"]', caption='{"facebook":"x"}',
                  status="failed", last_error="Buffer could not send it", created_at=NOON_UTC.isoformat(), updated_at=NOON_UTC.isoformat())
        db.insert(self.conn, "errors", ts=db.utcnow(), agent="publisher", kind="media_missing",
                  message="publisher is LIVE but image hosting is not configured", alerted=0)
        summary = watchdog.run(self.ctx, now=NOON_UTC, client=None, probe=ok_probe, force_digest=False)
        self.assertIn("sent", summary)
        mails = alert_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 1)
        _, body, _ = read_mail(mails[0])
        self.assertIn("publisher last ran", body)
        self.assertIn("Buffer could not send it", body)
        self.assertIn("media_missing", body)
        self.assertIsNotNone(db.one(self.conn, "SELECT notified_at FROM errors")["notified_at"])

    def test_stuck_scheduled_post_alerts(self):
        qid = db.insert(self.conn, "content_queue", kind="photo", photo_ids="[]", targets='["instagram"]', caption='{"instagram":"x"}',
                        status="scheduled", payload='{"instagram": {"dueAt": "2026-10-09T03:00:00Z"}}',
                        created_at=NOON_UTC.isoformat(), updated_at=NOON_UTC.isoformat())
        self.run_at(NOON_UTC)
        mails = alert_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 1)
        _, body, _ = read_mail(mails[0])
        self.assertIn(f"Post {qid} is still waiting in Buffer", body)

    def test_budget_cap_and_dashboard_down(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "1.00"
        config.reset()
        self.ctx = make_ctx(self.conn, agent="watchdog")
        for _ in range(80):
            budget.record(self.conn, "test", "x")
        db.insert(self.conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent="content", units=1, cost_usd=1.25)

        def down(url):
            raise ConnectionError("refused")
        summary = self.run_at(NOON_UTC, probe=down)
        self.assertIn("3 sent", summary)
        mails = alert_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 1)
        _, body, _ = read_mail(mails[0])
        self.assertIn("Buffer API 15m window", body)
        self.assertIn("monthly cap", body)
        self.assertIn("not answering", body)

    def test_clean_system_sends_nothing(self):
        summary = self.run_at(NOON_UTC)
        self.assertIn("alerts: 0 found, 0 sent", summary)
        self.assertEqual(outbox(self.ctx.cfg), [])

    def test_metrics_pulled_once_a_day(self):
        add_channels(self.conn, "instagram")
        fake = FakeBuffer()
        client = BufferClient("test-key", conn=self.conn, transport=fake)
        self.run_at(NOON_UTC, client=client)
        pulls = [c for c in fake.calls if c[0].startswith("query Posts")]
        self.assertEqual(len(pulls), 1)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM post_metrics")["n"], 1)
        self.run_at(NOON_UTC + timedelta(hours=1), client=client)
        self.assertEqual(len([c for c in fake.calls if c[0].startswith("query Posts")]), 1, "a second run the same day does not pull again")
        self.assertEqual(settings.get(self.conn, metrics.PULLED_KEY), "2026-10-09")


class Digest(WatchCase):
    def test_digest_goes_dry_to_the_outbox_once_at_the_digest_hour(self):
        add_channels(self.conn, "instagram")
        oauth.set_state(self.conn, "ok")
        db.insert(self.conn, "post_history", buffer_post_id="post-9", service="instagram",
                  sent_at=(DIGEST_UTC - timedelta(hours=2)).isoformat(), caption="Green room calm before the keynote.")
        db.insert(self.conn, "content_queue", kind="photo", photo_ids="[]", targets='["facebook"]', caption='{"facebook":"x"}',
                  status="draft", created_at=DIGEST_UTC.isoformat(), updated_at=DIGEST_UTC.isoformat())
        self.assertIn("digest: not due", self.run_at(NOON_UTC))
        self.assertEqual(digest_mails(self.ctx.cfg), [])
        summary = self.run_at(DIGEST_UTC)
        self.assertIn("digest: sent", summary)
        mails = digest_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 1)
        msg, body, plain = read_mail(mails[0])
        self.assertIn("1 posted, 1 waiting, 0 broke", msg["Subject"])
        self.assertIn("Green room calm before the keynote.", body)
        self.assertIn("Waiting for your Approve (1)", body)
        self.assertIn("Google Drive is signed in.", body)
        self.assertTrue(plain)
        text = re.sub(r"<[^>]+>", " ", body)
        self.assertTrue(text.strip())
        self.assertIsNone(copy_rules.DASH.search(text), "the digest uses no dashes")
        self.assertIsNone(copy_rules.DASH.search(plain), "the digest uses no dashes")
        self.assertIn("digest: not due", self.run_at(DIGEST_UTC + timedelta(minutes=40)))
        self.assertEqual(len(digest_mails(self.ctx.cfg)), 1)
        self.assertEqual(settings.get(self.conn, "watchdog.digest_sent_on"), "2026-10-09")

    def test_force_digest(self):
        self.assertIn("digest: sent", self.run_at(NOON_UTC, force_digest=True))
        self.assertEqual(len(digest_mails(self.ctx.cfg)), 1)

    def test_runner_end_to_end(self):
        self.assertEqual(runner.run("watchdog", lambda ctx: watchdog.run(ctx, probe=ok_probe, force_digest=False)), runner.EXIT_OK)
        summary = db.one(self.conn, "SELECT summary FROM agent_runs WHERE agent='watchdog' ORDER BY id DESC LIMIT 1")["summary"]
        self.assertTrue(summary)
        self.assertIn("alerts:", summary)
