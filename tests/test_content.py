"""The daily draft: the right kind of photo for the day, variety, the final check, designs, and no paid call in dry run."""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timedelta, timezone
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
    """Claude's final check: answers per photo from a dict {drive_id: True} for a photo that fails (a readable plate).
    Until 2026-10-15 the failing answer was "someone may be under 18"; Chris ruled the age gate out, so `minors` now
    answers possible_minor true on photos that must still pass (an old-style answer stops nothing)."""
    def __init__(self, verdicts, minors=()):
        self.verdicts = verdicts
        self.minors = set(minors)
        self.calls = 0
        self.beta = self
        self.messages = self
        self.current = None

    def create(self, **kw):
        self.calls += 1
        plate = self.verdicts.get(self.current, False)
        t = types.SimpleNamespace(type="text", text=json.dumps({"possible_minor": self.current in self.minors,
                                                                "personal_details": ["vehicle_plate"] if plate else [], "summary": "ok"}))
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
                      is_convention=int(subject == "event"), quality=q, possible_minor=0, personal_details="[]",
                      space="exterior", residential=0, empty_room=0, sharp=1, light=4, moment=4, classified_at=now)
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
            data = Path(paths[0]).read_bytes()
            self.assertIn(b"Event photography", data)                         # our SEO title travels in the file
            self.assertNotIn(b"Katsucon", data)                               # never which event (2026-10-11)
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
                  quality=2, possible_minor=0, personal_details="[]", space="exterior", residential=0, empty_room=0, sharp=1, light=4, moment=4, classified_at=now)
        content.draft_one(self.ctx(), self.fetch, now=datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc))
        meta = json.loads(self.queue()[3]["rule_report"])
        self.assertEqual((meta["wanted"], meta["subject"], meta["event"]), ("architecture", "event", "Awesome Con"))

    def test_an_event_posted_lately_comes_after_the_others_not_never(self):
        """2026-10-26: 1,481 of the 1,796 approved event photos are CPAC Texas, and CPAC had posted inside VARIETY_DAYS,
        so the daily draft's event wall left six candidates and the same six came round on every draft ("it keeps
        posting the same photos again"). The rule is the designed drafts' (2026-10-15): fresh events first while one
        is left, then the rest; the repeat window on the photo itself is untouched."""
        when = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat()
        db.insert(self.conn, "content_queue", kind="photo", photo_ids="[999]", targets='["instagram"]', caption="{}",
                  status="published", created_at=when, updated_at=when, rule_report=json.dumps({"event": "Katsucon"}))
        order = [r["id"] for r in content.candidates(self.conn, "event")]
        self.assertEqual(order[0], self.ids["e3"], "Otakon, which no post had lately, leads")
        self.assertEqual(sorted(order[1:]), sorted([self.ids["e1"], self.ids["e2"]]), "Katsucon follows instead of vanishing")
        db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps([self.ids["e1"]]), targets='["instagram"]', caption="{}",
                  status="published", created_at=when, updated_at=when, rule_report=json.dumps({"event": "Katsucon"}))
        self.assertNotIn(self.ids["e1"], [r["id"] for r in content.candidates(self.conn, "event")], "a photo on a post inside the window still sits out")

    def test_live_final_check_skips_a_photo_with_a_plate(self):
        """Deliberate change, 2026-10-15 (no age gate): this pinned the skip of a possible minor; the final check's
        skip is now pinned with a readable plate, which still stops a photo."""
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

    def test_live_an_age_answer_skips_nothing(self):
        """Chris, 2026-10-15: "Get rid of the gate all together!" A final check that answers possible_minor true
        (an old-style answer) leaves the photo on the post."""
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        client = FinalClient({}, minors={"e1"})
        orig = self.fetch

        def fetch(row):
            client.current = row["drive_id"]
            return orig(row)
        line = content.draft_one(self.ctx(dry=False), fetch, now=MONDAY_6AM, check_client=client)
        self.assertIn("drafted post", line)
        self.assertEqual(json.loads(self.queue()[0]["photo_ids"]), [self.ids["e1"]])
        self.assertEqual(client.calls, 1)

    def test_nothing_cleared_nothing_drafted(self):
        self.conn.execute("UPDATE drive_folders SET clearance='not_cleared'")
        self.assertIn("nothing drafted", content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM))
        self.assertEqual(self.queue(), [])
        self.assertEqual(self.fetched, [])

    def test_a_photo_in_a_post_chris_set_aside_sits_out(self):
        """2026-10-13: his reject counts like the art director's: the photo sits out for the repeat window and the
        day is drafted again with another one. The event is not "used": nothing of a set-aside post aired."""
        content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM)
        first = self.queue()[0]
        self.assertEqual(json.loads(first["photo_ids"]), [self.ids["e1"]])
        meta = json.loads(first["rule_report"])
        meta.update(rejected_by="chris", rejected_at=db.utcnow())
        self.conn.execute("UPDATE content_queue SET status='rejected', rule_report=?, updated_at=? WHERE id=?",
                          (json.dumps(meta), db.utcnow(), first["id"]))
        used_photos, used_events, _ = content.recent_use(self.conn, 30)
        self.assertIn(self.ids["e1"], used_photos)
        self.assertNotIn("katsucon", used_events)
        line = content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM)
        self.assertIn("drafted post", line)
        self.assertEqual(json.loads(self.queue()[1]["photo_ids"]), [self.ids["e2"]], line)

    def test_todays_post_set_aside_is_drafted_again_today(self):
        """A reject after 08:00, when tomorrow's post already stands: today is drafted again, not lost. A day
        that never had a post is not filled this way (the agent's job is tomorrow; the window retries that)."""
        content.draft_one(self.ctx(), self.fetch, now=TUESDAY_6AM)          # Wednesday's post, made Tuesday morning
        self.assertIn("already drafted", content.draft_one(self.ctx(), self.fetch, now=TUESDAY_6AM))
        self.assertEqual(len(self.queue()), 1, "Tuesday never had a post and nothing was set aside: nothing is made for it")
        content.draft_one(self.ctx(), self.fetch, now=MONDAY_6AM)           # Tuesday's post, as if made Monday
        tuesday = self.queue()[1]
        self.assertEqual(json.loads(tuesday["rule_report"])["for_day"], "2026-10-13")
        self.assertIn("already drafted", content.draft_one(self.ctx(), self.fetch, now=TUESDAY_6AM))
        meta = json.loads(tuesday["rule_report"])
        meta.update(rejected_by="chris", rejected_at=db.utcnow())
        self.conn.execute("UPDATE content_queue SET status='rejected', rule_report=?, updated_at=? WHERE id=?",
                          (json.dumps(meta), db.utcnow(), tuesday["id"]))
        line = content.draft_one(self.ctx(), self.fetch, now=TUESDAY_6AM)
        self.assertIn(f"drafted post", line)
        self.assertIn(meta["for_day"], line)
        again = self.queue()[2]
        self.assertEqual(json.loads(again["rule_report"])["for_day"], meta["for_day"])
        self.assertNotEqual(json.loads(again["photo_ids"]), json.loads(tuesday["photo_ids"]), "the set-aside photo sits out")
        self.assertIn("already drafted", content.draft_one(self.ctx(), self.fetch, now=TUESDAY_6AM))


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
        assert kw["messages"][0]["content"][-1]["text"].endswith("Review this post."), "told what it sees, then asked"
        a = self.answers.pop(0)
        t = types.SimpleNamespace(type="text", text=json.dumps(a))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=2500, output_tokens=150))


