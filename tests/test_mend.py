"""Chris, 2026-10-12: "the captions should auto correct themselves with the warnings they gave me before
approval. I don't want to change any captions." A queued draft whose captions break a rule now is rewritten by
the suite: by the content agent on every run, by the draft page the moment he opens it, and by Approve before
it would ever refuse."""
from __future__ import annotations

import json
from pathlib import Path
import os
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import content
from convention_social.ai import claude, copy_rules
from convention_social.core import auth, config, db, runner
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

BROKEN = "Conference photography includes portraits like this one, shot on site in a few minutes. Request a quote for your event."
CLEAN = "Conference photography: a speaker on the main stage. Event Caliber, event photographer. Request a quote at eventcaliber.com/book."


class Writer:
    """A caption writer that answers what it is told to, counting the calls and keeping the notes it was given."""
    model = "claude-test"

    def __init__(self, answers):
        self.answers, self.calls, self.notes = list(answers), 0, []

    def draft(self, facts, photo, notes=()):
        self.calls += 1
        self.notes.append(list(notes))
        text = self.answers.pop(0) if self.answers else CLEAN
        return claude.Draft(captions={"instagram": text, "facebook": text, "pinterest": text}, photo_summary="x",
                            model=self.model, alt_text="A speaker on the main stage")


