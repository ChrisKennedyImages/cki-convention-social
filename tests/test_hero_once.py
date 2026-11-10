"""The hero once (Chris, 2026-11-09, his choice "the hero not back-to-back"): no picture twice in a reel holds for the hero
too, even with nothing between. Darkroom's hero had come back after the contact sheet, the enlarger, the tray and the zone
scale (at 4.40 s, 6.47 s and 10.00 s); Section's after its room's stop and again after its word (at 9.50 s and 12.27 s).
Now Darkroom's cut frame, the enlarger's picture and the tray's print are three other photos of the post, and the hero is
first seen on the line; Section's room A has a photo of its own, seen on its stop and drawn empty beside its word, and the
hero is seen in the exploded view and the end card only. Proved on a render by the card check, recorded with no picture
back with nothing between."""
from __future__ import annotations

import json
import re

from PIL import Image

from convention_social import music
from convention_social.render import reel_check, reel_looks
from tests._base import IsolatedCase

LOOKS_SRC = reel_looks.REEL_LOOKS / "src" / "looks"


def photo(room, colour):
    return reel_looks.LookPhoto(Image.new("RGB", (300, 200), (colour, 0, 0)), room)


class TheHeroOnce(IsolatedCase):
    def test_darkroom_shows_the_hero_on_the_line_the_daylight_and_the_end_card_only(self):
        text = (LOOKS_SRC / "Darkroom.tsx").read_text()
        self.assertEqual(text.count("own(p, ar, HERO)"), 2, "the daylight and the end card; the line takes it as the first word")
        for scene, pic in (("Contact", "CHOSEN"), ("Enlarger", "ENLARGED"), ("Tray", "TRAY")):
            body = text.split(f"const {scene}: Scene")[1].split("\nconst ")[0]
            self.assertNotIn("HERO)", body, scene)
            self.assertIn(f"own(p, ar, {pic})", body, scene)
        self.assertIn("const HERO = 0, TRAY = 3, ENLARGED = 4, CHOSEN = 5, ON_SHEET = [6, 7];", text)
        self.assertEqual(reel_looks.SLOTS["darkroom"], reel_looks.Slots(8, 8))
        self.assertIn("darkroom", reel_looks.FIRST_WORD_LEADS, "the hero carries the first word, on the line")

    def test_section_shows_the_hero_in_the_exploded_view_and_the_end_card_only(self):
        text = (LOOKS_SRC / "Section.tsx").read_text()
        self.assertEqual(len(re.findall(r"photoAt\(p, HERO\)", text)), 2, "the exploded view's top plate and the title under it")
        self.assertIn("floor(ROOM_A, ROOM_B, F0);", text, "no room of the drawing is the hero's")
        self.assertIn("if (g >= 222 && g < 346) return !stop && wordRoom.includes(r)", text, "a room seen on its stop stays empty")
        self.assertEqual(reel_looks.SLOTS["section"], reel_looks.Slots(6, 3))
        self.assertNotIn("section", reel_looks.FIRST_WORD_LEADS, "its words go on the three photos after the hero")

    def test_the_words_go_on_the_photos_they_name_and_section_words_its_room_a(self):
        plan = reel_looks.Plan(1, music.LookTrack(reel_check.silence(self.root / "s.wav", 1), 0.0, 1.0))
        rooms = ["main_stage", "candid", "reception", "breakout", None, "backstage"]
        p = reel_looks.props("section", [photo(r, 30 * k) for k, r in enumerate(rooms)], plan=plan,
                             fillers=[reel_looks.Filler(k, self.filler(k)) for k in range(3)], public=self.root / "section")
        self.assertEqual(p["wordPhotos"], [1, 2, 3], "room A, B and C: the three after the hero")
        self.assertEqual(p["words"], ["Candid.", "Reception.", "Breakouts."], "each its own photo's room")
        with Image.open(self.root / "section" / p["photos"][0]["src"]) as im:
            self.assertEqual(im.getpixel((5, 5))[0], 0, "the hero leads, for the exploded view")
        rooms = ["main_stage", "candid", "reception", None, "breakout", "backstage", None, "candid"]
        p = reel_looks.props("darkroom", [photo(r, 30 * k) for k, r in enumerate(rooms)], plan=plan,
                             fillers=[reel_looks.Filler(k, self.filler(k)) for k in range(8)], public=self.root / "darkroom")
        self.assertEqual((p["wordPhotos"], p["words"]), ([0, 1, 2], ["Main stage.", "Candid.", "Reception."]))
        self.assertEqual((len(p["photos"]), len(p["fillers"])), (8, 8))

    def filler(self, k):
        path = self.root / f"f{k}.jpg"
        Image.new("RGB", (300, 200), (0, 0, 10 * k)).save(path, "JPEG")
        return path

    def test_their_card_checks_found_no_picture_back_with_nothing_between(self):
        book = json.loads(reel_check.REGISTRY.read_text())
        for look in ("darkroom", "section"):
            self.assertEqual(book[look]["source"], reel_check.source_hash(look), f"run `ccs reel-check {look} --record`")
            self.assertEqual(book[look]["back_with_nothing_between"], [], f"{look}: a picture back with nothing between")
