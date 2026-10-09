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

    def test_hyphenated_words_are_fine(self):
        self.assertTrue(copy_rules.check("Same-day delivery of approved images.").ok)

    def test_affiliation_needs_confirmation(self):
        text = "Proud to be the official photographer of this show."
        self.assertIn("affiliation", [b.rule for b in copy_rules.check(text).blocks])
        self.assertTrue(copy_rules.check(text, official=True).ok)

    def test_promises_blocked(self):
        self.assertFalse(copy_rules.check("Guaranteed the best shots.").ok)

    def test_tidy_turns_dashes_into_commas(self):
        out = tidy("Backstage — before the panel -- calm")
        self.assertTrue(copy_rules.check(out).ok, out)
        self.assertNotIn("—", out)
