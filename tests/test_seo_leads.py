"""The SEO loop, part two (Chris, 2026-11-01: "shouldn't we have it do it all. Why wouldn't we?"; "One tap from my
phone"): a page just off Google's first page for a search gets its lead sentence reworded to work that search in,
proposed with a ping and a signed one-tap Approve, laid on the site only once approved, judged on that search four weeks
on and put back by itself if the page dropped for it. Search Console, Claude and ntfy are fakes (part one's, from
tests/test_seo_loop.py); every date is relative to now."""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import seo as seo_agent
from convention_social.core import approve_token, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.seo import changes, leads, search_console, titles
from convention_social.site import build, deploy
from tests._fakes import make_ctx
from tests.test_seo_loop import BREAKOUTS, DINNERS, NEW_TITLE, SITE, STAGE, FakeClaude, LoopCase

SEARCH = "keynote photographers dc"
NEW_LEAD = ("The keynote is the photograph most events need first. As keynote photographers in Washington, DC, we make it "
            "from the room, with the stage, the screens and the audience in one frame.")


class LeadCase(LoopCase):
    def lead(self, path: str) -> str:
        return build.site_words(self.conn)[build.rel_of(path)]["lead"]

    def near_stage(self, rows=None) -> tuple[str, str]:
        """A kept window in which the main stage page sits at 11.4 for SEARCH, shown 64 times."""
        win = self.window()
        self.keep(win, {STAGE: (3, 400, 6.0)}, {STAGE: rows or [(SEARCH, 0, 64, 11.4)]})
        return tuple(d.isoformat() for d in win)

    def lead_proposal(self, path=STAGE, lead=NEW_LEAD, search=SEARCH, **kw) -> int:
        return changes.propose(self.conn, kind="lead", page=path, before={"lead": self.lead(path)}, after={"lead": lead},
                               search=search, queries=[{"query": search, "clicks": 0, "impressions": 64, "position": 11.4}],
                               reason=f'Shown 64 times in Google search for "{search}".', **kw)

    def name(self, name: str) -> None:
        now = db.utcnow()
        db.insert(self.conn, "conventions", name=name, kind="business", start_date="2026-03-01", created_at=now, updated_at=now)


# ------------------------------------------------------------------ finding

class Finding(LeadCase):
    def test_a_near_miss_sits_at_place_8_to_20_shown_30_times_one_a_page_the_most_shown_first(self):
        win = self.window()
        self.name("Annual Meeting")
        rows = [("/", "convention photographers", 2, 120, 8.0),             # the first page's foot: a near miss, the most shown
                (STAGE, "conference photographers dc", 0, 64, 11.4),
                (STAGE, "keynote photographers", 0, 40, 12.0),               # the same page's second: one a page
                (BREAKOUTS, "panel photographers", 0, 29, 12.0),             # 29 showings say too little
                (BREAKOUTS, "breakout photographers", 1, 50, 7.9),           # on the first page: part one's ground
                (BREAKOUTS, "conference photography", 0, 50, 20.1),          # too far off
                (DINNERS, "gala photographers", 0, 30, 20.0),                # 30 showings at 20: just in
                ("/coverage/exhibition_hall/", "trade show photographers", 0, 31, 15.0),
                ("/about/", "event photographers dc", 0, 80, 10.0),          # a page with no lead sentence
                ("/coverage/portraits/", "cpac photographer", 0, 200, 9.0),  # a word outside the trade and place words
                ("/coverage/portraits/", "annual meeting photographers", 0, 90, 9.0)]   # every word safe, but a name
        search_console.keep_rows(self.conn, *win, [],
                                 [{"keys": [SITE + p, q], "clicks": c, "impressions": i, "position": pos} for p, q, c, i, pos in rows]
                                 + [{"keys": ["https://www.eventcaliber.com/coverage/backstage/", "backstage photographers"],
                                     "clicks": 0, "impressions": 900, "position": 10.0}])         # not an address of the site
        found, left_out = leads.near_misses(self.conn, tuple(d.isoformat() for d in win))
        self.assertEqual([(r["path"], r["query"]) for r in found],
                         [("/", "convention photographers"), (STAGE, "conference photographers dc"),
                          ("/coverage/exhibition_hall/", "trade show photographers"), (DINNERS, "gala photographers")])
        self.assertEqual(left_out, {"words": 2, "no lead": 1})
        self.assertEqual((found[1]["impressions"], found[1]["position"], found[1]["clicks"]), (64, 11.4, 0))
        self.assertIn('Shown 64 times in Google search for "conference photographers dc"', leads.reason(found[1]))
        self.assertIn("at an average place of 11.4: at the foot of the first page or just past it", leads.reason(found[1]))

    def test_only_a_search_of_trade_and_place_words_with_no_name_and_not_the_brand(self):
        known = ["Annual Meeting"]
        self.assertEqual(leads.photo_text.searchable("Keynote  Photographers DC", "Event Caliber", known), "keynote photographers dc")
        for search in ("cpac photographer", "annual meeting photographers", "event caliber photographers",
                       "jane smith keynote photographer"):
            self.assertEqual(leads.photo_text.searchable(search, "Event Caliber", known), "", search)

    def test_a_week_with_nothing_near_says_so_and_names_what_it_left_out(self):
        self.near_stage([("cpac photographer", 0, 200, 9.0)])
        self.assertEqual(leads.propose_week(self.conn, client=FakeClaude()).split("; ")[1],
                         "1 more left out, a word in the search is not a trade or place word")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)


