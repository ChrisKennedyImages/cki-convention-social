"""The SEO loop, part one (Chris, 2026-11-01: "shouldn't we have it do it all. Why wouldn't we?"; "One tap from my
phone"): pages whose title and description lose the click get new words from Claude, proposed with a ping and a
signed one-tap Approve, laid on the site only once approved, measured for four weeks and put back by themselves if
fewer people click. Search Console, Claude and ntfy are fakes; every date is relative to now."""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import time
import types
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import chief
from convention_social.agents import seo as seo_agent
from convention_social.core import approve_token, auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.seo import changes, search_console, titles
from convention_social.site import build, deploy
from tests._fakes import AgentCase, make_ctx

SITE = "https://eventcaliber.com"
STAGE, BREAKOUTS, DINNERS = "/coverage/stage/", "/coverage/breakouts/", "/coverage/dinners/"
NEW_TITLE = "Main stage and keynote photographers in Washington, DC"
NEW_DESCRIPTION = ("Photos of the main stage, the keynotes and the panels at conferences and conventions in Washington, DC "
                   "and nationwide. Request a quote.")
SEARCHES = [("conference photographer dc", 1, 120, 3.8), ("keynote photographer", 0, 90, 4.5), ("cpac photographer", 0, 40, 5.0)]


def today() -> date:
    return datetime.now(timezone.utc).date()


class FakeClaude:
    """beta.messages.create, recorded; answers {"title", "description"} (one answer, or one per call in turn)."""

    def __init__(self, *answers, stop="end_turn", error=None):
        self.answers = list(answers) or [{"title": NEW_TITLE, "description": NEW_DESCRIPTION}]
        self.calls, self.stop, self.error = [], stop, error
        self.beta = types.SimpleNamespace(messages=self)

    def create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(answer))], stop_reason=self.stop,
                                     model=kw["model"], usage=types.SimpleNamespace(input_tokens=900, output_tokens=300))


