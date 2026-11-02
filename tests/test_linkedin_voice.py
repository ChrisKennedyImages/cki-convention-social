"""The LinkedIn caption in Chris's voice (2026-11-01 evening). His words on the first ones: "this is way to fake of a comment
above. I need it to be in my voice and less robotic and I don't explain shots.... It's too much, way too much." He chose
"Mix all three" styles, "LinkedIn only for now", "Photo alone". One or two short plain sentences, then eventcaliber.com,
then two hashtags; never how the photo was made; three styles round robin, said on the draft page; the fallback one of
his approved lines; the other networks' captions exactly as they were."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from convention_social.agents import content
from convention_social.ai import claude, copy_rules, linkedin, seo_plan
from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase
from tests._fakes import AgentCase, add_photo, add_post

DOMAIN = "eventcaliber.com"
TAIL = f"\n\n{DOMAIN}\n\n#eventphotography #conferencephotography"
MONDAY_6AM = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)


class Rotation(AgentCase):
    def test_round_robin_never_twice_running(self):
        self.assertEqual(linkedin.next_style(None), "moment")
        self.assertEqual(linkedin.next_style("moment"), "client")
        self.assertEqual(linkedin.next_style("client"), "personal")
        self.assertEqual(linkedin.next_style("personal"), "moment")
        self.assertEqual(linkedin.next_style("nonsense"), "moment")
        conn = self.connect()
        picks = [content.linkedin_style(conn) for _ in range(5)]
        self.assertEqual(picks, ["moment", "client", "personal", "moment", "client"])
        self.assertEqual(settings.get(conn, content.LINKEDIN_STYLE_KEY), "client", "recorded the moment it is chosen")
        self.assertTrue(all(a != b for a, b in zip(picks, picks[1:])))


class HisLines(IsolatedCase):
    def test_every_approved_line_and_his_own_posts_pass_his_rules_and_the_gate(self):
        for style, lines in linkedin.EXAMPLES.items():
            for line in lines:
                done = linkedin.finish(line, DOMAIN)
                self.assertEqual(linkedin.problems(done, style), [], line)
                self.assertTrue(copy_rules.check(done, social=True, linkedin=True).ok, line)
        self.assertIn("you've already got the promo", linkedin.EXAMPLES["client"][0], "his second line, with the hint at speed he allowed")
        for style, lines in linkedin.FALLBACK.items():
            for line in lines.values():
                self.assertEqual(linkedin.problems(linkedin.finish(line, DOMAIN), style), [], line)
        for post in linkedin.HIS_POSTS:
            self.assertEqual(linkedin.problems(linkedin.finish(post, DOMAIN)), [], post)

    def test_only_the_personal_line_mentions_the_years(self):
        """On a real feed every post would otherwise say thirty years (the three voice2 mocks all did, 2026-11-01)."""
        said = ("Thirty years in and the room still goes quiet for a good speaker.", "Three decades of this and we still lean in.",
                "Twenty years, and the best moments are still backstage.")
        for style in ("moment", "client"):
            for text in said:
                self.assertIn("mentions the years", " | ".join(linkedin.problems(linkedin.finish(text, DOMAIN), style)), (style, text))
            self.assertEqual(linkedin.problems(linkedin.finish(linkedin.EXAMPLES[style][0], DOMAIN), style), [], "his own line for the style")
            self.assertEqual(linkedin.problems(linkedin.finish("Planning a conference next year? We would love to be in the room.", DOMAIN), style), [],
                             "next year is not the years")
            lines = " ".join(linkedin.prompt_lines(style))
            self.assertIn("not the years", lines)
            self.assertNotIn(linkedin.FACTS, lines, "the facts are not offered to this style")
        for text in said:
            self.assertEqual(linkedin.problems(linkedin.finish(text, DOMAIN), "personal"), [], text)
        self.assertIn(linkedin.FACTS, " ".join(linkedin.prompt_lines("personal")))
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="main_stage")
        done = {"linkedin": linkedin.finish("Thirty years in and we still lean in.", DOMAIN)}
        self.assertTrue(seo_plan.problems(done, plan, "moment"), "the plan asks LinkedIn's rules with the draft's style")
        self.assertEqual(seo_plan.problems(done, plan, "personal"), [])

    def test_finish_is_his_words_then_the_address_then_two_hashtags(self):
        self.assertEqual(linkedin.finish("Another great keynote in the books.", DOMAIN), "Another great keynote in the books." + TAIL)
        messy = "Another great keynote in the books. #eventprofs #keynote\n\nhttps://eventcaliber.com"
        self.assertEqual(linkedin.finish(messy, DOMAIN), "Another great keynote in the books." + TAIL, "whatever the writer added comes off")
        self.assertEqual(linkedin.finish("Good day. eventcaliber.com/book", DOMAIN), "Good day." + TAIL)

    def test_too_many_sentences_or_characters(self):
        four = linkedin.finish("One. Two. Three. Four.", DOMAIN)
        self.assertIn("runs to 4 sentences", " | ".join(linkedin.problems(four)))
        long = linkedin.finish("A line that goes on " * 12 + ".", DOMAIN)
        self.assertIn(f"over {linkedin.MAX_CHARS} characters", " | ".join(linkedin.problems(long)))
        self.assertEqual(linkedin.problems(linkedin.finish("The room goes quiet. He steps up to the podium. We've already got the shot, and "
                                                           "you've already got the promo.", DOMAIN)), [], "three short sentences that build")

    def test_explaining_the_shot_is_a_miss(self):
        """What he objected to: light, angles, positions, bursts, gear, technique, narrating the frame."""
        for text in ("I waited for the hand to come forward and shot a short burst.",
                     "The blue wash on the back wall gave me the separation.",
                     "I shot this from the house, low enough to hold the speaker in the same frame.",
                     "Backlit from the stage, 85mm wide open.", "I was positioned at the foot of the stage."):
            got = " | ".join(linkedin.problems(linkedin.finish(text, DOMAIN)))
            self.assertIn("explains the shot", got, text)
        for text in ("Some speakers just own the room!", "You never know when the right moment will come!",
                     "Still love it.", "Great energy in that room today."):
            self.assertEqual(linkedin.problems(linkedin.finish(text, DOMAIN)), [], text)

    def test_the_fallback_is_one_of_his_lines_in_the_drafts_style(self):
        self.assertEqual(linkedin.template("moment", "stage"), "Some speakers just own the room!")
        self.assertEqual(linkedin.template("client", "stage"), "Good room, good speaker, good day. If you've got a conference coming up, let's talk.")
        self.assertEqual(linkedin.template("personal", "stage"), "Over thirty years of doing this and moments like this still never get old.")
        self.assertEqual(linkedin.template("personal", "evening"), linkedin.EXAMPLES["personal"][0], "the line he liked most")
        for style in linkedin.STYLES:
            for room in ("stage", "backstage", "evening", "crowd", "venue"):
                done = linkedin.finish(linkedin.template(style, room), DOMAIN)
                self.assertEqual(linkedin.problems(done, style), [], (style, room))
                self.assertTrue(copy_rules.check(done, social=True, linkedin=True).ok, (style, room))

    def test_the_plan_leaves_linkedin_to_his_rules_and_the_others_as_they_were(self):
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="main_stage")
        done = seo_plan.finish({"instagram": "Conference photography today. #random", "facebook": "Conference photography. #x",
                                "pinterest": "Conference photography.", "linkedin": "Some speakers just own the room! #x"}, plan, "eventcaliber.com/book")
        self.assertEqual(done["linkedin"], "Some speakers just own the room!" + TAIL)
        self.assertEqual(done["facebook"], "Conference photography. eventcaliber.com/book")
        self.assertTrue(done["instagram"].endswith(" ".join(plan.hashtags)))
        self.assertTrue(done["pinterest"].startswith("Conference photography. eventcaliber.com/book #"))
        self.assertEqual(seo_plan.problems({"linkedin": done["linkedin"]}, plan), [], "no search phrase, no place words asked of LinkedIn")
        os.environ["SERVICE_AREA"] = "Washington DC, nationwide"
        config.reset()
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="main_stage")
        self.assertEqual(seo_plan.problems({"linkedin": done["linkedin"]}, plan), [])
        self.assertTrue(any("does not mention Washington DC" in p for p in seo_plan.problems({"facebook": done["facebook"]}, plan)),
                        "the others still carry the place words")


class NeverBrothers(IsolatedCase):
    """Chris, 2026-11-01: "Never use "brothers" use "we". It's fine on the website, but I don't want it to be a part of posts"."""

    def test_a_post_on_any_network_never_says_brother(self):
        for text in ("My brother and I keep showing up for it.", "Two brothers, thirty years, one camera bag.", "Ask my brother."):
            for linkedin_too in (False, True):
                r = copy_rules.check(text, social=True, linkedin=linkedin_too)
                self.assertIn("brothers", [b.rule for b in r.blocks], (text, linkedin_too))
                self.assertIn("a post says we, never brothers", " | ".join(b.message for b in r.blocks))
            self.assertTrue(copy_rules.check(text).ok, f"the website and outreach may still say it: {text}")
        self.assertTrue(copy_rules.check("We keep showing up for it.", social=True, linkedin=True).ok)

    def test_the_writer_is_told_we_and_his_lines_say_we(self):
        for style in linkedin.STYLES:
            self.assertIn("never brother or brothers", " ".join(linkedin.prompt_lines(style)))
            for line in (*linkedin.EXAMPLES[style], *linkedin.FALLBACK[style].values()):
                self.assertNotRegex(line, r"(?i)\bbrothers?\b", line)
        self.assertNotIn("brother", linkedin.FACTS)
        self.assertNotIn("brother", " ".join(linkedin.HIS_POSTS))
        self.assertNotIn("brother", claude.SYSTEM_PROMPT.lower())
        self.assertEqual(linkedin.EXAMPLES["personal"][0],
                         "Thirty some years in and the hallway is still where the good stuff happens. We keep showing up for it.")


class TheGateOnLinkedIn(IsolatedCase):
    """Chris, "Yes, on LinkedIn only": a light hint at how fast the photos come passes there and nowhere else; the steps,
    face match, selfies, badges and a price never pass."""

    def test_a_hint_at_speed_passes_on_linkedin_and_blocks_everywhere_else(self):
        text = "We've already got the shot, and you've already got the promo."
        self.assertTrue(copy_rules.check(text, social=True, linkedin=True).ok, text)
        self.assertTrue(copy_rules.check(text, social=True).ok, "a line that never tripped the gate still does not")
        for text, rule in (("They had the photos the same day.", "claims"), ("Photos delivered before the last session let out.", "offer"),
                           ("Everyone gets their photos within minutes.", "claims")):
            self.assertTrue(copy_rules.check(text, social=True, linkedin=True).ok, text)
            self.assertIn(rule, [b.rule for b in copy_rules.check(text, social=True).blocks], f"Instagram still blocks: {text}")
            if rule == "claims":
                self.assertIn(rule, [b.rule for b in copy_rules.check(text).blocks], f"the site and outreach still block: {text}")

    def test_the_steps_and_a_price_never_pass_on_linkedin(self):
        for text, rule in (("Scan a badge, add a selfie, and the photos come to you.", "offer"), ("Photo delivery by face match.", "offer"),
                           ("Headshots from $150.", "price"), ("Every photo comes with retouching.", "claims"),
                           ("We offer full coverage.", "offer")):
            self.assertIn(rule, [b.rule for b in copy_rules.check(text, social=True, linkedin=True).blocks], text)
        self.assertTrue(copy_rules.check("Guests scan their badge, add a selfie, and every photo they are in comes straight to them.").ok,
                        "the site may still say the steps plainly (2026-10-12)")


class OnTheDraft(AgentCase):
    def test_a_dry_draft_takes_the_next_style_and_his_line_and_the_page_says_so(self):
        from tests.test_linkedin_logo import DraftCase          # the one-photo library, shared
        case = DraftCase("setUp")
        case.setUp()
        try:
            line = content.draft_one(case.ctx(dry=True), case.fetch, now=MONDAY_6AM)
            self.assertIn("LinkedIn the moment", line)
            row = case.row()
            meta = json.loads(row["rule_report"])
            self.assertEqual(meta["linkedin_style"], "moment")
            self.assertEqual(json.loads(row["caption"])["linkedin"], "Another great one in the books." + TAIL,
                             "the template in his voice; the test photo's room is not confirmed as a stage")
            self.assertEqual(settings.get(case.conn, content.LINKEDIN_STYLE_KEY), "moment")
        finally:
            case.tearDown()

    def test_the_draft_page_says_the_style(self):
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        conn = self.connect()
        pid = add_photo(conn, self.root / "photos", seed=1)
        qid = add_post(conn, [pid], ("instagram", "linkedin"), status="draft")
        conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"design": "single", "linkedin_style": "client"}), qid))
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        page = client.get(f"/queue/{qid}").text
        self.assertIn("style: the moment and the client", page)
