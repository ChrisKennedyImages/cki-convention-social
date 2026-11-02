"""Chris, 2026-11-02: "You keep using the same fucking photos for reels! You MUST figure this out too. I'm tired of asking
the same fucking question!" The frames of one Drive folder within MOMENT_MINUTES are one moment: once one airs on a
network its siblings stay off that network for the window, and one post never holds two of them. Candidates come from
the shoot least recently on a post first, and a post takes at most FOLDER_CAP photos from one shoot while other shoots
are free (library/moments, agents/content.Picker, in_turn, shoot_uses)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from convention_social.agents import content, publisher
from convention_social.core import config, db
from convention_social.library import moments
from tests._fakes import add_channels, add_post, all_eligible, make_ctx, write_render
from tests.test_linkedin_logo import DraftCase
from tests.test_repeat_per_network import MONDAY_6AM, FRIDAY_8AM, aired
from unittest import mock


class Case(DraftCase):
    """DraftCase's one photo (folder "fe") plus any the test adds, with their own folder and camera time."""

    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        self.conn.execute("UPDATE photos SET taken_at='2025:02:14 10:00:00' WHERE id=?", (self.pid,))

    def photo(self, folder: str, taken: str, *, quality: int = 5, event: str = "Katsucon") -> int:
        now = db.utcnow()
        if db.one(self.conn, "SELECT 1 FROM drive_folders WHERE drive_id=?", (folder,)) is None:
            db.insert(self.conn, "drive_folders", drive_id=folder, name=folder, clearance="cleared", first_seen_at=now, last_seen_at=now)
        n = db.one(self.conn, "SELECT COUNT(*) AS n FROM photos")["n"] + 1
        pid = db.insert(self.conn, "photos", drive_id=f"d{n}", name=f"d{n}.jpg", folder_id=folder, width=3000, height=2000,
                        taken_at=taken, first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name=event, is_convention=1,
                  quality=quality, possible_minor=0, personal_details="[]", space="exterior", residential=0, empty_room=0, sharp=1,
                  light=4, moment=4, classified_at=now)
        return pid

    def candidates(self) -> list[int]:
        return [r["id"] for r in content.candidates(self.conn, "event")]


class TheMoment(Case):
    def test_siblings_within_ten_minutes_are_held_after_one_airs_on_that_network(self):
        sibling = self.photo("fe", "2025:02:14 10:09:59")
        aired(self.conn, self.pid, ["instagram"])
        used, _, _ = content.recent_use(self.conn, 30, "instagram")
        self.assertEqual(used, {self.pid, sibling}, "the sibling counts as used on Instagram")
        used_li, _, _ = content.recent_use(self.conn, 30, "linkedin")
        self.assertEqual(used_li, set(), "and not on LinkedIn: the window counts per network")
        self.assertEqual(self.candidates(), [sibling, self.pid], "both free for LinkedIn, so candidates; the aired one after its sibling")
        content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        self.assertNotIn("instagram", json.loads(row["targets"]))
        self.assertIn("linkedin", json.loads(row["targets"]))
        self.assertIn(f"photo {self.pid}, a frame of the same moment as one of these, was on post #", json.loads(row["rule_report"])["skipped"]["instagram"])

    def test_siblings_eleven_minutes_apart_are_not(self):
        apart = self.photo("fe", "2025:02:14 10:11:00")
        aired(self.conn, self.pid, ["instagram"])
        used, _, _ = content.recent_use(self.conn, 30, "instagram")
        self.assertEqual(used, {self.pid})
        self.assertEqual(moments.siblings(self.conn, [self.pid]), {self.pid})
        self.assertIn(apart, self.candidates())

    def test_another_folder_at_the_same_minute_is_another_moment(self):
        other = self.photo("other-folder", "2025:02:14 10:00:30")
        self.assertEqual(moments.siblings(self.conn, [self.pid]), {self.pid})
        self.assertNotIn(other, moments.siblings(self.conn, [self.pid]))

    def test_a_photo_with_no_camera_time_is_its_own_moment(self):
        untimed = self.photo("fe", None)
        self.assertEqual(moments.siblings(self.conn, [untimed]), {untimed})
        self.assertEqual(moments.siblings(self.conn, [self.pid]), {self.pid})

    def test_each_photo_sent_from_the_phone_is_its_own_moment(self):
        """Every phone send is filed under one folder id: two sends a minute apart are two pictures he chose, never one
        moment (CI, 2026-11-02: a second share-sheet send was refused on every network)."""
        first = self.photo(moments.PHONE_FOLDER, "2025:02:14 10:00:00")
        second = self.photo(moments.PHONE_FOLDER, "2025:02:14 10:01:00")
        self.assertEqual(moments.siblings(self.conn, [first]), {first})
        self.assertFalse(moments.same_moment(db.one(self.conn, "SELECT * FROM photos WHERE id=?", (first,)),
                                             db.one(self.conn, "SELECT * FROM photos WHERE id=?", (second,))))
        self.assertEqual(moments.siblings(self.conn, [self.pid]), {self.pid}, "a Drive shoot keeps its moments")

    def test_one_post_never_holds_two_frames_of_one_moment(self):
        sibling = self.photo("fe", "2025:02:14 10:03:00")
        apart = self.photo("fe", "2025:02:14 10:40:00")
        pool = [dict(r) for r in db.rows(self.conn, "SELECT * FROM photos ORDER BY id")]
        picker = content.Picker(pool, "cascade")                   # takes 3
        taken = []
        for row in picker.candidates():
            picker.take(row)
            taken.append(row["id"])
        self.assertEqual(taken, [self.pid, apart], "the sibling frame is passed over, and the pool had no third moment")

    def test_make_draft_leaves_out_a_second_frame_of_a_moment_by_any_road(self):
        sibling = self.photo("fe", "2025:02:14 10:03:00")
        rows = [dict(db.one(self.conn, "SELECT p.*, c.subject, c.convention_name, c.event_kind, c.shot_type FROM photos p "
                                       "JOIN classifications c ON c.photo_id = p.id WHERE p.id=?", (pid,))) for pid in (self.pid, sibling)]
        for r in rows:
            r["credit"] = ""
        from datetime import date
        qid, art, line = content.make_draft(self.ctx(dry=True), date(2026, 10, 13), [(r, self.fetch(r)) for r in rows], "cascade",
                                            want="event", kind_used="event", asked="cascade", track=None)
        self.assertEqual(json.loads(self.row()["photo_ids"]), [self.pid])
        self.assertIn(f"left out photo {sibling} (the same moment as another on this post)", line)

    def test_the_door_turns_back_a_sibling_of_a_frame_that_went_out(self):
        p = mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible())
        p.start()
        self.addCleanup(p.stop)
        add_channels(self.conn, "instagram", "linkedin")
        sibling = self.photo("fe", "2025:02:14 10:04:00")
        self.conn.execute("UPDATE photos SET prominent_logo=0, local_path=? WHERE id IN (?, ?)",
                          (write_render(self.root / "photos", "e1.jpg"), self.pid, sibling))
        old = aired(self.conn, self.pid, ["instagram"])
        renders = {"4:5": [write_render(self.root / "renders", "r-45.jpg")]}
        qid = add_post(self.conn, [sibling], ("instagram",), render_paths=renders)
        publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "draft")
        self.assertIn(f"Photo {self.pid}, a frame of the same moment as one on this post, already went out as post #{old}", row["last_error"])


