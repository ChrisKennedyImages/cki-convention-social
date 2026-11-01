"""The SEO loop, part three (Chris, 2026-11-01: "Pages from real demand: searches you appear for with no page built for
them", each coming to him "with a rendered preview first since a new page carries photos"): a search people make often
that no page answers gets a page of its own under /coverage/, proposed with a ping, a preview and a signed one-tap
Approve, built like a coverage page only once approved, judged on its own eight weeks on, and proposed for taking down,
never taken down by itself, when it did not earn its place. Search Console, Claude, Drive and ntfy are fakes (part one's,
from tests/test_seo_loop.py); every date is relative to now."""
from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from convention_social.agents import seo as seo_agent
from convention_social.core import approve_token, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.seo import changes, pages, photo_text, search_console
from convention_social.site import build, deploy
from tests._fakes import make_ctx
from tests.test_seo_loop import BREAKOUTS, DINNERS, SITE, STAGE, FakeClaude, LoopCase
from tests.test_wedding import event_photo

SEARCH = "conference photographer dc"
NEW = "/coverage/conference/"
PAGE = {"heading": "Conferences", "name": "Conference photography",
        "description": ("Conference photography in Washington, DC and nationwide: the main stage, the breakouts and the people "
                        "between them. Request a quote."),
        "lead": "A conference is photographed room by room, from the main stage and the keynotes to the breakouts and the people meeting between them.",
        "paragraphs": ["We photograph a conference the way it runs: the main stage from several positions, the breakouts on a plan "
                       "made with you around the schedule, and the speakers as they come off the stage.",
                       "One of us is at every event. Tell us which rooms matter, and every event is quoted on its own."],
        "shots": ["main_stage", "breakout"]}


def answer(**changed) -> dict:
    """Claude's answer: PAGE as it writes it (no title: the site makes it), with `changed` fields."""
    return {**PAGE, **changed}


def picture(row) -> Image.Image:
    return Image.new("RGB", (int(row["width"]), int(row["height"])), (90, 70, 130))


class PageCase(LoopCase):
    def page_proposal(self, path=NEW, page=None, searches=((SEARCH, 0, 60, 34.0),), **kw) -> int:
        page = page or {**PAGE, "title": f"{PAGE['name']}, {build.AREA}"}
        return changes.propose(self.conn, kind="page", page=path, before={}, after=page, search=searches[0][0],
                               queries=[{"query": q, "clicks": c, "impressions": i, "position": p} for q, c, i, p in searches],
                               reason=f'Searched "{searches[0][0]}" 60 times in Google.', **kw)

    def photo(self, n: int, shot: str, **kw) -> int:
        """An approved event photo of one kind of shot: cleared, sorted, its final check passed."""
        pid = event_photo(self.conn, f"d{n}", kind="business", final="business", width=1200, height=800, **kw)
        self.conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=?", (shot, pid))
        return pid

    def demand(self, rows) -> tuple[list[dict], dict]:
        win = self.window()
        search_console.keep_rows(self.conn, *win, [], [{"keys": [SITE + p, q], "clicks": c, "impressions": i, "position": pos}
                                                       for p, q, c, i, pos in rows])
        return pages.demand(self.conn, tuple(d.isoformat() for d in win))


# ------------------------------------------------------------------ finding

