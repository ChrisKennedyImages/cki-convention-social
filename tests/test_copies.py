"""One card per picture, the copies saved as other files included (Chris, 2026-11-02: "And I thought you got rid of the
duplicates and I still see so many").

The same picture sits in Drive as identical files and as other files: a low-res export beside the original, the client's
copies filed into one folder per person. library/copies.link stores the photo that stands for each picture (the largest
file the sorter has looked at); To review shows that one card, a decision on it is on every copy, a post takes it, and a
picture that went out went out whichever of its files was on the post. Frames of one burst stay different pictures."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from convention_social.agents import content, scanner
from convention_social.buffer import payloads
from convention_social.core import auth, config, db, runner
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.drive.api import DriveReader
from convention_social.library import copies, eligibility
from tests._base import IsolatedCase
from tests.fake_drive import FakeDrive

JSON = {"Accept": "application/json"}
SECOND = "2021:04:22 12:04:34"


class Library(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.now = db.utcnow()
        self.n = 0

    def folder(self, fid, name, clearance="not_cleared"):
        db.insert(self.conn, "drive_folders", drive_id=fid, name=name, clearance=clearance, first_seen_at=self.now,
                  last_seen_at=self.now)

    def photo(self, name, w, h, *, folder=None, taken=SECOND, md5=None, sort="vision", trashed=0, clearance="inherit"):
        """A photo row as the inventory writes it, sorted by `sort` (None: not even the folder pass), each its own file
        (its own md5) unless `md5` says otherwise."""
        self.n += 1
        pid = db.insert(self.conn, "photos", drive_id=f"d{self.n}", name=name, folder_id=folder, width=w, height=h, taken_at=taken,
                        md5=md5 or f"bytes-{self.n}", trashed=trashed, clearance=clearance,
                        thumbnail_link="https://drive.example/t=s220", first_seen_at=self.now, last_seen_at=self.now)
        if sort:
            db.insert(self.conn, "classifications", photo_id=pid, method=sort, subject="event", event_kind="business",
                      shot_type="candid", quality=3, possible_minor=0, personal_details="[]", space="exterior", residential=0,
                      empty_room=0, classified_at=self.now)
        return pid

    def picture(self, pid):
        return db.one(self.conn, "SELECT picture FROM photos WHERE id=?", (pid,))["picture"]

    def clearance(self, pid):
        row = db.one(self.conn, "SELECT clearance, clearance_at FROM photos WHERE id=?", (pid,))
        return row["clearance"], row["clearance_at"]


class Matching(Library):
    def test_the_same_file_saved_again_is_one_picture_and_the_largest_stands_for_it(self):
        low = self.photo("Stone_Point-14.jpg", 916, 600)                   # "Low-Res Images" beside the original
        original = self.photo("Stone_Point-14.jpg", 7867, 5151)
        scott = self.photo("1-Texas_2022NICL4065-TEXAS2022.jpg", 5472, 3648, taken="2022:08:16 06:17:11")
        steven = self.photo("1-Texas_2022NICL4065-TEXAS2022.jpg", 5472, 3648, taken="2022:08:16 06:17:11")
        drives_copy = self.photo("Copy of Copy of IMG_0084.JPG", 3000, 2000)
        export = self.photo("IMG_0084.jpg", 6000, 4000)
        download = self.photo("IMG_0084 (1).jpg", 6000, 4000)
        got = copies.link(self.conn)
        self.assertEqual((self.picture(low), self.picture(original)), (original, original), "the largest file")
        self.assertEqual((self.picture(scott), self.picture(steven)), (scott, scott), "the same size: the lowest id")
        self.assertEqual({self.picture(p) for p in (drives_copy, export, download)}, {export},
                         "Drive's Copy of, however often, and a second download are the same file")
        self.assertEqual((got.pictures, got.extra), (3, 4))
        self.assertEqual(got.line(), "copies: 3 pictures in more than one file (4 extra), 7 relinked, 0 given their picture's decision")
        self.assertEqual(copies.link(self.conn).relinked, 0, "a second pass changes nothing")

    def test_frames_of_a_burst_and_other_shapes_are_other_pictures(self):
        alone = [
            self.photo("DSC_6552.jpg", 4912, 7360), self.photo("DSC_6553.jpg", 4912, 7360),       # a burst: numbered frames
            self.photo("20170811_204436(0).jpg", 4032, 3024),                                    # a phone's frames in one second
            self.photo("20170811_204436(1).jpg", 4032, 3024),
            self.photo("DSC_1.jpg", 6000, 4000), self.photo("DSC_1.jpg", 6000, 3375),            # cropped to another shape
            self.photo("CK6_0180.jpg", 8256, 5504), self.photo("CK6_0180.jpg", 7344, 4931),      # cropped, 0.7% off its shape
            self.photo("DSC_2.jpg", 6000, 4000), self.photo("DSC_2.jpg", 4000, 6000),            # turned the other way round
            self.photo("DSC_3.jpg", 6000, 4000), self.photo("DSC_3.jpg", 6000, 4000, taken="2021:04:22 12:04:35"),
            self.photo("DSC_4.jpg", 6000, 4000, taken=None), self.photo("DSC_4.jpg", 6000, 4000, taken=None),
            self.photo("DSC_5 copy.jpg", 6000, 4000), self.photo("DSC_5.jpg", 6000, 4000),       # Finder's " copy" is an edit
        ]
        got = copies.link(self.conn)
        self.assertEqual([self.picture(p) for p in alone], alone, "every one its own picture")
        self.assertEqual(got.pictures, 0)

    def test_identical_files_and_copies_of_copies_are_one_picture(self):
        a = self.photo("A.jpg", 3000, 2000, md5="same")
        b = self.photo("Export.jpg", 3000, 2000, taken="2022:01:01 10:00:00", md5="same")        # a's bytes under another name
        c = self.photo("Export.jpg", 6000, 4000, taken="2022:01:01 10:00:00")                    # b saved again, larger
        twin = self.photo("Twin.jpg", 3000, 2000, taken=None, md5="twin")
        twin2 = self.photo("Twin (renamed).jpg", 3000, 2000, taken=None, md5="twin")
        copies.link(self.conn)
        self.assertEqual({self.picture(p) for p in (a, b, c)}, {c}, "a copy of a copy is a copy")
        self.assertEqual((self.picture(twin), self.picture(twin2)), (twin, twin), "identical files, as since 2026-10-26")

    def test_a_file_the_sorter_never_looked_at_or_gone_from_drive_does_not_stand_for_the_picture(self):
        small = self.photo("IMG_7645.jpg", 2000, 1333)
        big = self.photo("IMG_7645.jpg", 6000, 4000, sort="folder")        # in a folder the sorter never reads
        copies.link(self.conn)
        self.assertEqual(self.picture(big), small, "the card must be sorted to be on To review at all")
        self.conn.execute("UPDATE classifications SET method='vision' WHERE photo_id=?", (big,))
        copies.link(self.conn)
        self.assertEqual((self.picture(small), self.picture(big)), (big, big), "sorted: the largest file stands from the next pass")
        self.conn.execute("UPDATE photos SET trashed=1 WHERE id=?", (big,))
        copies.link(self.conn)
        self.assertEqual((self.picture(small), self.picture(big)), (small, small), "gone from Drive: never the card, still the picture")
        self.assertEqual(copies.every_copy(self.conn, {big}), {big, small}, "a post of the file since removed holds the copy left")


class Decisions(Library):
    def test_a_decision_on_one_copy_is_on_every_copy_and_dont_use_wins(self):
        a = self.photo("CK5_2499.jpg", 7089, 4135, clearance="cleared")
        self.conn.execute("UPDATE photos SET clearance_at='2026-10-11T20:09:30+00:00' WHERE id=?", (a,))
        b = self.photo("CK5_2499.jpg", 7089, 4135)
        c = self.photo("CK5_2499.jpg", 2048, 1195)
        gone = self.photo("CK5_2499.jpg", 7089, 4135, trashed=1)
        undecided = [self.photo("CK5_2500.jpg", 7089, 4135), self.photo("CK5_2500.jpg", 2048, 1195)]
        got = copies.link(self.conn)
        self.assertEqual({self.clearance(p) for p in (a, b, c)}, {("cleared", "2026-10-11T20:09:30+00:00")}, "his Use, when he gave it")
        self.assertEqual(got.decided, 2)
        self.assertEqual(self.clearance(gone), ("inherit", None), "a file gone from Drive takes no decision")
        self.assertEqual({self.clearance(p) for p in undecided}, {("inherit", None)}, "no decision: nothing is made up")
        self.conn.execute("UPDATE photos SET clearance='blocked', clearance_at='2026-11-02T22:48:27+00:00' WHERE id=?", (c,))
        copies.link(self.conn)
        self.assertEqual({self.clearance(p) for p in (a, b, c)}, {("blocked", "2026-11-02T22:48:27+00:00")},
                         "Don't use on any copy wins over a Use on another")


class TheCard(Library):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.folder("low", "Low-Res Images")
        self.folder("orig", "Stone Point Apartments")
        self.low = self.photo("Stone_Point-14.jpg", 916, 600, folder="low")
        self.original = self.photo("Stone_Point-14.jpg", 7867, 5151, folder="orig")
        self.other = self.photo("Stone_Point-15.jpg", 7867, 5151, folder="orig", taken="2021:04:22 13:00:00")
        copies.link(self.conn)

    def listed(self, view="review"):
        dash.prepare_photo_views(self.conn, eligibility.folder_decisions(self.conn))
        return [p["id"] for p in dash.photo_page(self.conn, view, 1, size=100)]

    def test_to_review_shows_one_card_per_picture_the_largest_file(self):
        self.assertEqual(sorted(self.listed()), [self.original, self.other])
        page = self.client.get("/library?view=review").text
        self.assertIn(f'id="p{self.original}"', page)
        self.assertNotIn(f'id="p{self.low}"', page)
        deck = json.loads(self.client.get("/library/swipe").text.split('id="deck-data">', 1)[1].split("</script>", 1)[0])
        self.assertEqual((deck["left"], sorted(c["id"] for c in deck["next"])), (2, [self.original, self.other]))

    def test_a_use_on_the_card_clears_every_copy(self):
        r = self.client.post(f"/library/photo/{self.original}/clearance", data={"state": "cleared"}, headers=JSON)
        self.assertEqual(r.status_code, 200)
        self.assertEqual({self.clearance(p)[0] for p in (self.low, self.original)}, {"cleared"})
        self.assertEqual(self.listed(), [self.other])
        self.assertEqual(self.listed("approved"), [self.original], "one card on Approved too")

    def test_a_swipe_on_the_card_decides_every_copy(self):
        d = self.client.post(f"/library/swipe/{self.original}", data={"state": "blocked", "subject": "event"}, headers=JSON).json()
        self.assertEqual({self.clearance(p)[0] for p in (self.low, self.original)}, {"blocked"})
        self.assertEqual((d["left"], [c["id"] for c in d["next"]]), (1, [self.other]))
        self.assertEqual(self.client.post(f"/library/swipe/{self.low}", data={"state": "cleared"}, headers=JSON).status_code, 409,
                         "a copy behind the card is never on To review")

    def test_never_use_on_the_card_keeps_every_copy_out(self):
        drive_id = db.one(self.conn, "SELECT drive_id FROM photos WHERE id=?", (self.original,))["drive_id"]
        db.insert(self.conn, "do_not_use", kind="photo", value=drive_id, added_at=self.now)
        low = db.one(self.conn, "SELECT * FROM photos WHERE id=?", (self.low,))
        self.assertEqual(eligibility.blocked_by_list(self.conn, low), "another copy of this picture is on the do-not-use list")
        rule = {r["id"] for r in db.rows(self.conn, "SELECT * FROM photos") if eligibility.blocked_by_list(self.conn, r)}
        self.assertEqual(eligibility.do_not_use_photos(self.conn), rule, "the list and the photo-by-photo rule agree")
        self.assertEqual(rule, {self.low, self.original})
        self.assertEqual(self.listed(), [self.other])


class Posts(Library):
    def setUp(self):
        super().setUp()
        for fid in ("low", "orig", "elsewhere"):
            self.folder(fid, fid)
        self.low = self.photo("Stone_Point-14.jpg", 916, 600, folder="low", clearance="cleared")      # his Use, on each file
        self.original = self.photo("Stone_Point-14.jpg", 7867, 5151, folder="orig", clearance="cleared")
        self.other = self.photo("Gala-1.jpg", 6000, 4000, folder="elsewhere", taken="2023:05:01 19:00:00", clearance="cleared")
        copies.link(self.conn)

    def test_a_post_takes_the_largest_file_and_a_copy_that_went_out_holds_them_all(self):
        self.assertEqual(sorted(r["id"] for r in content.candidates(self.conn, "event")), [self.original, self.other],
                         "never the small copy, never two copies of one picture")
        when = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat()
        db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps([self.low]), caption="{}",
                  targets=json.dumps(list(payloads.posting_networks())), status="published", created_at=when, updated_at=when,
                  rule_report=json.dumps({"event": "Stone Point"}))           # a post from before: the small copy went out
        used, _, _ = content.recent_use(self.conn, 30)
        self.assertEqual(used, {self.low, self.original}, "the picture went out, whichever file was on the post")
        self.assertEqual([r["id"] for r in content.candidates(self.conn, "event")], [self.other])


class TheScanner(IsolatedCase):
    def test_the_scanner_links_new_photos_after_the_inventory(self):
        drive = FakeDrive()
        drive.folder("flow", "Low-Res Images")
        drive.folder("forig", "Stone Point Apartments")
        drive.image("lo", "Stone_Point-14.jpg", "flow", w=916, h=600, time=SECOND)
        drive.image("hi", "Stone_Point-14.jpg", "forig", w=7867, h=5151, time=SECOND)
        drive.image("next", "Stone_Point-15.jpg", "forig", w=7867, h=5151, time="2021:04:22 12:05:10")
        conn = db.connect()
        self.addCleanup(conn.close)
        line = scanner.run(runner.Context("scanner", conn, None, config.get_config(), True, 0),
                           reader=DriveReader("tok", conn=conn, transport=drive))
        self.assertIn("copies: 1 picture in more than one file (1 extra)", line)
        ids = {r["drive_id"]: r["id"] for r in db.rows(conn, "SELECT id, drive_id FROM photos")}
        pictures = {r["drive_id"]: r["picture"] for r in db.rows(conn, "SELECT drive_id, picture FROM photos")}
        self.assertEqual(pictures, {"lo": ids["hi"], "hi": ids["hi"], "next": ids["next"]}, "linked at once, the largest standing")


class TheMigration(Library):
    def test_the_migration_fills_what_sql_can_tell(self):
        """Before the first pass: identical files stand behind one of them (in Drive, sorted, the lowest id); every other
        photo stands for itself. Copies saved as other files wait for the pass."""
        unsorted = self.photo("A.jpg", 3000, 2000, md5="same", sort="folder")
        sorted_ = self.photo("Copy of A.jpg", 3000, 2000, md5="same")
        gone = self.photo("A (1).jpg", 3000, 2000, md5="same", trashed=1)
        low = self.photo("Stone_Point-14.jpg", 916, 600)
        original = self.photo("Stone_Point-14.jpg", 7867, 5151)
        self.conn.executescript("DROP INDEX idx_photos_picture; ALTER TABLE photos DROP COLUMN picture;")
        self.conn.executescript(Path(db.MIGRATIONS_DIR, "0096_one_card_per_picture.sql").read_text())
        self.assertEqual([self.picture(p) for p in (unsorted, sorted_, gone, low, original)], [sorted_, sorted_, sorted_, low, original])
