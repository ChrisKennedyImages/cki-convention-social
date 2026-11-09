"""One Event Caliber brief that every AI step reads (Chris, 2026-11-08: "Maybe we need a chief that knows everything and
leave the art director to do its work?"; "Yes, build it."), his labels ("Candid, Backstage, Green room, Panels, Portraits,
Main stage, Breakouts, Awards, Event building, and Reception kept."), and his law ("NOTHING IS PRIVATE because I have hand
approved every photo! No one can override MY approvals and that is a law"; "Yes, override everything")."""
from __future__ import annotations

import json
import os
import re
import types
from datetime import date
from pathlib import Path

from PIL import Image

from convention_social import house_brief, reel_lines
from convention_social.agents import art_director, chief, content, publisher
from convention_social.ai import claude, reply
from convention_social.core import config, db
from convention_social.library import classify, eligibility
from convention_social.outreach import dates, research
from convention_social.render import design_samples, reel_looks, reels3d
from convention_social.seo import changes, photo_text
from tests._base import IsolatedCase
from tests._fakes import add_channels, add_post, make_ctx
from tests._photos import jpeg_bytes
from tests.test_wedding import event_photo

REPO = Path(__file__).resolve().parents[1]


class Recorder:
    """A Claude client that keeps every call it is given and answers `text`."""

    def __init__(self, text: str):
        self.text, self.calls = text, []
        self.beta = self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        block = types.SimpleNamespace(type="text", text=self.text, citations=None)
        return types.SimpleNamespace(content=[block], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=10, output_tokens=5, server_tool_use=None))


def first_block(call) -> str:
    system = call["system"]
    return system[0]["text"] if isinstance(system, list) else system


