"""Captions built around search (Chris, 2026-10-11: "Make sure the captions are SEO optimized
painstakingly"), and no cosplay anywhere ("We are going to NOT do ANY COSPLAY ... erase that from
everything")."""
from __future__ import annotations

import itertools
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from convention_social import offer
from convention_social.agents import content, publisher
from convention_social.ai import claude, copy_rules, names, seo_plan
from convention_social.buffer import payloads
from convention_social.buffer.client import BufferClient
from convention_social.core import config, db, runner, settings
from convention_social.library import eligibility
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_channels, add_photo, add_post, all_eligible, field, make_ctx, write_render, AgentCase
from tests._photos import jpeg_bytes

KINDS = ("business", "fan", None)
SHOTS = ("stage_panel", "backstage", "portrait", "vendor_hall", "dinner_reception", "crowd", None)
DESIGNS = ("single", "spotlight", "carousel", "fan", "facematch", "reel")


def every_plan():
    for subject in ("event", "architecture"):
        for kind, shot, design in itertools.product(KINDS, SHOTS, DESIGNS):
            yield seo_plan.plan_for(subject=subject, event_kind=kind, shot_type=shot, design=design)


class Plans(IsolatedCase):
    def test_every_plan_and_its_template_meet_the_rules(self):
        for area in ("", "Washington DC"):
            os.environ["SERVICE_AREA"] = area
            config.reset()
            plans = list(every_plan())
            self.assertGreater(len(plans), 200)
            for plan in plans:
                caps = seo_plan.template_captions(plan, "eventcaliber.com/book", "Event Caliber")
                self.assertEqual(seo_plan.problems(caps, plan), [], plan)
                for net, text in caps.items():
                    self.assertTrue(copy_rules.check(text, names=list(names.ALWAYS), social=True).ok, (net, text))
                    if net == "linkedin":          # his voice, outside the search rules (2026-11-01 evening; tests/test_linkedin_voice.py)
                        self.assertEqual(seo_plan.linkedin.problems(text), [], text)
                        self.assertEqual(len(seo_plan.HASHTAG.findall(text)), 2)
                        continue
                    self.assertIn(plan.primary.lower(), seo_plan.first_sentence(text).lower())
                self.assertEqual(len(seo_plan.HASHTAG.findall(caps["instagram"])), 5)
                self.assertEqual(len(seo_plan.HASHTAG.findall(caps["pinterest"])), 3)
                self.assertEqual(seo_plan.HASHTAG.findall(caps["facebook"]), [])
                self.assertIn("eventcaliber.com/book", caps["facebook"])
                self.assertLessEqual(len(seo_plan.first_sentence(caps["pinterest"])), 100)
                if area:
                    self.assertIn("Washington DC", caps["facebook"])

    def test_the_phrase_follows_what_the_post_shows(self):
        p = lambda **kw: seo_plan.plan_for(**{"subject": "event", "design": "single", **kw}).primary  # noqa: E731
        self.assertEqual(p(event_kind="business", shot_type="stage_panel"), "conference photography")
        self.assertEqual(p(event_kind="business", shot_type="portrait"), "conference headshots")
        self.assertEqual(p(event_kind="business", shot_type="reception"), "corporate event photography")
        self.assertEqual(p(event_kind="fan", shot_type="stage_panel"), "convention photography")
        self.assertEqual(p(event_kind=None, shot_type="backstage"), "backstage event photography")
        self.assertEqual(p(event_kind="business", shot_type="portrait", design="carousel"), "conference photography")
        self.assertEqual(seo_plan.plan_for(subject="architecture", event_kind=None, shot_type=None).primary, "venue photography")

    def test_misses_are_named(self):
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="stage_panel")
        bad = {"instagram": "A great day on site. " + "x " * 70 + "conference photography.",
               "facebook": "Lovely panel.", "pinterest": "Panel day " + "y" * 120 + ". Conference photography."}
        got = " | ".join(seo_plan.problems(bad, plan))
        for words in ("instagram caption's first sentence", "falls below the fold", "facebook caption uses none of the related",
                      "Pinterest title (its first sentence) is over 100"):
            self.assertIn(words, got)

    def test_finish_puts_hashtags_and_link_where_each_network_wants_them(self):
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="stage_panel")
        done = seo_plan.finish({"instagram": "Conference photography today. #random #tags", "facebook": "Conference photography. #x",
                                "pinterest": "Conference photography."}, plan, "eventcaliber.com/book")
        self.assertTrue(done["instagram"].endswith(" ".join(plan.hashtags)))
        self.assertNotIn("#random", done["instagram"])
        self.assertEqual(done["facebook"], "Conference photography. eventcaliber.com/book")
        self.assertTrue(done["pinterest"].startswith("Conference photography. eventcaliber.com/book #"))


