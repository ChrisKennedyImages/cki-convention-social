"""Chris, 2026-10-12: "And yet no site map or Google search indexing". The sitemap was there; the telling was
not. The Google Search Console tag rides every page from the Keys page, the sitemap's lastmod dates are true,
the IndexNow key file is served and the engines are pinged after every live publish."""
from __future__ import annotations

import io
import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from PIL import Image

from convention_social import cli
from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.seo import indexnow, markup, site_check
from convention_social.site import build, deploy
from tests import test_site_deploy as deploy_tests          # a module, so its cases are not collected twice
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def im(seed=0):
    return Image.open(io.BytesIO(jpeg_bytes((80, 90 + seed * 20, 120), size=(2400, 1600), seed=seed)))


def photos(seed=0):
    return build.SitePhotos(hero=[(im(seed), "a")], coverage=[(im(i + seed), "c") for i in range(3)], venues=[(im(9), "v")])


class Sitemap(IsolatedCase):
    def test_lastmod_is_listed_only_for_a_page_with_a_true_date(self):
        xml = markup.sitemap_xml("https://eventcaliber.com", ["/", "/book/"], lastmod={"/": "2026-10-12", "/book/": ""})
        root = ET.fromstring(xml.encode())
        urls = root.findall(f"{NS}url")
        self.assertEqual(urls[0].find(f"{NS}lastmod").text, "2026-10-12")
        self.assertIsNone(urls[1].find(f"{NS}lastmod"))
        self.assertTrue(site_check.check_sitemap(200, xml)["ok"])

    def test_the_build_keeps_each_pages_date_until_its_content_changes(self):
        out = self.root / "dist"
        with mock.patch("convention_social.site.build.datetime") as dt:
            dt.now.return_value.date.return_value.isoformat.return_value = "2026-10-01"
            build.build(None, photos(), out=out)
        record = json.loads((config.get_config().data_root / "site" / build.LASTMOD_FILE).read_text())
        self.assertEqual(sorted(record), sorted(build.PAGES))
        self.assertEqual({r["date"] for r in record.values()}, {"2026-10-01"})
        dates = {u.find(f"{NS}loc").text: u.find(f"{NS}lastmod").text for u in ET.fromstring((out / "sitemap.xml").read_bytes()).findall(f"{NS}url")}
        self.assertEqual(dates["https://eventcaliber.com/"], "2026-10-01")
        self.assertEqual(len(dates), len(build.PAGES))

        with mock.patch("convention_social.site.build.datetime") as dt:
            dt.now.return_value.date.return_value.isoformat.return_value = "2026-10-12"
            build.build(None, photos(), out=out)                      # nothing changed: every date stays
        dates = {u.find(f"{NS}loc").text: u.find(f"{NS}lastmod").text for u in ET.fromstring((out / "sitemap.xml").read_bytes()).findall(f"{NS}url")}
        self.assertEqual(set(dates.values()), {"2026-10-01"}, "a rebuild with the same content moves no date")

        with mock.patch("convention_social.site.build.datetime") as dt:
            dt.now.return_value.date.return_value.isoformat.return_value = "2026-10-12"
            build.build(None, photos(seed=3), out=out)                # a new hero: the home page changed, the rest did not
        dates = {u.find(f"{NS}loc").text: u.find(f"{NS}lastmod").text for u in ET.fromstring((out / "sitemap.xml").read_bytes()).findall(f"{NS}url")}
        self.assertEqual(dates["https://eventcaliber.com/"], "2026-10-12")
        self.assertEqual(dates["https://eventcaliber.com/privacy/"], "2026-10-01")

    def test_a_preview_reads_the_record_and_never_writes_it(self):
        out = self.root / "dist"
        path = config.get_config().data_root / "site" / build.LASTMOD_FILE
        build.build(None, photos(), out=out, preview=True)
        self.assertFalse(path.exists(), "a preview is side-effect free")
        build.build(None, photos(), out=out)
        before = path.read_text()
        build.build(None, photos(seed=5), out=out, preview=True)
        self.assertEqual(path.read_text(), before)