class EveryStepReadsTheBrief(IsolatedCase):
    """The brief is the first system block of every Claude call, built by each step's own code with a fake client."""

    def setUp(self):
        super().setUp()
        os.environ["AI_MONTHLY_CAP_USD"] = "50"
        config.reset()
        config.get_config().ensure_dirs()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.brief = house_brief.text()
        self.photo = self.root / "p.jpg"
        Image.new("RGB", (800, 600), (90, 80, 70)).save(self.photo)

    def told(self, rec: Recorder, task: str) -> None:
        self.assertTrue(rec.calls, "no call was made")
        for call in rec.calls:
            self.assertEqual(first_block(call), self.brief, "the brief first")
            self.assertIn(task, json.dumps(call["system"]), "then the step's own task")

    def test_the_sorter_the_local_sorter_and_the_final_check(self):
        rec = Recorder(json.dumps({"subject": "event"}))
        classify.ClaudeSorter(self.conn, client=rec).classify(jpeg_bytes(), "hint")
        self.told(rec, classify.SYSTEM[:60])
        self.assertEqual(rec.calls[0]["system"][-1]["cache_control"], {"type": "ephemeral"}, "cached where it was cached")
        sent = []

        def post(url, json=None):
            sent.append(json)
            return types.SimpleNamespace(status_code=200, json=lambda: {"message": {"content": ""}})
        classify.OllamaSorter("qwen2.5vl", post=post).classify(jpeg_bytes(), "hint")
        self.assertTrue(sent[0]["messages"][0]["content"].startswith(self.brief))
        self.assertTrue(sent[0]["messages"][0]["content"].endswith(classify.SYSTEM))
        rec = Recorder(json.dumps({**classify.NO_LABELS, "shot_type": "portrait", "room": "portrait"}))
        classify.look(self.conn, jpeg_bytes(), client=rec)
        self.told(rec, classify.FINAL_SYSTEM[:60])

    def test_the_art_director_and_its_photo_question(self):
        rec = Recorder(json.dumps({"pictures": ["ok"], "verdict": "pass", "focus_x": 0.5, "focus_y": 0.4, "notes": "Fine."}))
        art_director.look(self.conn, [self.photo], brief=reel_looks.brief("darkroom"), client=rec)
        self.told(rec, art_director.SYSTEM[:60])
        self.assertIn(reel_looks.ON_PURPOSE["darkroom"], rec.calls[0]["messages"][0]["content"][-1]["text"], "the look's brief too")
        rec = Recorder(json.dumps({"subject": "woman"}))
        art_director.subject_of(self.conn, self.photo, client=rec)
        self.told(rec, art_director.JUDGE_SYSTEM)

    def test_the_caption_writer_and_the_quote_reply(self):
        rec = Recorder(json.dumps({"photo_summary": "A stage.", "alt_text": "A speaker.",
                                   "captions": {n: "A speaker on stage." for n in claude.NETWORKS}}))
        claude.ClaudeDrafter(self.conn, client=rec).draft(claude.PostFacts(brand_name="Event Caliber"), self.photo)
        self.told(rec, claude.SYSTEM_PROMPT[:60])
        rec = Recorder(json.dumps({"subject": "Your event", "body": "Hi.\n\n" + reply.QUOTE_MARK + "\n\nChris"}))
        inquiry = {"name": "Ana Lee", "organization": "", "event_name": "Expo", "event_kind": "business", "start_date": "",
                   "end_date": "", "venue": "", "city": "", "attendance": "", "coverage": "[]", "message": ""}
        reply.draft(self.conn, inquiry, client=rec)
        self.told(rec, reply.SYSTEM[:60])

    def test_the_scout_its_structuring_and_the_dates_reader(self):
        rec = Recorder("Notes with no block in them.")
        research.research(self.conn, rec, region="Washington DC", today=date(2026, 11, 8), earliest=date(2027, 2, 8),
                          horizon=date(2027, 11, 8), known=[])
        self.assertEqual(len(rec.calls), 2, "the research and, its answer unreadable, the structuring")
        self.assertEqual([first_block(c) for c in rec.calls], [self.brief, self.brief])
        self.assertIn(research.SYSTEM[:60], json.dumps(rec.calls[0]["system"]))
        self.assertIn(research.STRUCTURE_SYSTEM[:60], json.dumps(rec.calls[1]["system"]))
        rec = Recorder(json.dumps({"start_date": "", "end_date": "", "quote": ""}))
        dates.Reader(self.conn, client=rec).read("A page.", "https://example.org", date(2026, 11, 8))
        self.told(rec, dates.SYSTEM[:60])

    def test_the_sites_photo_text_the_search_writers_and_the_morning_read(self):
        rec = Recorder(json.dumps({"title": "t", "alt": "a", "description": "d", "keywords": []}))
        facts = photo_text.PhotoFacts(photo_id=1, subject="event", shot_type="portrait", event_name="", event_kind="business",
                                      year="", city="", view="", summary="", handles=(), brand="Event Caliber")
        photo_text.ClaudeWriter(self.conn, client=rec, model="claude-opus-5").write(facts)
        self.told(rec, photo_text.SYSTEM[:60])
        from convention_social.seo import leads, pages, titles
        for writer in (pages, titles, leads):
            rec = Recorder(json.dumps({"lead": "x"}))
            changes.ask(self.conn, rec, model="claude-opus-5", system=writer.SYSTEM, schema=writer.SCHEMA, facts={},
                        detail="t", agent="seo")
            self.told(rec, writer.SYSTEM[:60])
            self.assertNotIn("two brothers who photograph", writer.SYSTEM, "the brief says who the company is, once")
        rec = Recorder(json.dumps({"read": "Nothing needs you."}))
        chief.written_read(self.conn, {"needs": [], "done": [], "watching": []}, client=rec)
        self.told(rec, chief.READ_SYSTEM)

    def test_no_claude_call_in_the_suite_skips_the_brief(self):
        """A new AI step must read the brief: every module that calls Claude or the local sorter builds its system with
        house_brief, and no system is written by hand any more."""
        missing, by_hand = [], []
        for path in sorted((REPO / "convention_social").rglob("*.py")):
            text = path.read_text()
            if "messages.create(" in text or "/api/chat" in text:
                if "house_brief." not in text or not re.search(r"^from \.\. import .*\bhouse_brief\b", text, re.M):
                    missing.append(str(path.relative_to(REPO)))
                by_hand += [f"{path.relative_to(REPO)}: {m.group(0)}" for m in re.finditer(r'system=\[\{"type": "text"', text)]
        self.assertEqual(missing, [])
        self.assertEqual(by_hand, [])

    def test_the_drifted_company_notes_are_gone(self):
        self.assertNotIn("The company photographs business", claude.SYSTEM_PROMPT)
        self.assertNotIn("one-person", chief.READ_SYSTEM)
        self.assertNotIn("photography company", art_director.SYSTEM + art_director.JUDGE_SYSTEM)
        portrait = claude.user_text(claude.PostFacts(brand_name="Event Caliber", shot_type="portrait"))
        self.assertIn("made as the brief says", portrait)
        self.assertNotIn("color gels", portrait, "how portraits are made is said once, in the brief")


