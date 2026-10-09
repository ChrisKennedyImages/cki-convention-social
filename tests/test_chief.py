"""The Chief of staff's morning brief: what needs Chris comes first, once a day, never a paid call in dry run."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone

from convention_social.agents import chief, watchdog
from convention_social.core import config, db, runner, settings
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
