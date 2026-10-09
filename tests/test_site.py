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
        self.assertIn("PREVIEW, not live", home)
        self.assertIn("noindex", home)

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
                      personal_details="[]", quality=5 - n, classified_at=now)
            if final:
                db.insert(conn, "final_checks", photo_id=pid, possible_minor=0, personal_details="[]", model="m", checked_at=now)
        fetched = []
        photos = build.pick_photos(conn, lambda r: fetched.append(r["drive_id"]) or im())
        self.assertEqual(sorted(fetched), ["d0", "d2"])            # d1 never passed the final check
        self.assertEqual((len(photos.hero), len(photos.venues)), (1, 1))
        conn.close()