def say(verdict, x=0.5, y=0.42, notes="Fine.", pictures=("Looks fine.",)):
    return {"pictures": list(pictures), "verdict": verdict, "focus_x": x, "focus_y": y, "notes": notes}


class ArtDirector(Content):
    def setUp(self):
        super().setUp()
        # the art director's redo reworks a crop, which only the single photo card has (a phone send uses it); since
        # 2026-10-15 no day of the week is the single, so these drafts keep Tuesday on it to pin the redo itself
        from unittest import mock
        keep = mock.patch.dict(content.DESIGNS, {"tuesday": "single"})
        keep.start()
        self.addCleanup(keep.stop)

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


class TheDraftSurvivesTheAPI(ArtDirector):
    """2026-10-13: an Anthropic error in the final check, the caption writer or the art director used to stop
    the 08:00 run dead, with no "no draft" ping and no retry until the next morning."""

    def test_a_final_check_that_cannot_run_is_a_reason_not_a_dead_run(self):
        class Broken(FinalClient):
            def create(self, **kw):
                self.calls += 1
                raise ConnectionError("api down")
        client = Broken({})
        line = content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=client)
        self.assertIn("the final check could not run for 2026-10-13", line)
        self.assertIn("ConnectionError", line)
        self.assertEqual(self.queue(), [])
        errs = db.rows(self.conn, "SELECT kind, message FROM errors WHERE agent='content' AND kind != 'ntfy'")   # live in a test: no topic
        self.assertEqual([e["kind"] for e in errs], ["final_check"], "said once, not once per photo")
        self.assertIn("ConnectionError: api down", errs[0]["message"])
        self.assertGreaterEqual(client.calls, 2, "every candidate was tried before giving up")

    def test_a_writer_that_cannot_write_leaves_the_template_and_says_so(self):
        class Broken:
            model = "claude-test"

            def draft(self, facts, photo, notes=()):
                raise content.claude.DraftError("APIConnectionError: Connection error.")
        line = content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient({}), drafter=Broken(),
                                 art_client=ArtClient([say("pass")]))
        self.assertIn("drafted post", line)
        meta_ = json.loads(self.queue()[0]["rule_report"])
        self.assertEqual(meta_["model"], "template")
        self.assertIn("APIConnectionError", meta_["seo"]["writer_error"])
        errs = db.rows(self.conn, "SELECT kind, message FROM errors WHERE agent='content' AND kind != 'ntfy'")   # live in a test: no topic
        self.assertEqual([e["kind"] for e in errs], ["captions"])
        self.assertIn("APIConnectionError", errs[0]["message"])

    def test_an_art_director_that_cannot_look_lets_the_draft_through_marked_not_reviewed(self):
        class Broken(ArtClient):
            def create(self, **kw):
                self.calls += 1
                raise ConnectionError("api down")
        line = content.draft_one(self.live(), self.fetch, now=MONDAY_6AM, check_client=FinalClient({}), art_client=Broken([]))
        self.assertIn("drafted post", line)
        meta_ = json.loads(self.queue()[0]["rule_report"])
        self.assertEqual(meta_["art"]["verdict"], "not reviewed")
        errs = db.rows(self.conn, "SELECT kind, message FROM errors WHERE kind != 'ntfy'")   # live in a test: no topic
        self.assertEqual([e["kind"] for e in errs], ["art_director"])
        self.assertIn("ConnectionError: api down", errs[0]["message"])

    def test_the_claude_writer_turns_api_errors_into_draft_errors(self):
        from convention_social.ai import claude
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()

        class Raising:
            def __init__(self):
                self.beta = self
                self.messages = self

            def create(self, **kw):
                raise ConnectionError("no route")
        photo = self.root / "p.jpg"
        photo.write_bytes(jpeg_bytes())
        facts = claude.PostFacts(brand_name="Event Caliber", event_kind="business")
        with self.assertRaises(claude.DraftError) as caught:
            claude.ClaudeDrafter(self.conn, client=Raising()).draft(facts, photo)
        self.assertIn("ConnectionError: no route", str(caught.exception))
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        with self.assertRaises(claude.SpendCapReached):
            claude.ClaudeDrafter(self.conn, client=Raising()).draft(facts, photo)


