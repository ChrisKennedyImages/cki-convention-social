"""The website for three sizes (Chris, 2026-10-14: "we must ALWAYS treat UX UI optimization for phone ipad and
computer, no shortcuts!!!"): the phone to 760px with the bar at the bottom, the iPad from 761 to 1100 with the menu
in words, the computer above 1100 with the phone number in the bar. About has a place in the menu, the hero's words
sit under the photo, the work strip rolls on its own, there is one page per coverage item with the place in its title,
a Contact page of email and phone only, a footer with everything in it, and the Keys page fields the site shows.

Every pin here was run against the code before this change (the files of this branch replaced by main's in a private
copy) and seen to fail, and the ones that guard a line of code were run again with that line changed and seen to fail.
"""
from __future__ import annotations

import html
import io
import json
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from convention_social import offer
from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.seo import site_check
from convention_social.site import build, deploy, theme
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

REPO = Path(__file__).resolve().parents[1]
BASE = "https://eventcaliber.com"
JSONLD = r'<script type="application/ld\+json">(.*?)</script>'
NAV = r'<nav class="mono" aria-label="Pages">(.*?)</nav>'
TABS = r'<nav class="tabbar" aria-label="Pages">(.*?)</nav>'


def im(seed=0):
    return Image.open(io.BytesIO(jpeg_bytes((80, 90 + seed * 5, 120), size=(2400, 1600), seed=seed)))


def photos(*, frames=4, pages=True):
    """A hero, `frames` work photos each linking to its coverage page, one venue, and the coverage pages' own photos
    (four on the first, third, fifth... page and two on the others)."""
    p = build.SitePhotos(hero=[(im(), "a")], coverage=[(im(i + 1) , f"c{i}") for i in range(frames)], venues=[(im(9), "v")])
    keys = offer.coverage_keys()
    p.links = [f"/coverage/{k}/" for k in keys[:frames]]
    if pages:
        p.pages = {k: [(im(20 + 10 * i + j), f"{k.replace('_', ' ')} photo {j}") for j in range(2 if i % 2 else 4)] for i, k in enumerate(keys)}
    return p


def blocks_of(page: str) -> list[dict]:
    return [json.loads(b) for b in re.findall(JSONLD, page, flags=re.S)]


class SizesCase(IsolatedCase):
    def built(self, photos_=None, **kw):
        return build.build(None, photos() if photos_ is None else photos_, out=self.root / "dist", **kw)

    def page(self, out, rel):
        return (out / rel).read_text()


class Breakpoints(SizesCase):
    def test_three_sizes_and_the_bar_only_on_the_phone(self):
        """Phone to 760px, iPad 761 to 1100, computer above. The bar at the bottom exists only on the phone: hidden
        outside the phone block, fixed at the bottom inside it, clear of the iPhone's home indicator, with the page
        padded so nothing ends under it. Touch targets 44px or more; the pointer ring only for a fine pointer."""
        css = theme.CSS
        ipad_at, phone_at = css.index("@media (min-width:761px) and (max-width:1100px)"), css.index("@media (max-width:760px)")
        self.assertLess(ipad_at, phone_at)
        base, ipad, phone = css[:ipad_at], css[ipad_at:phone_at], css[phone_at:css.index("@media (prefers-reduced-motion:reduce)")]
        self.assertIn(".tabbar{display:none}", base)
        self.assertNotIn("tabbar", ipad)
        self.assertIn(".tabbar{position:fixed;left:0;right:0;bottom:0;z-index:55;display:flex;", phone)
        self.assertIn("padding:8px 6px calc(8px + env(safe-area-inset-bottom))", phone)
        self.assertIn("body{padding-bottom:calc(74px + env(safe-area-inset-bottom))}", phone)
        self.assertIn(".preview{bottom:calc(90px + env(safe-area-inset-bottom))}", phone, "the preview stamp sits above the bar")
        self.assertIn("min-height:48px", phone[phone.index(".tabbar a{"):][:400])
        self.assertIn(".top nav{display:none}", phone)
        self.assertIn(".top .tel{margin-left:auto}", phone)
        self.assertIn(".top .btn .long{display:none}", phone, "the quote button says QUOTE on a phone")
        self.assertIn(".top .tel{display:none}", ipad, "the iPad keeps the number for the footer and the Contact page")
        self.assertNotIn(".top nav{display:none}", ipad)
        self.assertIn(".top nav a{color:var(--g5);min-height:44px", base)
        self.assertIn(".top .tel{color:var(--g5);white-space:nowrap;min-height:44px", base)
        self.assertIn(".reel .arrows button{width:44px;height:44px", base)
        self.assertIn("@media (pointer:fine){.cursor{display:block}", base)
        self.assertNotIn(".cursor{display:block}", phone + ipad)
        self.assertIn('content="width=device-width,initial-scale=1,viewport-fit=cover"', self.page(self.built(), "index.html"))

    def test_the_headline_ends_above_the_fold_at_the_four_sizes(self):
        """The words under the photo must still be on the first screen (the hero photo's height, the band's padding,
        the kicker and three lines of the headline, read from the CSS), at an iPhone 390x844 (less the bar), an iPad
        820x1180 and 1180x820, and a computer 1440x900."""
        css = theme.CSS
        phone = css[css.index("@media (max-width:760px)"):]
        ipad = css[css.index("@media (min-width:761px) and (max-width:1100px)"):css.index("@media (max-width:760px)")]
        self.assertIn(".hero .photo{position:relative;height:56svh;min-height:400px;max-height:820px", css)
        self.assertIn(".mega{font:400 clamp(40px,min(7vw,9.5vh),124px)/.92 var(--display)", css)
        self.assertIn(".hero .photo{height:54svh;min-height:380px}.mega{font-size:clamp(36px,7.4vw,84px)}", ipad)
        self.assertIn(".hero .photo{height:50svh;min-height:300px}.hero .copy{padding:28px var(--pad) 44px}", phone)
        self.assertIn(".mega{font-size:min(clamp(30px,10.4vw,64px),calc((100vw - 100px) / 9.9))}", phone)
        kicker = 17 + 28                                           # the kicker line and its margin
        for w, h, room in ((390, 844, 844 - 74), (820, 1180, 1180), (1180, 820, 820), (1440, 900, 900)):
            if w <= 760:
                photo, pad, mega = max(300, 0.50 * h), 28, min(min(max(30, 0.104 * w), 64), (w - 100) / 9.9)
            elif w <= 1100:
                photo, pad, mega = max(380, 0.54 * h), min(max(34, 0.05 * w), 64), min(max(36, 0.074 * w), 84)
            else:
                photo, pad, mega = min(820, max(400, 0.56 * h)), min(max(34, 0.05 * w), 64), min(max(40, min(0.07 * w, 0.095 * h)), 124)
            bottom = photo + pad + kicker + 3 * mega * 0.92
            self.assertLessEqual(bottom, room, (w, h, bottom))