# ------------------------------------------------------------------ drafting

class Drafting(LeadCase):
    def test_claude_rewords_the_lead_for_the_search_and_it_is_proposed_and_pinged(self):
        self.near_stage()
        own = self.lead(STAGE)
        fake = FakeClaude({"lead": NEW_LEAD})
        said = leads.propose_week(self.conn, client=fake)
        self.assertEqual(said, f'{STAGE}: proposed (change 1) for "{SEARCH}", ping sent')
        facts = json.loads(fake.calls[0]["messages"][0]["content"])
        self.assertEqual((facts["lead_now"], facts["search"], facts["lead_max_characters"]), (own, SEARCH, build.LEAD_MAX))
        self.assertEqual(facts["numbers"], {"shown": 64, "clicked": 0, "average_place": 11.4})
        self.assertIn("We photograph the main stage from several positions", facts["page_text"])
        self.assertIn("Never name an event", fake.calls[0]["system"])
        self.assertEqual(fake.calls[0]["model"], leads.MODEL)
        row = self.row(1)
        self.assertEqual((row["kind"], row["page"], row["status"], row["search"]), ("lead", STAGE, "proposed", SEARCH))
        self.assertEqual((json.loads(row["before"]), json.loads(row["after"])), ({"lead": own}, {"lead": NEW_LEAD}))
        self.assertEqual(json.loads(row["fields"]), ["lead"])
        self.assertEqual(json.loads(row["queries"]), [{"query": SEARCH, "clicks": 0, "impressions": 64, "position": 11.4}])
        self.assertEqual(self.lead(STAGE), own, "nothing on the site changes until Approve")
        spent = self.spent()
        self.assertEqual(len(spent), 1, "reserved, then recorded on the same row")
        self.assertIn("seo lead /coverage/stage/", spent[0]["detail"])
        self.assertGreater(spent[0]["cost_usd"], 0)
        (title, message), kw = self.pings[0]
        self.assertEqual(title, "Event Caliber: new search words to approve")
        self.assertIn(f"Lead sentence now: {own}\nLead sentence new: {NEW_LEAD}", message)
        self.assertIn(f'for "{SEARCH}"', message)
        self.assertIn("put back by itself if the page drops 2 places or more in Google for that search", message)
        self.assertIn("http, Approve, http://127.0.0.1:4610/seo/changes/1/by-token/approve, method=POST", kw["actions"])
        token = re.search(r"body='token=([^']+)'", kw["actions"]).group(1)
        self.assertTrue(approve_token.check(self.conn, row, token, scope=changes.TOKENS)[0], "the ping carries a live token")

    def test_a_lead_that_breaks_a_rule_is_dropped_with_the_reason_and_never_proposed(self):
        win = self.near_stage()
        near = leads.near_misses(self.conn, win)[0][0]
        own = self.lead(STAGE)
        for lead, why in (
                (NEW_LEAD.replace("keynote photographers", "CPAC keynote photographers"), "names 'CPAC'"),
                (NEW_LEAD.replace("in Washington, DC", "at the Marriott in Washington, DC"), "it says Marriott, which the page does not"),
                (NEW_LEAD.replace("most events", "500 events"), "it says 500, which the page does not"),
                (NEW_LEAD + " From $900 a day.", "mentions a price"),
                (NEW_LEAD.replace("we make it", "our package includes it"), "says something about the company"),
                (NEW_LEAD.replace("As keynote photographers", "As the official photographer and keynote photographers"),
                 "claims a tie to the event"),
                (NEW_LEAD.replace("As keynote photographers", "Trusted by associations, as keynote photographers"),
                 "claims a tie to the event ('Trusted by')"),
                (own, "Claude kept the lead the page has"),
                ("The keynote is the photograph most events need first, made from the room in one frame.",
                 f'it works in none of the words of "{SEARCH}" the lead lacks'),
                ("The main stage is the photograph most events need first, by photographers in Washington, DC.",
                 "it drops keynote, which the search has and the lead had"),
                (NEW_LEAD + " The room, the stage and the audience are in it.", "characters, 200 at most"),
                ("", "the lead is empty")):
            said = leads.draft(self.conn, FakeClaude({"lead": lead}), near, win)
            self.assertTrue(said.startswith(f"{STAGE}: dropped, "), said)
            self.assertIn(why, said)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)
        self.assertEqual(self.pings, [])
        self.assertEqual(leads.draft(self.conn, FakeClaude(stop="refusal"), near, win),
                         f"{STAGE}: dropped, Claude refused or gave nothing readable")
        said = leads.draft(self.conn, FakeClaude({"lead": NEW_LEAD.replace("DC, we", "DC — we")}), near, win)
        self.assertIn("proposed", said, "a dash is tidied into a comma, as every caption's is")

    def test_at_most_two_a_week_the_cap_and_a_missing_key_stop_it_cleanly(self):
        win = self.window()
        self.keep(win, {}, {STAGE: [(SEARCH, 0, 64, 11.4)], BREAKOUTS: [("panel photographers", 0, 50, 12.0)],
                            DINNERS: [("gala photographers", 0, 40, 14.0)]})
        fake = FakeClaude({"lead": "x"})
        said = leads.propose_week(self.conn, client=fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(said.count("dropped"), 2)
        config.reset()
        self.assertEqual(leads.propose_week(self.conn), "no Anthropic key, so nothing drafted")
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        fake = FakeClaude({"lead": NEW_LEAD})
        self.assertEqual(leads.propose_week(self.conn, client=fake), "the monthly AI cap is reached, so nothing more drafted")
        self.assertEqual(fake.calls, [])
        os.environ["AI_MONTHLY_CAP_USD"] = "20"
        config.reset()
        said = leads.propose_week(self.conn, client=FakeClaude(error=ConnectionError("down")))
        self.assertTrue(said.startswith(f"{STAGE}: Claude could not be asked (ConnectionError)"), said)
        self.assertIn("could not be drafted", db.one(self.conn, "SELECT message FROM errors WHERE kind='seo_lead'")["message"])


# ------------------------------------------------------------------ one at a time, whatever the kind

class OneAtATime(LeadCase):
    def test_one_open_change_per_page_across_kinds_and_the_rest_counts_both(self):
        title = self.proposal()                                     # part one's: new words for the stage page's result
        with self.assertRaises(changes.Refused) as cm:
            self.lead_proposal()
        self.assertIn(f"change {title} for it is waiting for your Approve", str(cm.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            db.insert(self.conn, "seo_changes", kind="lead", page=STAGE, fields="[]", before="{}", after="{}", reason="x",
                      status="proposed", proposed_at=db.utcnow(), updated_at=db.utcnow())
        self.near_stage()
        fake = FakeClaude({"lead": NEW_LEAD})
        self.assertEqual(leads.propose_week(self.conn, client=fake),
                         f"{STAGE}: left alone, change {title} for it is waiting for your Approve")
        self.assertEqual(fake.calls, [], "nothing paid for a page that is not free")
        lead = self.lead_proposal(BREAKOUTS, lead="Breakout photographers.", search="breakout photographers")
        self.keep(self.window(), {BREAKOUTS: (1, 300, 4.0)})
        self.assertIn(f"{BREAKOUTS}: left alone, change {lead} for it is waiting for your Approve",
                      titles.propose_week(self.conn, client=FakeClaude()), "a lead open keeps part one away too")
        now = datetime.now(timezone.utc)
        self.set(title, status="kept", live_at=(now - timedelta(weeks=7)).isoformat(timespec="seconds"))
        self.assertIn("put live less than eight weeks ago", changes.resting(self.conn, STAGE), "a title change rests the page for leads")


# ------------------------------------------------------------------ approving and the page

class Approving(LeadCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_approve_sends_the_site_to_publish_and_says_how_it_is_judged(self):
        cid = self.lead_proposal()
        ok, words = changes.approve(self.conn, cid)
        self.assertTrue(ok, words)
        self.assertIn(f"The new words go on {STAGE} when the site next publishes", words)
        self.assertIn("put back by itself if the page drops 2 places or more in Google for that search", words)
        self.assertTrue(settings.get(self.conn, deploy.SEO_CHANGED_KEY))

    def test_approve_is_refused_when_the_lead_changed_or_would_no_longer_pass(self):
        cid = self.lead_proposal()
        self.set(cid, before=json.dumps({"lead": "A lead the page never had."}))
        ok, why = changes.approve(self.conn, cid)
        self.assertFalse(ok)
        self.assertIn("the page's lead changed since this was drafted", why)
        self.set(cid, before=json.dumps({"lead": self.lead(STAGE)}))
        self.name("Keynote Photographers")
        ok, why = changes.approve(self.conn, cid)
        self.assertFalse(ok)
        self.assertIn("names 'Keynote Photographers'", why)
        self.assertIn("the search it was made for is not one public words may use", why)
        self.assertEqual(self.row(cid)["status"], "proposed")

    def test_the_page_shows_the_sentence_before_and_after_and_the_search_with_its_numbers(self):
        cid = self.lead_proposal()
        page = html.unescape(self.client.get("/seo/changes").text)
        for words in ("On the page now", self.lead(STAGE), "Proposed", NEW_LEAD, f"{SITE}{STAGE}", "The search it is for",
                      f"<td>{SEARCH}</td><td>64</td><td>0</td><td>11.4</td>", f'Shown 64 times in Google search for "{SEARCH}".',
                      f'action="/seo/changes/{cid}/approve"', f'action="/seo/changes/{cid}/skip"',
                      "a page just off Google's first page for a search gets its lead sentence reworded"):
            self.assertIn(words, page)
        self.assertNotIn('<div class="serp">', page.split(f'id="c{cid}"')[1], "a lead is the page's sentence, not a search result")
        token = approve_token.issue(self.conn, self.row(cid), scope=changes.TOKENS)
        tap = html.unescape(self.client.get(f"/seo/changes/{cid}/by-token/approve?token={token}").text)
        self.assertIn(f'For the search "{SEARCH}"', tap)
        self.assertIn(f"Lead sentence new</span><br>{NEW_LEAD}", tap)


# ------------------------------------------------------------------ the site

class Building(LeadCase):
    def built(self, rel: str) -> tuple[str, str]:
        """(the lead sentence, the meta description) as a page was written."""
        text = (self.root / "dist" / rel).read_text()
        return (html.unescape(re.search(r'<p class="first">(.*?)</p>', text).group(1)),
                html.unescape(re.search(r'<meta name="description" content="(.*?)">', text).group(1)))

    def test_the_build_lays_an_approved_lead_and_not_a_proposed_one(self):
        own_stage, own_home = self.lead(STAGE), self.lead("/")
        approved = self.lead_proposal()
        self.set(approved, status="approved")
        self.lead_proposal("/", lead="Event Caliber are convention photographers in Washington, DC and nationwide.",
                           search="convention photographers")
        build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        self.assertEqual(self.built("coverage/stage/index.html"), (NEW_LEAD, own_stage), "the lead changes, the description stays")
        self.assertEqual(self.built("index.html")[0], own_home, "a proposed lead is not on the site")
        self.assertEqual(json.loads(settings.get(self.conn, changes.BUILT_KEY)), [approved], "for the deploy to mark live")

    def test_a_stale_lead_and_one_that_no_longer_passes_are_left_off_with_a_note(self):
        own = self.lead(STAGE)
        cid = self.lead_proposal()
        self.set(cid, status="live", before=json.dumps({"lead": "A lead the page no longer has."}))
        build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        self.assertEqual(self.built("coverage/stage/index.html")[0], own, "the page keeps its own lead")
        self.assertEqual(json.loads(settings.get(self.conn, changes.BUILT_KEY)), [])
        note = db.one(self.conn, "SELECT message FROM errors WHERE agent='site' AND kind='seo_change'")["message"]
        self.assertIn(f"Search change {cid} is not on the site: {STAGE} no longer has the words it replaced", note)
        self.set(cid, before=json.dumps({"lead": own}))
        self.name("Keynote Photographers")
        brand = config.get_config().brand_name
        words, laid, off = build.with_seo_changes(self.conn, build.page_words(build.offer.load(), build.copy_text(), brand), brand)
        self.assertEqual((laid, words["coverage/stage/index.html"]["lead"]), ([], own))
        self.assertIn("its words no longer pass: the lead names 'Keynote Photographers'", off[cid])
        self.assertIn("no longer pass", changes.view(self.conn)[0]["off_site"])

    def test_a_kept_title_and_a_lead_on_one_page_are_both_laid_in_order(self):
        brand = config.get_config().brand_name
        title = self.proposal()
        self.set(title, status="kept")
        lead = self.lead_proposal()
        self.set(lead, status="approved")
        words, laid, off = build.with_seo_changes(self.conn, build.page_words(build.offer.load(), build.copy_text(), brand), brand)
        self.assertEqual((laid, off), ([title, lead], {}))
        self.assertEqual((words["coverage/stage/index.html"]["title"], words["coverage/stage/index.html"]["lead"]), (NEW_TITLE, NEW_LEAD))


# ------------------------------------------------------------------ live, judged on its search, kept or put back

class Measuring(LeadCase):
    def live(self, days_ago: int = 33, base: tuple[int, int, float] | None = (0, 64, 11.4)) -> int:
        """A lead change that went live `days_ago`, its baseline the search's numbers in a read that ended before."""
        cid = self.lead_proposal()
        self.keep(self.window(days_ago + 3), {STAGE: (3, 400, 6.0)}, {STAGE: [(SEARCH, *base)]} if base else {})
        self.set(cid, status="approved")
        settings.set(self.conn, changes.BUILT_KEY, json.dumps([cid]))
        self.assertEqual(changes.went_live(self.conn, now=datetime.now(timezone.utc) - timedelta(days=days_ago)), [STAGE])
        return cid

    def since(self, place: float, shown: int = 45) -> None:
        self.keep(self.window(), {STAGE: (5, 420, 5.5)}, {STAGE: [(SEARCH, 1, shown, place)]})

    def test_the_baseline_is_the_searchs_own_numbers_not_the_pages(self):
        cid = self.live(0)
        base = json.loads(self.row(cid)["baseline"])
        self.assertEqual((base["impressions"], base["position"]), (64, 11.4))
        self.assertEqual(changes.measure(self.conn), [], "not before 31 days")

    def test_kept_at_the_same_place_or_better(self):
        cid = self.live()
        self.since(9.8)
        seen = changes.measure(self.conn)
        self.assertEqual([(m["id"], m["verdict"]) for m in seen], [(cid, "kept")])
        self.assertIn(f'The new lead on {STAGE} stays: for "{SEARCH}" it sat at an average place of 9.8 in 45 showings', seen[0]["words"])
        self.assertIn("against 11.4 before", seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "kept")
        self.assertEqual(self.lead(STAGE), NEW_LEAD, "a kept lead stays on the site")
        self.assertIsNone(settings.get(self.conn, deploy.SEO_CHANGED_KEY))

    def test_the_same_place_is_kept(self):
        self.live()
        self.since(11.4)
        self.assertEqual(changes.measure(self.conn)[0]["verdict"], "kept")

    def test_put_back_two_places_lower_or_more(self):
        cid = self.live()
        self.since(13.4)
        seen = changes.measure(self.conn)
        self.assertEqual(seen[0]["verdict"], "reverted")
        self.assertIn(f'The new lead on {STAGE} was put back: for "{SEARCH}" its average place went from 11.4 to 13.4', seen[0]["words"])
        self.assertIn("2 places lower", seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "reverted")
        self.assertTrue(settings.get(self.conn, deploy.SEO_CHANGED_KEY), "the site republishes")
        self.assertNotEqual(self.lead(STAGE), NEW_LEAD, "the page has its own lead again")
        done, _ = changes.brief(self.conn, datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertIn(f"Search: {seen[0]['words']}", done)

    def test_lower_by_less_than_two_places_or_too_few_showings_keeps_measuring_and_says_so(self):
        cid = self.live()
        self.since(12.9)
        seen = changes.measure(self.conn)
        self.assertIsNone(seen[0]["verdict"])
        self.assertIn(f'{STAGE} sat at an average place of 12.9 for "{SEARCH}" since its new lead went live', seen[0]["words"])
        self.assertIn("against 11.4 before: lower, by less than 2 places, so measured again next week", seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "live")
        _, watching = changes.brief(self.conn, datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertEqual(watching, [f"Search: {seen[0]['words']}"])
        self.since(9.0, shown=29)
        seen = changes.measure(self.conn)
        self.assertIsNone(seen[0]["verdict"])
        self.assertIn(f'was shown 29 times for "{SEARCH}" since its new lead went live', seen[0]["words"])
        self.assertIn("fewer than 30: measured again next week", seen[0]["words"])

    def test_a_search_with_no_place_before_cannot_have_dropped(self):
        self.live(base=None)
        self.since(15.0)
        seen = changes.measure(self.conn)
        self.assertEqual(seen[0]["verdict"], "kept")
        self.assertIn("against no place for it before", seen[0]["words"])


# ------------------------------------------------------------------ the weekly run

class Weekly(LeadCase):
    def test_a_dry_run_reads_nothing_pays_nothing_and_proposes_nothing(self):
        self.near_stage()
        fake, google = FakeClaude({"lead": NEW_LEAD}), mock.Mock()
        line = seo_agent.run(make_ctx(self.conn, agent="seo", dry_run=True), console=google, changes_client=fake)
        self.assertIn("search changes: none in dry run (nothing read, measured, paid for or proposed)", line)
        self.assertEqual((fake.calls, google.call_count, self.spent(), self.pings), ([], 0, [], []))
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)

    def test_the_live_week_proposes_a_lead_after_part_one_and_says_so(self):
        def google(method, url, body, headers):
            if url.endswith("/sites"):
                return 200, {"siteEntry": [{"siteUrl": "sc-domain:eventcaliber.com", "permissionLevel": "siteOwner"}]}
            dims = (body or {}).get("dimensions")
            if not dims:
                return 200, {"rows": [{"clicks": 20, "impressions": 900, "position": 5.0}]}
            if dims == ["query"]:
                return 200, {"rows": []}
            if dims == ["page"]:
                return 200, {"rows": [{"keys": [SITE + STAGE], "clicks": 30, "impressions": 500, "position": 3.0}]}
            return 200, {"rows": [{"keys": [SITE + STAGE, SEARCH], "clicks": 0, "impressions": 64, "position": 11.4}]}
        fake = FakeClaude({"lead": NEW_LEAD})
        with mock.patch.object(search_console, "access_token", return_value="tok"), \
                mock.patch.object(seo_agent.site_check, "run_check", return_value={"checked": 1, "failed": 0}):
            line = seo_agent.run(make_ctx(self.conn, agent="seo", dry_run=False), console=google, changes_client=fake)
        self.assertIn("New words: no page lost its clicks to its words from", line)
        self.assertIn(f'Near misses: {STAGE}: proposed (change 1) for "{SEARCH}", ping sent.', line)
        self.assertIn("Standing: 1 waiting for your Approve.", line)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.row(1)["kind"], "lead")


if __name__ == "__main__":
    import unittest
    unittest.main()
