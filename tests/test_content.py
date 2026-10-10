"""The daily draft: the right kind of photo for the day, variety, the final check, designs, and no paid call in dry run."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from convention_social.agents import content
from convention_social.core import config, db, runner
from convention_social.render import meta
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

TUESDAY_6AM = datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)     # tomorrow is Wednesday: the building day
MONDAY_6AM = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)      # tomorrow is Tuesday: an event day


class FinalClient:
    """Claude's final check: answers per photo from a dict {drive_id: possible_minor}."""
    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.calls = 0
        self.beta = self
        self.messages = self
        self.current = None

    def create(self, **kw):
        self.calls += 1
        minor = self.verdicts.get(self.current, False)
        t = types.SimpleNamespace(type="text", text=json.dumps({"possible_minor": minor, "personal_details": [], "summary": "ok"}))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=1500, output_tokens=100))


class Content(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="fe", name="Con", clearance="cleared", first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "drive_folders", drive_id="fa", name="Hotel exteriors", clearance="cleared", first_seen_at=now, last_seen_at=now)
        self.ids = {}
        for n, (did, folder, subject, event, q) in enumerate((("e1", "fe", "event", "Katsucon", 5), ("e2", "fe", "event", "Katsucon", 4),
                                                              ("e3", "fe", "event", "Otakon", 3), ("a1", "fa", "architecture", None, 5))):
            pid = db.insert(self.conn, "photos", drive_id=did, name=f"{did}.jpg", folder_id=folder, width=3000, height=2000,
                            taken_at="2025:02:14 10:00:00", first_seen_at=now, last_seen_at=now)
            db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject=subject, convention_name=event,
                      is_convention=int(subject == "event"), quality=q, possible_minor=0, personal_details="[]", classified_at=now)
            self.ids[did] = pid
        self.fetched = []

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def ctx(self, dry=True):
        config.get_config().ensure_dirs()
        return runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), dry, 0)

    def fetch(self, row):
        self.fetched.append(row["drive_id"])
        return jpeg_bytes(seed=len(self.fetched), size=(3000, 2000))

    def queue(self):
        return db.rows(self.conn, "SELECT * FROM content_queue ORDER BY id")

    def test_dry_run_drafts_with_no_paid_call_and_cannot_be_approved_yet(self):
        line = content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM)
        self.assertIn("DRY RUN drafted post", line)
        rows = self.queue()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(json.loads(row["photo_ids"]), [self.ids["e1"]])          # best event photo
        renders = json.loads(row["render_paths"])
        self.assertEqual(sorted(renders), ["2:3", "4:5"])
        for paths in renders.values():
            self.assertEqual(meta.is_clean(Path(paths[0])), [])
            self.assertIn(b"at Katsucon", Path(paths[0]).read_bytes())          # our SEO title travels in the file
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='anthropic'")["n"], 0)
        from convention_social.library import eligibility
        self.assertEqual(eligibility.is_eligible(self.conn, self.ids["e1"]), (False, "not given the final check yet"))
        # a second run the same day drafts nothing new
        self.assertIn("already drafted", content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM))

    def test_building_day_and_variety(self):
        content.draft_one(self.ctx(), self.fetch, now=TUESDAY_6AM)
        self.assertEqual(json.loads(self.queue()[0]["photo_ids"]), [self.ids["a1"]])
        content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM)
        self.assertEqual(json.loads(self.queue()[1]["photo_ids"]), [self.ids["e1"]])
        # next event day: Katsucon was just used, so Otakon, not the other Katsucon photo
        content.draft_one(self.ctx(), self.fetch, now=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(json.loads(self.queue()[2]["photo_ids"]), [self.ids["e3"]])
        # a building day with no building left falls back to event work (a new event; the Katsucon photo still sits out)
        now = db.utcnow()
        pid = db.insert(self.conn, "photos", drive_id="e4", name="e4.jpg", folder_id="fe", width=3000, height=2000,
                        first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name="Awesome Con",
                  quality=2, possible_minor=0, personal_details="[]", classified_at=now)
        content.draft_one(self.ctx(), self.fetch, now=datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc))
        meta = json.loads(self.queue()[3]["rule_report"])
        self.assertEqual((meta["wanted"], meta["subject"], meta["event"]), ("architecture", "event", "Awesome Con"))

    def test_live_final_check_skips_a_possible_minor(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        client = FinalClient({"e1": True})
        orig = self.fetch

        def fetch(row):
            client.current = row["drive_id"]
            return orig(row)
        line = content.draft_one(self.ctx(dry=False), fetch, now=MONDAY_6AM, check_client=client)
        self.assertIn("drafted post", line)
        self.assertEqual(json.loads(self.queue()[0]["photo_ids"]), [self.ids["e2"]])
        self.assertEqual(client.calls, 2)
        from convention_social.library import eligibility
        self.assertTrue(eligibility.is_eligible(self.conn, self.ids["e2"])[0])
        self.assertFalse(eligibility.is_eligible(self.conn, self.ids["e1"])[0])

    def test_nothing_cleared_nothing_drafted(self):
        self.conn.execute("UPDATE drive_folders SET clearance='not_cleared'")
        self.assertIn("nothing drafted", content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM))
        self.assertEqual(self.queue(), [])
        self.assertEqual(self.fetched, [])


