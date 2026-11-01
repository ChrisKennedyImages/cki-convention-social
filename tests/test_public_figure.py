"""Chris, 2026-11-01: "LinkedIn posts avoid photos whose main subject is a recognisable public figure; Instagram stays as it
is." The art director judges the hero photo once (one Claude look through the till, stored on the photo, never asked
again, never by a name); judged so, the draft has no LinkedIn caption, card or tick and the draft page says why; a photo
not judged yet (a dry run, the cap, no key) is not sent to LinkedIn until it is, and the publisher judges it once when it
can. The other networks are untouched."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import art_director, content, publisher
from convention_social.buffer.client import BufferClient
from convention_social.core import auth, config, db, runner
from convention_social.dashboard import app as app_module
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render.motion import LINKEDIN_CARD
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_channels, add_photo, add_post, all_eligible, make_ctx, write_render
from tests._photos import jpeg_bytes

MONDAY_6AM = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)      # tomorrow is Tuesday: an event day
FRIDAY_8AM = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


class FinalClient:
    """Claude's final check passes every photo."""
    def __init__(self):
        self.beta = self
        self.messages = self

    def create(self, **kw):
        t = types.SimpleNamespace(type="text", text=json.dumps({"possible_minor": False, "personal_details": [], "summary": "ok"}))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=1500, output_tokens=100))


class Eye:
    """The art director's client: answers the public figure question with `figure` and every look with pass; counts each."""
    def __init__(self, figure: bool):
        self.figure = figure
        self.figure_calls = 0
        self.look_calls = 0
        self.beta = self
        self.messages = self

    def create(self, **kw):
        schema = kw["output_config"]["format"]["schema"]
        if "public_figure" in schema["properties"]:
            self.figure_calls += 1
            assert "Never write a name" in kw["system"][0]["text"], "told to name no one"
            assert sum(1 for b in kw["messages"][0]["content"] if b["type"] == "image") == 1, "one photo, on its own"
            answer = {"public_figure": self.figure}
        else:
            self.look_calls += 1
            answer = {"pictures": ["Fine."], "verdict": "pass", "focus_x": 0.5, "focus_y": 0.42, "notes": "Fine."}
        t = types.SimpleNamespace(type="text", text=json.dumps(answer))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=1000, output_tokens=50))


class DraftCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="fe", name="Con", clearance="cleared", first_seen_at=now, last_seen_at=now)
        self.pid = db.insert(self.conn, "photos", drive_id="e1", name="e1.jpg", folder_id="fe", width=3000, height=2000,
                             taken_at="2025:02:14 10:00:00", first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=self.pid, method="ollama", subject="event", convention_name="Katsucon",
                  is_convention=1, quality=5, possible_minor=0, personal_details="[]", space="exterior", residential=0,
                  empty_room=0, sharp=1, light=4, moment=4, classified_at=now)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def ctx(self, dry):
        config.get_config().ensure_dirs()
        return runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), dry, 0)

    def live(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        return self.ctx(dry=False)

    def fetch(self, row):
        return jpeg_bytes(seed=1, size=(3000, 2000))

    def row(self):
        return db.one(self.conn, "SELECT * FROM content_queue ORDER BY id DESC LIMIT 1")

    def photo(self):
        return db.one(self.conn, "SELECT public_figure, public_figure_at FROM photos WHERE id=?", (self.pid,))


class Draft(DraftCase):
    def test_a_public_figure_is_skipped_for_linkedin_and_the_draft_says_why(self):
        eye = Eye(True)
        line = content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient(), art_client=eye, figure_client=eye)
        self.assertIn("drafted post", line)
        self.assertIn("LinkedIn skipped (a public figure)", line)
        row = self.row()
        self.assertEqual(json.loads(row["targets"]), ["instagram", "facebook", "pinterest"])
        self.assertNotIn("linkedin", json.loads(row["caption"]), "no LinkedIn caption")
        self.assertNotIn(LINKEDIN_CARD, json.loads(row["render_paths"]), "no LinkedIn card")
        self.assertIn("2:3", json.loads(row["render_paths"]), "the other cards as before")
        meta = json.loads(row["rule_report"])
        self.assertEqual(meta["skipped"], {"linkedin": art_director.FIGURE_SKIP})
        self.assertNotIn("linkedin", meta["rules"])
        self.assertEqual(self.photo()["public_figure"], 1)
        self.assertTrue(self.photo()["public_figure_at"])
        self.assertEqual((eye.figure_calls, eye.look_calls), (1, 1), "one judgement, one look at the design")

    def test_not_a_public_figure_keeps_linkedin(self):
        eye = Eye(False)
        line = content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient(), art_client=eye, figure_client=eye)
        self.assertNotIn("LinkedIn skipped", line)
        row = self.row()
        self.assertEqual(json.loads(row["targets"]), list(content.TARGETS))
        self.assertIn("linkedin", json.loads(row["caption"]))
        self.assertIn(LINKEDIN_CARD, json.loads(row["render_paths"]))
        self.assertNotIn("skipped", json.loads(row["rule_report"]))
        self.assertEqual(self.photo()["public_figure"], 0, "judged no, stored so it is never asked again")
        self.assertEqual(eye.figure_calls, 1)

    def test_a_dry_run_judges_nothing_and_spends_nothing(self):
        eye = Eye(True)
        content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM, check_client=FinalClient(), art_client=eye, figure_client=eye)
        row = self.row()
        self.assertIn("linkedin", json.loads(row["targets"]), "not judged: the draft keeps LinkedIn, the publisher holds it")
        self.assertIsNone(self.photo()["public_figure"])
        self.assertEqual(eye.figure_calls, 0)

    def test_judged_once_and_never_again(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        eye = Eye(False)
        image = jpeg_bytes(seed=1)
        self.assertIs(art_director.public_figure(self.conn, self.pid, image, client=eye), False)
        self.assertIs(art_director.public_figure(self.conn, self.pid, image, client=eye), False)
        self.assertEqual(eye.figure_calls, 1, "the stored answer, not a second look")
        self.conn.execute("UPDATE photos SET public_figure=1 WHERE id=?", (self.pid,))
        self.assertIs(art_director.public_figure(self.conn, self.pid, image, client=Eye(False)), True, "the stored answer stands")
        self.assertIsNone(art_director.public_figure(self.conn, 999999, image, client=eye), "a photo not in the library")

    def test_an_answer_that_is_not_the_question_is_no_judgement(self):
        """The art director's review answer, or anything else, is never read as a verdict; nothing is stored."""
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()

        class Review(Eye):
            def create(self, **kw):
                t = types.SimpleNamespace(type="text", text=json.dumps({"verdict": "pass", "notes": "", "pictures": []}))
                return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                             usage=types.SimpleNamespace(input_tokens=10, output_tokens=5))
        self.assertIsNone(art_director.public_figure(self.conn, self.pid, jpeg_bytes(seed=1), client=Review(True)))
        self.assertIsNone(self.photo()["public_figure"])

    def test_the_cap_reached_means_no_call_and_no_answer(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        eye = Eye(True)
        self.assertIsNone(art_director.public_figure(self.conn, self.pid, jpeg_bytes(seed=1), client=eye))
        self.assertEqual(eye.figure_calls, 0)
        self.assertIsNone(self.photo()["public_figure"])
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        self.assertIsNone(art_director.public_figure(self.conn, self.pid, jpeg_bytes(seed=1), client=None), "no key: no look")
        self.assertIsNone(self.photo()["public_figure"])


class Publisher(IsolatedCase):
    """The hold at the door: a photo judged a public figure never goes to LinkedIn; one not judged yet waits."""

    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        p = mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible())
        p.start()
        self.addCleanup(p.stop)
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        add_channels(self.conn, "instagram", "linkedin")
        self.pid = add_photo(self.conn, self.root / "photos", seed=1)
        renders = {"4:5": [write_render(self.root / "renders", "r-45.jpg")], "2:3": [write_render(self.root / "renders", "r-23.jpg")],
                   LINKEDIN_CARD: [write_render(self.root / "renders", "r-linkedin.jpg")]}
        self.qid = add_post(self.conn, [self.pid], ("instagram", "linkedin"), render_paths=renders)

    def judged(self, value):
        self.conn.execute("UPDATE photos SET public_figure=? WHERE id=?", (value, self.pid))

    def row(self):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (self.qid,))

    def test_a_public_figure_never_goes_to_linkedin_and_it_is_no_fault(self):
        self.judged(1)
        stats = publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        row = self.row()
        self.assertEqual(set(json.loads(row["payload"])), {"instagram"})
        self.assertEqual(stats["skipped_networks"], 1)
        self.assertIn(art_director.FIGURE_SKIP, row["last_error"])
        self.assertEqual(json.loads(row["rule_report"])["skipped"], {"linkedin": art_director.FIGURE_SKIP})
        self.assertEqual(db.rows(self.conn, "SELECT kind FROM errors"), [], "a rule, not a fault")

    def test_judged_not_a_public_figure_goes(self):
        self.judged(0)
        publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        self.assertEqual(set(json.loads(self.row()["payload"])), {"instagram", "linkedin"})

    def test_not_judged_yet_waits_in_a_dry_run(self):
        eye = Eye(False)
        publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM, figure_client=eye)
        row = self.row()
        self.assertEqual(set(json.loads(row["payload"])), {"instagram"})
        self.assertIn(art_director.FIGURE_WAIT, row["last_error"])
        self.assertEqual(json.loads(row["rule_report"])["skipped"], {"linkedin": art_director.FIGURE_WAIT})
        self.assertEqual(eye.figure_calls, 0, "a dry run pays for nothing")

    def live_publish(self, eye):
        os.environ["AI_MONTHLY_CAP_USD"] = os.environ.get("AI_MONTHLY_CAP_USD", "5")
        config.reset()
        fake = FakeBuffer()
        client = BufferClient("test-key", conn=self.conn, transport=fake)
        uploads = []

        def up(path, key):
            uploads.append(key)
            return f"https://media.example/m/{key}"
        stats = publisher.publish_ready(make_ctx(self.conn, dry_run=False), client=client, uploader=up, now=FRIDAY_8AM, figure_client=eye)
        return stats, fake

    def test_live_the_publisher_judges_once_then_sends(self):
        eye = Eye(False)
        stats, fake = self.live_publish(eye)
        self.assertEqual(stats["scheduled"], 1)
        self.assertEqual([c["channelId"] for c in fake.created], ["ch-ig", "ch-li"])
        self.assertEqual(eye.figure_calls, 1)
        self.assertEqual(db.one(self.conn, "SELECT public_figure FROM photos WHERE id=?", (self.pid,))["public_figure"], 0)

    def test_live_a_public_figure_found_at_the_door_is_held(self):
        eye = Eye(True)
        stats, fake = self.live_publish(eye)
        self.assertEqual([c["channelId"] for c in fake.created], ["ch-ig"])
        self.assertIn(art_director.FIGURE_SKIP, self.row()["last_error"])

    def test_live_with_the_cap_reached_no_call_and_linkedin_waits(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        eye = Eye(True)
        stats, fake = self.live_publish(eye)
        self.assertEqual([c["channelId"] for c in fake.created], ["ch-ig"], "Instagram goes, LinkedIn waits")
        self.assertEqual(eye.figure_calls, 0)
        self.assertIn(art_director.FIGURE_WAIT, self.row()["last_error"])
        self.assertIsNone(db.one(self.conn, "SELECT public_figure FROM photos WHERE id=?", (self.pid,))["public_figure"])


class Page(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_draft_page_says_why_linkedin_is_not_sent(self):
        pid = add_photo(self.conn, self.root / "photos", seed=1)
        qid = add_post(self.conn, [pid], ("instagram", "facebook", "pinterest"), status="draft")
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?",
                          (json.dumps({"design": "single", "skipped": {"linkedin": art_director.FIGURE_SKIP}}), qid))
        page = self.client.get(f"/queue/{qid}").text
        self.assertIn("not sent: the photo&#39;s main subject is a recognisable public figure; LinkedIn posts avoid those (Chris, 2026-11-01)", page)
        import re
        self.assertRegex(page, r'name="target_linkedin"\s+style', "the LinkedIn box is unticked")
        self.assertRegex(page, r'name="target_instagram"\s+checked')
        self.assertNotIn('name="caption_linkedin"', page, "no caption box under a network that is not sent")
