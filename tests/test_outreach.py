"""Outreach: drafts only, Chris approves, every send carries what the law asks, opt-outs win. No network."""
from __future__ import annotations

import json
import logging
import os
from unittest import mock
import re
import sqlite3
import types
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from convention_social.agents import outreach
from convention_social.ai import copy_rules, spend
from convention_social.core import auth, config, db, runner
from convention_social.dashboard import scout_outreach_routes
from convention_social.dashboard.app import COOKIE, conn_dep, create_app, make_token, render, require_user
from convention_social.outreach import compliance, draft, keys
from convention_social.outreach.site import UnsubscribeAPI
from tests._base import IsolatedCase
from tests._fakes import read_mail

NS = types.SimpleNamespace
FROM = "hello@eventcaliber.com"
POSTAL = "PO Box 100, Annapolis, MD 21401"
DASHES = re.compile(r"[‐-―−]|\s-{1,2}\s")
FACTS = {"event_name": "Sample Con 2027", "event_kind": "fan", "start_date": "2027-03-05", "end_date": "2027-03-07",
         "city": "Baltimore", "venue": "Convention Center", "organizer": "Sample Events LLC"}


class FakeSite:
    """The Worker's opt-out store: GET /api/unsubscribes and POST /api/unsubscribes/ack."""

    def __init__(self, tokens=(), fail=False):
        self.items = [{"token": t, "received_at": "2026-10-09T12:00:00Z"} for t in tokens]
        self.acked = []
        self.fail = fail

    def __call__(self, method, url, headers, payload):
        assert headers["Authorization"] == "Bearer tok"
        if self.fail:
            raise ConnectionError("site down")
        path = url.split("eventcaliber.com", 1)[1]
        if method == "GET" and path == "/api/unsubscribes":
            data = {"unsubscribes": list(self.items)}
        elif method == "POST" and path == "/api/unsubscribes/ack":
            self.acked += payload["tokens"]
            self.items = [i for i in self.items if i["token"] not in payload["tokens"]]
            data = {"deleted": len(payload["tokens"])}
        else:
            raise AssertionError(path)
        return NS(json=lambda: data)


class OutreachCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        for key in ("OUTREACH_DAILY_DRAFTS", "OUTREACH_DAILY_SENDS", "OUTREACH_MODEL", "AI_MONTHLY_CAP_USD", "SITE_BASE_URL"):
            os.environ.pop(key, None)
        os.environ["BRAND_FROM_EMAIL"] = FROM
        os.environ["BRAND_POSTAL_ADDRESS"] = POSTAL
        config.reset()
        self.conn = db.connect()
        self.today = datetime.now(timezone.utc).date()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def ctx(self, dry=True):
        config.get_config().ensure_dirs()
        return runner.Context("outreach", self.conn, logging.getLogger("t"), config.get_config(), dry, 0)

    def api(self, site=None):
        return UnsubscribeAPI("tok", base="https://eventcaliber.com", transport=site or FakeSite())

    def day(self, n):
        return (self.today + timedelta(days=n)).isoformat()

    def scout_event(self, name="Sample Con 2027", email="press@samplecon.example", start=40, status="new", kind="fan"):
        now = db.utcnow()
        start_date = self.day(start) if start is not None else None
        return db.insert(self.conn, "scout_events", dedup_key=keys.event_key(name, start_date), name_key=keys.name_key(name),
                         name=name, kind=kind, start_date=start_date, city="Baltimore", website="https://samplecon.example",
                         organizer="Sample Events LLC", organizer_email=email, email_source_url="https://samplecon.example/contact",
                         sources=json.dumps(["https://samplecon.example"]), status=status, found_at=now, updated_at=now)

    def row(self, *, email="press@samplecon.example", status="approved", body=None, subject="Photography for Sample Con 2027",
            kind="first", parent_id=None, sent_at=None, name="Sample Con 2027"):
        now = db.utcnow()
        d = draft.template_first(dict(FACTS, event_name=name))
        return db.insert(self.conn, "outreach", kind=kind, parent_id=parent_id, event_key=keys.event_key(name, "2027-03-05"),
                         event_name=name, event_kind="fan", start_date="2027-03-05", email=email, subject=subject,
                         body=body if body is not None else d.body, status=status, token=keys.new_token(), model="template",
                         drafted_at=now, approved_at=now if status == "approved" else None, sent_at=sent_at,
                         created_at=now, updated_at=now)

    def outbox(self):
        return sorted((config.get_config().data_root / "outbox-dry").glob("*.eml"))

    def status(self, oid):
        return db.one(self.conn, "SELECT status FROM outreach WHERE id=?", (oid,))["status"]