class Writer:
    """Stands in for the caption writer: answers in turn, records what it was told."""
    name = model = "claude-opus-5"

    def __init__(self, answers, alt="A speaker at a podium under stage lights"):
        self.answers, self.alt, self.calls = list(answers), alt, []

    def draft(self, facts, photo, notes=()):
        self.calls.append({"plan": facts.plan, "notes": list(notes)})
        caps = self.answers.pop(0)
        return claude.Draft(captions=caps, photo_summary="x", model=self.model, alt_text=self.alt)


class DailyDraft(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="fe", name="F", clearance="cleared", first_seen_at=now, last_seen_at=now)
        pid = db.insert(self.conn, "photos", drive_id="e1", name="e1.jpg", folder_id="fe", width=3000, height=2000,
                        first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", event_kind="business",
                  convention_name="CPAC 2025", is_convention=1, quality=5, possible_minor=0, personal_details="[]",
                  space="exterior", residential=0, empty_room=0, sharp=1, light=4, moment=4, shot_type="stage_panel", classified_at=now)
        os.environ["BRAND_DOMAIN"] = "eventcaliber.com"
        config.reset()

    def run_draft(self, writer):
        config.get_config().ensure_dirs()
        ctx = runner.Context("content", self.conn, __import__("logging").getLogger("t"), config.get_config(), True, 0)
        line = content.draft_one(ctx, lambda row: jpeg_bytes(seed=1, size=(3000, 2000)), drafter=writer,
                                 now=datetime(2026, 10, 13, 10, tzinfo=timezone.utc))         # tomorrow: Wednesday, a single
        row = db.one(self.conn, "SELECT caption, rule_report FROM content_queue ORDER BY id DESC LIMIT 1")
        return line, json.loads(row["caption"]), json.loads(row["rule_report"])

    GOOD = {"instagram": "Conference photography: the keynote, from the back of the room. Event Caliber, event photographer.",
            "facebook": "Conference photography: the keynote, from the back of the room. Event Caliber, event photographer. Request a quote.",
            "pinterest": "Conference photography: the keynote, from the back of the room. Event Caliber, event photographer."}

    def test_a_draft_that_meets_its_plan_is_used_as_written_with_its_alt_text(self):
        writer = Writer([self.GOOD])
        line, caps, meta = self.run_draft(writer)
        self.assertIn('for "conference photography"', line)
        self.assertEqual(len(writer.calls), 1)
        self.assertEqual(writer.calls[0]["plan"].primary, "conference photography")
        self.assertTrue(caps["instagram"].startswith(self.GOOD["instagram"]))
        self.assertTrue(caps["instagram"].endswith("#eventphotography"))
        self.assertIn("eventcaliber.com/book", caps["facebook"])
        self.assertEqual((meta["model"], meta["seo"]["fell_back"], meta["alt_text"]),
                         ("claude-opus-5", False, "A speaker at a podium under stage lights"))
        self.assertTrue(all(r["ok"] for r in meta["rules"].values()))

    def test_a_miss_is_written_again_with_the_misses_named(self):
        weak = {n: "A great day on stage. Request a quote." for n in self.GOOD}
        writer = Writer([weak, self.GOOD])
        _, caps, meta = self.run_draft(writer)
        self.assertEqual(len(writer.calls), 2)
        self.assertTrue(any('does not say "conference photography"' in n for n in writer.calls[1]["notes"]))
        self.assertTrue(caps["facebook"].startswith("Conference photography"))
        self.assertEqual([len(t["missed"]) > 0 for t in meta["seo"]["tries"]], [True, False])

    def test_service_talk_is_a_miss_even_when_the_plan_is_met(self):
        """Chris, 2026-10-11: "not talk about what is offered or what is a service, specifically in captions"."""
        selling = {n: ("Conference photography from the keynote to the last panel. Your event photographer for every room, "
                       "with photo delivery by face match. Request a quote.") for n in self.GOOD}
        writer = Writer([selling, self.GOOD])
        _, caps, meta = self.run_draft(writer)
        self.assertEqual(len(writer.calls), 2)
        self.assertTrue(any("talks about what is offered" in n for n in writer.calls[1]["notes"]), writer.calls[1]["notes"])
        self.assertTrue(caps["instagram"].startswith("Conference photography: the keynote"))
        self.assertEqual(meta["seo"]["fell_back"], False)

    def test_a_claim_about_the_company_is_never_used(self):
        """The real draft of 2026-10-11: "Suite wide - NOTHING INCLUDES ANYTHING!"."""
        claim = {n: ("Conference photography includes portraits like this one, shot on site in a few minutes. Colored gradient "
                     "background, one chair, and a short line of attendees who all leave with a new headshot. As an event "
                     "photographer I also cover the sessions. Request a quote for your event.") for n in self.GOOD}
        writer = Writer([claim, claim])
        _, caps, meta = self.run_draft(writer)
        self.assertEqual(len(writer.calls), 2)
        self.assertTrue(any("nothing includes anything" in n and "'includes'" in n for n in writer.calls[1]["notes"]), writer.calls[1]["notes"])
        self.assertEqual((meta["model"], meta["seo"]["fell_back"]), ("template", True))
        for net, text in caps.items():
            self.assertTrue(copy_rules.check(text).ok, (net, text))
            self.assertNotIn("includ", text.lower())
        self.assertTrue(all(r["ok"] for r in meta["rules"].values()))

    def test_two_misses_or_a_name_and_the_template_stands_in(self):
        named = {n: "Conference photography at CPAC, your event photographer. Request a quote." for n in self.GOOD}
        writer = Writer([named, named], alt="Speaker at the CPAC podium")
        _, caps, meta = self.run_draft(writer)
        self.assertEqual(len(writer.calls), 2)
        self.assertTrue(any("names 'CPAC'" in n for n in writer.calls[1]["notes"]))
        self.assertEqual((meta["model"], meta["seo"]["fell_back"]), ("template", True))
        self.assertNotIn("cpac", json.dumps(caps).lower())
        self.assertEqual(meta["alt_text"], "Stage panel at a conference, photographed by Event Caliber")


