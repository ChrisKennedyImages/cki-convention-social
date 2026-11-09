"""Chris, 2026-11-01 evening, asked whether LinkedIn should skip photos where an organization's name or logo is prominent:
"Yes, skip on LinkedIn". That skip is gone: 2026-11-08, "NOTHING IS PRIVATE because I have hand approved every photo! No
one can override MY approvals and that is a law"; asked whether that covers the LinkedIn logo skip too, "Yes, override
everything". A photo he used goes to every network he posts to, a logo in it or not, and no model is asked about it."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import art_director, content, publisher
from convention_social.buffer.client import BufferClient
from convention_social.core import auth, config, db, runner
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render.photo import LINKEDIN_PHOTO
from tests._base import IsolatedCase
from tests._fakes import camera_time, FakeBuffer, add_channels, add_photo, add_post, all_eligible, make_ctx, write_render
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
    """The art director's client: passes every look; a question about a logo would be counted, and none is asked."""
    def __init__(self):
        self.logo_calls = 0
        self.look_calls = 0
        self.beta = self
        self.messages = self

    def create(self, **kw):
        schema = kw["output_config"]["format"]["schema"]
        if "prominent_logo" in schema["properties"]:
            self.logo_calls += 1
            answer = {"prominent_logo": True}
        elif "subject" in schema["properties"]:
            answer = {"subject": "unclear"}
        else:
            self.look_calls += 1
            answer = {"pictures": ["Fine."], "verdict": "pass", "focus_x": 0.5, "focus_y": 0.42, "notes": "Fine."}
        t = types.SimpleNamespace(type="text", text=json.dumps(answer))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=1000, output_tokens=50))


class DraftCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,facebook,pinterest,linkedin"   # every network on: these tests pin every card (2026-11-02)
        config.reset()
        self.conn = db.connect()
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="fe", name="Con", first_seen_at=now, last_seen_at=now)
        self.pid = db.insert(self.conn, "photos", drive_id="e1", name="e1.jpg", folder_id="fe", width=3000, height=2000,
                             taken_at=camera_time(), clearance="cleared", clearance_at=now,     # his Use: a folder never approves
                             first_seen_at=now, last_seen_at=now)
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


class Draft(DraftCase):
    def test_a_photo_with_a_prominent_logo_gets_its_linkedin_caption_photo_and_tick(self):
        eye = Eye()
        line = content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient(), art_client=eye, judge_client=eye)
        self.assertIn("drafted post", line)
        self.assertNotIn("LinkedIn skipped", line)
        row = self.row()
        self.assertEqual(json.loads(row["targets"]), list(content.TARGETS))
        self.assertIn("linkedin", json.loads(row["caption"]))
        self.assertIn(LINKEDIN_PHOTO, json.loads(row["render_paths"]))
        self.assertNotIn("skipped", json.loads(row["rule_report"]))
        self.assertEqual((eye.logo_calls, eye.look_calls), (0, 1), "no question about a logo; one look at the design")
        self.assertFalse(hasattr(art_director, "prominent_logo"), "the judgement is gone")
        self.assertFalse(hasattr(art_director, "LOGO_SKIP"))
        columns = [c[1] for c in self.conn.execute("PRAGMA table_info(photos)")]
        self.assertNotIn("prominent_logo", columns, "and its columns (migration 0102)")
        self.assertNotIn("prominent_logo_at", columns)


class Publisher(IsolatedCase):
    """At the door: a photo goes to LinkedIn like any other, and nothing is asked about a logo in it."""

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
                   LINKEDIN_PHOTO: [write_render(self.root / "renders", "r-linkedin.jpg")]}
        self.qid = add_post(self.conn, [self.pid], ("instagram", "linkedin"), render_paths=renders)

    def row(self):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (self.qid,))

    def test_it_goes_to_linkedin_in_a_dry_run(self):
        stats = publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        self.assertEqual(set(json.loads(self.row()["payload"])), {"instagram", "linkedin"})
        self.assertEqual(stats["skipped_networks"], 0)
        self.assertFalse(hasattr(publisher, "linkedin_hold"), "the hold is gone")

    def test_live_it_goes_to_both(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        fake = FakeBuffer()
        client = BufferClient("test-key", conn=self.conn, transport=fake)
        stats = publisher.publish_ready(make_ctx(self.conn, dry_run=False), client=client,
                                        uploader=lambda path, key: f"https://media.example/m/{key}", now=FRIDAY_8AM)
        self.assertEqual(stats["scheduled"], 1)
        self.assertEqual([c["channelId"] for c in fake.created], ["ch-ig", "ch-li"])


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

    def test_the_draft_page_still_says_why_a_network_is_held(self):
        """The repeat window still holds a network (when a photo airs, not whether), and the page says so."""
        pid = add_photo(self.conn, self.root / "photos", seed=1)
        qid = add_post(self.conn, [pid], ("instagram", "facebook", "pinterest"), status="draft")
        why = "the photo went out on LinkedIn as post #3 inside the repeat window"
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?",
                          (json.dumps({"design": "single", "skipped": {"linkedin": why}}), qid))
        page = self.client.get(f"/queue/{qid}").text
        self.assertIn(f"not sent: {why}", page)
        self.assertRegex(page, r'name="target_linkedin"\s+style', "the LinkedIn box is unticked")
        self.assertRegex(page, r'name="target_instagram"\s+checked')
        self.assertNotIn('name="caption_linkedin"', page, "no caption box under a network that is not sent")
