"""The AI cap sees every paid call (the 2026-11-09 audit's money findings)."""
from __future__ import annotations

import os
import types

from convention_social.ai import spend
from convention_social.core import config, db
from convention_social.library import classify
from tests._base import IsolatedCase


class Client:
    """Stands in for the Anthropic client: counts the calls, answers one sort."""

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail
        self.messages = types.SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls += 1
        if self.fail:
            raise OSError("the network")
        return types.SimpleNamespace(stop_reason="end_turn", model=kw["model"],
                                     usage={"input_tokens": 1000, "output_tokens": 100},
                                     content=[types.SimpleNamespace(type="text", text='{"subject": "event"}')])


class TheCapSeesEveryCall(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["AI_MONTHLY_CAP_USD"] = "10"
        config.reset()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def spent(self):
        return spend.cycle_to_date(self.conn)

    def test_a_model_with_no_price_is_counted_at_the_dearest_rate_never_free(self):
        dearest_in, dearest_out = max(r[0] for r in spend.RATES.values()), max(r[1] for r in spend.RATES.values())
        self.assertIsNone(spend.rate_for("claude-mirage-7"))
        self.assertEqual(spend.cost_usd("claude-mirage-7", 1_000_000, 1_000_000), dearest_in + dearest_out)
        held = spend.reserve(self.conn, "t", "claude-mirage-7")
        cost = spend.record(self.conn, "t", "claude-mirage-7", 100_000, 10_000, reservation=held)
        self.assertGreater(cost, 0)
        self.assertEqual(round(self.spent(), 6), cost, "settling an unknown model never turns its hold into $0")

    def test_the_paid_sorter_does_not_call_claude_past_the_cap(self):
        db.insert(self.conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent="t", units=1, unit_kind="tokens",
                  cost_usd=10.0, detail="x")
        client = Client()
        sorter = classify.ClaudeSorter(self.conn, agent="phone", client=client, model="claude-opus-5")
        with self.assertRaises(classify.CapReached):
            sorter.classify(b"", "hint")
        self.assertEqual(client.calls, 0)

    def test_a_thumbnail_that_cannot_be_read_calls_nothing_and_holds_nothing(self):
        client = Client()
        sorter = classify.ClaudeSorter(self.conn, agent="phone", client=client, model="claude-opus-5")
        with self.assertRaises(Exception):
            sorter.classify(b"not a jpeg", "hint")          # the thumbnail cannot be read: no call, nothing held
        self.assertEqual((client.calls, self.spent()), (0, 0.0))

    def test_a_failed_call_gives_its_hold_back(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (40, 30), (9, 9, 9)).save(buf, "JPEG")
        failing = Client(fail=True)
        sorter = classify.ClaudeSorter(self.conn, agent="phone", client=failing, model="claude-opus-5")
        with self.assertRaises(OSError):
            sorter.classify(buf.getvalue(), "hint")
        self.assertEqual((failing.calls, self.spent()), (1, 0.0), "the hold is released, not left on the cap")
        ok = Client()
        sorter = classify.ClaudeSorter(self.conn, agent="phone", client=ok, model="claude-opus-5")
        self.assertEqual(sorter.classify(buf.getvalue(), "hint"), {"subject": "event"})
        rows = db.rows(self.conn, "SELECT cost_usd, detail FROM api_usage WHERE provider='anthropic'")
        self.assertEqual(len(rows), 1, "one row: the hold became the call")
        self.assertTrue(0 < rows[0]["cost_usd"] < spend.RESERVE_USD)
        self.assertNotIn(spend.RESERVED, rows[0]["detail"])
