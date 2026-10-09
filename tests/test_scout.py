"""The scout: region gate, dry run makes no paid call, nothing kept without a source, emails only from the event's own site. No network."""
from __future__ import annotations

import json
import logging
import os
import types
from datetime import timedelta

from fastapi.testclient import TestClient

from convention_social.agents import scout
from convention_social.ai import spend
from convention_social.core import auth, config, db, runner
from convention_social.dashboard import scout_outreach_routes
from convention_social.dashboard.app import COOKIE, conn_dep, create_app, make_token, render, require_user
from convention_social.outreach import research
from tests._base import IsolatedCase

NS = types.SimpleNamespace


def resp(content, stop="end_turn", searches=0, model="claude-opus-5-5"):
    return NS(content=content, stop_reason=stop, model=model,
              usage=NS(input_tokens=2000, output_tokens=800, server_tool_use=NS(web_search_requests=searches)))


def search_block(*urls):
    return NS(type="web_search_tool_result", tool_use_id="srv1",
              content=[NS(type="web_search_result", url=u, title="t", encrypted_content="x", page_age=None) for u in urls])


def search_error(code="max_uses_exceeded"):
    return NS(type="web_search_tool_result", tool_use_id="srv2", content=NS(type="web_search_tool_result_error", error_code=code))


def text(t, citations=None):
    return NS(type="text", text=t, citations=citations)


def cite(url, quoted):
    return NS(type="web_search_result_location", url=url, cited_text=quoted, encrypted_index="e", title="t")


def answer(events):
    return "Here is what I found.\n\n```json\n" + json.dumps({"events": events}) + "\n```\n"


class FakeClaude:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if not self.responses:
            raise AssertionError("no more canned responses")
        return self.responses.pop(0)


def ev(name, start, **kw):
    base = {"name": name, "kind": "fan", "start_date": start, "end_date": "", "city": "Baltimore", "venue": "",
            "website": "", "organizer": "", "organizer_email": "", "email_source_url": "", "sources": []}
    base.update(kw)
    return base


class ScoutCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        for key in ("SCOUT_REGION", "SCOUT_MONTHS", "SCOUT_MODEL", "SCOUT_EFFORT", "AI_MONTHLY_CAP_USD"):
            os.environ.pop(key, None)
        os.environ["SCOUT_REGION"] = "Washington DC, Maryland, Virginia"
        config.reset()
        self.conn = db.connect()
        self.today = scout.local_today(config.get_config())

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def ctx(self, dry=False):
        config.get_config().ensure_dirs()
        return runner.Context("scout", self.conn, logging.getLogger("t"), config.get_config(), dry, 0)

    def day(self, n):
        return (self.today + timedelta(days=n)).isoformat()


