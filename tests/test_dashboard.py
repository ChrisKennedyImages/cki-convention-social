"""The dashboard: fail-closed login, clearance, do-not-use, calendar, approve gates."""
from __future__ import annotations

import json
import os
import re
import time
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.ai import copy_rules
from convention_social.core import approve_token, auth, config, db
from convention_social.core.settings import get as settings_get
from convention_social.dashboard.app import COOKIE, SESSION_DAYS, create_app, make_token
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

    def test_every_answer_carries_the_security_headers_and_pages_are_never_kept(self):
        """2026-10-24 audit: the dashboard sent no X-Frame-Options, X-Content-Type-Options, Referrer-Policy or Content
        Security Policy (the Worker's team pages do), and the crash page, answered outside the middleware, carried no
        cache header."""
        from unittest import mock
        from convention_social.dashboard import app as dash
        wanted = {"x-frame-options": "DENY", "x-content-type-options": "nosniff", "referrer-policy": "same-origin"}
        page = self.signed_in().get("/")
        self.assertEqual(page.status_code, 200)
        for name, value in wanted.items():
            self.assertEqual(page.headers[name], value, name)
        csp = page.headers["content-security-policy"]
        for word in ("default-src 'self'", "frame-ancestors 'none'", "form-action 'self'", "object-src 'none'"):
            self.assertIn(word, csp)
        self.assertNotIn("http", csp, "nothing from anywhere else")
        self.assertEqual(page.headers["cache-control"], "no-store")
        renders = config.get_config().data_root / "renders"
        renders.mkdir(parents=True, exist_ok=True)
        (renders / "contact-sheet-20261011.jpg").write_bytes(b"\xff\xd8jpeg")
        picture = self.client.get("/library/renders/contact-sheet-20261011.jpg")
        self.assertEqual((picture.status_code, picture.headers["x-content-type-options"]), (200, "nosniff"))
        self.assertNotIn("cache-control", picture.headers, "a picture may be kept; only pages and redirects never are")
        away = TestClient(create_app()).get("/library", follow_redirects=False)
        self.assertEqual((away.status_code, away.headers["x-frame-options"], away.headers["cache-control"]), (307, "DENY", "no-store"))
        crashing = TestClient(create_app(), raise_server_exceptions=False)
        crashing.cookies.set(COOKIE, make_token("chris"))

        def boom(*a, **k):
            raise RuntimeError("the photo list could not be read")
        with mock.patch.object(dash, "photo_page", boom):
            crash = crashing.get("/library")
        self.assertEqual(crash.status_code, 500)
        self.assertEqual((crash.headers["cache-control"], crash.headers["x-frame-options"]), ("private, no-store", "DENY"),
                         "made outside the middlewares: hardened and private all the same")

    def test_signing_out_is_the_signed_in_users_own_choice(self):
        """2026-10-24 audit: /logout was an unauthenticated POST."""
        self.assertEqual(TestClient(create_app()).post("/logout", follow_redirects=False).status_code, 401)
        r = self.signed_in().post("/logout", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/login?bye=1"))
        self.assertIn("Max-Age=0", r.headers["set-cookie"], "the cookie is dropped")

    def test_a_convention_saved_with_a_bad_id_is_refused_not_a_crash(self):
        """2026-10-24 audit: POST /calendar/save with id=abc crashed the page."""
        r = self.signed_in().post("/calendar/save", data={"id": "abc", "name": "Big Con", "kind": "fan"}, follow_redirects=False)
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM conventions"))
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM errors WHERE agent='dashboard'"), "no crash recorded")

    def test_every_page_renders(self):
        c = self.signed_in()
        self.seed_library()
        qid = self.draft()
        for path in ("/", "/library", "/library?show=all", "/library/folder/fcon", "/donotuse", "/calendar", "/drive",
                     "/agents", "/keys", f"/queue/{qid}"):
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertRegex(r.text, r'<main( class="wide")?>', path)          # Today is the wide one (2026-10-15)

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
        """Chris's reject used to leave the day without a post until 08:00 (2026-10-13): the post is set aside with him
        on the record and a new one is drafted at once. Since 2026-10-15 it is Skip, and its photos go back into the
        rotation instead of sitting out (tests/test_today.py pins that). Skip asks first; the old address still works."""
        c = self.signed_in()
        popen = self.popen()
        q = self.draft()
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps({"for_day": "2026-10-14", "design": "single"}), q))
        form = re.search(rf'<form[^>]*action="/queue/{q}/skip"[^>]*>', c.get(f"/queue/{q}").text).group(0)
        self.assertIn("confirm(", form)
        r = c.post(f"/queue/{q}/reject", follow_redirects=False)
        self.assertIn("Skipped+post", r.headers["location"])
        row = db.one(self.conn, "SELECT status, rule_report, last_error FROM content_queue WHERE id=?", (q,))
        meta = json.loads(row["rule_report"])
        self.assertEqual((row["status"], meta["rejected_by"], meta["for_day"]), ("rejected", "skip", "2026-10-14"))
        self.assertTrue(meta["rejected_at"])
        self.assertIn("Skipped by you", row["last_error"])
        self.assertEqual(popen.call_args[0][0][-2:], ["run", "content"])
        self.assertEqual(popen.call_count, 1)
        page = c.get(r.headers["location"]).text
        self.assertIn("Skipped post", page)
        self.assertIn("A new daily post is being made in its place", page)
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
        self.assertIn("3+things+you+approved+in+practice+run", r.headers["location"])        # dry run is called practice run (2026-10-15)
        self.assertIn("3 things you approved in practice run", c.get("/agents?" + r.headers["location"].split("?", 1)[1]).text)
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
        self.assertNotIn("approved+in+practice+run", r.headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (dry,))["status"], "approved")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (late,))["status"], "would_publish")
        self.conn.execute("UPDATE content_queue SET status='would_publish' WHERE id=?", (dry,))
        r = c.post("/agents/publisher/dry-run", data={"state": "off"}, follow_redirects=False)
        self.assertIn("2+things+you+approved+in+practice+run", r.headers["location"])
        self.assertEqual([r["status"] for r in db.rows(self.conn, "SELECT status FROM content_queue WHERE id IN (?, ?)", (dry, late))], ["approved", "approved"])
        self.conn.execute("UPDATE content_queue SET status='would_publish' WHERE id=?", (late,))
        self.conn.execute("UPDATE content_queue SET status='scheduled' WHERE id=?", (dry,))
        r = c.post("/agents/publisher/dry-run", data={"state": "off"}, follow_redirects=False)
        self.assertIn("1+thing+you+approved+in+practice+run+goes+out", r.headers["location"])
        self.assertFalse(settings.dry_run(self.conn, "publisher"))
        r = c.post("/agents/publisher/dry-run", data={"state": "on"}, follow_redirects=False)
        self.assertNotIn("approved+in+practice+run", r.headers["location"])
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
        """4.1 (2026-10-13): an edit without Save was lost on Approve. One form; the gates still hold. Since 2026-10-15
        the form's choices are Post now and Follow the pace (do=now, do=pace); do=approve still follows the pace."""
        c = self.signed_in()
        q = self.draft()
        page = c.get(f"/queue/{q}").text
        self.assertIn('<button form="edit" class="primary" type="submit" name="do" value="now">Post now</button>', page)
        self.assertIn('<button form="edit" class="ok" type="submit" name="do" value="pace">Follow the pace</button>', page)
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
        reviewed. Since 2026-10-15 that list is Needs you on Today: the card is on it and opens the draft, where
        every caption and every card is; the Instagram caption is on Today (posts go to Instagram)."""
        c = self.signed_in()
        good = self.rendered_draft()
        bad = self.draft("Coverage from $500 a day.")
        plain = self.draft()
        page = c.get("/").text
        self.assertIn(f'action="/queue/{good}/approve"', page)
        self.assertIn(f'action="/queue/{plain}/approve"', page, "no art verdict (no render) is not a hold")
        self.assertNotIn(f'action="/queue/{bad}/approve"', page)
        self.assertIn(f'<a href="/queue/{good}"><img class="media" src="/media/render/{good}/4x5/1"', page, "the card opens the draft")
        self.assertEqual(page.count("Request a quote for your event."), 2, "the caption of both clean drafts")
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
        self.assertIn("confirm(", form_tag(c.get(f"/queue/{q}").text, f"/queue/{q}/skip"))
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
        self.assertIn("button.small,.btn.small{min-height:44px", c.get("/").text, "every tap target 44px or more (2026-10-15)")

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

    def test_a_tap_answers_without_a_reload_and_the_form_still_works_without_it(self):
        """5.1 (2026-10-13): one tap was one full page. The page's own script asks for JSON and swaps the badge;
        the plain form (no script) still gets the redirect."""
        c = self.signed_in()
        pid = self.seed_library()
        page = c.get("/library").text
        self.assertIn('class="inline tap"', page)
        self.assertIn("fetch(", page)
        self.assertIn("'Accept': 'application/json'", page)
        r = c.post(f"/library/photo/{pid}/clearance", data={"state": "cleared", "back": "/library"}, headers={"Accept": "application/json"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"id": pid, "state": "cleared", "words": "Approved."})
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM photos WHERE id=?", (pid,))["clearance"], "cleared")
        r = c.post(f"/library/photo/{pid}/clearance", data={"state": "blocked", "back": "/library"}, headers={"Accept": "application/json"})
        self.assertEqual(r.json()["words"], "Kept out.")
        r = c.post(f"/library/photo/{pid}/clearance", data={"state": "inherit", "back": "/library?view=approved"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/library?view=approved"))

    def test_bulk_use_and_dont_use(self):
        """5.1: tick several, one tap for all of them."""
        from convention_social.drive import scan
        from convention_social.drive.api import DriveReader
        from tests.fake_drive import FakeDrive
        c = self.signed_in()
        d = FakeDrive()
        d.folder("fcon", "Katsucon 2025")
        for i in (1, 2, 3):
            d.image(f"p{i}", f"{i}.jpg", "fcon")
        scan.full_inventory(self.conn, DriveReader("t", conn=self.conn, transport=d))
        classify.folder_pass(self.conn)
        self.conn.execute("UPDATE classifications SET method='ollama', subject='event', possible_minor=0, personal_details='[]'")
        ids = [r["id"] for r in db.rows(self.conn, "SELECT id FROM photos ORDER BY id")]
        page = c.get("/library").text
        self.assertIn('id="bulk"', page)
        self.assertIn('action="/library/photos/clearance"', page)
        for pid in ids:
            self.assertIn(f'form="bulk" name="ids" value="{pid}"', page)
        r = c.post("/library/photos/clearance", data={"ids": [str(ids[0]), str(ids[1])], "state": "cleared", "back": "/library?view=review"},
                   follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/library?view=review"))
        self.assertEqual([r["clearance"] for r in db.rows(self.conn, "SELECT clearance FROM photos ORDER BY id")], ["cleared", "cleared", "inherit"])
        c.post("/library/photos/clearance", data={"ids": [str(ids[2])], "state": "blocked"})
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM photos WHERE id=?", (ids[2],))["clearance"], "blocked")
        self.assertEqual(c.post("/library/photos/clearance", data={"ids": [str(ids[2])], "state": "excluded"}).status_code, 400)
        self.assertTrue(self.conn.execute("SELECT value FROM settings WHERE key='site.photos_changed_at'").fetchone()[0], "the site follows")

    def test_an_excluded_folder_keeps_a_tapped_photo_off_the_approved_page(self):
        """5.2: the page's SQL follows the same rule as the walker."""
        c = self.signed_in()
        pid = self.seed_library()
        c.post(f"/library/photo/{pid}/clearance", data={"state": "cleared"})
        self.assertIn(f'id="p{pid}"', c.get("/library?view=approved").text)
        c.post("/library/folder/fcon/clearance", data={"state": "excluded"})
        self.assertNotIn(f'id="p{pid}"', c.get("/library?view=approved").text)
        self.assertNotIn(f'id="p{pid}"', c.get("/library").text, "nor back in review: the folder is excluded")
        self.assertIn("kept out, even photos you tapped Use on", c.get("/library/folder/fcon").text)

    def test_blocked_photos_are_visible_and_never_use_is_one_tap_from_the_card(self):
        """5.3: a Don't use was invisible afterwards; now a Blocked chip lists them with Unblock, and every card
        has Never use (the do-not-use list) that comes back to the same page."""
        c = self.signed_in()
        pid = self.seed_library()
        self.assertIn('href="/library?view=blocked"', c.get("/library").text)
        self.assertNotIn(f'id="p{pid}"', c.get("/library?view=blocked").text)
        c.post(f"/library/photo/{pid}/clearance", data={"state": "blocked"})
        blocked = c.get("/library?view=blocked").text
        self.assertIn(f'id="p{pid}"', blocked)
        self.assertIn(">Unblock<", blocked)
        self.assertIn('name="state" value="inherit"', blocked)
        self.assertNotIn(f'id="p{pid}"', c.get("/library").text)
        c.post(f"/library/photo/{pid}/clearance", data={"state": "inherit"})
        review = c.get("/library").text
        self.assertIn(f'id="p{pid}"', review)
        form = re.search(r'<form[^>]*action="/donotuse/add"[^>]*>.*?</form>', review, flags=re.S).group(0)
        self.assertIn("confirm(", form)
        self.assertIn('name="kind" value="photo"', form)
        self.assertIn('name="value" value="p1"', form)
        r = c.post("/donotuse/add", data={"kind": "photo", "value": "p1", "back": "/library?view=review&page=1"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/library?view=review&page=1")
        self.assertEqual(db.one(self.conn, "SELECT kind, value FROM do_not_use")["value"], "p1")
        r = c.post("/donotuse/add", data={"kind": "handle", "value": "@x", "back": "//evil.example/x"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/donotuse")

    def test_the_site_follows_the_photos(self):
        """5.4: Use, Don't use, a folder decision and the hero pick stamp the change; the Website card says the
        site publishes by itself; Publish stays for the impatient."""
        from convention_social.site import deploy
        c = self.signed_in()
        pid = self.seed_library()
        self.assertIsNone(settings_get(self.conn, deploy.PHOTOS_CHANGED_KEY))
        c.post(f"/library/photo/{pid}/clearance", data={"state": "cleared"})
        first = settings_get(self.conn, deploy.PHOTOS_CHANGED_KEY)
        self.assertTrue(first)
        from convention_social.core import settings as settings_mod
        for path, data in (("/library/folder/fcon/clearance", {"state": "cleared"}), (f"/library/photo/{pid}/hero", {}),
                           ("/donotuse/add", {"kind": "handle", "value": "@x"})):
            settings_mod.set(self.conn, deploy.PHOTOS_CHANGED_KEY, "")
            c.post(path, data=data)
            self.assertTrue(settings_get(self.conn, deploy.PHOTOS_CHANGED_KEY), path)
        page = c.get("/library?view=approved").text
        self.assertIn("publish", page.lower())
        self.assertIn("by itself in a few minutes with your photo changes", page)

    def test_mail_is_google_workspace_on_the_keys_page_and_in_the_guide(self):
        """6.5 (Chris, 2026-10-13: chris@eventcaliber.com on Google Workspace): the sender is plain SMTP with
        STARTTLS on 587, which is smtp.gmail.com with an app password. The words say so where he looks."""
        page = self.signed_in().get("/keys").text
        self.assertIn("smtp.gmail.com", page)
        self.assertIn("app password", page.lower())
        guide = (config.REPO_ROOT / "docs" / "SETUP.md").read_text()
        section = guide.split("## 4.")[1].split("## 5.")[0]
        for words in ("Google Workspace", "smtp.gmail.com", "app password", "Email Routing", "MX", "SPF", "DKIM", "Send mail as"):
            self.assertIn(words, section, words)
        self.assertNotIn("Resend", section, "the sending-service recipe is gone")

    def test_the_posts_page_shows_the_history_the_live_links_and_the_numbers(self):
        """7.2 (2026-10-13): post_history and the metrics summary existed and were shown nowhere."""
        from tests._fakes import write_render
        c = self.signed_in()
        q = self.draft()
        folder = config.get_config().data_root / "renders"
        self.conn.execute("UPDATE content_queue SET status='published', render_paths=? WHERE id=?",
                          (json.dumps({"4:5": [write_render(folder, "p.jpg")]}), q))
        from datetime import date, timedelta
        sent = (date.today() - timedelta(days=4)).isoformat() + "T15:30:05Z"
        captured = (date.today() - timedelta(days=1)).isoformat()
        for pid, svc in (("post-1", "instagram"), ("post-2", "facebook")):
            db.insert(self.conn, "post_history", buffer_post_id=pid, queue_id=q, service=svc, sent_at=sent,
                      caption="Backstage.", external_link=f"https://{svc}.example/p/{pid}", metrics=json.dumps({"reach": 120, "likes": 7}))
            db.insert(self.conn, "post_metrics", buffer_post_id=pid, service=svc, ours=1, sent_at=sent, text="Backstage.",
                      captured_on=captured, metrics=json.dumps({"reach": 120, "likes": 7, "link_clicks": 3}), metrics_updated_at=captured + "T00:00:00Z")
        # 2026-10-15: the Posts page folded into Today (Went out, with the numbers); the weekly table is on All posts
        self.assertEqual(c.get("/posts", follow_redirects=False).headers["location"], "/#went-out")
        page = c.get("/").text
        self.assertIn('href="https://instagram.example/p/post-1"', page)
        self.assertIn("Open on Instagram", page)
        self.assertIn(f'/media/render/{q}/4x5/1', page)
        self.assertIn("reach 240", page, "reach over the last 30 days, two posts")
        self.assertIn("Last 30 days", page)
        self.assertIn('href="/history"', page)
        self.assertIn("Week of", c.get("/history").text)

    def test_today_says_what_needs_him(self):
        """7.3: the Queue page shows the needs list and the open-error count before the morning brief exists."""
        from convention_social.core import runner as runner_module
        c = self.signed_in()
        self.draft()
        now = db.utcnow()
        db.insert(self.conn, "inquiries", remote_id="r1", received_at=now, name="Dana", email="d@example.org", status="drafted",
                  reply_status="draft", updated_at=now)
        runner_module.record_error(self.conn, "content", "no_draft", "nothing drafted")
        page = c.get("/").text
        self.assertIn("Needs you", page)
        self.assertIn('<span class="count" title="posts to approve">1</span>', page, "the draft itself, with its choices (2026-10-15)")
        self.assertIn("1 quote request(s) waiting for your reply.", page)
        self.assertIn("No post was drafted", page, "each alert itself, with its fix")
        self.assertIn("nothing drafted", page)

    def test_pull_back_a_scheduled_post(self):
        """7.5: a post Buffer already holds comes back to drafts, deleted there first; a draft is nothing to pull."""
        from unittest import mock
        from convention_social.buffer.client import BufferClient
        from tests._fakes import FakeBuffer
        c = self.signed_in()
        q = self.draft()
        self.conn.execute("UPDATE content_queue SET status='scheduled', buffer_post_ids=?, payload='{}' WHERE id=?",
                          (json.dumps({"instagram": "post-1", "facebook": "post-2"}), q))
        page = c.get(f"/queue/{q}").text
        form = re.search(rf'<form[^>]*action="/queue/{q}/pullback"[^>]*>', page).group(0)
        self.assertIn("confirm(", form)
        fake = FakeBuffer()
        with mock.patch.object(BufferClient, "from_config", return_value=BufferClient("test-key", conn=self.conn, transport=fake)):
            r = c.post(f"/queue/{q}/pullback", follow_redirects=False)
        self.assertIn("msg=pulled_back", r.headers["location"])
        self.assertEqual(sorted(fake.deleted), ["post-1", "post-2"])
        row = db.one(self.conn, "SELECT status, buffer_post_ids, payload, last_error FROM content_queue WHERE id=?", (q,))
        self.assertEqual((row["status"], row["buffer_post_ids"], row["payload"]), ("draft", None, None))
        self.assertIn("pulled back", row["last_error"].lower())
        self.assertIn("pulled back", c.get(f"/queue/{q}?msg=pulled_back").text.lower())
        with mock.patch.object(BufferClient, "from_config", return_value=BufferClient("test-key", conn=self.conn, transport=fake)):
            c.post(f"/queue/{q}/pullback")
        self.assertEqual(len(fake.deleted), 2, "a draft is nothing to pull back")
        gone = self.draft()
        self.conn.execute("UPDATE content_queue SET status='published', buffer_post_ids=? WHERE id=?", (json.dumps({"instagram": "post-5"}), gone))
        with mock.patch.object(BufferClient, "from_config", return_value=BufferClient("test-key", conn=self.conn, transport=fake)):
            c.post(f"/queue/{gone}/pullback")
        self.assertEqual(len(fake.deleted), 2, "a post that went out is not pulled back from here")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (gone,))["status"], "published")
        q2 = self.draft()
        self.conn.execute("UPDATE content_queue SET status='scheduled', buffer_post_ids=? WHERE id=?", (json.dumps({"instagram": "post-9"}), q2))
        with mock.patch.object(BufferClient, "from_config", return_value=None):
            r = c.post(f"/queue/{q2}/pullback", follow_redirects=False)
        self.assertIn("msg=no_buffer", r.headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q2,))["status"], "scheduled", "nothing changes without Buffer")
        refusing = FakeBuffer(reject_at=("post-9",))
        with mock.patch.object(BufferClient, "from_config", return_value=BufferClient("test-key", conn=self.conn, transport=refusing)):
            r = c.post(f"/queue/{q2}/pullback", follow_redirects=False)
        self.assertIn("msg=pullback_failed", r.headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q2,))["status"], "scheduled", "Buffer kept it: so do we")

    def test_the_keys_page_tests_the_outside_watch(self):
        """7.4: one button, and the answer says whether the site sent the alert."""
        from unittest import mock
        from convention_social.booking.remote import SiteAPI
        c = self.signed_in()
        self.assertIn("Test the outside watch", c.get("/keys").text)
        with mock.patch.object(SiteAPI, "from_config", return_value=None):
            r = c.post("/keys/test-watch", follow_redirects=False)
        self.assertIn("MEDIA_UPLOAD_TOKEN", r.headers["location"])
        calls = []

        def transport(method, url, headers, payload):
            calls.append((method, url))
            return mock.Mock(json=lambda: {"ok": True, "sent": True})
        with mock.patch.object(SiteAPI, "from_config", return_value=SiteAPI("tok", base="https://eventcaliber.com", transport=transport)):
            r = c.post("/keys/test-watch", follow_redirects=False)
        self.assertEqual(calls, [("POST", "https://eventcaliber.com/api/heartbeat/test")])
        self.assertIn("sent", r.headers["location"].lower())

    def test_the_ntfy_topic_is_kept_like_a_key(self):
        """2026-10-24 audit: the topic was shown plain on the Keys page though it is the only thing guarding the pings:
        whoever knows it reads every ping and can push fake ones with a link of their choosing."""
        os.environ["NTFY_TOPIC"] = "event-caliber-k9x7"
        config.reset()
        page = self.signed_in().get("/keys").text
        self.assertNotIn("event-caliber-k9x7", page)
        self.assertRegex(page, r'<input type="password" name="NTFY_TOPIC"')
        self.assertNotIn('name="clear_NTFY_TOPIC"', page, "replaced, never cleared, like a key")

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

    def test_a_keys_value_with_a_line_break_is_refused_and_adds_no_line_to_env(self):
        """2026-10-24 audit: BRAND_NAME "Fine Name\\nINJECTED_KEY=pwned" went into .env as two lines."""
        from urllib.parse import unquote_plus
        c = self.signed_in()
        r = c.post("/keys", data={"BRAND_NAME": "Fine Name\nINJECTED_KEY=pwned\nAUTOPOST_ENABLED=1"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("line break", unquote_plus(r.headers["location"]))
        config.reset()
        self.assertIsNone(config.getenv("INJECTED_KEY"))
        self.assertIsNone(config.getenv("AUTOPOST_ENABLED"))
        self.assertNotIn("Fine Name", config.getenv("BRAND_NAME") or "")

    def test_a_token_body_bigger_than_a_token_is_refused_before_it_is_read(self):
        """2026-10-24 audit: the no-login token routes read any body whole into memory."""
        import asyncio
        from fastapi import HTTPException
        from convention_social.dashboard import team_routes
        c = self.signed_in()
        now = db.utcnow()
        qid = db.insert(self.conn, "content_queue", kind="photo", photo_ids="[1]", targets='["instagram"]', caption='{"instagram": "x"}',
                        status="draft", created_at=now, updated_at=now)
        big = b"token=" + b"x" * (team_routes.TOKEN_BODY_MAX + 1)
        for path in (f"/queue/{qid}/choose-by-token/now", f"/queue/{qid}/approve-by-token", f"/queue/{qid}/feed-by-token"):
            self.assertEqual(c.post(path, content=big).status_code, 413, path)
        self.assertEqual(c.post(f"/queue/{qid}/choose-by-token/now", data={"token": "x"}).status_code, 409, "a small one is read as before")

        class Chunked:
            headers: dict = {}

            async def stream(self):
                for _ in range(3):
                    yield b"x" * 2000
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(team_routes.small_body(Chunked(), 4096))
        self.assertEqual(cm.exception.status_code, 413, "a body with no length is cut off as it streams")

    def test_library_never_opens_empty_when_folders_exist(self):
        d = FakeDrive()
        d.folder("fmisc", "Phone dump")
        d.image("m1", "IMG_1.jpg", "fmisc")
        scan.full_inventory(self.conn, DriveReader("t", conn=self.conn, transport=d))
        page = self.signed_in().get("/library?view=folders").text
        self.assertIn("Phone dump", page)
        self.assertIn("No folder has been recognised as event work yet", page)

    def test_a_file_route_never_follows_a_link_out_of_the_data_folder(self):
        """2026-10-24 audit: /library/renders/{name} and /library/design/{folder}/{name} checked the name and nothing
        else, so a link planted under renders/ with a good name would have served any file on the Mini."""
        renders = config.get_config().data_root / "renders"
        (renders / "design-20261011-1800").mkdir(parents=True)
        outside = self.root / "outside.jpg"
        outside.write_bytes(b"\xff\xd8not for the web")
        (renders / "contact-sheet-20261011.jpg").symlink_to(outside)
        (renders / "design-20261011-1800" / "fan-post.jpg").symlink_to(outside)
        (renders / "building-sheet-20261011.jpg").write_bytes(b"\xff\xd8jpeg")
        c = self.signed_in()
        self.assertEqual(c.get("/library/renders/contact-sheet-20261011.jpg").status_code, 404)
        self.assertEqual(c.get("/library/design/design-20261011-1800/fan-post.jpg").status_code, 404)
        self.assertEqual(c.get("/library/renders/building-sheet-20261011.jpg").status_code, 200, "a file of its own is served")

    def test_library_report_and_sheets_are_on_the_dashboard(self):
        renders = config.get_config().data_root / "renders"
        renders.mkdir(parents=True, exist_ok=True)
        (renders / "library-report-20261010.html").write_text("<p>old</p>")
        (renders / "library-report-20261011.html").write_text("<p>new report</p>")
        (renders / "contact-sheet-20261011.jpg").write_bytes(b"\xff\xd8jpeg")
        (renders / "building-sheet-20261011.jpg").write_bytes(b"\xff\xd8jpeg")
        (renders / "notes.txt").write_text("not for the web")
        page = self.signed_in().get("/music").text          # with the music since the Design card left (2026-10-15)
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
        self.assertIn("Dismiss all 3", page)
        self.assertIn('<input type="hidden" name="kind" value="site_check">', page)
        r = c.post("/errors/ack-kind", data={"kind": "drive_auth"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("Dismissed+3%3A+Google+Drive+is+signed+out", r.headers["location"])
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
        self.assertIn('<input type="hidden" name="kind" value="no_draft"><input type="hidden" name="back" value="/errors"><button type="submit">Dismiss</button>', r.text)
        r = c.post(f"/errors/{eid}/ack", data={"back": "/errors"}, follow_redirects=False)
        self.assertEqual(r.headers["location"], "/errors")
        self.assertIn("None.", c.get("/errors").text)
        self.assertIn('href="/errors"', c.get("/settings").text)
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
        # 2026-10-15: More became Settings
        for path, tab, chip in (("/", "Today", "Today"), ("/library?view=folders", "Photos", "Folders"), ("/calendar", "Bookings", "Calendar"),
                                ("/agents", "Settings", "Agents"), ("/keys", "Settings", "Keys"), ("/settings", "Settings", None)):
            page = c.get(path).text
            tabs = re.findall(r'<nav>(.*?)</nav>', page, flags=re.S)[0]
            self.assertEqual(re.findall(r">([A-Za-z]+)</a>", tabs), ["Today", "Photos", "Bookings", "Settings"], path)
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

    # ------------------------------------------------------------------ sign-in hardening (the 2026-10-24 audit)
    def test_sign_out_is_a_sign_out_on_this_side_too(self):
        """The cookie opened the dashboard for 30 days after a sign-out. One password is one session for every phone and
        computer: a sign-out raises the session generation, so every cookie minted before it is dead, and the login page
        says so. A sign-out without a live cookie (anyone on the tailnet) is refused and changes nothing for whoever is
        signed in."""
        c = self.signed_in()
        old = c.cookies.get(COOKIE)
        self.assertEqual(c.get("/", follow_redirects=False).status_code, 200)
        r = c.post("/logout", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/login?bye=1"))
        self.assertEqual(settings_get(self.conn, "dashboard.session_generation"), "1")
        self.assertIn("Signed out everywhere", c.get("/login?bye=1").text)
        c.cookies.set(COOKIE, old)
        self.assertEqual(c.get("/", follow_redirects=False).status_code, 307, "the old cookie is dead")
        self.assertEqual(c.post("/calendar/save", data={"name": "Con"}).status_code, 401)
        c.cookies.set(COOKIE, make_token("chris"))
        self.assertEqual(TestClient(create_app()).post("/logout", follow_redirects=False).status_code, 401)
        self.assertEqual(settings_get(self.conn, "dashboard.session_generation"), "1")
        self.assertEqual(c.get("/", follow_redirects=False).status_code, 200, "a sign-out without a live cookie ends no session")

    def test_a_cookie_past_thirty_days_is_dead_as_before(self):
        self.client.cookies.set(COOKIE, make_token("chris", now=time.time() - (SESSION_DAYS + 1) * 86400))
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 307)
        self.client.cookies.set(COOKIE, make_token("chris", now=time.time() - (SESSION_DAYS - 1) * 86400))
        self.assertEqual(self.client.get("/", follow_redirects=False).status_code, 200)

    def hash_in_env_file(self, password):
        """The hash where the Mini keeps it, in .env, not the process environment (which would win over a change)."""
        config.write_env({"DASHBOARD_PASSWORD_HASH": auth.hash_password(password)})
        os.environ.pop("DASHBOARD_PASSWORD_HASH", None)
        config.reset()

    def test_the_password_changes_only_with_the_current_one_and_signs_the_other_devices_out(self):
        """The form took the new password twice and nothing else, and the old cookie opened the dashboard after the change."""
        self.hash_in_env_file("correct horse")
        c = self.signed_in()
        here, phone = c.cookies.get(COOKIE), make_token("chris", now=time.time() - 60)       # the phone signed in a minute ago
        page = c.get("/keys").text
        self.assertIn('name="current" autocomplete="current-password"', page)
        self.assertLess(page.index('name="current"'), page.index('name="password"'), "the current one first")
        new = {"password": "a new password", "confirm": "a new password"}
        for wrong in ({"current": "nope", **new}, new):
            r = c.post("/keys/password", data=wrong, follow_redirects=False)
            self.assertIn("current+password+did+not+match", r.headers["location"])
            self.assertNotIn(COOKIE, r.cookies)
        config.reset()
        self.assertTrue(auth.verify_password("correct horse", config.getenv("DASHBOARD_PASSWORD_HASH")), "nothing changed")
        for cookie in (here, phone):
            c.cookies.clear()           # one cookie at a time: a Set-Cookie leaves its own in the jar beside a set() one
            c.cookies.set(COOKIE, cookie)
            self.assertEqual(c.get("/keys", follow_redirects=False).status_code, 200, "both still signed in")
        c.cookies.clear()
        c.cookies.set(COOKIE, here)
        r = c.post("/keys/password", data={"current": "correct horse", **new}, follow_redirects=False)
        self.assertIn("Password+changed", r.headers["location"])
        self.assertIn(COOKIE, r.cookies, "this browser gets a fresh cookie")
        self.assertNotEqual(r.cookies[COOKIE], here)
        self.assertEqual(c.get("/keys", follow_redirects=False).status_code, 200, "and stays in")
        for dead in (here, phone):
            c.cookies.clear()
            c.cookies.set(COOKIE, dead)
            self.assertEqual(c.get("/keys", follow_redirects=False).status_code, 307, "every other device is signed out")
        anon = TestClient(create_app())
        self.assertIn("bad=1", anon.post("/login", data={"password": "correct horse"}, follow_redirects=False).headers["location"])
        self.assertEqual(anon.post("/login", data={"password": "a new password"}, follow_redirects=False).headers["location"], "/")

    def test_sign_out_everywhere_ends_every_session_and_asks_first(self):
        c = self.signed_in()
        here, laptop = c.cookies.get(COOKIE), make_token("chris", now=time.time() - 3600)
        form = re.search(r'<form[^>]*action="/keys/sign-out-everywhere"[^>]*>', c.get("/keys").text).group(0)
        self.assertIn("confirm(", form, "destructive: it asks first")
        r = c.post("/keys/sign-out-everywhere", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/login?bye=1"))
        for dead in (here, laptop):
            c.cookies.clear()
            c.cookies.set(COOKIE, dead)
            self.assertEqual(c.get("/keys", follow_redirects=False).status_code, 307)
        self.assertEqual(TestClient(create_app()).post("/keys/sign-out-everywhere").status_code, 401, "signed in only")
        self.assertEqual(c.post("/login", data={"password": "correct horse"}, follow_redirects=False).headers["location"], "/")
        self.assertEqual(c.get("/keys", follow_redirects=False).status_code, 200, "signing in again works")

    def test_a_post_from_another_page_is_refused_before_any_route(self):
        """SameSite=lax alone let a page beside the dashboard post to it. The page that sent the form (Origin, else
        Referer) must be on this dashboard's own host, the one the request came to; a client that sends neither (curl,
        the ntfy app) is not a browser and goes on to the route's own guard."""
        c = self.signed_in()
        q = self.draft()
        for headers in ({"Origin": "https://evil.example"}, {"Referer": "https://evil.example/a"}, {"Origin": "null"},
                        {"Origin": "https://evil.example", "Referer": "http://testserver/"}):
            r = c.post(f"/queue/{q}/skip", headers=headers, follow_redirects=False)
            self.assertEqual(r.status_code, 403, headers)
            self.assertIn("not from this dashboard", r.text)
            self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (q,))["status"], "draft")
        for headers in ({"Origin": "http://testserver"}, {"Referer": "http://testserver/calendar"}, {}):
            self.assertEqual(c.post("/calendar/save", data={"name": "Con"}, headers=headers, follow_redirects=False).status_code, 303, headers)
        tail = "mac-mini.tail915d2c.ts.net:8443"      # the phone's address: the same rule by that name, case apart
        self.assertEqual(c.post("/calendar/save", data={"name": "Con"}, follow_redirects=False,
                                headers={"Host": tail, "Origin": "https://MAC-MINI.tail915d2c.ts.net:8443"}).status_code, 303)
        self.assertEqual(c.post("/calendar/save", data={"name": "Con"}, follow_redirects=False,
                                headers={"Host": tail, "Origin": "http://testserver"}).status_code, 403)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) AS n FROM conventions")["n"], 4)
        self.assertEqual(c.get("/", headers={"Origin": "https://evil.example"}).status_code, 200, "a GET is never refused for it")
        anon = TestClient(create_app())
        self.assertEqual(anon.post("/login", data={"password": "correct horse"}, headers={"Origin": "https://evil.example"}).status_code, 403,
                         "the sign-in form too, before the password is looked at")

    def test_the_pings_one_tap_buttons_pass_the_same_site_rule(self):
        """The ntfy app's Post now, Follow the pace and Skip are POSTs with the ping's single-use token and no Origin or
        Referer (a native app, not a browser): they reach the route, whose guard is the token. The approve page's own
        buttons come from the dashboard's address. From another site's page they are refused like every other POST."""
        popen = self.popen()
        anon = TestClient(create_app())

        def token_for(qid):
            return approve_token.issue(self.conn, db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,)))

        def status(qid):
            return db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (qid,))["status"]
        q = self.draft()
        token = token_for(q)
        r = anon.post(f"/queue/{q}/choose-by-token/skip", data={"token": token}, headers={"Origin": "https://evil.example"})
        self.assertEqual((r.status_code, status(q)), (403, "draft"))
        self.assertEqual(anon.post(f"/queue/{q}/choose-by-token/skip", data={"token": "nonsense"}).status_code, 409, "reached the route")
        r = anon.post(f"/queue/{q}/choose-by-token/skip", content=f"token={token}",
                      headers={"Content-Type": "application/x-www-form-urlencoded"})         # as the ntfy app sends it
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(f"Skipped post {q}", r.text)
        self.assertEqual(status(q), "rejected")
        self.assertEqual(popen.call_args[0][0][-2:], ["run", "content"])
        other = self.draft()
        r = anon.post(f"/queue/{other}/choose-by-token/skip", data={"token": token_for(other)}, headers={"Origin": "http://testserver"})
        self.assertEqual((r.status_code, status(other)), (200, "rejected"))

    def test_the_drive_sign_in_starts_on_a_post_only(self):
        c = self.signed_in()
        self.assertEqual(c.get("/drive/login", follow_redirects=False).status_code, 405, "a GET starts nothing")
        self.assertIn('<form method="post" action="/drive/login"', c.get("/").text, "Today's card: one tap, a POST")