class LoopCase(AgentCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = self.connect()
        self.pings = []
        pusher = mock.patch.object(changes.notify, "push_result", side_effect=lambda *a, **kw: self.pings.append((a, kw)) or "sent")
        pusher.start()
        self.addCleanup(pusher.stop)

    def window(self, ends_days_ago: int = 3) -> tuple[date, date]:
        end = today() - timedelta(days=ends_days_ago)
        return end - timedelta(days=27), end

    def keep(self, win, pages: dict, searches: dict | None = None):
        """Rows as the weekly read keeps them: each page's own (clicks, impressions, place), and its searches."""
        search_console.keep_rows(self.conn, *win,
                                 [{"keys": [SITE + p], "clicks": c, "impressions": i, "position": pos} for p, (c, i, pos) in pages.items()],
                                 [{"keys": [SITE + p, q], "clicks": c, "impressions": i, "position": pos}
                                  for p, rows in (searches or {}).items() for q, c, i, pos in rows])

    def weak_stage(self):
        win = self.window()
        self.keep(win, {STAGE: (2, 340, 4.2)}, {STAGE: SEARCHES})
        return tuple(d.isoformat() for d in win)

    def own(self, path: str) -> tuple[str, str]:
        return build.site_words(self.conn)[build.rel_of(path)]

    def proposal(self, path=STAGE, title=NEW_TITLE, description=NEW_DESCRIPTION, **kw) -> int:
        before_title, before_description = self.own(path)
        return changes.propose(self.conn, kind="title", page=path, before={"title": before_title, "description": before_description},
                               after={"title": title, "description": description}, queries=[], reason="Shown 340 times.", **kw)

    def row(self, cid):
        return changes.get(self.conn, cid)

    def set(self, cid, **values):
        sets = ", ".join(f"{k}=?" for k in values)
        self.conn.execute(f"UPDATE seo_changes SET {sets} WHERE id=?", (*values.values(), cid))

    def spent(self) -> list:
        return db.rows(self.conn, "SELECT detail, cost_usd FROM api_usage WHERE provider='anthropic'")


# ------------------------------------------------------------------ the data

class Reading(LoopCase):
    def test_the_weekly_read_keeps_every_page_and_every_search_on_a_page_for_its_window(self):
        class Google:
            def __init__(self, page_clicks=9):
                self.calls, self.page_clicks = [], page_clicks

            def __call__(self, method, url, body, headers):
                self.calls.append(body)
                if url.endswith("/sites"):
                    return 200, {"siteEntry": [{"siteUrl": "sc-domain:eventcaliber.com", "permissionLevel": "siteOwner"}]}
                dims = (body or {}).get("dimensions")
                if not dims:
                    return 200, {"rows": [{"clicks": 12, "impressions": 340, "position": 6.1}]}
                if dims == ["query"]:
                    return 200, {"rows": [{"keys": ["event caliber"], "clicks": 5, "impressions": 40, "position": 1.2}]}
                if dims == ["page"]:
                    return 200, {"rows": [{"keys": [SITE + "/"], "clicks": self.page_clicks, "impressions": 200, "position": 4.26},
                                          {"keys": [SITE + STAGE], "clicks": 2, "impressions": 140, "position": 7.0}]}
                return 200, {"rows": [{"keys": [SITE + STAGE, "keynote photographer"], "clicks": 1, "impressions": 90, "position": 6.5},
                                      {"keys": [SITE + STAGE, "stage photos"], "clicks": 1, "impressions": 30, "position": 8.0}]}
        g = Google()
        r = search_console.read(self.conn, transport=g, today=today(), token="tok")
        start, end = search_console.window(today())
        page_bodies = [b for b in g.calls if b and b.get("dimensions") in (["page"], ["page", "query"])]
        self.assertEqual([(b["dimensions"], b["rowLimit"], b["startDate"], b["endDate"]) for b in page_bodies],
                         [(["page"], 1000, start.isoformat(), end.isoformat()), (["page", "query"], 1000, start.isoformat(), end.isoformat())])
        win = (start.isoformat(), end.isoformat())
        self.assertEqual(search_console.latest_window(self.conn), win)
        self.assertEqual(search_console.page_numbers(self.conn, win, SITE + "/"),
                         {"start": win[0], "end": win[1], "clicks": 9, "impressions": 200, "ctr": 0.045, "position": 4.3})
        self.assertEqual([q["query"] for q in search_console.searches(self.conn, win, SITE + STAGE)], ["keynote photographer", "stage photos"])
        self.assertEqual(search_console.page_numbers(self.conn, win, SITE + "/about/")["impressions"], 0, "a page Google did not list")
        self.assertEqual(r["pages"][0], {"key": SITE + "/", "clicks": 9, "impressions": 200, "position": 4.3}, "the brief's top pages")
        self.assertIn("Google search, ", search_console.line(r))
        search_console.read(self.conn, transport=Google(page_clicks=11), today=today(), token="tok")
        self.assertEqual(search_console.page_numbers(self.conn, win, SITE + "/")["clicks"], 11, "a second read of a window replaces it")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM search_console_rows")["n"], 4)


# ------------------------------------------------------------------ finding

class Finding(LoopCase):
    def test_the_usual_click_rate_is_the_industry_table_on_the_first_page_only(self):
        self.assertEqual(titles.expected_ctr(1), titles.EXPECTED_CTR[1])
        self.assertEqual(titles.expected_ctr(10), titles.EXPECTED_CTR[10])
        self.assertAlmostEqual(titles.expected_ctr(4.5), (titles.EXPECTED_CTR[4] + titles.EXPECTED_CTR[5]) / 2)
        self.assertIsNone(titles.expected_ctr(10.2), "past the first page the words are not what loses the click")
        self.assertIsNone(titles.expected_ctr(0), "no place given")
        self.assertEqual(list(titles.EXPECTED_CTR), list(range(1, 11)))
        self.assertTrue(all(a > b for a, b in zip(titles.EXPECTED_CTR.values(), list(titles.EXPECTED_CTR.values())[1:])))

    def test_a_page_shown_100_times_and_clicked_under_half_its_usual_rate_is_weak(self):
        win = self.window()
        rows = {STAGE: (2, 340, 4.2),                    # usual 8.0%: 2 of 340 is 0.6%, weak
                BREAKOUTS: (14, 340, 4.2),               # 4.1%, just over half its usual: fine
                DINNERS: (0, 99, 3.0),                   # 99 showings say too little
                "/coverage/portraits/": (0, 500, 12.0),  # past the first page: part two's
                "/": (1, 1000, 6.0),                     # usual 4.9%: 0.1%, weak, and the most clicks missing
                "/assets/hero-1600.jpg": (0, 900, 2.0)}  # not a page of the site
        search_console.keep_rows(self.conn, *win, [{"keys": [SITE + p], "clicks": c, "impressions": i, "position": pos}
                                                   for p, (c, i, pos) in rows.items()]
                                 + [{"keys": ["https://www.eventcaliber.com" + DINNERS], "clicks": 0, "impressions": 900, "position": 2.0}], [])
        weak = titles.weak_pages(self.conn, tuple(d.isoformat() for d in win))
        self.assertEqual([w["path"] for w in weak], ["/", STAGE], "the most clicks missing first; the www address is not the page")
        self.assertEqual(weak[1]["impressions"], 340)
        self.assertIn("Shown 340 times in Google search", titles.reason(weak[1]))
        self.assertIn("clicked 2 times (0.6%). Results at that place usually get about 8.0%", titles.reason(weak[1]))


# ------------------------------------------------------------------ drafting

class Drafting(LoopCase):
    def test_claude_writes_from_the_real_searches_and_the_draft_is_proposed_and_pinged(self):
        self.weak_stage()
        fake = FakeClaude()
        said = titles.propose_week(self.conn, client=fake)
        self.assertEqual(said, f"{STAGE}: proposed (change 1), ping sent")
        facts = json.loads(fake.calls[0]["messages"][0]["content"])
        self.assertEqual([s["search"] for s in facts["searches"]], [q for q, *_ in SEARCHES])
        self.assertEqual((facts["title_now"], facts["description_now"]), self.own(STAGE))
        self.assertEqual((facts["title_suffix"], facts["title_max_characters"]), (" | Event Caliber", 75 - 16))
        self.assertIn("Never name an event", fake.calls[0]["system"])
        self.assertEqual(fake.calls[0]["model"], titles.MODEL)
        row = self.row(1)
        self.assertEqual((row["kind"], row["page"], row["status"]), ("title", STAGE, "proposed"))
        before_title, before_description = self.own(STAGE)
        self.assertEqual(json.loads(row["before"]), {"title": before_title, "description": before_description})
        self.assertEqual(json.loads(row["after"]), {"title": NEW_TITLE, "description": NEW_DESCRIPTION})
        self.assertEqual(json.loads(row["fields"]), ["title", "description"])
        self.assertEqual([q["query"] for q in json.loads(row["queries"])], [q for q, *_ in SEARCHES])
        self.assertIn("usually get about 8.0%", row["reason"])
        self.assertEqual(self.own(STAGE), (before_title, before_description), "nothing on the site changes until Approve")
        spent = self.spent()
        self.assertEqual(len(spent), 1, "reserved, then recorded on the same row")
        self.assertIn("seo title /coverage/stage/", spent[0]["detail"])
        self.assertGreater(spent[0]["cost_usd"], 0)
        (title, message), kw = self.pings[0]
        self.assertEqual(title, "Event Caliber: new search words to approve")
        self.assertIn(f"Title now: {before_title} | Event Caliber", message)
        self.assertIn(f"Title new: {NEW_TITLE} | Event Caliber", message)
        self.assertIn(f"Description new: {NEW_DESCRIPTION}", message)
        self.assertIn("put back by itself if fewer people click", message)
        self.assertFalse(kw["dry_run"])
        self.assertIn(f"http, Approve, http://127.0.0.1:4610/seo/changes/1/by-token/approve, method=POST", kw["actions"])
        self.assertIn("http, Skip, http://127.0.0.1:4610/seo/changes/1/by-token/skip, method=POST", kw["actions"])
        self.assertIn("view, Open, http://127.0.0.1:4610/seo/changes#c1", kw["actions"])
        token = re.search(r"body='token=([^']+)'", kw["actions"]).group(1)
        self.assertTrue(approve_token.check(self.conn, row, token, scope=changes.TOKENS)[0], "the ping carries a live token")

    def test_a_draft_that_breaks_a_rule_is_dropped_with_the_reason_and_never_proposed(self):
        win = self.weak_stage()
        weak = titles.weak_pages(self.conn, win)[0]
        own_title, own_description = self.own(STAGE)
        for answer, why in (({"title": "CPAC main stage photographers, DC", "description": NEW_DESCRIPTION}, "names 'CPAC'"),
                            ({"title": NEW_TITLE, "description": "Main stage photos from $500 a day."}, "mentions a price"),
                            ({"title": NEW_TITLE, "description": "Every package includes the keynotes."}, "says something about the company"),
                            ({"title": "Main stage, keynote, panel and award photographers for conferences in Washington, DC",
                              "description": NEW_DESCRIPTION}, "characters in a search result, 75 at most"),
                            ({"title": own_title, "description": own_description}, "Claude kept the words the page has"),
                            ({"title": "", "description": NEW_DESCRIPTION}, "the title is empty")):
            said = titles.draft(self.conn, FakeClaude(answer), weak, win)
            self.assertTrue(said.startswith(f"{STAGE}: dropped, "), said)
            self.assertIn(why, said)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)
        said = titles.draft(self.conn, FakeClaude({"title": "Main stage — keynote photographers in Washington, DC",
                                                   "description": NEW_DESCRIPTION}), weak, win)
        self.assertIn("proposed", said, "a dash is tidied into a comma, as every caption's is")
        self.assertEqual(json.loads(self.row(db.one(self.conn, "SELECT MAX(id) m FROM seo_changes")["m"])["after"])["title"],
                         "Main stage, keynote photographers in Washington, DC")
        self.assertEqual(titles.draft(self.conn, FakeClaude(stop="refusal"), weak, win),
                         f"{STAGE}: dropped, Claude refused or gave nothing readable")

    def test_at_most_two_pages_a_week(self):
        win = self.window()
        self.keep(win, {STAGE: (2, 340, 4.2), BREAKOUTS: (1, 300, 4.0), DINNERS: (0, 300, 3.0)})
        fake = FakeClaude()
        said = titles.propose_week(self.conn, client=fake)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes WHERE status='proposed'")["n"], 2)
        self.assertEqual(said.count("proposed"), 2)
        said = titles.propose_week(self.conn, client=fake)
        self.assertIn("left alone, change", said, "a page with an open change is not drafted again")
        self.assertEqual(len(fake.calls), 3, "the third page's turn")

    def test_the_cap_a_missing_key_and_a_failing_call_stop_it_cleanly(self):
        self.weak_stage()
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        fake = FakeClaude()
        self.assertEqual(titles.propose_week(self.conn, client=fake), "the monthly AI cap is reached, so nothing more drafted")
        self.assertEqual((fake.calls, self.spent()), ([], []))
        os.environ["AI_MONTHLY_CAP_USD"] = "20"
        config.reset()
        self.assertEqual(titles.propose_week(self.conn), "no Anthropic key, so nothing drafted")
        said = titles.propose_week(self.conn, client=FakeClaude(error=ConnectionError("down")))
        self.assertEqual(said, f"{STAGE}: Claude could not be asked (ConnectionError)")
        self.assertEqual(self.spent(), [], "the reservation is released")
        self.assertIn("could not be drafted", db.one(self.conn, "SELECT message FROM errors WHERE kind='seo_title'")["message"])
        self.assertEqual(self.pings, [])