# ---------------------------------------------------------------------- drafting
class Drafting(OutreachCase):
    def test_template_is_specific_plain_and_clean(self):
        d = draft.template_first(FACTS)
        self.assertTrue(d.body)
        self.assertEqual(d.subject, "Photography for Sample Con 2027")
        # Chris, 2026-10-31: "Here is what I want it to say Specifically and this should be the template for all of them."
        self.assertEqual(d.body, "\n".join([
            "Hello,", "",
            "I'm reaching out regarding Sample Con 2027, taking place March 5–7, 2027, in Baltimore.", "",
            "We're local convention and event photographers offering a unique service: delivering photos to attendees while the "
            "event is still underway. We can provide this service to all attendees or exclusively to your staff, depending on your preference.", "",
            "For an event like yours, we can cover keynotes and main-stage presentations, breakout sessions and panels, dinners and "
            "receptions, and portraits. We also offer flexible coverage before, during, and into the evening to accommodate your event schedule.", "",
            "Do you already have a photographer lined up for March? If not, I'd love to hear a little about your plans so I can put "
            "together a quote tailored to your needs.", "",
            "Chris", "Event Caliber"]))
        for word in ("face match", "facematch", "selfie", "badge", "every photo they are in"):
            self.assertNotIn(word, d.body.lower(), "Chris, 2026-10-12: delivery is a feature, never the name or the steps")
        self.assertTrue(copy_rules.check(d.subject + "\n" + d.body).ok)
        self.assertEqual(compliance.text_problems(d.subject, d.body), [])
        # his dates carry an en dash; no other dash anywhere (the copy rules refuse a dash used as punctuation)
        self.assertEqual(re.findall(r"\S*[‐-―−]\S*", d.body + d.subject), ["5–7,"])
        self.assertEqual(draft.dates_as_chris_writes_them("2027-03-30", "2027-04-02"), "March 30–April 2, 2027")
        self.assertEqual(draft.dates_as_chris_writes_them("2026-12-31", "2027-01-02"), "December 31, 2026–January 2, 2027")
        self.assertEqual(draft.dates_as_chris_writes_them("2027-03-11", ""), "March 11, 2027")
        self.assertEqual(draft.dates_as_chris_writes_them("someday", "2027-03-11"), "")
        self.assertNotRegex(d.body.lower(), r"official|client|\$|price")
        # the word for their event comes off its name; the month off its first day; nothing is said that is not known
        self.assertIn("while the meeting is still underway", draft.template_first({"event_name": "AMWA 112th Annual Meeting"}).body)
        self.assertIn("while the show is still underway", draft.template_first({"event_name": "Small Business Expo"}).body)
        bare = draft.template_first({"event_name": "Sample Con"}).body
        self.assertIn("I'm reaching out regarding Sample Con.\n", bare)
        self.assertIn("Do you already have a photographer lined up? If not,", bare)
        self.assertEqual(draft.template_first({"event_name": "Expo - Washington, D.C.", "city": "Washington, DC"}).subject,
                         "Photography for Expo, Washington, D.C.")
        f = draft.template_follow_up(FACTS)
        self.assertEqual(compliance.text_problems(f.subject, f.body), [])
        self.assertIn("Sample Con 2027", f.body)


