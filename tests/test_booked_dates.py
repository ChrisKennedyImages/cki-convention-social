"""The booked dates live on the quote page (Chris, 2026-10-15: "the availabilty calender is completly empty which is
a very bad look and its its own tab"; redone fresh from main on 2026-10-31, his ruling). The Availability page and its
menu word are gone; /book/ carries one line, "Dates already booked", the dates and nothing else, never a name, that stays
hidden while nothing is booked, when the script does not run, and when the API is down or answers with an error. The
old address answers 301 to /book/ (the Worker's own test, run below); the public pages, the sitemap and the outside
check agree without it. The API itself is untouched: GET /api/availability, booked dates only, fed by the Mini's PUT.

The line's script is run in node against a stand-in page and a stand-in API, so the empty case is proven where it is
used: the element keeps `hidden`, and `hidden` wins over the line's flex layout.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image

from convention_social import offer
from convention_social.seo import markup, site_check
from convention_social.site import build, theme
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes

REPO = Path(__file__).resolve().parents[1]
NAV = r'<nav class="mono" aria-label="Pages">(.*?)</nav>'
SCRIPT = r"<script>(\(function\(\)\{const M=.*?)</script>"
# the line's script with a stand-in document, fetch and clock; prints what the page would show
HARNESS = r"""
const fs = require("node:fs");
const { script, booked, now, api } = JSON.parse(fs.readFileSync(0, "utf8"));
const els = { booked: { hidden: true, textContent: "" }, "booked-when": { hidden: false, textContent: "" } };
const calls = [];
const RealDate = Date;
class FixedDate extends RealDate { constructor(...a) { if (a.length) super(...a); else super(now); } static now() { return new RealDate(now).getTime(); } }
const fetch = async (url) => {
  calls.push(url);
  if (api === "down") throw new TypeError("Failed to fetch");
  if (api === "error") return { ok: false, json: async () => { throw new SyntaxError("not json"); } };
  return { ok: true, json: async () => ({ booked }) };
};
new Function("document", "fetch", "Date", script)({ getElementById: (id) => els[id] }, fetch, FixedDate);
setTimeout(() => console.log(JSON.stringify({ hidden: els.booked.hidden, text: els["booked-when"].textContent, calls })), 50);
"""


def im(seed=0):
    return Image.open(io.BytesIO(jpeg_bytes((80, 90 + seed * 20, 120), size=(2400, 1600), seed=seed)))


class BookedDates(IsolatedCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")

    def built(self, photos=None):
        photos = photos or build.SitePhotos(hero=[(im(), "a")], coverage=[(im(i), "c") for i in range(3)], venues=[(im(9), "v")])
        return build.build(None, photos, out=self.root / "dist")

    def run_line(self, booked, now="2026-10-15T12:00:00", api="ok"):
        self.assertTrue(self.node, "node is needed to run the line's script (the Mini and CI have it)")
        book = (self.out / "book/index.html").read_text()
        script = re.search(SCRIPT, book, flags=re.S).group(1)
        run = subprocess.run([self.node, "-e", HARNESS], input=json.dumps({"script": script, "booked": booked, "now": now, "api": api}),
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def setUp(self):
        super().setUp()
        self.out = self.built()

    def test_nothing_booked_shows_nothing(self):
        """The empty case: no grid, no line, no "nothing booked" either. The same when the API is down, answers with
        an error or with something that is not a list, or every date it has is already past."""
        book = (self.out / "book/index.html").read_text()
        self.assertIn('<p class="booked" id="booked" hidden>', book, "hidden in the page itself, so no script shows nothing")
        css = (self.out / "assets/site.css").read_text()
        self.assertIn(".booked[hidden]{display:none}", css, "the line's display:flex would otherwise beat the hidden attribute")
        self.assertLess(css.index(".booked{display:flex"), css.index(".booked[hidden]{display:none}"))
        for booked, api in (([], "ok"), (None, "ok"), ("Acme Gala", "ok"), (["2026-10-01", "2026-10-14"], "ok"),
                            (["2026-11-07"], "down"), (["2026-11-07"], "error")):
            seen = self.run_line(booked, api=api)
            self.assertEqual(seen, {"hidden": True, "text": "", "calls": ["/api/availability"]}, (booked, api))
        for old in (".cal{", ".days{", ".legend{", ".month "):
            self.assertNotIn(old, theme.CSS, "the calendar's styles went with the page")
        for page in self.out.rglob("*.html"):
            self.assertNotIn('id="cal"', page.read_text(), page)

    def test_a_few_booked_dates_read_as_one_line_of_dates_only(self):
        """Runs of days read as one ("Nov 7 to 9"), across a month too; a year is said only when it is not this one;
        past days, repeats and anything that is not a date are dropped, so a name can never show; every run shows,
        there is no "and more"; no dash anywhere (the copy rules)."""
        booked = ["2026-10-14", "2026-10-15", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-09", "2026-11-07", "2026-11-08",
                  "2026-12-03", "2026-12-03", "2026-12-31", "2027-01-01", "2027-01-02", "2027-02-10", "Acme Gala", "2026-13", 7, None]
        seen = self.run_line(booked)
        self.assertFalse(seen["hidden"])
        text = seen["text"]
        self.assertEqual(text.replace("\u00a0", " "), "Oct 15 \u00b7 Oct 30 to Nov 1 \u00b7 Nov 7 to 9 \u00b7 Dec 3 \u00b7 Dec 31 to Jan 2, 2027 \u00b7 Feb 10, 2027")
        self.assertNotRegex(text, r"[‐-―−]|Acme|more")
        # a line may break only after a dot: every run is held together, and a dot never starts a line
        self.assertEqual(text.replace("\u00a0", "_").split(" "), ["Oct_15_\u00b7", "Oct_30_to_Nov_1_\u00b7", "Nov_7_to_9_\u00b7", "Dec_3_\u00b7",
                                                         "Dec_31_to_Jan_2,_2027_\u00b7", "Feb_10,_2027"])
        many = [f"2026-11-{d:02d}" for d in range(1, 30, 2)]           # fifteen single days, two apart
        seen = self.run_line(many)
        self.assertEqual(seen["text"].replace("\u00a0", " ").split(" \u00b7 "), [f"Nov {d}" for d in range(1, 30, 2)], "every one of them")

    def test_the_line_sits_under_the_quote_page_opening_and_nowhere_else(self):
        book = (self.out / "book/index.html").read_text()
        self.assertLess(book.index("What moves the quote"), book.index('id="booked"'))
        self.assertLess(book.index('id="booked"'), book.index('<div class="split2">'))
        self.assertIn('<span class="mono c">Dates already booked</span><span class="when" id="booked-when"></span></p>', book,
                      "the label, then the dates: nothing else on the line")
        for page in self.out.rglob("*.html"):
            if page.name == "index.html" and page.parent.name == "book":
                continue
            self.assertNotIn('id="booked"', page.read_text(), page)

    def test_availability_is_gone_from_the_menu_the_footer_and_every_page(self):
        for out in (self.out, self.built(build.SitePhotos())):
            pages = list(out.rglob("*.html"))
            self.assertGreater(len(pages), 10)
            for page in pages:
                text = page.read_text()
                self.assertNotIn("/availability/", text, page)
                self.assertNotIn(">Availability<", text, page)
                nav = re.search(NAV, text, flags=re.S).group(1)
                self.assertEqual([w for w in re.findall(r">([A-Za-z ]+)</a>", nav) if w != "Work"], ["Coverage", "About", "Contact"], page)
            self.assertFalse((out / "availability").exists())

    def test_the_public_pages_the_sitemap_and_the_outside_check_agree_without_it(self):
        self.assertNotIn("/availability/", offer.public_pages())
        self.assertNotIn("/availability/", markup.DEFAULT_PAGES)
        self.assertEqual(build.PAGES, offer.public_pages())
        self.assertEqual(site_check.HTML_PATHS, build.PAGES)
        sitemap = (self.out / "sitemap.xml").read_text()
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
        self.assertEqual([loc for loc in locs if not loc.endswith(".jpg")], ["https://eventcaliber.com" + p for p in build.PAGES])
        self.assertNotIn("availability", sitemap)
        for p in build.PAGES:
            rel = "index.html" if p == "/" else p.strip("/") + "/index.html"
            self.assertTrue((self.out / rel).exists(), rel)

    def test_the_old_address_answers_301_to_the_quote_page(self):
        """The Worker sends /availability/ (and anything under it) to /book/ for good, after the www and https redirect
        and before the assets; the API it read is still routed. The Worker's own test proves it against a stand-in request."""
        body = (REPO / "worker/index.js").read_text()
        route = 'if (/^\\/availability(\\/.*)?$/.test(url.pathname)) return Response.redirect(`${url.origin}/book/`, 301);'
        self.assertIn(route, body)
        self.assertLess(body.index('if (www || (url.protocol === "http:" && !local))'), body.index(route))
        self.assertLess(body.index(route), body.index('if (url.pathname === "/api/availability") return availability(request, env);'))
        self.assertLess(body.index(route), body.index("return env.ASSETS ? env.ASSETS.fetch(request)"))
        test = (REPO / "tests/worker_test.mjs").read_text()
        self.assertIn("answers 301 to /book/", test)
        self.assertTrue(self.node, "node is needed to run the Worker's own test (the Mini and CI have it)")
        run = subprocess.run([self.node, str(REPO / "tests/worker_test.mjs")], capture_output=True, text=True, timeout=120, cwd=str(REPO))
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