class Mend(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        os.environ["BRAND_DOMAIN"] = "eventcaliber.com"
        config.reset()
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="fe", name="Con", clearance="cleared", first_seen_at=now, last_seen_at=now)
        self.pid = db.insert(self.conn, "photos", drive_id="e1", name="e1.jpg", folder_id="fe", width=3000, height=2000,
                             taken_at="2025:02:14 10:00:00", first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=self.pid, method="ollama", subject="event", convention_name="Liberty Summit",
                  event_kind="business", shot_type="stage_panel", is_convention=1, quality=5, possible_minor=0, personal_details="[]",
                  classified_at=now)
        db.insert(self.conn, "final_checks", photo_id=self.pid, possible_minor=0, personal_details="[]", model="m", checked_at=now,
                  shot_type="stage_panel", event_kind="business")

    def draft(self, caption=BROKEN, status="draft", **meta):
        now = db.utcnow()
        return db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps([self.pid]), targets=json.dumps(["instagram", "facebook", "pinterest"]),
                         caption=json.dumps({"instagram": caption, "facebook": caption, "pinterest": caption}), status=status,
                         rule_report=json.dumps({"for_day": "2026-10-12", "subject": "event", "design": "single", "seo": {"primary": "conference photography"}, **meta}),
                         created_at=now, updated_at=now)

    def row(self, qid):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))

    def test_a_draft_that_breaks_a_rule_now_is_rewritten_with_the_rules_words_and_a_clean_one_is_left_alone(self):
        qid = self.draft()
        clean = self.draft(caption=CLEAN)
        self.assertFalse(copy_rules.check(BROKEN, social=True).ok)
        writer = Writer([CLEAN])
        mend = content.mend_captions(self.conn, self.row(qid), drafter=writer)
        self.assertEqual(writer.calls, 1)
        self.assertEqual(mend["by"], "claude-test")
        self.assertIn("instagram", mend["fixed"])
        self.assertTrue(any("include" in why or "offer" in why or "service" in why for why in mend["fixed"]["instagram"]), mend["fixed"])
        self.assertEqual(mend["was"]["instagram"], BROKEN)
        row = self.row(qid)
        captions = json.loads(row["caption"])
        for n, text in captions.items():
            self.assertTrue(copy_rules.check(text, social=True).ok, (n, text))
            self.assertNotIn("includes", text)
        meta = json.loads(row["rule_report"])
        self.assertTrue(all(r["ok"] for r in meta["rules"].values()))
        self.assertEqual(meta["mended"][0]["by"], "claude-test")
        self.assertEqual(meta["for_day"], "2026-10-12", "the rest of the record is kept")
        self.assertIsNone(content.mend_captions(self.conn, self.row(qid), drafter=writer), "mended once, it passes")
        self.assertIsNone(content.mend_captions(self.conn, self.row(clean), drafter=writer))
        self.assertEqual(writer.calls, 1, "a passing draft costs nothing")
        self.assertEqual(json.loads(self.row(clean)["caption"])["instagram"], CLEAN)

    def test_the_writer_is_told_what_it_missed_and_the_template_stands_in_after_two_misses(self):
        qid = self.draft()
        writer = Writer([BROKEN, BROKEN])
        mend = content.mend_captions(self.conn, self.row(qid), drafter=writer)
        self.assertEqual(writer.calls, 2)
        self.assertTrue(writer.notes[1], "the second try carries the misses")
        self.assertEqual(mend["by"], "template")
        captions = json.loads(self.row(qid)["caption"])
        self.assertTrue(all(copy_rules.check(t, social=True).ok for t in captions.values()))
        self.assertIn("Conference photography", captions["instagram"])

    def test_a_writer_that_cannot_write_leaves_the_template_not_the_broken_caption(self):
        qid = self.draft()

        class Capped:
            model = "claude-test"

            def draft(self, facts, photo, notes=()):
                raise claude.SpendCapReached("monthly AI spend cap reached; no caption drafted")
        mend = content.mend_captions(self.conn, self.row(qid), drafter=Capped())
        self.assertEqual(mend["by"], "template")
        meta = json.loads(self.row(qid)["rule_report"])
        self.assertIn("SpendCapReached", meta["seo"]["writer_error"])
        self.assertTrue(all(r["ok"] for r in meta["rules"].values()))

    def test_without_a_copy_of_the_photo_the_template_writes_and_nothing_is_spent(self):
        qid = self.draft()
        with mock.patch("convention_social.ai.claude.get_drafter") as get:
            mend = content.mend_captions(self.conn, self.row(qid))
        self.assertEqual(get.call_count, 0, "the writer looks at the photo; there is no copy here")
        self.assertEqual(mend["by"], "template")

    def test_mend_queue_takes_every_open_draft_and_leaves_posted_ones(self):
        a, b = self.draft(), self.draft()
        done = self.draft(status="published")
        self.assertEqual(content.mend_queue(self.conn, drafter=Writer([CLEAN, CLEAN])), 2)
        self.assertEqual(json.loads(self.row(done)["caption"])["instagram"], BROKEN, "what went out is history")
        self.assertEqual(content.mend_queue(self.conn, drafter=Writer([])), 0)

    def test_the_content_agent_mends_before_it_drafts(self):
        self.draft()
        config.get_config().ensure_dirs()
        ctx = runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), False, 0)
        with mock.patch("convention_social.agents.content.draft_one", return_value="drafted post #9"), \
             mock.patch("convention_social.ai.claude.get_drafter", return_value=Writer([CLEAN])):
            line = content.run(ctx, fetch=lambda row: jpeg_bytes())
        self.assertEqual(line, "rewrote the captions of 1 queued draft(s) that broke a rule; drafted post #9")
        with mock.patch("convention_social.agents.content.draft_one", return_value="drafted post #10"):
            self.assertEqual(content.run(ctx, fetch=lambda row: jpeg_bytes()), "drafted post #10")


