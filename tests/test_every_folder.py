"""Chris, 2026-11-06: "Never go to my phone photos backup", "Every folder should have been sorted as discussed (not phone
folders). And duplicates stacked as one", "flatten the duplicates that are already approved to one photo", and "Let's do
50 a page for 'pick the keepers'".

The phone backup (Drive's "Google Photos" folder at the top of My Drive) is never inventoried, in a full pass or a
changes pass, and the rows an earlier pass made of it go. Every other folder is sorted, whatever its name says, and the
paid sorter stops with a tenth of the monthly cap left for the drafts. The same frame saved under another name (its camera
time changed or stripped on export) is one card when the pictures match. Pick the keepers shows 50 a page."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw

from convention_social.ai import spend
from convention_social.core import config, db, settings
from convention_social.dashboard import app as dash
from convention_social.drive import scan
from convention_social.drive.api import DriveReader
from convention_social.library import classify, copies
from tests._base import IsolatedCase
from tests.fake_drive import FakeDrive

MIGRATION = Path(__file__).resolve().parents[1] / "convention_social" / "core" / "migrations" / "0098_never_the_phone_backup.sql"


def picture(seed: int, size=(320, 213)) -> bytes:
    """A JPEG with its own pattern: the same seed is the same picture at any size, another seed another picture."""
    im = Image.new("RGB", (64, 43), (40, 40, 40))
    d = ImageDraw.Draw(im)
    for i in range(6):
        x = (seed * 7 + i * 13) % 58
        y = (seed * 3 + i * 11) % 37
        d.rectangle((x, y, x + 6 + i, y + 5), fill=(200 - i * 20, 90 + seed % 100, 60 + i * 25))
    buf = io.BytesIO()
    im.resize(size).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class PhoneBackup(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.d = FakeDrive()
        self.d.folder("gp", "Google Photos")
        self.d.folder("gp17", "2017", "gp")
        self.d.folder("gp1702", "02", "gp17")
        self.d.image("phone1", "IMG_20170203_101010.jpg", "gp1702")
        self.d.image("phone2", "IMG_20170204.jpg", "gp")
        self.d.folder("work", "Event photography")
        self.d.folder("gpwork", "Google Photos", "work")          # a folder of work that happens to share the name
        self.d.image("w1", "DSC_0001.jpg", "work")
        self.d.image("w2", "DSC_0002.jpg", "gpwork")
        self.reader = DriveReader("tok", conn=self.conn, transport=self.d)

    def ids(self, table="photos", col="drive_id"):
        return {r[col] for r in db.rows(self.conn, f"SELECT {col} FROM {table}")}

    def test_a_full_pass_never_lists_the_backup(self):
        stats = scan.full_inventory(self.conn, self.reader)
        self.assertEqual(self.ids(), {"w1", "w2"})
        self.assertFalse({"gp", "gp17", "gp1702"} & self.ids("drive_folders"))
        self.assertEqual(stats.phone_backup, 2)
        self.assertEqual(scan.never_read(self.conn), {"gp", "gp17", "gp1702"})

    def test_a_changes_pass_passes_over_the_backup_and_a_new_folder_in_it(self):
        scan.full_inventory(self.conn, self.reader)
        self.d.folder("gpnew", "03", "gp17")
        self.d.image("phone3", "IMG_3.jpg", "gpnew")
        self.d.image("phone4", "IMG_4.jpg", "gp1702")
        self.d.image("w3", "DSC_0003.jpg", "work")
        self.d.changes = [{"fileId": fid, "file": self.d.folders.get(fid) or self.d.files[fid]}
                          for fid in ("gpnew", "phone3", "phone4", "w3")]
        stats = scan.incremental(self.conn, self.reader)
        self.assertEqual(self.ids(), {"w1", "w2", "w3"})
        self.assertNotIn("gpnew", self.ids("drive_folders"))
        self.assertIn("gpnew", scan.never_read(self.conn))
        self.assertEqual(stats.phone_backup, 2)

    def test_the_migration_removes_what_an_earlier_pass_made_of_the_backup(self):
        now = db.utcnow()
        for fid, parent, path in (("gp", None, "My Drive/Google Photos"), ("gp17", "gp", "My Drive/Google Photos/2017"),
                                  ("gp1702", "gp17", None), ("work", None, "My Drive/Event photography")):
            db.insert(self.conn, "drive_folders", drive_id=fid, name=fid, parent_id=parent, path=path, first_seen_at=now,
                      last_seen_at=now)
        ids = {}
        for did, folder in (("phone1", "gp1702"), ("phone2", "gp"), ("w1", "work")):
            ids[did] = db.insert(self.conn, "photos", drive_id=did, name=did, folder_id=folder, first_seen_at=now,
                                 last_seen_at=now, md5="same" if did != "phone2" else "other")
            db.insert(self.conn, "classifications", photo_id=ids[did], method="folder", classified_at=now)
        self.conn.execute("UPDATE photos SET picture=? WHERE drive_id IN ('phone1', 'w1')", (ids["phone1"],))
        self.conn.executescript(MIGRATION.read_text())
        self.assertEqual(self.ids(), {"w1"})
        self.assertEqual(self.ids("drive_folders"), {"work"})
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM classifications")["n"], 1)
        self.assertIsNone(db.one(self.conn, "SELECT picture FROM photos WHERE drive_id='w1'")["picture"],
                          "a work copy the backup file stood for stands for itself again")
        self.assertEqual(set(json.loads(settings.get(self.conn, scan.NEVER_READ_KEY))), {"gp", "gp17", "gp1702"})


class TheSortersReserve(IsolatedCase):
    """Sorting every folder costs more than was left of the month's cap: the paid sorter stops with a tenth of the cap
    left, so the drafts and captions keep running."""

    class PaidSorter:
        method, model = "vision", "claude-opus-5"

        def __init__(self):
            self.calls = 0

        def paid(self):
            return True

        def classify(self, thumb, hint):
            self.calls += 1
            return {"subject": "event", "event_kind": "business", "shot_type": "candid", "quality": 3, "sharp": True,
                    "light": 3, "moment": 3, "people_count": 2, "possible_minor": False, "personal_details": [],
                    "summary": "People talking."}

    def setUp(self):
        super().setUp()
        os.environ["AI_MONTHLY_CAP_USD"] = "150"
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        d = FakeDrive()
        d.folder("f", "Event photography")
        for i in range(3):
            d.image(f"p{i}", f"DSC_000{i}.jpg", "f", time=f"2024:03:02 10:00:0{i}")
        self.reader = DriveReader("tok", conn=self.conn, transport=d)
        scan.full_inventory(self.conn, self.reader)
        classify.folder_pass(self.conn)

    def spent(self, usd):
        db.insert(self.conn, "api_usage", ts=db.utcnow(), provider="anthropic", agent="content", units=1, unit_kind="tokens",
                  cost_usd=usd, detail="test")

    def test_it_sorts_while_more_than_a_tenth_of_the_cap_is_left(self):
        self.spent(100)
        sorter = self.PaidSorter()
        st = classify.sort_pass(self.conn, self.reader.thumbnail_for, sorter=sorter)
        self.assertEqual((st.done, sorter.calls), (3, 3))

    def test_it_stops_with_a_tenth_of_the_cap_left(self):
        self.spent(136)
        self.assertEqual(classify.sort_reserve(), 15.0)
        sorter = self.PaidSorter()
        st = classify.sort_pass(self.conn, self.reader.thumbnail_for, sorter=sorter)
        self.assertEqual((st.done, sorter.calls), (0, 0))
        self.assertIn("$15.00 of the monthly AI cap left for drafts and captions", st.stopped)
        self.assertFalse(spend.cap_reached(self.conn), "the drafts still have the rest of the cap")


class TheSortingBudget(TheSortersReserve):
    """Chris, 2026-11-06, with $36.64 of the cap left until it resets: Nic's and the shared galleries first, then up to $20,
    "and then until the 19th"."""

    def tearDown(self):
        os.environ.pop("CLASSIFY_BUDGET", None)
        config.reset()
        super().tearDown()

    def budget(self, value):
        os.environ["CLASSIFY_BUDGET"] = value
        config.reset()

    def sorter_spent(self, usd, ts="2026-11-07T10:00:00+00:00"):
        db.insert(self.conn, "api_usage", ts=ts, provider="anthropic", agent="scanner", units=1, unit_kind="tokens",
                  cost_usd=usd, detail="claude-opus-5 classify")

    def test_inside_its_days_the_sorter_stops_once_the_amount_is_spent(self):
        from datetime import date
        self.budget("20 from 2026-11-06 until 2026-11-19")
        self.sorter_spent(12)
        self.spent(30)                                   # the drafts' own spend does not count against the sorting
        self.assertIsNone(classify.budget_stop(self.conn, date(2026, 11, 8)))
        self.sorter_spent(8.5)
        why = classify.budget_stop(self.conn, date(2026, 11, 8))
        self.assertIn("the $20 for sorting from 2026-11-06 is spent ($20.50); sorting goes on 2026-11-19", why)
        self.assertIsNone(classify.budget_stop(self.conn, date(2026, 11, 19)), "from the 19th the limit is gone")
        self.assertIsNone(classify.budget_stop(self.conn, date(2026, 11, 5)))

    def test_the_pass_says_why_it_stopped(self):
        today = __import__("datetime").date.today().isoformat()
        self.budget(f"1 from {today} until 2099-01-01")
        self.sorter_spent(1, ts=db.utcnow())
        sorter = self.PaidSorter()
        st = classify.sort_pass(self.conn, self.reader.thumbnail_for, sorter=sorter)
        self.assertEqual((st.done, sorter.calls), (0, 0))
        self.assertIn("sorting goes on 2099-01-01", st.stopped)

    def test_a_value_it_cannot_read_stops_the_sorting(self):
        self.budget("twenty dollars please")
        self.assertIn("CLASSIFY_BUDGET is not readable", classify.budget_stop(self.conn))
        sorter = self.PaidSorter()
        self.assertEqual(classify.sort_pass(self.conn, self.reader.thumbnail_for, sorter=sorter).done, 0)

    def test_shared_galleries_are_sorted_first(self):
        now = db.utcnow()
        db.insert(self.conn, "drive_folders", drive_id="nic", name="Event photography", shared_by="Nic Kennedy",
                  first_seen_at=now, last_seen_at=now)
        pid = db.insert(self.conn, "photos", drive_id="n1", name="DSC_9.jpg", folder_id="nic", taken_at="2010:01:01 10:00:00",
                        thumbnail_link="https://drive.example/t", first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="folder", classified_at=now)
        self.assertEqual(classify.queue(self.conn, 1)[0]["id"], pid, "the oldest photo, but in Nic's gallery")


class CopiesUnderOtherNames(IsolatedCase):
    """The same frame saved under other names: LOR_1573.jpg, LOR_1573-edit.jpg, 1-Texas_2022LOR_1573-TEXAS2022.jpg,
    with the camera time changed or stripped on export, were four cards (2026-11-06)."""

    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.now = db.utcnow()
        self.pictures: dict[str, bytes] = {}
        self.fetched: list[str] = []

    def photo(self, name, seed, w=5148, h=2809, taken=None, clearance="inherit"):
        did = f"d{len(self.pictures)}"
        self.pictures[did] = picture(seed)
        pid = db.insert(self.conn, "photos", drive_id=did, name=name, width=w, height=h, taken_at=taken, md5=f"m-{did}",
                        clearance=clearance, thumbnail_link="https://drive.example/t", first_seen_at=self.now,
                        last_seen_at=self.now)
        db.insert(self.conn, "classifications", photo_id=pid, method="vision", subject="event", event_kind="business",
                  shot_type="candid", quality=3, possible_minor=0, personal_details="[]", classified_at=self.now)
        return pid

    def fetch(self, drive_id):
        self.fetched.append(drive_id)
        return self.pictures[drive_id]

    def link(self):
        copies.hash_pictures(self.conn, self.fetch)
        copies.link(self.conn)
        return {r["id"]: r["picture"] for r in db.rows(self.conn, "SELECT id, picture FROM photos")}

    def test_frame_numbers_are_read_from_every_kind_of_export_name(self):
        for name, frames in (("LOR_1573.jpg", {"lor1573"}), ("LOR_1573-edit.jpg", {"lor1573"}),
                             ("1-Texas_2022LOR_1573-TEXAS2022.jpg", {"lor1573"}),
                             ("1-Texas_2022NICL4172-TEXAS2022.jpg", {"nicl4172"}), ("NICL5707-2.jpg", {"nicl5707"}),
                             ("_DSC2420.JPG", {"dsc2420"}), ("CK1_5613.JPG", {"ck15613"}),
                             ("1-Texas_2022cpac2022texas-38-TEXAS2022.jpg", set()), ("20170811_204436(1).jpg", set())):
            self.assertEqual(copies.frame_numbers(name), frames, name)

    def test_one_frame_under_four_names_is_one_card(self):
        ids = [self.photo("LOR_1573.jpg", 5), self.photo("LOR_1573-TEXAS2022.jpg", 5),
               self.photo("LOR_1573-edit.jpg", 5, taken="2022:08:16 02:09:20"),
               self.photo("1-Texas_2022LOR_1573-TEXAS2022.jpg", 5, taken="2022:08:16 06:26:41")]
        pictures = self.link()
        self.assertEqual(len({pictures[i] for i in ids}), 1)

    def test_a_low_res_export_of_the_frame_is_the_same_card(self):
        big, small = self.photo("NICL5707-TEXAS2022.jpg", 9, 5472, 3648), self.photo("NICL5707-2.jpg", 9, 547, 365)
        pictures = self.link()
        self.assertEqual(pictures[big], pictures[small])
        self.assertEqual(pictures[small], big, "the largest file stands for the picture")

    def test_two_shoots_that_reuse_a_frame_number_stay_apart(self):
        a, b = self.photo("IMG_0053.jpg", 11, 5472, 3648), self.photo("IMG_0053.jpg", 47, 5472, 3648)
        pictures = self.link()
        self.assertNotEqual(pictures[a], pictures[b])

    def test_burst_frames_stay_their_own_cards(self):
        """2026-11-03, on two burst frames side by side: "Those are fine"."""
        a, b = self.photo("_DSC2419.JPG", 3, 7360, 4912), self.photo("_DSC2420.JPG", 3, 7360, 4912)
        pictures = self.link()
        self.assertNotEqual(pictures[a], pictures[b])
        self.assertEqual(self.fetched, [], "no frame number in common: nothing to compare")

    def test_a_crop_is_another_picture(self):
        a, b = self.photo("NICL4172.jpg", 13, 5110, 3407), self.photo("NICL4172-crop.jpg", 13, 4612, 3419)
        pictures = self.link()
        self.assertNotEqual(pictures[a], pictures[b])

    def test_an_unreadable_preview_joins_nothing(self):
        a, b = self.photo("LOR_1907.jpg", 21), self.photo("LOR_1907-TEXAS2022.jpg", 21)
        self.pictures[db.one(self.conn, "SELECT drive_id FROM photos WHERE id=?", (b,))["drive_id"]] = b"not a picture"
        pictures = self.link()
        self.assertNotEqual(pictures[a], pictures[b])

    def test_a_preview_is_read_once(self):
        self.photo("LOR_1584.jpg", 31), self.photo("LOR_1584-TEXAS2022.jpg", 31)
        self.link()
        self.link()
        self.assertEqual(len(self.fetched), 2)

    def test_copies_he_approved_one_by_one_flatten_to_one_card_on_approved(self):
        """2026-11-06: "flatten the duplicates that are already approved to one photo"."""
        ids = [self.photo("LOR_1622.jpg", 41, 3069, 4352, clearance="cleared"),
               self.photo("LOR_1622-TEXAS2022.jpg", 41, 3069, 4352, clearance="cleared"),
               self.photo("1-Texas_2022LOR_1622-TEXAS2022.jpg", 41, 3069, 4352)]
        self.link()
        dash.prepare_photo_views(self.conn, {})
        shown = [p["id"] for p in dash.photo_page(self.conn, "approved", 1, size=50)]
        self.assertEqual(len(shown), 1)
        self.assertEqual({r["clearance"] for r in db.rows(self.conn, "SELECT clearance FROM photos")}, {"cleared"},
                         "his Use on a copy is on every copy")
        self.assertIn(shown[0], ids)


class FiftyAPage(IsolatedCase):
    def test_pick_the_keepers_shows_fifty_a_page(self):
        """2026-11-06: "why 12 a page? Let's do 50 a page for 'pick the keepers'"."""
        self.assertEqual(dash.KEEPERS_PAGE, 50)