class Menu(SizesCase):
    def test_words_with_the_page_you_are_on_marked_on_every_page(self):
        """About has a real place in the navigation (Chris, 2026-10-14). The menu is words, the page you are on
        carries aria-current, the bar on the phone has Work, About, Contact and Quote in that order and marks the
        page too; the Coverage word is current on every coverage page."""
        out = self.built()
        for rel, word, tab in (("index.html", "/#work", "/#work"), ("coverage/index.html", "/coverage/", None),
                               ("coverage/backstage/index.html", "/coverage/", None), ("about/index.html", "/about/", "/about/"),
                               ("availability/index.html", "/availability/", None), ("contact/index.html", "/contact/", "/contact/"),
                               ("book/index.html", None, "/book/"), ("privacy/index.html", None, None), ("thanks/index.html", None, None)):
            page = self.page(out, rel)
            nav = re.search(NAV, page, flags=re.S).group(1)
            self.assertEqual(re.findall(r">([A-Za-z ]+)</a>", nav), ["Work", "Coverage", "About", "Availability", "Contact"], rel)
            self.assertEqual(re.findall(r'<a href="([^"]+)" aria-current="page">', nav), [word] if word else [], rel)
            self.assertNotRegex(nav, r"<b>\d\d</b>", "no numbering")
            tabs = re.search(TABS, page, flags=re.S).group(1)
            self.assertEqual(re.findall(r"<span>([A-Za-z]+)</span>", tabs), ["Work", "About", "Contact", "Quote"], rel)
            self.assertEqual(tabs.count("<svg"), 4, "an icon on every tab")
            self.assertEqual(re.findall(r'<a href="([^"]+)" class="[a-z ]+" aria-current="page">', tabs), [tab] if tab else [], rel)
            self.assertIn('<a href="/book/" class="quote q"', tabs)
            self.assertLess(page.index("</main>"), page.index('<nav class="tabbar"'), "the bar comes after the content, for readers")
        self.assertIn('<a href="/#work" aria-current="page">Work</a><a href="/coverage/">Coverage</a><a href="/about/">About</a>'
                      '<a href="/availability/">Availability</a><a href="/contact/">Contact</a>', self.page(out, "index.html"))

    def test_without_photos_work_leaves_the_menu_and_goes_to_the_coverage_pages_elsewhere(self):
        """A site built before any photo is cleared has no strip, so the menu has no Work word (a dead link otherwise);
        the footer's Work and the bar's Work open the coverage pages instead."""
        out = self.built(build.SitePhotos())
        for rel in ("index.html", "coverage/index.html", "about/index.html"):
            page = self.page(out, rel)
            nav = re.search(NAV, page, flags=re.S).group(1)
            self.assertEqual(re.findall(r">([A-Za-z ]+)</a>", nav), ["Coverage", "About", "Availability", "Contact"], rel)
            self.assertNotIn("#work", page, rel)
            self.assertIn('<li><a href="/coverage/">Work</a></li>', page, rel)
            self.assertIn('<a href="/coverage/" class="work"', page, rel)
        tabs = re.search(TABS, self.page(out, "coverage/stage/index.html"), flags=re.S).group(1)
        self.assertIn('<a href="/coverage/" class="work" aria-current="page">', tabs)
        self.assertEqual(theme._current("/#work", "/about/"), "", "a section link is never current off the home page")
        self.assertEqual(theme._current("/coverage/", "/coverage/stage/"), ' aria-current="page"')
        self.assertEqual(theme._current("/about/", "/about/"), ' aria-current="page"')
        self.assertEqual(theme._current("/about/", "/"), "")


class Hero(SizesCase):
    def test_the_words_are_under_the_photo_not_on_it(self):
        """Chris, 2026-10-14: the words over the hero photo were unreadable. The photo block holds the picture, the web
        canvas and the corner marks and no words; the band under it holds the kicker, the headline, the first
        sentence, the lede and the quote button. The brightness and saturation of 2026-10-12 stay on the photo."""
        out = self.built()
        home = self.page(out, "index.html")
        hero = home[home.index('<section class="hero">'):home.index("</section>")]
        photo = hero[hero.index('<div class="photo">'):hero.index('<div class="copy">')]
        self.assertEqual(re.sub(r"<[^>]+>", "", photo).strip(), "", "no words on the picture")
        self.assertIn('<canvas class="web" aria-hidden="true"></canvas>', photo)
        self.assertIn('<div class="vf" aria-hidden="true"><i></i><i></i><i></i><i></i></div>', photo)
        self.assertIn('src="/assets/hero-1600.jpg"', photo)
        self.assertIn('loading="eager" fetchpriority="high"', photo)
        copy = hero[hero.index('<div class="copy">'):]
        self.assertIn('<div class="kick mono c">Event and convention photography, Washington, DC and nationwide</div>', copy)
        self.assertIn('<h1 class="mega"><span><em>Two</em></span><span class="o"><em>brothers,</em></span><span><em>every room<b>.</b></em></span></h1>', copy)
        self.assertIn('<p class="first">Event Caliber photographs conventions, conferences, galas and award dinners in Washington, DC and across the country.</p>', copy)
        self.assertIn('<p class="lede">', copy)
        self.assertIn('<a class="btn fill" href="/book/">Request a quote', copy)
        self.assertEqual(home.count("<h1"), 1)
        css = theme.CSS
        self.assertIn(".hero .copy{position:relative;z-index:3;padding:clamp(34px,5vw,64px) var(--pad) clamp(44px,6vw,80px);background:var(--k)}", css)
        self.assertIn(".hero{position:relative;padding:0}", css, "no section padding over the photo: 160px of it pushed the headline below the fold")
        self.assertNotIn(".hero .copy{position:absolute", css)
        self.assertIn("filter:brightness(1.24) saturate(1.35)", css[css.index(".hero .img img{"):][:300])
        self.assertIn(".hero .photo:after{content:\"\";position:absolute;inset:0;background:linear-gradient(", css)
        self.assertIn('<link rel="preload" as="image" imagesrcset="/assets/hero-800.jpg 800w, /assets/hero-1600.jpg 1600w" imagesizes="100vw">', home)
        self.assertNotIn('rel="preload"', self.page(out, "about/index.html"), "only the page that shows the hero preloads it")
        self.assertNotIn('rel="preload"', self.page(self.built(build.SitePhotos()), "index.html"), "no hero, nothing to preload")


class Strip(SizesCase):
    def test_rolls_on_its_own_pauses_under_a_hand_and_never_moves_with_the_page(self):
        """Chris, 2026-10-14: the gallery said Scroll and moved sideways when you scrolled down, and he asked for it to
        roll on its own at a slow pace. The strip is a native sideways scroller the script nudges 24px a second; it
        pauses under the pointer, a finger or keyboard focus and while the tab is hidden, stays still under reduced
        motion, moves one frame per arrow, and nothing in it reads the page's scroll or sets a transform."""
        js = theme.JS
        roll = js[js.index("const roll=document.querySelector('.reel .track')"):js.index("// parallax")]
        self.assertIn("const SPEED=24", roll)
        self.assertIn("pos=roll.scrollLeft;", roll)
        self.assertIn("pos+=SPEED*dt/1000;", roll, "a float of its own: scrollLeft rounds to whole pixels and a fraction added every frame adds nothing")
        self.assertIn("roll.scrollLeft=pos}", roll)
        self.assertIn("if(Math.abs(roll.scrollLeft-pos)>1)pos=roll.scrollLeft;", roll, "a swipe or an arrow moved it: the roll goes on from there")
        self.assertIn("if(pos>=period())pos-=period();", roll, "the doubled strip loops without a jump")
        self.assertIn("return f.length>1?f[f.length/2].offsetLeft-f[0].offsetLeft:0", roll, "one period: the first frame to its copy")
        for word in ("transform", "scrollY", "addEventListener('scroll'"):
            self.assertNotIn(word, roll, word)
        for ev, flag in (("pointerenter", "over=true"), ("touchstart", "touch=true"), ("focusin", "focus=true")):
            self.assertIn(f"roll.addEventListener('{ev}',()=>{{{flag}}}", roll, ev)
        for ev, flag in (("pointerleave", "over=false"), ("focusout", "focus=false")):
            self.assertIn(f"roll.addEventListener('{ev}',()=>{{{flag}}}", roll, ev)
        self.assertIn("['touchend','touchcancel'].forEach(ev=>roll.addEventListener(ev,()=>{touch=false;hold=performance.now()+1200}", roll,
                      "a finger lifted: the swipe's own glide finishes before the roll goes on")
        self.assertIn("if(!over&&!touch&&!focus&&!document.hidden&&t>hold&&period()>0){", roll)
        self.assertIn("if(!reduce&&!fits)raf=requestAnimationFrame(step)", roll)
        self.assertIn("hold=performance.now()+900;roll.scrollBy({left:(b.dataset.dir==='prev'?-1:1)*width(),behavior:'smooth'})", roll,
                      "an arrow's smooth move is not cancelled by the roll setting scrollLeft")
        self.assertNotIn("track.style.transform", js, "the old scroll-driven reel is gone")
        self.assertNotIn("getElementById('tc')", js, "the dead timecode block is gone")
        css = theme.CSS
        self.assertIn(".reel .track{display:flex;gap:18px;padding:0 var(--pad);overflow-x:auto;overscroll-behavior-x:contain;scrollbar-width:none;align-items:flex-end}", css)
        self.assertNotIn(".reel .pin", css)
        self.assertNotIn("will-change:transform", css[css.index("/* work"):css.index("/* delivery */")])
        home = self.page(self.built(), "index.html")
        strip = home[home.index('<section id="work" class="reel">'):]
        strip = strip[:strip.index("</section>")]
        self.assertIn('<span class="hint mono">Rolls on its own. Swipe, or use the arrows.</span>', strip)
        self.assertNotIn("Scroll", strip)
        self.assertIn('<button type="button" data-dir="prev" aria-label="Previous photos">', strip)
        self.assertIn('<button type="button" data-dir="next" aria-label="Next photos">', strip)
        self.assertEqual(strip.count('<div class="frame">'), 4)
        self.assertEqual(strip.count('<div class="frame" aria-hidden="true"><a tabindex="-1" href="/coverage/'), 4, "the copies are out of the reader's and the keyboard's way")
        self.assertEqual(re.findall(r'<div class="frame"><a href="([^"]+)">', strip),
                         ["/coverage/backstage/", "/coverage/green_room/", "/coverage/breakouts/", "/coverage/stage/"], "each frame opens its coverage page")
        self.assertNotIn('data-speed', strip, "no parallax on the frames")