# ------------------------------------------------------------------ one at a time

class OneAtATime(LoopCase):
    def test_one_open_change_per_page_and_eight_weeks_of_rest(self):
        cid = self.proposal()
        with self.assertRaises(changes.Refused) as cm:
            self.proposal()
        self.assertIn(f"change {cid} for it is waiting for your Approve", str(cm.exception))
        with self.assertRaises(sqlite3.IntegrityError):
            db.insert(self.conn, "seo_changes", kind="title", page=STAGE, fields="[]", before="{}", after="{}", reason="x",
                      status="approved", proposed_at=db.utcnow(), updated_at=db.utcnow())
        self.assertEqual(changes.resting(self.conn, BREAKOUTS), "", "another page is free")
        now = datetime.now(timezone.utc)
        self.set(cid, status="kept", live_at=(now - timedelta(weeks=7)).isoformat(timespec="seconds"))
        self.assertIn("put live less than eight weeks ago", changes.resting(self.conn, STAGE))
        self.set(cid, live_at=(now - timedelta(weeks=9)).isoformat(timespec="seconds"))
        self.assertEqual(changes.resting(self.conn, STAGE), "")
        other = self.proposal(BREAKOUTS)
        self.assertTrue(changes.skip(self.conn, other)[0])
        self.assertIn("was skipped less than eight weeks ago", changes.resting(self.conn, BREAKOUTS))