class Finding(PageCase):
    def test_searches_shown_20_times_that_no_page_answers_grouped_by_what_they_ask_for_the_most_shown_first(self):
        found, left_out = self.demand([
            ("/", SEARCH, 1, 30, 12.0),                                       # the home page shows it: no page answers it
            ("/", "dc conference photographers", 0, 15, 14.0),                # the same words, another order, a plural
            (BREAKOUTS, "dc conference photographers", 0, 10, 41.0),          # summed over the pages: 25 in all
            ("/", "gala photographers", 0, 24, 18.0),
            (BREAKOUTS, "corporate event photographers", 0, 21, 25.0),        # a page shows it, but worse than place 20
            ("/", "trade show photographer", 0, 19, 30.0),                    # 19 showings say too little
            (DINNERS, "awards dinner photographer", 0, 40, 9.0),              # a page answers it at place 9
            ("/", "keynote photographer", 0, 50, 30.0),                       # the main stage page's title carries keynote
            ("/", "headshot photographer dc", 0, 22, 25.0),                   # a headshot is a portrait: that page's title
            ("/", "event photographer dc", 0, 60, 8.0),                       # the home page's title carries event
            ("/", "photographers near me", 0, 33, 9.0),                        # the business as a whole: the home page's
            ("/", "comic convention photographer", 0, 45, 15.0),              # a fan convention: never offered (2026-10-12)
            ("/", "hotel photographer dc", 0, 30, 22.0),                      # a venue: left for Chris
            ("/", "convention center photographers", 0, 26, 22.0),            # a venue too
            ("/", "conference photographer new york", 0, 70, 40.0),           # a place not served: not a place word at all
            ("/", "cpac photographer", 0, 90, 12.0)])                         # a name
        self.assertEqual([(r["path"], r["query"], r["impressions"]) for r in found],
                         [(NEW, SEARCH, 55), ("/coverage/gala/", "gala photographers", 24),
                          ("/coverage/corporate-event/", "corporate event photographers", 21)])
        self.assertEqual([(s["query"], s["impressions"], s["page"]) for s in found[0]["searches"]],
                         [(SEARCH, 30, "/"), ("dc conference photographers", 25, "/")])
        self.assertEqual(left_out, {"words": 2, "whole": 1, "venue": 2, "unoffered": 1, "answered": 4, "taken down": 0})
        self.assertIn('Searched "conference photographer dc" and 1 search like it 55 times in Google', pages.reason(found[0]))
        self.assertIn("Google showed the home page", pages.reason(found[0]))
        self.assertIn("Google showed /coverage/breakouts/ at an average place of 25", pages.reason(found[2]))

    def test_only_what_the_business_offers_and_only_where_it_works(self):
        """A word the searchers' vocabulary may gain one day is still not proposed unless offer.json names it: a place
        not served, a kind of event not offered."""
        with mock.patch.object(photo_text, "SEARCH_VOCAB", photo_text.SEARCH_VOCAB | {"boston", "wedding", "anime"}):
            found, left_out = self.demand([("/", "conference photographer boston", 0, 40, 30.0),
                                           ("/", "wedding photographer dc", 0, 40, 30.0),
                                           ("/", "anime convention photographers", 0, 40, 30.0),
                                           ("/", "booth photographer", 0, 40, 30.0),         # a booth is the exhibition hall
                                           ("/", "association conference photography", 0, 40, 30.0)])
        self.assertEqual([r["path"] for r in found], ["/coverage/association-conference/"])
        self.assertEqual((left_out["unoffered"], left_out["answered"]), (3, 1))
        offered = pages.offered()
        for word in ("conference", "convention", "gala", "corporate", "association", "trade", "show", "portrait", "keynote"):
            self.assertIn(word, offered)
        for word in ("comic", "anime", "fan", "wedding", "photographer", "hotel", "venue"):
            self.assertNotIn(word, offered)

    def test_never_an_address_the_site_has_or_took_down(self):
        cid = self.page_proposal("/coverage/gala/", searches=(("gala photographers", 0, 30, 18.0),))
        self.set(cid, status="kept")
        down = changes.propose(self.conn, kind="takedown", page="/coverage/gala/", before={"title": "Gala photography"},
                               after={"removed": True}, queries=[], reason="did not earn its place",
                               now=datetime.now(timezone.utc) + timedelta(weeks=9))
        self.set(down, status="kept")
        found, left_out = self.demand([("/", "gala photographers", 0, 30, 18.0)])
        self.assertEqual((found, left_out["taken down"]), ([], 1))

    def test_a_week_with_nothing_to_build_says_what_it_left_out_and_venues_wait_for_chris(self):
        win = self.window()
        search_console.keep_rows(self.conn, *win, [], [{"keys": [SITE + "/", "hotel photographer dc"], "clicks": 0,
                                                       "impressions": 30, "position": 22.0}])
        said = pages.propose_week(self.conn, client=FakeClaude(answer()))
        self.assertTrue(said.startswith("no search without a page of its own was shown 20 times or more from"), said)
        self.assertIn("1 more left out, for a venue, waiting for you: a venue page needs the venue's name", said)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)


# ------------------------------------------------------------------ drafting

