"""Chris, 2026-10-15: "Stop with this 18 and under bullshit! It stops damn near half the images from posting and its
wildly incorrect. Get rid of the gate all together! If I approve something, it means I checked it and you are not
required!" And the same morning: "we are ONLY using Insta now so get rid of the other socails or tunr off thier errors".

No model judges anyone's age, and an age flag written before the ruling stops nothing: eligibility, the review list,
the best-frames picker and the prompts. Everything else that stops a photo still stops it. Posts go to Instagram only
until he switches another network on (POST_NETWORKS on the Keys page), and a network that is off is never reported
as missing a channel."""
from __future__ import annotations

import json
import os

from datetime import datetime, timezone
from unittest import mock

from convention_social.agents import publisher
from convention_social.buffer import payloads
from convention_social.core import config, db
from convention_social.library import classify, eligibility
from tests._base import IsolatedCase
from tests._fakes import AgentCase, add_channels, add_photo, add_post, all_eligible, make_ctx, write_render


def photo(conn, n, *, minor, folder="f-1", clearance="cleared", details="[]", kind="business", final=True):
    now = db.utcnow()
    if not db.one(conn, "SELECT 1 FROM drive_folders WHERE drive_id=?", (folder,)):
        db.insert(conn, "drive_folders", drive_id=folder, name="Con 2026", clearance=clearance, first_seen_at=now, last_seen_at=now)
    pid = db.insert(conn, "photos", drive_id=f"d{n}", name=f"{n}.jpg", mime_type="image/jpeg", folder_id=folder,
                    width=3000, height=2000, first_seen_at=now, last_seen_at=now)
    db.insert(conn, "classifications", photo_id=pid, method="ollama", subject="event", is_convention=1, possible_minor=minor,
              personal_details=details, event_kind=kind, shot_type="candid", quality=5, light=4, moment=4, sharp=1, classified_at=now)
    if final:
        db.insert(conn, "final_checks", photo_id=pid, possible_minor=minor, personal_details=details, event_kind=kind,
                  model="m", checked_at=now)
    return pid


class NoAgeGate(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def test_an_age_flag_stops_nothing(self):
        flagged = photo(self.conn, 1, minor=1)
        self.assertEqual(eligibility.is_candidate(self.conn, flagged), (True, "ok"))
        self.assertEqual(eligibility.is_eligible(self.conn, flagged), (True, "ok"))
        self.assertEqual(eligibility.eligible_photo_ids(self.conn, [flagged]), [flagged])

    def test_everything_else_still_stops_a_photo(self):
        self.assertIn("vehicle_plate", eligibility.is_eligible(self.conn, photo(self.conn, 2, minor=0, details='["vehicle_plate"]'))[1])
        self.assertFalse(eligibility.is_eligible(self.conn, photo(self.conn, 3, minor=0, kind="wedding"))[0])
        self.assertEqual(eligibility.is_eligible(self.conn, photo(self.conn, 4, minor=0, folder="f-2", clearance="not_cleared")),
                         (False, "not cleared yet"))
        self.assertEqual(eligibility.is_eligible(self.conn, photo(self.conn, 5, minor=0, final=False)), (False, "not given the final check yet"))
        blocked = photo(self.conn, 6, minor=0)
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (blocked,))
        self.assertEqual(eligibility.is_eligible(self.conn, blocked), (False, "Chris blocked this photo"))
        unsorted = photo(self.conn, 7, minor=None, final=False)
        self.conn.execute("UPDATE classifications SET method='folder' WHERE photo_id=?", (unsorted,))
        self.assertEqual(eligibility.is_candidate(self.conn, unsorted), (False, "not sorted yet"), "a model must still have looked")

    def test_no_prompt_asks_about_age(self):
        for text in (classify.SYSTEM, classify.FINAL_SYSTEM):
            self.assertNotIn("under 18", text)
            self.assertNotIn("possible_minor", text)
        for schema in (classify.SCHEMA, classify.FINAL_SCHEMA):
            self.assertNotIn("possible_minor", schema["properties"])
            self.assertNotIn("possible_minor", schema["required"])

    def test_the_review_list_shows_a_flagged_photo(self):
        from convention_social.dashboard import app as dash
        self.assertNotIn("possible_minor", dash.VIEWS["review"][0])

    def test_no_code_reads_the_age_flag_and_no_prompt_asks(self):
        """The gate is gone everywhere, not only in eligibility: until 2026-10-24 reels3d.fillers kept flagged photos
        off a reel's wall, and the caption writer was still asked whether anyone could be under 18 (nothing read
        the answer). The column stays in the database; no line of code reads it and no prompt asks."""
        import re
        from pathlib import Path
        import convention_social
        from convention_social.ai import claude as captions
        self.assertNotIn("under 18", captions.SYSTEM_PROMPT)
        self.assertNotIn("possible_minor", captions.SYSTEM_PROMPT)
        self.assertNotIn("possible_minor", captions.OUTPUT_SCHEMA["properties"])
        self.assertNotIn("possible_minor", captions.OUTPUT_SCHEMA["required"])
        pkg = Path(convention_social.__file__).resolve().parent
        reads = re.compile(r"""\[\s*['"]possible_minor['"]\s*\]|\.get\(\s*['"]possible_minor['"]|(?<!excluded)\.possible_minor\b""")
        hits = [f"{p.relative_to(pkg)}:{n}" for p in sorted(pkg.rglob("*.py")) if "__pycache__" not in p.parts
                for n, line in enumerate(p.read_text().splitlines(), 1) if reads.search(line)]
        self.assertEqual(hits, [], "a line of code reads the age flag")
        self.assertTrue(reads.search('if r["possible_minor"]:'), "the pin catches a planted read")


class InstagramOnly(AgentCase):
    def setUp(self):
        super().setUp()
        os.environ["PINTEREST_BOARD_ID"] = "board-123"
        config.reset()
        p = mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible())
        p.start()
        self.addCleanup(p.stop)
        self.conn = self.connect()

    def post(self):
        pid = add_photo(self.conn, self.root / "photos", seed=1)
        renders = {"4:5": [write_render(self.root / "renders", "r-45.jpg")], "2:3": [write_render(self.root / "renders", "r-23.jpg")]}
        return add_post(self.conn, [pid], render_paths=renders)

    def test_the_default_is_instagram_only(self):
        self.assertEqual(payloads.posting_networks(), ("instagram",))
        os.environ["POST_NETWORKS"] = " Instagram, facebook , nonsense"
        config.reset()
        self.assertEqual(payloads.posting_networks(), ("instagram", "facebook"))

    def test_only_instagram_goes_and_the_others_say_nothing(self):
        add_channels(self.conn, "instagram")                 # Facebook and Pinterest are not connected in Buffer
        qid = self.post()
        stats = publisher.publish_ready(make_ctx(self.conn), now=datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc))
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "would_publish")
        self.assertEqual(set(json.loads(row["payload"])), {"instagram"})
        self.assertEqual(stats["skipped_networks"], 0)
        self.assertFalse(row["last_error"])
        self.assertEqual(db.rows(self.conn, "SELECT kind FROM errors WHERE kind='no_channel'"), [], "no alert for a network that is off")

    def test_a_network_switched_back_on_goes_again(self):
        os.environ["POST_NETWORKS"] = "instagram,facebook"
        config.reset()
        add_channels(self.conn, "instagram", "facebook")
        qid = self.post()
        publisher.publish_ready(make_ctx(self.conn), now=datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc))
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(set(json.loads(row["payload"])), {"instagram", "facebook"})
