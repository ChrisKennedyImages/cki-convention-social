"""The organizer's email is read off the event's own website, carefully (Chris, 2026-10-30: "Not one outreach email
has been sent"; "It should search for these emails")."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from convention_social.core import db
from convention_social.outreach import emails, keys
from tests._base import IsolatedCase

HOME = "<html><title>Sample Con</title><a href='mailto:webmaster@wixpress.com'>x</a> <img src='a@b.png'></html>"
CONTACT = "<p>Press: <a href='mailto:Press@SampleCon.example'>Press@SampleCon.example</a> or info@samplecon.example; not ours: hello@othersite.example</p>"


class Site:
    """A fake event site: {path: (status, body)}; every fetch is recorded, and refusals are a status."""
    def __init__(self, pages: dict):
        self.pages, self.fetched = pages, []

    def __call__(self, url: str):
        self.fetched.append(url)
        path = url.split("samplecon.example", 1)[-1] or "/"
        status, body = self.pages.get(path.rstrip("/") or "/", (404, None))
        if status in emails.REFUSED:
            return None, url, True
        return (body if status == 200 else None), url, False


def no_sleep(_s):
    pass


class Discover(IsolatedCase):
    def test_the_contact_page_gives_the_public_address_on_the_sites_own_domain(self):
        site = Site({"/": (200, HOME), "/contact": (200, CONTACT)})
        found = emails.discover("https://www.samplecon.example/", budget=[40], fetch=site, sleep=no_sleep)
        self.assertEqual((found.email, found.page), ("press@samplecon.example", "https://samplecon.example/contact"))
        self.assertEqual(site.fetched, ["https://samplecon.example", "https://samplecon.example/contact"], "the home page first, then the contact page, then it stops")

    def test_an_organizers_domain_counts_as_the_events_own(self):
        self.assertTrue(emails.own_address("meetings@aha.org", "annualmeeting.aha.org"))
        self.assertFalse(emails.own_address("hello@othersite.example", "samplecon.example"))
        self.assertEqual(emails.addresses("a: events@samplecon.example b: info@samplecon.example c: zz@samplecon.example", "samplecon.example"),
                         ["events@samplecon.example", "info@samplecon.example", "zz@samplecon.example"], "press and events before info, and before the rest")

    def test_a_named_persons_address_waits_for_a_role_address_on_a_later_page(self):
        site = Site({"/": (200, "web by paul.clark@samplecon.example"), "/contact": (200, CONTACT)})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=site, sleep=no_sleep)
        self.assertEqual(found.email, "press@samplecon.example", "the role address on the contact page, not the person on the home page")
        only_person = Site({"/": (200, "web by paul.clark@samplecon.example")})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=only_person, sleep=no_sleep)
        self.assertEqual((found.email, found.page), ("paul.clark@samplecon.example", "https://samplecon.example"), "kept when nothing better turns up anywhere")
        self.assertEqual(len(only_person.fetched), len(emails.PROBE_PATHS), "every page was read first")
        team = Site({"/": (200, "a.b@samplecon.example c.d@samplecon.example e.f@samplecon.example g.h@samplecon.example")})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=team, sleep=no_sleep)
        self.assertEqual(found.email, "", "several people named: no one is picked for them")
        self.assertEqual(found.note, "no role address; people named on https://samplecon.example: a.b@samplecon.example, c.d@samplecon.example, e.f@samplecon.example; pick one by hand")

    def test_the_events_own_page_is_read_first_when_the_site_is_the_organizers(self):
        site = Site({"/conference/sample-con": (200, "<a href='mailto:events@samplecon.example'>x</a>"), "/": (200, HOME)})
        found = emails.discover("https://www.samplecon.example/conference/sample-con/", budget=[40], fetch=site, sleep=no_sleep)
        self.assertEqual((found.email, found.page), ("events@samplecon.example", "https://samplecon.example/conference/sample-con"))
        self.assertEqual(site.fetched, ["https://samplecon.example/conference/sample-con"])

    def test_a_page_that_lands_on_another_site_is_not_the_events(self):
        def elsewhere(url):
            # every page of the event's site redirects to an affiliate that prints an address on the event's domain
            return "write to ashe@samplecon.example", "https://affiliate.example/press", False
        found = emails.discover("https://annual.samplecon.example", budget=[40], fetch=elsewhere, sleep=no_sleep)
        self.assertEqual(found.email, "")
        self.assertIn("sends readers to another site (https://affiliate.example/press)", found.note)
        self.assertTrue(emails.own_host("aha.org", "annualmeeting.aha.org"), "the organizer's own site is still the event's")

    def test_a_refusal_stops_the_walk_and_is_said(self):
        site = Site({"/": (403, None)})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=site, sleep=no_sleep)
        self.assertEqual(found.email, "")
        self.assertIn("refused an automated read", found.note)
        self.assertEqual(len(site.fetched), 1)

    def test_a_dead_site_a_form_only_site_and_a_spent_budget_each_say_why(self):
        self.assertIn("did not answer", emails.discover("https://samplecon.example", budget=[40], fetch=Site({}), sleep=no_sleep).note)
        self.assertIn("may use a form", emails.discover("https://samplecon.example", budget=[40], fetch=Site({"/": (200, HOME)}), sleep=no_sleep).note)
        budget = [1]
        found = emails.discover("https://samplecon.example", budget=budget, fetch=Site({"/": (200, HOME), "/contact": (200, CONTACT)}), sleep=no_sleep)
        self.assertIn("budget", found.note)
        self.assertEqual(budget, [0])


class Lookup(IsolatedCase):
    def event(self, name, website, *, email=None, start=30):
        conn = self.conn
        now = db.utcnow()
        start_date = (datetime.now(timezone.utc).date() + timedelta(days=start)).isoformat()
        return db.insert(conn, "scout_events", dedup_key=keys.event_key(name, start_date), name_key=keys.name_key(name), name=name,
                         kind="business", start_date=start_date, city="Washington, DC", website=website, organizer="Sample Events LLC",
                         organizer_email=email, sources=json.dumps([website]), status="new", found_at=now, updated_at=now)

    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def test_events_without_an_address_are_read_once_soonest_first_and_the_result_is_kept(self):
        a = self.event("Sample Con 2027", "https://samplecon.example", start=20)
        b = self.event("Other Con 2027", "https://othercon.example", start=10)
        c = self.event("Has One 2027", "https://has.example", email="x@has.example")
        site = Site({"/": (200, HOME), "/contact": (200, CONTACT)})
        stats = emails.lookup_missing(self.conn, fetch=site, sleep=no_sleep)
        self.assertEqual(stats, {"looked": 2, "found": 1, "refused": 0})
        row = db.one(self.conn, "SELECT * FROM scout_events WHERE id=?", (a,))
        self.assertEqual((row["organizer_email"], row["email_source_url"]), ("press@samplecon.example", "https://samplecon.example/contact"))
        self.assertTrue(row["email_checked_at"])
        other = db.one(self.conn, "SELECT * FROM scout_events WHERE id=?", (b,))
        self.assertIsNone(other["organizer_email"])
        self.assertIn("did not answer", other["email_note"])
        self.assertEqual(site.fetched[0], "https://othercon.example", "the sooner event is read first")
        self.assertIsNone(db.one(self.conn, "SELECT email_checked_at FROM scout_events WHERE id=?", (c,))["email_checked_at"], "an event with an address is left alone")
        self.assertEqual(emails.lookup_missing(self.conn, fetch=site, sleep=no_sleep), {"looked": 0, "found": 0, "refused": 0}, "each event once")

    def test_a_walk_cut_short_by_the_budget_leaves_the_event_for_the_next_run(self):
        a = self.event("Sample Con 2027", "https://samplecon.example", start=20)
        b = self.event("Other Con 2027", "https://othercon.example", start=30)
        site = Site({"/": (200, HOME), "/contact": (200, CONTACT)})
        stats = emails.lookup_missing(self.conn, budget=[1], fetch=site, sleep=no_sleep)
        self.assertEqual(stats, {"looked": 0, "found": 0, "refused": 0})
        self.assertEqual(site.fetched, ["https://samplecon.example"], "one page, then the run stops")
        for ev in (a, b):
            row = db.one(self.conn, "SELECT email_checked_at, email_note FROM scout_events WHERE id=?", (ev,))
            self.assertEqual((row["email_checked_at"], row["email_note"]), (None, None), "not marked: it is first in line next run")

    def test_an_address_on_the_do_not_contact_list_is_never_kept(self):
        self.event("CPAC Texas 2027", "https://samplecon.example")
        site = Site({"/": (200, "write to media@conservative.org")})
        emails.lookup_missing(self.conn, fetch=site, sleep=no_sleep)
        row = db.one(self.conn, "SELECT organizer_email, email_note FROM scout_events")
        self.assertIsNone(row["organizer_email"])
        self.assertTrue(row["email_note"])