class Drafting(PageCase):
    def setUp(self):
        super().setUp()
        for n, shot in enumerate(("main_stage", "breakout", "main_stage", "portrait", "reception")):
            self.photo(n, shot)
        fetch = mock.patch.object(build, "library_fetch", return_value=(picture, ""))
        fetch.start()
        self.addCleanup(fetch.stop)

    def week(self, fake, rows=(("/", SEARCH, 1, 30, 12.0), ("/", "dc conference photographers", 0, 25, 14.0))) -> str:
        win = self.window()
        search_console.keep_rows(self.conn, *win, [], [{"keys": [SITE + p, q], "clicks": c, "impressions": i, "position": pos}
                                                       for p, q, c, i, pos in rows])
        return pages.propose_week(self.conn, client=fake)

    def test_claude_writes_the_page_it_is_proposed_previewed_and_pinged(self):
        fake = FakeClaude(answer())
        said = self.week(fake)
        self.assertEqual(said, f'{NEW}: proposed (change 1) for "{SEARCH}", ping sent')
        facts = json.loads(fake.calls[0]["messages"][0]["content"])
        self.assertEqual((facts["address"], facts["what_they_ask_for"]), (NEW, "conference"))
        self.assertEqual([s["search"] for s in facts["searches"]], [SEARCH, "dc conference photographers"])
        self.assertEqual(facts["name_max_characters"], 75 - len(" | Event Caliber") - len(", Washington, DC"))
        self.assertEqual(set(facts["photo_kinds"]), set(build.SHOT_KINDS))
        self.assertIn("Never name an event", fake.calls[0]["system"])
        self.assertEqual(fake.calls[0]["output_config"]["format"]["schema"], pages.SCHEMA)
        row = self.row(1)
        self.assertEqual((row["kind"], row["page"], row["status"], row["search"]), ("page", NEW, "proposed", SEARCH))
        self.assertEqual(json.loads(row["after"]), {**PAGE, "title": "Conference photography, Washington, DC"})
        self.assertEqual(json.loads(row["before"]), {})
        self.assertEqual([q["query"] for q in json.loads(row["queries"])], [SEARCH, "dc conference photographers"])
        self.assertNotIn("coverage/conference/index.html", build.site_words(self.conn), "nothing on the site until Approve")
        self.assertIn("seo page /coverage/conference/", self.spent()[0]["detail"])
        self.assertTrue((pages.preview_dir(1) / "index.html").is_file(), "the preview is built before the ping")
        (title, message), kw = self.pings[0]
        self.assertEqual(title, "Event Caliber: a new page to approve")
        self.assertIn("Title: Conference photography, Washington, DC | Event Caliber\n", message)
        self.assertIn("Photos: Main stage, Breakout session", message)
        self.assertIn("Preview shows the page as the site would", message)
        self.assertNotIn(" now: ", message, "a new page has no before")
        self.assertIn("view, Preview, http://127.0.0.1:4610/seo/changes/1/preview", kw["actions"])
        self.assertEqual(kw["click"], "http://127.0.0.1:4610/seo/changes/1/preview")
        token = re.search(r"body='token=([^']+)'", kw["actions"]).group(1)
        self.assertTrue(approve_token.check(self.conn, row, token, scope=changes.TOKENS)[0])

    def test_a_draft_that_breaks_a_rule_is_dropped_with_the_reason_and_never_proposed(self):
        win = self.window()
        search_console.keep_rows(self.conn, *win, [], [{"keys": [SITE + "/", SEARCH], "clicks": 0, "impressions": 30, "position": 12.0}])
        found = pages.demand(self.conn, tuple(d.isoformat() for d in win))[0][0]
        for raw, why in (({"name": "CPAC conference photography"}, "names 'CPAC'"),
                         ({"description": "Conference photography from $900 a day."}, "mentions a price"),
                         ({"lead": "Every package includes the keynote."}, "says something about the company"),
                         ({"paragraphs": ["We photograph conferences at the Marriott, room by room."]}, "it says Marriott, which the site does not"),
                         ({"paragraphs": ["We have photographed 400 conferences, room by room."]}, "it says 400, which the site does not"),
                         ({"name": "Event photography"}, "its title does not carry conference, which the search asks for"),
                         ({"heading": "Conferences, conventions, galas and award dinners"}, "the heading is 49 characters, 35 at most"),
                         ({"paragraphs": ["One.", "Two.", "Three."]}, "it needs one or two paragraphs, not 3"),
                         ({"shots": ["wedding"]}, "its photos must be one to 3 of the kinds the site shows"),
                         ({"name": "Conference, convention and association meeting photography"}, "characters in a search result, 75 at most"),
                         ({"lead": "The official photographer of every conference."}, "claims a tie to the event"),
                         ({"lead": ""}, "the lead is empty")):
            said = pages.draft(self.conn, FakeClaude(answer(**raw)), found)
            self.assertTrue(said.startswith(f"{NEW}: dropped, "), said)
            self.assertIn(why, said)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)
        self.assertEqual(self.pings, [])
        self.assertEqual(pages.draft(self.conn, FakeClaude(stop="refusal"), found), f"{NEW}: dropped, Claude refused or gave nothing readable")
        said = pages.draft(self.conn, FakeClaude(answer(lead=PAGE["lead"].replace("room by room, from", "room by room — from"))), found)
        self.assertIn("proposed", said, "a dash is tidied into a comma, as every caption's is")

    def test_at_most_one_a_week_the_cap_and_a_missing_key_stop_it_cleanly(self):
        rows = (("/", SEARCH, 1, 30, 12.0), ("/", "gala photographers", 0, 24, 18.0))
        fake = FakeClaude(answer())
        said = self.week(fake, rows)
        self.assertEqual((len(fake.calls), said.count("proposed")), (1, 1))
        said = self.week(FakeClaude(answer(heading="Galas", name="Gala photography")), rows)
        self.assertIn(f"{NEW}: left alone, change 1 for it is waiting for your Approve", said)
        self.assertIn('/coverage/gala/: proposed (change 2) for "gala photographers"', said, "the next one's turn, the week after")
        self.conn.execute("DELETE FROM seo_changes")
        config.reset()
        self.assertEqual(self.week(None, rows).split("; ")[0], "no Anthropic key, so nothing drafted")
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        fake = FakeClaude(answer())
        self.assertEqual(self.week(fake, rows).split("; ")[0], "the monthly AI cap is reached, so nothing more drafted")
        self.assertEqual(fake.calls, [])

    def test_without_drive_the_page_is_still_proposed_and_its_preview_waits_for_the_tap(self):
        with mock.patch.object(build, "library_fetch", return_value=(None, "Drive is not signed in yet.")):
            said = self.week(FakeClaude(answer()))
        self.assertIn("proposed (change 1)", said)
        self.assertIn("no preview yet (the photos could not be fetched: Drive is not signed in yet.)", said)
        self.assertFalse(pages.preview_dir(1).exists())


