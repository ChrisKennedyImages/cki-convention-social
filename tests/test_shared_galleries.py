"""Chris, 2026-10-14: "Can you pick up shared galleries too on drive? Several have me and my brothers images."
The galleries his brother shares with him are scanned like his own and cleared like his own: nothing in them is
used until he clears a folder or a photo. The fake Drive answers like the real one: a flat listing holds what is
his and what was shared with him directly; what sits inside a shared folder is reached only by asking for it."""
from __future__ import annotations

import os

from fastapi.testclient import TestClient

from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.drive import scan
from convention_social.drive.api import DriveReader
from convention_social.library import eligibility
from tests._base import IsolatedCase
from tests.test_library import library


def shared_library():
    d = library()
    d.shared_folder("gbro", "Otakon 2024 by Mike")                    # his brother's gallery, parent unreadable
    d.folder("gport", "Portraits", "gbro")
    d.image("s1", "M_1.jpg", "gbro")
    d.image("s2", "M_2.jpg", "gport")
    d.image("loose", "one.jpg", None, by="Mike Kennedy")             # a single photo shared on its own
    return d


class Shared(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.drive = shared_library()
        self.reader = DriveReader("tok", conn=self.conn, transport=self.drive)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def folders(self):
        return {r["drive_id"]: r for r in db.rows(self.conn, "SELECT * FROM drive_folders")}

    def photos(self):
        return {r["drive_id"]: r for r in db.rows(self.conn, "SELECT * FROM photos")}

    def asked_children_of(self, fid, calls=None):
        return any(f"'{fid}' in parents" in p.get("q", "") for _, p in (calls if calls is not None else self.drive.calls))

    def test_the_full_pass_walks_a_shared_gallery(self):
        st = scan.full_inventory(self.conn, self.reader)
        self.assertEqual(st.shared_galleries, 1)
        self.assertIn("shared_galleries=1", st.line())
        rows, photos = self.folders(), self.photos()
        self.assertEqual(rows["gbro"]["path"], "Shared with me/Otakon 2024 by Mike")
        self.assertIsNone(rows["gbro"]["parent_id"], "the top of a shared gallery is a top folder of its own")
        self.assertEqual((rows["gport"]["path"], rows["gport"]["parent_id"]), ("Shared with me/Otakon 2024 by Mike/Portraits", "gbro"))
        self.assertEqual((rows["gbro"]["shared_by"], rows["gport"]["shared_by"]), ("Mike Kennedy", "Mike Kennedy"))
        self.assertIsNone(rows["fcon"]["shared_by"], "his own folders carry no sharer")
        self.assertEqual((photos["s1"]["folder_id"], photos["s2"]["folder_id"]), ("gbro", "gport"), "the photos inside the gallery were found")
        self.assertTrue(self.asked_children_of("gbro") and self.asked_children_of("gport"), "each shared folder was asked for its children")
        self.assertEqual((rows["gbro"]["image_count"], rows["gport"]["image_count"]), (1, 1))
        self.assertEqual(rows["fcos"]["path"], "My Drive/Katsucon 2025/Portraits", "his own paths as before")
        self.assertEqual(st.images, 4 + 3)

    def test_shared_photos_are_not_cleared_by_default_and_follow_the_folder_chain(self):
        scan.full_inventory(self.conn, self.reader)
        rows = self.folders()
        self.assertEqual((rows["gbro"]["clearance"], rows["gport"]["clearance"]), ("not_cleared", "not_cleared"))
        s2 = self.photos()["s2"]
        self.assertEqual(eligibility.clearance_of(self.conn, s2), "not_cleared")
        self.assertEqual(eligibility.folder_decisions(self.conn)["gport"], "not_cleared")
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='gbro'")
        self.assertEqual(eligibility.clearance_of(self.conn, s2), "cleared", "clearing the gallery reaches the photos inside its subfolders")
        self.assertEqual(eligibility.folder_decisions(self.conn)["gport"], "cleared")
        self.conn.execute("UPDATE drive_folders SET clearance='excluded' WHERE drive_id='gbro'")
        self.conn.execute("UPDATE photos SET clearance='cleared' WHERE drive_id='s2'")
        self.assertEqual(eligibility.clearance_of(self.conn, self.photos()["s2"]), "excluded", "an excluded gallery keeps its photos out, Use or not")

    def test_a_newly_shared_gallery_lands_on_a_changes_run_and_is_walked_once(self):
        scan.full_inventory(self.conn, self.reader)
        self.drive.shared_folder("gnew", "Katsucon 2026 by Mike")
        self.drive.image("n1", "N_1.jpg", "gnew")
        self.drive.changes = []
        st = scan.incremental(self.conn, self.reader)
        self.assertEqual(st.shared_galleries, 1)
        row = self.folders()["gnew"]
        self.assertEqual((row["path"], row["parent_id"], row["shared_by"]), ("Shared with me/Katsucon 2026 by Mike", None, "Mike Kennedy"))
        self.assertEqual(self.photos()["n1"]["folder_id"], "gnew")
        before = len(self.drive.calls)
        st = scan.incremental(self.conn, self.reader)
        self.assertEqual(st.shared_galleries, 0)
        self.assertFalse(self.asked_children_of("gnew", self.drive.calls[before:]), "a known gallery is not walked again every hour")
        self.assertTrue(any("sharedWithMe" in p.get("q", "") for _, p in self.drive.calls[before:]), "the shares are listed again each run")

    def test_a_photo_added_to_a_known_gallery_arrives_through_the_changes_feed(self):
        scan.full_inventory(self.conn, self.reader)
        self.drive.image("s3", "M_3.jpg", "gport")
        self.drive.changes = [{"fileId": "s3", "file": self.drive.files["s3"]}, {"fileId": "gport", "file": self.drive.folders["gport"]}]
        st = scan.incremental(self.conn, self.reader)
        self.assertEqual((st.changes, st.images, st.shared_galleries), (2, 1, 0))
        self.assertEqual(self.photos()["s3"]["folder_id"], "gport")
        row = self.folders()["gport"]
        self.assertEqual(row["shared_by"], "Mike Kennedy", "a change that says nothing about the sharer keeps the name")
        self.assertEqual(row["path"], "Shared with me/Otakon 2024 by Mike/Portraits")

    def test_a_loose_shared_photo_has_no_folder_row(self):
        scan.full_inventory(self.conn, self.reader)
        self.assertIsNone(self.photos()["loose"]["folder_id"])
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM drive_folders WHERE name='(new folder)'")["n"], 0, "no stub row for a parent nobody can see")
        self.assertEqual(eligibility.clearance_of(self.conn, self.photos()["loose"]), "not_cleared")

    def test_an_unreadable_parent_makes_a_top_folder_and_a_known_parent_keeps_the_chain(self):
        self.drive.shared_folder("gsub", "Selects", parent="gbro")        # shared on its own too, inside the shared gallery
        self.drive.image("s4", "M_4.jpg", "gsub")
        self.drive.shared_folder("gnop", "No parent at all", parent=None)
        self.drive.image("s5", "M_5.jpg", "gnop")
        st = scan.full_inventory(self.conn, self.reader)
        rows = self.folders()
        self.assertEqual(st.shared_galleries, 2, "gbro and gnop are tops; gsub keeps its chain under gbro")
        self.assertEqual((rows["gsub"]["path"], rows["gsub"]["parent_id"]), ("Shared with me/Otakon 2024 by Mike/Selects", "gbro"))
        self.assertEqual((rows["gnop"]["path"], rows["gnop"]["parent_id"]), ("Shared with me/No parent at all", None))
        self.assertEqual((self.photos()["s4"]["folder_id"], self.photos()["s5"]["folder_id"]), ("gsub", "gnop"))
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='gbro'")
        self.assertEqual(eligibility.clearance_of(self.conn, self.photos()["s4"]), "cleared", "clearing the gallery reaches the folder shared on its own inside it")

    def test_a_loose_photo_at_the_top_of_my_drive_gets_no_stub_on_a_changes_run(self):
        scan.full_inventory(self.conn, self.reader)
        self.assertEqual(settings.get(self.conn, scan.ROOT_IDS_KEY), '["rootid"]')
        self.drive.image("top1", "top.jpg", self.drive.root)
        self.drive.changes = [{"fileId": "top1", "file": self.drive.files["top1"]}]
        scan.incremental(self.conn, self.reader)
        self.assertIsNone(self.photos()["top1"]["folder_id"])
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM drive_folders WHERE drive_id='rootid'"), "My Drive itself is never a folder row")

    def test_the_walk_is_gets_only_before_the_lock_and_asks_for_no_address(self):
        seen = []

        def watching(url, params, headers, stream=False):
            seen.append(self.conn.in_transaction)
            return self.drive(url, params, headers, stream=stream)
        reader = DriveReader("tok", conn=self.conn, transport=watching)
        scan.full_inventory(self.conn, reader)
        self.drive.shared_folder("gnew", "Later by Mike")
        self.drive.changes = []
        scan.incremental(self.conn, reader)
        self.assertTrue(seen)
        self.assertNotIn(True, seen, "every read happens with no transaction open")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='drive'")["n"], len(self.drive.calls))
        for url, p in self.drive.calls:
            self.assertNotIn("emailAddress", p.get("fields", ""), "a name is asked for, never an address")
            self.assertNotIn("permissions", url)


class OnThePages(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.drive = shared_library()
        scan.full_inventory(self.conn, DriveReader("tok", conn=self.conn, transport=self.drive))

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_the_folders_folder_and_drive_pages_say_who_shared(self):
        page = self.client.get("/library?view=folders&show=all").text
        self.assertEqual(page.count("shared by Mike Kennedy"), 2, "the gallery and its subfolder, not his own folders")
        self.assertIn("Shared with me/Otakon 2024 by Mike", page)
        page = self.client.get("/library/folder/gbro").text
        self.assertIn("shared by Mike Kennedy; nothing here is used until you approve it", page)
        self.assertNotIn("shared by", self.client.get("/library/folder/fcon").text)
        page = self.client.get("/drive").text
        self.assertIn("1 shared gallery found, from Mike Kennedy", page)
        self.assertIn("Otakon 2024 by Mike", page)

    def test_the_drive_page_says_when_none_were_found(self):
        self.conn.execute("UPDATE drive_folders SET shared_by=NULL")
        self.assertIn("No shared galleries found yet", self.client.get("/drive").text)