class Agent(OutreachCase):
    def test_drafts_from_scout_finds_with_an_email_and_never_sends_them(self):
        self.scout_event()
        self.scout_event(name="No Email Con", email=None)
        self.scout_event(name="Dismissed Con", email="x@dismissed.example", status="dismissed")
        self.scout_event(name="Past Con", email="x@past.example", start=-3)
        line = outreach.run(self.ctx(), api=self.api())
        rows = db.rows(self.conn, "SELECT * FROM outreach")
        self.assertEqual(len(rows), 1, line)
        r = rows[0]
        self.assertEqual((r["status"], r["email"], r["kind"], r["model"]), ("draft", "press@samplecon.example", "first", "template"))
        self.assertRegex(r["token"], r"^[a-f0-9]{32}$")
        self.assertIn("drafted=1", line)
        self.assertEqual(self.outbox(), [])               # a draft is never sent
        outreach.run(self.ctx(dry=False), api=self.api())
        self.assertEqual(self.outbox(), [])
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM outreach")["n"], 1)   # one note per prospect per event

    def test_first_notes_claude_wrote_are_rewritten_in_the_template_unless_chris_touched_them(self):
        now = db.utcnow()
        common = dict(kind="first", event_key="k", event_name="Sample Con 2027", event_kind="business", start_date="2027-03-05",
                      end_date="2027-03-07", city="Baltimore", email="press@samplecon.example", subject="Photography for Sample Con 2027",
                      status="draft", model="claude-opus-5", drafted_at=now, created_at=now)
        untouched = db.insert(self.conn, "outreach", body="Hello,\n\nI am Chris, a convention and event photographer.\n\nChris\nEvent Caliber",
                              updated_at=now, token=keys.new_token(), **common)
        edited = db.insert(self.conn, "outreach", body="Hello,\n\nChris wrote this himself.\n\nChris\nEvent Caliber",
                           updated_at="2026-10-31T14:00:00+00:00", token=keys.new_token(), **{**common, "email": "other@samplecon.example"})
        line = outreach.run(self.ctx(), api=self.api())
        self.assertIn("rewritten in the template=1", line)
        a = db.one(self.conn, "SELECT body, model, updated_at FROM outreach WHERE id=?", (untouched,))
        self.assertEqual(a["body"], draft.template_first({"event_name": "Sample Con 2027", "start_date": "2027-03-05", "end_date": "2027-03-07", "city": "Baltimore"}).body)
        self.assertEqual(a["model"], "template")
        self.assertEqual(db.one(self.conn, "SELECT body FROM outreach WHERE id=?", (edited,))["body"], "Hello,\n\nChris wrote this himself.\n\nChris\nEvent Caliber")
        self.assertIn("rewritten in the template=0", outreach.run(self.ctx(), api=self.api()), "once")

    def test_daily_draft_cap(self):
        for i in range(7):
            self.scout_event(name=f"Con {i}", email=f"press{i}@con{i}.example", start=30 + i)
        line = outreach.run(self.ctx(), api=self.api())
        self.assertIn("drafted=5", line)
        self.assertIn("left for tomorrow=2", line)
        line = outreach.run(self.ctx(), api=self.api())
        self.assertIn("drafted=0", line)
        os.environ["OUTREACH_DAILY_DRAFTS"] = "6"
        config.reset()
        self.assertIn("drafted=1", outreach.run(self.ctx(), api=self.api()))

    def test_do_not_contact_is_checked_before_drafting(self):
        self.scout_event()
        compliance.block(self.conn, "PRESS@samplecon.example", source="reply")
        line = outreach.run(self.ctx(), api=self.api())
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM outreach"))
        self.assertIn("on do-not-contact=1", line)

    def test_one_address_is_not_drafted_twice_for_two_events_at_once(self):
        self.scout_event(name="Spring Con")
        self.scout_event(name="Fall Con", start=200)
        outreach.run(self.ctx(), api=self.api())
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM outreach")["n"], 1)

    def test_drafted_notes_ping_the_phone_once_to_the_outreach_page(self):
        """6.2 (2026-10-13): a note drafted for his Approve used to wait unseen."""
        self.scout_event()
        with mock.patch.object(outreach.notify, "push") as push:
            outreach.run(self.ctx(), api=self.api())
        self.assertEqual(push.call_count, 1)
        args, kw = push.call_args
        self.assertIn("1 organizer note", args[1])
        self.assertTrue(kw["click"].endswith("/outreach"))
        self.assertIs(kw["conn"], self.conn)
        with mock.patch.object(outreach.notify, "push") as push:
            outreach.run(self.ctx(), api=self.api())
        self.assertEqual(push.call_count, 0, "nothing new drafted, no ping")

    def test_prospects_added_by_hand_are_drafted(self):
        now = db.utcnow()
        oid = db.insert(self.conn, "outreach", event_key=keys.event_key("Hand Con", None), event_name="Hand Con", email="a@hand.example",
                        status="queued", token=keys.new_token(), created_at=now, updated_at=now)
        outreach.run(self.ctx(), api=self.api())
        r = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (oid,))
        self.assertEqual(r["status"], "draft")
        self.assertIn("Hand Con", r["body"])


