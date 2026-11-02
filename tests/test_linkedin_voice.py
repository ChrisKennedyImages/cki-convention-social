"""The LinkedIn caption in Chris's voice, gated against drift (2026-11-01). His words, in order: "this is way to fake ... in
my voice and less robotic and I don't explain shots"; "The 3rd one is closest - but the others sound like a robot"; "Never
use "brothers" use "we""; "You're using a lot of innuendo's and silly kid of wording. Tell it more specifically and more
casually written ... It's written like AI would write it"; and on lines in his own rhythm: "Much better! That's great, but
gate any drift so you don't steer back to another tone or voice." "the 1st image is a women which is VERY VERY VERY
important not to mess up." "I just can't have you mixing up captions that say he when it's a she.\""""
from __future__ import annotations

import json
import os
import types
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from convention_social.agents import content
from convention_social.ai import claude, copy_rules, linkedin, seo_plan
from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase
from tests._fakes import AgentCase, add_photo, add_post, write_render

DOMAIN = "eventcaliber.com"
TAIL = f"\n\n{DOMAIN}\n\n#eventphotography #conferencephotography"
MONDAY_6AM = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
APPROVED = [line for lines in linkedin.EXAMPLES.values() for line in lines]
# every line he turned back, from the first round to the third, and the coordinator's rejected set
REJECTED = (
    "She had the whole room with her from the first sentence.",
    "A speaker settling in at the podium, right before the room goes quiet. If you have a conference coming up, I'd be glad to hear about it.",
    "Thirty some years in and the hallway is still where the good stuff happens. My brother and I keep showing up for it.",
    "She leaned out over the front row like she was telling one person a secret, and the whole room leaned in with her. We have both been "
    "doing this more than thirty years and that moment still gets us.",
    "He leans into the microphone and the room settles. My brother and I have been doing this more than thirty years each, and the shot is "
    "already done before he finishes the sentence.",
    "Three decades in and the audience still tells me more than the stage does. My brother and I keep watching the seats.",
    "She asked a question, waited, and the room went quiet. We watched the whole audience lean in before she said another word.",
    "He held perfectly still while the crowd behind him kept moving. Hours later the day was over for everyone else, and the client still has "
    "that one quiet second from it.",
    "She leaned out over the front row and the whole room leaned with her. We got the second she made her point land.",
    "The crowd stops talking. He holds still, and nobody moves. We have the picture, and you have the day.",
    "Thirty some years of this and the honest reactions in the crowd still get me. We watch the room, because that is where people forget "
    "they are being seen.",
    "Love when that happens!",
    "The crowd is half the story at any conference.",
    "You can't plan that kind of thing, you just have to be ready for it.",
)


class Rotation(AgentCase):
    def test_round_robin_never_twice_running(self):
        self.assertEqual(linkedin.next_style(None), "moment")
        self.assertEqual(linkedin.next_style("moment"), "client")
        self.assertEqual(linkedin.next_style("client"), "attendees")
        self.assertEqual(linkedin.next_style("attendees"), "moment")
        self.assertEqual(linkedin.next_style("nonsense"), "moment")
        conn = self.connect()
        picks = [content.linkedin_style(conn) for _ in range(5)]
        self.assertEqual(picks, ["moment", "client", "attendees", "moment", "client"])
        self.assertEqual(settings.get(conn, content.LINKEDIN_STYLE_KEY), "client", "recorded the moment it is chosen")


