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

    def test_the_hero_carries_the_magnetic_web(self):
        """Chris, 2026-10-11: "make the photo have the magnetic web effect": a canvas over the hero, drawn by the
        site's script, pulled by the pointer, still under reduced motion and asleep off screen."""
        out = self.built()
        home = (out / "index.html").read_text()
        self.assertIn('<canvas class="web" aria-hidden="true"></canvas>', home)
        self.assertEqual(home.index('class="img"'), home.index('class="img"'), "one hero")
        self.assertLess(home.index('<div class="img">'), home.index('<canvas class="web"'))
        js = (out / "assets/site.js").read_text()
        self.assertIn("document.querySelector('.hero canvas.web')", js)
        self.assertIn("if(web&&!reduce)", js)
        for word in ("mousemove", "touchmove", "IntersectionObserver(es=>{live=", "visibilitychange", "requestAnimationFrame(step)"):
            self.assertIn(word, js, word)
        css = (out / "assets/site.css").read_text()
        self.assertIn("filter:brightness(1.24) saturate(1.35)", css[css.index(".hero .img img{"):][:300],
                      "Chris, 2026-10-12: up the saturation, it was lost in the layer; up brightness too")
        self.assertIn(".hero canvas.web{position:absolute;inset:0", css)
        self.assertIn("pointer-events:none", css[css.index(".hero canvas.web{"):][:200])
        self.assertIn(".hero canvas.web{display:none}", css[css.index("prefers-reduced-motion"):])

    def test_the_headline_fits_a_phone_on_three_lines(self):
        """Chris, 2026-10-12: "Brothers is cut off on the website landing page". Each headline line is a block
        that clips (the slide-up animation), so a line wider than the hero's text box loses its end. In Michroma
        the longest line, EVERY ROOM., is 9.6 times the font size wide and BROTHERS, 8.08 (measured in Chromium
        with the real font); the hero's text box on a phone is the viewport less 100 pixels. So on phones the
        size is capped at that width over 9.9, and every line stays whole and on one line at every width."""
        out = self.built()
        css = (out / "assets/site.css").read_text()
        phone = css[css.index("@media (max-width:900px)"):]
        self.assertIn(".mega{font-size:min(clamp(30px,10.4vw,64px),calc((100vw - 100px) / 9.9))}", phone)
        for width in (320, 375, 390, 430):
            self.assertLessEqual(min(max(30, 0.104 * width), (width - 100) / 9.9) * 9.6, width - 100, width)

    def test_the_heros_shadows_are_dodged_a_tad(self):
        """Chris, 2026-10-12: "Up brightness and dodge shadows a tad"."""
        dark = Image.new("RGB", (8, 8), (20, 20, 20))
        self.assertEqual(build.dodge_shadows(dark).getpixel((0, 0)), (33, 33, 33))
        self.assertEqual(build.dodge_shadows(Image.new("RGB", (8, 8), (255, 255, 255))).getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(build.dodge_shadows(Image.new("RGB", (8, 8), (128, 128, 128))).getpixel((0, 0)), (132, 132, 132))
        hero = Image.new("RGB", (2400, 1600), (20, 20, 20))
        out = self.built(photos=build.SitePhotos(hero=[(hero, "a")]))
        with Image.open(out / "assets/hero-800.jpg") as saved:
            self.assertGreater(saved.getpixel((10, 10))[0], 28, "the saved hero carries the lift")
            self.assertLess(saved.getpixel((10, 10))[0], 42, "a tad, not a wash (Chris: way too much dodging)")

    def test_the_main_page_never_says_fan_conventions_and_keeps_delivery_out_of_the_hero(self):
        """Chris, 2026-10-12: "Get rid of 'fan conventions'... Don't put that on the main page"; instant delivery
        can be highlighted but never front and center."""
        home = (self.built() / "index.html").read_text()
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", home, flags=re.S).lower()
        self.assertNotIn("fan convention", text)
        hero = home[home.index('<section class="hero">'):home.index("</section>")]
        for word in ("selfie", "badge", "scan"):
            self.assertNotIn(word, hero.lower(), word)
        self.assertIn("conventions, conferences, galas and award dinners for more than thirty years each", hero)

    def test_the_site_is_inhabited_by_the_two_brothers(self):
        """Chris, 2026-10-12, after the research: the site is the two of them, in their voice, with the camera
        readouts gone, an About page, who will be at your event, and one reply promise everywhere."""
        out = self.built()
        home = (out / "index.html").read_text()
        hero = home[home.index('<section class="hero">'):home.index("</section>")]
        for gone in ('id="tc"', "ISO 3200", 'id="fr"', 'class="cross"', 'class="focus"', 'class="hud'):
            self.assertNotIn(gone, home, gone)
        self.assertIn("<em>Two</em>", hero)
        self.assertIn("<em>brothers,</em>", hero)
        self.assertIn("<em>every room<b>.</b></em>", hero)
        self.assertIn("one of us will write back within 24 hours", hero)
        self.assertIn('<div class="vf" aria-hidden="true"><i></i><i></i><i></i><i></i></div>', hero, "the corner marks stay")
        self.assertIn("Who will be at your event", home)
        self.assertIn("One of us is at every event.", home)
        self.assertIn("References available on request.", home)
        self.assertIn('href="/about/"', home)
        self.assertIn("<b>05</b> About", home)
        self.assertNotIn("Scan.</div>", home)
        about = (out / "about/index.html").read_text()
        for word in ("Chris and Nic Kennedy, brothers", "Corcoran", "Nic finished in 1999, Chris in 2002", "darkroom at home",
                     "our father taught and had graduated before us", "Who will be at your event", "within 24 hours"):
            self.assertIn(word, about, word)
        self.assertEqual(about.count("<figure>"), 2, "two of the work photos stand in until there are portraits")
        for rel in ("index.html", "about/index.html", "book/index.html"):
            page = (out / rel).read_text()
            self.assertIn("within 24 hours", page, rel)
            self.assertNotIn("political", page.lower(), rel)
        # Chris, 2026-10-12: "We are going to get rid of 'fan conventions'": nowhere on the site, the quote form included
        for rel in ("index.html", "about/index.html", "book/index.html", "availability/index.html", "privacy/index.html"):
            self.assertNotIn("fan convention", (out / rel).read_text().lower(), rel)
        book = (out / "book/index.html").read_text()
        self.assertIn("What moves the quote", book)
        self.assertNotIn('value="fan"', book)
        self.assertIn('<option value="business">Conference, convention or corporate event</option>', book)
        self.assertNotIn("headshot", home.lower(), "portraits and headshots are one thing (2026-10-12)")
        self.assertNotIn('value="headshots"', book)
        self.assertIn('value="portraits"', book)
        js = (out / "assets/site.js").read_text()
        self.assertIn("setTimeout(()=>{web.style.transition='opacity 1.6s ease';web.style.opacity='0'", js, "the web fades after six seconds")
        self.assertIn("live=!done&&es[0].isIntersecting", js)
        from convention_social.seo import site_check
        self.assertIn("/about/", site_check.HTML_PATHS)

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
        self.assertEqual(locs, ["https://eventcaliber.com/", "https://eventcaliber.com/about/", "https://eventcaliber.com/book/",
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
