"""SEO parts four and five (Chris, 2026-11-01: all five, "shouldn't we have it do it all"). Four: the photo writer is told
what people search to find the site, only searches made of trade and place words, never a name, and the site's photos
are written once more when those words change. Five: every week Google is asked which pages it has in its index, and
the brief names any it does not."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from convention_social.agents import chief, seo
from convention_social.core import db, settings
from convention_social.seo import photo_text, search_console as gsc
from tests._fakes import make_ctx
from tests.test_search_console import Google
from tests.test_seo import FakeClaude, SeoCase

WIN = ("2026-10-03", "2026-10-30")


class Words(SeoCase):
    def rows(self, *pairs, page="https://eventcaliber.com/"):
        now = db.utcnow()
        for q, shown in pairs:
            db.insert(self.conn, "search_console_rows", read_at=now, start_date=WIN[0], end_date=WIN[1], page=page, query=q,
                      clicks=0, impressions=shown, position=9.0)

    def test_only_trade_and_place_words_never_a_name_never_the_brand(self):
        self.photo(event="CPAC")
        self.rows(("conference photographer dc", 40), ("cpac photographer", 90), ("event caliber", 300), ("jordan example photos", 50),
                  ("keynote photographer", 12), ("convention photography", 3), ("headshots near me", 20), ("event photographer 2025", 30))
        self.rows(("conference photographer dc", 15), page="https://eventcaliber.com/coverage/stage/")
        self.assertEqual(photo_text.search_words(self.conn), ("conference photographer dc", "headshots near me", "keynote photographer"),
                         "summed over pages, most shown first; names, the brand, numbers, unknown words and rare searches left out")

    def test_the_writer_is_told_and_may_use_them(self):
        pid = self.photo(shot="main_stage")
        self.calendar()
        self.rows(("keynote photographer", 20))
        f = photo_text.gather(self.conn, pid)
        self.assertEqual(f.search_words, ("keynote photographer",))
        self.assertIn("What people search to find this company (use a phrase only where it truly describes this photo): keynote photographer",
                      photo_text.user_text(f))
        self.assertIn("keynote photographer", photo_text.merge_keywords(["keynote photographer", "jordan example"], f))
        self.assertNotIn("jordan example", photo_text.merge_keywords(["keynote photographer", "jordan example"], f))

    def test_the_sites_photos_are_written_once_more_when_the_words_change(self):
        shown, other, edited = self.photo(), self.photo(shot="reception"), self.photo(shot="breakout")
        self.calendar()
        photo_text.write_all(self.conn, dry_run=False, client=FakeClaude())
        self.conn.execute("UPDATE photo_seo SET edited_at=? WHERE photo_id=?", (db.utcnow(), edited))
        settings.set(self.conn, "site.shown_photo_ids", json.dumps([shown, edited]))
        old = (datetime.now(timezone.utc) - timedelta(days=3)).replace(microsecond=0).isoformat()
        self.conn.execute("UPDATE photo_seo SET written_at=?", (old,))
        self.rows(("keynote photographer", 20))
        stats = photo_text.write_all(self.conn, dry_run=False, client=FakeClaude())
        self.assertEqual(stats["refreshed"], 1, "the shown photo, once; not the one Chris edited, not one off the site")
        after = {r["photo_id"]: r["written_at"] for r in db.rows(self.conn, "SELECT photo_id, written_at FROM photo_seo")}
        self.assertGreater(after[shown], old)
        self.assertEqual((after[other], after[edited]), (old, old))
        self.assertEqual(photo_text.write_all(self.conn, dry_run=False, client=FakeClaude())["refreshed"], 0, "once per change")
        self.assertEqual(photo_text.write_all(self.conn, dry_run=True)["refreshed"], 0, "a dry run rewrites nothing")


class Index(SeoCase):
    def google(self, verdicts):
        g = Google()
        base = g.__call__

        def answer(method, url, body, headers):
            if url == gsc.INSPECT_API:
                path = body["inspectionUrl"].split("eventcaliber.com", 1)[1]
                v, cov = verdicts.get(path, ("PASS", "Submitted and indexed"))
                return 200, {"inspectionResult": {"indexStatusResult": {"verdict": v, "coverageState": cov,
                                                                        "pageFetchState": "SUCCESSFUL"}}}
            return base(method, url, body, headers)
        return answer

    def test_every_page_is_asked_and_the_brief_names_the_missing(self):
        import os
        from convention_social import offer
        from convention_social.core import config
        os.environ["BRAND_DOMAIN"] = "eventcaliber.com"
        config.reset()
        calls = []
        fake = self.google({"/coverage/selects/": ("NEUTRAL", "Discovered - currently not indexed"), "/book/": ("FAIL", "Server error (5xx)")})

        def recorded(method, url, body, headers):
            calls.append((url, body))
            return fake(method, url, body, headers)
        r = gsc.index_check(self.conn, transport=recorded, token="tok")
        asked = [b["inspectionUrl"] for u, b in calls if u == gsc.INSPECT_API]
        self.assertEqual(asked, [f"https://eventcaliber.com{p}" for p in offer.public_pages()])
        self.assertEqual({b["siteUrl"] for u, b in calls if u == gsc.INSPECT_API}, {"sc-domain:eventcaliber.com"})
        total = len(offer.public_pages())
        self.assertEqual(gsc.index_line(r), f"Google has {total - 2} of {total} pages in its index. Not yet: /coverage/selects/ "
                                            "(Discovered - currently not indexed); /book/ (Server error (5xx)). Search Console, URL "
                                            "inspection, Request indexing asks Google for them.")
        now = datetime.now(timezone.utc)
        self.assertTrue(gsc.fresh_index_line(self.conn, now).startswith("Google has "))
        self.assertEqual(gsc.fresh_index_line(self.conn, now + timedelta(hours=31)), "")
        b = chief.gather(make_ctx(self.conn, agent="chief", dry_run=True), now)
        self.assertTrue(any(w.startswith("Google has ") for w in b["watching"]), b["watching"])

    def test_the_weekly_run_checks_the_index_after_the_numbers(self):
        import os
        from convention_social.core import config
        os.environ["BRAND_DOMAIN"] = "eventcaliber.com"
        config.reset()
        with mock.patch.object(gsc, "access_token", return_value="tok"), \
                mock.patch.object(seo.site_check, "run_check", return_value={"checked": 1, "failed": 0}):
            line = seo.run(make_ctx(self.conn, agent="seo", dry_run=False), console=self.google({}))
        self.assertIn("Google has ", line)
        self.assertIn("pages in its index.", line)
        self.assertIn("Search Console not read in dry run", seo.run(make_ctx(self.conn, agent="seo", dry_run=True)))
