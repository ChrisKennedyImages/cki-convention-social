"""Outreach: drafts only, Chris approves, every send carries what the law asks, opt-outs win. No network."""
from __future__ import annotations

import json
import logging
import os
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


class FakeClaude:
    def __init__(self, subject="Photography for Sample Con 2027", body=None, stop="end_turn"):
        self.subject = subject
        self.body = body if body is not None else (
            "Hello,\n\nI saw that Sample Con 2027 is coming to Baltimore on March 5. Do you have a photographer lined up yet?\n\n"
            "I cover cosplay portraits, the main stage and the exhibition hall, and can deliver approved images on site.\n\n"
            "Chris\nEvent Caliber")
        self.stop = stop
        self.calls = []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        t = NS(type="text", text=json.dumps({"subject": self.subject, "body": self.body}))
        return NS(content=[t], stop_reason=self.stop, model=kw["model"], usage=NS(input_tokens=900, output_tokens=300))


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
        for words in ("Sample Con 2027", "March 5 to 7, 2027", "Baltimore", "photographer lined up", "Cosplay portraits",
                      "Approved images", "quote"):
            self.assertIn(words.lower(), d.body.lower(), words)
        self.assertTrue(d.body.endswith("Chris\nEvent Caliber"))
        self.assertTrue(copy_rules.check(d.subject + "\n" + d.body).ok)
        self.assertEqual(compliance.text_problems(d.subject, d.body), [])
        self.assertIsNone(DASHES.search(d.body + d.subject))
        self.assertNotIn("-", d.body)                     # not even a hyphen: dates are written in words
        self.assertNotRegex(d.body.lower(), r"official|client|\$|price")
        f = draft.template_follow_up(FACTS)
        self.assertEqual(compliance.text_problems(f.subject, f.body), [])
        self.assertIn("Sample Con 2027", f.body)

    def test_claude_draft_call_shape_and_spend(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        fake = FakeClaude()
        d = draft.draft_first(self.conn, FACTS, client=fake)
        self.assertEqual(d.model, "claude-opus-5-5")
        self.assertIn("photographer lined up", d.body)
        kw = fake.calls[0]
        self.assertEqual((kw["betas"], kw["fallbacks"], kw["thinking"]), (["server-side-fallback-2026-07-01"], "default", {"type": "adaptive"}))
        self.assertEqual(kw["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(kw["output_config"]["effort"], "medium")
        self.assertIn("Sample Con 2027", kw["messages"][0]["content"])
        self.assertIn("Cosplay portraits", kw["messages"][0]["content"])      # coverage comes from offer.json
        self.assertGreater(spend.month_to_date(self.conn), 0)

    def test_a_draft_that_breaks_a_rule_is_thrown_away(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        bad = {"price": "Hello,\nCoverage starts at $900 a day.\nChris\nEvent Caliber",
               "official": "Hello,\nI was the official photographer of a big show.\nChris\nEvent Caliber",
               "clients": "Hello,\nOur past clients loved it.\nChris\nEvent Caliber",
               "covered": "Hello,\nI photographed your event before.\nChris\nEvent Caliber",
               "promise": "Hello,\nGuaranteed the best shots.\nChris\nEvent Caliber",
               "link": "Hello,\nSee https://eventcaliber.com for more.\nChris\nEvent Caliber"}
        for why, body in bad.items():
            d = draft.draft_first(self.conn, FACTS, client=FakeClaude(body=body))
            self.assertEqual(d.model, "template", why)
            self.assertIn("thrown away", d.note, why)
            self.assertEqual(compliance.text_problems(d.subject, d.body), [], why)
        d = draft.draft_first(self.conn, FACTS, client=FakeClaude(subject="Re: your show", body=FakeClaude().body))
        self.assertEqual(d.model, "template")
        refused = draft.draft_first(self.conn, FACTS, client=FakeClaude(stop="refusal"))
        self.assertEqual(refused.model, "template")

    def test_dashes_from_the_model_become_commas(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        body = "Hello,\nSample Con 2027 — what a weekend. Do you have a photographer lined up yet?\nChris\nEvent Caliber"
        d = draft.draft_first(self.conn, FACTS, client=FakeClaude(body=body))
        self.assertEqual(d.model, "claude-opus-5-5")
        self.assertIsNone(DASHES.search(d.body))

    def test_an_api_error_costs_one_claude_draft_not_the_run(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()

        class Down(FakeClaude):
            def create(self, **kw):
                raise ConnectionError("api down")
        d = draft.draft_first(self.conn, FACTS, client=Down())
        self.assertEqual(d.model, "template")
        self.assertIn("ConnectionError", d.note)
        self.assertEqual(compliance.text_problems(d.subject, d.body), [])

    def test_no_call_at_the_cap(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "1"
        config.reset()
        spend.record(self.conn, "content", "claude-opus-5-5", 1_000_000, 0)
        fake = FakeClaude()
        d = draft.draft_first(self.conn, FACTS, client=fake)
        self.assertEqual((d.model, fake.calls), ("template", []))
        self.assertIn("cap", d.note)


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

    def test_prospects_added_by_hand_are_drafted(self):
        now = db.utcnow()
        oid = db.insert(self.conn, "outreach", event_key=keys.event_key("Hand Con", None), event_name="Hand Con", email="a@hand.example",
                        status="queued", token=keys.new_token(), created_at=now, updated_at=now)
        outreach.run(self.ctx(), api=self.api())
        r = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (oid,))
        self.assertEqual(r["status"], "draft")
        self.assertIn("Hand Con", r["body"])


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
