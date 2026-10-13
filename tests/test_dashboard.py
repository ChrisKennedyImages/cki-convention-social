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

    def popen(self):
        """The content agent is started as its own process (core/runner.start_agent); here it is only counted."""
        from unittest import mock
        from convention_social.core import runner as runner_module
        p = mock.patch.object(runner_module.subprocess, "Popen")
        self.addCleanup(p.stop)
        return p.start()

    def test_do_not_use_sets_the_post_aside_and_drafts_again(self):
        """2026-10-13: a do-not-use entry used to send the post back to drafts and leave it there; now the
        post is set aside with the reason and the day is drafted again at once."""
        c = self.signed_in()
        popen = self.popen()
        pid = self.seed_library()
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        self.final_check(pid)
        q = self.draft(photo_ids=[pid])
        c.post(f"/queue/{q}/approve")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q,))["status"], "approved")
        c.post("/donotuse/add", data={"kind": "photo", "value": "https://drive.google.com/file/d/p1/view"})
        self.assertEqual(db.one(self.conn, "SELECT value FROM do_not_use")["value"], "p1")
        row = db.one(self.conn, "SELECT status, last_error, rule_report FROM content_queue WHERE id=?", (q,))
        self.assertEqual(row["status"], "rejected")
        self.assertIn("do-not-use", row["last_error"])
        self.assertEqual(json.loads(row["rule_report"])["rejected_by"], "donotuse")
        self.assertEqual(popen.call_args[0][0][-2:], ["run", "content"])
        self.assertEqual(popen.call_count, 1)
        # an entry that touches nothing waiting starts nothing
        c.post("/donotuse/add", data={"kind": "handle", "value": "@nobody"})
        self.assertEqual(popen.call_count, 1)

    def test_reject_sets_the_post_aside_and_drafts_again(self):
        """Chris's reject used to leave the day without a post until 08:00 and the photo free to come straight
        back (2026-10-13): now the post is set aside with him on the record, its photo sits out
        (agents/content.recent_use), and a new one is drafted at once. Reject asks first."""
        c = self.signed_in()
        popen = self.popen()
        q = self.draft()
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"for_day": "2026-10-14", "design": "single"}), q))
        form = re.search(rf'<form[^>]*action="/queue/{q}/reject"[^>]*>', c.get(f"/queue/{q}").text).group(0)
        self.assertIn("confirm(", form)
        r = c.post(f"/queue/{q}/reject", follow_redirects=False)
        self.assertIn("msg=rejected", r.headers["location"])
        row = db.one(self.conn, "SELECT status, rule_report, last_error FROM content_queue WHERE id=?", (q,))
        meta = json.loads(row["rule_report"])
        self.assertEqual((row["status"], meta["rejected_by"], meta["for_day"]), ("rejected", "chris", "2026-10-14"))
        self.assertTrue(meta["rejected_at"])
        self.assertIn("Set aside", row["last_error"])
        self.assertEqual(popen.call_args[0][0][-2:], ["run", "content"])
        self.assertEqual(popen.call_count, 1)
        page = c.get("/?msg=rejected").text
        self.assertIn("Set aside", page)
        self.assertIn("new post is being made", page)
        # a post that already went out is not something to reject
        p = self.draft()
        self.conn.execute("UPDATE content_queue SET status='published' WHERE id=?", (p,))
        c.post(f"/queue/{p}/reject")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (p,))["status"], "published")
        self.assertEqual(popen.call_count, 1)

    def test_unapprove_puts_an_approved_post_back_in_drafts(self):
        c = self.signed_in()
        q = self.draft()
        c.post(f"/queue/{q}/approve")
        self.assertIn(f'action="/queue/{q}/unapprove"', c.get(f"/queue/{q}").text)
        r = c.post(f"/queue/{q}/unapprove", follow_redirects=False)
        self.assertIn("msg=unapproved", r.headers["location"])
        row = db.one(self.conn, "SELECT status, approved_at FROM content_queue WHERE id=?", (q,))
        self.assertEqual((row["status"], row["approved_at"]), ("draft", None))
        self.assertIn("will not go out", c.get(f"/queue/{q}?msg=unapproved").text)
        # a post Buffer already holds is not taken back from here
        self.conn.execute("UPDATE content_queue SET status='scheduled' WHERE id=?", (q,))
        c.post(f"/queue/{q}/unapprove")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q,))["status"], "scheduled")
        self.assertNotIn("/unapprove", c.get(f"/queue/{q}").text)

    def test_going_live_sends_what_he_approved_in_dry_run(self):
        """Chris, 2026-10-13: posts and replies he approved in dry run go out when the lane is switched live.
        What the dry run marked would_publish / would_send is approved again; what was sent stays sent."""
        from convention_social.core import settings
        from convention_social.outreach import keys
        c = self.signed_in()
        now = db.utcnow()
        dry = self.draft()
        self.conn.execute("UPDATE content_queue SET status='would_publish', payload='{\"x\": 1}', dry_run=1, last_error='dry run note' WHERE id=?", (dry,))
        gone = self.draft()
        self.conn.execute("UPDATE content_queue SET status='published' WHERE id=?", (gone,))
        inq = {}
        for name, st in (("dry", "would_send"), ("gone", "sent")):
            inq[name] = db.insert(self.conn, "inquiries", remote_id=f"r-{name}", received_at=now, name="Dana", email="dana@example.org",
                                  reply_subject="Photography", reply_body="Hi Dana, here it is.\nChris", reply_status=st,
                                  notes="dry run: written to outbox", updated_at=now)
        out = {}
        for name, st in (("dry", "would_send"), ("gone", "sent")):
            out[name] = db.insert(self.conn, "outreach", event_key=keys.event_key(f"{name} Con", None), event_name=f"{name} Con",
                                  email=f"{name}@example.org", subject="Hello", body="Hi.", status=st, token=keys.new_token(),
                                  approved_at=now, last_attempt_at=now, notes="dry run", created_at=now, updated_at=now)
        r = c.post("/agents/all/dry-run", data={"state": "off"}, follow_redirects=False)
        self.assertIn("3+things+you+approved+in+dry+run", r.headers["location"])
        self.assertIn("3 things you approved in dry run", c.get("/agents?" + r.headers["location"].split("?", 1)[1]).text)
        post = db.one(self.conn, "SELECT status, payload, last_error FROM content_queue WHERE id=?", (dry,))
        self.assertEqual((post["status"], post["payload"], post["last_error"]), ("approved", None, None))
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (gone,))["status"], "published")
        self.assertEqual(db.one(self.conn, "SELECT reply_status, notes FROM inquiries WHERE id=?", (inq["dry"],))["reply_status"], "approved")
        self.assertEqual(db.one(self.conn, "SELECT reply_status FROM inquiries WHERE id=?", (inq["gone"],))["reply_status"], "sent")
        self.assertEqual(db.one(self.conn, "SELECT status FROM outreach WHERE id=?", (out["dry"],))["status"], "approved")
        self.assertEqual(db.one(self.conn, "SELECT status FROM outreach WHERE id=?", (out["gone"],))["status"], "sent")
        # back to dry run leaves them approved and releases nothing; one lane switched live on its own releases its own rows
        late = self.draft()
        self.conn.execute("UPDATE content_queue SET status='would_publish' WHERE id=?", (late,))
        r = c.post("/agents/all/dry-run", data={"state": "on"}, follow_redirects=False)
        self.assertNotIn("approved+in+dry+run", r.headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (dry,))["status"], "approved")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (late,))["status"], "would_publish")
        self.conn.execute("UPDATE content_queue SET status='would_publish' WHERE id=?", (dry,))
        r = c.post("/agents/publisher/dry-run", data={"state": "off"}, follow_redirects=False)
        self.assertIn("2+things+you+approved+in+dry+run", r.headers["location"])
        self.assertEqual([r["status"] for r in db.rows(self.conn, "SELECT status FROM content_queue WHERE id IN (?, ?)", (dry, late))], ["approved", "approved"])
        self.conn.execute("UPDATE content_queue SET status='would_publish' WHERE id=?", (late,))
        self.conn.execute("UPDATE content_queue SET status='scheduled' WHERE id=?", (dry,))
        r = c.post("/agents/publisher/dry-run", data={"state": "off"}, follow_redirects=False)
        self.assertIn("1+thing+you+approved+in+dry+run+goes+out", r.headers["location"])
        self.assertFalse(settings.dry_run(self.conn, "publisher"))
        r = c.post("/agents/publisher/dry-run", data={"state": "on"}, follow_redirects=False)
        self.assertNotIn("approved+in+dry+run", r.headers["location"])
        self.assertTrue(settings.dry_run(self.conn, "publisher"))

    def rendered_draft(self, **kw):
        """A draft with its cards on disk and a passing art verdict, as the content agent leaves it."""
        from tests._fakes import write_render
        q = self.draft(**kw)
        folder = config.get_config().data_root / "renders"
        paths = {"4:5": [write_render(folder, f"q{q}-45.jpg")], "2:3": [write_render(folder, f"q{q}-23.jpg")]}
        self.conn.execute("UPDATE content_queue SET render_paths=?, rule_report=? WHERE id=?",
                          (json.dumps(paths), json.dumps({"for_day": "2026-10-14", "art": {"verdict": "pass", "notes": "Fine."}}), q))
        return q

    def test_save_and_approve_is_one_tap_and_keeps_the_edit(self):
        """4.1 (2026-10-13): an edit without Save was lost on Approve. One form, two buttons; the gates still hold."""
        c = self.signed_in()
        q = self.draft()
        self.assertIn('name="do" value="approve"', c.get(f"/queue/{q}").text)
        words = "Green room before the keynote, calm and ready. Request a quote for your event."
        data = {"caption_instagram": words, "caption_facebook": words, "caption_pinterest": words, "do": "approve"}
        r = c.post(f"/queue/{q}/save", data=data, follow_redirects=False)
        self.assertIn("msg=notargets", r.headers["location"], "the gates still hold; the edit is kept")
        row = db.one(self.conn, "SELECT status, caption FROM content_queue WHERE id=?", (q,))
        self.assertEqual((row["status"], json.loads(row["caption"])["instagram"]), ("draft", words))
        r = c.post(f"/queue/{q}/save", data={**data, "target_instagram": "on"}, follow_redirects=False)
        self.assertIn("msg=approved", r.headers["location"])
        row = db.one(self.conn, "SELECT status, caption, targets FROM content_queue WHERE id=?", (q,))
        self.assertEqual((row["status"], json.loads(row["caption"])["facebook"], json.loads(row["targets"])), ("approved", words, ["instagram"]))
        q2 = self.draft()
        r = c.post(f"/queue/{q2}/save", data={**data, "target_instagram": "on", "do": "save"}, follow_redirects=False)
        self.assertIn("msg=saved", r.headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q2,))["status"], "draft")

    def test_the_list_approves_only_when_the_gates_pass_and_shows_the_card(self):
        """4.2: Approve on the Queue list for a draft whose rules pass, photos usable, art verdict pass or not
        reviewed; the thumbnail opens the full card; every caption is there to read."""
        c = self.signed_in()
        good = self.rendered_draft()
        bad = self.draft("Coverage from $500 a day.")
        plain = self.draft()
        page = c.get("/").text
        self.assertIn(f'action="/queue/{good}/approve"', page)
        self.assertIn(f'action="/queue/{plain}/approve"', page, "no art verdict (no render) is not a hold")
        self.assertNotIn(f'action="/queue/{bad}/approve"', page)
        self.assertIn(f'<a href="/media/render/{good}/4x5/1"', page, "the thumbnail opens the full card")
        self.assertIn("<details", page)
        self.assertEqual(page.count("Request a quote for your event."), 6, "all three captions of both clean drafts")
        c.post(f"/queue/{good}/approve")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (good,))["status"], "approved")
        self.assertNotIn(f'action="/queue/{good}/approve"', c.get("/").text)
        redo = self.rendered_draft()
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"art": {"verdict": "redo", "notes": "Crop tighter."}}), redo))
        self.assertNotIn(f'action="/queue/{redo}/approve"', c.get("/").text, "an art director redo is his to look at")

    def test_destructive_buttons_ask_first(self):
        """4.2: Reject, Delete, Cancel, Exclude, Switch everything live, Remove and Spam each ask on the phone;
        the small buttons are tall enough for a thumb."""
        from convention_social.outreach import compliance
        c = self.signed_in()
        now = db.utcnow()
        q = self.draft()
        db.insert(self.conn, "do_not_use", kind="handle", value="@x", added_at=now)
        c.post("/calendar/save", data={"name": "Big Con", "kind": "business"})
        c.post("/bookings/add", data={"title": "Sample", "start_date": "2027-03-05", "status": "booked"})
        iid = db.insert(self.conn, "inquiries", remote_id="r1", received_at=now, name="Dana", email="dana@example.org", updated_at=now)
        compliance.block(self.conn, "stop@example.org", source="reply")
        self.seed_library()

        def form_tag(page, action):
            m = re.search(rf'<form[^>]*action="{re.escape(action)}"[^>]*>', page)
            self.assertIsNotNone(m, action)
            return m.group(0)
        self.assertIn("confirm(", form_tag(c.get(f"/queue/{q}").text, f"/queue/{q}/reject"))
        rid = db.one(self.conn, "SELECT id FROM do_not_use")["id"]
        self.assertIn("confirm(", form_tag(c.get("/donotuse").text, f"/donotuse/{rid}/remove"))
        cid = db.one(self.conn, "SELECT id FROM conventions")["id"]
        self.assertIn("confirm(", form_tag(c.get("/calendar").text, f"/calendar/{cid}/delete"))
        bid = db.one(self.conn, "SELECT id FROM bookings")["id"]
        self.assertIn("confirm(", form_tag(c.get("/bookings").text, f"/bookings/{bid}/status"))
        did = db.one(self.conn, "SELECT id FROM do_not_contact")["id"]
        self.assertIn("confirm(", form_tag(c.get("/outreach/donotcontact").text, f"/outreach/donotcontact/{did}/remove"))
        self.assertIn("confirm(", form_tag(c.get("/agents").text, "/agents/all/dry-run"))
        inquiry = c.get(f"/inquiries/{iid}").text
        self.assertRegex(inquiry, r'<form[^>]*onsubmit="return confirm\([^"]*\)"[^>]*><input type="hidden" name="status" value="spam">')
        self.assertNotRegex(inquiry, r'<form[^>]*confirm\([^"]*\)"[^>]*><input type="hidden" name="status" value="quoted">')
        folder = c.get("/library/folder/fcon").text
        self.assertRegex(folder, r'<form[^>]*onsubmit="return confirm\([^"]*\)"[^>]*><input type="hidden" name="state" value="excluded">')
        self.assertNotRegex(folder, r'<form[^>]*confirm\([^"]*\)"[^>]*><input type="hidden" name="state" value="cleared">')
        self.assertIn("button.small{min-height:40px", c.get("/").text)

    def test_words_match_the_law(self):
        """4.4: the draft page never tells him to fix a caption; a folder-approved photo says so instead of a no-op Undo."""
        c = self.signed_in()
        page = c.get(f"/queue/{self.draft()}?msg=blocked").text
        self.assertIn("Nothing for you to do", page)
        self.assertNotIn("Fix it and save first", page)
        pid = self.seed_library()
        c.post("/library/folder/fcon/clearance", data={"state": "cleared"})
        approved = c.get("/library?view=approved").text
        self.assertIn("approved by its folder", approved)
        self.assertNotIn(">Undo<", approved)
        c.post(f"/library/photo/{pid}/clearance", data={"state": "cleared"})
        approved = c.get("/library?view=approved").text
        self.assertIn(">Undo<", approved)
        self.assertNotIn("approved by its folder", approved)

    def test_keys_page_has_every_setting_and_can_clear_one(self):
        """4.5: every setting the code reads is on the page (the Scout page pointed at a field that was not there),
        and a non-secret can be cleared back to its default."""
        c = self.signed_in()
        page = c.get("/keys").text
        for name in ("SCOUT_REGION", "SCOUT_MONTHS", "POST_TIMES", "BUILDING_WEEKDAY", "DIGEST_HOUR", "TIMEZONE", "VARIETY_DAYS",
                     "PHOTO_REPEAT_DAYS", "OUTREACH_DAILY_DRAFTS", "OUTREACH_DAILY_SENDS", "PINTEREST_LINK"):
            self.assertIn(f'name="{name}"', page, name)
            self.assertIn(f'name="clear_{name}"', page, name)
        self.assertNotIn('name="clear_ANTHROPIC_API_KEY"', page, "a secret is replaced, never cleared from here")
        c.post("/keys", data={"SCOUT_REGION": "Washington DC, Maryland and Virginia", "DIGEST_HOUR": "6"})
        config.reset()
        self.assertEqual(config.getenv("SCOUT_REGION"), "Washington DC, Maryland and Virginia")
        self.assertEqual(config.get_config().digest_hour, 6)
        self.assertIn('value="Washington DC, Maryland and Virginia"', c.get("/keys").text)
        r = c.post("/keys", data={"SCOUT_REGION": "Washington DC, Maryland and Virginia", "clear_SCOUT_REGION": "on"}, follow_redirects=False)
        config.reset()
        self.assertIsNone(config.getenv("SCOUT_REGION"), "cleared: the default stands again")
        self.assertIn("cleared", r.headers["location"])
        self.assertEqual(config.get_config().digest_hour, 6, "the other field kept its value")
        c.post("/keys", data={"ANTHROPIC_API_KEY": "sk-secret-value", "BUFFER_PLAN": "team"})
        c.post("/keys", data={"clear_ANTHROPIC_API_KEY": "on", "clear_BUFFER_PLAN": "on"})
        config.reset()
        self.assertEqual(config.getenv("ANTHROPIC_API_KEY"), "sk-secret-value", "a secret is never cleared from the page")
        self.assertEqual(config.getenv("BUFFER_PLAN"), "team", "a choice has no clear")

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
        from convention_social.core import runner as runner_module
        with mock.patch.object(runner_module.subprocess, "Popen") as popen:
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
