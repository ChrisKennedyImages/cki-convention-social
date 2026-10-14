"""Never a wedding, and every photo judged on its own (Chris, 2026-10-11: "The main photo when you open the
website is from a damn wedding! That one needs to be the best of the best and not a wedding! Don't get stuck
on certain photos. They get judge individually not against anything but itself")."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone

from PIL import Image

from convention_social.agents import content
from convention_social.core import config, db, runner
from convention_social.dashboard import app as dash
from convention_social.library import classify, eligibility
from convention_social.render import design_samples
from convention_social.site import build
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say


class FinalClient:
    """Claude's final check answering a kind per photo (by drive id) and business for the rest."""
    def __init__(self, kinds=None, shot_type="stage_panel"):
        self.kinds, self.shot_type, self.calls, self.current = kinds or {}, shot_type, [], None
        self.beta = self.messages = self

    def create(self, **kw):
        self.calls.append(self.current)
        assert kw["output_config"]["format"]["schema"] is classify.FINAL_SCHEMA
        body = {"possible_minor": False, "personal_details": [], "shot_type": self.shot_type,
                "event_kind": self.kinds.get(self.current, "business"), "summary": "A room."}
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(body))], stop_reason="end_turn",
                                     model=kw["model"], usage=types.SimpleNamespace(input_tokens=1500, output_tokens=100))


def event_photo(conn, drive_id, *, kind="unknown", quality=5, sharp=1, light=4, moment=4, width=3000, height=2000, folder="fe",
                final=None):
    """A cleared, sorted event photo; `final` is the kind an existing final check carries (None for none, "" for an
    old check from before the question)."""
    now = db.utcnow()
    if db.one(conn, "SELECT 1 FROM drive_folders WHERE drive_id=?", (folder,)) is None:
        db.insert(conn, "drive_folders", drive_id=folder, name="Con", clearance="cleared", first_seen_at=now, last_seen_at=now)
    pid = db.insert(conn, "photos", drive_id=drive_id, name=f"{drive_id}.jpg", folder_id=folder, width=width, height=height,
                    taken_at="2025:02:14 10:00:00", first_seen_at=now, last_seen_at=now)
    db.insert(conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name="Liberty Summit",
              event_kind=kind, is_convention=0 if kind in classify.NOT_OFFERED_KINDS else 1, quality=quality, possible_minor=0,
              personal_details="[]", space="exterior", residential=0, empty_room=0, sharp=sharp, light=light, moment=moment,
              shot_type="stage_panel", classified_at=now)
    if final is not None:
        db.insert(conn, "final_checks", photo_id=pid, possible_minor=0, personal_details="[]", model="m", checked_at=now,
                  shot_type="stage_panel", event_kind=final or None)
    return pid


