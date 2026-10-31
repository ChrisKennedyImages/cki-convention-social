"""eventcaliber.com: every page builds, carries no banned copy, posts the form to the Worker, and shows only postable photos."""
from __future__ import annotations

import io
import json
import os
import re

from PIL import Image

from convention_social import offer
from convention_social.core import config, db
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
        # Cloudflare Turnstile on the form (2026-10-24): the widget with the site key, shown only when a visitor has to tick
        # a box; Send waits for the token; the Worker's refusals have plain words and the closed form names the email
        self.assertEqual(build.TURNSTILE_SITE_KEY, "0x4AAAAAAFkmbrAUupO81Nil", "the widget made for eventcaliber.com and www on 2026-10-24")
        self.assertIn(f'<div class="full"><div class="cf-turnstile" data-sitekey="{build.TURNSTILE_SITE_KEY}" data-action="quote" '
                      'data-theme="dark" data-size="flexible" data-appearance="interaction-only" data-callback="checkPassed" '
                      'data-expired-callback="checkExpired" data-error-callback="checkFailed"></div>', book)
        self.assertLess(book.index('class="cf-turnstile"'), book.index('<button class="btn fill" type="submit">Send the request'),
                        "the box, when it shows, sits right above Send")
        self.assertIn('<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer onerror="checkFailed()"></script>', book)
        self.assertLess(book.index("function checkFailed()"), book.index('src="https://challenges.cloudflare.com'),
                        "the handlers exist before the script that calls them")
        self.assertIn('book.addEventListener("submit",ev=>{if(token)return;ev.preventDefault();waiting=true;', book)
        mail = f'<a href="mailto:{build.contact_email()}" class="c">{build.contact_email()}</a>'
        self.assertIn(f"closed:'The form is not taking requests right now. Please email us at {mail}.'", book)
        self.assertIn(f"say('Our spam check could not load in this browser. Please email us at {mail}.')", book)
        self.assertIn(f'<noscript><p class="mono g" style="margin-bottom:22px">This form needs JavaScript. Without it, email us at {mail}.</p></noscript>', book)
        self.assertIn('new ResizeObserver(([en])=>box.classList.toggle("shown",en.contentRect.height>0)).observe(box);', book)
        self.assertIn(".cf-turnstile.shown{margin-bottom:22px}", (out / "assets/site.css").read_text(),
                      "room above Send only while the box shows: a visitor who never sees it gets the form as it was")
        # the Worker refuses a token solved for another action or site: it and the form must name the same ones
        worker = (config.REPO_ROOT / "worker" / "index.js").read_text()
        self.assertIn(f'const TURNSTILE_ACTION = "{build.TURNSTILE_ACTION}";', worker)
        self.assertIn('const TURNSTILE_HOSTS = ["eventcaliber.com", "www.eventcaliber.com"];', worker)
        self.assertIn('if (!env.TURNSTILE_SECRET_KEY) return "closed";', worker, "no secret key: the form is closed, never open")
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
        size is capped at that width over 9.9, and every line stays whole and on one line at every width.
        2026-10-14: the phone block is now `max-width:760px` (the three sizes: phone to 760, iPad to 1100, computer
        above), so the slice moved; the cap itself is unchanged."""
        out = self.built()
        css = (out / "assets/site.css").read_text()
        phone = css[css.index("@media (max-width:760px)"):]
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

    def test_the_main_page_never_says_fan_conventions_and_delivery_leads_without_its_method(self):
        """Chris, 2026-10-12: "Get rid of 'fan conventions'... Don't put that on the main page". 2026-10-30: "Instant delivery
        needs to be a top priority for getting customers": the outcome and the choice lead the hero; the method never does,
        and the hour for selects stays out of the top ("Don't include the selects part in the top"). 2026-10-31: "a link at
        the top where the instant delivery also lives to the detailed page about it": right after the delivery sentence."""
        home = (self.built() / "index.html").read_text()
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", home, flags=re.S).lower()
        self.assertNotIn("fan convention", text)
        hero = home[home.index('<section class="hero">'):home.index("</section>")]
        for word in ("selfie", "badge", "scan"):
            self.assertNotIn(word, hero.lower(), word)
        self.assertIn("conventions, conferences, galas and award dinners for more than thirty years each", hero)
        self.assertIn("while the event is still on, and post them as it happens: all attendees, or your staff only, your choice", hero)
        self.assertNotIn("within the hour", hero)
        link = f'<a class="c" href="{offer.coverage_page("on_site_delivery")}">More about instant delivery &#8599;</a>'
        self.assertIn(link, hero, "the top links to the detailed delivery page")
        self.assertLess(hero.index("your staff only, your choice."), hero.index(link), "right after the delivery sentence")
        self.assertLess(hero.index(link), hero.index("for more than thirty years each"))

    def test_delivery_is_a_feature_with_no_name_and_no_steps_and_portraits_are_backstage(self):
        """Chris, 2026-10-12: "Don't say instant delivery by 'facematch' and don't give the steps ... it's a feature not the
        entire product"; and portraits are backstage for the speakers, lit on site with our own lights and gels."""
        out = self.built()
        for rel in ("index.html", "about/index.html", "book/index.html", "availability/index.html", "privacy/index.html"):
            text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", (out / rel).read_text(), flags=re.S).lower()
            for word in ("face match", "facematch", "selfie", "scan the code", "scan their badge", "three short fields", "add a selfie"):
                self.assertNotIn(word, text, (rel, word))
        home = (out / "index.html").read_text()
        self.assertIn("Instant delivery during the event", home)
        self.assertIn('<span class="">Instant delivery</span><span class="dot">', home, "the ticker says it the same way")
        self.assertNotIn("Delivered on site", home)
        # 2026-10-31: the choice, the posting and the staff are said in full on the delivery page; the home page says the
        # choice once, in the hero, and links there
        delivery_page = (out / "coverage/on_site_delivery/index.html").read_text()
        self.assertIn("You decide who gets them: all attendees, or your staff only.", delivery_page)
        self.assertIn("Selects within the hour when we know before the event which moments you want;", delivery_page)
        self.assertNotIn("You decide who gets them", home)
        self.assertNotIn("The photography is the work.", home, "2026-10-30: delivery is no longer played down")
        self.assertIn("<em>Backstage, for the speakers and the people the event is about.", home)
        self.assertIn("finished in the camera", home)
        self.assertNotIn("every attendee", home.lower(), "attendee portraits are a different product, not advertised")
        book = (out / "book/index.html").read_text()
        self.assertIn("<span>Instant delivery during the event</span>", book)
        self.assertIn("Whether photos go out during the event, and to whom", book)
        self.assertIn(".list a .t em{display:block", (out / "assets/site.css").read_text())

    def test_the_bottom_block_is_the_organizers_selects_within_the_hour(self):
        """Chris, 2026-10-31: "why instant delivery is still also on the bottom service on the main page ... The bottom one was
        suppose to be replaced with 1 hour selects": "the selects for the clients in 1 hour during the event". The block is the
        organizer's selects, within the hour, when the moments are known before the event; attendee delivery is in the hero
        and on its coverage page, never here."""
        home = (self.built() / "index.html").read_text()
        block = home[home.index('<section class="deliver">'):]
        block = block[:block.index("</section>")]
        self.assertIn('<div class="kick mono c">Selects during the event</div>', block)
        self.assertIn('<h2>Your selects, <span class="o">within</span> the hour.</h2>', block)
        self.assertIn("Tell us before the event which moments you want", block)
        self.assertIn("yours within the hour", block)
        self.assertIn("The finished set follows after the event.", block)
        words = re.sub(r"<[^>]+>", " ", block).lower()
        self.assertIsNone(re.search(r"\b(attendees?|posts?|posting|staff|speakers?|instant|sent)\b", words), words)
        self.assertIn('<span class="stamp mono">Selects</span>', block, "the stamp on the prints says what they are, not that they went out")

    def test_a_coverage_note_passes_the_same_gate_as_the_labels(self):
        """The Portraits row's note is public copy: a price or a claim in it stops the build like one in a label would."""
        bad = json.loads(json.dumps(offer.load()))
        bad["coverage"][0]["note"] = "From $500 a day."
        (self.root / "offer.json").write_text(json.dumps(bad))
        os.environ["OFFER_FILE"] = str(self.root / "offer.json")
        config.reset()
        with self.assertRaises(build.SiteCopyRefused):
            self.built()
        self.assertFalse((self.root / "dist" / "index.html").exists())

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
        # 2026-10-14: the menu is words, not numbers ("<b>05</b> About" is gone): About has a real place in it
        self.assertIn('<a href="/about/">About</a>', home[home.index('<nav class="mono" aria-label="Pages">'):home.index("</nav>")])
        self.assertNotIn("<b>05</b>", home)
        self.assertNotIn("Scan.</div>", home)
        about = (out / "about/index.html").read_text()
        for word in ("Chris and Nic Kennedy, brothers", "Corcoran", "Nic finished in 1999, Chris in 2002", "darkroom at home",
                     "our father taught and had graduated before us", "Who will be at your event", "within 24 hours"):
            self.assertIn(word, about, word)
        self.assertEqual(about.count("<figure style="), 2, "two of the work photos stand in until there are portraits (each with its shape, 2026-10-14)")
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

    def test_nothing_but_the_cursor_ring_follows_the_pointer(self):
        """Chris, 2026-10-14: "It just follows my mouse (that picture)". The coverage peek, a photo that trailed the
        cursor over the Coverage list on a desktop, is gone; the cursor ring and the hero's web are the only things
        that answer the pointer."""
        from convention_social.site import theme
        home = (self.built() / "index.html").read_text()
        self.assertNotIn('class="peek"', home)
        self.assertNotIn("data-img=", home)
        self.assertIn('class="list rv"', home, "the Coverage list itself stays")
        self.assertNotIn("peek", theme.JS)
        self.assertNotIn(".peek", theme.CSS)
        self.assertEqual(theme.JS.count("mousemove"), 2, "the cursor ring and the hero web, nothing else")

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
        """2026-10-14: the sitemap lists every public page in build.PAGES (the coverage index, nine coverage pages and
        Contact joined the five), and the business block carries a locality and region (a service-area business), still
        never a street."""
        out = self.built()
        robots = (out / "robots.txt").read_text()
        self.assertIn("Sitemap: https://eventcaliber.com/sitemap.xml", robots)
        self.assertNotIn("Disallow: /\n", robots)
        sitemap = (out / "sitemap.xml").read_text()
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        self.assertEqual(locs, ["https://eventcaliber.com" + p for p in build.PAGES])
        self.assertEqual(len(locs), 16)
        self.assertEqual(locs[:3], ["https://eventcaliber.com/", "https://eventcaliber.com/about/", "https://eventcaliber.com/coverage/"])
        self.assertIn("https://eventcaliber.com/coverage/backstage/", locs)
        self.assertIn("https://eventcaliber.com/contact/", locs)
        images = re.findall(r"<image:loc>([^<]+)</image:loc>", sitemap)
        self.assertEqual(len(images), 5)                          # hero, 3 coverage, 1 venue (no coverage page photos handed in)
        for loc in images:
            self.assertTrue((out / loc.replace("https://eventcaliber.com/", "")).exists(), loc)
        home = (out / "index.html").read_text()
        blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', home, flags=re.S)]
        self.assertTrue(blocks)
        self.assertEqual([b["@type"] for b in blocks], ["ProfessionalService"] + ["ImageObject"] * 5)
        self.assertEqual(blocks[0]["legalName"], "CKI, LLC")
        self.assertEqual(blocks[0]["address"], {"@type": "PostalAddress", "addressLocality": "Washington", "addressRegion": "DC", "addressCountry": "US"})
        self.assertNotIn("streetAddress", json.dumps(blocks[0]))
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
