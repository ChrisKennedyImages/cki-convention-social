"""Chris, 2026-10-15: "Website says interior and exterior and both are exteriors. Just one or two venue picks at most
and not labeled on the image itself". The labels came from position (the first Exterior, the second Interior), never
from the photo. The home page's Venues section shows at most two photos and no word on any of them; one photo alone
takes the full width."""
from __future__ import annotations

import io
import re

from PIL import Image

from convention_social.site import build, theme
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes


def im(seed=0):
    return Image.open(io.BytesIO(jpeg_bytes((80, 90 + seed * 20, 120), size=(2400, 1600), seed=seed)))


class Venues(IsolatedCase):
    def built(self, n):
        photos = build.SitePhotos(hero=[(im(), "a")], coverage=[(im(i + 1), f"c{i}") for i in range(3)],
                                  venues=[(im(20 + i), f"v{i}") for i in range(n)])
        out = build.build(None, photos, out=self.root / f"dist{n}")
        home = (out / "index.html").read_text()
        return out, home[home.index('<section id="venues"'):home.index("</section>", home.index('<section id="venues"'))]

    def test_two_at_most_and_no_word_on_a_picture(self):
        out, section = self.built(4)
        self.assertEqual(build.VENUE_ROWS, 2)
        self.assertEqual(section.count("<figure"), 2)
        for word in ("Exterior", "Interior", 'class="mono"'):
            self.assertNotIn(word, section[section.index('<div class="grid'):], word)
        self.assertEqual(sorted(p.name.split("-")[1] for p in (out / "assets").glob("venue-*.jpg")), ["0", "0", "1", "1"],
                         "only the two shown are saved (two widths each)")
        self.assertNotIn(".venues figure .mono", theme.CSS)

    def test_one_photo_takes_the_full_width(self):
        _, section = self.built(1)
        self.assertEqual(section.count("<figure"), 1)
        self.assertIn('<div class="grid one">', section)
        self.assertIn(".venues .grid.one{columns:1}", theme.CSS)
        _, two = self.built(2)
        self.assertIn('<div class="grid">', two)
