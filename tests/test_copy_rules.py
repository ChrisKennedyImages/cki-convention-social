from __future__ import annotations

import unittest

from convention_social.ai import copy_rules
from convention_social.ai.claude import tidy


class CopyRules(unittest.TestCase):
    def test_clean_caption_passes(self):
        r = copy_rules.check("Green room calm before the keynote. Request a quote for your event.")
        self.assertTrue(r.ok, r.as_dict())

    def test_prices_are_blocked(self):
        for text in ("Coverage from $500 a day.", "Headshots 20% off this week.", "Only 300 dollars.",
                     "Starting at a fair rate.", "Use promo code CON.", "€200 per session"):
            r = copy_rules.check(text)
            self.assertFalse(r.ok, text)
            self.assertIn("price", [b.rule for b in r.blocks], text)

    def test_dashes_are_blocked(self):
        for text in ("Backstage — before the panel.", "Day one – done.", "Calm - then chaos."):
            self.assertIn("dash", [b.rule for b in copy_rules.check(text).blocks], text)
        # a range is not punctuation: Chris writes dates "March 11–14, 2027" in his outreach template (2026-10-31)
        for text in ("taking place March 11–14, 2027, in Washington, DC.", "Doors 9–5.", "December 31, 2026–January 2, 2027"):
            self.assertNotIn("dash", [b.rule for b in copy_rules.check(text).blocks], text)

    def test_hyphenated_words_are_fine(self):
        self.assertTrue(copy_rules.check("Well-lit portraits between the sessions.").ok)

    def test_nothing_includes_anything(self):
        """Chris, 2026-10-11, on a real draft: "Suite wide - NOTHING INCLUDES ANYTHING! Don't ever say
        something you don't know or don't ask me about my own company"."""
        for text in ("Conference photography includes portraits like this one, shot on site in a few minutes.",
                     "A short line of attendees who all leave with a new headshot.",
                     "Every guest gets their photos the same day.", "Headshots come with retouching.",
                     "Ask about our packages.", "Fast turnaround on every gallery.", "Delivered within hours.",
                     "Including the green room.", "Unlimited photos for your team."):
            r = copy_rules.check(text)
            self.assertIn("claims", [b.rule for b in r.blocks], text)
            self.assertIn("nothing includes anything", r.blocks[0].message)
        self.assertTrue(copy_rules.check("One of us writes back within 24 hours.").ok, "his stated reply promise")
        self.assertTrue(copy_rules.check("Selects within the hour when we know before the event which moments you want.").ok,
                        "his stated promise for selects, 2026-10-30")
        self.assertFalse(copy_rules.check("Selects within an hour.").ok, "any other time is still a claim")
        for text in ("Conference photography, covering the main stage, the keynotes, the breakouts and the panels.",
                     "Guests scan their badge, add a selfie, and every photo they are in comes straight to them.",
                     "Request a quote for your event.", "Based in Washington DC, covering events nationwide."):
            self.assertTrue(copy_rules.check(text).ok, text)

    def test_affiliation_needs_confirmation(self):
        text = "Proud to be the official photographer of this show."
        self.assertIn("affiliation", [b.rule for b in copy_rules.check(text).blocks])
        self.assertTrue(copy_rules.check(text, official=True).ok)

    def test_promises_blocked(self):
        self.assertFalse(copy_rules.check("Guaranteed the best shots.").ok)

    def test_offer_talk_is_blocked_on_social_copy_only(self):
        """Chris, 2026-10-11: "keep to specifics and not talk about what is offered or what is a service,
        specifically in captions and social media"."""
        for text in ("Every room of your event, covered.", "Your vendors and exhibitors get their shots too.",
                     "Photo delivery by face match while the event is on.", "We cover whole events.",
                     "Our services for conferences.", "Full coverage from the keynote on.", "Scan a badge, add a selfie.",
                     "Conference photography and what we offer."):
            r = copy_rules.check(text, social=True)
            self.assertIn("offer", [b.rule for b in r.blocks], text)
            self.assertIn("what the photo shows", r.blocks[0].message)
            self.assertTrue(copy_rules.check(text).ok, f"a quote reply or a note to an organizer may say it: {text}")
        for text in ("Conference photography: a speaker on the main stage. Event Caliber, event photographer.",
                     "Based in Washington DC, covering events nationwide. Request a quote for your event.",
                     "The keynote, from the room.", "ONE EVENT. ROOM BY ROOM."):
            self.assertTrue(copy_rules.check(text, social=True).ok, text)

    def test_tidy_turns_dashes_into_commas(self):
        out = tidy("Backstage — before the panel -- calm")
        self.assertTrue(copy_rules.check(out).ok, out)
        self.assertNotIn("—", out)
