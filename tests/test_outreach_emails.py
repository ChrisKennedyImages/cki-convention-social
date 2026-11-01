"""The organizer's address and the event's dates, read off the event's own website, carefully. No network: every
fetcher and every Claude client here is a stand-in.

Chris, 2026-10-30: "Not one outreach email has been sent"; "It should search for these emails". 2026-11-01: "Scrape other
avenues to find their actual emails" (a person's address before info@ or contact@), and "Look up their dates"."""
from __future__ import annotations

import json
import logging
import os
import types
from datetime import date, timedelta

from convention_social.agents import outreach, scout
from convention_social.ai import spend
from convention_social.core import config, db, runner
from convention_social.outreach import dates, draft, emails, keys
from tests._base import IsolatedCase

NS = types.SimpleNamespace
HOME = "<html><title>Sample Con</title><a href='mailto:webmaster@wixpress.com'>x</a> <img src='a@b.png'></html>"
CONTACT = "<p>Press: <a href='mailto:Press@SampleCon.example'>Press@SampleCon.example</a> or info@samplecon.example; not ours: hello@othersite.example</p>"


def cf(email: str, key: int = 0x42) -> str:
    """An address the way Cloudflare's email protection writes it into a page."""
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email)


class Site:
    """A fake event site: {path: (status, body)}; every fetch is recorded, and refusals are a status."""
    def __init__(self, pages: dict, host: str = "samplecon.example"):
        self.pages, self.fetched, self.host = pages, [], host

    def __call__(self, url: str):
        self.fetched.append(url)
        path = url.split(self.host, 1)[-1] or "/"
        status, body = self.pages.get(path.rstrip("/") or "/", (404, None))
        if status in emails.REFUSED:
            return None, url, True
        return (body if status == 200 else None), url, False


class Extraction(IsolatedCase):
    def test_the_addresses_a_page_hides_are_read_and_the_junk_is_not(self):
        page = (f'<p>Jane Doe <a href="/cdn-cgi/l/email-protection" class="__cf_email__" data-cfemail="{cf("jane.doe@samplecon.example")}">'
                f'[email&#160;protected]</a></p>'
                f'<a href="/cdn-cgi/l/email-protection#{cf("ann.lee@samplecon.example", 0x17)}">Write to Ann</a>'
                '<a href="mailto:%20bob.smith@samplecon.example?subject=Hello">Bob</a>'
                '<p>Events: events%40samplecon.example</p>'
                '<p>noreply@samplecon.example webmaster@samplecon.example careers@samplecon.example logo@2x.png '
                'x@sentry.io privacy@samplecon.example</p>'
                '<script>var a = "someone@cdn.example";</script>')
        self.assertEqual(emails.extract_emails(page), ["jane.doe@samplecon.example", "ann.lee@samplecon.example",
                                                       "bob.smith@samplecon.example", "events@samplecon.example",
                                                       "someone@cdn.example"],
                         "Cloudflare's protection decoded, a mailto unquoted, %40 read as @, in the order a reader meets "
                         "them; no-reply, webmaster, careers, privacy, images and a script library's address dropped")
        self.assertEqual(emails.addresses(page, "samplecon.example"),
                         ["jane.doe@samplecon.example", "ann.lee@samplecon.example", "bob.smith@samplecon.example",
                          "events@samplecon.example"], "only the event's own domain is kept")
        self.assertEqual(emails._cf_decode("zz"), "")
        # read on americascreditunions.org, 2026-11-01: a page's data escapes ">" as \u003e right before an address
        self.assertEqual(emails.extract_emails('<script>{"html":"\\u003ca href=\\u0022mailto:hello@acu.example\\u0022\\u003ehello@acu.example"}</script>'),
                         ["hello@acu.example"])

    def test_a_shared_inbox_is_told_from_a_persons_address(self):
        for role in ("info@x.org", "contact@x.org", "hello@x.org", "register@x.org", "registration@x.org", "registrar@x.org",
                     "events@x.org", "eventsteam@x.org", "info2027@x.org", "info.dc@x.org", "contactus@x.org", "press@x.org",
                     "cs@x.org", "membership@x.org", "meetings@x.org"):
            self.assertTrue(emails.is_role(role), role)
        for person in ("jane.doe@x.org", "jdoe@x.org", "associatedirector@amwa-doc.org", "priya@x.org", "hidy.lee@terrapinn.com",
                       "jlieberson@aplu.org"):
            self.assertFalse(emails.is_role(person), person)
        # an event's own inbox, and a mailbox with the organization's own name, are shared inboxes too (read 2026-11-01)
        for shared in ("gacinfo@americascreditunions.org", "amwaevents@amwa-doc.org", "mylegion@legion.org", "satshow2027@satshow.com",
                       "advocacy@americascreditunions.org", "governmentaffairs@x.org", "research@x.org"):
            self.assertTrue(emails.is_role(shared), shared)


