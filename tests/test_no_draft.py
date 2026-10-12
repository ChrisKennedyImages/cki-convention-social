"""Chris, 2026-10-12: "the render didn't land this morning at 8am". A morning with no draft is said out loud:
the reason on the phone and on the Agents page, never a quiet summary line; and the two quiet reasons the
final check had (the monthly cap, no key) are errors the moment they bite."""
from __future__ import annotations

import os
from unittest import mock

from convention_social.agents import content
from convention_social.core import config, db, runner
from convention_social.library import classify
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes


class NoDraft(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        config.get_config().ensure_dirs()

    def ctx(self, dry=False):
        return runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), dry, 0)

    def errors(self):
        return db.rows(self.conn, "SELECT kind, message FROM errors WHERE agent='content' ORDER BY id")

    def go(self, summary, dry=False):
        with mock.patch("convention_social.agents.content.draft_one", return_value=summary), \
             mock.patch.object(content.notify, "push") as push:
            line = content.run(self.ctx(dry), fetch=lambda row: jpeg_bytes())
        return line, push

    def test_no_draft_is_an_error_and_a_ping_with_the_reason(self):
        line, push = self.go("no photo passed the final check for 2026-10-13 (tried 5)")
        self.assertEqual(line, "no photo passed the final check for 2026-10-13 (tried 5)")
        errs = self.errors()
        self.assertEqual([e["kind"] for e in errs], ["no_draft"])
        self.assertIn("No post was drafted for 2026-", errs[0]["message"])
        self.assertIn("no photo passed the final check", errs[0]["message"])
        self.assertEqual(push.call_count, 1)
        title, body = push.call_args.args
        self.assertIn("no post drafted for", title)
        self.assertIn("no photo passed the final check", body)
        self.assertFalse(push.call_args.kwargs["dry_run"])
        self.assertTrue(push.call_args.kwargs["click"].endswith("/agents"))
        self.go("no photo ready for 2026-10-13: clear folders on the Library page (nothing drafted)")
        self.assertEqual(len(self.errors()), 2, "a different reason is its own line")
        self.go("no photo ready for 2026-10-13: clear folders on the Library page (nothing drafted)")
        self.assertEqual(len(self.errors()), 2, "the same open reason is one line, not one per run")

    def test_a_draft_or_an_already_drafted_day_is_quiet(self):
        for summary in ("drafted post #9 for 2026-10-13 (event): single with 1 photo(s)", "DRY RUN drafted post #9 for 2026-10-13",
                        "a post for 2026-10-13 is already drafted"):
            line, push = self.go(summary)
            self.assertEqual(line, summary)
            self.assertEqual(push.call_count, 0, summary)
        self.assertEqual(self.errors(), [])

    def test_the_cap_is_named_when_it_is_the_reason(self):
        with mock.patch("convention_social.ai.spend.cap_reached", return_value=True):
            line, push = self.go("no photo passed the final check for 2026-10-13 (tried 5)")
        self.assertIn("the monthly AI cap is reached (Keys page, AI)", self.errors()[0]["message"])
        self.assertIn("monthly AI cap", push.call_args.args[1])

    def test_a_dry_run_says_it_but_sends_nothing(self):
        line, push = self.go("no photo ready for 2026-10-13: clear folders on the Library page (nothing drafted)", dry=True)
        self.assertEqual(push.call_count, 1)
        self.assertTrue(push.call_args.kwargs["dry_run"])


class TheFinalCheckSpeaks(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def errors(self):
        return db.rows(self.conn, "SELECT agent, kind FROM errors ORDER BY id")

    def test_the_cap_and_a_missing_key_are_errors_once_not_silence(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        self.assertIsNone(classify.look(self.conn, jpeg_bytes(), agent="content"))
        self.assertIsNone(classify.look(self.conn, jpeg_bytes(), agent="content"))
        self.assertEqual([(e["agent"], e["kind"]) for e in self.errors()], [("content", "ai_cap")])
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        self.assertIsNone(classify.look(self.conn, jpeg_bytes(), agent="site"), "no key in a test")
        self.assertEqual([(e["agent"], e["kind"]) for e in self.errors()], [("content", "ai_cap"), ("site", "no_ai_key")])
        self.assertIn("Keys page, AI", db.one(self.conn, "SELECT message FROM errors WHERE kind='no_ai_key'")["message"])
