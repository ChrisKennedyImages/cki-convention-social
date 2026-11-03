"""What a photo shows is Claude's word, then Chris's; never only the local sorter's guess.
Chris, 2026-10-11: "it calls a stage shot a portrait which, never can happen!"."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import content
from convention_social.ai import copy_rules, seo_plan
from convention_social.core import auth, config, db, runner
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import classify, copies
from tests._base import IsolatedCase
from tests._fakes import camera_time, add_photo, add_post
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say


class FinalClient:
    """Claude's final check: no minor, nothing readable, and what the photo shows."""
    def __init__(self, shot_type="stage_panel"):
        self.shot_type, self.calls = shot_type, 0
        self.beta = self.messages = self

    def create(self, **kw):
        self.calls += 1
        assert kw["output_config"]["format"]["schema"] is classify.FINAL_SCHEMA
        body = {"possible_minor": False, "personal_details": [], "shot_type": self.shot_type, "summary": "A speaker at a podium."}
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(body))], stop_reason="end_turn",
                                     model=kw["model"], usage=types.SimpleNamespace(input_tokens=1500, output_tokens=100))


def stage_photo_called_a_portrait(conn) -> int:
    now = db.utcnow()
    db.insert(conn, "drive_folders", drive_id="fe", name="Conference", first_seen_at=now, last_seen_at=now)
    pid = db.insert(conn, "photos", drive_id="e1", name="e1.jpg", folder_id="fe", width=3000, height=2000,
                    taken_at=camera_time(), clearance="cleared", clearance_at=now,     # his Use: a folder never approves
                    first_seen_at=now, last_seen_at=now)
    db.insert(conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name="Liberty Summit",
              event_kind="business", is_convention=1, quality=5, possible_minor=0, personal_details="[]", space="exterior",
              residential=0, empty_room=0, sharp=1, light=4, moment=4, shot_type="portrait", classified_at=now)
    return pid


class FinalCheck(IsolatedCase):
    def test_claudes_word_is_kept_and_replaces_the_sorters_guess(self):
        conn = db.connect()
        pid = stage_photo_called_a_portrait(conn)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        data = classify.final_check(conn, pid, jpeg_bytes(), client=FinalClient("stage_panel"))
        self.assertEqual(data["shot_type"], "stage_panel")
        self.assertEqual(db.one(conn, "SELECT shot_type FROM final_checks WHERE photo_id=?", (pid,))["shot_type"], "stage_panel")
        self.assertEqual(db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (pid,))["shot_type"], "stage_panel")
        self.assertIn("stage_panel: several people seated on a stage", classify.FINAL_SYSTEM)
        self.assertIn("shot_type", classify.FINAL_SCHEMA["required"])
        # Chris, 2026-10-26: "The sorting should also not name names! Just the type of image!"
        from pathlib import Path
        from convention_social.ai import claude as writer
        for text in (classify.SYSTEM, classify.FINAL_SYSTEM, classify.SCHEMA["properties"]["summary"]["description"],
                     classify.FINAL_SCHEMA["properties"]["summary"]["description"], writer.OUTPUT_SCHEMA["properties"]["photo_summary"]["description"]):
            self.assertIn("person's name", text.lower().replace("person\u2019s", "person's"), "every description asked of a model forbids naming anyone")
        conn.execute("UPDATE classifications SET summary=? WHERE photo_id=?", ("A senator waves to the crowd.", pid))
        conn.executescript(Path(db.MIGRATIONS_DIR, "0083_summaries_name_no_one.sql").read_text())
        self.assertEqual(db.one(conn, "SELECT summary FROM classifications WHERE photo_id=?", (pid,))["summary"], "", "what the old prompt wrote is cleared")
        self.assertTrue(classify.set_shot_type(conn, pid, "candid"))
        self.assertFalse(classify.set_shot_type(conn, pid, "selfie"), "not a shot type: nothing written")
        self.assertEqual(db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (pid,))["shot_type"], "candid")
        conn.close()