# ---------------------------------------------------------------------- never CPAC, never the ACU
class NeverContacted(OutreachCase):
    """Chris, 2026-10-13: "never outreach to CPAC or the ACU or any affiliates! NEVER and that's a hard rule."
    The rule is code: no page can remove it, and it is checked at the scout, the drafter, the send and the hand add."""

    def test_the_rule_is_code_not_a_list(self):
        for email, names, urls in (("press@cpac.org", (), ()), ("Media@CPAC.Conservative.org", (), ()),
                                   ("hello@texascpac.com", (), ()), ("info@acuf.org", (), ()),
                                   ("events@sample.org", ("CPAC 2027",), ()), ("events@sample.org", ("Sample Expo", "American Conservative Union"), ()),
                                   ("events@sample.org", ("Conservative Political Action Conference",), ()),
                                   ("events@sample.org", ("Sample Expo",), ("https://www.conservative.org/cpac/2027",)),
                                   ("events@sample.org", ("Regional Conservative Union Gala",), ())):
            why = compliance.never_contact(email=email, names=names, urls=urls)
            self.assertIsNotNone(why, (email, names, urls))
            self.assertIn("never contacted", why)
        for email, names, urls in (("events@sample.org", ("Sample Con 2027", "Sample Events LLC"), ("https://samplecon.example",)),
                                   ("hello@acupuncture-summit.example", ("Acupuncture Summit",), ()),
                                   ("x@vacuum.example", ("Vacuum Tech Expo",), ()), ("", (), ())):
            self.assertIsNone(compliance.never_contact(email=email, names=names, urls=urls), (email, names, urls))

    def test_scout_finds_and_hand_prospects_are_never_drafted(self):
        self.scout_event(name="CPAC 2027", email="press@samplecon.example")
        self.scout_event(name="Sample Con 2027", email="press@samplecon.example", start=50)
        now = db.utcnow()
        hand = db.insert(self.conn, "outreach", event_key=keys.event_key("Hand Con", None), event_name="Hand Con", email="press@cpac.org",
                         status="queued", token=keys.new_token(), created_at=now, updated_at=now)
        line = outreach.run(self.ctx(), api=self.api())
        drafted = db.rows(self.conn, "SELECT * FROM outreach WHERE status='draft'")
        self.assertEqual([r["event_name"] for r in drafted], ["Sample Con 2027"], line)
        r = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (hand,))
        self.assertEqual(r["status"], "rejected")
        self.assertIn("never contacted", r["notes"])
        self.assertIn("never contacted=2", line)

    def test_an_approved_note_is_refused_at_send(self):
        oid = self.row(email="Media@CPAC.Conservative.org", status="approved")
        named = self.row(email="events@sample.org", status="approved", name="CPAC 2027")
        line = outreach.run(self.ctx(), api=self.api())
        for rid in (oid, named):
            r = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (rid,))
            self.assertEqual(r["status"], "rejected", line)
            self.assertIn("never contacted", r["notes"])
        self.assertEqual(self.outbox(), [])
        self.assertIn("never=2", line)

    def test_no_follow_up_either(self):
        sent = (datetime.now(timezone.utc) - timedelta(days=9)).replace(microsecond=0).isoformat()
        oid = self.row(email="press@cpac.org", status="sent", sent_at=sent)
        why = compliance.follow_up_allowed(self.conn, db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (oid,)))
        self.assertIsNotNone(why)
        self.assertIn("never contacted", why)