class Prompt(IsolatedCase):
    def test_the_writer_is_told_nothing_includes_anything_and_no_service_talk(self):
        self.assertIn("The words include, coverage, service, offer and delivery never appear.", claude.SYSTEM_PROMPT)
        self.assertIn("Never describe the company's services or what it offers", claude.SYSTEM_PROMPT)
        self.assertIn("A post is about the photo", claude.SYSTEM_PROMPT)
        for word in ("face match", "selfie", "delivers", "covers whole events"):
            self.assertNotIn(word, claude.SYSTEM_PROMPT, word)

    def test_the_writer_is_given_the_plan_and_asked_for_alt_text(self):
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="stage_panel")
        text = claude.user_text(claude.PostFacts(brand_name="Event Caliber", event_kind="business", plan=plan))
        self.assertIn("Search phrase: conference photography.", text)
        self.assertIn("Related search phrases: event photographer; corporate event photography.", text)
        self.assertNotIn("Services:", text, "the writer is given no list of services to repeat")
        self.assertIn("Write no hashtags and no links", text)
        self.assertIn("alt_text", claude.OUTPUT_SCHEMA["required"])
        self.assertIn("first sentence under 100 characters", claude.SYSTEM_PROMPT)

    def test_the_writer_is_told_portraits_are_backstage_and_never_for_every_attendee(self):
        """Chris, 2026-10-12: portraits are backstage for the speakers and VIPs, lit on site with our own lights and
        color gels; portraits for every attendee are a different product, never advertised."""
        portrait = claude.user_text(claude.PostFacts(brand_name="Event Caliber", event_kind="business", shot_type="portrait"))
        for words in ("made backstage", "lit on site with professional lights", "color gels", "finished in the camera",
                      "never say that every attendee gets one"):
            self.assertIn(words, portrait, words)
        self.assertIn("made backstage", claude.user_text(claude.PostFacts(brand_name="Event Caliber", shot_type="headshot")))
        self.assertNotIn("backstage", claude.user_text(claude.PostFacts(brand_name="Event Caliber", shot_type="stage_panel")))
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="portrait")
        caps = seo_plan.template_captions(plan, "eventcaliber.com/book", "Event Caliber")
        self.assertIn(": a portrait lit on site, backstage.", caps["instagram"])
        self.assertNotIn("every attendee", caps["instagram"].lower())