# ------------------------------------------------------------------ approving

class Approving(LoopCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(create_app())

    def signed_in(self):
        self.client.cookies.set(COOKIE, make_token("chris"))

    def tap(self, cid, how, token):
        return self.client.post(f"/seo/changes/{cid}/by-token/{how}", content=f"token={token}",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})

    def test_the_pings_approve_is_signed_single_use_and_sends_the_site_to_publish(self):
        cid = self.proposal()
        token = approve_token.issue(self.conn, self.row(cid), scope=changes.TOKENS)
        page = self.client.get(f"/seo/changes/{cid}/by-token/approve?token={token}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'action="/seo/changes/{cid}/by-token/approve"', page.text)
        self.assertIn(NEW_TITLE, page.text)
        self.assertEqual(self.row(cid)["status"], "proposed", "a GET decides nothing")
        self.assertIsNone(settings.get(self.conn, deploy.SEO_CHANGED_KEY))
        r = self.tap(cid, "approve", token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(f"The new words go on {STAGE} when the site next publishes", r.text)
        self.assertEqual(self.row(cid)["status"], "approved")
        self.assertTrue(self.row(cid)["approved_at"])
        self.assertTrue(settings.get(self.conn, deploy.SEO_CHANGED_KEY))
        stamp = datetime.fromisoformat(settings.get(self.conn, deploy.SEO_CHANGED_KEY))
        self.assertEqual(deploy.photos_pending(self.conn, now=stamp + timedelta(minutes=11)),
                         (True, f"a search change was approved or put back at {stamp:%H:%M}; publishing them"))
        r = self.tap(cid, "approve", token)
        self.assertEqual(r.status_code, 409)
        self.assertIn("already used", r.text)
        self.assertIn("the Search changes page", r.text)

    def test_skip_from_the_ping_and_tokens_that_do_not_open_this_change(self):
        cid = self.proposal()
        row = self.row(cid)
        self.assertEqual(self.tap(cid, "approve", "nonsense").status_code, 409)
        self.assertEqual(self.tap(999, "approve", "1.2.3").status_code, 404)
        self.assertEqual(self.tap(cid, "publish", "1.2.3").status_code, 404)
        post_token = approve_token.issue(self.conn, row)                         # a post's token for the same number
        self.assertIn("already used", self.tap(cid, "approve", post_token).text, "a post's token never opens a change")
        expired = approve_token.issue(self.conn, row, now=time.time() - 40 * 3600, scope=changes.TOKENS)
        self.assertIn("expired", self.tap(cid, "approve", expired).text)
        stale = approve_token.issue(self.conn, row, scope=changes.TOKENS)
        self.set(cid, updated_at="2026-01-01T00:00:00+00:00")
        self.assertIn("moved on since that ping", self.tap(cid, "approve", stale).text)
        fresh = approve_token.issue(self.conn, self.row(cid), scope=changes.TOKENS)
        r = self.tap(cid, "skip", fresh)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("keeps its words", r.text)
        self.assertEqual(self.row(cid)["status"], "skipped")
        self.assertIsNone(settings.get(self.conn, deploy.SEO_CHANGED_KEY), "a skip before Approve changes nothing on the site")
        self.assertEqual(self.tap(cid, "approve", fresh).status_code, 409)

    def test_the_page_shows_before_and_after_with_approve_and_skip(self):
        self.assertEqual(self.client.get("/seo/changes", follow_redirects=False).status_code, 307)
        self.assertEqual(self.client.post("/seo/changes/1/approve").status_code, 401)
        cid, other = self.proposal(), self.proposal(BREAKOUTS)
        self.signed_in()
        page = html.unescape(self.client.get("/seo/changes").text)
        own_title, own_description = self.own(STAGE)
        for words in (f"{own_title} | Event Caliber", own_description, f"{NEW_TITLE} | Event Caliber", NEW_DESCRIPTION, "Shown 340 times.",
                      f'action="/seo/changes/{cid}/approve"', f'action="/seo/changes/{cid}/skip"', "waiting for your Approve"):
            self.assertIn(words, page)
        self.assertIn("2 waiting", self.client.get("/seo").text, "the Search page leads to it")
        r = self.client.post(f"/seo/changes/{cid}/approve", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("msg=Approved", r.headers["location"])
        self.assertEqual(self.row(cid)["status"], "approved")
        self.assertIn("Take it back", self.client.get("/seo/changes").text)
        self.assertIn("bad=", self.client.post(f"/seo/changes/{cid}/approve", follow_redirects=False).headers["location"])
        self.client.post(f"/seo/changes/{other}/skip")
        self.assertEqual(self.row(other)["status"], "skipped")

    def test_approve_is_refused_when_the_words_would_no_longer_pass(self):
        cid = self.proposal()
        now = db.utcnow()
        db.insert(self.conn, "conventions", name="Keynote Photographers", kind="business", start_date="2026-03-01",
                  created_at=now, updated_at=now)
        ok, why = changes.approve(self.conn, cid)
        self.assertFalse(ok)
        self.assertIn("names 'Keynote Photographers'", why)
        self.assertEqual(self.row(cid)["status"], "proposed")

    def test_today_and_the_brief_say_a_change_waits(self):
        self.proposal()
        self.assertIn(("1 search change(s) waiting for your Approve: new words for a page that loses clicks.", "/seo/changes"),
                      chief.needs(self.conn))
        self.signed_in()
        self.assertIn('href="/seo/changes"', self.client.get("/").text)

    def test_through_cloudflare_access_the_buttons_open_the_page_in_the_browser(self):
        os.environ["DASHBOARD_PUBLIC_URL"] = "https://dash.eventcaliber.com"
        config.reset()
        actions = changes.actions(4, "1.n.s")
        self.assertIn("view, Approve, https://dash.eventcaliber.com/seo/changes/4/by-token/approve?token=1.n.s, clear=true", actions)
        self.assertIn("view, Skip, https://dash.eventcaliber.com/seo/changes/4/by-token/skip?token=1.n.s, clear=true", actions)


# ------------------------------------------------------------------ the site

class Building(LoopCase):
    def built(self, rel: str) -> tuple[str, str]:
        text = (self.root / "dist" / rel).read_text()
        return (html.unescape(re.search(r"<title>(.*?)</title>", text).group(1)),
                html.unescape(re.search(r'<meta name="description" content="(.*?)">', text).group(1)))

    def test_the_build_lays_an_approved_change_and_not_a_proposed_one(self):
        approved = self.proposal()
        self.set(approved, status="approved")
        self.proposal(BREAKOUTS, title="Breakout and panel photographers in Washington, DC")
        own_breakouts = self.own(BREAKOUTS)
        build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        self.assertEqual(self.built("coverage/stage/index.html"), (f"{NEW_TITLE} | Event Caliber", NEW_DESCRIPTION))
        self.assertEqual(self.built("coverage/breakouts/index.html"), (f"{own_breakouts[0]} | Event Caliber", own_breakouts[1]))
        self.assertEqual(json.loads(settings.get(self.conn, changes.BUILT_KEY)), [approved], "for the deploy to mark live")
        build.build(self.conn, build.SitePhotos(), out=self.root / "preview", preview=True)
        self.assertEqual(json.loads(settings.get(self.conn, changes.BUILT_KEY)), [approved], "a preview records nothing")

    def test_a_change_that_no_longer_passes_is_left_off_with_a_note(self):
        own = self.own(STAGE)
        cid = self.proposal()
        self.set(cid, status="live")
        now = db.utcnow()
        db.insert(self.conn, "conventions", name="Keynote Photographers", kind="business", start_date="2026-03-01",
                  created_at=now, updated_at=now)
        build.build(self.conn, build.SitePhotos(), out=self.root / "dist")
        self.assertEqual(self.built("coverage/stage/index.html"), (f"{own[0]} | Event Caliber", own[1]), "the page keeps its own words")
        self.assertEqual(json.loads(settings.get(self.conn, changes.BUILT_KEY)), [])
        note = db.one(self.conn, "SELECT message FROM errors WHERE agent='site' AND kind='seo_change'")["message"]
        self.assertIn(f"Search change {cid} is not on the site: its words no longer pass: the title names 'Keynote Photographers'", note)
        self.assertIn("no longer pass", changes.view(self.conn)[0]["off_site"])

    def test_changes_are_laid_in_order_and_only_over_the_words_they_replaced(self):
        brand = config.get_config().brand_name
        first = self.proposal()
        self.set(first, status="kept")
        second = self.proposal(title="Keynote and main stage photographers, Washington, DC")
        before = json.loads(self.row(second)["before"])
        self.assertEqual(before["title"], NEW_TITLE, "the page's words today are the kept change's")
        self.set(second, status="approved")
        words, laid, off = build.with_seo_changes(self.conn, build.page_words(build.offer.load(), build.copy_text(), brand), brand)
        self.assertEqual((laid, off), ([first, second], {}))
        self.assertEqual(words["coverage/stage/index.html"][0], "Keynote and main stage photographers, Washington, DC")
        self.set(first, status="reverted")
        words, laid, off = build.with_seo_changes(self.conn, build.page_words(build.offer.load(), build.copy_text(), brand), brand)
        self.assertEqual(laid, [])
        self.assertEqual(off, {second: f"{STAGE} no longer has the words it replaced"})


# ------------------------------------------------------------------ live, measured, kept or put back

class Measuring(LoopCase):
    def live(self, days_ago: int, base: tuple[int, int, float] = (2, 340, 4.2)) -> int:
        """A change that went live `days_ago`, its baseline taken from a read that ended before."""
        cid = self.proposal()
        went = datetime.now(timezone.utc) - timedelta(days=days_ago)
        self.keep(self.window(days_ago + 3), {STAGE: base})
        self.set(cid, status="approved")
        settings.set(self.conn, changes.BUILT_KEY, json.dumps([cid]))
        self.assertEqual(changes.went_live(self.conn, now=went), [STAGE])
        return cid

    def test_went_live_takes_the_baseline_from_the_last_read_before_and_sets_the_day_it_is_measured(self):
        cid = self.live(0)
        row = self.row(cid)
        self.assertEqual(row["status"], "live")
        base = json.loads(row["baseline"])
        self.assertEqual((base["clicks"], base["impressions"], base["ctr"], base["position"]), (2, 340, 0.0059, 4.2))
        self.assertEqual(datetime.fromisoformat(row["measure_after"]) - datetime.fromisoformat(row["live_at"]), timedelta(days=31))
        self.assertEqual(changes.went_live(self.conn), [], "once")
        self.assertEqual(changes.measure(self.conn), [], "not before 31 days")

    def test_kept_when_the_clicks_hold(self):
        cid = self.live(33)
        self.keep(self.window(), {STAGE: (12, 400, 3.9)})
        seen = changes.measure(self.conn)
        self.assertEqual([(m["id"], m["verdict"]) for m in seen], [(cid, "kept")])
        self.assertIn(f"The new words on {STAGE} stay: 3.0% of 400 showings clicked", seen[0]["words"])
        self.assertIn("against 0.6% of 340 before", seen[0]["words"])
        row = self.row(cid)
        self.assertEqual((row["status"], json.loads(row["result"])["verdict"]), ("kept", "kept"))
        self.assertTrue(row["verdict_at"])
        self.assertEqual(self.own(STAGE)[0], NEW_TITLE, "a kept change stays on the site")
        self.assertIsNone(settings.get(self.conn, deploy.SEO_CHANGED_KEY))

    def test_put_back_when_the_click_rate_falls_by_a_fifth_or_more(self):
        cid = self.live(33, base=(20, 400, 3.0))           # 5.0% before
        self.keep(self.window(), {STAGE: (15, 400, 3.0)})   # 3.75%: a quarter fewer
        seen = changes.measure(self.conn)
        self.assertEqual(seen[0]["verdict"], "reverted")
        self.assertIn(f"The new words on {STAGE} were put back: 3.8% of 400 showings clicked", seen[0]["words"])
        self.assertIn("against 5.0% of 400 before, 25% fewer", seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "reverted")
        self.assertTrue(settings.get(self.conn, deploy.SEO_CHANGED_KEY), "the site republishes")
        self.assertNotEqual(self.own(STAGE)[0], NEW_TITLE, "the page has its own words again")
        self.assertIn("put live less than eight weeks ago", changes.resting(self.conn, STAGE))

    def test_a_tenth_fewer_is_kept(self):
        self.live(33, base=(20, 400, 3.0))
        self.keep(self.window(), {STAGE: (18, 400, 3.0)})
        self.assertEqual(changes.measure(self.conn)[0]["verdict"], "kept")

    def test_too_few_showings_since_keeps_measuring_and_says_so(self):
        cid = self.live(33)
        self.keep(self.window(), {STAGE: (1, 60, 4.0)})
        seen = changes.measure(self.conn)
        self.assertIsNone(seen[0]["verdict"])
        self.assertIn(f"{STAGE} was shown 60 times in Google since its new words went live", seen[0]["words"])
        self.assertIn("fewer than 100: measured again next week", seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "live")
        _, watching = changes.brief(self.conn, datetime.now(timezone.utc) - timedelta(hours=24))
        self.assertEqual(watching, [f"Search: {seen[0]['words']}"])

    def test_no_read_of_the_days_since_waits_for_one(self):
        cid = self.live(33)
        seen = changes.measure(self.conn)
        self.assertIn("no Search Console read of the days since its new words went live yet", seen[0]["words"])
        self.assertEqual(self.row(cid)["status"], "live")


# ------------------------------------------------------------------ the brief and the weekly run

class Telling(LoopCase):
    def test_the_morning_brief_says_what_was_proposed_approved_kept_and_put_back(self):
        now = datetime.now(timezone.utc)
        recent, old = (now - timedelta(hours=2)).isoformat(timespec="seconds"), (now - timedelta(days=40)).isoformat(timespec="seconds")
        proposed = self.proposal()
        approved = self.proposal(BREAKOUTS)
        self.set(approved, status="approved", approved_at=recent, proposed_at=old)
        kept = self.proposal(DINNERS)
        self.set(kept, status="kept", proposed_at=old, approved_at=old, live_at=old, verdict_at=recent,
                 result=json.dumps({"verdict": "kept", "words": f"The new words on {DINNERS} stay: 3.0% of 400 showings clicked."}))
        back = self.proposal("/coverage/portraits/")
        self.set(back, status="reverted", proposed_at=old, approved_at=old, live_at=old, verdict_at=recent,
                 result=json.dumps({"verdict": "reverted", "words": "The new words on /coverage/portraits/ were put back."}))
        b = chief.gather(make_ctx(self.conn, agent="chief", dry_run=True), now)
        self.assertIn(f"Search: new words proposed for {STAGE}. Shown 340 times.", b["done"])
        self.assertIn(f"Search: you approved the new words for {BREAKOUTS}.", b["done"])
        self.assertIn(f"Search: The new words on {DINNERS} stay: 3.0% of 400 showings clicked.", b["done"])
        self.assertIn("Search: The new words on /coverage/portraits/ were put back.", b["done"])
        self.assertIn(("1 search change(s) waiting for your Approve: new words for a page that loses clicks.", "/seo/changes"), b["needs"])
        self.assertEqual(changes.brief(self.conn, now + timedelta(hours=1)), ([], []), "only what happened since the last brief")
        self.assertEqual(proposed, 1)

    def test_the_home_page_is_called_the_home_page_and_its_title_keeps_the_name(self):
        home = "Conference and convention photographers in Washington, DC | Event Caliber"
        cid = self.proposal("/", title=home)
        _, message = changes.ping_words(self.row(cid))
        self.assertTrue(message.startswith("The home page: Shown 340 times."), message)
        self.assertIn(f"Title new: {home}\n", message, "the home page's title is whole: no second name after it")
        self.assertEqual(changes.describe(self.row(cid))["name"], "The home page")
        brand = config.get_config().brand_name
        self.assertIn("the home page's title must keep the name Event Caliber",
                      build.words_problems("index.html", "Convention photographers in Washington, DC", NEW_DESCRIPTION, brand, []))
        self.assertEqual(build.words_problems("index.html", home, NEW_DESCRIPTION, brand, []), [])

    def test_a_dry_run_reads_nothing_pays_nothing_and_proposes_nothing(self):
        self.weak_stage()
        fake, google = FakeClaude(), mock.Mock()
        line = seo_agent.run(make_ctx(self.conn, agent="seo", dry_run=True), console=google, title_client=fake)
        self.assertIn("search changes: none in dry run (nothing read, measured, paid for or proposed)", line)
        self.assertEqual((fake.calls, google.call_count, self.spent(), self.pings), ([], 0, [], []))
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM seo_changes")["n"], 0)

    def test_the_live_week_reads_measures_then_proposes_and_says_so(self):
        due = self.live_change_due()

        def google(method, url, body, headers):
            if url.endswith("/sites"):
                return 200, {"siteEntry": [{"siteUrl": "sc-domain:eventcaliber.com", "permissionLevel": "siteOwner"}]}
            dims = (body or {}).get("dimensions")
            if not dims:
                return 200, {"rows": [{"clicks": 20, "impressions": 900, "position": 5.0}]}
            if dims == ["query"]:
                return 200, {"rows": []}
            if dims == ["page"]:
                return 200, {"rows": [{"keys": [SITE + STAGE], "clicks": 30, "impressions": 500, "position": 3.0},
                                      {"keys": [SITE + BREAKOUTS], "clicks": 1, "impressions": 300, "position": 4.0}]}
            return 200, {"rows": [{"keys": [SITE + BREAKOUTS, "panel photographer"], "clicks": 0, "impressions": 120, "position": 4.1}]}
        fake = FakeClaude({"title": "Breakout and panel photographers in Washington, DC", "description": NEW_DESCRIPTION})
        with mock.patch.object(search_console, "access_token", return_value="tok"), \
                mock.patch.object(seo_agent.site_check, "run_check", return_value={"checked": 1, "failed": 0}):
            line = seo_agent.run(make_ctx(self.conn, agent="seo", dry_run=False), console=google, title_client=fake)
        self.assertIn(f"search changes: The new words on {STAGE} stay", line)
        self.assertIn(f"New words: {BREAKOUTS}: proposed (change {due + 1}), ping sent.", line)
        self.assertIn("Standing: 1 waiting for your Approve.", line)
        self.assertEqual(self.row(due)["status"], "kept")
        self.assertEqual(len(fake.calls), 1)

    def live_change_due(self) -> int:
        cid = self.proposal()
        self.keep(self.window(36), {STAGE: (2, 340, 4.2)})
        self.set(cid, status="approved")
        settings.set(self.conn, changes.BUILT_KEY, json.dumps([cid]))
        changes.went_live(self.conn, now=datetime.now(timezone.utc) - timedelta(days=33))
        return cid


if __name__ == "__main__":
    import unittest
    unittest.main()