class OnTheDraftPage(Mend):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_opening_a_draft_mends_it_and_says_so(self):
        qid = self.draft()
        with mock.patch("convention_social.ai.claude.get_drafter", return_value=Writer([CLEAN])) as get:
            page = self.client.get(f"/queue/{qid}").text
        self.assertIn("the suite rewrote it. Nothing to fix.", page)
        self.assertIn("Captions rewritten by the suite (template", page)      # no copy of the photo here: the template wrote
        self.assertNotIn("includes portraits", page)
        self.assertNotIn('class="rule block"', page)
        self.assertEqual(page.count('class="rule ok">passes'), 3)
        self.assertTrue(all(copy_rules.check(t, social=True).ok for t in json.loads(self.row(qid)["caption"]).values()))
        page = self.client.get(f"/queue/{qid}").text
        self.assertNotIn("Nothing to fix.", page, "once mended it just passes")
        self.assertIn("rules pass, rewritten by the suite", self.client.get("/").text)

    def test_approve_mends_first_instead_of_refusing(self):
        qid = self.draft()
        r = self.client.post(f"/queue/{qid}/approve", follow_redirects=False)
        self.assertIn("msg=approved", r.headers["location"])
        row = self.row(qid)
        self.assertEqual(row["status"], "approved")
        self.assertTrue(all(copy_rules.check(t, social=True).ok for t in json.loads(row["caption"]).values()))
        self.assertEqual(len(json.loads(row["rule_report"])["mended"]), 1)

    def test_an_official_post_for_an_official_event_is_left_as_it_is(self):
        now = db.utcnow()
        cid = db.insert(self.conn, "conventions", name="Liberty Summit", kind="business", official=1, start_date="2026-11-02",
                        created_at=now, updated_at=now)
        text = "Official photographer at the summit: a speaker on the main stage. Request a quote for your event."
        qid = self.draft(caption=text)
        self.conn.execute("UPDATE content_queue SET convention_id=? WHERE id=?", (cid, qid))
        self.assertIsNone(content.mend_captions(self.conn, self.row(qid), drafter=Writer([])), "Chris marked it official")
        self.client.get(f"/queue/{qid}")
        self.assertEqual(json.loads(self.row(qid)["caption"])["instagram"], text)
        self.conn.execute("UPDATE conventions SET official=0 WHERE id=?", (cid,))
        self.assertEqual(content.mend_captions(self.conn, self.row(qid), drafter=Writer([CLEAN]))["by"], "claude-test")
        self.assertNotIn("Official", json.loads(self.row(qid)["caption"])["instagram"])

    def test_a_draft_already_approved_is_not_touched_by_the_page(self):
        qid = self.draft(status="approved")
        self.client.get(f"/queue/{qid}")
        self.assertEqual(json.loads(self.row(qid)["caption"])["instagram"], BROKEN)


class TheCard(Mend):
    """The card comes from the same day as the captions: cards from before 2026-10-11 said "coverage", a word
    a card no longer carries, so a mended draft's card is drawn again with today's words."""

    def test_the_card_is_drawn_again_from_the_photo_copy_on_this_machine(self):
        cache = config.get_config().data_root / "photos"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "e1.img").write_bytes(jpeg_bytes(seed=3, size=(3000, 2000)))
        old = self.root / "old-card.jpg"
        old.write_bytes(jpeg_bytes(size=(1080, 1350)))
        qid = self.draft()
        self.conn.execute("UPDATE content_queue SET render_paths=? WHERE id=?", (json.dumps({"4:5": [str(old)]}), qid))
        self.conn.execute("UPDATE photos SET local_path=? WHERE id=?", (str(cache / "e1.img"), self.pid))
        mend = content.mend_captions(self.conn, self.row(qid), drafter=Writer([CLEAN]))
        self.assertEqual(mend["card"], "card drawn again with today's words")
        paths = json.loads(self.row(qid)["render_paths"])
        self.assertEqual(sorted(paths), ["2:3", "4:5"])
        for files in paths.values():
            for f in files:
                self.assertNotEqual(f, str(old))
                self.assertTrue(Path(f).is_file(), f)
                self.assertIn(str(config.get_config().data_root / "renders" / "posts" / "2026-10-12"), f)
        data = Path(paths["4:5"][0]).read_bytes()
        self.assertIn(b"Stage and panel", data, "today's words travel in the file")
        self.assertIn("Card drawn again with today&#39;s words.", self.client_page(qid))

    def test_without_a_copy_of_the_photo_the_old_card_stays_and_says_so(self):
        old = self.root / "old-card.jpg"
        old.write_bytes(jpeg_bytes(size=(1080, 1350)))
        qid = self.draft()
        self.conn.execute("UPDATE content_queue SET render_paths=? WHERE id=?", (json.dumps({"4:5": [str(old)]}), qid))
        mend = content.mend_captions(self.conn, self.row(qid), drafter=Writer([CLEAN]))
        self.assertEqual(mend["card"], f"card kept: no copy of photo {self.pid} on this machine")
        self.assertEqual(json.loads(self.row(qid)["render_paths"]), {"4:5": [str(old)]})
        self.assertTrue(all(copy_rules.check(t, social=True).ok for t in json.loads(self.row(qid)["caption"]).values()), "the captions are mended all the same")

    def client_page(self, qid):
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        return client.get(f"/queue/{qid}").text
