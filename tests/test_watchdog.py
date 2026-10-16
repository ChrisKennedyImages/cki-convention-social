"""Watchdog: Drive sign-in, channels, posts, spend, missed runs, one alert email, the daily digest. No network."""
from __future__ import annotations

import json
import os
import re
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from unittest import mock

from convention_social.agents import watchdog
from convention_social.ai import copy_rules
from convention_social.buffer import budget, metrics
from convention_social.buffer.client import BufferClient
from convention_social.core import config, db, mail, runner, settings
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
        kw.setdefault("start", mock.Mock())
        kw.setdefault("client", None)
        kw.setdefault("api", None)
        kw.setdefault("probe", ok_probe)
        kw.setdefault("force_digest", False)
        # these tests pin the watchdog's own digest; with the Chief of staff built, the brief replaces it
        with mock.patch.object(watchdog, "is_built", lambda name: name != "chief"):
            return watchdog.run(self.ctx, now=now, **kw)


class Heartbeat(WatchCase):
    """7.4 (2026-10-13): the one watch that does not live on the Mini. The watchdog checks in with the site
    hourly; the site's cron tells the phone when the Mini goes quiet."""

    def site(self, fail=False):
        from convention_social.booking.remote import SiteAPI
        calls = []

        def transport(method, url, headers, payload):
            calls.append((method, url, headers.get("Authorization")))
            if fail:
                raise ConnectionError("site down")
            return mock.Mock(json=lambda: {"ok": True, "at": "2026-10-09T16:00:00.000Z"})
        return SiteAPI("tok", base="https://eventcaliber.com", transport=transport), calls

    def test_checks_in_hourly_and_says_so(self):
        api, calls = self.site()
        self.run_at(NOON_UTC, api=api)
        self.assertEqual(calls, [("POST", "https://eventcaliber.com/api/heartbeat", "Bearer tok")])
        self.assertEqual(settings.get(self.conn, watchdog.HEARTBEAT_KEY), NOON_UTC.isoformat())
        self.run_at(NOON_UTC + timedelta(minutes=10), api=api)
        self.assertEqual(len(calls), 1, "once an hour, not every run")
        self.run_at(NOON_UTC + timedelta(minutes=61), api=api)
        self.assertEqual(len(calls), 2)
        self.run_at(NOON_UTC + timedelta(minutes=70), api=None)
        self.assertEqual(len(calls), 2, "no site token, no heartbeat, no error")
        self.assertIsNone(db.one(self.conn, "SELECT id FROM errors WHERE kind='heartbeat'"))

    def test_a_site_that_does_not_answer_is_said_once(self):
        api, calls = self.site(fail=True)
        self.run_at(NOON_UTC, api=api)
        self.run_at(NOON_UTC + timedelta(minutes=61), api=api)
        self.assertEqual(len(calls), 2, "tried again the next hour")
        rows = db.rows(self.conn, "SELECT message FROM errors WHERE kind='heartbeat'")
        self.assertEqual(len(rows), 1)
        self.assertIn("ConnectionError", rows[0]["message"])
        self.assertNotEqual(settings.get(self.conn, watchdog.HEARTBEAT_KEY), NOON_UTC.isoformat(), "not recorded as checked in")


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
        self.assertIs(push.call_args.kwargs["conn"], self.conn, "a ping that fails is recorded as an error")
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

    def test_each_error_row_is_alerted_and_a_second_of_the_same_kind_is_not_swallowed(self):
        """Keyed by kind alone, the second `door` error inside six hours was never sent, yet marked as sent."""
        db.insert(self.conn, "errors", ts=db.utcnow(), agent="publisher", kind="door", message="post 7: caption breaks a rule", alerted=0)
        self.run_at(NOON_UTC)
        db.insert(self.conn, "errors", ts=db.utcnow(), agent="publisher", kind="door", message="post 8: photo no longer usable", alerted=0)
        summary = self.run_at(NOON_UTC + timedelta(minutes=10))
        self.assertIn("1 sent", summary)
        mails = alert_mails(self.ctx.cfg)
        self.assertEqual(len(mails), 2)
        _, body, _ = read_mail(mails[1])
        self.assertIn("post 8: photo no longer usable", body)
        self.assertNotIn("post 7", body, "said once, in the first mail")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE notified_at IS NULL")["n"], 0)

    def test_an_alert_that_could_not_be_delivered_stays_unsent_and_is_said(self):
        db.insert(self.conn, "errors", ts=db.utcnow(), agent="publisher", kind="door", message="post 7: caption breaks a rule", alerted=0)
        failed = mail.MailResult(sent=False, dry_run=False, error="SMTPAuthenticationError: bad password")
        with mock.patch.object(watchdog.mail, "send", return_value=failed), \
             mock.patch.object(watchdog.notify, "_push", return_value="could not reach ntfy (ConnectionError: no route)"):
            summary = self.run_at(NOON_UTC)
        self.assertIn("1 found, 0 sent", summary)
        self.assertIsNone(db.one(self.conn, "SELECT notified_at FROM errors WHERE kind='door'")["notified_at"], "not sent, so not marked sent")
        kinds = {r["kind"] for r in db.rows(self.conn, "SELECT kind FROM errors WHERE agent='watchdog'")}
        self.assertEqual(kinds, {"alert_mail", "ntfy"})
        self.assertIsNone(settings.get(self.conn, "watchdog.alert.error:door:1"), "no suppression for an alert that never went")
        summary = self.run_at(NOON_UTC + timedelta(minutes=10))        # the mail works again: everything unsent goes now
        self.assertIn("sent", summary)
        _, body, _ = read_mail(alert_mails(self.ctx.cfg)[-1])
        self.assertIn("post 7: caption breaks a rule", body)
        self.assertIn("alert_mail", body, "the watchdog's own trouble is said too")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE notified_at IS NULL")["n"], 0)

    def test_every_agent_on_a_schedule_has_a_gap(self):
        # the phone agent runs when a photo is sent and the sample agent when Post this is pressed, not on a schedule: no gap to
        # watch; the designed drafts run only when one is due (2026-10-15), so a quiet hour is no missed run either
        self.assertEqual(set(watchdog.MAX_GAP), set(watchdog.AGENTS) - {"dashboard", "art_director", "phone", "sample", "designed"})

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