class Golden(IsolatedCase):
    """The drift gate: his lines pass, every line he turned back fails."""

    def test_every_approved_line_passes_his_rules_and_the_gate(self):
        for style, lines in linkedin.EXAMPLES.items():
            for line in lines:
                done = linkedin.finish(line, DOMAIN)
                self.assertEqual(linkedin.problems(done, style), [], line)
                self.assertTrue(copy_rules.check(done, social=True, linkedin=True).ok, line)
        for style, line in linkedin.FALLBACK.items():
            done = linkedin.finish(line, DOMAIN)
            self.assertEqual(linkedin.problems(done, style), [], line)
            self.assertTrue(copy_rules.check(done, social=True, linkedin=True).ok, line)
            self.assertEqual(linkedin.pronouns_in(done), set(), "the fallback names no he or she, whatever the photo")
            self.assertEqual(linkedin.template(style), line)

    def test_every_rejected_line_fails(self):
        for line in REJECTED:
            done = linkedin.finish(line, DOMAIN)
            why = linkedin.problems(done, "moment") + [b.message for b in copy_rules.check(done, social=True, linkedin=True).blocks]
            self.assertTrue(why, f"should fail: {line}")

    def test_the_rules_by_name(self):
        def why(text, style="moment"):
            return " | ".join(linkedin.problems(linkedin.finish(text, DOMAIN), style))
        self.assertIn("no payoff", why("The room goes quiet and the speaker steps up to the podium."))
        self.assertIn("ends on a tag line", why("Room goes quiet, he steps up, we got the shot. Love when that happens!"))
        self.assertIn("ends on a tag line", why("Room goes quiet, he steps up, we got the shot. That's how it should work."))
        self.assertIn("reaches for a metaphor", why("Room goes quiet, she steps up, we got the shot right when it hit home."))
        self.assertIn("reflects", why("Room goes quiet, we got the shot, and that still gets me every time."))
        self.assertIn("reflects", why("Room goes quiet, we got the shot, thirty some years in."))
        self.assertIn("he says we", why("Room goes quiet, I got the shot."))
        self.assertIn("he says we", why("Room goes quiet, we got the shot, and my favorite part is the hallway."))
        self.assertIn(f"under {linkedin.MAX_WORDS}", why("Room goes quiet, " * 14 + "we got the shot."))
        self.assertIn("explains the shot", why("Room goes quiet, we got the shot from the back wall with the lights down."))
        self.assertEqual(why("Doors open, the room fills, the speaker steps up, we got it, and the attendees have theirs before they hit the hallway.", "attendees"), "")

    def test_finish_is_his_words_then_the_address_then_two_hashtags(self):
        self.assertEqual(linkedin.finish(APPROVED[1], DOMAIN), APPROVED[1] + TAIL)
        messy = APPROVED[1] + " #eventprofs #keynote\n\nhttps://eventcaliber.com"
        self.assertEqual(linkedin.finish(messy, DOMAIN), APPROVED[1] + TAIL, "whatever the writer added comes off")

    def test_the_writer_is_told_his_rhythm_and_only_the_delivery_styles_get_the_delivery_facts(self):
        for style in linkedin.STYLES:
            text = " ".join(linkedin.prompt_lines(style))
            self.assertIn("plain action beats strung with commas", text)
            self.assertIn("never I or my, never brothers, no thirty years", text)
            self.assertIn("Never say how the photo was made", text)
            self.assertIn("Say he or she only when the photo clearly shows one main person", text)
            for line in linkedin.EXAMPLES[style]:
                self.assertIn(line, text)
            self.assertEqual(linkedin.DELIVERY in text, style != "moment", style)
        self.assertNotIn("brother", " ".join(linkedin.prompt_lines("client")).replace("never brothers", ""))
        self.assertIn("own rhythm", claude.SYSTEM_PROMPT)


class NeverBrothers(IsolatedCase):
    """Chris, 2026-11-01: "Never use "brothers" use "we". It's fine on the website, but I don't want it to be a part of posts"."""

    def test_a_post_on_any_network_never_says_brother(self):
        for text in ("My brother and I keep showing up for it.", "Two brothers, thirty years, one camera bag.", "Ask my brother."):
            for linkedin_too in (False, True):
                r = copy_rules.check(text, social=True, linkedin=linkedin_too)
                self.assertIn("brothers", [b.rule for b in r.blocks], (text, linkedin_too))
            self.assertTrue(copy_rules.check(text).ok, f"the website and outreach may still say it: {text}")
        self.assertTrue(copy_rules.check("We keep showing up for it.", social=True, linkedin=True).ok)


class TheGateOnLinkedIn(IsolatedCase):
    """Chris, "Yes, on LinkedIn only": what the site says about delivery may be said there and nowhere else; the steps,
    face match, selfies, badges and a price never pass."""

    def test_delivery_as_the_site_says_it_passes_on_linkedin_and_blocks_everywhere_else(self):
        for text in (APPROVED[2], APPROVED[3]):
            self.assertTrue(copy_rules.check(text, social=True, linkedin=True).ok, text)
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


class Writer:
    """A writer that answers with the same captions every time: the plan's template for the three networks, and `line` for LinkedIn."""
    def __init__(self, line, facts):
        self.line, self.facts, self.calls = line, facts, 0
        self.model = "fake"

    def draft(self, facts, photo, notes=()):
        self.calls += 1
        caps = seo_plan.template_captions(facts.plan, facts.quote_link, facts.brand_name, facts.linkedin_style)
        caps["linkedin"] = self.line
        return claude.Draft(captions=caps, photo_summary="x", model=self.model, alt_text="A speaker on a stage.")


class Judge:
    """The art director's client for the pronoun look: answers the subject question with `subject`; counts the looks."""
    def __init__(self, subject):
        self.subject, self.calls = subject, 0
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        assert list(kw["output_config"]["format"]["schema"]["properties"]) == ["subject"]
        assert "Never write a name" in kw["system"][0]["text"]
        t = types.SimpleNamespace(type="text", text=json.dumps({"subject": self.subject}))
        return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=800, output_tokens=10))