class TheBrief(IsolatedCase):
    def test_it_says_what_the_company_photographs_in_his_words(self):
        text = house_brief.text()
        for words in ("Chris Kennedy and his brother Nic Kennedy", "conferences, conventions and trade shows",
                      "galas, receptions and award dinners", "DC, Maryland and Virginia and nationwide",
                      "we provide portraits at many of our events for LinkedIn profiles or backstage for speakers or many reasons",
                      "for the speakers and the people the event is about", "lit on site with our own lights and color gels",
                      "charity walks and runs, fundraisers, heart walks and Alzheimer's walks", "a great heart walk photo",
                      "No one can override MY approvals and that is a law", "Yes, override everything",
                      "never rule an approved photo unfit", "NOTHING INCLUDES ANYTHING",
                      "CPAC, the American Conservative Union (ACU) and their affiliates are never contacted"):
            self.assertIn(words, text, words)
        for never in ("cosplay", "fan convention", "political", "under 18", "brothers, more than thirty", "$"):
            self.assertNotIn(never, text.lower() if never.islower() else text, never)

    def test_it_takes_the_name_as_it_is_set(self):
        os.environ["BRAND_NAME"] = "Other Name"
        config.reset()
        self.assertTrue(house_brief.text().startswith("Other Name is the event photography company"))