class ArtClient:
    """The art director's eye: answers from a list, one per look."""
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        assert kw["model"] == "claude-opus-5" and kw["fallbacks"] == "default"
        assert sum(1 for b in kw["messages"][0]["content"] if b["type"] == "image") == 2     # both aspects, side by side
        a = self.answers.pop(0)
        t = types.SimpleNamespace(type="text", text=json.dumps(a))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=2500, output_tokens=150))


def say(verdict, x=0.5, y=0.42, notes="Fine."):
    return {"verdict": verdict, "focus_x": x, "focus_y": y, "notes": notes}


class ArtDirector(Content):
    def live(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        return self.ctx(dry=False)

    def test_redo_reworks_the_crop_then_passes(self):
        art = ArtClient([say("redo", 0.3, 0.2, "The head is cut at the top."), say("pass", notes="Strong crop now.")])
        content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient({}), art_client=art)
        self.assertEqual(art.calls, 2)
        meta = json.loads(self.queue()[0]["rule_report"])
        self.assertTrue(meta["art"])
        self.assertEqual((meta["art"]["verdict"], meta["art"]["rounds"], meta["art"]["focus"]), ("pass", 2, [0.3, 0.2]))
        self.assertEqual(self.queue()[0]["status"], "draft")

    def test_reject_turns_the_photo_back_and_the_next_one_is_drafted(self):
        art = ArtClient([say("reject", notes="Soft focus on the face."), say("pass")])
        line = content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient({}), art_client=art)
        self.assertIn("turned back photo", line)
        rows = self.queue()
        self.assertEqual([r["status"] for r in rows], ["rejected", "draft"])
        self.assertIn("Soft focus", rows[0]["last_error"])
        self.assertEqual(json.loads(rows[1]["photo_ids"]), [self.ids["e2"]])      # the turned back post never aired, so its event is still fair
        # the turned back photo sits out next time too
        self.assertIn(self.ids["e1"], content.recent_use(self.conn, 30)[0])

    def test_redo_stops_after_the_limit(self):
        art = ArtClient([say("redo")] * 5)
        content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient({}), art_client=art)
        self.assertEqual(art.calls, 3)                                         # one look and two reworks
        self.assertEqual(json.loads(self.queue()[0]["rule_report"])["art"]["verdict"], "redo")

    def test_dry_run_is_not_reviewed_and_costs_nothing(self):
        content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM)
        self.assertEqual(json.loads(self.queue()[0]["rule_report"])["art"]["verdict"], "not reviewed")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage")["n"], 0)