class TheWord(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()

    def test_the_sorter_and_the_final_check_are_both_asked_what_kind_of_occasion(self):
        for schema in (classify.SCHEMA, classify.FINAL_SCHEMA):
            self.assertEqual(schema["properties"]["event_kind"]["enum"], ["fan", "business", "wedding", "private", "unknown"])
            self.assertIn("event_kind", schema["required"])
        for prompt in (classify.SYSTEM, classify.FINAL_SYSTEM):
            self.assertIn('wedding', prompt)
            self.assertIn("bride", prompt)
        self.assertIn("A wedding is never business", classify.FINAL_SYSTEM)

    def test_claude_calling_it_a_wedding_keeps_it_out_everywhere(self):
        pid = event_photo(self.conn, "w1", kind="unknown")
        self.assertEqual(eligibility.is_candidate(self.conn, pid), (True, "ok"), "the sorter could not tell")
        self.assertTrue(eligibility.needs_kind_check(self.conn, pid))
        client = FinalClient({"w1": "wedding"})
        client.current = "w1"
        data = classify.final_check(self.conn, pid, jpeg_bytes(), client=client)
        self.assertEqual(data["event_kind"], "wedding")
        fc = db.one(self.conn, "SELECT event_kind FROM final_checks WHERE photo_id=?", (pid,))
        cls = db.one(self.conn, "SELECT event_kind, is_convention FROM classifications WHERE photo_id=?", (pid,))
        self.assertEqual((fc["event_kind"], cls["event_kind"], cls["is_convention"]), ("wedding", "wedding", 0))
        self.assertEqual(eligibility.is_candidate(self.conn, pid), (False, eligibility.NOT_OFFERED_KIND_WHY))
        self.assertEqual(eligibility.is_eligible(self.conn, pid), (False, eligibility.NOT_OFFERED_KIND_WHY))
        self.assertFalse(eligibility.needs_kind_check(self.conn, pid))
        self.assertFalse(design_samples.usable(self.conn, {"id": pid, "shot_type": "stage_panel", "event_kind": "wedding"}))
        # a business answer leaves the photo in, and is the word the sorter's row now carries
        pid2 = event_photo(self.conn, "b1", kind="unknown")
        client.current = "b1"
        classify.final_check(self.conn, pid2, jpeg_bytes(), client=client)
        self.assertEqual(db.one(self.conn, "SELECT event_kind FROM classifications WHERE photo_id=?", (pid2,))["event_kind"], "business")
        self.assertEqual(eligibility.is_eligible(self.conn, pid2), (True, "ok"))

    def test_the_sorters_own_wedding_word_keeps_it_out_too(self):
        pid = event_photo(self.conn, "s1", kind="unknown")
        photo = db.one(self.conn, "SELECT * FROM photos WHERE id=?", (pid,))
        answer = {"subject": "event", "event_kind": "wedding", "event_name_seen": "", "shot_type": "dinner_reception",
                  "view": "interior", "quality": 5, "people_count": 2, "possible_minor": False, "personal_details": [],
                  "space": "none", "residential": False, "empty_room": False, "sharp": True, "light": 5, "moment": 5, "summary": "A first dance."}
        classify.save_sort(self.conn, photo, answer, "ollama", "qwen")
        cls = db.one(self.conn, "SELECT event_kind, is_convention, subject FROM classifications WHERE photo_id=?", (pid,))
        self.assertEqual((cls["event_kind"], cls["is_convention"], cls["subject"]), ("wedding", 0, "event"))
        self.assertEqual(eligibility.is_candidate(self.conn, pid), (False, eligibility.NOT_OFFERED_KIND_WHY))
        # and the Photos tab never offers it for review
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        self.conn.execute("UPDATE drive_folders SET clearance='not_cleared'")
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        self.assertEqual(dash.count_photos(self.conn, "review"), 0)
        event_photo(self.conn, "ok1", kind="business")
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        self.assertEqual(dash.count_photos(self.conn, "review"), 1)

    def test_the_final_checks_word_alone_keeps_a_photo_out(self):
        pid = event_photo(self.conn, "f1", kind="business", final="wedding")       # the sorter said business; Claude said wedding
        self.assertEqual(eligibility.is_candidate(self.conn, pid), (True, "ok"))
        self.assertEqual(eligibility.is_eligible(self.conn, pid), (False, "the final check says " + eligibility.NOT_OFFERED_KIND_WHY))

    def test_an_old_final_check_needs_the_question_asked_again(self):
        old = event_photo(self.conn, "o1", kind="business", final="")
        new = event_photo(self.conn, "n1", kind="business", final="business")
        self.assertTrue(eligibility.needs_kind_check(self.conn, old))
        self.assertFalse(eligibility.needs_kind_check(self.conn, new))
        self.assertEqual(eligibility.is_eligible(self.conn, old), (True, "ok"), "an old check still counts where nobody can ask again")


class TheSite(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        self.fetched = []

    def fetch(self, row):
        self.fetched.append(row["drive_id"])
        return Image.new("RGB", (int(row["width"]), int(row["height"])), (80, 60, 120))

    def test_the_hero_is_the_strongest_frame_on_its_own_merit_never_a_wedding(self):
        event_photo(self.conn, "soft", kind="business", quality=5, sharp=0, light=5, moment=5, final="business")   # quality 5 but soft
        event_photo(self.conn, "best", kind="business", quality=4, sharp=1, light=5, moment=5, final="business")
        event_photo(self.conn, "tall", kind="business", quality=5, sharp=1, light=5, moment=5, width=2000, height=3000, final="business")
        event_photo(self.conn, "wed", quality=5, sharp=1, light=5, moment=5, final="wedding", kind="wedding")
        event_photo(self.conn, "mystery", quality=5, sharp=1, light=5, moment=5, final="unknown", kind="unknown")
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(self.fetched[0], "best", "the hero: sharp and lit beats a soft quality 5; a known conference beats an unknown kind")
        self.assertNotIn("wed", self.fetched)
        self.assertEqual(len(photos.hero), 1)
        self.assertEqual(sorted(self.fetched), ["best", "mystery", "soft", "tall"])

    def test_a_photo_claude_has_not_judged_for_its_kind_is_asked_during_the_build(self):
        event_photo(self.conn, "old", quality=5, final="")                      # a check from before the question
        event_photo(self.conn, "never", quality=5)                              # never checked at all
        event_photo(self.conn, "known", quality=3, final="business")
        client = FinalClient({"old": "wedding", "never": "business"})

        def recheck(row, image):
            client.current = row["drive_id"]
            return classify.final_check(self.conn, row["id"], jpeg_bytes(), client=client, agent="site")
        photos = build.pick_photos(self.conn, self.fetch, recheck=recheck)
        self.assertEqual(sorted(client.calls), ["never", "old"])
        self.assertEqual(self.fetched[0], "old", "fetched to be looked at")
        self.assertEqual(len(photos.hero), 1)
        self.assertEqual(len(photos.coverage), 1)                               # never (the hero) and known; old was a wedding
        old_id = db.one(self.conn, "SELECT id FROM photos WHERE drive_id='old'")["id"]
        self.assertEqual(db.one(self.conn, "SELECT event_kind FROM classifications WHERE photo_id=?", (old_id,))["event_kind"], "wedding")
        self.assertEqual(eligibility.is_eligible(self.conn, old_id)[0], False)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage WHERE agent='site'")["n"], 2, "paid through the one till")

    def test_without_the_hook_a_never_checked_photo_waits_and_an_old_check_still_counts(self):
        event_photo(self.conn, "old", quality=5, final="")
        event_photo(self.conn, "never", quality=4)
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(self.fetched, ["old"])
        self.assertEqual(len(photos.hero), 1)

    def test_the_build_asks_at_most_twelve_times(self):
        for i in range(15):
            event_photo(self.conn, f"p{i:02d}", quality=5)
        client = FinalClient()

        def recheck(row, image):
            client.current = row["drive_id"]
            return classify.final_check(self.conn, row["id"], jpeg_bytes(), client=client, agent="site")
        photos = build.pick_photos(self.conn, self.fetch, recheck=recheck)
        self.assertEqual(len(client.calls), 12, "the cap: the rest wait for another build or a draft")
        # twelve checked photos: the hero and eleven frames (the strip holds twelve since 2026-10-14; it held six)
        self.assertEqual((len(photos.hero), len(photos.coverage)), (1, min(build.COVERAGE_ROWS, build.RECHECKS - 1)))
        self.assertEqual(build.RECHECKS, 12)

    def test_a_check_claude_refuses_keeps_the_photo_out(self):
        event_photo(self.conn, "x", quality=5)
        photos = build.pick_photos(self.conn, self.fetch, recheck=lambda row, image: None)
        self.assertEqual(len(photos.hero), 0)


class TheDraft(IsolatedCase):
    def test_a_live_draft_drops_a_photo_claude_calls_a_wedding(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        config.get_config().ensure_dirs()
        event_photo(conn, "w", quality=5)
        event_photo(conn, "c", quality=4)
        client = FinalClient({"w": "wedding"})
        fetched = []

        def fetch(row):
            client.current = row["drive_id"]
            fetched.append(row["drive_id"])
            return jpeg_bytes(seed=len(fetched), size=(3000, 2000))
        ctx = runner.Context("content", conn, __import__("logging").getLogger("t"), config.get_config(), False, 0)
        art = ArtClientAny([say("pass", notes="ok")])
        content.draft_one(ctx, fetch, now=datetime(2026, 10, 13, 10, tzinfo=timezone.utc), check_client=client, art_client=art)
        row = db.one(conn, "SELECT photo_ids, rule_report FROM content_queue ORDER BY id DESC LIMIT 1")
        ids = json.loads(row["photo_ids"])
        self.assertEqual(ids, [db.one(conn, "SELECT id FROM photos WHERE drive_id='c'")["id"]])
        self.assertEqual(db.one(conn, "SELECT event_kind FROM classifications WHERE photo_id=?",
                                (db.one(conn, "SELECT id FROM photos WHERE drive_id='w'")["id"],))["event_kind"], "wedding")