class Gallery(SizesCase):
    """Chris, 2026-10-14, on the live site: "the website gallery has duplicate images and lets expand the gallery to more
    images and a variety". The six live frames were six different pictures (no two alike by bytes or by perceptual
    hash); what read as duplicates were the loop's copies coming round after only six frames, and four of the six were
    portraits. Now twelve frames, drawn across the rooms and the events, and the copies only when the photos do not
    fit the screen."""

    def test_twelve_frames_across_the_rooms_and_the_events_never_the_same_photo_twice(self):
        self.assertEqual(build.COVERAGE_ROWS, 12)
        pool = []                                            # the pool's order is the rotation's: least recently used first
        for pid, shot, event in ((1, "portrait", "E1"), (2, "portrait", "E1"), (3, "portrait", "E2"), (4, "stage", "E1"),
                                 (5, "backstage", "E2"), (6, "reception", "E3"), (7, "breakout", "E1"), (8, "portrait", "E3"),
                                 (9, "stage", "E2"), (10, "candid", "E1")):
            pool.append({"id": pid, "shot_type": shot, "convention_name": event})
        grid = [r["id"] for r in build.pick_grid(pool)]
        self.assertEqual(grid, [1, 6, 5, 4, 7, 10, 3, 9, 2, 8],
                         "one of each room first (and across events within the round), then the rooms again, the least recently used first within a room")
        self.assertEqual(len(set(grid)), len(grid), "never the same photo twice")
        self.assertEqual(len({r["shot_type"] for r in build.pick_grid(pool)[:6]}), 6, "the first six frames are six rooms")
        many = [{"id": i, "shot_type": "portrait", "convention_name": "E1"} for i in range(1, 30)]
        self.assertEqual([r["id"] for r in build.pick_grid(many)], list(range(1, 13)), "one room only: the twelve least recently used of it")
        self.assertEqual(build.pick_grid([]), [])

    def test_the_same_picture_under_two_ids_is_shown_once_and_sits_out_under_both(self):
        """Chris, 2026-10-14, on the live strip: "same picked twice". The library holds the same file under several ids
        (the same photo in two Drive folders, a copy in a shared gallery: 1,431 md5 groups that day), each with its own
        classification, so an id check passed and the picture came twice. One row now stands for each md5 group, the
        home page and the coverage pages show it once, its use under any id counts for the whole group, and Chris's
        own hero pick on a twin is still his pick."""
        from tests.test_wedding import event_photo
        from convention_social.library import report
        conn = db.connect()
        self.addCleanup(conn.close)
        ids = [event_photo(conn, f"p{i:02d}", kind="business", final="business", quality=5) for i in range(30)]
        twins = {ids[2]: ids[9], ids[4]: ids[11], ids[5]: ids[13]}                    # three pictures, each under two ids: 27 pictures
        for i, pid in enumerate(ids):
            conn.execute("UPDATE photos SET md5=? WHERE id=?", (f"md5-{i:02d}", pid))
        for a, b in twins.items():
            conn.execute("UPDATE photos SET md5=(SELECT md5 FROM photos WHERE id=?) WHERE id=?", (a, b))
        conn.execute("UPDATE photos SET md5=NULL WHERE id IN (?, ?)", (ids[28], ids[29]))   # two phone photos, no md5: their own
        fetch = lambda r: Image.new("RGB", (int(r["width"]), int(r["height"])), (80, 60, 120))
        got = build.pick_photos(conn, fetch)
        md5s = {r["id"]: r["md5"] for r in db.rows(conn, "SELECT id, md5 FROM photos")}
        pictures = [md5s[i] or f"id:{i}" for i in got.grid_ids]
        self.assertEqual(len(got.grid_ids), 13, "the hero and twelve frames, from thirteen distinct pictures")
        self.assertEqual(len(set(pictures)), len(pictures), "no picture twice on the home page")
        self.assertEqual(len(set(got.grid_ids)), len(got.grid_ids))
        self.assertEqual(sorted(got.ids), sorted(set(got.ids)))
        shown_twice = [i for i in got.ids if i in twins.values()]
        self.assertEqual(shown_twice, [], "a twin never stands beside its picture: the first id of the group stands for both")
        self.assertIn(ids[28], got.ids); self.assertIn(ids[29], got.ids)
        build.build(conn, got, out=self.root / "dist")
        second = build.pick_photos(conn, fetch)
        self.assertEqual(set(second.grid_ids) & set(got.grid_ids), set(), "the next build shows other pictures")
        self.assertEqual([i for i in second.grid_ids if i in twins.values()], [], "and not a shown picture under its other id")
        # the rotation counts a use under any id of the group
        kept, shared = build.one_per_picture([{"id": 1, "md5": "x"}, {"id": 2, "md5": "x"}, {"id": 3, "md5": None}], {2: "2026-10-10T00:00:00"})
        self.assertEqual([r["id"] for r in kept], [1, 3])
        self.assertEqual(shared, {1: "2026-10-10T00:00:00", 2: "2026-10-10T00:00:00"})
        kept, _ = build.one_per_picture([{"id": 1, "md5": "x"}, {"id": 2, "md5": "x"}], {}, keep={2})
        self.assertEqual([r["id"] for r in kept], [2], "Chris's hero pick on a twin stands for the group")
        settings.set(conn, build.HERO_KEY, str(ids[9]))                                   # his pick is the twin of ids[2]
        third = build.pick_photos(conn, fetch)
        self.assertEqual(third.grid_ids[0], ids[9], "his pick is the hero")
        self.assertNotIn(ids[2], third.ids, "and its twin is nowhere else on the site")

    def test_the_strip_from_the_library_spans_the_rooms_and_the_copies_go_when_the_photos_fit(self):
        from tests.test_wedding import event_photo
        conn = db.connect()
        self.addCleanup(conn.close)
        shots = ["portrait", "portrait", "portrait", "portrait", "stage_panel", "backstage", "reception", "breakout", "candid", "portrait",
                 "portrait", "stage_panel", "portrait", "portrait"]
        ids = []
        for i, shot in enumerate(shots):
            pid = event_photo(conn, f"p{i:02d}", kind="business", final="business", quality=5, width=3000 if i % 2 else 2000, height=2000 if i % 2 else 2500)
            conn.execute("UPDATE classifications SET shot_type=? WHERE photo_id=?", (shot, pid))
            conn.execute("UPDATE final_checks SET shot_type=? WHERE photo_id=?", (shot, pid))
            ids.append(pid)
        got = build.pick_photos(conn, lambda r: Image.new("RGB", (int(r["width"]), int(r["height"])), (80, 60, 120)))
        frames = got.grid_ids[1:]                              # after the hero (a landscape library photo)
        self.assertEqual(len(frames), build.COVERAGE_ROWS)
        self.assertEqual(len(set(frames)), len(frames), "no photo twice in the strip")
        self.assertNotIn(got.grid_ids[0], frames, "nor the hero")
        rooms = {r["shot_type"] for r in db.rows(conn, "SELECT photo_id, shot_type FROM classifications") if r["photo_id"] in frames[:6]}
        self.assertGreater(len(rooms), 1, "the first frames span more than one room when the pool has them")
        self.assertEqual(len(set(got.links[:5])), 5, "the first five frames open five different coverage pages")
        out = self.built(got)
        home = self.page(out, "index.html")
        strip = home[home.index('<section id="work" class="reel">'):]
        strip = strip[:strip.index("</section>")]
        own = re.findall(r'<div class="frame"><a href="[^"]+"><div class="ph" style="--ar:[0-9.]+"><img class="" src="(/assets/work-\d+-1600.jpg)"', strip)
        self.assertEqual(len(own), build.COVERAGE_ROWS)
        self.assertEqual(len(set(own)), len(own), "the first half of the strip never repeats a photo")
        copies = re.findall(r'<div class="frame" aria-hidden="true"><a tabindex="-1" href="[^"]+"><div class="ph" style="--ar:[0-9.]+"><img class="" src="(/assets/work-\d+-1600.jpg)"', strip)
        self.assertEqual(copies, own, "the second half is the loop's copy of the first, hidden from readers")
        js = theme.JS
        roll = js[js.index("const roll=document.querySelector('.reel .track')"):js.index("// parallax")]
        self.assertIn("const own=[...roll.querySelectorAll('.frame:not([aria-hidden])')]", roll)
        self.assertIn("const fits=!lastOwn||lastOwn.offsetLeft+lastOwn.offsetWidth<=roll.clientWidth;", roll)
        self.assertIn("if(fits)roll.querySelectorAll('.frame[aria-hidden]').forEach(c=>c.remove());", roll, "photos that fit the screen: no copies, no repeats")
        self.assertIn("if(!reduce&&!fits)raf=requestAnimationFrame(step)", roll, "and nothing rolls")


