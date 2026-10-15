"""The logos under the hero (Chris, 2026-10-15): "should we add the companies we have worked for on the website? like
their logos", then "it can be political organizations, i just dont want them the only thing on the site". His answers:
under the top photo on the home page, in their own colours, headed "We've photographed for", no permission needed.
Off until he turns it on in offer.json (`clients.show`)."""
from __future__ import annotations

import html
import io
import json
import os

from PIL import Image

from convention_social import offer
from convention_social.ai import copy_rules
from convention_social.site import build, theme
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes


def photo(seed=0):
    return Image.open(io.BytesIO(jpeg_bytes((80, 90 + seed * 20, 120), size=(2400, 1600), seed=seed)))


class Logos(IsolatedCase):
    def setUp(self):
        super().setUp()
        (self.root / "site" / "clients").mkdir(parents=True)
        self.offer = json.loads(json.dumps(offer.load()))

    def logo(self, name: str, size=(600, 200), color=(20, 60, 140, 255), exif: bool = False) -> str:
        im = Image.new("RGBA", size, color)
        path = self.root / "site" / "clients" / f"{name}.png"
        if exif:
            ex = Image.Exif()
            ex[0x010E] = "a description that must not travel"
            im.save(path, exif=ex.tobytes())
        else:
            im.save(path)
        return f"site/clients/{name}.png"

    def use(self, show=True, items=(), heading=None):
        self.offer["clients"] = {"show": show, "heading": heading or "We've photographed for", "list": list(items)}
        (self.root / "offer.json").write_text(json.dumps(self.offer))
        os.environ["OFFER_FILE"] = str(self.root / "offer.json")

    def built(self):
        photos = build.SitePhotos(hero=[(photo(), "a")], coverage=[(photo(i), "c") for i in range(3)])
        out = build.build(None, photos, out=self.root / "dist", preview=True)
        return out, (out / "index.html").read_text()

    def test_on_by_his_word_with_his_twelve_in_order_rows_centred(self):
        """Chris, 2026-10-15, on the renders at the three sizes: "On, rows centered (Recommended)"."""
        self.assertIs(offer.load()["clients"]["show"], True)
        shown, why = build.client_logos()
        self.assertEqual(why, [])
        order = [c["name"] for c in shown]
        self.assertEqual(len(order), 12)
        self.assertEqual(order[0], "Library of Congress")
        self.assertEqual((order.index("American Conservative Union"), order.index("CPAC")), (3, 8))   # after the 3rd and 7th
        os.environ.pop("OFFER_FILE", None)
        _, home = self.built()
        self.assertIn('<section class="clients"', home)
        for name in order:
            self.assertIn(f'alt="{html.escape(name)}"', home)
        css = theme.CSS
        self.assertIn("justify-content:center", css[css.index(".clients .logos{"):][:220])
        self.assertIn("justify-content:center", css[css.index(".clients .kick{"):][:80])

    def test_off_when_he_turns_it_off(self):
        self.use(show=False, items=[{"name": "Plain", "logo": self.logo("plain"), "spread": False}])
        self.assertEqual(build.client_logos(), ([], []))
        _, home = self.built()
        self.assertNotIn('class="clients"', home)

    def test_his_twelve_each_with_its_file_its_source_and_its_date(self):
        """His list (2026-10-15), less Miner Feinstein Architects, which has no website and waits for his file."""
        repo = offer.load()["clients"]["list"]
        self.assertEqual(len(repo), 12)
        names = [c["name"] for c in repo]
        for want in ("Library of Congress", "Hamel Builders", "Center for Adoption Support and Education (C.A.S.E.)",
                     "Washington Nationals", "American Heart Association", "Associated Press", "American Conservative Union",
                     "CPAC", "WC Smith", "Bozzuto", "APTA Pelvic Health", "Grimm + Parker Architects"):
            self.assertIn(want, names)
        for c in repo:
            self.assertTrue((offer.path().parent / c["logo"]).is_file(), c["logo"])
            self.assertTrue(c["logo"].startswith("site/clients/") and c["logo"].endswith(".png"), c["logo"])
            self.assertTrue(c["source"] and c["fetched"], c["name"])
            self.assertIs(c["spread"], c["name"] in ("American Conservative Union", "CPAC"), c["name"])
        self.assertEqual(next(c for c in repo if c["name"] == "CPAC")["tile"], "dark")       # its mark is white

    def test_on_the_strip_sits_under_the_hero_with_each_logo_named_at_its_own_shape(self):
        self.use(items=[{"name": "Plain One", "logo": self.logo("one"), "spread": False},
                        {"name": "Plain Two", "logo": self.logo("two", (300, 300)), "spread": False, "tile": "dark"}])
        out, home = self.built()
        self.assertIn('<section class="clients" aria-label="We&#x27;ve photographed for">', home)
        self.assertLess(home.index('<section class="hero">'), home.index('class="clients"'))
        self.assertLess(home.index('class="clients"'), home.index('class="ticker'))
        self.assertIn('alt="Plain One" width="360" height="120"', home)          # 600x200 kept at its shape, LOGO_H tall
        self.assertIn('<li class="tile dark"><img src="/assets/clients/plain-two.png" alt="Plain Two" width="120" height="120"', home)
        with Image.open(out / "assets" / "clients" / "plain-one.png") as im:
            self.assertEqual(im.size, (360, 120))

    def test_a_logo_is_saved_fresh_from_its_pixels(self):
        self.use(items=[{"name": "Plain One", "logo": self.logo("one", exif=True), "spread": False}])
        out, _ = self.built()
        with Image.open(out / "assets" / "clients" / "plain-one.png") as im:
            self.assertNotIn("exif", im.info)
            self.assertEqual(len(im.getexif()), 0)

    def test_political_logos_never_lead_never_bunch_and_never_outnumber_the_rest(self):
        """"i just dont want them the only thing on the site"."""
        p = lambda n: {"name": n, "logo": self.logo(n.lower().replace(" ", "-")), "spread": True}   # noqa: E731
        q = lambda n: {"name": n, "logo": self.logo(n.lower().replace(" ", "-")), "spread": False}  # noqa: E731
        self.use(items=[p("Pol A"), p("Pol B"), p("Pol C"), q("Plain A"), q("Plain B")])
        shown, why = build.client_logos()
        self.assertEqual([c["name"] for c in shown], ["Plain A", "Pol A", "Plain B", "Pol B"])
        self.assertEqual(len(why), 1)
        self.assertIn("Pol C", why[0])
        self.use(items=[p("Pol A"), p("Pol B")])
        shown, why = build.client_logos()
        self.assertEqual(shown, [])
        self.assertEqual(len(why), 2)
        _, home = self.built()
        self.assertNotIn('class="clients"', home)

    def test_political_logos_are_spread_through_the_row(self):
        mk = lambda n, pol: {"name": n, "logo": self.logo(n.lower().replace(" ", "-")), "spread": pol}   # noqa: E731
        plain = [mk(f"Plain {i}", False) for i in range(10)]
        self.use(items=plain[:3] + [mk("Pol A", True), mk("Pol B", True)] + plain[3:])
        order = [c["name"] for c in build.client_logos()[0]]
        self.assertEqual(order.index("Pol A"), 3, order)                    # after the third of ten
        self.assertEqual(order.index("Pol B"), 8, order)                    # after the seventh
        for i in range(len(order) - 1):
            self.assertFalse(order[i].startswith("Pol") and order[i + 1].startswith("Pol"), order)

    def test_the_acu_and_cpac_may_be_on_the_strip_and_are_still_never_contacted(self):
        """Chris, 2026-10-15: "no you can use acu and cpac for this, i just donrt want them emailed for outreach as i
        stated in the beginning"."""
        from convention_social.outreach import compliance
        plain = [{"name": f"Plain {i}", "logo": self.logo(f"plain-{i}"), "spread": False} for i in range(2)]
        self.use(items=plain + [{"name": "American Conservative Union", "logo": self.logo("acu"), "spread": True},
                                {"name": "CPAC", "logo": self.logo("cpac"), "spread": True, "tile": "dark"}])
        _, home = self.built()
        self.assertIn('alt="American Conservative Union"', home)
        self.assertIn('alt="CPAC"', home)
        for refused in (compliance.never_contact(names=("CPAC",)), compliance.never_contact(names=("American Conservative Union",)),
                        compliance.never_contact(email="press@conservative.org"), compliance.never_contact(urls=("https://www.cpac.org/",))):
            self.assertIsNotNone(refused)

    def test_each_logo_is_cut_to_what_shows_and_set_by_its_weight(self):
        im = Image.new("RGBA", (900, 300), (255, 255, 255, 255))           # a white box with the mark in its middle
        im.paste((20, 60, 140, 255), (300, 100, 600, 200))
        path = self.root / "site" / "clients" / "boxed.png"
        im.save(path)
        self.use(items=[{"name": "Boxed", "logo": "site/clients/boxed.png", "spread": False}])
        out, home = self.built()
        with Image.open(out / "assets" / "clients" / "boxed.png") as got:
            self.assertAlmostEqual(got.width / got.height, 3.0, delta=0.25)   # the mark, not the box
            self.assertEqual(got.getpixel((1, 1))[3], 0, "the white box went clear")
        self.assertIn('style="--k:', home)
        self.assertEqual(build.optical(120, 120), 1.3)                       # a square mark is set up to the tile's height
        self.assertEqual(build.optical(745, 120), 0.6)                       # a long wordmark comes down
        self.assertLess(build.optical(484, 120), build.optical(199, 120))
        self.assertIn("height:calc(var(--lh) * var(--k, 1))", theme.CSS)

    def test_unsaid_politics_counts_as_political(self):
        """Fail closed: only `spread: false` makes a logo count as not political (offer.json says "spread", never the word
        itself: nothing there positions the company, 2026-10-12)."""
        self.use(items=[{"name": "Unsaid", "logo": self.logo("unsaid")}])
        self.assertEqual(build.client_logos()[0], [])
        self.use(items=[{"name": "Unsaid", "logo": self.logo("unsaid")}, {"name": "Plain", "logo": self.logo("plain"), "spread": False}])
        self.assertEqual([c["name"] for c in build.client_logos()[0]], ["Plain", "Unsaid"])

    def test_a_logo_without_its_name_its_file_or_a_safe_svg_is_left_out_and_said(self):
        bad_svg = self.root / "site" / "clients" / "bad.svg"
        bad_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
        far_svg = self.root / "site" / "clients" / "far.svg"
        far_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://elsewhere.example/x.png"/></svg>')
        good_svg = self.root / "site" / "clients" / "good.svg"
        good_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 30 10"><rect width="30" height="10"/></svg>')
        (self.root / "outside.png").write_bytes((self.root / self.logo("tmp")).read_bytes())
        self.use(items=[{"name": "", "logo": self.logo("noname"), "spread": False},
                        {"name": "No File", "logo": "site/clients/missing.png", "spread": False},
                        {"name": "Outside", "logo": "outside.png", "spread": False},
                        {"name": "Climbs Out", "logo": "site/clients/../../outside.png", "spread": False},
                        {"name": "Script", "logo": "site/clients/bad.svg", "spread": False},
                        {"name": "Far", "logo": "site/clients/far.svg", "spread": False},
                        {"name": "Good", "logo": "site/clients/good.svg", "spread": False}])
        shown, why = build.client_logos()
        self.assertEqual([c["name"] for c in shown], ["Good"])
        self.assertEqual(len(why), 6)
        out, home = self.built()
        self.assertTrue((out / "assets" / "clients" / "good.svg").is_file())
        self.assertIn('<img src="/assets/clients/good.svg" alt="Good" loading="lazy"', home)

    def test_the_heading_passes_the_copy_rules(self):
        self.use(items=[{"name": "Plain", "logo": self.logo("plain"), "spread": False}], heading="Trusted by")
        with self.assertRaises(build.SiteCopyRefused):
            self.built()

    def test_the_names_rule_still_holds_everywhere_else(self):
        """The strip is the one place an organization is named; a caption naming one is still refused."""
        self.assertFalse(copy_rules.check("Backstage at Plain One this week.", names=["Plain One"], social=True).ok)

    def test_three_sizes(self):
        css = theme.CSS
        self.assertIn(".clients .tile{height:84px", css)
        ipad = css[css.index("@media (min-width:761px) and (max-width:1100px)"):]
        ipad = ipad[:ipad.index("}}") + 2]
        self.assertIn(".clients .tile{height:74px", ipad)
        phone = css[css.index("@media (max-width:760px)"):]
        phone = phone[:phone.index("}}") + 2]
        self.assertIn(".clients .tile{height:62px", phone)
        self.assertIn("flex-wrap:wrap", css[css.index(".clients .logos{"):][:200])
