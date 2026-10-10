"""Booking: requests in from the site, replies Chris approves, booked dates out. No network."""
from __future__ import annotations

import json
import os
import re
import types
from pathlib import Path

from fastapi.testclient import TestClient

from convention_social import offer
from convention_social.agents import inbox
from convention_social.ai import copy_rules, reply
from convention_social.booking.remote import SiteAPI
from convention_social.core import auth, config, db, runner, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase

REPO = Path(__file__).resolve().parents[1]


class FakeSite:
    def __init__(self, items=()):
        self.items = list(items)
        self.calls = []
        self.days = None

    def __call__(self, method, url, headers, payload):
        assert headers["Authorization"] == "Bearer tok"
        self.calls.append((method, url, payload))
        path = url.split("eventcaliber.com", 1)[1]
        if method == "GET" and path == "/api/inquiries":
            data = {"inquiries": self.items}
        elif path == "/api/inquiries/ack":
            ids = set(payload["ids"])
            self.items = [i for i in self.items if i["id"] not in ids]
            data = {"deleted": len(ids)}
        elif path == "/api/availability":
            self.days = payload["booked"]
            data = {"booked": len(self.days)}
        else:
            raise AssertionError(path)
        return types.SimpleNamespace(json=lambda: data)


REQ = {"id": "r1", "received_at": "2026-10-09T20:00:00Z", "name": "Dana Lee", "email": "dana@example.org",
       "organization": "Sample Con", "event_name": "Sample Con 2027", "event_kind": "fan", "start_date": "2027-03-05",
       "end_date": "2027-03-07", "city": "Baltimore", "coverage": ["backstage", "on_site_delivery"], "message": "Hi"}


class Inbox(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def ctx(self, dry=True):
        config.get_config().ensure_dirs()
        return runner.Context("inbox", self.conn, __import__("logging").getLogger("t"), config.get_config(), dry, 0)

    def test_pull_store_ack_and_template_draft(self):
        site = FakeSite([REQ, dict(REQ, id="r2", email="")])
        api = SiteAPI("tok", base="https://eventcaliber.com", transport=site)
        line = inbox.run(self.ctx(), api=api)
        self.assertIn("requests new=1", line)
        rows = db.rows(self.conn, "SELECT * FROM inquiries")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["status"], r["reply_status"]), ("drafted", "draft"))
        self.assertIn(reply.QUOTE_MARK, r["reply_body"])
        self.assertIn("Approved images delivered on site", r["reply_body"])
        # only the stored request was acked; the bad one stays on the site
        self.assertEqual([i["id"] for i in site.items], ["r2"])
        # a second pull of the same id does not duplicate
        site.items.append(REQ)
        inbox.run(self.ctx(), api=api)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM inquiries")["n"], 1)

    def test_claude_draft_never_writes_a_price(self):
        row = self._stored()

        class Fake:
            def __init__(self, body):
                self.body = body
                self.beta = self
                self.messages = self

            def create(self, **kw):
                assert kw["fallbacks"] == "default"
                t = types.SimpleNamespace(type="text", text=json.dumps({"subject": "Photography for Sample Con", "body": self.body}))
                return types.SimpleNamespace(content=[t], stop_reason="end_turn", model=kw["model"],
                                             usage=types.SimpleNamespace(input_tokens=900, output_tokens=300))
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        good = reply.draft(self.conn, row, client=Fake(f"Hi Dana,\nThanks for asking.\n{reply.QUOTE_MARK}\nChris"))
        self.assertEqual(good.model, "claude-opus-5")
        priced = reply.draft(self.conn, row, client=Fake("Hi Dana, coverage is $1,500 a day.\nChris"))
        self.assertEqual(priced.model, "template")       # a drafted price is thrown away
        self.assertNotIn("$", priced.body)
        claimed = reply.draft(self.conn, row, client=Fake("Hi Dana, trusted by the biggest cons.\nChris"))
        self.assertEqual(claimed.model, "template")

    def _stored(self):
        inbox.store(self.conn, REQ)
        return db.one(self.conn, "SELECT * FROM inquiries")

    def test_ready_to_send(self):
        self.assertIn("quote line", reply.ready_to_send("s", f"hi\n{reply.QUOTE_MARK}"))
        self.assertIsNone(reply.ready_to_send("Photography for Sample Con", "Hi Dana, three days of coverage is 2400 dollars.\nChris"))
        self.assertIn("dash", reply.ready_to_send("s", "Hi — there"))
        self.assertIn("tie to the event", reply.ready_to_send("s", "As the official photographer of the show"))

    def test_send_only_what_was_approved_and_dry_run_writes_eml(self):
        self._stored()
        self.conn.execute("UPDATE inquiries SET reply_subject='Photography for Sample Con', reply_body='Hi Dana, here it is.\nChris', reply_status='draft'")
        stats = inbox.send_approved(self.ctx())
        self.assertEqual(stats, {"sent": 0, "would_send": 0, "failed": 0, "held": 0})
        self.conn.execute("UPDATE inquiries SET reply_status='approved'")
        stats = inbox.send_approved(self.ctx())
        self.assertEqual(stats["would_send"], 1)
        eml = sorted((config.get_config().data_root / "outbox-dry").glob("*.eml"))
        self.assertEqual(len(eml), 1)
        text = eml[0].read_text()
        self.assertIn("dana@example.org", text)
        self.assertIn("a brand of CKI, LLC", text)

    def test_reply_edited_back_to_a_quote_mark_is_held(self):
        self._stored()
        self.conn.execute("UPDATE inquiries SET reply_subject='s', reply_body=?, reply_status='approved'", (f"x {reply.QUOTE_MARK}",))
        self.assertEqual(inbox.send_approved(self.ctx())["held"], 1)
        self.assertEqual(db.one(self.conn, "SELECT reply_status FROM inquiries")["reply_status"], "draft")

    def test_availability_dates_only_and_dry_run_holds(self):
        now = db.utcnow()
        db.insert(self.conn, "bookings", title="Secret client", start_date="2027-03-05", end_date="2027-03-07", status="booked",
                  created_at=now, updated_at=now)
        db.insert(self.conn, "bookings", title="Maybe", start_date="2027-04-01", end_date="2027-04-01", status="hold",
                  created_at=now, updated_at=now)
        site = FakeSite()
        api = SiteAPI("tok", base="https://eventcaliber.com", transport=site)
        self.assertIn("dry run", inbox.sync_availability(self.ctx(dry=True), api))
        self.assertIsNone(site.days)
        self.assertIn("3 booked", inbox.sync_availability(self.ctx(dry=False), api))
        self.assertEqual(site.days, ["2027-03-05", "2027-03-06", "2027-03-07"])
        self.assertNotIn("Secret", json.dumps(site.calls))
        self.assertEqual(inbox.sync_availability(self.ctx(dry=False), api), "calendar unchanged")