class TheCapIsHeldInFlight(ArtDirector):
    """8.2 (2026-10-13): the cap was checked but never held, so two agents could each overshoot it by one call.
    Every paid call reserves first, settles the reservation to its real cost (one row), lets it go when the call
    fails, and makes no call at all when the reservation itself would pass the cap."""

    def setUp(self):
        super().setUp()
        os.environ["AI_MONTHLY_CAP_USD"] = "1"
        config.reset()

    def spent(self, usd):
        db.insert(self.conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent="t", units=1, unit_kind="tokens", cost_usd=usd, detail="x")

    def ledger(self):
        return db.rows(self.conn, "SELECT cost_usd, detail FROM api_usage WHERE provider='anthropic' AND detail != 'x'")

    def settled(self, rows, word):
        from convention_social.ai import spend
        self.assertEqual(len(rows), 1, "the reservation settled into the one real row, not a second one")
        self.assertIn(word, rows[0]["detail"])
        self.assertNotIn("reserved", rows[0]["detail"])
        self.assertGreater(rows[0]["cost_usd"], 0)
        self.assertLess(rows[0]["cost_usd"], spend.RESERVE_USD, "the real cost, not the estimate")

    def test_the_caption_writer(self):
        from convention_social.ai import claude

        class Writer:
            def __init__(self, fail=False):
                self.fail, self.calls = fail, 0
                self.beta = self
                self.messages = self

            def create(self, **kw):
                self.calls += 1
                if self.fail:
                    raise ConnectionError("no route")
                return types.SimpleNamespace(content=[], stop_reason="refusal", model=kw["model"],
                                             usage=types.SimpleNamespace(input_tokens=10_000, output_tokens=1_000))
        photo = self.root / "p.jpg"
        photo.write_bytes(jpeg_bytes())
        facts = claude.PostFacts(brand_name="Event Caliber", event_kind="business")
        with self.assertRaises(claude.DraftError):            # a refusal: the call was made and is paid for
            claude.ClaudeDrafter(self.conn, client=Writer()).draft(facts, photo)
        self.settled(self.ledger(), "caption")
        with self.assertRaises(claude.DraftError):
            claude.ClaudeDrafter(self.conn, client=Writer(fail=True)).draft(facts, photo)
        self.assertEqual(len(self.ledger()), 1, "a call that failed holds nothing")
        self.spent(0.85)                                      # under the cap, but one more call's reservation would pass it
        writer = Writer()
        with self.assertRaises(claude.SpendCapReached):
            claude.ClaudeDrafter(self.conn, client=writer).draft(facts, photo)
        self.assertEqual(writer.calls, 0, "the reservation would pass the cap: no call")
        self.assertEqual(len(self.ledger()), 1)

    def test_the_art_director(self):
        from convention_social.agents import art_director

        class Broken(ArtClient):
            def create(self, **kw):
                self.calls += 1
                raise ConnectionError("api down")
        paths = []
        for n in range(2):
            paths.append(self.root / f"r{n}.jpg")
            paths[-1].write_bytes(jpeg_bytes(seed=n))
        told = content.BRIEFS["single"]
        self.assertEqual(art_director.look(self.conn, paths, brief=told, client=ArtClient([say("pass")]))["verdict"], "pass")
        self.settled(self.ledger(), "art review")
        self.assertIsNone(art_director.look(self.conn, paths, brief=told, client=Broken([])))
        self.assertEqual(len(self.ledger()), 1, "a call that failed holds nothing")
        self.spent(0.85)
        client = ArtClient([say("pass")])
        self.assertIsNone(art_director.look(self.conn, paths, brief=told, client=client))
        self.assertEqual(client.calls, 0, "the reservation would pass the cap: no call")
        self.assertEqual(len(self.ledger()), 1)


