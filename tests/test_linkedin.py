"""The LinkedIn lane (2026-11-01): Chris's own profile, through the same Buffer account. Off until linkedin is added to
POST_NETWORKS on the Keys page, like Facebook and Pinterest since 2026-10-15; one photo per post (the hero alone on its
4:5 card); one post a day, weekday mornings, none at weekends; the caption in his own voice, through the same gate as
every caption. Buffer's live schema was read the same day: every LinkedInPostMetadataInput field is optional, so an
image post carries no metadata, and the channel service is linkedin."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from convention_social.agents import art_director, pacing, publisher
from convention_social.ai import claude, copy_rules, seo_plan
from convention_social.buffer import payloads
from convention_social.core import config, db
from convention_social.render.motion import LINKEDIN_CARD
from tests._fakes import AgentCase, add_channels, add_photo, add_post, all_eligible, make_ctx, write_render

NY = ZoneInfo("America/New_York")
FRIDAY_8AM = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)      # 08:00 New York, a Friday
FRIDAY, SATURDAY, MONDAY = date(2026, 10, 9), date(2026, 10, 10), date(2026, 10, 12)


class Switch(AgentCase):
    """Off by default; on by adding linkedin to POST_NETWORKS. Verified at the consumer: what the publisher builds."""

    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        p = mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible())
        p.start()
        self.addCleanup(p.stop)

    def post(self):
        pid = add_photo(self.conn, self.root / "photos", seed=1)
        renders = {"4:5": [write_render(self.root / "renders", "r-45.jpg")], "2:3": [write_render(self.root / "renders", "r-23.jpg")],
                   LINKEDIN_CARD: [write_render(self.root / "renders", "r-linkedin.jpg")]}
        return add_post(self.conn, [pid], ("instagram", "linkedin"), render_paths=renders)

    def row(self, qid):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))

    def test_linkedin_is_a_network_the_suite_knows_and_is_off_by_default(self):
        self.assertIn("linkedin", payloads.NETWORKS)
        self.assertEqual(payloads.name_of("linkedin"), "LinkedIn")
        self.assertEqual(payloads.posting_networks(), ("instagram",))
        os.environ["POST_NETWORKS"] = "instagram, LinkedIn"
        config.reset()
        self.assertEqual(payloads.posting_networks(), ("instagram", "linkedin"))

    def test_off_a_linked_channel_gets_nothing_and_nothing_is_reported(self):
        add_channels(self.conn, "instagram", "linkedin")
        qid = self.post()
        stats = publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        row = self.row(qid)
        self.assertEqual(row["status"], "would_publish")
        self.assertEqual(set(json.loads(row["payload"])), {"instagram"})
        self.assertEqual(stats["skipped_networks"], 0)
        self.assertFalse(row["last_error"])
        self.assertEqual(db.rows(self.conn, "SELECT kind FROM errors WHERE kind='no_channel'"), [], "a network that is off is no fault")

    def test_on_the_post_goes_to_his_channel_as_one_image_with_no_metadata(self):
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        add_channels(self.conn, "instagram", "linkedin")
        qid = self.post()
        publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        payload = json.loads(self.row(qid)["payload"])
        self.assertEqual(set(payload), {"instagram", "linkedin"})
        li = payload["linkedin"]
        self.assertEqual(li["channelId"], "ch-li")
        self.assertEqual(len(li["assets"]), 1, "one photo per post")
        self.assertIn("linkedin", li["assets"][0]["image"]["url"], "the LinkedIn card (media.card_key), not the 4:5 design")
        self.assertNotIn("metadata", li, "every LinkedInPostMetadataInput field is optional (live schema, 2026-11-01)")
        self.assertEqual((li["mode"], li["schedulingType"], li["needsApproval"]), ("customScheduled", "automatic", False))
        self.assertEqual(li["dueAt"], "2026-10-09T13:00:00Z", "9:00 New York on a weekday")
        self.assertEqual(payload["instagram"]["assets"][0]["image"]["url"].count("linkedin"), 0, "Instagram keeps its own design")

    def test_on_without_his_channel_linked_the_draft_says_so(self):
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        add_channels(self.conn, "instagram")
        qid = self.post()
        stats = publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        row = self.row(qid)
        self.assertEqual(set(json.loads(row["payload"])), {"instagram"})
        self.assertEqual(stats["skipped_networks"], 1)
        said = " ".join(e["message"] for e in db.rows(self.conn, "SELECT message FROM errors WHERE kind='no_channel'"))
        self.assertIn("linkedin", said.lower())

    def test_the_payload_builder_takes_one_image_and_sends_no_metadata(self):
        inp = payloads.build("linkedin", "ch-li", "Backstage. Request a quote.", ["https://m.example/a.jpg", "https://m.example/b.jpg"],
                             scheduled_for="2026-12-07T09:00")
        self.assertEqual([a["image"]["url"] for a in inp["assets"]], ["https://m.example/a.jpg"])
        self.assertNotIn("metadata", inp)
        self.assertEqual(inp["dueAt"], "2026-12-07T14:00:00Z")      # EST in December
        self.assertEqual(inp["mode"], "customScheduled")


class Pacing(AgentCase):
    """One a day, 9:00 am Eastern on weekdays, none at weekends; no second time; a time Chris chose counts as the day's."""

    def test_the_defaults(self):
        self.assertEqual(pacing.time_for("linkedin", FRIDAY).strftime("%H:%M"), "09:00")
        self.assertIsNone(pacing.time_for("linkedin", SATURDAY))
        self.assertIsNone(pacing.second_time_for("linkedin", FRIDAY))
        conn = self.connect()
        self.assertEqual([s.strftime("%H:%M") for s in pacing.day_slots(conn, "linkedin", FRIDAY, NY)], ["09:00"])
        self.assertEqual(pacing.day_slots(conn, "linkedin", SATURDAY, NY), [])
        text = pacing.describe()
        self.assertIn("LinkedIn 9:00 am weekdays.", text)
        self.assertIn("Instagram 11:30 am and 5:30 pm weekdays, 10:00 am and 4:00 pm weekends.", text, "the others as they were")

    def test_the_next_slot_is_the_next_weekday_morning(self):
        conn = self.connect()
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "linkedin", FRIDAY_8AM)), "2026-10-09T09:00")
        friday_noon = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "linkedin", friday_noon)), "2026-10-12T09:00", "the weekend is skipped")
        planned = pacing.plan(conn, ["instagram", "linkedin"], None, friday_noon)
        self.assertEqual(planned["linkedin"], "2026-10-12T09:00")

    def test_one_a_day_even_beside_a_time_chris_chose(self):
        conn = self.connect()
        qid = add_post(conn, [1], ("linkedin",), status="scheduled")
        conn.execute("UPDATE content_queue SET payload=? WHERE id=?",
                     (json.dumps({"linkedin": {"dueAt": "2026-10-09T18:00:00Z"}}), qid))     # Friday 14:00 New York, his time
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "linkedin", FRIDAY_8AM)), "2026-10-12T09:00",
                         "Friday has its one LinkedIn post, five hours from the morning slot or not")
        self.assertEqual(pacing.slot_value(pacing.next_slot(conn, "facebook", FRIDAY_8AM)), "2026-10-09T09:30", "the others still take two a day")

    def test_post_times_keeps_weekends_off_unless_told(self):
        os.environ["POST_TIMES"] = "linkedin=08:30"
        config.reset()
        self.assertEqual(pacing.times_table()["linkedin"], (time(8, 30), None))
        os.environ["POST_TIMES"] = "linkedin=08:30/10:00"
        config.reset()
        self.assertEqual(pacing.times_table()["linkedin"], (time(8, 30), time(10, 0)))
        os.environ["POST_TIMES"] = "linkedin=08:30/junk"
        config.reset()
        self.assertEqual(pacing.times_table()["linkedin"], (time(9, 0), None), "an unreadable weekend time keeps the default")
        os.environ["POST_TIMES"] = "facebook=08:00"
        config.reset()
        self.assertEqual(pacing.times_table()["facebook"], (time(8, 0), time(8, 0)), "one time still means every day for the others")

    def test_the_learner_leaves_the_hour_alone_and_the_learner_page_says_so(self):
        from convention_social.agents import learner
        conn = self.connect()
        suggestion = learner.learn(conn, config.get_config(), FRIDAY_8AM)
        self.assertNotIn("linkedin", suggestion.times, "no weekend time to learn from: the hour is not learned")
        self.assertIn("instagram", suggestion.times)
        row = next(n for n in learner.dashboard_view(conn)["networks"] if n["network"] == "linkedin")
        self.assertEqual((row["start"], row["in_use"], row["suggested"]), ("9:00 am weekdays only", "9:00 am weekdays only", "not learned"))

    def test_the_today_page_says_the_schedule_in_his_words(self):
        from convention_social.dashboard import today
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        conn = self.connect()
        times = " | ".join(today.schedule(conn, FRIDAY_8AM)["times"])
        self.assertIn("LinkedIn posts go out at 9:00 am on weekdays, never at weekends", times)
        self.assertNotIn("Linkedin", times)