# ---------------------------------------------------------------------- sending
class Sending(OutreachCase):
    def test_approved_dry_run_writes_a_compliant_email(self):
        oid = self.row()
        token = db.one(self.conn, "SELECT token FROM outreach")["token"]
        line = outreach.run(self.ctx(), api=self.api())
        self.assertIn("would_send=1", line)
        self.assertEqual(self.status(oid), "would_send")
        files = self.outbox()
        self.assertEqual(len(files), 1)
        msg, html, plain = read_mail(files[0])
        self.assertEqual(msg["From"], FROM)
        self.assertEqual(msg["To"], "press@samplecon.example")
        self.assertEqual(msg["Subject"], "Photography for Sample Con 2027")
        unsub = f"https://eventcaliber.com/unsubscribe?t={token}"
        self.assertEqual(msg["List-Unsubscribe"], f"<mailto:{FROM}?subject=unsubscribe>, <{unsub}>")
        self.assertEqual(msg["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click")
        for part in (plain, html):
            self.assertIn(POSTAL, part)
            self.assertIn(unsub, part)
            self.assertIn("reply STOP", part)
            self.assertIn("a brand of CKI, LLC", part)
        self.assertNotIn("samplecon.example", unsub)                     # the address never rides in the link
        self.assertTrue(copy_rules.check(plain.split(POSTAL)[0]).ok)

    def test_drafts_never_send(self):
        oid = self.row(status="draft")
        outreach.send_approved(self.ctx(dry=False), opt_outs_synced=True)
        self.assertEqual((self.status(oid), self.outbox()), ("draft", []))

    def test_no_postal_address_means_nothing_sends(self):
        oid = self.row()
        os.environ["BRAND_POSTAL_ADDRESS"] = ""
        config.reset()
        stats = outreach.send_approved(self.ctx(), opt_outs_synced=True)
        self.assertEqual(stats["held"], 1)
        self.assertEqual((self.status(oid), self.outbox()), ("approved", []))
        self.assertIn("BRAND_POSTAL_ADDRESS", db.one(self.conn, "SELECT notes FROM outreach")["notes"])

    def test_the_sender_must_be_on_the_company_domain(self):
        oid = self.row()
        for sender in ("", "chris@gmail.example"):
            os.environ["BRAND_FROM_EMAIL"] = sender
            config.reset()
            self.assertEqual(outreach.send_approved(self.ctx(), opt_outs_synced=True)["held"], 1, sender)
        self.assertEqual((self.status(oid), self.outbox()), ("approved", []))

    def test_do_not_contact_is_checked_again_before_sending(self):
        oid = self.row()
        self.conn.execute("INSERT INTO do_not_contact (email, source, added_at) VALUES ('press@samplecon.example', 'reply', ?)", (db.utcnow(),))
        stats = outreach.send_approved(self.ctx(dry=False), opt_outs_synced=True)
        self.assertEqual(stats["opted_out"], 1)
        self.assertEqual((self.status(oid), self.outbox()), ("opted_out", []))

    def test_edited_into_a_broken_rule_goes_back_to_draft(self):
        oid = self.row(body="Hello,\nThree days for $2,000.\nChris\nEvent Caliber")
        other = self.row(email="b@other.example", body="Hello,\nOur past clients include big shows.\nChris\nEvent Caliber", name="Other Con")
        stats = outreach.send_approved(self.ctx(), opt_outs_synced=True)
        self.assertEqual(stats["redrafted"], 2)
        self.assertEqual((self.status(oid), self.status(other), self.outbox()), ("draft", "draft", []))

    def test_daily_send_cap(self):
        for i in range(12):
            self.row(email=f"p{i}@con{i}.example", name=f"Con {i}")
        stats = outreach.send_approved(self.ctx(), opt_outs_synced=True)
        self.assertEqual((stats["would_send"], stats["over_cap"]), (10, 2))
        self.assertEqual(len(self.outbox()), 10)
        self.assertEqual(outreach.send_approved(self.ctx(), opt_outs_synced=True)["would_send"], 0)
        os.environ["OUTREACH_DAILY_SENDS"] = "11"
        config.reset()
        self.assertEqual(outreach.send_approved(self.ctx(), opt_outs_synced=True)["would_send"], 1)

    def test_live_sends_hold_when_opt_outs_cannot_be_checked(self):
        oid = self.row()
        line = outreach.run(self.ctx(dry=False), api=None)      # no MEDIA_UPLOAD_TOKEN in tests
        self.assertIn("no MEDIA_UPLOAD_TOKEN", line)
        self.assertEqual((self.status(oid), self.outbox()), ("approved", []))
        line = outreach.run(self.ctx(dry=False), api=self.api(FakeSite(fail=True)))
        self.assertIn("not pulled (ConnectionError)", line)
        self.assertEqual((self.status(oid), self.outbox()), ("approved", []))
        outreach.run(self.ctx(dry=False), api=self.api())
        self.assertEqual(len(self.outbox()), 1)     # a test process can never reach SMTP; core.mail writes the .eml

    def test_follow_up_only_after_seven_days_and_only_one(self):
        now = datetime.now(timezone.utc)
        first = self.row(status="sent", sent_at=(now - timedelta(days=3)).replace(microsecond=0).isoformat())
        r = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (first,))
        self.assertIn("7 days", compliance.follow_up_allowed(self.conn, r))
        self.assertIsNone(compliance.follow_up_allowed(self.conn, r, now=now + timedelta(days=5)))
        # a follow-up approved too early waits, still approved
        f = self.row(kind="follow_up", parent_id=first, subject="Following up: photography for Sample Con 2027",
                     body=draft.template_follow_up(FACTS).body)
        stats = outreach.send_approved(self.ctx(), opt_outs_synced=True)
        self.assertEqual((stats["held"], self.status(f), self.outbox()), (1, "approved", []))
        self.conn.execute("UPDATE outreach SET sent_at=? WHERE id=?", ((now - timedelta(days=8)).replace(microsecond=0).isoformat(), first))
        self.assertEqual(outreach.send_approved(self.ctx(), opt_outs_synced=True)["would_send"], 1)
        r = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (first,))
        self.assertIn("already has its one follow-up", compliance.follow_up_allowed(self.conn, r))
        with self.assertRaises(sqlite3.IntegrityError):     # the table itself refuses a second follow-up
            self.row(kind="follow_up", parent_id=first, status="draft")