class SmallStuff(SizesCase):
    """Chris, 2026-10-14, from his computer: "the top website scroller cuts off on the left side when viewing on a computer.
    who we are - should be more than two fucking words! dont just skip the small stuuf becuse thats just as important as
    the main page". The inner pages get the home page's care."""

    def test_the_ticker_fades_over_the_gutter_and_starts_on_screen(self):
        """Seen live at 1440 and 1920: the word leaving at the left was sliced flat at x=0 while every other line on the
        page sits behind the 56px gutter. The ticker fades out over var(--pad) at both ends. Deliberate change,
        2026-10-15 ("still geting clipped ... its the top ticker"): the first word stood 26px in, inside that fade, so
        the page opened on a faded B. The strip now starts on the text column: translate by var(--pad) less 26px."""
        css = theme.CSS
        ticker = css[css.index(".ticker{"):css.index("}", css.index(".ticker{"))]
        for prop in ("-webkit-mask-image:linear-gradient(90deg,transparent,#000 var(--pad),#000 calc(100% - var(--pad)),transparent)",
                     "mask-image:linear-gradient(90deg,transparent,#000 var(--pad),#000 calc(100% - var(--pad)),transparent)", "overflow:hidden"):
            self.assertIn(prop, ticker, prop)
        self.assertIn("@keyframes tick{to{transform:translateX(-50%)}}", css, "from the natural position, no offset")
        self.assertIn(".ticker span{font:400 clamp(26px,3.6vw,54px)/1 var(--display);text-transform:uppercase;padding:0 26px;white-space:nowrap}", css)
        self.assertIn(".ticker .track{display:flex;width:max-content;translate:max(0px,calc(var(--pad) - 26px)) 0;"
                      "animation:tick 38s linear infinite}", css)
        home = self.page(self.built(), "index.html")
        self.assertEqual(home.count('aria-hidden="true"><div class="track"><span'), 2, "the two tickers of words")
        self.assertEqual(home.count('<div class="ticker'), 3, "and, since 2026-10-16, the logo strip rolls on the ticker's own class")
        self.assertIn('<div class="ticker" aria-hidden="true"><div class="track"><span class="">Backstage</span>', home)

    def test_who_we_are_is_a_paragraph_and_the_contact_links_fit_their_boxes(self):
        out = self.built()
        privacy = self.page(out, "privacy/index.html")
        who = privacy[privacy.index("<h3>Who we are</h3>"):privacy.index("</div></section>", privacy.index("<h3>Who we are</h3>"))]
        self.assertIn("<p>Event Caliber is the brand of Chris and Nic Kennedy, brothers and event photographers based in Washington, DC. "
                      "The company behind it is CKI, LLC. Questions about this page, a photo or the form go to hello@eventcaliber.com.</p>", who)
        self.assertNotIn("<p>Event Caliber is a brand of CKI, LLC.</p>", privacy, "the one-liner is gone")
        self.assertGreater(len(re.sub(r"<[^>]+>", " ", who).split()), 30)
        css = theme.CSS
        self.assertIn(".contact .hand{display:grid;grid-template-columns:1fr 1fr;gap:30px;margin-top:40px;max-width:1000px}", css)
        self.assertIn(".contact .hand a.l{display:block;font:400 clamp(16px,1.6vw,24px)/1.3 var(--display);margin-top:12px;overflow-wrap:anywhere}", css,
                      "at 30px the address broke mid-word in its box on an iPad and a computer")

    def test_thanks_and_not_found_say_what_happens_and_the_pages_end_near_the_footer(self):
        out = self.built()
        thanks = self.page(out, "thanks/index.html")
        self.assertIn('<p class="first">Your request is in. One of us reads it and writes back to you by email within 24 hours.</p>', thanks)
        self.assertIn("Until then, the coverage pages show what each room of an event looks like in our photographs.", thanks)
        self.assertIn('<a class="btn" href="/coverage/">The coverage', thanks)
        self.assertNotIn("min-height:70vh", thanks)
        lost = self.page(out, "404.html")
        self.assertIn('<p class="first">There is no page at this address. The pages are in the menu, and the coverage pages are a tap away.</p>', lost)
        for href in ("/", "/coverage/", "/contact/"):
            self.assertIn(f'<a class="btn" href="{href}">', lost, href)
        self.assertNotIn("min-height:70vh", lost)
        self.assertIn(".page{padding-top:clamp(130px,16vh,170px);padding-bottom:clamp(60px,8vw,110px)}", theme.CSS)
        self.assertIn(".page .first{font:400 clamp(19px,1.6vw,24px)/1.45 var(--body);color:var(--w);max-width:760px;margin:26px 0 0}", theme.CSS,
                      "the lead line is the same on every inner page: Contact, the coverage pages, Thanks and Not found")
        self.assertNotIn(".cover .first,.contact .first{", theme.CSS)
        book = self.page(out, "book/index.html")
        self.assertIn('<div class="f full"><label class="mono" for="event_kind">Kind of event</label>', book, "the menu's first choice was cut short in a half-width field")
        for rel in ("thanks/index.html", "404.html", "privacy/index.html"):
            text = re.sub(r"<script.*?</script>|<[^>]+>", " ", self.page(out, rel), flags=re.S)
            self.assertNotRegex(text, r"[—–]|\s-\s", rel)