class Discover(IsolatedCase):
    def test_a_persons_address_outranks_every_shared_inbox_found(self):
        site = Site({"/": (200, "<p>info@samplecon.example</p>"), "/contact": (200, CONTACT),
                     "/about": (200, "<p>Jane Doe, Director: jane.doe@samplecon.example</p>")})
        found = emails.discover("https://www.samplecon.example/", budget=[40], fetch=site)
        self.assertEqual((found.email, found.page, found.person), ("jane.doe@samplecon.example", "https://samplecon.example/about", True))
        self.assertEqual(len(site.fetched), len(emails.PROBE_PATHS), "every usual page was read before choosing")

    def test_a_shared_inbox_is_kept_only_when_no_person_turns_up_on_the_whole_walk(self):
        home = "<a href='/get-in-touch/'>Contact</a> <a href='/our-team/'>Team</a> info@samplecon.example"
        site = Site({"/": (200, home), "/contact": (200, CONTACT), "/our-team": (200, "<p>Our team works hard.</p>")})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=site)
        self.assertEqual((found.email, found.person), ("press@samplecon.example", False), "press before info when no person")
        self.assertIn("https://samplecon.example/our-team/", site.fetched, "the site's own team page, linked from home, is read too")
        self.assertEqual(site.fetched[:len(emails.PROBE_PATHS)], emails.probes("https://samplecon.example", "samplecon.example"))

    def test_the_sites_own_pages_are_followed_same_host_only(self):
        home = ("<a href='/leadership/'>Leadership</a> <a href='https://othersite.example/contact'>Partner</a> "
                "<a href='/news/'>News</a> <a href='/staff-directory.pdf'>Staff (PDF)</a> <a href='mailto:x@othersite.example'>x</a> "
                "<a href='https://www.samplecon.example/about/people#top'>People</a>")
        self.assertEqual(emails.contact_links(home, "https://samplecon.example/", "samplecon.example"),
                         ["https://www.samplecon.example/about/people", "https://samplecon.example/leadership/"],
                         "people before leadership (LINK_ORDER); another site, news, a PDF and a mailto are not followed")
        self.assertEqual(emails.contact_links("<a href='/about-us/financials'>x</a><a href='/about-us/'>About</a>"
                                              "<a href='/about-us/contact'>Contact</a>", "https://samplecon.example/", "samplecon.example"),
                         ["https://samplecon.example/about-us/contact", "https://samplecon.example/about-us/"],
                         "by the last part of the address: an about page's financials are not a contact page")
        site = Site({"/": (200, home), "/leadership": (200, "<p>Executive Director Mark Ray mark.ray@samplecon.example</p>")})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=site)
        self.assertEqual(found.email, "mark.ray@samplecon.example")
        self.assertFalse([u for u in site.fetched if "othersite" in u])

    def test_of_several_people_the_one_whose_words_say_events_else_the_first(self):
        """Chris's rule, 2026-11-01 as built: of several people named, the first whose name and title say events,
        meetings, conference, sponsorship, exhibits, partnerships or marketing; otherwise the first on the page."""
        team = ("<h2>Staff</h2><p>John Smith, Membership Manager, john.smith@samplecon.example</p>"
                "<p>Jane Doe, Director of Meetings and Events, jane.doe@samplecon.example</p>"
                "<p>Ann Lee, Sponsorship, ann.lee@samplecon.example</p>")
        found = emails.discover("https://samplecon.example", budget=[40], fetch=Site({"/": (200, team)}))
        self.assertEqual(found.email, "jane.doe@samplecon.example")
        plain = "<p>John Smith, Treasurer, john.smith@samplecon.example</p><p>Jane Doe, Editor, jane.doe@samplecon.example</p>"
        found = emails.discover("https://samplecon.example", budget=[40], fetch=Site({"/": (200, plain)}))
        self.assertEqual(found.email, "john.smith@samplecon.example", "no events words: the first on the page")
        for word in ("events", "Meeting", "conference", "Sponsorships", "exhibits", "Partnerships", "marketing"):
            self.assertTrue(emails.EVENTS_WORDS.search(f"Director of {word}"), word)

    def test_a_page_two_addresses_land_on_is_read_once(self):
        def landing(url):
            seen.append(url)
            path = url.split("samplecon.example", 1)[-1]
            final = "https://samplecon.example/about-us/" if path in ("/about", "/about-us") else url
            return ("<a href='/about-us/'>About</a> info@samplecon.example" if path in ("", "/about", "/about-us") else None), final, False
        seen: list[str] = []
        emails.discover("https://samplecon.example", budget=[40], fetch=landing)
        self.assertEqual(seen.count("https://samplecon.example/about-us"), 0, "/about landed on /about-us/: not read twice")
        self.assertEqual(seen.count("https://samplecon.example/about"), 1)

    def test_the_walk_ends_early_only_on_a_person_whose_words_say_events(self):
        site = Site({"/": (200, "<p>Conference Manager: Jane Doe jane.doe@samplecon.example</p>"), "/contact": (200, CONTACT)})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=site)
        self.assertEqual(found.email, "jane.doe@samplecon.example")
        self.assertEqual(site.fetched, ["https://samplecon.example"])

    def test_an_organizers_domain_counts_as_the_events_own(self):
        self.assertTrue(emails.own_address("meetings@aha.org", "annualmeeting.aha.org"))
        self.assertFalse(emails.own_address("hello@othersite.example", "samplecon.example"))

    def test_the_events_own_page_is_read_first_when_the_site_is_the_organizers(self):
        site = Site({"/conference/sample-con": (200, "<p>Events director: <a href='mailto:kim.park@samplecon.example'>Kim</a></p>"),
                     "/": (200, HOME)})
        found = emails.discover("https://www.samplecon.example/conference/sample-con/", budget=[40], fetch=site)
        self.assertEqual((found.email, found.page), ("kim.park@samplecon.example", "https://samplecon.example/conference/sample-con"))
        self.assertEqual(site.fetched, ["https://samplecon.example/conference/sample-con"])
        self.assertEqual(found.text_url, "https://samplecon.example/conference/sample-con", "its words are kept for the dates")

    def test_a_page_that_lands_on_another_site_is_not_the_events(self):
        def elsewhere(url):
            # every page of the event's site redirects to an affiliate that prints an address on the event's domain
            return "write to ashe@samplecon.example", "https://affiliate.example/press", False
        found = emails.discover("https://annual.samplecon.example", budget=[40], fetch=elsewhere)
        self.assertEqual(found.email, "")
        self.assertIn("sends readers to another site (https://affiliate.example/press)", found.note)

    def test_a_refusal_stops_the_walk_and_what_came_before_stands(self):
        site = Site({"/": (403, None)})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=site)
        self.assertEqual(found.email, "")
        self.assertTrue(found.note.startswith(emails.REFUSED_NOTE))
        self.assertEqual(len(site.fetched), 1)
        site = Site({"/": (200, "info@samplecon.example"), "/contact": (429, None)})
        found = emails.discover("https://samplecon.example", budget=[40], fetch=site)
        self.assertEqual(found.email, "info@samplecon.example")
        self.assertEqual(len(site.fetched), 2, "the server is left alone once it refuses")

    def test_an_address_not_to_be_written_to_is_passed_over(self):
        page = "<p>Events: jane.doe@samplecon.example</p><p>Sponsors: ann.lee@samplecon.example</p>"
        found = emails.discover("https://samplecon.example", budget=[40], fetch=Site({"/": (200, page)}),
                                refuse=lambda e: "on the do-not-contact list" if e.startswith("jane") else None)
        self.assertEqual(found.email, "ann.lee@samplecon.example")
        found = emails.discover("https://samplecon.example", budget=[40], fetch=Site({"/": (200, page)}), refuse=lambda e: "no")
        self.assertEqual(found.email, "")
        self.assertIn("not to be written to", found.note)

    def test_a_dead_site_a_form_only_site_and_a_spent_budget_each_say_why(self):
        self.assertIn("did not answer", emails.discover("https://samplecon.example", budget=[40], fetch=Site({})).note)
        self.assertIn("may use a form", emails.discover("https://samplecon.example", budget=[40], fetch=Site({"/": (200, HOME)})).note)
        budget = [1]
        found = emails.discover("https://samplecon.example", budget=budget, fetch=Site({"/": (200, HOME), "/contact": (200, CONTACT)}))
        self.assertEqual(found.note, emails.BUDGET_SPENT)
        self.assertEqual(budget, [0])

    def test_a_test_process_never_reaches_the_network(self):
        self.assertEqual(emails.fetch("https://samplecon.example/"), (None, "https://samplecon.example/", False))