class OptOuts(OutreachCase):
    def test_pulled_tokens_put_the_address_on_do_not_contact(self):
        sent = self.row(status="sent")
        open_note = self.row(status="draft", name="Second Con")
        token = db.one(self.conn, "SELECT token FROM outreach WHERE id=?", (sent,))["token"]
        site = FakeSite([token, "f" * 32, "not-a-token"])
        line = outreach.run(self.ctx(), api=self.api(site))
        self.assertIn("opt-outs pulled=2 blocked=1 unknown=1 acked=2", line)
        dnc = db.one(self.conn, "SELECT * FROM do_not_contact")
        self.assertIsNotNone(dnc)
        self.assertEqual((dnc["email"], dnc["source"]), ("press@samplecon.example", "unsubscribe"))
        self.assertEqual(self.status(open_note), "opted_out")
        self.assertEqual(self.status(sent), "sent")
        self.assertEqual(sorted(site.acked), sorted([token, "f" * 32]))

    def test_the_link_carries_a_token_never_the_address(self):
        token = keys.new_token()
        self.assertRegex(token, r"^[a-f0-9]{32}$")
        self.assertNotEqual(token, keys.new_token())
        url = compliance.unsubscribe_url(token)
        self.assertEqual(url, f"https://eventcaliber.com/unsubscribe?t={token}")
        self.assertNotIn("@", url)