class NothingCropped(SizesCase):
    def test_a_wide_photo_is_wide_and_a_tall_one_tall_on_every_surface_but_the_hero(self):
        """Chris, 2026-10-14: "the horizontal images must not be cropped anywhere on any device or should at least open
        to the full image - the landing page photo i know needs to be cropped at times". Every frame on the site has its
        photo's own shape (--ar, width over height, after the EXIF orientation) and shows it whole (object-fit:contain):
        the work strip, the delivery stack, the venues, the coverage pages and the About page. The hero is the one
        picture that may be cropped (object-fit:cover), and the only one."""
        wide, tall = Image.new("RGB", (2400, 1600), (40, 60, 90)), Image.new("RGB", (1600, 2000), (90, 40, 60))
        self.assertEqual((build.aspect(wide), build.aspect(tall)), ("1.5000", "0.8000"))
        turned = Image.new("RGB", (2400, 1600), (1, 2, 3))
        exif = Image.Exif()
        exif[0x0112] = 6                                      # a camera held upright: the saved file is 1600 by 2400
        with_exif = io.BytesIO()
        turned.save(with_exif, format="JPEG", exif=exif.tobytes())
        self.assertEqual(build.aspect(Image.open(with_exif)), "0.6667")
        p = build.SitePhotos(hero=[(wide, "a")], coverage=[(wide, "wide one"), (tall, "tall one"), (wide, "wide two")],
                             venues=[(wide, "v"), (tall, "v")], links=["/coverage/stage/"] * 3)
        p.pages = {"stage": [(wide, "stage photo 0"), (tall, "stage photo 1")]}
        out = self.built(p)
        home = self.page(out, "index.html")
        strip = home[home.index('<section id="work" class="reel">'):]
        self.assertEqual(re.findall(r'<div class="ph" style="--ar:([0-9.]+)">', strip[:strip.index("</section>")]),
                         ["1.5000", "0.8000", "1.5000"] * 2, "each frame, and its copy, carries the photo's shape")
        self.assertEqual(re.findall(r'<div class="stack rv">(?:<figure style="--ar:([0-9.]+)">)', home), ["1.5000"])
        self.assertEqual(home.count('<figure style="--ar:'), 3 + 2, "the stack's three and the two venues")
        self.assertNotIn("data-speed", home, "the venues' parallax needed a taller picture to slide: gone")
        stage = self.page(out, "coverage/stage/index.html")
        self.assertEqual(re.findall(r'<figure style="--ar:([0-9.]+)">', stage), ["1.5000", "0.8000"])
        about = self.page(out, "about/index.html")
        self.assertEqual(re.findall(r'<figure style="--ar:([0-9.]+)">', about), ["1.5000", "0.8000"])
        self.assertIn('<section class="page cover">', about, "the About page's figures take the coverage pages' layout")
        css = theme.CSS
        covers = [m.start() for m in re.finditer("object-fit:cover", css)]
        self.assertEqual(len(covers), 1, "one crop on the whole site")
        self.assertIn(".hero .img img{", css[css.rindex("{", 0, covers[0]) - 20:covers[0]], "and it is the hero's")
        for rule in (".frame .ph{width:min(calc(var(--h) * var(--ar,0.8)),calc(100vw - 2 * var(--pad)));aspect-ratio:var(--ar,0.8);background:var(--g2)}",
                     ".frame img{width:100%;height:100%;object-fit:contain;transition:filter .4s}",
                     ".stack figure{position:absolute;margin:0;width:62%;aspect-ratio:var(--ar,0.8);",
                     ".stack figure img{width:100%;height:100%;object-fit:contain}",
                     ".venues figure{margin:0 0 18px;break-inside:avoid;position:relative;overflow:hidden;background:var(--g2);aspect-ratio:var(--ar,1.5)}",
                     ".venues figure img{width:100%;height:100%;object-fit:contain}",
                     ".cover figure{margin:0 0 18px;break-inside:avoid;aspect-ratio:var(--ar,0.8);overflow:hidden;background:var(--g2)}.cover figure img{width:100%;height:100%;object-fit:contain}",
                     ".cover .grid{columns:3;gap:18px;margin-top:50px}", ".venues .grid{columns:2;gap:18px;margin-top:56px}"):
            self.assertIn(rule, css, rule)
        self.assertNotIn("transform:scale(1.06)", css, "the hover zoom cut the edges off")
        self.assertNotIn("aspect-ratio:4/5", css)
        self.assertNotIn("height:124%", css)
        phone = css[css.index("@media (max-width:760px)"):]
        self.assertIn(".frame{--h:clamp(240px,44vh,380px)}", phone, "a wide frame on a phone is capped at the screen's width by the min() above")
        self.assertIn(".cover .grid{columns:2;gap:10px}", phone)
        self.assertIn(".venues .grid{columns:1}", phone)
        ipad = css[css.index("@media (min-width:761px) and (max-width:1100px)"):css.index("@media (max-width:760px)")]
        self.assertIn(".frame{--h:clamp(280px,40vh,480px)}", ipad)
        self.assertIn(".cover .grid{columns:2}", ipad)
        js = theme.JS
        self.assertIn("for(const f of roll.querySelectorAll('.frame')){if(f.offsetLeft+f.offsetWidth>x+1)return f.offsetWidth+18}", js,
                      "an arrow moves by the frame at the left edge, since the frames differ in width now")