NINE_NY = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)           # 09:00 New York, Friday; tomorrow is Saturday


class TheDraftWindow(WatchCase):
    """2026-10-13: the 08:00 draft fires once; a Mini asleep at 8, a Drive hiccup or an API blip lost the day.
    The hourly watchdog starts the content agent again inside the day's window until a draft lands."""

    def tomorrow(self):
        from convention_social.agents import content
        return content.target_day(self.ctx.cfg, NINE_NY)

    def drafted(self):
        db.insert(self.conn, "content_queue", kind="photo", photo_ids="[]", targets='["instagram"]', caption="{}",
                  rule_report=json.dumps({"for_day": self.tomorrow().isoformat()}), created_at=db.utcnow(), updated_at=db.utcnow())

    def test_nothing_drafted_at_nine_starts_the_content_agent_once(self):
        start = mock.Mock()
        summary = self.run_at(NINE_NY, start=start)
        start.assert_called_once_with("content")
        self.assertIn("alerts: 0 found", summary)
        notes = json.loads(settings.get(self.conn, "watchdog.notes"))
        self.assertTrue(any("content started again" in n for n in notes), notes)

    def test_a_draft_for_tomorrow_means_nothing_to_do(self):
        self.drafted()
        start = mock.Mock()
        self.run_at(NINE_NY, start=start)
        self.run_at(NINE_NY + timedelta(hours=12), start=start)
        start.assert_not_called()
        self.assertEqual(outbox(self.ctx.cfg), [])

    def test_the_same_inputs_after_a_try_that_found_nothing_wait_until_something_changes(self):
        from convention_social.agents import content
        settings.set(self.conn, content.LAST_ATTEMPT_KEY, json.dumps({
            "day": self.tomorrow().isoformat(), "summary": "no photo ready for tomorrow: clear folders on the Library page",
            "fingerprint": content.inputs_fingerprint(self.conn), "transient": False}))
        start = mock.Mock()
        self.run_at(NINE_NY, start=start)
        start.assert_not_called()
        self.assertTrue(any("nothing has changed" in n for n in json.loads(settings.get(self.conn, "watchdog.notes"))))
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="f1", name="Con", clearance="cleared", clearance_at=now,
                  first_seen_at=now, last_seen_at=now)                     # he approved a folder: worth another try
        self.run_at(NINE_NY + timedelta(hours=1), start=start)
        start.assert_called_once_with("content")

    def test_a_transient_reason_or_a_crashed_run_is_tried_again(self):
        from convention_social.agents import content
        settings.set(self.conn, content.LAST_ATTEMPT_KEY, json.dumps({
            "day": self.tomorrow().isoformat(), "summary": "the final check could not run for tomorrow: ConnectionError",
            "fingerprint": content.inputs_fingerprint(self.conn), "transient": True}))
        start = mock.Mock()
        self.run_at(NINE_NY, start=start)
        start.assert_called_once_with("content")
        settings.set(self.conn, content.LAST_ATTEMPT_KEY, json.dumps({
            "day": self.tomorrow().isoformat(), "summary": "no photo ready", "fingerprint": content.inputs_fingerprint(self.conn),
            "transient": False}))
        db.insert(self.conn, "agent_runs", agent="content", started_at=(NINE_NY + timedelta(minutes=30)).isoformat(),
                  finished_at=(NINE_NY + timedelta(minutes=31)).isoformat(), ok=0, dry_run=0, summary="KeyError: x")
        self.run_at(NINE_NY + timedelta(hours=1), start=start)
        self.assertEqual(start.call_count, 2, "a run that crashed is tried again whatever the inputs")

    def test_before_eight_after_four_tries_and_during_a_run_it_waits(self):
        start = mock.Mock()
        self.run_at(NINE_NY - timedelta(hours=2), start=start)                  # 07:00: the 08:00 job has not had its turn
        start.assert_not_called()
        for i in range(4):
            db.insert(self.conn, "agent_runs", agent="content", started_at=(NINE_NY - timedelta(minutes=50 - i)).isoformat(),
                      finished_at=(NINE_NY - timedelta(minutes=49 - i)).isoformat(), ok=1, dry_run=0, summary="no photo ready")
        self.run_at(NINE_NY, start=start)
        start.assert_not_called()
        self.assertTrue(any("no more by itself today" in n for n in json.loads(settings.get(self.conn, "watchdog.notes"))))
        self.conn.execute("DELETE FROM agent_runs")
        db.insert(self.conn, "agent_runs", agent="content", started_at=(NINE_NY - timedelta(minutes=5)).isoformat(), dry_run=0)
        self.run_at(NINE_NY, start=start)
        start.assert_not_called()

    def test_after_eight_in_the_evening_a_missing_post_is_said_loudly_once(self):
        start = mock.Mock()
        with mock.patch.object(watchdog.notify, "push", return_value=False) as push:
            summary = self.run_at(NINE_NY + timedelta(hours=12), start=start)       # 21:00
        start.assert_not_called()
        self.assertIn("1 sent", summary)
        _, body, _ = read_mail(alert_mails(self.ctx.cfg)[0])
        self.assertIn("has no post drafted", body)
        self.assertEqual(push.call_args.kwargs["priority"], "urgent")
        self.assertIn("0 sent", self.run_at(NINE_NY + timedelta(hours=13), start=start))


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
        self.assertEqual(runner.run("watchdog", lambda ctx: watchdog.run(ctx, probe=ok_probe, force_digest=False, start=mock.Mock())),
                         runner.EXIT_OK)
        summary = db.one(self.conn, "SELECT summary FROM agent_runs WHERE agent='watchdog' ORDER BY id DESC LIMIT 1")["summary"]
        self.assertTrue(summary)
        self.assertIn("alerts:", summary)