class OfferFile(IsolatedCase):
    def test_offer_has_no_price_and_matches_the_site_form(self):
        o = offer.load()
        self.assertTrue(o["coverage"])
        self.assertTrue(copy_rules.check(json.dumps(o)).ok, "the offer file must never carry a price")
        js = (REPO / "worker" / "index.js").read_text()
        worker_keys = set(re.findall(r'"([a-z_]+)"', re.search(r"const COVERAGE = \[([^\]]+)\]", js).group(1)))
        self.assertEqual(worker_keys, set(offer.coverage_keys()))


class BookingPages(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.c = TestClient(create_app())
        self.c.cookies.set(COOKIE, make_token("chris"))
        self.conn = db.connect()
        inbox.store(self.conn, REQ)
        self.iid = db.one(self.conn, "SELECT id FROM inquiries")["id"]
        d = reply.template_draft(db.one(self.conn, "SELECT * FROM inquiries"))
        self.conn.execute("UPDATE inquiries SET reply_subject=?, reply_body=?, reply_status='draft'", (d.subject, d.body))

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_pages_render(self):
        for path in ("/inquiries", "/inquiries?show=all", f"/inquiries/{self.iid}", "/bookings"):
            r = self.c.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("<main>", r.text)
        self.assertIn("Deposit links are off", self.c.get(f"/inquiries/{self.iid}").text)

    def test_approve_refused_until_the_quote_line_is_filled(self):
        r = self.c.post(f"/inquiries/{self.iid}/approve", follow_redirects=False)
        self.assertIn("not_ready", r.headers["location"])
        body = db.one(self.conn, "SELECT reply_body FROM inquiries")["reply_body"].replace(reply.QUOTE_MARK, "Three days of coverage: 2400 dollars.")
        self.c.post(f"/inquiries/{self.iid}/reply", data={"subject": "Photography for Sample Con 2027", "body": body})
        r = self.c.post(f"/inquiries/{self.iid}/approve", follow_redirects=False)
        self.assertIn("approved", r.headers["location"])
        self.assertEqual(db.one(self.conn, "SELECT reply_status FROM inquiries")["reply_status"], "approved")

    def test_book_dates_from_a_request(self):
        self.c.post("/bookings/add", data={"title": "Sample Con", "start_date": "2027-03-05", "end_date": "2027-03-07",
                                           "status": "booked", "inquiry_id": str(self.iid)})
        self.assertEqual(db.one(self.conn, "SELECT status FROM inquiries")["status"], "booked")
        self.assertEqual(inbox.booked_days(self.conn), ["2027-03-05", "2027-03-06", "2027-03-07"])
        self.assertEqual(self.c.post("/bookings/add", data={"title": "x", "start_date": "2027-03-07", "end_date": "2027-03-01"}).status_code, 400)