class Captions(AgentCase):
    """In his voice, built for search like the rest, and through the same gate."""

    def plan(self):
        return seo_plan.plan_for(subject="event", event_kind="business", shot_type="main_stage")

    def test_the_writer_is_asked_for_a_linkedin_caption_in_the_first_person(self):
        self.assertIn("linkedin", claude.NETWORKS)
        self.assertIn("linkedin", claude.OUTPUT_SCHEMA["properties"]["captions"]["required"])
        facts = claude.PostFacts(brand_name="Event Caliber", event_kind="business", shot_type="main_stage", quote_link="eventcaliber.com/book")
        facts.plan = self.plan()
        self.assertIn("linkedin (two or three short paragraphs in the first person singular", claude.user_text(facts))
        self.assertIn("first person singular", claude.SYSTEM_PROMPT)
        self.assertIn("under 200 characters", claude.SYSTEM_PROMPT)

    def test_the_template_meets_the_plan_and_finish_keeps_paragraphs_adds_the_link_and_three_hashtags(self):
        plan = self.plan()
        caps = seo_plan.template_captions(plan, "eventcaliber.com/book", "Event Caliber")
        self.assertIn("linkedin", caps)
        self.assertEqual(seo_plan.problems(caps, plan), [])
        self.assertEqual(len(seo_plan.HASHTAG.findall(caps["linkedin"])), 3)
        self.assertIn("eventcaliber.com/book", caps["linkedin"])
        done = seo_plan.finish({"linkedin": "Conference photography, from the floor. #x\n\nAn event photographer is in the room before the doors open."},
                               plan, "eventcaliber.com/book")
        self.assertEqual(done["linkedin"], "Conference photography, from the floor.\n\nAn event photographer is in the room before the doors open. "
                                           "eventcaliber.com/book\n\n" + " ".join(plan.hashtags[:3]))
        self.assertEqual(seo_plan.problems(done, plan), [])
        self.assertNotIn("\n", seo_plan.finish({"facebook": "One.\n\nTwo."}, plan, "")["facebook"], "Facebook as it was")

    def test_the_phrase_must_show_before_see_more(self):
        plan = self.plan()
        late = {"linkedin": "A long opening sentence " + "that says nothing in particular, " * 8 + "conference photography. Event photographer."}
        got = " | ".join(seo_plan.problems(late, plan))
        self.assertIn("on LinkedIn", got)
        self.assertIn("falls below the fold (the first 200 characters)", got)
        long = {"linkedin": "Conference photography, from the floor. Event photographer. " + "More words. " * 300}
        self.assertIn("the LinkedIn caption is over 3000 characters", seo_plan.problems(long, plan))

    def test_the_same_gate_as_every_caption(self):
        """His rules hold on LinkedIn too: no dash as punctuation, nothing about services or delivery, nothing promised."""
        ok = ("Conference photography, from the floor of a packed main stage. I stood at the side for this one and waited for "
              "the room to settle. Request a quote for your event.")
        self.assertTrue(copy_rules.check(ok, social=True).ok)
        for text, rule in (("Conference photography — from the floor.", "dash"), ("Every attendee leaves with their photos.", "claims"),
                           ("We offer full coverage of your event.", "offer"), ("Headshots from $150.", "price")):
            self.assertIn(rule, [b.rule for b in copy_rules.check(text, social=True).blocks], text)


class Card(AgentCase):
    """The hero alone on the single card at 4:5, every design; the art director does not look at it a second time."""

    def test_the_art_director_skips_the_linkedin_card_and_still_passes_it_on(self):
        conn = self.connect()
        folder = self.root / "r"
        paths = {"4:5": [write_render(folder, "a.jpg")], "2:3": [write_render(folder, "p.jpg")], LINKEDIN_CARD: [write_render(folder, "l.jpg")]}
        seen = []

        def look(conn_, files, *, brief, client, agent):
            seen.append([Path(f).name for f in files])
            return {"verdict": "pass", "notes": "", "pictures": [], "focus_x": 0.5, "focus_y": 0.42}

        with mock.patch.object(art_director, "look", look):
            out, verdict = art_director.direct(conn, lambda focus: paths, brief=lambda p: "the single card", dry_run=False, max_files=4)
        self.assertEqual(seen, [["a.jpg", "p.jpg"]])
        self.assertEqual(verdict["verdict"], "pass")
        self.assertEqual(out, paths, "the card still goes out with the draft")