class Draft(IsolatedCase):
    def test_every_word_on_the_post_follows_what_claude_saw(self):
        conn = db.connect()
        pid = stage_photo_called_a_portrait(conn)
        os.environ.update(AI_MONTHLY_CAP_USD="5", AI_MODEL="template", BRAND_DOMAIN="eventcaliber.com")
        config.reset()
        config.get_config().ensure_dirs()
        ctx = runner.Context("content", conn, __import__("logging").getLogger("t"), config.get_config(), False, 0)
        line = content.draft_one(ctx, lambda row: jpeg_bytes(seed=1, size=(3000, 2000)), now=datetime(2026, 10, 13, 10, tzinfo=timezone.utc),
                                 check_client=FinalClient("stage_panel"), art_client=ArtClientAny([say("pass")]))
        self.assertIn('for "conference photography"', line, "a stage shot, not conference headshots")
        row = db.one(conn, "SELECT caption, render_paths, rule_report FROM content_queue")
        meta = json.loads(row["rule_report"])
        self.assertEqual(meta["seo"]["primary"], "conference photography")
        self.assertEqual(meta["alt_text"], "Stage panel at a conference, photographed by Event Caliber")
        self.assertNotIn("headshot", row["caption"].lower())
        self.assertNotIn("portrait", row["caption"].lower())
        for paths in json.loads(row["render_paths"]).values():
            data = Path(paths[0]).read_bytes()
            self.assertIn(b"Stage panel at a conference", data, "the file's own search fields too")
            self.assertNotIn(b"Portrait at", data)
        conn.close()


class CorrectionCase(IsolatedCase):
    """A signed-in dashboard and the stage photo the sorter called a portrait, with its final check."""

    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.pid = stage_photo_called_a_portrait(self.conn)
        db.insert(self.conn, "final_checks", photo_id=self.pid, possible_minor=0, personal_details="[]", model="m",
                  checked_at=db.utcnow(), shot_type="portrait")

    def shot(self, table):
        return db.one(self.conn, f"SELECT shot_type FROM {table} WHERE photo_id=?", (self.pid,))["shot_type"]


class Correction(CorrectionCase):
    def test_chris_fixes_the_word_and_a_new_draft_is_made(self):
        qid = add_post(self.conn, [self.pid], status="draft")
        page = self.client.get(f"/queue/{qid}").text
        self.assertIn("shows: portrait", page)
        self.assertIn("Wrong? Fix and draft again", page)
        with mock.patch.object(dash, "start_agent") as start:
            r = self.client.post(f"/queue/{qid}/photo/{self.pid}/shot", data={"shot_type": "stage_panel"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/?msg=redraft"))
        self.assertEqual(start.call_args[0], ("content",))
        self.assertEqual((self.shot("classifications"), self.shot("final_checks")), ("stage_panel", "stage_panel"))
        row = db.one(self.conn, "SELECT status, last_error FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "rejected")
        self.assertIn("shows Stage panel", row["last_error"])
        self.assertIn("new one is being made", self.client.get("/?msg=redraft").text)

    def test_refusals_and_a_post_already_approved(self):
        qid = add_post(self.conn, [self.pid], status="draft")
        with mock.patch.object(dash, "start_agent") as start:
            self.assertEqual(self.client.post(f"/queue/{qid}/photo/{self.pid}/shot", data={"shot_type": "selfie"}).status_code, 400)
            self.assertEqual(self.client.post(f"/queue/{qid}/photo/999/shot", data={"shot_type": "candid"}).status_code, 400)
            self.assertEqual(start.call_count, 0)
            self.assertEqual(self.shot("classifications"), "portrait")
            approved = add_post(self.conn, [self.pid], status="approved")
            r = self.client.post(f"/queue/{approved}/photo/{self.pid}/shot", data={"shot_type": "candid"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], f"/queue/{approved}?msg=saved")
        self.assertEqual(self.shot("classifications"), "candid")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (approved,))["status"], "approved")
        self.assertEqual(start.call_count, 0, "an approved post is not redrafted behind Chris's back")


class HisWord(CorrectionCase):
    """Chris, 2026-11-02: "I also want to be able to change the type of shot that is miss labeled. Most backstage images
    are called candid". He sets the kind on the photo list or under the swipe card; it is his word on every copy of the
    picture, the room printed on a post with it, and no later look by a model replaces it."""

    def test_his_word_outlasts_every_later_look(self):
        self.assertTrue(classify.set_shot_type(self.conn, self.pid, "backstage"))
        row = db.one(self.conn, "SELECT shot_type, shot_by FROM classifications WHERE photo_id=?", (self.pid,))
        self.assertEqual((row["shot_type"], row["shot_by"]), ("backstage", "chris"))
        self.assertEqual(db.one(self.conn, "SELECT room FROM final_checks WHERE photo_id=?", (self.pid,))["room"], "backstage")
        # the sorter's second look keeps it
        photo = db.one(self.conn, "SELECT * FROM photos WHERE id=?", (self.pid,))
        classify.save_sort(self.conn, photo, {"subject": "event", "event_kind": "business", "shot_type": "candid", "quality": 4},
                           "vision", "m")
        self.assertEqual(self.shot("classifications"), "backstage")
        # and so does the final check before a post: his word, and the room printed with it
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        classify.final_check(self.conn, self.pid, jpeg_bytes(), client=FinalClient("candid"))
        fc = db.one(self.conn, "SELECT shot_type, room FROM final_checks WHERE photo_id=?", (self.pid,))
        self.assertEqual((self.shot("classifications"), fc["shot_type"], fc["room"]), ("backstage", "backstage", "backstage"))

    def test_the_photo_list_sets_it_on_every_copy_and_a_waiting_draft_is_made_again(self):
        now = db.utcnow()
        self.conn.execute("UPDATE photos SET md5='same' WHERE id=?", (self.pid,))
        twin = db.insert(self.conn, "photos", drive_id="e2", name="e2.jpg", folder_id="fe", width=3000, height=2000, md5="same",
                         taken_at=camera_time(), first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=twin, method="ollama", subject="event", is_convention=1, quality=5,
                  possible_minor=0, personal_details="[]", shot_type="candid", classified_at=now)
        copies.link(self.conn)                         # the scanner's pass makes them one picture
        page = self.client.get("/library?view=approved").text
        self.assertIn(f'action="/library/photo/{self.pid}/shot"', page)
        self.assertIn('<option value="portrait" selected>Portrait</option>', page)
        self.assertIn('<option value="backstage">Backstage</option>', page)
        draft = add_post(self.conn, [self.pid], status="draft")
        approved = add_post(self.conn, [self.pid], status="approved")
        with mock.patch.object(dash, "start_agent") as start:
            self.assertEqual(self.client.post(f"/library/photo/{self.pid}/shot", data={"shot_type": "selfie"}).status_code, 400)
            r = self.client.post(f"/library/photo/{self.pid}/shot", data={"shot_type": "backstage"},
                                 headers={"Accept": "application/json"})
        self.assertEqual(r.json(), {"id": self.pid, "shot": "backstage", "kind": "backstage",
                                    "words": "Kind of shot: Backstage. The draft with it is being made again."})
        for pid in (self.pid, twin):
            row = db.one(self.conn, "SELECT shot_type, shot_by FROM classifications WHERE photo_id=?", (pid,))
            self.assertEqual((row["shot_type"], row["shot_by"]), ("backstage", "chris"), pid)
        row = db.one(self.conn, "SELECT status, last_error FROM content_queue WHERE id=?", (draft,))
        self.assertEqual((row["status"], row["last_error"]),
                         ("rejected", f"Set aside: photo {self.pid} shows Backstage, not what the caption said. Drafted again."))
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (approved,))["status"], "approved",
                         "an approved post is not redrafted behind his back")
        self.assertEqual(start.call_args_list, [mock.call("content")])

    def test_the_swipe_card_shows_the_kind_of_the_photo_on_top(self):
        self.conn.execute("UPDATE photos SET clearance='inherit', clearance_at=NULL WHERE id=?", (self.pid,))
        self.conn.execute("UPDATE classifications SET method='vision' WHERE photo_id=?", (self.pid,))
        page = self.client.get("/library/swipe").text
        self.assertIn('<label for="kind">Kind of shot</label>', page)
        self.assertIn('<option value="portrait" selected>Portrait</option>', page)
        self.assertIn('<option value="backstage">Backstage</option>', page)
        self.assertNotIn("Building exterior", page.split('id="kind"')[1].split("</select>")[0], "an event photo's kinds only")
        self.assertIn('"shot": "portrait"', page)