class CoveragePages(SizesCase):
    def test_nine_pages_with_the_place_in_the_title_their_photos_and_their_blocks(self):
        """One page per coverage item (Chris, 2026-10-14; the local search playbook: one page per service with the
        place in the title): its title with the place, its plain first sentence, its paragraph, its own photos, the
        Service, BreadcrumbList and ImageObject blocks, and the other eight pages linked under it."""
        out = self.built()
        items = offer.load()["coverage"]
        self.assertEqual(len(items), 9)
        for i, c in enumerate(items):
            rel = f"coverage/{c['key']}/index.html"
            page = self.page(out, rel)
            self.assertIn(f"<title>{html.escape(c['title'])}, Washington, DC | Event Caliber</title>", page)
            self.assertIn(f'<meta name="description" content="{html.escape(c["first"])}">', page)
            self.assertIn(f'<h1>{html.escape(c["label"])}<b>.</b></h1>', page)
            self.assertIn(f'<p class="first">{html.escape(c["first"])}</p>', page)
            self.assertIn(f'<div class="prose"><p>{html.escape(c["about"])}</p></div>', page)
            n = 2 if i % 2 else 4
            self.assertEqual(page.count("<figure style="), n, rel)
            self.assertIn(f'src="/assets/cover-{c["key"]}-0-1600.jpg"', page)
            self.assertIn(f'alt="{c["key"].replace("_", " ")} photo 0"', page)
            blocks = blocks_of(page)
            self.assertEqual([b["@type"] for b in blocks], ["Service", "BreadcrumbList"] + ["ImageObject"] * n, rel)
            self.assertEqual((blocks[0]["name"], blocks[0]["description"], blocks[0]["url"]), (c["title"], c["first"], f"{BASE}/coverage/{c['key']}/"))
            self.assertEqual([a["name"] for a in blocks[0]["areaServed"]], list(build.AREA_SERVED))
            self.assertEqual(blocks[0]["image"], f"{BASE}/assets/cover-{c['key']}-0-1600.jpg")
            self.assertEqual(blocks[0]["provider"], {"@type": "ProfessionalService", "name": "Event Caliber", "url": f"{BASE}/"})
            self.assertEqual([(x["position"], x["name"]) for x in blocks[1]["itemListElement"]], [(1, "Event Caliber"), (2, "Coverage"), (3, c["label"])])
            self.assertEqual(blocks[2]["contentUrl"], f"{BASE}/assets/cover-{c['key']}-0-1600.jpg")
            more = page[page.index('<div class="more">'):page.index("</section>")]
            self.assertEqual(re.findall(r'<a href="/coverage/([a-z_]+)/">', more), [k for k in offer.coverage_keys() if k != c["key"]], rel)
            self.assertIn('<a class="btn fill" href="/book/">Request a quote', page)
            self.assertIn('<a href="/coverage/">Coverage</a></div><h1>', page, "the kicker goes back to the index")
        index = self.page(out, "coverage/index.html")
        self.assertIn("<title>Event photography coverage in Washington, DC | Event Caliber</title>", index)
        self.assertEqual(re.findall(r'<a href="/coverage/([a-z_]+)/"><span class="mono g">', index), offer.coverage_keys())
        self.assertEqual([b["@type"] for b in blocks_of(index)], ["BreadcrumbList"])
        self.assertEqual(sorted(p.name for p in (out / "assets").glob("cover-*-1600.jpg")), sorted(f"cover-{k}-{j}-1600.jpg" for i, k in enumerate(offer.coverage_keys()) for j in range(2 if i % 2 else 4)))
        self.assertEqual(offer.public_pages(), ("/", "/about/", "/coverage/") + tuple(f"/coverage/{k}/" for k in offer.coverage_keys()) + ("/book/", "/availability/", "/contact/", "/privacy/"))
        self.assertEqual(build.PAGES, offer.public_pages())
        self.assertEqual(site_check.HTML_PATHS, build.PAGES, "the outside check reads the same list")

    def test_a_page_with_no_photos_of_its_own_still_builds_and_shares_the_hero_for_search(self):
        out = self.built(photos(pages=False))
        page = self.page(out, "coverage/portraits/index.html")
        self.assertNotIn("<figure>", page)
        self.assertEqual([b["@type"] for b in blocks_of(page)], ["Service", "BreadcrumbList"])
        self.assertIn(f'<meta property="og:image" content="{BASE}/assets/hero-1600.jpg">', page)
        self.assertNotIn('"image"', json.dumps(blocks_of(page)[0]))

    def test_every_shot_word_has_a_page_and_the_picker_fills_each_room_from_its_own_shots_first(self):
        """coverage_key_for: the page that lists the shot first (a stage shot is the main stage, a panel is breakouts,
        a candid is the delivery page), else the first page that lists it. pick_page_photos: up to six of the room's
        own kind, its first kind before the kinds it borrows, each photo on one page before any page repeats one; a
        room with under three photos is filled from the rest of the pool, so a page is never empty while the library
        has photos."""
        for key, shots in build.COVERAGE_SHOTS.items():
            self.assertIn(key, offer.coverage_keys(), key)
            for shot in shots:
                self.assertIn(shot, build.COVERAGE_SHOTS[build.coverage_key_for({"shot_type": shot})], shot)
        for shot, key in (("stage", "stage"), ("main_stage", "stage"), ("stage_panel", "stage"), ("breakout", "breakouts"),
                          ("backstage", "backstage"), ("candid", "on_site_delivery"), ("reception", "evening_events"),
                          ("portrait", "portraits"), ("building_exterior", ""), ("", ""), (None, "")):
            self.assertEqual(build.coverage_key_for({"shot_type": shot}), key, shot)
        pool = []
        for shot, n in (("backstage", 8), ("stage_panel", 7), ("stage", 2), ("portrait", 1), ("breakout", 3), ("candid", 6), ("reception", 4)):
            pool += [{"id": len(pool) + 1 + j, "shot_type": shot} for j in range(n)]
        pages = build.pick_page_photos(pool)
        ids = {k: [r["id"] for r in v] for k, v in pages.items()}
        self.assertEqual(list(ids), offer.coverage_keys())
        self.assertEqual(ids["backstage"], [1, 2, 3, 4, 5, 6], "six of its own, in the pool's order")
        self.assertEqual(ids["green_room"], [7, 8, 1, 2, 3, 4], "the two left, then the same room again before any other")
        self.assertEqual(ids["breakouts"], [19, 20, 21], "three of its own: enough, so nothing borrowed")
        self.assertEqual(ids["stage"], [16, 17, 9, 10, 11, 12], "its own stage shots first, then the panels (one room since 2026-10-29)")
        self.assertEqual(ids["evening_events"], [28, 29, 30, 31, 22, 23], "dinners first, then candids")
        self.assertEqual(ids["dinners"], [28, 29, 30, 31], "four of its own: enough, so nothing borrowed")
        self.assertEqual(ids["portraits"], [18, 13, 14, 15, 24, 25], "one portrait is under three: the pool's unused photos fill in")
        self.assertEqual(ids["exhibition_hall"], [26, 27, 1, 2, 3, 4], "no expo title among the eight: the page fills from the pool")
        self.assertEqual(ids["on_site_delivery"], [22, 23, 24, 25, 26, 27])
        two = [{"id": 1, "shot_type": "backstage"}, {"id": 2, "shot_type": "backstage"}]
        self.assertEqual({k: [r["id"] for r in v] for k, v in build.pick_page_photos(two).items()}, {k: [1, 2] for k in offer.coverage_keys()},
                         "two photos in the library: every page shows both")
        self.assertEqual(build.pick_page_photos([]), {k: [] for k in offer.coverage_keys()})

    def test_the_build_lists_the_pages_photos_after_the_home_pages(self):
        from tests.test_wedding import event_photo
        conn = db.connect()
        self.addCleanup(conn.close)
        ids = [event_photo(conn, f"p{i}", kind="business", final="business", quality=5) for i in range(10)]
        got = build.pick_photos(conn, lambda r: Image.new("RGB", (int(r["width"]), int(r["height"])), (80, 60, 120)))
        self.assertEqual(len(got.grid_ids), min(1 + build.COVERAGE_ROWS, len(ids)), "ten photos: the hero and nine frames")
        self.assertEqual(got.ids[:len(got.grid_ids)], got.grid_ids)
        self.assertEqual(sorted(got.ids), sorted(ids), "every usable photo is somewhere on the site")
        self.assertEqual(list(got.pages), offer.coverage_keys())
        self.assertEqual(got.links, ["/coverage/stage/"] * (len(ids) - 1), "the grid's frames open the page of their kind of shot")
        self.assertTrue(all(len(v) >= build.PAGE_MIN for v in got.pages.values()), {k: len(v) for k, v in got.pages.items()})
        self.assertEqual(len(got.pages["breakouts"]), build.PAGE_ROWS, "the panels' own page is full")


