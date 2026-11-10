"""A word or a line printed over or beside his photos must be true of them (Chris, 2026-11-09). The reel's room list (the
stack label: "Main stage · reception · candid", the rooms of its three word photos) was printed beside pictures it does
not describe in eight of the ten looks: Weather's cloth over one speaker, Split Screen's field over a contact sheet of
fillers, Chiaroscuro's night watch over one man on a stage, Manifesto's climax under one main-stage photo, Titles' paper
foot under a filler, Darkroom's print margin, Stillness's pair, Powers of Ten's title strip over the mosaic. It is now
printed only where no picture it does not name is in view: Section's roof, lettered while its rooms are drawn empty, and
Axis's far wall. Each room is still named beside its own photo by the beat words. And Split Screen's cover set "Same
moment. every angle." between two photos of two moments: that set never goes on Split Screen."""
from __future__ import annotations

import json

from convention_social import reel_lines
from convention_social.core import db
from convention_social.render import reel_looks
from tests._base import IsolatedCase

LOOKS_SRC = reel_looks.REEL_LOOKS / "src" / "looks"
# the looks that print the room list, and where: over no picture it does not name
ROOM_LIST_OVER_NO_PHOTO = {
    "section": "the dimension across the roof, lettered while the sheet's rooms are drawn empty",
    "axis": "the corridor's far wall, a lit wall with no picture on it",
}


class TheRoomListOnlyBesideWhatItNames(IsolatedCase):
    def test_no_look_prints_the_room_list_beside_a_picture_it_does_not_name(self):
        """One test over every look, so a look added or changed cannot print it beside other pictures unseen: a look
        reads the stack label only where ROOM_LIST_OVER_NO_PHOTO says it sits over no picture."""
        self.assertEqual(set(reel_looks.COMPOSITION), set(reel_looks.LOOKS))
        for look, comp in reel_looks.COMPOSITION.items():
            text = (LOOKS_SRC / f"{comp}.tsx").read_text()
            if look in ROOM_LIST_OVER_NO_PHOTO:
                self.assertIn("p.stackLabel", text, f"{comp}: {ROOM_LIST_OVER_NO_PHOTO[look]}")
            else:
                self.assertNotIn("stackLabel", text, f"{comp} prints the room list beside pictures it does not name")
        for path in LOOKS_SRC.glob("*.ts"):
            self.assertNotIn("stackLabel", path.read_text(), path.name)

    def test_the_set_that_says_same_moment_never_goes_on_split_screen(self):
        """Set 6: "Same moment. every angle." and "Stage and floor." Split Screen sets them between two photos; the suite
        never takes two frames of one moment, so they would be untrue."""
        self.assertEqual(reel_lines.SETS[6].open, ("Same", "moment."))
        self.assertFalse(reel_lines.fits(6, "splitscreen"))
        self.assertTrue(all(reel_lines.fits(6, look) for look in reel_looks.LOOKS if look != "splitscreen"))
        self.assertTrue(all(reel_lines.fits(n, "splitscreen") for n in reel_lines.SETS if n != 6))
        self.assertFalse(reel_lines.fits(11, "weather"), "a set it does not have")
        conn = db.connect()
        self.addCleanup(conn.close)

        def used(n, at):
            db.insert(conn, "content_queue", kind="photo", photo_ids="[]", targets="[]", caption="{}", status="draft",
                      rule_report=json.dumps({"design": "reel", "lines": n}), created_at=at, updated_at=at)
        for n in (1, 2, 3, 4, 5, 7, 8, 9, 10):
            used(n, f"2026-11-{n:02d}T10:00:00+00:00")
        self.assertEqual(reel_lines.choose(conn, "weather"), 6, "the one never used, on any other look")
        self.assertEqual(reel_lines.choose(conn, "splitscreen"), 1, "never on Split Screen: the one used longest ago")
        self.assertEqual(reel_lines.choose(conn), 6)

    def test_a_split_screen_drawn_again_takes_another_set_than_its_own_six(self):
        """A draft's reel is drawn again with its own set (rule_report.lines) only where that set may go on its look."""
        from unittest import mock
        from convention_social import music
        from convention_social.agents import content
        conn = db.connect()
        self.addCleanup(conn.close)
        row, meta = {"render_paths": "{}"}, {"lines": 6, "music": "t.mp3"}
        with mock.patch.object(music, "played_as", return_value=music.LookTrack(self.root / "t.mp3", 0.0, 1.0)):
            self.assertNotEqual(content.look_parts(conn, row, meta, "splitscreen")[0].lines, 6)
            self.assertEqual(content.look_parts(conn, row, meta, "weather")[0].lines, 6, "its own set where it may go")