class Everywhere(IsolatedCase):
    """Chris, 2026-10-11: "Where I work is everywhere so what do I put"."""

    def test_nationwide_a_base_or_both(self):
        self.assertEqual(seo_plan.place_phrase("nationwide"), "Covering events nationwide, wherever yours is.")
        self.assertEqual(seo_plan.place_phrase("Washington DC"), "Covering events in Washington DC and beyond.")
        self.assertEqual(seo_plan.place_phrase("Washington DC, nationwide"), "Based in Washington DC, covering events nationwide.")
        self.assertEqual(seo_plan.place_phrase("everywhere"), "Covering events nationwide, wherever yours is.")
        for area, words in (("nationwide", ["nationwide"]), ("Washington DC, nationwide", ["Washington DC", "nationwide"])):
            os.environ["SERVICE_AREA"] = area
            config.reset()
            plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="stage_panel")
            caps = seo_plan.template_captions(plan, "eventcaliber.com/book", "Event Caliber")
            self.assertEqual(seo_plan.problems(caps, plan), [])
            for w in words:
                self.assertIn(w, caps["facebook"])
                self.assertIn(w, " ".join(plan.prompt_lines()))
            self.assertTrue(copy_rules.check(caps["facebook"]).ok)
            bare = {n: "Conference photography on stage. Your event photographer. Request a quote." for n in caps}
            self.assertTrue(any("does not mention" in p for p in seo_plan.problems(bare, plan)))