# ---------------------------------------------------------------------- dashboard
class Pages(OutreachCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        app = create_app()
        if not any(getattr(r, "path", "") == "/outreach" for r in app.routes):
            scout_outreach_routes.register(app, require_user, conn_dep, render)
        self.c = TestClient(app)
        self.c.cookies.set(COOKIE, make_token("chris"))

    def test_pages_render(self):
        oid = self.row(status="draft")
        for path in ("/outreach", f"/outreach/{oid}", "/outreach/donotcontact"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("<main>", r.text, path)
        detail = self.c.get(f"/outreach/{oid}").text
        self.assertIn(POSTAL, detail)
        self.assertIn("unsubscribe?t=", detail)
        self.assertIn("List-Unsubscribe=One-Click", detail)
        self.assertEqual(self.c.get("/outreach/999").status_code, 404)

    def test_approve_is_refused_while_a_rule_is_broken(self):
        oid = self.row(status="draft", body="Hello,\nIt is $500 a day.\nChris\nEvent Caliber")
        r = self.c.post(f"/outreach/{oid}/approve", follow_redirects=False)
        self.assertIn("not_ready", r.headers["location"])
        self.assertEqual(self.status(oid), "draft")
        self.c.post(f"/outreach/{oid}/save", data={"subject": "Photography for Sample Con 2027", "body": draft.template_first(FACTS).body})
        r = self.c.post(f"/outreach/{oid}/approve", follow_redirects=False)
        self.assertIn("approved", r.headers["location"])
        self.assertEqual(self.status(oid), "approved")
        # editing an approved note sends it back to draft
        self.c.post(f"/outreach/{oid}/save", data={"subject": "Photography for Sample Con 2027", "body": "Hello again.\nChris"})
        self.assertEqual(self.status(oid), "draft")

    def test_approve_is_refused_without_a_postal_address(self):
        oid = self.row(status="draft")
        os.environ["BRAND_POSTAL_ADDRESS"] = ""
        config.reset()
        self.assertIn("not_ready", self.c.post(f"/outreach/{oid}/approve", follow_redirects=False).headers["location"])
        self.assertIn("BRAND_POSTAL_ADDRESS", self.c.get(f"/outreach/{oid}").text)
        self.assertEqual(self.status(oid), "draft")

    def test_a_prospect_chris_writes_himself_is_left_alone_by_the_agent(self):
        self.c.post("/outreach/add", data={"event_name": "Hand Con", "email": "org@hand.example"})
        oid = db.one(self.conn, "SELECT id FROM outreach")["id"]
        self.c.post(f"/outreach/{oid}/save", data={"subject": "Photography for Hand Con", "body": "Hello,\nMy own words.\nChris"})
        outreach.run(self.ctx(), api=self.api())
        r = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (oid,))
        self.assertEqual((r["status"], r["body"], r["model"]), ("draft", "Hello,\nMy own words.\nChris", "chris"))

    def test_save_and_approve_in_one_tap(self):
        """4.1 (2026-10-13): one form, two buttons; the compliance gates still hold on the way."""
        oid = self.row(status="draft", body="Hello,\nIt is $500 a day.\nChris\nEvent Caliber")
        self.assertIn('name="do" value="approve"', self.c.get(f"/outreach/{oid}").text)
        r = self.c.post(f"/outreach/{oid}/save", data={"subject": "Photography for Sample Con 2027", "body": "Hello,\nStill $500 a day.\nChris",
                                                       "do": "approve"}, follow_redirects=False)
        self.assertIn("not_ready", r.headers["location"])
        self.assertEqual(self.status(oid), "draft")
        self.assertIn("Still $500", db.one(self.conn, "SELECT body FROM outreach WHERE id=?", (oid,))["body"], "saved all the same")
        r = self.c.post(f"/outreach/{oid}/save", data={"subject": "Photography for Sample Con 2027", "body": draft.template_first(FACTS).body,
                                                       "do": "approve"}, follow_redirects=False)
        self.assertIn("approved", r.headers["location"])
        self.assertEqual(self.status(oid), "approved")

    def test_the_page_shows_the_caps_and_the_do_not_contact_count(self):
        page = self.c.get("/outreach").text
        self.assertIn("up to 5 organizer drafts and 10 approved sends a day", page)
        self.assertIn("0 addresses on the do-not-contact list", page)
        compliance.block(self.conn, "stop@example.org", source="reply")
        self.assertIn("1 address on the do-not-contact list", self.c.get("/outreach").text)

    def test_reject(self):
        oid = self.row(status="draft")
        self.c.post(f"/outreach/{oid}/reject")
        self.assertEqual(self.status(oid), "rejected")
        self.assertIn("locked", self.c.post(f"/outreach/{oid}/save", data={"subject": "x", "body": "y"},
                                            follow_redirects=False).headers["location"])

    def test_add_a_prospect_by_hand(self):
        data = {"event_name": "Hand Con", "email": "Org@Hand.example", "kind": "business", "start_date": "2027-05-01"}
        self.assertIn("queued", self.c.post("/outreach/add", data=data, follow_redirects=False).headers["location"])
        r = db.one(self.conn, "SELECT * FROM outreach")
        self.assertIsNotNone(r)
        self.assertEqual((r["status"], r["email"], r["event_kind"], r["start_date"]), ("queued", "org@hand.example", "business", "2027-05-01"))
        self.assertIn("exists", self.c.post("/outreach/add", data=data, follow_redirects=False).headers["location"])
        self.assertIn("bad_prospect", self.c.post("/outreach/add", data=dict(data, email="nope"), follow_redirects=False).headers["location"])
        compliance.block(self.conn, "x@blocked.example")
        self.assertIn("blocked", self.c.post("/outreach/add", data=dict(data, email="x@blocked.example"),
                                             follow_redirects=False).headers["location"])

    def test_cpac_and_the_acu_are_refused_on_every_page(self):
        data = {"event_name": "Hand Con", "email": "press@cpac.org"}
        self.assertIn("never", self.c.post("/outreach/add", data=data, follow_redirects=False).headers["location"])
        self.assertIn("never", self.c.post("/outreach/add", data={"event_name": "CPAC 2027", "email": "org@hand.example"},
                                           follow_redirects=False).headers["location"])
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM outreach"))
        oid = self.row(status="draft", name="CPAC 2027", email="events@sample.org")
        page = self.c.get(f"/outreach/{oid}").text
        self.assertIn("never contacted", page)
        self.assertNotIn(f"/outreach/{oid}/approve", page)
        self.assertIn("not_ready", self.c.post(f"/outreach/{oid}/approve", follow_redirects=False).headers["location"])
        self.assertEqual(self.status(oid), "draft")
        dnc = self.c.get("/outreach/donotcontact").text
        self.assertIn("CPAC", dnc)
        self.assertIn("cannot be removed", dnc)

    def test_do_not_contact_closes_open_notes(self):
        oid = self.row(status="approved")
        self.c.post("/outreach/donotcontact/add", data={"email": "PRESS@samplecon.example", "source": "reply", "reason": "said STOP"})
        self.assertEqual(self.status(oid), "opted_out")
        row = db.one(self.conn, "SELECT * FROM do_not_contact")
        self.assertEqual((row["email"], row["source"], row["reason"]), ("press@samplecon.example", "reply", "said STOP"))
        self.assertIn("press@samplecon.example", self.c.get("/outreach/donotcontact").text)
        self.c.post(f"/outreach/donotcontact/{row['id']}/remove")
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM do_not_contact"))

    def test_follow_up_button(self):
        first = self.row(status="sent", sent_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        r = self.c.post(f"/outreach/{first}/followup", follow_redirects=False)
        self.assertIn("no_follow_up", r.headers["location"])
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM outreach WHERE kind='follow_up'"))
        old = (datetime.now(timezone.utc) - timedelta(days=8)).replace(microsecond=0).isoformat()
        self.conn.execute("UPDATE outreach SET sent_at=? WHERE id=?", (old, first))
        r = self.c.post(f"/outreach/{first}/followup", follow_redirects=False)
        f = db.one(self.conn, "SELECT * FROM outreach WHERE kind='follow_up'")
        self.assertIsNotNone(f)
        self.assertIn(f"/outreach/{f['id']}", r.headers["location"])
        self.assertEqual((f["status"], f["parent_id"], f["email"]), ("draft", first, "press@samplecon.example"))
        self.assertNotEqual(f["token"], db.one(self.conn, "SELECT token FROM outreach WHERE id=?", (first,))["token"])
        self.assertIn("no_follow_up", self.c.post(f"/outreach/{first}/followup", follow_redirects=False).headers["location"])
        self.assertIn("approved", self.c.post(f"/outreach/{f['id']}/approve", follow_redirects=False).headers["location"])
