"""The dashboard: fail-closed login, clearance, do-not-use, calendar, approve gates."""
from __future__ import annotations

import json
import os
import re

from fastapi.testclient import TestClient

from convention_social.ai import copy_rules
from convention_social.core import auth, config, db
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.drive import scan
from convention_social.drive.api import DriveReader
from convention_social.library import classify
from tests._base import IsolatedCase
from tests.fake_drive import FakeDrive


class Dashboard(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def signed_in(self):
        self.client.cookies.set(COOKIE, make_token("chris"))
        return self.client

    def seed_library(self):
        d = FakeDrive()
        d.folder("fcon", "Katsucon 2025")
        d.image("p1", "a.jpg", "fcon")
        scan.full_inventory(self.conn, DriveReader("t", conn=self.conn, transport=d))
        classify.folder_pass(self.conn)
        self.conn.execute("UPDATE classifications SET method='ollama', subject='event', possible_minor=0, personal_details='[]'")
        return db.one(self.conn, "SELECT id FROM photos")["id"]

    def final_check(self, pid, minor=0):
        db.insert(self.conn, "final_checks", photo_id=pid, possible_minor=minor, personal_details="[]",
                  model="claude-opus-5", checked_at=db.utcnow())

    def draft(self, caption="Green room before the keynote. Request a quote for your event.", photo_ids=(), convention_id=None):
        now = db.utcnow()
        return db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps(list(photo_ids)), convention_id=convention_id,
                         targets=json.dumps(["instagram"]), caption=json.dumps({"instagram": caption, "facebook": caption, "pinterest": caption}),
                         created_at=now, updated_at=now)

    def test_no_password_means_503(self):
        os.environ.pop("DASHBOARD_PASSWORD_HASH")
        config.reset()
        self.assertEqual(TestClient(create_app()).get("/login").status_code, 503)

    def test_pages_need_sign_in(self):
        r = self.client.get("/library", follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertEqual(self.client.post("/donotuse/add", data={"kind": "handle", "value": "@x"}).status_code, 401)

    def test_login(self):
        bad = self.client.post("/login", data={"password": "nope"}, follow_redirects=False)
        self.assertIn("bad=1", bad.headers["location"])
        good = self.client.post("/login", data={"password": "correct horse", "next": "//evil.example"}, follow_redirects=False)
        self.assertEqual(good.headers["location"], "/")
        self.assertIn(COOKIE, good.cookies)

    def test_every_page_renders(self):
        c = self.signed_in()
        self.seed_library()
        qid = self.draft()
        for path in ("/", "/library", "/library?show=all", "/library/folder/fcon", "/donotuse", "/calendar", "/drive",
                     "/agents", "/keys", f"/queue/{qid}"):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("<main>", r.text, path)

    def test_folder_clearance_and_photo_block(self):
        c = self.signed_in()
        pid = self.seed_library()
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM drive_folders WHERE drive_id='fcon'")["clearance"], "cleared")
        self.assertIn("ready to pick", c.get("/library/folder/fcon").text)
        c.post(f"/library/photo/{pid}/clearance", data={"state": "blocked"})
        self.assertIn("Chris blocked this photo", c.get("/library/folder/fcon").text)
        self.assertEqual(c.post("/library/folder/fcon/clearance", data={"state": "weird"}).status_code, 400)

    def test_approve_refuses_rule_break_and_ineligible_photo(self):
        c = self.signed_in()
        pid = self.seed_library()
        # Chris, 2026-10-12: a caption that breaks a rule is rewritten by the suite, never refused back to him
        q1 = self.draft("Coverage from $500 a day.")
        r = c.post(f"/queue/{q1}/approve", follow_redirects=False)
        self.assertIn("msg=approved", r.headers["location"])
        caption = json.loads(db.one(self.conn, "SELECT caption FROM content_queue WHERE id=?", (q1,))["caption"])["instagram"]
        self.assertNotIn("$500", caption)
        self.assertTrue(copy_rules.check(caption, social=True).ok, caption)
        q2 = self.draft(photo_ids=[pid])
        self.assertIn("msg=ineligible", c.post(f"/queue/{q2}/approve", follow_redirects=False).headers["location"])
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        # cleared and sorted, but Claude has not given it the final check: still refused
        self.assertIn("msg=ineligible", c.post(f"/queue/{q2}/approve", follow_redirects=False).headers["location"])
        self.final_check(pid)
        self.assertIn("msg=approved", c.post(f"/queue/{q2}/approve", follow_redirects=False).headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q2,))["status"], "approved")

    def test_official_claim_needs_the_calendar_flag(self):
        c = self.signed_in()
        c.post("/calendar/save", data={"name": "Big Con", "kind": "fan", "attending": "on"})
        cid = db.one(self.conn, "SELECT id, official FROM conventions")
        self.assertEqual(cid["official"], 0)
        q = self.draft("Proud to be the official photographer here.", convention_id=cid["id"])
        self.assertIn("msg=approved", c.post(f"/queue/{q}/approve", follow_redirects=False).headers["location"])
        caption = json.loads(db.one(self.conn, "SELECT caption FROM content_queue WHERE id=?", (q,))["caption"])["instagram"]
        self.assertNotIn("official", caption.lower(), "without the flag the claim is rewritten away, never posted")
        c.post("/calendar/save", data={"id": cid["id"], "name": "Big Con", "kind": "business", "official": "on"})
        q2 = self.draft("Proud to be the official photographer here.", convention_id=cid["id"])
        self.assertIn("msg=approved", c.post(f"/queue/{q2}/approve", follow_redirects=False).headers["location"])
        caption = json.loads(db.one(self.conn, "SELECT caption FROM content_queue WHERE id=?", (q2,))["caption"])["instagram"]
        self.assertIn("official", caption.lower(), "with the flag the claim stands as written")

    def test_do_not_use_pulls_an_approved_post_back(self):
        c = self.signed_in()
        pid = self.seed_library()
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        self.final_check(pid)
        q = self.draft(photo_ids=[pid])
        c.post(f"/queue/{q}/approve")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q,))["status"], "approved")
        c.post("/donotuse/add", data={"kind": "photo", "value": "https://drive.google.com/file/d/p1/view"})
        self.assertEqual(db.one(self.conn, "SELECT value FROM do_not_use")["value"], "p1")
        row = db.one(self.conn, "SELECT status, last_error FROM content_queue WHERE id=?", (q,))
        self.assertEqual(row["status"], "draft")
        self.assertIn("do-not-use", row["last_error"])

    def test_keys_page_writes_env_and_never_shows_secrets(self):
        c = self.signed_in()
        c.post("/keys", data={"ANTHROPIC_API_KEY": "sk-secret-value", "BRAND_NAME": "New Name",
                              "CREDITS_SHEET_ID": "https://docs.google.com/spreadsheets/d/sheet123/edit"})
        config.reset()
        self.assertEqual(config.getenv("BRAND_NAME"), "New Name")
        self.assertEqual(config.getenv("CREDITS_SHEET_ID"), "sheet123")
        page = c.get("/keys").text
        self.assertNotIn("sk-secret-value", page)
        self.assertIn("New Name", page)

    def test_library_never_opens_empty_when_folders_exist(self):
        d = FakeDrive()
        d.folder("fmisc", "Phone dump")
        d.image("m1", "IMG_1.jpg", "fmisc")
        scan.full_inventory(self.conn, DriveReader("t", conn=self.conn, transport=d))
        page = self.signed_in().get("/library?view=folders").text
        self.assertIn("Phone dump", page)
        self.assertIn("No folder has been recognised as event work yet", page)

    def test_library_report_and_sheets_are_on_the_dashboard(self):
        renders = config.get_config().data_root / "renders"
        renders.mkdir(parents=True, exist_ok=True)
        (renders / "library-report-20261010.html").write_text("<p>old</p>")
        (renders / "library-report-20261011.html").write_text("<p>new report</p>")
        (renders / "contact-sheet-20261011.jpg").write_bytes(b"\xff\xd8jpeg")
        (renders / "building-sheet-20261011.jpg").write_bytes(b"\xff\xd8jpeg")
        (renders / "notes.txt").write_text("not for the web")
        page = self.signed_in().get("/library?view=design").text
        for name in ("library-report-20261011.html", "contact-sheet-20261011.jpg", "building-sheet-20261011.jpg"):
            self.assertIn(f"/library/renders/{name}", page)
        r = self.client.get("/library/report", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/library/renders/library-report-20261011.html")
        got = self.client.get("/library/renders/library-report-20261011.html")
        self.assertEqual(got.status_code, 200)
        self.assertIn("new report", got.text)
        self.assertEqual(self.client.get("/library/renders/contact-sheet-20261011.jpg").headers["content-type"], "image/jpeg")
        for bad in ("notes.txt", "contact-sheet-2026.jpg", "..%2F..%2F.env", "library-report-20261011.html.bak"):
            self.assertEqual(self.client.get(f"/library/renders/{bad}").status_code, 404, bad)
        anon = TestClient(create_app())
        self.assertNotEqual(anon.get("/library/renders/library-report-20261011.html", follow_redirects=False).status_code, 200)

    def test_run_now_starts_one_agent_run(self):
        from unittest import mock
        import sys
        from convention_social.dashboard import app as app_module
        with mock.patch.object(app_module.subprocess, "Popen") as popen:
            r = self.signed_in().post("/agents/scanner/run", follow_redirects=False)
            self.assertEqual(r.status_code, 303)
            self.assertIn("scanner+started", r.headers["location"])
            args = popen.call_args[0][0]
            self.assertEqual(args, [sys.executable, "-m", "convention_social.cli", "run", "scanner"])
            for bad in ("dashboard", "art_director", "nonsense"):
                self.assertEqual(self.client.post(f"/agents/{bad}/run").status_code, 404, bad)
            self.assertEqual(popen.call_count, 1)
            self.assertIn("Run now", self.client.get("/agents").text)
            anon = TestClient(create_app())
            self.assertNotEqual(anon.post("/agents/scanner/run", follow_redirects=False).status_code, 303)
            self.assertEqual(popen.call_count, 1)

    def test_the_dashboard_records_its_pid_for_the_updater(self):
        from unittest import mock
        from convention_social import cli
        with mock.patch("uvicorn.run") as served:
            cli.main(["dashboard"])
        served.assert_called_once()
        pid_file = config.get_config().locks_dir / "dashboard.pid"
        self.assertEqual(pid_file.read_text(), str(os.getpid()))

    def test_each_photo_has_use_and_dont_use_and_comes_back_to_itself(self):
        """Chris, 2026-10-11: "It dosent let me deny any images". Block worked, but every tap reloaded
        the folder at the top, so in a folder of hundreds the change was out of sight."""
        pid = self.seed_library()
        fid = db.one(self.conn, "SELECT folder_id FROM photos WHERE id=?", (pid,))["folder_id"]
        c = self.signed_in()
        page = c.get(f"/library/folder/{fid}").text
        self.assertIn(f'id="p{pid}"', page)
        self.assertIn(">Use<", page)
        self.assertIn("Don&#39;t use", page)
        r = c.post(f"/library/photo/{pid}/clearance", data={"state": "blocked", "back": f"/library/folder/{fid}#p{pid}"},
                   follow_redirects=False)
        self.assertEqual(r.headers["location"], f"/library/folder/{fid}#p{pid}")
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM photos WHERE id=?", (pid,))["clearance"], "blocked")
        page = c.get(f"/library/folder/{fid}").text
        self.assertIn('class="card off"', page)
        self.assertIn("Chris blocked this photo", page)
        self.assertIn(">Unblock<", page)
        c.post(f"/library/photo/{pid}/clearance", data={"state": "cleared", "back": f"/library/folder/{fid}#p{pid}"})
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM photos WHERE id=?", (pid,))["clearance"], "cleared")
        page = c.get(f"/library/folder/{fid}").text
        self.assertIn(">Undo use<", page)
        self.assertNotIn('class="card off"', page)

    def test_dismiss_all_of_one_kind_leaves_the_others(self):
        """Chris, 2026-10-11: "the terminal command to dismiss all the drive errors". 23 stale Drive
        sign-in errors sat on the Agents page with one Dismiss button each."""
        from convention_social.core import runner
        for _ in range(3):
            runner.record_error(self.conn, "scanner", "drive_auth", "Google Drive is not signed in yet.")
        runner.record_error(self.conn, "seo", "site_check", "the sitemap did not answer")
        c = self.signed_in()
        page = c.get("/agents").text
        self.assertIn("Dismiss all 3 drive auth", page)
        self.assertIn("Dismiss all 1 site check", page)
        r = c.post("/errors/ack-kind", data={"kind": "drive_auth"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("3+drive+auth+errors+dismissed", r.headers["location"])
        open_kinds = [row["kind"] for row in db.rows(self.conn, "SELECT kind FROM errors WHERE alerted=0")]
        self.assertEqual(open_kinds, ["site_check"])
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors")["n"], 4)       # dismissed, never deleted

    def test_the_errors_page_lists_open_errors_and_dismisses_back_to_itself(self):
        """More listed /errors with no page behind it."""
        c = self.signed_in()
        eid = db.insert(self.conn, "errors", ts=db.utcnow(), agent="content", kind="no_draft",
                        message="No post was drafted for Tuesday", alerted=0)
        r = c.get("/errors")
        self.assertEqual(r.status_code, 200)
        self.assertIn("No post was drafted for Tuesday", r.text)
        self.assertIn("Dismiss all 1 no draft", r.text)
        r = c.post(f"/errors/{eid}/ack", data={"back": "/errors"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/errors")
        self.assertIn("None.", c.get("/errors").text)
        self.assertIn('href="/errors"', c.get("/more").text)
        r = c.post(f"/errors/{eid}/ack", data={"back": "https://evil.example/"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/agents", "only our own pages")

    def test_photos_review_then_approved_and_only_approved_counts(self):
        """Chris, 2026-10-11: "I only want to choose what I approve" and "I am unable to go back to the main
        library page where I can hit clear". To review lists the undecided photos with Use; Approved lists
        what he chose; a folder page links back and clears the whole folder in place."""
        pid = self.seed_library()
        fid = db.one(self.conn, "SELECT folder_id FROM photos WHERE id=?", (pid,))["folder_id"]
        c = self.signed_in()
        review = c.get("/library").text
        self.assertIn(f'id="p{pid}"', review)
        self.assertIn(">Use<", review)
        self.assertIn('<a href="/library" class="on">Photos</a>', review)
        self.assertNotIn(f'id="p{pid}"', c.get("/library?view=approved").text)
        r = c.post(f"/library/photo/{pid}/clearance", data={"state": "cleared", "back": f"/library?view=review&page=1#p{pid}"},
                   follow_redirects=False)
        self.assertEqual(r.headers["location"], f"/library?view=review&page=1#p{pid}")
        self.assertNotIn(f'id="p{pid}"', c.get("/library").text)
        approved = c.get("/library?view=approved").text
        self.assertIn(f'id="p{pid}"', approved)
        self.assertIn(">Undo<", approved)
        folder = c.get(f"/library/folder/{fid}").text
        self.assertIn(f'href="/library?view=folders#f-{fid}"', folder)
        self.assertIn("Approve all 1 photos", folder)
        self.assertIn("not only the ones you picked", folder)
        c.post(f"/library/folder/{fid}/clearance", data={"state": "cleared", "back": f"/library/folder/{fid}"})
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM drive_folders WHERE drive_id=?", (fid,))["clearance"], "cleared")
        r = c.post(f"/library/photo/{pid}/clearance", data={"state": "inherit", "back": "//elsewhere.example/x"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/library")

    def test_four_tabs_and_every_page_one_tap_from_its_section(self):
        c = self.signed_in()
        for path, tab, chip in (("/", "Today", None), ("/library?view=folders", "Photos", "Folders"), ("/calendar", "Bookings", "Calendar"),
                                ("/agents", "More", "Agents"), ("/keys", "More", "Keys"), ("/more", "More", None)):
            page = c.get(path).text
            tabs = re.findall(r'<nav>(.*?)</nav>', page, flags=re.S)[0]
            self.assertEqual(re.findall(r">([A-Za-z]+)</a>", tabs), ["Today", "Photos", "Bookings", "More"], path)
            self.assertIn(f'class="on">{tab}</a>', tabs, path)
            if chip:
                self.assertRegex(page, rf'<div class="chips">.*class="on">{chip}</a>', path)

    def test_everything_live_in_one_tap_and_back(self):
        """Chris, 2026-10-11: "Everything should be live now too so we can see the damn thing work!" """
        from convention_social.core import settings
        c = self.signed_in()
        self.assertIn("Switch everything live", c.get("/agents").text)
        r = c.post("/agents/all/dry-run", data={"state": "off"}, follow_redirects=False)
        self.assertIn("now+LIVE", r.headers["location"])
        self.assertTrue(all(not settings.dry_run(self.conn, a) for a in settings.AGENTS_WITH_DRY_RUN))
        page = c.get("/agents").text
        self.assertIn(f"{len(settings.AGENTS_WITH_DRY_RUN)} of {len(settings.AGENTS_WITH_DRY_RUN)} agents live", page)
        self.assertNotIn("Switch everything live", page)
        c.post("/agents/all/dry-run", data={"state": "on"})
        self.assertTrue(all(settings.dry_run(self.conn, a) for a in settings.AGENTS_WITH_DRY_RUN))

    def test_healthz_says_which_commit_this_dashboard_runs_without_a_login(self):
        import subprocess
        head = subprocess.run(["git", "-C", str(config.REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertTrue(head)
        r = self.client.get("/healthz")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True, "commit": head}))