class FakeClaude:
    """Answers each date read with the next canned answer; every call is recorded."""
    def __init__(self, *answers, model="claude-haiku-4-5"):
        self.answers, self.calls, self.model = list(answers), [], model
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        answer = self.answers.pop(0)
        return NS(content=[NS(type="text", text=json.dumps(answer))], stop_reason="end_turn", model=self.model,
                  usage=NS(input_tokens=3000, output_tokens=60))


class Dates(IsolatedCase):
    PAGE = "<h1>AMWA 2027 Annual Meeting</h1><p>Join us March 11–14, 2027 in Washington, DC. Hotel block closes February 1, 2027.</p>"
    TODAY = date(2026, 11, 1)

    def test_dates_are_kept_only_when_the_page_says_them_word_for_word(self):
        text = emails.page_text(self.PAGE)
        ok = dates.checked({"start_date": "2027-03-11", "end_date": "2027-03-14", "quote": "March 11–14, 2027"}, text, "u", self.TODAY)
        self.assertEqual((ok.start, ok.end, ok.note), ("2027-03-11", "2027-03-14", 'read off u: "March 11–14, 2027"'))
        for raw, why in (({"start_date": "2027-03-11", "end_date": "2027-03-14", "quote": "March 11-14, 2027"}, "word for word"),
                         ({"start_date": "2027-03-11", "end_date": "2027-03-14", "quote": "March 11 to 14, 2027"}, "word for word"),
                         ({"start_date": "2027-03-12", "end_date": "2027-03-14", "quote": "March 11–14, 2027"}, "do not name"),
                         ({"start_date": "2028-03-11", "end_date": "", "quote": "March 11–14, 2027"}, "do not name"),
                         ({"start_date": "2027-02-30", "end_date": "", "quote": "March 11–14, 2027"}, "could not be read"),
                         ({"start_date": "2027-03-11", "end_date": "2027-06-14", "quote": "March 11–14, 2027"}, "one event"),
                         ({"start_date": "", "end_date": "", "quote": ""}, "no dates")):
            got = dates.checked(raw, text, "u", self.TODAY)
            self.assertEqual((got.start, got.end), ("", ""), raw)
            self.assertIn(why, got.note, raw)
        past = dates.checked({"start_date": "2026-03-11", "end_date": "", "quote": "March 11, 2026"}, "Held March 11, 2026.", "u", self.TODAY)
        self.assertEqual(past.start, "")
        self.assertIn("has passed", past.note)

    def test_the_words_must_name_the_days(self):
        d = date.fromisoformat
        self.assertTrue(dates.names_days("march 30–april 2, 2027", d("2027-03-30"), d("2027-04-02")))
        self.assertTrue(dates.names_days("mar 11-14, 2027", d("2027-03-11"), d("2027-03-14")))
        self.assertTrue(dates.names_days("11-14 march 2027", d("2027-03-11"), d("2027-03-14")))
        self.assertTrue(dates.names_days("3/11/2027", d("2027-03-11"), None))
        self.assertTrue(dates.names_days("sept. 9, 2027", d("2027-09-09"), None))
        self.assertFalse(dates.names_days("march 11–14", d("2027-03-11"), d("2027-03-14")), "no year: not kept")
        self.assertFalse(dates.names_days("march 30–april 2, 2027", d("2027-03-30"), d("2027-05-02")), "the end's month is not April")
        self.assertFalse(dates.names_days("march 21, 2027", d("2027-03-01"), None), "21 is not the 1st")


