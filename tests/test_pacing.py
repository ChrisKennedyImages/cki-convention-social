"""Pacing: one post a day per network, at that network's own time; a time on the draft wins."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from convention_social.agents import pacing
from convention_social.core import config, db
from tests._fakes import AgentCase, add_post

NY = ZoneInfo("America/New_York")
FRIDAY_8AM = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)      # 08:00 New York, Friday
FRIDAY, SATURDAY, MONDAY = date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 12)


class Times(AgentCase):
    def test_founder_defaults(self):
        table = pacing.times_table()
        self.assertEqual(set(table), {"instagram", "facebook", "pinterest"})
        self.assertEqual(pacing.time_for("instagram", FRIDAY).strftime("%H:%M"), "11:30")
        self.assertEqual(pacing.time_for("instagram", SATURDAY).strftime("%H:%M"), "10:00")
        self.assertEqual(pacing.time_for("facebook", MONDAY).strftime("%H:%M"), "09:30")
        self.assertEqual(pacing.time_for("facebook", SATURDAY).strftime("%H:%M"), "09:30")
        self.assertEqual(pacing.time_for("pinterest", FRIDAY).strftime("%H:%M"), "20:30")
        text = pacing.describe()
        self.assertTrue(text)
        self.assertIn("Instagram 11:30 am weekdays, 10:00 am weekends.", text)
        self.assertIn("Pinterest 8:30 pm.", text)

    def test_post_times_overrides_and_ignores_garbage(self):
        os.environ["POST_TIMES"] = "instagram=12:15/09:05, facebook=08:00,pinterest=25:99,tiktok=10:00,nonsense"
        config.reset()
        table = pacing.times_table()
        self.assertTrue(table)
        self.assertNotIn("tiktok", table)
        self.assertEqual(pacing.time_for("instagram", FRIDAY).strftime("%H:%M"), "12:15")
        self.assertEqual(pacing.time_for("instagram", SATURDAY).strftime("%H:%M"), "09:05")
        self.assertEqual(pacing.time_for("facebook", SATURDAY).strftime("%H:%M"), "08:00", "one time means every day")
        self.assertEqual(pacing.time_for("pinterest", FRIDAY).strftime("%H:%M"), "20:30", "an unreadable time keeps the default")

    def test_the_lead_example_format(self):
        os.environ["POST_TIMES"] = "instagram=11:30,facebook=09:30,pinterest=20:30"
        config.reset()
        self.assertEqual(pacing.time_for("instagram", SATURDAY).strftime("%H:%M"), "11:30")


class Slots(AgentCase):
    def test_first_open_slot_per_network(self):
        conn = self.connect()
        ig = pacing.next_slot(conn, "instagram", FRIDAY_8AM)
        fb = pacing.next_slot(conn, "facebook", FRIDAY_8AM)
        pin = pacing.next_slot(conn, "pinterest", FRIDAY_8AM)
        self.assertIsNotNone(ig)
        self.assertEqual(pacing.slot_value(ig), "2026-10-09T11:30")
        self.assertEqual(pacing.slot_value(fb), "2026-10-09T09:30")
        self.assertEqual(pacing.slot_value(pin), "2026-10-09T20:30")
        late = datetime(2026, 10, 9, 13, 10, tzinfo=timezone.utc)       # 09:10, inside the 30 minute lead
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "facebook", late)), "2026-10-10T09:30")

    def test_one_post_per_network_per_local_day(self):
        conn = self.connect()
        qid = add_post(conn, [1], ("instagram", "facebook"), status="scheduled")
        payload = {"instagram": {"dueAt": "2026-10-09T15:30:00Z"}, "facebook": {"dueAt": "2026-10-10T13:30:00Z"}}
        conn.execute("UPDATE content_queue SET payload=? WHERE id=?", (json.dumps(payload), qid))
        taken = pacing.taken_days(conn, "instagram", NY)
        self.assertTrue(taken)
        self.assertEqual(taken, {FRIDAY})
        # Friday is taken on Instagram, so the next one is Saturday at the weekend time
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "instagram", FRIDAY_8AM)), "2026-10-10T10:00")
        # Facebook has Saturday taken, Friday still open
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "facebook", FRIDAY_8AM)), "2026-10-09T09:30")
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "pinterest", FRIDAY_8AM)), "2026-10-09T20:30")

    def test_dry_rows_count_only_when_asked_and_history_counts(self):
        conn = self.connect()
        qid = add_post(conn, [1], ("pinterest",), status="would_publish")
        conn.execute("UPDATE content_queue SET payload=? WHERE id=?",
                     (json.dumps({"pinterest": {"dueAt": "2026-10-10T00:30:00Z"}}), qid))
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "pinterest", FRIDAY_8AM)), "2026-10-09T20:30")
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "pinterest", FRIDAY_8AM, include_dry=True)), "2026-10-10T20:30")
        db.insert(conn, "post_history", buffer_post_id="p1", service="facebook", sent_at="2026-10-09T13:31:00+00:00")
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "facebook", FRIDAY_8AM)), "2026-10-10T09:30")

    def test_a_time_on_the_draft_wins_for_every_network(self):
        conn = self.connect()
        chosen = pacing.plan(conn, ["instagram", "pinterest"], "2026-10-12T14:00", FRIDAY_8AM)
        self.assertEqual(chosen, {"instagram": "2026-10-12T14:00", "pinterest": "2026-10-12T14:00"})
        free = pacing.plan(conn, ["instagram", "pinterest"], None, FRIDAY_8AM)
        self.assertEqual(free, {"instagram": "2026-10-09T11:30", "pinterest": "2026-10-09T20:30"})