class GoogleTag(IsolatedCase):
    def test_the_tag_from_the_keys_page_rides_every_live_page_never_a_preview(self):
        out = self.root / "dist"
        build.build(None, photos(), out=out)
        self.assertNotIn("google-site-verification", (out / "index.html").read_text())
        os.environ["GOOGLE_SITE_VERIFICATION"] = '<meta name="google-site-verification" content="AbC-123_xyzXYZ789" />'
        config.reset()
        self.assertEqual(build.verification_value(), "AbC-123_xyzXYZ789", "the whole tag may be pasted; its content is kept")
        build.build(None, photos(), out=out)
        for rel in ("index.html", "about/index.html", "book/index.html", "availability/index.html", "privacy/index.html"):
            self.assertIn('<meta name="google-site-verification" content="AbC-123_xyzXYZ789">', (out / rel).read_text(), rel)
        self.assertTrue(site_check.check_html(200, (out / "index.html").read_text())["ok"])
        build.build(None, photos(), out=out, preview=True)
        self.assertNotIn("google-site-verification", (out / "index.html").read_text(), "a preview is never verified")
        os.environ["GOOGLE_SITE_VERIFICATION"] = 'x"><script>alert(1)</script>'
        config.reset()
        self.assertEqual(build.verification_value(), "", "only a plain token can reach the page")
        os.environ["GOOGLE_SITE_VERIFICATION"] = "short"
        config.reset()
        self.assertEqual(build.verification_value(), "")


class IndexNow(IsolatedCase):
    def test_the_key_is_made_once_kept_in_env_and_served_from_the_root(self):
        self.assertEqual(indexnow.key(), "")
        made = indexnow.ensure_key()
        self.assertTrue(indexnow.valid(made))
        self.assertEqual(indexnow.key(), made)
        self.assertEqual(indexnow.ensure_key(), made, "made once")
        self.assertIn(f"INDEXNOW_KEY={made}", Path(os.environ["CCS_ENV_FILE"]).read_text())
        out = self.root / "dist"
        build.build(None, photos(), out=out)
        self.assertEqual((out / f"{made}.txt").read_text(), made)
        build.build(None, photos(), out=out, preview=True)
        self.assertFalse((out / f"{made}.txt").exists(), "a preview proves nothing")
        self.assertFalse(indexnow.valid("too!short"))
        self.assertFalse(indexnow.valid("a" * 129))

    def test_the_ping_names_every_page_and_the_key_file_and_reads_the_answer(self):
        seen = []

        def post(url, body):
            seen.append((url, body))
            return 202, ""
        told, note = indexnow.ping("https://eventcaliber.com", build.PAGES, value="k" * 32, post=post)
        self.assertTrue(told)
        self.assertIn("IndexNow told about 5 page(s)", note)
        url, body = seen[0]
        self.assertEqual(url, "https://api.indexnow.org/indexnow")
        self.assertEqual(body["host"], "eventcaliber.com")
        self.assertEqual(body["key"], "k" * 32)
        self.assertEqual(body["keyLocation"], f"https://eventcaliber.com/{'k' * 32}.txt")
        self.assertEqual(body["urlList"][:2], ["https://eventcaliber.com/", "https://eventcaliber.com/about/"])
        self.assertEqual(len(body["urlList"]), 5)
        told, note = indexnow.ping("https://eventcaliber.com", build.PAGES, value="k" * 32, post=lambda u, b: (422, "key not found"))
        self.assertEqual((told, note), (False, "IndexNow answered 422: key not found"))

        def down(u, b):
            raise ConnectionError("no route")
        self.assertEqual(indexnow.ping("https://eventcaliber.com", build.PAGES, value="k" * 32, post=down), (False, "IndexNow could not be reached (ConnectionError)"))
        self.assertEqual(indexnow.ping("https://eventcaliber.com", build.PAGES, value="", post=post)[0], False)

    def test_the_weekly_check_reads_the_key_file_from_outside(self):
        os.environ["INDEXNOW_KEY"] = "k" * 32
        config.reset()
        pages = {f"https://eventcaliber.com{p}": (200, "<html><head><title>t</title><meta name=\"description\" content=\"d\"></head><body><h1>h</h1></body></html>")
                 for p in site_check.HTML_PATHS}
        pages["https://eventcaliber.com/sitemap.xml"] = (200, markup.sitemap_xml("https://eventcaliber.com", build.PAGES))
        pages["https://eventcaliber.com/robots.txt"] = (200, markup.robots_txt("https://eventcaliber.com"))
        pages[f"https://eventcaliber.com/{'k' * 32}.txt"] = (200, "k" * 32 + "\n")
        results = site_check.check_all(transport=lambda u: pages[u])
        self.assertEqual([r["path"] for r in results][-1], f"/{'k' * 32}.txt")
        self.assertTrue(all(r["ok"] for r in results), [r for r in results if not r["ok"]])
        pages[f"https://eventcaliber.com/{'k' * 32}.txt"] = (200, "something else")
        bad = site_check.check_all(transport=lambda u: pages[u])[-1]
        self.assertEqual((bad["ok"], bad["problems"]), (False, ["does not carry the IndexNow key"]))
        pages[f"https://eventcaliber.com/{'k' * 32}.txt"] = (404, "")
        self.assertEqual(site_check.check_all(transport=lambda u: pages[u])[-1]["problems"], ["answered 404"])
        os.environ.pop("INDEXNOW_KEY")
        config.reset()
        self.assertEqual(len(site_check.check_all(transport=lambda u: pages[u])), len(site_check.PATHS), "no key, no key file to read")