class Lookup(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ.pop("AI_MONTHLY_CAP_USD", None)
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.today = date(2026, 11, 2)                     # every date here is counted from this pinned day
        self.earliest = scout.earliest_start(self.today)

    def day(self, n):
        return (self.today + timedelta(days=n)).isoformat()

    def event(self, name, website, *, email=None, start=120, checked=False, note=None):
        now = db.utcnow()
        start_date = self.day(start) if start is not None else None
        return db.insert(self.conn, "scout_events", dedup_key=keys.event_key(name, start_date), name_key=keys.name_key(name), name=name,
                         kind="business", start_date=start_date, city="Washington, DC", website=website, organizer="Sample Events LLC",
                         organizer_email=email, email_checked_at=now if checked else None, email_note=note,
                         sources=json.dumps([website]), status="new", found_at=now, updated_at=now)

    def ev(self, eid):
        return db.one(self.conn, "SELECT * FROM scout_events WHERE id=?", (eid,))

    def look(self, site, **kw):
        return emails.look_up(self.conn, today=self.today, earliest=self.earliest, fetch=site, **kw)

    def draft_for(self, eid, email, status="draft"):
        ev, now = self.ev(eid), db.utcnow()
        d = draft.draft_first({"event_name": ev["name"], "start_date": ev["start_date"], "end_date": ev["end_date"], "city": ev["city"]})
        return db.insert(self.conn, "outreach", kind="first", scout_event_id=eid, event_key=ev["dedup_key"], event_name=ev["name"],
                         event_kind="business", start_date=ev["start_date"], end_date=ev["end_date"], city=ev["city"],
                         website=ev["website"], email=email, subject=d.subject, body=d.body, status=status, token=keys.new_token(),
                         model="template", drafted_at=now, approved_at=now if status == "approved" else None, created_at=now, updated_at=now)

    def ctx(self):
        config.get_config().ensure_dirs()
        return runner.Context("outreach", self.conn, logging.getLogger("t"), config.get_config(), True, 0)

    def test_events_without_an_address_are_read_once_soonest_first_and_the_result_is_kept(self):
        a = self.event("Sample Con 2027", "https://samplecon.example", start=120)
        b = self.event("Other Con 2027", "https://othercon.example", start=100)
        c = self.event("Has One 2027", "https://has.example", email="jane.doe@has.example")
        site = Site({"/": (200, HOME), "/contact": (200, CONTACT)})
        stats = self.look(site)
        self.assertEqual((stats["looked"], stats["found"], stats["people"], stats["refused"]), (2, 1, 0, 0))
        row = self.ev(a)
        self.assertEqual((row["organizer_email"], row["email_source_url"]), ("press@samplecon.example", "https://samplecon.example/contact"))
        self.assertTrue(row["email_checked_at"] and row["person_looked_at"])
        other = self.ev(b)
        self.assertIsNone(other["organizer_email"])
        self.assertIn("did not answer", other["email_note"])
        self.assertTrue(site.fetched[0].startswith("https://othercon.example"), "the sooner event is read first")
        self.assertIsNone(self.ev(c)["person_looked_at"], "a person's address is left alone")
        site.fetched.clear()
        self.assertEqual(self.look(site)["looked"], 0, "each event once")
        self.assertEqual(site.fetched, [])

    def test_events_under_three_months_away_are_never_read(self):
        self.event("Soon Con", "https://samplecon.example", start=60)
        site = Site({"/": (200, CONTACT)})
        self.assertEqual(self.look(site)["looked"], 0)
        self.assertEqual(site.fetched, [])

    def test_a_walk_cut_short_by_the_budget_leaves_the_event_for_the_next_run(self):
        a = self.event("Sample Con 2027", "https://samplecon.example", start=120)
        b = self.event("Other Con 2027", "https://othercon.example", start=130)
        site = Site({"/": (200, HOME), "/contact": (200, CONTACT)})
        stats = self.look(site, budget=[1])
        self.assertEqual(stats["looked"], 0)
        self.assertEqual(site.fetched, ["https://samplecon.example"], "one page, then the run stops")
        for eid in (a, b):
            row = self.ev(eid)
            self.assertEqual((row["email_checked_at"], row["person_looked_at"], row["email_note"]), (None, None, None))

    def test_an_address_on_the_never_list_is_never_kept(self):
        self.event("CPAC Texas 2027", "https://samplecon.example")
        self.look(Site({"/": (200, "write to media@conservative.org and cpac.events@samplecon.example")}))
        row = db.one(self.conn, "SELECT organizer_email, email_note FROM scout_events")
        self.assertIsNone(row["organizer_email"])
        self.assertIn("never contacted", row["email_note"])

    def test_a_second_look_moves_a_waiting_draft_to_a_person_and_never_an_approved_note(self):
        """The second look, as built 2026-11-01: an event the earlier walk left with a shared inbox is walked once more; a
        person's address found takes its place, and the draft waiting for Chris follows. An approved note is Chris's: its
        event is not looked at again and the note is never touched."""
        waiting = self.event("Sample Con 2027", "https://samplecon.example", email="register@samplecon.example", checked=True)
        approved = self.event("Other Con 2027", "https://othercon.example", email="info@othercon.example", checked=True, start=130)
        refused = self.event("Shy Con 2027", "https://shycon.example", checked=True, start=140,
                             note=f"{emails.REFUSED_NOTE} (https://shycon.example); open it by hand")
        d = self.draft_for(waiting, "register@samplecon.example")
        a = self.draft_for(approved, "info@othercon.example", status="approved")
        before = dict(db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (a,)))
        team = "<p>Jane Doe, Director of Meetings, jane.doe@samplecon.example</p><p>info@samplecon.example</p>"
        site = Site({"/": (200, team)})
        stats = self.look(site)
        self.assertEqual((stats["second_looks"], stats["people"]), (1, 1))
        self.assertFalse([u for u in site.fetched if "othercon" in u or "shycon" in u], "approved and refused events are left alone")
        ev = self.ev(waiting)
        self.assertEqual(ev["organizer_email"], "jane.doe@samplecon.example")
        self.assertIn("instead of the shared inbox register@samplecon.example", ev["email_note"])
        followed = outreach.follow_events(self.ctx(), self.earliest)
        self.assertEqual(followed["moved"], 1)
        row = db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (d,))
        self.assertEqual((row["email"], row["status"]), ("jane.doe@samplecon.example", "draft"))
        self.assertIn("Now to jane.doe@samplecon.example, a person's address on their site", row["notes"])
        self.assertEqual(row["updated_at"], row["drafted_at"], "still untouched by Chris: the template may still rewrite it")
        self.assertEqual(dict(db.one(self.conn, "SELECT * FROM outreach WHERE id=?", (a,))), before, "the approved note is never touched")
        self.assertEqual(self.ev(approved)["organizer_email"], "info@othercon.example")
        self.assertIsNone(self.ev(refused)["person_looked_at"])
        site.fetched.clear()
        self.assertEqual(self.look(site)["second_looks"], 0, "a second look happens once")
        self.assertEqual(site.fetched, [])

    def test_a_second_look_with_no_person_keeps_the_shared_inbox_and_the_draft(self):
        eid = self.event("Sample Con 2027", "https://samplecon.example", email="info@samplecon.example", checked=True)
        d = self.draft_for(eid, "info@samplecon.example")
        self.look(Site({"/": (200, CONTACT)}))
        self.assertEqual(self.ev(eid)["organizer_email"], "info@samplecon.example", "a better shared inbox is not a reason to move")
        self.assertIn("no person's address", self.ev(eid)["email_note"])
        outreach.follow_events(self.ctx(), self.earliest)
        self.assertEqual(tuple(db.one(self.conn, "SELECT email, status FROM outreach WHERE id=?", (d,))), ("info@samplecon.example", "draft"))

    def test_an_undated_event_with_an_address_has_its_dates_read_once_on_the_ledger(self):
        eid = self.event("AMWA 2027 Annual Meeting", "https://samplecon.example/meeting", start=None)
        fake = FakeClaude({"start_date": "2027-03-11", "end_date": "2027-03-14", "quote": "March 11–14, 2027"})
        site = Site({"/meeting": (200, "<p>Meetings team: kim.park@samplecon.example</p>" + Dates.PAGE)})
        stats = self.look(site, reader=dates.Reader(self.conn, client=fake))
        self.assertEqual((stats["dates_read"], stats["dated"]), (1, 1))
        ev = self.ev(eid)
        self.assertEqual((ev["organizer_email"], ev["start_date"], ev["end_date"]), ("kim.park@samplecon.example", "2027-03-11", "2027-03-14"))
        self.assertEqual(ev["dates_note"], 'read off https://samplecon.example/meeting: "March 11–14, 2027"')
        self.assertEqual(site.fetched, ["https://samplecon.example/meeting"], "the walk's own page is the one read for the dates")
        call = fake.calls[0]
        self.assertEqual(call["model"], "claude-haiku-4-5", "the cheapest model the suite already uses")
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertIn("March 11–14, 2027", call["messages"][0]["content"])
        self.assertNotIn("<p>", call["messages"][0]["content"], "the page's words, not its markup")
        usage = db.rows(self.conn, "SELECT * FROM api_usage")
        self.assertEqual(len(usage), 1)
        self.assertIn("claude-haiku-4-5 in=3000 out=60 event dates", usage[0]["detail"])
        self.assertAlmostEqual(usage[0]["cost_usd"], 0.0033)
        self.assertEqual(self.look(site, reader=dates.Reader(self.conn, client=FakeClaude()))["dates_read"], 0, "read once")

    def test_dates_not_on_the_page_word_for_word_are_not_kept(self):
        eid = self.event("Sample Con 2027", "https://samplecon.example", email="jane.doe@samplecon.example", start=None)
        fake = FakeClaude({"start_date": "2027-03-11", "end_date": "2027-03-14", "quote": "March 11 through 14, 2027"})
        stats = self.look(Site({"/": (200, Dates.PAGE)}), reader=dates.Reader(self.conn, client=fake))
        self.assertEqual((stats["dates_read"], stats["dated"]), (1, 0))
        ev = self.ev(eid)
        self.assertIsNone(ev["start_date"])
        self.assertTrue(ev["dates_checked_at"])
        self.assertIn("word for word", ev["dates_note"])

    def test_no_read_without_an_address_nor_when_the_cap_is_reached(self):
        self.event("No Address Con", "https://samplecon.example", start=None)
        fake = FakeClaude()
        self.look(Site({"/": (200, Dates.PAGE)}), reader=dates.Reader(self.conn, client=fake))
        self.assertEqual(fake.calls, [], "no address, no paid read")
        eid = self.event("Capped Con", "https://capped.example", email="jane.doe@capped.example", start=None)
        os.environ["AI_MONTHLY_CAP_USD"] = "1"
        config.reset()
        spend.record(self.conn, "content", "claude-opus-5", 200_000, 0)          # $1.00: the cap is reached
        stats = self.look(Site({"/": (200, Dates.PAGE)}, host="capped.example"), reader=dates.Reader(self.conn, client=fake))
        self.assertEqual((fake.calls, stats["dates_read"]), ([], 0))
        ev = self.ev(eid)
        self.assertIsNone(ev["dates_checked_at"], "read on a later run, once the cap allows")
        self.assertIn("monthly AI cap", ev["dates_note"])
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage")["n"], 1, "nothing reserved, nothing recorded")

    def test_a_dry_run_and_ai_model_template_make_no_read(self):
        fake = FakeClaude()
        self.assertEqual(dates.reader(self.conn, dry_run=True, client=fake), (None, "a dry run reads no dates (a paid call)"))
        os.environ["AI_MODEL"] = "template"
        config.reset()
        self.assertEqual(dates.reader(self.conn, dry_run=False, client=fake), (None, "AI_MODEL=template: no dates read"))
        os.environ.pop("AI_MODEL")
        config.reset()
        self.assertEqual(dates.reader(self.conn, dry_run=False), (None, "no ANTHROPIC_API_KEY: no dates read"))
        reader, why = dates.reader(self.conn, dry_run=False, client=fake)
        self.assertIsInstance(reader, dates.Reader)
        # the agent itself, live, with AI_MODEL=template: the undated event is not read and nothing is paid
        eid = self.event("Sample Con 2027", "https://samplecon.example", email="jane.doe@samplecon.example", start=None)
        os.environ["AI_MODEL"] = "template"
        config.reset()
        ctx = runner.Context("outreach", self.conn, logging.getLogger("t"), config.get_config(), False, 0)
        line = outreach.run(ctx, api=None, client=fake)
        self.assertIn("AI_MODEL=template: no dates read", line)
        self.assertEqual(fake.calls, [])
        self.assertIsNone(self.ev(eid)["dates_checked_at"])
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM api_usage"))
