"""eventcaliber.com: every page builds, carries no banned copy, posts the form to the Worker, and shows only postable photos."""
from __future__ import annotations

import io
import json
import re

from PIL import Image

from convention_social import offer
from convention_social.core import db
from convention_social.site import build
from convention_social.render import meta
from convention_social.seo import site_check
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes


def im(seed=0):
    return Image.open(io.BytesIO(jpeg_bytes((80, 90 + seed * 20, 120), size=(2400, 1600), seed=seed)))


class Site(IsolatedCase):
    def built(self, preview=False, photos=None):
        photos = photos or build.SitePhotos(hero=[(im(), "a")], coverage=[(im(i), "c") for i in range(3)], venues=[(im(9), "v")])
        return build.build(None, photos, out=self.root / "dist", preview=preview)

    def test_pages_and_form(self):
        out = self.built()
        for rel in ("index.html", "book/index.html", "thanks/index.html", "availability/index.html", "privacy/index.html", "404.html",
                    "assets/site.css", "assets/mark.svg"):
            self.assertTrue((out / rel).exists(), rel)
        book = (out / "book/index.html").read_text()
        self.assertIn('action="/api/quote"', book)
        self.assertIn('name="website"', book)                      # the honeypot the Worker checks
        for key in offer.coverage_keys():
            self.assertIn(f'value="{key}"', book)
        home = (out / "index.html").read_text()
        self.assertIn("a brand of CKI, LLC", home)
        self.assertNotIn("PREVIEW", home)
        self.assertNotIn("noindex", home)
        self.assertIn("/api/availability", (out / "availability/index.html").read_text())

    def test_no_banned_copy_on_any_page(self):
        out = self.built()
        for page in out.rglob("*.html"):
            text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", page.read_text(), flags=re.S)
            self.assertNotRegex(text, r"[$£€]\s?\d|—|–|official photographer|trusted by", page.name)

    def test_preview_is_stamped_and_hidden_from_search(self):
        home = (self.built(preview=True) / "index.html").read_text()
        self.assertIn("Preview, not live", home)
        self.assertIn("noindex", home)

    def test_search_files_and_structured_data(self):
        out = self.built()
        robots = (out / "robots.txt").read_text()
        self.assertIn("Sitemap: https://eventcaliber.com/sitemap.xml", robots)
        self.assertNotIn("Disallow: /\n", robots)
        sitemap = (out / "sitemap.xml").read_text()
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        self.assertEqual(locs, ["https://eventcaliber.com/", "https://eventcaliber.com/book/",
                                "https://eventcaliber.com/availability/", "https://eventcaliber.com/privacy/"])
        images = re.findall(r"<image:loc>([^<]+)</image:loc>", sitemap)
        self.assertEqual(len(images), 5)                          # hero, 3 coverage, 1 venue
        for loc in images:
            self.assertTrue((out / loc.replace("https://eventcaliber.com/", "")).exists(), loc)
        home = (out / "index.html").read_text()
        blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', home, flags=re.S)]
        self.assertTrue(blocks)
        self.assertEqual([b["@type"] for b in blocks], ["ProfessionalService"] + ["ImageObject"] * 5)
        self.assertEqual(blocks[0]["legalName"], "CKI, LLC")
        self.assertNotIn("address", blocks[0])
        self.assertNotIn("ld+json", (out / "book/index.html").read_text())
        # the SEO agent's weekly check reads these same two files on the live site
        self.assertEqual(site_check.check_sitemap(200, sitemap)["problems"], [])
        self.assertEqual(site_check.check_robots(200, robots)["problems"], [])

    def test_preview_is_never_crawled(self):
        robots = (self.built(preview=True) / "robots.txt").read_text()
        self.assertEqual(robots, "User-agent: *\nDisallow: /\n")
        self.assertIn("blocks the whole site (Disallow: /)", site_check.check_robots(200, robots)["problems"])

    def test_photos_carry_no_metadata(self):
        out = self.built()
        jpgs = list((out / "assets").glob("*.jpg"))
        self.assertEqual(len(jpgs), 10)                          # 5 photos at 2 widths
        for p in jpgs:
            self.assertEqual(meta.is_clean(p), [])

    def test_only_postable_photos_are_picked(self):
        conn = db.connect()
        now = db.utcnow()
        for n, (subject, final) in enumerate((("event", True), ("event", False), ("architecture", True))):
            conn.execute("INSERT INTO photos (drive_id, name, width, height, clearance, first_seen_at, last_seen_at) "
                         "VALUES (?,?,?,?, 'cleared', ?, ?)", (f"d{n}", "x.jpg", 3000, 2000, now, now))
            pid = db.one(conn, "SELECT id FROM photos WHERE drive_id=?", (f"d{n}",))["id"]
            db.insert(conn, "classifications", photo_id=pid, method="ollama", subject=subject, possible_minor=0,
                      personal_details="[]", quality=5 - n, space="exterior", residential=0, empty_room=0, sharp=1, light=4, moment=4, classified_at=now)
            if final:
                db.insert(conn, "final_checks", photo_id=pid, possible_minor=0, personal_details="[]", model="m", checked_at=now)
        fetched = []
        photos = build.pick_photos(conn, lambda r: fetched.append(r["drive_id"]) or im())
        self.assertEqual(sorted(fetched), ["d0", "d2"])            # d1 never passed the final check
        self.assertEqual((len(photos.hero), len(photos.venues)), (1, 1))
        conn.close()