class AfterAPublish(deploy_tests.Run):
    """The engines are told only once the site is live; a ping that fails never fails the publish."""

    def test_a_live_publish_tells_the_engines_and_the_card_says_so(self):
        settings.set(self.conn, deploy.DEPLOYED_KEY, "")
        calls = []
        with mock.patch("convention_social.seo.indexnow._post", side_effect=lambda u, b: (calls.append(b), (200, ""))[1]):
            self.assertEqual(self.go(), 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["host"], "eventcaliber.com")
        self.assertEqual(calls[0]["key"], indexnow.key(), "the key the first publish made")
        self.assertTrue(indexnow.valid(indexnow.key()))
        st = deploy.read_status()
        self.assertEqual(st["state"], "done")
        self.assertTrue(st["engines_told"])
        self.assertIn("IndexNow told about 5 page(s)", st["engines"])
        self.assertIn(st["engines"], self.said)

    def test_a_failed_ping_is_a_note_not_a_failed_publish(self):
        with mock.patch("convention_social.seo.indexnow._post", side_effect=lambda u, b: (429, "slow down")):
            self.assertEqual(self.go(), 0)
        st = deploy.read_status()
        self.assertEqual((st["state"], st["engines_told"]), ("done", False))
        self.assertEqual(st["engines"], "IndexNow answered 429: slow down")
        self.assertEqual(settings.get(self.conn, deploy.DEPLOYED_KEY), self.head(), "live all the same")

    def test_no_ping_when_the_site_did_not_go_live(self):
        with mock.patch("convention_social.seo.indexnow._post") as post:
            self.assertEqual(self.go(checker=(False, ["FAIL  https://eventcaliber.com/  (404)"])), 1)
            self.assertEqual(self.go(deployer=__import__("subprocess").CompletedProcess(["x"], 1, "", "boom")), 1)
        self.assertEqual(post.call_count, 0)


class OnTheDashboard(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_keys_page_takes_the_tag_and_shows_the_key(self):
        page = self.client.get("/keys").text
        self.assertIn("<strong>Search engines</strong>", page)
        self.assertIn('name="GOOGLE_SITE_VERIFICATION"', page)
        self.assertIn('name="INDEXNOW_KEY"', page)
        self.assertIn("submit sitemap.xml there once", page)
        r = self.client.post("/keys", data={"GOOGLE_SITE_VERIFICATION": '<meta name="google-site-verification" content="AbC-123_xyzXYZ789" />'},
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(build.verification_value(), "AbC-123_xyzXYZ789")

    def test_the_website_card_says_what_the_engines_know(self):
        with mock.patch("convention_social.site.deploy.ready", return_value=(True, "ready")):
            page = self.client.get("/library?view=approved").text
            self.assertIn("Google Search Console tag missing", page)
            self.assertIn("The IndexNow key is made on the first publish.", page)
            os.environ["GOOGLE_SITE_VERIFICATION"] = "AbC-123_xyzXYZ789"
            os.environ["INDEXNOW_KEY"] = "k" * 32
            config.reset()
            page = self.client.get("/library?view=approved").text
            self.assertIn("Google Search Console tag on every page.", page)
            self.assertIn("Bing and the other IndexNow engines are told after every publish.", page)
            deploy.write_status("done", "live on abc1234", engines="IndexNow told about 5 page(s) (Bing, Yandex and the others; Google reads the sitemap)", engines_told=True)
            page = self.client.get("/library?view=approved").text
            self.assertIn("Last publish: IndexNow told about 5 page(s)", page)