class Contact(SizesCase):
    def test_email_always_phone_only_when_set_and_no_form(self):
        """A general Contact page was missing (Chris, 2026-10-14); his decision: email and phone only, no form. The
        number comes from the Keys page (BRAND_PHONE); until he adds one nothing shows. With one, it is tappable on
        the Contact page, at the top on phones, in the footer and in the business block search engines read."""
        out = self.built()
        page = self.page(out, "contact/index.html")
        self.assertIn("<title>Contact us | Event Caliber</title>", page)
        self.assertIn('<h1>Get in<br><span class="o">touch</span><b>.</b></h1>', page)
        self.assertIn('<p class="first">Email or call, and one of us writes back within 24 hours.</p>', page)
        self.assertIn('<div class="mono c">Email</div><a class="l" href="mailto:hello@eventcaliber.com">hello@eventcaliber.com</a>', page)
        self.assertNotIn("tel:", page)
        self.assertNotIn("Phone</div>", page)
        self.assertNotIn("<form", page)
        self.assertIn(html.escape(build.AREA_LINE), page)
        self.assertIn('<a href="/privacy/" class="c">Privacy and photo removal</a>', page)
        self.assertIn('<a class="btn fill" href="/book/">Request a quote', page)
        home = self.page(out, "index.html")
        self.assertNotIn('class="tel mono"', home)
        self.assertNotIn("telephone", json.dumps(blocks_of(home)[0]))
        self.assertEqual(build.contact_phone(), "")
        os.environ["BRAND_PHONE"] = " 202 555 0100 "
        config.reset()
        self.assertEqual(build.contact_phone(), "202 555 0100")
        out = self.built()
        page = self.page(out, "contact/index.html")
        self.assertIn('<div class="mono c">Phone</div><a class="l" href="tel:2025550100">202 555 0100</a>', page)
        for rel in ("index.html", "about/index.html", "coverage/stage/index.html", "contact/index.html"):
            text = self.page(out, rel)
            self.assertIn('<a class="tel mono" href="tel:2025550100" aria-label="Call 202 555 0100"><svg viewBox="0 0 24 24" aria-hidden="true">', text, rel)
            self.assertIn("</svg><span>202 555 0100</span></a>", text, rel)
            self.assertIn('<li><a href="tel:2025550100">202 555 0100</a></li>', text, rel)
        self.assertEqual(blocks_of(self.page(out, "index.html"))[0]["telephone"], "202 555 0100")
        # the number as Chris typed it on the Keys page (2026-10-14): the words keep its brackets and dash, the links are digits
        for raw, href in (("(301) 523-0841", "tel:3015230841"), ("+1 301 523 0841", "tel:+13015230841"), ("301.523.0841", "tel:3015230841")):
            self.assertEqual(theme.tel_href(raw), href, raw)
        os.environ["BRAND_PHONE"] = "(301) 523-0841"
        config.reset()
        out = self.built()
        self.assertIn('<div class="mono c">Phone</div><a class="l" href="tel:3015230841">(301) 523-0841</a>', self.page(out, "contact/index.html"))
        home = self.page(out, "index.html")
        self.assertIn('<a class="tel mono" href="tel:3015230841" aria-label="Call (301) 523-0841">', home)
        self.assertIn('<li><a href="tel:3015230841">(301) 523-0841</a></li>', home)
        self.assertEqual(blocks_of(home)[0]["telephone"], "(301) 523-0841")
        self.assertNotIn("tel:(", home)
        css = theme.CSS
        self.assertIn(".contact .hand{display:grid;grid-template-columns:1fr 1fr", css)
        self.assertIn(".contact .hand{grid-template-columns:1fr}", css[css.index("@media (max-width:760px)"):])


class Footer(SizesCase):
    def test_every_page_every_coverage_item_the_contact_and_the_legal_line(self):
        """The footer was nearly empty (Chris, 2026-10-14). Now, on every page: the company and where it works, the
        nine coverage links, the pages, the email, the phone and the socials when set (https addresses only), and the
        legal line with the year."""
        out = self.built()
        for rel in ("index.html", "about/index.html", "coverage/stage/index.html", "contact/index.html", "404.html"):
            page = self.page(out, rel)
            foot = page[page.index("<footer>"):page.index("</footer>")]
            self.assertEqual(re.findall(r'<li><a href="/coverage/([a-z_]+)/">', foot), offer.coverage_keys(), rel)
            self.assertIn('<h4>Pages</h4><ul><li><a href="/#work">Work</a></li><li><a href="/about/">About</a></li><li><a href="/availability/">Availability</a></li>'
                          '<li><a href="/contact/">Contact</a></li><li><a href="/book/">Request a quote</a></li><li><a href="/privacy/">Privacy and photo removal</a></li></ul>', foot, rel)
            self.assertIn('<h4>Contact</h4><ul><li><a href="mailto:hello@eventcaliber.com">hello@eventcaliber.com</a></li></ul>', foot, rel)
            self.assertNotIn('rel="me', foot)
            self.assertIn(f"&#169; {date.today().year} CKI, LLC. Event Caliber is a brand of CKI, LLC.", foot, rel)
            self.assertIn("Event and convention photography by two brothers, more than thirty years each. " + html.escape(build.AREA_LINE), foot, rel)
            self.assertIn('<div class="big" aria-hidden="true">Event Caliber</div>', foot)
        os.environ["SOCIAL_INSTAGRAM"] = "https://www.instagram.com/eventcaliber/"
        os.environ["SOCIAL_FACEBOOK"] = "http://www.facebook.com/eventcaliber"          # not https: left out
        os.environ["SOCIAL_PINTEREST"] = "javascript:alert(1)"                             # never
        config.reset()
        self.assertEqual(build.social_links(), (("Instagram", "https://www.instagram.com/eventcaliber/"),))
        home = self.page(self.built(), "index.html")
        foot = home[home.index("<footer>"):home.index("</footer>")]
        self.assertIn('<li><a href="https://www.instagram.com/eventcaliber/" rel="me noopener">Instagram</a></li>', foot)
        self.assertNotIn("facebook", home)
        self.assertNotIn("javascript:", home)
        self.assertEqual(blocks_of(home)[0]["sameAs"], ["https://www.instagram.com/eventcaliber/"])
        os.environ["SOCIAL_PINTEREST"] = "https://www.pinterest.com/eventcaliber/"
        config.reset()
        self.assertEqual([a for a, _ in build.social_links()], ["Instagram", "Pinterest"])
        css = theme.CSS
        self.assertIn("footer .foot{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr", css)
        self.assertIn("footer .foot{grid-template-columns:1fr 1fr}", css[css.index("@media (min-width:761px)"):])
        self.assertIn("footer .foot{grid-template-columns:1fr;gap:28px}", css[css.index("@media (max-width:760px)"):])


class EveryPage(SizesCase):
    def test_one_h1_a_first_sentence_and_titles_and_descriptions_that_fit_a_search_result(self):
        """Every page: one h1; a plain first sentence on the home, coverage and contact pages; a title under 75 and a
        description under 160 characters. The build refuses a longer one instead of letting a search engine cut it."""
        out = self.built()
        pages = sorted(out.rglob("*.html"))
        self.assertEqual(len(pages), 18)
        for p in pages:
            text = p.read_text()
            self.assertEqual(text.count("<h1"), 1, p)
            title = html.unescape(re.search(r"<title>(.*?)</title>", text).group(1))
            desc = html.unescape(re.search(r'<meta name="description" content="(.*?)">', text).group(1))
            self.assertTrue(title and desc, p)
            self.assertLessEqual(len(title), build.TITLE_MAX, (p, title))
            self.assertLessEqual(len(desc), build.DESCRIPTION_MAX, (p, desc))
            self.assertNotRegex(title + desc, r"[—–]|\s-\s", p)
        for rel in ("index.html", "coverage/index.html", "coverage/backstage/index.html", "contact/index.html"):
            self.assertIn('<p class="first">', self.page(out, rel), rel)
        self.assertEqual((build.TITLE_MAX, build.DESCRIPTION_MAX), (75, 160))
        bad = json.loads(json.dumps(offer.load()))
        bad["coverage"][0]["first"] = "We photograph the minutes before the doors open, " * 4 + "quietly."
        self.assertGreater(len(bad["coverage"][0]["first"]), 160)
        (self.root / "offer.json").write_text(json.dumps(bad))
        os.environ["OFFER_FILE"] = str(self.root / "offer.json")
        config.reset()
        with self.assertRaises(build.SiteCopyRefused) as cm:
            self.built()
        self.assertIn("coverage/backstage/index.html", str(cm.exception))
        self.assertIn("160 at most", str(cm.exception))
        self.assertFalse((self.root / "dist" / "index.html").exists(), "nothing is written when a page is refused")
        bad["coverage"][0]["first"] = "Short."
        bad["coverage"][0]["title"] = "Backstage event photography for conferences, conventions and galas of every size"
        (self.root / "offer.json").write_text(json.dumps(bad))
        config.reset()
        with self.assertRaises(build.SiteCopyRefused) as cm:
            self.built()
        self.assertIn("75 at most", str(cm.exception))