class Gates(ScoutCase):
    def test_no_region_does_nothing_and_says_where_to_set_it(self):
        os.environ.pop("SCOUT_REGION")
        config.reset()
        fake = FakeClaude()
        line = scout.run(self.ctx(), client=fake)
        self.assertIn("SCOUT_REGION", line)
        self.assertIn("Keys page", line)
        self.assertEqual(fake.calls, [])

    def test_dry_run_makes_no_paid_call(self):
        fake = FakeClaude(resp([text(answer([]))]))
        line = scout.run(self.ctx(dry=True), client=fake)
        self.assertIn("DRY RUN", line)
        self.assertIn("Washington DC", line)
        self.assertEqual(fake.calls, [])
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM api_usage"))

    def test_no_key_no_call(self):
        line = scout.run(self.ctx())
        self.assertIn("no ANTHROPIC_API_KEY", line)

    def test_cap_reached_no_call(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "1"
        config.reset()
        spend.record(self.conn, "content", "claude-opus-5-5", 1_000_000, 0)
        fake = FakeClaude()
        self.assertIn("cap reached", scout.run(self.ctx(), client=fake))
        self.assertEqual(fake.calls, [])

    def test_horizon_and_months(self):
        os.environ["SCOUT_MONTHS"] = "3"
        config.reset()
        self.assertEqual(scout.months(), 3)
        self.assertEqual(scout.horizon(scout.date(2026, 11, 30), 3).isoformat(), "2027-02-28")
        os.environ["SCOUT_MONTHS"] = "nonsense"
        config.reset()
        self.assertEqual(scout.months(), 9)


class Research(ScoutCase):
    SITE = "https://www.samplecon.example/"
    CONTACT = "https://samplecon.example/contact"
    LISTING = "https://listings.example/events/sample-con"

    def good_run(self):
        events = [
            ev("Sample Con 2027", self.day(40), end_date=self.day(42), website=self.SITE, organizer="Sample Events LLC",
               organizer_email="Press@SampleCon.example", email_source_url=self.CONTACT, sources=[self.LISTING, self.SITE]),
            ev("Made Up Expo", self.day(50), sources=["https://never-searched.example/expo"]),        # no seen source: dropped
            ev("Other Site Email Con", self.day(60), website="https://othercon.example", organizer_email="boss@gmail.example",
               email_source_url="https://listings.example/events/other", sources=[self.LISTING]),     # email not from own site
            ev("Already Over Con", self.day(-5), sources=[self.LISTING]),                                # past: dropped
            ev("Far Future Con", self.day(400), sources=[self.LISTING]),                                 # beyond horizon: dropped
            ev("Fuzzy Date Summit", "sometime in May", kind="business", sources=[self.LISTING]),         # kept, no date
            ev("Sample Con 2027", self.day(40), sources=[self.SITE]),                                    # duplicate
            ev("Invented Site Con", self.day(70), website="https://invented.example", sources=[self.LISTING]),
            ev("", self.day(20), sources=[self.LISTING]),
        ]
        first = resp([search_block(self.SITE, self.LISTING, self.CONTACT, "https://othercon.example/"),
                      search_error(), text(answer(events))], searches=3)
        return FakeClaude(first)

    def test_live_research_call_shape(self):
        fake = self.good_run()
        scout.run(self.ctx(), client=fake)
        self.assertEqual(len(fake.calls), 1)
        kw = fake.calls[0]
        self.assertEqual(kw["model"], "claude-opus-5-5")
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["thinking"], {"type": "adaptive"})
        self.assertEqual(kw["output_config"], {"effort": "medium"})
        self.assertEqual(kw["tools"], [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}])
        self.assertIn("Washington DC, Maryland, Virginia", kw["messages"][0]["content"])

    def test_only_sourced_events_are_kept_and_emails_only_from_their_own_site(self):
        line = scout.run(self.ctx(), client=self.good_run())
        rows = {r["name"]: r for r in db.rows(self.conn, "SELECT * FROM scout_events")}
        self.assertTrue(rows, line)
        self.assertEqual(set(rows), {"Sample Con 2027", "Other Site Email Con", "Fuzzy Date Summit", "Invented Site Con"})
        sample = rows["Sample Con 2027"]
        self.assertEqual(sample["status"], "new")
        self.assertEqual(sample["organizer_email"], "press@samplecon.example")
        self.assertEqual(sample["email_source_url"], self.CONTACT)
        self.assertEqual(json.loads(sample["sources"]), [self.LISTING, self.SITE])
        self.assertEqual(sample["end_date"], self.day(42))
        self.assertIsNone(rows["Other Site Email Con"]["organizer_email"])        # read on a listing, not their site
        self.assertIsNone(rows["Fuzzy Date Summit"]["start_date"])                 # not a date: left empty
        self.assertEqual(rows["Fuzzy Date Summit"]["kind"], "business")
        self.assertIsNone(rows["Invented Site Con"]["website"])                    # a site no search returned
        for word in ("no source 1", "past 1", "beyond horizon 1", "no name 1"):
            self.assertIn(word, line)
        self.assertIn("1 with an organizer email", line)
        # a web search error is recorded, not swallowed
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors")["kind"], "web_search")

    def test_spend_is_recorded_for_tokens_and_searches(self):
        scout.run(self.ctx(), client=self.good_run())
        rows = db.rows(self.conn, "SELECT * FROM api_usage ORDER BY id")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["unit_kind"], "tokens")
        self.assertIn("claude-opus-5-5", rows[0]["detail"])
        self.assertGreater(rows[0]["cost_usd"], 0)
        self.assertEqual((rows[1]["unit_kind"], rows[1]["units"]), ("web_searches", 3))
        self.assertAlmostEqual(rows[1]["cost_usd"], 0.03)

    def test_a_second_run_adds_no_duplicates(self):
        scout.run(self.ctx(), client=self.good_run())
        n = db.one(self.conn, "SELECT COUNT(*) n FROM scout_events")["n"]
        self.assertGreater(n, 0)
        line = scout.run(self.ctx(), client=self.good_run())
        self.assertIn(", 0 new", line)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM scout_events")["n"], n)

    def test_events_already_on_the_calendar_are_skipped(self):
        now = db.utcnow()
        db.insert(self.conn, "conventions", name="Sample Con 2027", start_date=self.day(40), created_at=now, updated_at=now)
        scout.run(self.ctx(), client=self.good_run())
        names = [r["name"] for r in db.rows(self.conn, "SELECT name FROM scout_events")]
        self.assertTrue(names)
        self.assertNotIn("Sample Con 2027", names)

    def test_email_quoted_by_a_citation_from_their_own_site_is_kept(self):
        events = [ev("Cited Con", self.day(30), website="https://citedcon.example", organizer_email="hello@citedcon.example",
                     sources=["https://citedcon.example/about"])]
        fake = FakeClaude(resp([search_block("https://citedcon.example/about"),
                                text("They list a contact.", [cite("https://citedcon.example/faq", "Write to hello@citedcon.example")]),
                                text(answer(events))]))
        scout.run(self.ctx(), client=fake)
        row = db.one(self.conn, "SELECT * FROM scout_events")
        self.assertIsNotNone(row)
        self.assertEqual(row["organizer_email"], "hello@citedcon.example")
        self.assertEqual(row["email_source_url"], "https://citedcon.example/faq")

    def test_search_errors_only_means_nothing_kept(self):
        fake = FakeClaude(resp([search_error("too_many_requests"), text(answer([ev("Ghost Con", self.day(30), sources=[self.SITE])]))]))
        line = scout.run(self.ctx(), client=fake)
        self.assertIn("no source URLs came back", line)
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM scout_events"))

    def test_pause_turn_is_resumed_with_the_same_turn(self):
        paused = resp([search_block(self.SITE)], stop="pause_turn", searches=1)
        done = resp([text(answer([ev("Sample Con 2027", self.day(40), sources=[self.SITE])]))], searches=0)
        fake = FakeClaude(paused, done)
        scout.run(self.ctx(), client=fake)
        self.assertEqual(len(fake.calls), 2)
        msgs = fake.calls[1]["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertIs(msgs[1]["content"][0], paused.content[0])
        self.assertEqual(db.one(self.conn, "SELECT name FROM scout_events")["name"], "Sample Con 2027")

    def test_refusal_stores_nothing(self):
        fake = FakeClaude(resp([search_block(self.SITE), text(answer([ev("X Con", self.day(30), sources=[self.SITE])]))], stop="refusal"))
        line = scout.run(self.ctx(), client=fake)
        self.assertIn("declined", line)
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM scout_events"))

    def test_unreadable_answer_gets_one_structuring_call(self):
        notes = text("Sample Con 2027 runs in Baltimore, see " + self.SITE + " (no JSON, sorry)")
        structured = resp([text(json.dumps({"events": [ev("Sample Con 2027", self.day(40), sources=[self.SITE])]}))])
        fake = FakeClaude(resp([search_block(self.SITE), notes]), structured)
        line = scout.run(self.ctx(), client=fake)
        self.assertEqual(len(fake.calls), 2)
        second = fake.calls[1]
        self.assertNotIn("tools", second)
        self.assertEqual(second["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(second["fallbacks"], "default")
        self.assertIn("structured by a second call", line)
        self.assertEqual(db.one(self.conn, "SELECT name FROM scout_events")["name"], "Sample Con 2027")

    def test_parse_events_is_defensive(self):
        self.assertIsNone(research.parse_events("no json here"))
        self.assertEqual(research.parse_events('```json\n{"events": [{"name": "A"}, 3]}\n```'), [{"name": "A"}])
        self.assertEqual(research.parse_events('text {"events": []} more'), [])
        self.assertEqual(research.canonical("HTTPS://WWW.Example.com/a/#x"), "https://example.com/a")
        self.assertEqual(research.canonical("javascript:alert(1)"), "")


class ScoutPages(ScoutCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        app = create_app()
        if not any(getattr(r, "path", "") == "/scout" for r in app.routes):
            scout_outreach_routes.register(app, require_user, conn_dep, render)
        self.c = TestClient(app)
        self.c.cookies.set(COOKIE, make_token("chris"))
        now = db.utcnow()
        self.sid = db.insert(self.conn, "scout_events", dedup_key=f"sample con|{self.day(40)}", name_key="sample con",
                             name="Sample Con", kind="other", start_date=self.day(40), end_date=self.day(41), city="Baltimore",
                             website="https://samplecon.example", sources=json.dumps(["https://samplecon.example"]),
                             status="new", found_at=now, updated_at=now)

    def test_page_renders_and_needs_sign_in(self):
        r = self.c.get("/scout")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<main>", r.text)
        self.assertIn("Sample Con", r.text)
        self.assertIn("Washington DC", r.text)
        self.c.cookies.clear()
        self.assertEqual(self.c.get("/scout", follow_redirects=False).status_code, 307)
        self.assertEqual(self.c.post(f"/scout/{self.sid}/add").status_code, 401)

    def test_add_to_calendar_never_ticks_attending_or_official(self):
        r = self.c.post(f"/scout/{self.sid}/add", follow_redirects=False)
        self.assertIn("msg=added", r.headers["location"])
        conv = db.one(self.conn, "SELECT * FROM conventions")
        self.assertIsNotNone(conv)
        self.assertEqual((conv["name"], conv["attending"], conv["official"], conv["kind"]), ("Sample Con", 0, 0, "unknown"))
        self.assertEqual(conv["url"], "https://samplecon.example")
        row = db.one(self.conn, "SELECT status, convention_id FROM scout_events")
        self.assertEqual((row["status"], row["convention_id"]), ("added", conv["id"]))
        self.c.post(f"/scout/{self.sid}/add")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM conventions")["n"], 1)

    def test_dismiss(self):
        self.c.post(f"/scout/{self.sid}/dismiss")
        self.assertEqual(db.one(self.conn, "SELECT status FROM scout_events")["status"], "dismissed")
        self.assertIn("Nothing here", self.c.get("/scout").text)
        self.assertIn("Sample Con", self.c.get("/scout?show=dismissed").text)
        self.assertEqual(self.c.post("/scout/999/dismiss").status_code, 404)