class PronounGate(AgentCase):
    """A he or she stands only when a separate look at the photo says so; else the caption is written again with none, and
    after two misses the fallback, which has none, stands in."""

    def write(self, line, judge, cap="5"):
        os.environ["AI_MONTHLY_CAP_USD"] = cap
        config.reset()
        conn = self.connect()
        facts = claude.PostFacts(brand_name="Event Caliber", event_kind="business", shot_type="main_stage", quote_link="eventcaliber.com/book",
                                 linkedin_style="moment")
        facts.plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="main_stage")
        photo = write_render(self.root / "p", "hero.jpg")
        writer = Writer(line, facts)
        caps, alt, record, by = content.write_captions(writer, facts, __import__("pathlib").Path(photo), [], conn=conn, judge_client=judge)
        return caps["linkedin"], record, by, writer

    def test_a_she_caption_on_a_photo_of_a_woman_is_kept(self):
        line = "She walks right up to the edge of the stage, the front row's hanging on every word, we got it."
        caption, record, by, writer = self.write(line, judge := Judge("woman"))
        self.assertEqual(caption, line + TAIL)
        self.assertEqual((by, writer.calls, judge.calls), ("fake", 1, 1))
        self.assertEqual(record["subject_check"], "woman")

    def test_a_he_caption_on_a_photo_of_a_woman_is_refused(self):
        """Chris: "the 1st image is a women which is VERY VERY VERY important not to mess up"."""
        line = "He walks right up to the edge of the stage, the front row's hanging on every word, we got it."
        caption, record, by, writer = self.write(line, judge := Judge("woman"))
        self.assertEqual(caption, linkedin.FALLBACK["moment"] + TAIL, "two misses: the fallback, which names no one")
        self.assertEqual((by, writer.calls, judge.calls), ("template", 2, 1), "one look serves both tries")
        self.assertIn("says he and the photo check says woman", " | ".join(record["tries"][0]["missed"]))
        self.assertTrue(record["fell_back"])

    def test_an_unsure_look_strips_the_pronouns(self):
        line = "She walks right up to the edge of the stage, we got it."
        caption, record, by, writer = self.write(line, Judge("unclear"))
        self.assertEqual(caption, linkedin.FALLBACK["moment"] + TAIL)
        self.assertIn("the photo check is not sure", " | ".join(record["tries"][0]["missed"]))

    def test_the_cap_reached_strips_the_pronouns_without_a_look(self):
        line = "She walks right up to the edge of the stage, we got it."
        caption, record, by, writer = self.write(line, judge := Judge("woman"), cap="0")
        self.assertEqual(caption, linkedin.FALLBACK["moment"] + TAIL)
        self.assertEqual(judge.calls, 0, "no look under the cap")
        self.assertIn("could not run", " | ".join(record["tries"][0]["missed"]))

    def test_a_caption_with_no_pronoun_needs_no_look(self):
        line = "Doors open, the room fills up, the speaker steps up, we got the shot."
        caption, record, by, writer = self.write(line, judge := Judge("unclear"))
        self.assertEqual(caption, line + TAIL)
        self.assertEqual(judge.calls, 0)
        self.assertNotIn("subject_check", record)


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
            self.assertEqual(json.loads(row["caption"])["linkedin"], linkedin.FALLBACK["moment"] + TAIL, "the fallback in his rhythm")
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
        self.assertIn("style: the moment and the client&#39;s promo", page)

    def test_the_plan_leaves_linkedin_to_his_rules_and_the_others_as_they_were(self):
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="main_stage")
        done = seo_plan.finish({"instagram": "Conference photography today. #random", "facebook": "Conference photography. #x",
                                "pinterest": "Conference photography.", "linkedin": APPROVED[1] + " #x"}, plan, "eventcaliber.com/book")
        self.assertEqual(done["linkedin"], APPROVED[1] + TAIL)
        self.assertEqual(done["facebook"], "Conference photography. eventcaliber.com/book")
        self.assertTrue(done["instagram"].endswith(" ".join(plan.hashtags)))
        self.assertTrue(done["pinterest"].startswith("Conference photography. eventcaliber.com/book #"))
        self.assertEqual(seo_plan.problems({"linkedin": done["linkedin"]}, plan, "moment"), [])
        os.environ["SERVICE_AREA"] = "Washington DC, nationwide"
        config.reset()
        plan = seo_plan.plan_for(subject="event", event_kind="business", shot_type="main_stage")
        self.assertEqual(seo_plan.problems({"linkedin": done["linkedin"]}, plan, "moment"), [], "no place words asked of LinkedIn")
        self.assertTrue(any("does not mention Washington DC" in p for p in seo_plan.problems({"facebook": done["facebook"]}, plan)),
                        "the others still carry the place words")