class Head(SizesCase):
    def test_og_twitter_canonical_and_the_blocks(self):
        """og:url, og:site_name and a Twitter card on every page; a coverage page's og:image is its first photo;
        the thank-you and not-found pages carry noindex and no canonical; the home page's business block says where
        the company is and works, with a locality and region and never a street, its image, its logo, a telephone
        only when set and sameAs from the socials; the About page has a Person block for each brother."""
        out = self.built()
        for rel in ("index.html", "about/index.html", "coverage/index.html", "coverage/stage/index.html", "contact/index.html",
                    "book/index.html", "availability/index.html", "privacy/index.html"):
            page = self.page(out, rel)
            canonical = BASE + "/" + rel.replace("index.html", "")
            self.assertIn(f'<link rel="canonical" href="{canonical}"><meta property="og:url" content="{canonical}">', page, rel)
            self.assertIn('<meta property="og:site_name" content="Event Caliber">', page, rel)
            self.assertIn('<meta name="twitter:card" content="summary_large_image">', page, rel)
            self.assertNotIn("noindex", page, rel)
        self.assertIn(f'<meta property="og:image" content="{BASE}/assets/cover-stage-0-1600.jpg"><meta name="twitter:card" content="summary_large_image">'
                      f'<meta name="twitter:image" content="{BASE}/assets/cover-stage-0-1600.jpg">', self.page(out, "coverage/stage/index.html"))
        self.assertIn(f'<meta property="og:image" content="{BASE}/assets/hero-1600.jpg">', self.page(out, "index.html"))
        for rel in ("thanks/index.html", "404.html"):
            page = self.page(out, rel)
            self.assertIn('<meta name="robots" content="noindex,nofollow">', page, rel)
            self.assertNotIn('rel="canonical"', page, rel)
            self.assertNotIn("og:url", page, rel)
        business = blocks_of(self.page(out, "index.html"))[0]
        self.assertEqual(business["@type"], "ProfessionalService")
        self.assertEqual([a["name"] for a in business["areaServed"]], ["Washington, DC", "Maryland", "Virginia", "United States"])
        self.assertEqual(business["address"], {"@type": "PostalAddress", "addressLocality": "Washington", "addressRegion": "DC", "addressCountry": "US"})
        self.assertNotIn("streetAddress", json.dumps(business))
        self.assertEqual((business["image"], business["logo"]), (f"{BASE}/assets/hero-1600.jpg", f"{BASE}/assets/mark.svg"))
        self.assertNotIn("telephone", business)
        self.assertEqual(business["sameAs"], [])
        people = [b for b in blocks_of(self.page(out, "about/index.html")) if b["@type"] == "Person"]
        self.assertEqual([p["name"] for p in people], ["Chris Kennedy", "Nic Kennedy"])
        for p in people:
            self.assertEqual((p["jobTitle"], p["url"], p["worksFor"]["name"], p["alumniOf"]["name"]),
                             ("Photographer", f"{BASE}/about/", "Event Caliber", "The Corcoran, Washington, DC"))
        self.assertIn('<meta name="twitter:card" content="summary">', self.page(self.built(build.SitePhotos()), "index.html"), "no photo, a plain card")


class TheWorker(SizesCase):
    def test_www_goes_to_the_apex_for_good(self):
        """One address for the search engines: www.eventcaliber.com/about/?x=1 answers 301 to the same path on the
        apex, before any route. The live check is tests/worker_test.mjs under node (CI runs it too)."""
        js = (REPO / "worker/index.js").read_text()
        body = js[js.index("async fetch(request, env) {"):]
        self.assertLess(body.index('url.hostname.startsWith("www.")'), body.index('url.pathname.startsWith("/m/")'))
        self.assertLess(body.index('url.protocol === "http:"'), body.index('url.pathname.startsWith("/m/")'), "https only, before any route")
        self.assertIn("url.hostname = url.hostname.slice(4);", body)
        self.assertIn("return Response.redirect(url.toString(), 301);", body)
        test = (REPO / "tests/worker_test.mjs").read_text()
        self.assertIn('"https://www.eventcaliber.com/about/?x=1"', test)
        # seen live on 2026-10-14 after #64: www.eventcaliber.com/about/ answered 200 straight from the static assets, the
        # Worker never ran (Cloudflare serves a matching asset before the script unless told otherwise), while
        # www.eventcaliber.com/api/availability, no asset, answered 301. So the Worker runs first, for every request,
        # and hands the pages to the assets binding itself.
        config = (REPO / "wrangler.jsonc").read_text()
        assets = config[config.index('"assets": {'):config.index("},", config.index('"assets": {'))]
        self.assertIn('"run_worker_first": true', assets)
        self.assertIn('"binding": "ASSETS"', assets)
        self.assertIn("return env.ASSETS ? env.ASSETS.fetch(request) : new Response(\"not found\", { status: 404 });", body,
                      "the Worker still serves the site from the assets binding")
        node = shutil.which("node")
        self.assertTrue(node, "node is needed to run the Worker's own test (the Mini and CI have it)")
        run = subprocess.run([node, str(REPO / "tests/worker_test.mjs")], capture_output=True, text=True, timeout=120, cwd=str(REPO))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertRegex(run.stdout, r"worker: \d+ checks passed")


class KeysPage(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_four_fields_and_a_save_that_republishes_the_site(self):
        """The phone number and the three social addresses live on the Keys page (Chris adds them; nothing shows until
        he does). Saving one stamps the site like a photo change, so it republishes itself within minutes."""
        page = self.client.get("/keys").text
        self.assertIn("<strong>Website contact</strong>", page)
        for name in deploy.SITE_KEYS:
            self.assertIn(f'name="{name}"', page, name)
            self.assertIn(f'name="clear_{name}"', page, name)
        self.assertEqual(deploy.SITE_KEYS, ("BRAND_PHONE", "SOCIAL_INSTAGRAM", "SOCIAL_FACEBOOK", "SOCIAL_PINTEREST"))
        self.assertIn("republishes the site", page)
        self.assertIsNone(settings.get(self.conn, deploy.KEYS_CHANGED_KEY))
        r = self.client.post("/keys", data={"BRAND_PHONE": "202 555 0100"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertIn("the site republishes itself in a few minutes with the new contact details", r.headers["location"].replace("+", " "))
        config.reset()
        self.assertEqual(build.contact_phone(), "202 555 0100")
        stamp = settings.get(self.conn, deploy.KEYS_CHANGED_KEY)
        self.assertTrue(stamp)
        self.assertEqual(deploy.KEYS_CHANGED_KEY, "site.keys_changed_at")
        pending, why = deploy.photos_pending(self.conn)
        self.assertIn("the website's contact details on the Keys page changed at", why)
        r = self.client.post("/keys", data={"NTFY_TOPIC": "topic-x"}, follow_redirects=False)
        self.assertNotIn("republishes", r.headers["location"])
        self.assertEqual(settings.get(self.conn, deploy.KEYS_CHANGED_KEY), stamp, "another field changes nothing for the site")
        r = self.client.post("/keys", data={"SOCIAL_INSTAGRAM": "https://www.instagram.com/eventcaliber/"}, follow_redirects=False)
        self.assertIn("republishes", r.headers["location"])
        config.reset()
        self.assertEqual(build.social_links(), (("Instagram", "https://www.instagram.com/eventcaliber/"),))
        for path in ("convention_social/seo/markup.py", "convention_social/seo/photo_text.py", "convention_social/offer.py"):
            self.assertIn(path, deploy.SITE_PATHS, "a change here changes the site, so the updater redeploys it")
        env = (REPO / ".env.example").read_text()
        for name in deploy.SITE_KEYS:
            self.assertIn(f"{name}=", env)