# ------------------------------------------------------------------ the preview and the page

class Preview(PageCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(create_app())
        self.ids = [self.photo(n, shot) for n, shot in enumerate(("main_stage", "breakout", "breakout", "backstage"))]

    def test_the_preview_needs_sign_in_is_noindex_shows_real_photos_of_its_kinds_and_is_never_in_the_sitemap(self):
        cid = self.page_proposal()
        self.assertEqual(self.client.get(f"/seo/changes/{cid}/preview", follow_redirects=False).status_code, 307)
        self.assertEqual(self.client.get(f"/seo/changes/{cid}/preview/assets/site.css", follow_redirects=False).status_code, 307)
        fetched = []
        pages.preview(self.conn, cid, fetch=lambda r: fetched.append(r["id"]) or picture(r))
        self.assertEqual(sorted(fetched), sorted(self.ids[:3]), "its own kinds, the main stage and the breakouts: three, enough")
        self.client.cookies.set(COOKIE, make_token("chris"))
        r = self.client.get(f"/seo/changes/{cid}/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow")
        page = html.unescape(r.text)
        for words in ('<meta name="robots" content="noindex,nofollow">', "Preview, not live", "<title>Conference photography, "
                      "Washington, DC | Event Caliber</title>", ">Conferences<b>.</b></h1>", PAGE["lead"], *PAGE["paragraphs"],
                      f'href="/seo/changes/{cid}/preview/assets/site.css"'):
            self.assertIn(words, page)
        self.assertNotIn('"/assets/', page, "every file of the preview is served by the dashboard, under the preview")
        self.assertEqual(len(re.findall(r'<figure style="--ar:1.5000"><img', page)), 3)
        rows = re.findall(r'<span class="t">(.*?)</span>', page.split("The rest of the coverage")[1])
        self.assertEqual(rows[-1], "Selects within the hour", "the rest of the coverage, the page itself skipped")
        css = self.client.get(f"/seo/changes/{cid}/preview/assets/site.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn(f"url(/seo/changes/{cid}/preview/assets/fonts/", css.text)
        photo = re.search(rf'src="(/seo/changes/{cid}/preview/assets/[^"]+\.jpg)"', page).group(1)
        self.assertEqual(self.client.get(photo).headers["content-type"], "image/jpeg")
        for outside in ("../index.html", "../../../db/convention_social.sqlite3", "/etc/hosts", "fonts"):
            self.assertIsNone(pages.preview_asset(cid, outside), outside)
        self.assertEqual(self.client.get(f"/seo/changes/{cid}/preview/assets/%2E%2E/index.html").status_code, 404)
        title = changes.propose(self.conn, kind="title", page=STAGE, before={"title": "a", "description": "b"},
                                after={"title": "c", "description": "d"}, queries=[], reason="r")
        self.assertEqual(self.client.get(f"/seo/changes/{title}/preview").status_code, 404, "only a new page has one")
        out = build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        self.assertNotIn(NEW, (out / "sitemap.xml").read_text(), "a proposed page is in no sitemap")
        self.assertFalse((out / "coverage/conference").exists())
        self.assertFalse(pages.preview_dir(cid).is_relative_to(out))
        card = html.unescape(self.client.get("/seo/changes").text)
        for words in (f'href="/seo/changes/{cid}/preview"', "See the page first", "Proposed: a new page", PAGE["paragraphs"][1],
                      "Photos: Main stage, Breakout session.", "The search it is for"):
            self.assertIn(words, card)
        token = approve_token.issue(self.conn, self.row(cid), scope=changes.TOKENS)
        tap = html.unescape(self.client.get(f"/seo/changes/{cid}/by-token/approve?token={token}").text)
        self.assertIn(f'<a href="/seo/changes/{cid}/preview">See the page first</a>', tap)
        self.assertIn("Title</span><br>Conference photography, Washington, DC | Event Caliber", tap)

    def test_without_drive_the_preview_says_why_and_is_tried_again_when_opened(self):
        cid = self.page_proposal()
        self.client.cookies.set(COOKIE, make_token("chris"))
        with mock.patch.object(build, "library_fetch", return_value=(None, "Drive is not signed in yet.")):
            r = self.client.get(f"/seo/changes/{cid}/preview", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("No preview of /coverage/conference/ yet", html.unescape(r.headers["location"]).replace("%20", " ").replace("%2F", "/"))
        with mock.patch.object(build, "library_fetch", return_value=(picture, "")):
            self.assertEqual(self.client.get(f"/seo/changes/{cid}/preview").status_code, 200)

    def test_previews_of_decided_changes_are_pruned(self):
        cid, other = self.page_proposal(), self.page_proposal("/coverage/gala/", searches=(("gala photographers", 0, 30, 18.0),))
        for c in (cid, other):
            pages.preview(self.conn, c, fetch=picture)
        self.assertTrue(changes.skip(self.conn, other)[0])
        pages.prune_previews(self.conn)
        self.assertTrue(pages.preview_dir(cid).is_dir())
        self.assertFalse(pages.preview_dir(other).exists())


class Building(PageCase):
    def built(self, rel: str) -> str:
        return (self.root / "dist" / rel).read_text()

    def test_an_approved_page_is_built_listed_after_the_listed_rows_and_never_on_the_home_pages_list(self):
        approved = self.page_proposal()
        self.set(approved, status="approved")
        self.page_proposal("/coverage/gala/", searches=(("gala photographers", 0, 30, 18.0),))     # proposed only
        self.assertEqual(build.public_pages(self.conn), build.PAGES + (NEW,))
        build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        page = html.unescape(self.built("coverage/conference/index.html"))
        for words in ("<title>Conference photography, Washington, DC | Event Caliber</title>", f'content="{PAGE["description"]}"',
                      ">Conferences<b>.</b></h1>", f'<p class="first">{PAGE["lead"]}</p>', *PAGE["paragraphs"],
                      f'<link rel="canonical" href="https://eventcaliber.com{NEW}">'):
            self.assertIn(words, page)
        self.assertNotIn("noindex", page)
        blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, flags=re.S)]
        self.assertEqual([b["@type"] for b in blocks], ["Service", "BreadcrumbList"])
        self.assertEqual((blocks[0]["name"], blocks[0]["url"]), ("Conference photography", f"https://eventcaliber.com{NEW}"))
        self.assertEqual(blocks[1]["itemListElement"][-1]["name"], "Conferences")
        sitemap = self.built("sitemap.xml")
        self.assertIn(f"<loc>https://eventcaliber.com{NEW}</loc>", sitemap)
        self.assertNotIn("/coverage/gala/", sitemap, "a proposed page is not on the site")
        self.assertFalse((self.root / "dist/coverage/gala").exists())

        def rows(text: str) -> list[str]:
            return re.findall(r'<a href="(/coverage/[^"]+/)"><span class="mono g">\d+</span>', text)
        listed = [build.offer.coverage_page(c["key"]) for c in build.offer.listed_coverage()]
        self.assertEqual(rows(self.built("coverage/index.html")), listed + [NEW], "the coverage index: after the listed rows")
        self.assertIn('<span class="mono g">10</span><span class="t">Conferences</span>', self.built("coverage/index.html"))
        self.assertEqual(rows(self.built("index.html")), listed, "the home page's list is the one Chris ordered, untouched")
        self.assertEqual(rows(self.built("coverage/stage/index.html")), [p for p in listed if p != STAGE] + [NEW])
        self.assertEqual(rows(page), listed, "its own rest of the coverage: the listed rows, itself skipped")
        self.assertEqual(json.loads(settings.get(self.conn, changes.BUILT_KEY)), [approved], "for the deploy to mark live")
        self.assertEqual(json.loads(self.built(build.REMOVED_FILE)), {"pages": []})

    def test_a_page_that_no_longer_passes_or_whose_address_is_taken_is_left_off_with_a_note(self):
        cid = self.page_proposal()
        self.set(cid, status="live")
        now = db.utcnow()
        db.insert(self.conn, "conventions", name="Conference Photography", kind="business", start_date="2026-03-01",
                  created_at=now, updated_at=now)
        build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        self.assertFalse((self.root / "dist/coverage/conference").exists())
        self.assertNotIn(NEW, build.public_pages(self.conn))
        note = db.one(self.conn, "SELECT message FROM errors WHERE agent='site' AND kind='seo_change'")["message"]
        self.assertIn(f"Search change {cid} is not on the site: its words no longer pass: the title names 'Conference Photography'", note)
        self.assertIn("no longer pass", changes.view(self.conn)[0]["off_site"])
        stage = self.page_proposal(STAGE)
        self.set(stage, status="approved")
        self.assertEqual(build.with_seo_changes(self.conn, build.page_words(build.offer.load(), build.copy_text(), "Event Caliber"),
                                                "Event Caliber")[2][stage], f"the site already has a page at {STAGE}")

    def test_the_live_builds_photos_for_a_new_page_are_of_its_kinds_after_the_listed_pages(self):
        cid = self.page_proposal(page={**PAGE, "title": f"{PAGE['name']}, {build.AREA}", "shots": ["portrait"]})
        self.set(cid, status="kept")
        ids = [self.photo(n, shot) for n, shot in enumerate(("portrait", "portrait", "main_stage", "portrait", "breakout"))]
        got = build.pick_photos(self.conn, picture)
        self.assertEqual(list(got.pages), build.offer.coverage_keys() + ["conference"])
        self.assertEqual(len(got.pages["conference"]), 3, "its three portraits")
        pool = [{"id": i, "shot_type": s} for i, s in ((1, "portrait"), (2, "breakout"), (3, "portrait"))]
        picked = build.pick_page_photos(pool, [("conference", ("portrait",))])
        self.assertEqual([r["id"] for r in picked["conference"]], [1, 3, 2])
        self.assertEqual([label for *_, label in got.pages["conference"]], ["Portrait"] * 3)
        self.assertTrue(set(ids) <= set(got.ids))

    def test_approve_is_refused_when_the_page_would_no_longer_pass(self):
        cid = self.page_proposal()
        self.assertEqual(pages.problems(self.conn, self.row(cid)), [])
        now = db.utcnow()
        db.insert(self.conn, "conventions", name="Conference Photography", kind="business", start_date="2026-03-01",
                  created_at=now, updated_at=now)
        ok, why = changes.approve(self.conn, cid)
        self.assertFalse(ok)
        self.assertIn("names 'Conference Photography'", why)
        self.assertEqual(self.row(cid)["status"], "proposed")


# ------------------------------------------------------------------ eight weeks on: kept, or taking it down proposed

class Measuring(PageCase):
    def live(self, days_ago: int) -> int:
        cid = self.page_proposal()
        self.keep(self.window(days_ago + 3), {"/": (2, 300, 9.0)}, {"/": [(SEARCH, 0, 60, 34.0)]})
        self.set(cid, status="approved")
        settings.set(self.conn, changes.BUILT_KEY, json.dumps([cid]))
        self.assertEqual(changes.went_live(self.conn, now=datetime.now(timezone.utc) - timedelta(days=days_ago)), [NEW])
        return cid

    def since(self, on_page: int, place: float, elsewhere: int = 20) -> None:
        self.keep(self.window(), {NEW: (1, on_page, place)}, {NEW: [(SEARCH, 1, on_page, place)], "/": [(SEARCH, 0, elsewhere, 30.0)]})

    def test_measured_eight_weeks_and_three_days_after_it_went_live_and_nothing_before(self):
        cid = self.live(0)
        row = self.row(cid)
        self.assertEqual(datetime.fromisoformat(row["measure_after"]) - datetime.fromisoformat(row["live_at"]), timedelta(days=59))
        base = json.loads(row["baseline"])
        self.assertEqual((base["impressions"], base["page_impressions"], base["position"]), (60, 0, 0.0), "no before: nowhere")
        self.assertEqual(changes.measure(self.conn), [], "not before 59 days")
        self.assertIn("its searches were shown 60 times from", changes.describe(row)["baseline_words"])

    def test_kept_when_google_shows_it_for_its_searches_at_place_20_or_better(self):
        cid = self.live(60)
        self.since(40, 9.0)
        seen = changes.measure(self.conn)
        self.assertEqual([(m["id"], m["verdict"]) for m in seen], [(cid, "kept")])
        self.assertIn(f'The new page {NEW} stays: Google showed it for "{SEARCH}" at an average place of 9 in 40 of their 60 showings',
                      seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "kept")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 1, "nothing more proposed")

    def test_worse_than_place_20_proposes_taking_it_down_and_never_takes_it_down_by_itself(self):
        cid = self.live(60)
        self.since(30, 31.0, elsewhere=40)
        seen = changes.measure(self.conn)
        self.assertEqual(seen[0]["verdict"], "down")
        self.assertIn(f"The new page {NEW} did not reach Google's first two pages: for \"{SEARCH}\", shown 70 times", seen[0]["words"])
        self.assertIn("Google showed it at an average place of 31. Taking it down is proposed to you.", seen[0]["words"])
        row = self.row(cid)
        self.assertEqual((row["status"], json.loads(row["result"])["verdict"]), ("kept", "down"))
        self.assertIn(NEW, build.public_pages(self.conn), "still on the site: only his Approve takes it off")
        down = self.row(cid + 1)
        self.assertEqual((down["kind"], down["page"], down["status"]), ("takedown", NEW, "proposed"))
        (title, message), kw = self.pings[-1]
        self.assertEqual(title, "Event Caliber: a page to take down")
        self.assertIn(f"Page: Conference photography, Washington, DC, at {SITE}{NEW}", message)
        self.assertIn("Approve takes it off the site, and its address then sends visitors to the coverage page.", message)
        self.assertIn(f"view, Open, http://127.0.0.1:4610/seo/changes#c{cid + 1}", kw["actions"])
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        card = html.unescape(client.get("/seo/changes").text).split(f'id="c{cid + 1}"')[1].split("</article>")[0]
        for words in ("On the site now", f"Conference photography, Washington, DC, at {SITE}{NEW}",
                      "Taken off the site; its address sends visitors to the coverage page.", "waiting for your Approve",
                      f'action="/seo/changes/{cid + 1}/approve"'):
            self.assertIn(words, card)
        done, _ = changes.brief(self.conn, datetime.now(timezone.utc) - timedelta(hours=1))
        self.assertIn(f"Search: {seen[0]['words']}", done)
        self.assertIn(f"Search: taking down {NEW} proposed; it waits for your Approve.", done)
        ok, words = changes.approve(self.conn, cid + 1)
        self.assertTrue(ok, words)
        self.assertIn(f"{NEW} comes off the site when it next publishes", words)
        self.assertTrue(settings.get(self.conn, deploy.SEO_CHANGED_KEY), "the site republishes")
        build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        self.assertFalse((self.root / "dist/coverage/conference").exists())
        self.assertEqual(json.loads((self.root / "dist" / build.REMOVED_FILE).read_text()), {"pages": [NEW]})
        self.assertNotIn(NEW, (self.root / "dist/sitemap.xml").read_text())
        self.assertNotIn(NEW, (self.root / "dist/coverage/index.html").read_text())
        self.assertEqual(changes.went_live(self.conn), [NEW])
        down = self.row(cid + 1)
        self.assertEqual(down["status"], "kept", "nothing to measure: done as it goes live")
        self.assertEqual(changes.describe(down)["status_words"], "taken down")
        done, _ = changes.brief(self.conn, datetime.now(timezone.utc) - timedelta(minutes=1))
        self.assertIn(f"Search: {NEW} is off the site; its address sends visitors to the coverage page.", done)
        self.assertNotIn(f"Search: {NEW} is off the site.", done, "said once, by what was done")

    def test_skipping_the_take_down_keeps_the_page(self):
        cid = self.live(60)
        self.since(30, 31.0, elsewhere=40)
        changes.measure(self.conn)
        ok, words = changes.skip(self.conn, cid + 1)
        self.assertEqual((ok, words), (True, f"Skipped. {NEW} stays on the site."))
        self.assertIn(NEW, build.public_pages(self.conn))
        self.assertEqual(self.row(cid)["status"], "kept")

    def test_too_few_showings_wait_a_week_until_sixteen_weeks_then_taking_it_down_is_proposed(self):
        cid = self.live(60)
        self.since(10, 8.0)
        seen = changes.measure(self.conn)
        self.assertIsNone(seen[0]["verdict"])
        self.assertIn(f'{NEW}: "{SEARCH}" was shown 30 times from', seen[0]["words"])
        self.assertIn("fewer than 50: measured again next week", seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "live")
        self.conn.execute("DELETE FROM seo_changes")
        self.conn.execute("DELETE FROM search_console_rows")
        cid = self.live(120)
        self.since(10, 8.0)
        seen = changes.measure(self.conn)
        self.assertEqual(seen[0]["verdict"], "down")
        self.assertIn("fewer than 50 sixteen weeks after it went live. Taking it down is proposed to you.", seen[0]["words"])
        self.assertEqual(self.row(cid + 1)["kind"], "takedown")


# ------------------------------------------------------------------ the brief and the weekly run

class Telling(PageCase):
    def test_the_brief_says_what_was_proposed_approved_and_put_live(self):
        now = datetime.now(timezone.utc)
        cid = self.page_proposal()
        done, _ = changes.brief(self.conn, now - timedelta(hours=1))
        self.assertIn(f'Search: a new page proposed, {NEW}. Searched "{SEARCH}" 60 times in Google.', done)
        self.assertTrue(changes.approve(self.conn, cid)[0])
        settings.set(self.conn, changes.BUILT_KEY, json.dumps([cid]))
        changes.went_live(self.conn)
        done, _ = changes.brief(self.conn, now - timedelta(hours=1))
        self.assertIn(f"Search: you approved the new page {NEW}.", done)
        self.assertIn(f"Search: the new page {NEW} is on the site, measured for eight weeks from now.", done)
        self.assertEqual(changes.approve(self.conn, cid)[0], False)
        self.assertEqual(changes.describe(self.row(cid))["preview"], f"/seo/changes/{cid}/preview")

    def test_a_dry_run_reads_nothing_pays_nothing_and_proposes_nothing(self):
        win = self.window()
        search_console.keep_rows(self.conn, *win, [], [{"keys": [SITE + "/", SEARCH], "clicks": 0, "impressions": 30, "position": 12.0}])
        fake, google = FakeClaude(answer()), mock.Mock()
        with mock.patch.object(build, "library_fetch") as fetch:
            line = seo_agent.run(make_ctx(self.conn, agent="seo", dry_run=True), console=google, changes_client=fake)
        self.assertIn("search changes: none in dry run (nothing read, measured, paid for or proposed)", line)
        self.assertEqual((fake.calls, google.call_count, fetch.call_count, self.spent(), self.pings), ([], 0, 0, [], []))
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)

    def test_the_live_week_proposes_a_page_after_parts_one_and_two_and_says_so(self):
        def google(method, url, body, headers):
            if url.endswith("/sites"):
                return 200, {"siteEntry": [{"siteUrl": "sc-domain:eventcaliber.com", "permissionLevel": "siteOwner"}]}
            dims = (body or {}).get("dimensions")
            if not dims:
                return 200, {"rows": [{"clicks": 20, "impressions": 900, "position": 5.0}]}
            if dims == ["query"]:
                return 200, {"rows": []}
            if dims == ["page"]:
                return 200, {"rows": [{"keys": [SITE + "/"], "clicks": 30, "impressions": 500, "position": 3.0}]}
            return 200, {"rows": [{"keys": [SITE + "/", "gala photographers"], "clicks": 0, "impressions": 44, "position": 23.0}]}
        fake = FakeClaude(answer(heading="Galas", name="Gala photography"))
        with mock.patch.object(search_console, "access_token", return_value="tok"), \
                mock.patch.object(build, "library_fetch", return_value=(None, "Drive is not signed in yet.")), \
                mock.patch.object(seo_agent.site_check, "run_check", return_value={"checked": 1, "failed": 0}):
            line = seo_agent.run(make_ctx(self.conn, agent="seo", dry_run=False), console=google, changes_client=fake)
        self.assertIn("Near misses: no page sat just off the first page for a search from", line)
        self.assertIn('New pages: /coverage/gala/: proposed (change 1) for "gala photographers", ping sent', line)
        self.assertIn("Standing: 1 waiting for your Approve.", line)
        self.assertEqual((len(fake.calls), self.row(1)["kind"]), (1, "page"))


if __name__ == "__main__":
    import unittest
    unittest.main()