class TheShoot(Case):
    def test_the_least_recently_used_shoot_leads(self):
        fresh_in_used_folder = self.photo("fe", "2025:02:14 12:00:00", quality=5)
        never_used_folder = self.photo("other", "2025:03:01 09:00:00", quality=3)
        aired(self.conn, self.pid, ["instagram", "linkedin"], days_ago=3)         # folder fe was on a post three days ago
        order = self.candidates()
        self.assertEqual(order[0], never_used_folder, "the shoot no post has had leads, before the stronger photo of the used shoot")
        self.assertEqual(order, [never_used_folder, fresh_in_used_folder])
        self.assertEqual(set(content.shoot_uses(self.conn, ("instagram",))), {"fe"})

    def test_a_post_takes_at_most_two_photos_from_one_shoot_while_others_are_free(self):
        big = [self.photo("big", f"2025:02:14 {10 + k}:00:00") for k in range(5)]
        others = [self.photo(f"f{k}", f"2025:02:15 {10 + k}:00:00") for k in range(4)]
        pool = [dict(r) for r in db.rows(self.conn, "SELECT * FROM photos WHERE folder_id != 'fe' ORDER BY id")]
        picker = content.Picker(pool, "reel")                      # takes 6
        taken = []
        for row in picker.candidates():
            picker.take(row)
            taken.append(row)
        self.assertEqual(len(taken), 6)
        self.assertEqual(sum(1 for r in taken if r["folder_id"] == "big"), 2)
        self.assertEqual(picker.words(), "", "enough shoots were free: nothing to say")

    def test_fewer_shoots_than_the_post_needs_spread_as_evenly_as_they_can(self):
        for k in range(6):
            self.photo("big", f"2025:02:14 {10 + k}:00:00")
        for k in range(2):
            self.photo("small", f"2025:02:15 {10 + k}:00:00")
        pool = [dict(r) for r in db.rows(self.conn, "SELECT * FROM photos WHERE folder_id != 'fe' ORDER BY id")]
        picker = content.Picker(pool, "reel")
        taken = []
        for row in picker.candidates():
            picker.take(row)
            taken.append(row)
        self.assertEqual(len(taken), 6)
        self.assertEqual(sum(1 for r in taken if r["folder_id"] == "big"), 4, "the small shoot has two, so the big one gives four")
        self.assertEqual(picker.words(), "2 shoots free for 6 photos, so up to 4 from one")

    def test_the_daily_draft_says_when_one_shoot_had_to_give_more(self):
        for k in range(3):
            self.photo("fe", f"2025:02:14 {11 + k}:00:00")
        line = content.draft_one(self.ctx(dry=True), self.fetch, now=datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc))   # drafts Thursday: cascade, 3 photos
        self.assertIn("cascade with 3 photo(s)", line)
        self.assertIn("1 shoot free for 3 photos, so up to 3 from one", line)
        ids = json.loads(self.row()["photo_ids"])
        taken = [db.one(self.conn, "SELECT taken_at FROM photos WHERE id=?", (i,))["taken_at"] for i in ids]
        self.assertEqual(len(set(taken)), 3, "three different moments")
