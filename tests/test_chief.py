"""The Chief of staff's morning brief: what needs Chris comes first, once a day, never a paid call in dry run."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timedelta, timezone

from unittest import mock

from convention_social.agents import chief, watchdog
from convention_social.core import config, db, mail, runner, settings
from tests._base import IsolatedCase

BRIEF_UTC = datetime(2026, 10, 12, 11, 40, tzinfo=timezone.utc)     # 07:40 New York


class Chief(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["ALERT_EMAIL"] = "chris@example.org"
        config.reset()
        self.conn = db.connect()
        now = db.utcnow()
        db.insert(self.conn, "content_queue", kind="photo", photo_ids="[]", targets='["instagram"]', caption="{}",
                  rule_report=json.dumps({"art": {"verdict": "redo", "notes": "Tight crop."}}), created_at=now, updated_at=now)
        db.insert(self.conn, "inquiries", remote_id="r1", received_at=now, name="Dana", email="d@example.org", status="drafted",
                  reply_status="draft", updated_at=now)
        settings.set(self.conn, "drive.auth_state", "expired")

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def ctx(self, dry=True):
        config.get_config().ensure_dirs()
        return runner.Context("chief", self.conn, __import__("logging").getLogger("t"), config.get_config(), dry, 0)

    def test_needs_you_first_and_once_a_day(self):
        line = chief.run(self.ctx(), now=BRIEF_UTC)
        self.assertIn("need you", line)
        brief = json.loads(settings.get(self.conn, chief.BRIEF_KEY))
        needs = [n for n, _ in brief["needs"]]
        self.assertTrue(needs)
        self.assertTrue(any("waiting for your Approve" in n for n in needs))
        self.assertTrue(any("quote request" in n for n in needs))
        self.assertTrue(any("signed out" in n for n in needs))
        self.assertTrue(any("Art director" in n for n in needs))
        eml = list((config.get_config().data_root / "outbox-dry").glob("*.eml"))
        self.assertEqual(len(eml), 1)
        self.assertIn("Needs you", eml[0].read_text())
        self.assertEqual(chief.run(self.ctx(), now=BRIEF_UTC), "brief not due")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage")["n"], 0)

    def test_needs_is_the_plain_sql_part_the_today_page_shares(self):
        """7.3 (2026-10-13): the Today page shows what needs him without waiting for the morning brief."""
        needs = chief.needs(self.conn)
        hrefs = [h for _, h in needs]
        self.assertIn("/inquiries", hrefs)
        self.assertIn("/drive", hrefs)
        self.assertIn("/", hrefs, "the draft the art director was not happy with")
        self.assertEqual([t for t, h in needs if h == "/inquiries"], ["1 quote request(s) waiting for your reply."])
        gathered = chief.gather(self.ctx(), BRIEF_UTC)["needs"]
        for item in needs:
            self.assertIn(item, gathered, "the brief carries the same lines")

    def test_counts_outreach_drafts_and_scout_finds(self):
        """The brief reads the tables migration 0040 really makes: outreach and scout_events."""
        now = db.utcnow()
        db.insert(self.conn, "outreach", event_key="expo|2027-03-05", event_name="Expo", email="o@example.org",
                  status="draft", token="a" * 32, created_at=now, updated_at=now)
        db.insert(self.conn, "scout_events", dedup_key="expo|2027-03-05", name_key="expo", name="Expo",
                  sources='["https://example.org/expo"]', found_at=now, updated_at=now)
        chief.run(self.ctx(), now=BRIEF_UTC)
        needs = dict(json.loads(settings.get(self.conn, chief.BRIEF_KEY))["needs"])
        self.assertTrue(needs)
        self.assertEqual(needs.get("1 organizer email(s) drafted for your Approve."), "/outreach")
        self.assertEqual(needs.get("1 upcoming event(s) the scout found for you to look at."), "/scout")

    def test_a_brief_that_could_not_be_mailed_is_not_marked_sent_and_the_push_goes_once(self):
        failed = mail.MailResult(sent=False, dry_run=False, error="SMTPAuthenticationError: bad password")
        os.environ["AI_MODEL"] = "template"
        config.reset()
        with mock.patch.object(chief.mail, "send", return_value=failed), mock.patch.object(chief.notify, "push") as push:
            line = chief.run(self.ctx(dry=False), now=BRIEF_UTC)
            self.assertIn("mail FAILED", line)
            self.assertIsNone(settings.get(self.conn, chief.SENT_KEY), "not sent, so not marked sent: the next hour tries again")
            err = db.one(self.conn, "SELECT agent, kind, message FROM errors")
            self.assertEqual((err["agent"], err["kind"]), ("chief", "brief_mail"))
            self.assertIn("bad password", err["message"])
            self.assertEqual(push.call_count, 1)
            self.assertIs(push.call_args.kwargs["conn"], self.conn)
            chief.run(self.ctx(dry=False), now=BRIEF_UTC + timedelta(hours=1))
            self.assertEqual(push.call_count, 1, "the phone is told once a day, however often the mail fails")
            self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors")["n"], 1, "said once while it stands")
        chief.run(self.ctx(), now=BRIEF_UTC + timedelta(hours=2))          # the mail works again (dry run: the outbox)
        self.assertEqual(settings.get(self.conn, chief.SENT_KEY), "2026-10-12")

    def test_a_disconnected_channel_links_to_the_buffer_page(self):
        db.insert(self.conn, "channels", buffer_channel_id="ch-ig", service="instagram", display_name="Event Caliber", connected=0)
        needs = dict(chief.gather(self.ctx(), BRIEF_UTC)["needs"])
        self.assertEqual(needs.get("Instagram is disconnected in Buffer. Reconnect it there."), "/buffer")

    def test_not_before_the_hour(self):
        self.assertEqual(chief.run(self.ctx(), now=datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)), "brief not due")

    def test_live_read_is_claude_and_rule_checked(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()

        class Fake:
            def __init__(self, read):
                self.read = read
                self.beta = self
                self.messages = self

            def create(self, **kw):
                t = types.SimpleNamespace(type="text", text=json.dumps({"read": self.read}))
                return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                             usage=types.SimpleNamespace(input_tokens=600, output_tokens=60))
        b = chief.gather(self.ctx(), BRIEF_UTC)
        self.assertEqual(chief.written_read(self.conn, b, client=Fake("Approve the post first. Then reply to Dana.")),
                         "Approve the post first. Then reply to Dana.")
        # a read that breaks a rule falls back to the plain sentence
        self.assertEqual(chief.written_read(self.conn, b, client=Fake("Trusted by every big con.")), chief.plain_read(b))

    def test_watchdog_hands_its_digest_to_the_chief(self):
        ctx = runner.Context("watchdog", self.conn, __import__("logging").getLogger("t"), config.get_config(), True, 0)
        summary = watchdog.run(ctx, now=BRIEF_UTC, probe=lambda url: 200)      # no Buffer key here: no client
        self.assertIn("digest: not due", summary)
        self.assertTrue(json.loads(settings.get(self.conn, "watchdog.notes")) is not None)