class Headshots(IsolatedCase):
    """A studio or backstage portrait is the company's work: business, never private for being a portrait."""

    def test_both_prompts_say_so_and_private_keeps_only_his_meaning(self):
        for prompt in (classify.SYSTEM, classify.FINAL_SYSTEM):
            self.assertIn(classify.KIND_RULE, prompt)
        for words in ("a studio or backstage portrait or headshot", "lit for it on a backdrop, often with colored gels",
                      "is business unless the photo itself shows a wedding, never private for being a portrait",
                      "private for a family or personal occasion", "a private party or a religious ceremony",
                      "a nonprofit's public event (a charity walk or run, a fundraiser, a heart walk or an Alzheimer's walk)"):
            self.assertIn(words, classify.KIND_RULE, words)
        self.assertNotIn("portrait session with no event around it", classify.SYSTEM + classify.FINAL_SYSTEM)

    def test_a_portrait_the_final_check_calls_business_is_eligible(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        pid = event_photo(conn, "head1", kind="private")
        conn.execute("UPDATE classifications SET shot_type='portrait' WHERE photo_id=?", (pid,))
        rec = Recorder(json.dumps({**classify.NO_LABELS, "shot_type": "portrait", "event_kind": "business", "room": "portrait",
                                   "summary": "A studio headshot against a blue backdrop."}))
        classify.final_check(conn, pid, jpeg_bytes(), client=rec)
        cls = db.one(conn, "SELECT event_kind, is_convention, shot_type FROM classifications WHERE photo_id=?", (pid,))
        self.assertEqual((cls["event_kind"], cls["is_convention"], cls["shot_type"]), ("business", 1, "portrait"))
        self.assertEqual(eligibility.is_eligible(conn, pid), (True, "ok"))


class Darkroom(IsolatedCase):
    def test_the_art_director_is_told_the_white_first_cell_is_the_fogged_leader(self):
        told = reel_looks.brief("darkroom")
        for words in ("The first frame, top left, is the roll's fogged leader", "empty on purpose", "eleven different pictures",
                      "a dark or narrow photo makes a dark frame", "The fogged leader, the film's black",
                      "three different photos on purpose, since no picture is shown twice in the reel"):
            self.assertIn(words, told, words)
        self.assertNotIn("repeated", told, "no picture twice on the sheet (2026-11-08, night)")

    def test_every_look_names_what_it_puts_on_the_frame_on_purpose(self):
        named = {"section": ("drawn empty", "skewed flat as plates in an axonometric drawing",
                             "the first word's room stays drawn empty on purpose", "its word names that photo"),
                 "titles": ("ragged, hand cut bars",), "weather": ("rain streaks crossing them",),
                 "chiaroscuro": ("darkness", "warm grade", "close detail of the hero"),
                 "axis": ("black and white until the climax",), "stillness": ("with no photo",)}
        for look, words in named.items():
            for w in words:
                self.assertIn(w, reel_looks.ON_PURPOSE[look], (look, w))
        for look in reel_looks.LOOKS:
            told = reel_looks.brief(look)
            self.assertIn("No approved photo is a fault in itself", told, look)
            self.assertNotIn("soft or dark in the photo itself", told, look)
        for style in reels3d.STYLES:
            self.assertIn("never a fault in itself", reels3d.brief(style), style)


class TheArtDirectorJudgesTheDesign(IsolatedCase):
    def test_its_prompt_says_it_never_rules_an_approved_photo_unfit(self):
        for words in ("Every photo in the post is one Chris approved by hand, and his approval is final",
                      "you never rule an approved photo unfit",
                      "never turn a post back because of a photo itself, its darkness, black and white",
                      "or for a frame the design leaves empty or white on purpose", "Never \"reject\" for a photo itself.",
                      "does each word on the post name what its own photo plainly shows"):
            self.assertIn(words, art_director.SYSTEM, words)
        self.assertNotIn("Quality: is the photo sharp", art_director.SYSTEM)
        self.assertIn("never rule an approved photo unfit", house_brief.text())


class HisLabels(IsolatedCase):
    def test_the_list_is_his_in_his_order(self):
        self.assertEqual([label.word for label in house_brief.LABELS],
                         ["Candid", "Backstage", "Green room", "Panels", "Portraits", "Main stage", "Breakouts", "Awards",
                          "Event building", "Reception"])
        self.assertEqual(classify.SHOT_TYPES, house_brief.KEYS)
        self.assertEqual(classify.ROOMS, house_brief.KEYS, "Event building is a room a post may name")
        self.assertEqual(classify.FINAL_SCHEMA["properties"]["room"]["enum"], [*house_brief.KEYS, "none"])
        text = house_brief.text()
        self.assertIn('- awards ("Awards"): an award being presented or received', text)
        self.assertIn("Awards wins over portrait and main_stage", text)
        self.assertIn('- green_room ("Green room"): speakers or guests of honor waiting or relaxing', text)
        self.assertNotIn("a group standing for an award", text)
        self.assertIn("a posed group off the stage with no award in hand. A posed group on a stage is main_stage, and with an "
                      "award in hand it is awards.", text)
        self.assertIn('- candid ("Candid"): anything else at the event: the exhibition hall, its booths and the people at them',
                      text)

    def test_an_award_photos_room_prints_awards(self):
        self.assertEqual(reel_lines.beats(["awards", "main_stage", "breakout"]).words, ("Awards.", "Main stage.", "Breakouts."))
        self.assertEqual(design_samples.ROOMS["awards"][0], "AWARDS")
        conn = db.connect()
        self.addCleanup(conn.close)
        pid = event_photo(conn, "plaque", kind="business")
        db.insert(conn, "final_checks", photo_id=pid, possible_minor=0, model="m",
                  checked_at=db.utcnow(), shot_type="awards", room="awards")
        self.assertEqual(content.confirmed_rooms(conn, [pid])[pid][0], "AWARDS")

    def test_a_stack_label_says_portraits_only_where_a_photos_room_is_portrait(self):
        # draft 87: an award plaque came out "Portrait." under "PORTRAITS · SESSIONS · STAGE"
        self.assertEqual(reel_lines.beats(["awards", "breakout", "main_stage"]).stack, "Awards · breakouts · main stage")
        axis = reel_lines.beats(["awards", None, "main_stage", "portrait", None], "axis")
        self.assertEqual(axis.stack, "Awards · main stage", "a photo with no confirmed room is no portrait")
        self.assertEqual(reel_lines.beats([None, "portrait", None, None, None], "axis").stack, "Portraits")
        with self.assertRaises(reel_lines.TooFewRooms):
            reel_lines.beats([None] * 5, "axis")
        for rooms in (["awards", "breakout", "main_stage"], ["main_stage", "candid", "reception", "awards"]):
            self.assertNotIn("portrait", reel_lines.beats(rooms).stack.lower())

    def test_two_keys_of_one_word_never_make_the_same_word_twice(self):
        b = reel_lines.beats(["building_exterior", "building_interior", "reception", "candid"])
        self.assertEqual(b.words, ("Event building.", "Reception.", "Candid."))

    def test_every_printed_room_word_comes_from_the_one_list(self):
        words = {label.word for label in house_brief.LABELS}
        self.assertEqual(set(reel_lines.BEAT_WORDS.values()), {f"{w}." for w in words})
        self.assertEqual(set(reel_lines.STACK_WORDS.values()), {w.lower() for w in words})
        self.assertEqual({t for t, _ in design_samples.ROOMS.values()}, {w.upper() for w in words})
        from convention_social.dashboard import app as dash
        self.assertEqual({w.split(",")[0] for _, w in dash.SHOT_CHOICES}, words)
        from convention_social.site import build
        for key in house_brief.KEYS:
            self.assertIn(build.site_label({"subject": "event", "shot_type": key, "people_count": 1}), words)
        self.assertEqual(build.site_label({"subject": "architecture", "shot_type": "building_interior"}), "Event building")
        root = (REPO / "reel-looks" / "src" / "Root.tsx").read_text()
        for printed in re.findall(r'words: \[([^\]]*)\]', root)[0].split(","):
            self.assertIn(printed.strip().strip('"'), reel_lines.BEAT_WORDS.values())
        old = re.compile(r'"(?:Stage|Panel|Session|Portrait)\."|"STAGE PANEL"|"THE VENUE"|"ON THE FLOOR"|Portraits · headshots')
        hits = [f"{p.relative_to(REPO)}" for p in sorted((REPO / "convention_social").rglob("*.py")) if old.search(p.read_text())]
        self.assertEqual(hits, [], "an old room word still prints")

    def test_portraits_prints_only_over_one_person(self):
        """Chris, 2026-11-09, after draft #90 printed "Portraits." over a posed group of eight women (photo 52831): the word
        prints only over a photo with exactly one person in it, and "There can't be a 'none' label." Which of his other
        labels a pair or a group takes waits for the re-judge, so until then nothing prints Portraits over one: a post's
        title, a reel's beat words (it is never a word photo) and its stack label, the design samples, the site's caption."""
        from convention_social.site import build
        conn = db.connect()
        self.addCleanup(conn.close)
        ids = {}
        for did, people in (("one", 1), ("pair", 2), ("eight", 8), ("nobody", 0), ("uncounted", None)):
            ids[did] = event_photo(conn, did, kind="business")
            conn.execute("UPDATE classifications SET shot_type='portrait', people_count=? WHERE photo_id=?", (people, ids[did]))
            conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (ids[did],))
            db.insert(conn, "final_checks", photo_id=ids[did], possible_minor=0, model="m", checked_at=db.utcnow(),
                      shot_type="portrait", room="portrait")
        everyone = list(ids.values())
        rooms, words = content.checked_rooms(conn, everyone), content.confirmed_rooms(conn, everyone)
        self.assertEqual({d: rooms[p] for d, p in ids.items()},
                         {"one": "portrait", "pair": None, "eight": None, "nobody": None, "uncounted": None})
        self.assertEqual([d for d, p in ids.items() if words[p][0] == "PORTRAITS"], ["one"], "a post's title")
        reel = [rooms[ids[d]] for d in ("eight", "pair", "one", "nobody", "uncounted")] + ["main_stage", "reception"]
        beats = reel_lines.beats(reel)
        self.assertEqual((beats.photos, beats.words), ((2, 5, 6), ("Portraits.", "Main stage.", "Reception.")),
                         "the word Portraits on the one-person portrait; a group is never a word photo")
        self.assertEqual(reel_lines.beats(reel[:2] + reel[3:5] + ["main_stage"], "axis").stack, "Main stage",
                         "Axis's stack label names no group")
        self.assertEqual([r["id"] for r in design_samples.pick(conn, 400)], [ids["one"]], "the design samples")
        labels = {r["id"]: build.words_for(conn, r)[3] for r in build.page_pool(conn)}
        self.assertEqual({d: labels[p] for d, p in ids.items()},
                         {"one": "Portraits", "pair": "Event photography", "eight": "Event photography",
                          "nobody": "Event photography", "uncounted": "Event photography"}, "the site's caption")

    def test_the_learner_starts_the_new_labels_at_one(self):
        from convention_social.agents import learner
        conn = db.connect()
        self.addCleanup(conn.close)
        self.assertEqual(learner.weight_for(conn, "awards", "business"), 1.0)
        self.assertEqual(learner.weight_for(conn, "green_room", "business"), 1.0)
        self.assertEqual(learner.kind_words("shot_type", "stage_panel"), "Panels photos")