class AltTextAndPins(AgentCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        add_channels(self.conn, "instagram", "facebook", "pinterest")
        # all three networks on, so each one's alt text and pin link is pinned (since 2026-10-15 the default is Instagram only)
        os.environ.update(PINTEREST_BOARD_ID="board-123", BRAND_DOMAIN="eventcaliber.com", POST_NETWORKS="instagram,facebook,pinterest")
        config.reset()

    def post(self):
        self.seed = getattr(self, "seed", 0) + 1
        pid = add_photo(self.conn, self.root / "photos", seed=self.seed)
        qid = add_post(self.conn, [pid], render_paths={"4:5": [write_render(self.root / "data" / "r", "a.jpg")],
                                                        "2:3": [write_render(self.root / "data" / "r", "b.jpg")]})
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"alt_text": "Speaker at a podium"}), qid))
        return qid

    def publish(self, live, fake=None):
        up = lambda path, key: f"https://media.example/m/{key}"  # noqa: E731
        with mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible()):
            return publisher.publish_ready(make_ctx(self.conn, dry_run=not live), now=datetime(2026, 10, 12, 12, tzinfo=timezone.utc),
                                           client=BufferClient("test-key", conn=self.conn, transport=fake or FakeBuffer()), uploader=up)

    def test_alt_text_goes_where_the_live_schema_says_and_pins_link_to_the_quote_page(self):
        qid = self.post()
        fake = FakeBuffer()
        self.publish(True, fake)
        self.assertEqual(len(fake.created), 3)
        for made in fake.created:
            self.assertEqual(made["assets"][0]["image"]["metadata"], {"altText": "Speaker at a podium"})
        self.assertEqual(fake.created[2]["metadata"]["pinterest"]["url"], "https://eventcaliber.com/book/")
        self.assertEqual(json.loads(settings.get(self.conn, publisher.IMAGE_ALT_KEY))["path"], ["metadata", "altText"])
        # a dry run afterwards builds the same, from what the live run read
        qid2 = self.post()
        self.publish(False)
        sent = json.loads(db.one(self.conn, "SELECT payload FROM content_queue WHERE id=?", (qid2,))["payload"])
        self.assertEqual(sent["instagram"]["assets"][0]["image"]["metadata"], {"altText": "Speaker at a podium"})

    def test_no_alt_field_in_buffer_means_no_alt_text_and_the_post_still_goes(self):
        for schema in ({"AssetInput": [field("image", "ImageAssetInput")], "ImageAssetInput": [field("url", "String", True, "SCALAR")]},
                       {"AssetInput": [field("image", "ImageAssetInput")]}):          # no such type at all
            with self.subTest(types=list(schema)):
                self.conn.execute("DELETE FROM content_queue")
                self.post()
                fake = FakeBuffer(schema=schema)
                stats = self.publish(True, fake)
                self.assertEqual(stats["scheduled"], 1)
                self.assertEqual(fake.created[0]["assets"], [{"image": {"url": fake.created[0]["assets"][0]["image"]["url"]}}])


class NoCosplay(IsolatedCase):
    PUBLIC = ("offer.json", "worker/index.js", "convention_social/site/build.py", "convention_social/ai/claude.py",
              "convention_social/ai/seo_plan.py", "convention_social/outreach/draft.py", "convention_social/outreach/research.py",
              "convention_social/seo/photo_text.py", "convention_social/render/meta.py", "convention_social/render/design_samples.py",
              "convention_social/render/motion.py", "convention_social/ai/reply.py")

    def test_no_public_word_offers_cosplay(self):
        root = Path(config.REPO_ROOT)
        for rel in self.PUBLIC:
            self.assertNotIn("cosplay", (root / rel).read_text().lower(), rel)
        self.assertFalse([c for c in offer.coverage_keys() if "cos" in c])

    def test_nothing_positions_the_company_as_political(self):
        """Chris, 2026-10-12: "Preferably not political but will do if they're paying"."""
        from convention_social.seo import photo_text
        root = Path(config.REPO_ROOT)
        for rel in ("offer.json", "convention_social/site/build.py", "convention_social/ai/claude.py",
                    "convention_social/outreach/research.py", "convention_social/outreach/draft.py"):
            self.assertNotIn("political", (root / rel).read_text().lower(), rel)
        self.assertNotIn("political", photo_text.KIND_WORDS["business"])

    def test_a_costume_photo_is_never_used(self):
        conn = db.connect()
        now = db.utcnow()
        db.insert(conn, "drive_folders", drive_id="f", name="F", clearance="cleared", first_seen_at=now, last_seen_at=now)
        pid = db.insert(conn, "photos", drive_id="c1", name="c1.jpg", folder_id="f", first_seen_at=now, last_seen_at=now)
        db.insert(conn, "classifications", photo_id=pid, method="ollama", subject="event", possible_minor=0, personal_details="[]",
                  shot_type="candid", costume=1, classified_at=now)
        self.assertEqual(eligibility.is_candidate(conn, pid), (False, "a costume photo: Event Caliber does no cosplay"))
        from convention_social.dashboard import app as dash
        self.conn = conn
        conn.execute("UPDATE drive_folders SET clearance='not_cleared'")
        dash.prepare_photo_views(conn, eligibility.folder_decisions(conn))
        self.assertEqual(dash.count_photos(conn, "review"), 0, "never even offered for review")
        conn.close()