SUNDAY = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)         # tomorrow is Monday: spotlight
WEDNESDAY = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)      # tomorrow is Thursday: cascade (2026-10-15)
THURSDAY = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)       # tomorrow is Friday: select (2026-10-15)
SATURDAY = datetime(2026, 10, 17, 10, 0, tzinfo=timezone.utc)       # tomorrow is Sunday: poster (2026-10-15)


class NewDesigns(Content):
    """Chris, 2026-10-11: "Switch to new designs and it's ok to use 1 photo too sometimes." """

    def add_event_photo(self, did, event, q=3):
        now = db.utcnow()
        pid = db.insert(self.conn, "photos", drive_id=did, name=f"{did}.jpg", folder_id="fe", width=3000, height=2000,
                        first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name=event, is_convention=1,
                  quality=q, possible_minor=0, personal_details="[]", space="exterior", residential=0, empty_room=0, sharp=1,
                  light=4, moment=4, shot_type="portrait", classified_at=now)
        self.ids[did] = pid

    def last(self):
        row = self.queue()[-1]
        return row, json.loads(row["rule_report"]), json.loads(row["render_paths"]), json.loads(row["photo_ids"])

    def test_monday_is_the_spotlight_with_the_best_photo_first(self):
        line = content.draft_one(self.ctx(), self.fetch, now=SUNDAY)
        self.assertIn("spotlight with 3 photo(s)", line)
        _, meta_, renders, ids = self.last()
        self.assertEqual(meta_["design"], "spotlight")
        self.assertEqual(ids[0], self.ids["e1"])
        self.assertEqual(sorted(ids), sorted([self.ids["e1"], self.ids["e2"], self.ids["e3"]]))
        self.assertEqual(sorted(renders), ["2:3", "4:5"])
        with Image.open(renders["4:5"][0]) as im:
            self.assertEqual(im.size, (1080, 1350))
        self.assertEqual(meta.is_clean(Path(renders["4:5"][0])), [])

    def test_thursday_is_the_cascade_of_three_photos(self):
        """2026-10-15: Thursday was the carousel; the week is the four bold designs and the spotlight now."""
        self.add_event_photo("e4", "Awesome Con")
        content.draft_one(self.ctx(), self.fetch, now=WEDNESDAY)
        _, meta_, renders, ids = self.last()
        self.assertEqual(meta_["design"], "cascade")
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(renders["4:5"]), 1)

    def test_too_few_photos_for_the_select_is_a_one_photo_day_never_the_same_as_its_neighbours(self):
        line = content.draft_one(self.ctx(), self.fetch, now=THURSDAY)
        self.assertIn("select wanted but too few photos passed", line)
        _, meta_, renders, ids = self.last()
        self.assertEqual((meta_["design"], meta_["design_wanted"]), ("poster", "select"))   # Thursday cascade, Saturday reel
        self.assertEqual(ids, [self.ids["e1"]])
        self.assertEqual(sorted(renders), ["2:3", "4:5"])

    def test_every_design_has_a_pinterest_card(self):
        """2026-10-13: spotlight, carousel and fan rendered 4:5 only; Pinterest then fell back to the photo's own copy,
        a .img file the publisher refuses, and the whole post failed on every network once a board was set."""
        for did in ("e4", "e5"):
            self.add_event_photo(did, f"{did} Con")
        for now, design in ((SUNDAY, "spotlight"), (WEDNESDAY, "cascade"), (THURSDAY, "select")):
            self.conn.execute("DELETE FROM content_queue")                 # each design on the whole pool
            content.draft_one(self.ctx(), self.fetch, now=now)
            _, meta_, renders, _ = self.last()
            self.assertEqual(meta_["design"], design)
            self.assertEqual(len(renders.get("2:3") or []), 1, (design, renders))
            with Image.open(renders["2:3"][0]) as im:
                self.assertEqual(im.size, (1000, 1500), design)
            self.assertEqual(meta.is_clean(Path(renders["2:3"][0])), [])

    def test_sunday_is_the_poster(self):
        """The face match post is retired (Chris, 2026-10-11: a post never talks about a service); Sunday was a single
        photo until 2026-10-15 and is the poster now."""
        content.draft_one(self.ctx(), self.fetch, now=SATURDAY)
        _, meta_, renders, ids = self.last()
        self.assertEqual((meta_["design"], ids), ("poster", [self.ids["e1"]]))
        self.assertNotIn("facematch", content.DESIGNS.values())

    def test_live_every_photo_on_the_post_passes_the_final_check(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        self.add_event_photo("e4", "Awesome Con")
        client = FinalClient({"e2": True})
        orig = self.fetch

        def fetch(row):
            client.current = row["drive_id"]
            return orig(row)
        art = ArtClientAny([say("redo", notes="Tighten the left card.")])
        content.draft_one(self.ctx(dry=False), fetch, now=SUNDAY, check_client=client, art_client=art)
        _, meta_, _, ids = self.last()
        self.assertEqual(meta_["design"], "spotlight")
        self.assertNotIn(self.ids["e2"], ids)                              # a readable plate: never on the post
        self.assertEqual(len(ids), 3)
        from convention_social.library import eligibility
        self.assertTrue(all(eligibility.is_eligible(self.conn, i)[0] for i in ids))
        self.assertEqual((art.calls, meta_["art"]["verdict"]), (1, "pass"))  # several photos: no crop to redo


class ArtClientAny(ArtClient):
    def create(self, **kw):
        self.calls += 1
        a = self.answers.pop(0)
        t = types.SimpleNamespace(type="text", text=json.dumps(a))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=2500, output_tokens=150))