class HisApprovalIsFinal(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def test_a_used_photo_labelled_private_or_a_wedding_is_a_candidate_for_a_draft_and_a_reel(self):
        private = event_photo(self.conn, "walk", kind="private", final="private")
        wedding = event_photo(self.conn, "wed", kind="wedding", final="wedding")
        for pid in (private, wedding):
            self.assertEqual(eligibility.is_candidate(self.conn, pid), (True, "ok"))
            self.assertEqual(eligibility.is_eligible(self.conn, pid), (True, "ok"))
        pool = content.candidates(self.conn, "event")
        self.assertEqual({r["id"] for r in pool}, {private, wedding}, "the daily draft's pool, which every reel is picked from")
        picker = content.Picker(pool, "reel", style="darkroom")
        self.assertEqual({r["id"] for r in picker.candidates()}, {private, wedding}, "and a reel in a look takes them")
        for pid in (private, wedding):
            self.assertTrue(design_samples.usable(self.conn, dict(db.one(self.conn, "SELECT p.*, c.event_kind FROM photos p "
                                                                                 "JOIN classifications c ON c.photo_id = p.id WHERE p.id=?", (pid,)))))

    def test_a_used_photo_flagged_for_age_details_a_costume_or_a_building_rule_is_still_a_candidate(self):
        pid = event_photo(self.conn, "flag", kind="business", final="business")
        self.conn.execute("UPDATE classifications SET possible_minor=1, personal_details=?, costume=1 WHERE photo_id=?",
                          (json.dumps(["badge_name", "vehicle_plate", "house_number"]), pid))
        self.conn.execute("UPDATE final_checks SET possible_minor=1 WHERE photo_id=?", (pid,))
        self.assertEqual(eligibility.is_eligible(self.conn, pid), (True, "ok"))
        home = event_photo(self.conn, "home", kind="unknown", final="unknown")
        self.conn.execute("UPDATE classifications SET subject='architecture', residential=1, empty_room=1, space='bathroom' "
                          "WHERE photo_id=?", (home,))
        self.assertEqual(eligibility.is_eligible(self.conn, home), (True, "ok"))

    def test_what_keeps_a_photo_out_is_his_alone(self):
        pid = event_photo(self.conn, "his", kind="business", final="business")
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (pid,))
        self.assertEqual(eligibility.is_eligible(self.conn, pid), (False, "Chris marked it Never use"))
        undecided = event_photo(self.conn, "undecided", kind="business", final="business")
        self.conn.execute("UPDATE photos SET clearance='inherit' WHERE id=?", (undecided,))
        self.assertEqual(eligibility.is_eligible(self.conn, undecided), (False, "not cleared yet"))

    def test_a_refusal_is_a_check_with_no_labels_never_a_veto(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        pid = event_photo(self.conn, "refused", kind="business")

        class Refuses(Recorder):
            def create(self, **kw):
                out = super().create(**kw)
                out.stop_reason, out.content = "refusal", []
                return out
        data = classify.final_check(self.conn, pid, jpeg_bytes(), client=Refuses(""))
        self.assertEqual((data["room"], data["event_kind"]), ("none", "unknown"))
        self.assertEqual(db.one(self.conn, "SELECT room FROM final_checks WHERE photo_id=?", (pid,))["room"], None)
        self.assertEqual(eligibility.is_eligible(self.conn, pid), (True, "ok"))

    def test_a_used_photo_with_a_prominent_logo_still_goes_to_linkedin(self):
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        add_channels(self.conn, "instagram", "linkedin")
        pid = event_photo(self.conn, "logo", kind="business", final="business")
        qid = add_post(self.conn, [pid], targets=("instagram", "linkedin"))
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        active, skipped, held = publisher.usable_networks(make_ctx(self.conn), row)
        self.assertEqual((set(active), skipped, held), ({"instagram", "linkedin"}, {}, {}))
        self.assertFalse(hasattr(art_director, "prominent_logo"))
        self.assertFalse(hasattr(publisher, "linkedin_hold"))

    def test_to_review_still_offers_him_only_the_work(self):
        from convention_social.dashboard import app as dash
        wedding = event_photo(self.conn, "w-undecided", kind="wedding")
        self.conn.execute("UPDATE photos SET clearance='inherit', clearance_at=NULL WHERE id=?", (wedding,))
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        self.assertEqual(dash.count_photos(self.conn, "review"), 0, "a photo he has not decided on: offered only as before")


class Relabel(IsolatedCase):
    def test_it_finds_the_award_and_green_room_photos_counts_the_cost_and_marks_only_when_asked(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        plaque = event_photo(conn, "plaque", kind="business")
        conn.execute("UPDATE classifications SET shot_type='portrait', summary='Four people hold an award plaque.' WHERE photo_id=?",
                     (plaque,))
        lounge = event_photo(conn, "lounge", kind="business", final="business")
        conn.execute("UPDATE final_checks SET summary='Speakers wait in the green room.' WHERE photo_id=?", (lounge,))
        his = event_photo(conn, "his", kind="business")
        conn.execute("UPDATE classifications SET summary='A trophy on stage.', shot_by='chris' WHERE photo_id=?", (his,))
        plain = event_photo(conn, "plain", kind="business")
        conn.execute("UPDATE classifications SET summary='A speaker at a podium.' WHERE photo_id=?", (plain,))
        conn.execute("UPDATE photos SET thumbnail_link='https://drive.example/t'")
        db.insert(conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent="scanner", units=100, unit_kind="tokens",
                  cost_usd=0.005, detail="claude-opus-5 in=900 out=100 classify")
        found = classify.relabel(conn)
        self.assertEqual(sorted(found.ids), sorted([plaque, lounge]), "his own label is never touched")
        self.assertEqual((found.by_label, found.checked), ({"portrait": 1, "stage_panel": 1}, 1))
        self.assertEqual((found.per_photo_usd, found.usd, found.undercounts, found.marked), (0.005, 0.01, True, False),
                         "a row from before the till counted the cached prompt: said to under-count")
        db.insert(conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent="scanner", units=100, unit_kind="tokens",
                  cost_usd=0.007, detail="claude-opus-5 in=500 out=90 cache_read=3000 cache_write=0 classify")
        found = classify.relabel(conn)
        self.assertEqual((found.per_photo_usd, found.undercounts), (0.007, False), "rows that count it, when there are any")
        self.assertEqual(db.one(conn, "SELECT SUM(rejudge) s FROM classifications")["s"], 0, "nothing marked without --mark")
        classify.relabel(conn, mark=True)
        marked = {r["photo_id"] for r in db.rows(conn, "SELECT photo_id FROM classifications WHERE rejudge=1")}
        self.assertEqual(marked, {plaque, lounge})
        check = db.one(conn, "SELECT shot_type, room FROM final_checks WHERE photo_id=?", (lounge,))
        self.assertIsNotNone(check, "the check is kept: a draft already holding the photo stays approvable")
        self.assertEqual((check["shot_type"], check["room"]), (None, None),
                         "its label cleared: the full photo is labelled again, never the thumbnail's word over it")
        self.assertTrue(eligibility.is_eligible(conn, lounge)[0], "still eligible after --mark")
        self.assertIn(plaque, [r["id"] for r in classify.queue(conn, 10)], "the sorter's queue takes them")


class ATurnBackIsNotAUse(IsolatedCase):
    """2026-11-08, his approval is final: a draft the art director turned back aired nothing, so its photos are free for the
    next draft at once, as a skipped one's are (2026-10-15); his own set-asides still sit out."""

    def test_an_art_director_reject_releases_its_photos_to_the_next_draft(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        pid = event_photo(conn, "back", kind="business", final="business")
        now = db.utcnow()
        db.insert(conn, "content_queue", kind="photo", photo_ids=json.dumps([pid]), targets=json.dumps(["instagram"]),
                  caption="{}", status="rejected", last_error="Art director: too dark",
                  rule_report=json.dumps({"for_day": "turned back", "art": {"verdict": "reject", "notes": "too dark"}}),
                  created_at=now, updated_at=now)
        self.assertEqual(content.recent_use(conn, 180)[0], set())
        self.assertIsNone(content.photo_holder(conn, [pid], 180))
        self.assertEqual([r["id"] for r in content.candidates(conn, "event")], [pid], "free for the next draft")
        set_aside = event_photo(conn, "aside", kind="business", final="business")
        db.insert(conn, "content_queue", kind="photo", photo_ids=json.dumps([set_aside]), targets=json.dumps(["instagram"]),
                  caption="{}", status="rejected", rule_report=json.dumps({"rejected_by": "do_not_use"}), created_at=now,
                  updated_at=now)
        self.assertIn(set_aside, content.recent_use(conn, 180)[0], "his own set-aside still sits out")


class OtherIsEventWork(IsolatedCase):
    """2026-11-08: 24 photos he used were "other" to the sorter, a studio headshot among them, and no pool reached them."""

    def test_a_used_headshot_the_sorter_called_other_is_a_draft_candidate_and_on_the_site(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        pid = event_photo(conn, "head", kind="business", final="business")
        conn.execute("UPDATE classifications SET subject='other', shot_type='portrait' WHERE photo_id=?", (pid,))
        self.assertEqual(eligibility.work_of("other"), "event")
        self.assertEqual([r["id"] for r in content.candidates(conn, "event")], [pid])
        from convention_social.site import build
        self.assertEqual([r["id"] for r in build.page_pool(conn)], [pid])
        from convention_social.dashboard import app as dash
        self.assertIs(dash.SUBJECTS, eligibility.WORK, "one rule, one place")
        self.assertIn("for every posed portrait or headshot", classify.SYSTEM)


class TheTillCountsTheCache(IsolatedCase):
    def test_cached_tokens_are_recorded_and_priced(self):
        from convention_social.ai import spend
        conn = db.connect()
        self.addCleanup(conn.close)
        usage = types.SimpleNamespace(input_tokens=1000, output_tokens=100, cache_read_input_tokens=2000,
                                      cache_creation_input_tokens=400,
                                      cache_creation=types.SimpleNamespace(ephemeral_5m_input_tokens=300,
                                                                           ephemeral_1h_input_tokens=100))
        answered, cost = spend.record_response(conn, "content", types.SimpleNamespace(usage=usage, model="claude-opus-5"),
                                               "claude-opus-5", "final check")
        # $5 a million in, $25 out; a read is a tenth of the input rate, a 5-minute write 1.25 times it, a 1-hour one twice
        want = (1000 + 2000 * 0.1 + 300 * 1.25 + 100 * 2.0) / 1e6 * 5 + 100 / 1e6 * 25
        self.assertEqual((answered, cost), ("claude-opus-5", round(want, 6)))
        row = db.one(conn, "SELECT units, cost_usd, detail FROM api_usage")
        self.assertEqual((row["units"], row["cost_usd"]), (3500, round(want, 6)))
        self.assertIn("cache_read=2000 cache_write=400", row["detail"])
        self.assertEqual(spend.cost_usd("claude-opus-5-5", 0, 0, cache_read=1_000_000), 0.2, "a twentieth on Opus 5.5")

    def test_each_fallback_attempt_is_its_own_row_at_its_own_model(self):
        """The response of platform.claude.com's "Refusals and fallback" example: Fable 5 declines, Opus 4.8 answers. The
        attempts are the bill (usage.iterations); the top-level counts are only the answer, never added to them."""
        from convention_social.ai import spend
        conn = db.connect()
        self.addCleanup(conn.close)
        attempt = lambda model, kind, i, o: {"type": kind, "model": model, "input_tokens": i, "output_tokens": o,  # noqa: E731
                                             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
        response = {"model": "claude-opus-4-8", "usage": {
            "input_tokens": 412, "output_tokens": 264, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
            "iterations": [attempt("claude-fable-5", "message", 535, 0), attempt("claude-opus-4-8", "fallback_message", 412, 264)]}}
        answered, cost = spend.record_response(conn, "content", response, "claude-fable-5", "caption")
        fable, opus = 535 / 1e6 * 10, 412 / 1e6 * 5 + 264 / 1e6 * 25
        self.assertEqual((answered, cost), ("claude-opus-4-8", round(fable + opus, 6)))
        rows = db.rows(conn, "SELECT cost_usd, detail FROM api_usage ORDER BY id")
        self.assertEqual([r["cost_usd"] for r in rows], [round(fable, 6), round(opus, 6)])
        self.assertTrue(rows[0]["detail"].startswith("claude-fable-5 in=535 out=0 attempt 1 of 2"), rows[0]["detail"])

    def test_every_call_site_records_through_the_one_helper_and_the_final_check_is_cached(self):
        hand = [f"{p.relative_to(REPO)}" for p in sorted((REPO / "convention_social").rglob("*.py"))
                if "spend.record(" in p.read_text()]
        self.assertEqual(hand, [], "no caller does its own arithmetic")
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        conn = db.connect()
        self.addCleanup(conn.close)
        rec = Recorder(json.dumps({**classify.NO_LABELS, "shot_type": "portrait", "room": "portrait"}))
        classify.look(conn, jpeg_bytes(), client=rec)
        self.assertEqual(rec.calls[0]["system"][-1].get("cache_control"), {"type": "ephemeral"})
        self.assertNotIn("costume", classify.FINAL_SCHEMA["properties"], "nothing reads it")
        columns = [c[1] for c in conn.execute("PRAGMA table_info(final_checks)")]
        self.assertNotIn("personal_details", columns)
        self.assertNotIn("event_kind", columns)


class TheHeroAfterARefusal(IsolatedCase):
    def test_a_refusal_keeps_nothing_so_the_next_build_asks_again(self):
        from convention_social.site import hero
        conn = db.connect()
        self.addCleanup(conn.close)
        hero.save(jpeg_bytes(size=(1600, 1000)))
        ok, note = hero.checked(conn, lambda data: {**classify.NO_LABELS, "refused": True})
        self.assertEqual((ok, note), (True, "your photo; Claude has not looked at it yet"))
        self.assertIsNone(hero.record(conn), "nothing kept against the file")
