"""Post designs: every format and direction renders at the right size, carries no metadata, and refuses bad copy."""
from __future__ import annotations

import io
import json

from PIL import Image

from convention_social.core import db
from convention_social.render import meta, board, brand, posts
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes


def photo(seed=0, size=(2400, 1600)):
    return Image.open(io.BytesIO(jpeg_bytes((60 + seed * 40, 90, 120), size=size, seed=seed)))


class Render(IsolatedCase):
    def test_every_format_in_every_direction(self):
        made = 0
        for b in brand.DIRECTIONS.values():
            for fmt in posts.FORMATS:
                for aspect in ("4:5", "2:3"):
                    out = self.root / f"{b.key}-{fmt}-{aspect.replace(':', '')}.jpg"
                    text = posts.PostText(kicker="Katsucon 2025", headline="Every room of your event, covered.",
                                          lines=list(posts.SERVICES), credit="@ann_cos", site="example.org")
                    posts.render(fmt, [photo(i) for i in range(4)], text, b, aspect=aspect, out=out)
                    with Image.open(out) as im:
                        self.assertEqual(im.size, posts.SIZES[aspect])
                        self.assertEqual(meta.is_clean(out), [], "a post must carry no camera data, GPS included")
                    made += 1
        self.assertEqual(made, 3 * 4 * 2)

    def test_source_gps_never_travels(self):
        src = photo()
        self.assertIn(0x8825, src.getexif())   # the test photo really has GPS
        out = posts.render("photo", [src], posts.PostText(kicker="x"), brand.DIRECTIONS["lens"], out=self.root / "p.jpg")
        with Image.open(out) as im:
            self.assertNotIn(0x8825, im.getexif())
        self.assertEqual(meta.is_clean(out), [])

    def test_seo_fields_go_in_and_camera_data_stays_out(self):
        src_path = self.root / "src.jpg"
        src_path.write_bytes(jpeg_bytes())
        self.assertIn("gps", meta.is_clean(src_path))               # the checker sees a real original's GPS
        out = posts.render("photo", [photo()], posts.PostText(kicker="Katsucon 2025"), brand.DIRECTIONS["lens"],
                           out=self.root / "seo.jpg",
                           meta=meta.ImageMeta(title="Cosplay portrait at Katsucon 2025", description="A cosplayer in the main hall.",
                                               keywords=("cosplay", "convention photography"), credit="Cosplay: @ann_cos"))
        raw = out.read_bytes()
        self.assertTrue(raw)
        for needle in (b"Cosplay portrait at Katsucon 2025", b"convention photography", b"@ann_cos", b"Event Caliber", b"CKI, LLC",
                       b"eventcaliber.com/privacy/"):
            self.assertIn(needle, raw)
        self.assertEqual(meta.is_clean(out), [])

    def test_bad_copy_is_refused(self):
        b = brand.DIRECTIONS["press"]
        for text in (posts.PostText(headline="Coverage from $900"), posts.PostText(headline="Official photographer of the show"),
                     posts.PostText(headline="Fast — and good")):
            with self.assertRaises(posts.CopyRefused):
                posts.render("delivery", [photo()], text, b, out=self.root / "x.jpg")
        self.assertFalse((self.root / "x.jpg").exists())
        posts.render("delivery", [photo()], posts.PostText(headline="Official photographer of the show"), b,
                     out=self.root / "ok.jpg", official=True)

    def test_samples_page(self):
        conn = db.connect()
        picks = [{"id": i, "drive_id": f"d{i}", "convention_name": "Katsucon", "taken_at": "2025:02:14 10:00:00", "credit": ""}
                 for i in range(4)]
        out = board.samples(conn, picks, lambda r: photo(r["id"]), out_dir=self.root / "s",
                            captions=lambda r, f: {"instagram": "A moment at Katsucon."} if f == "photo" else {})
        files = sorted(p.name for p in out.glob("*.jpg"))
        self.assertEqual(len([f for f in files if not f.startswith("board-")]), 12)
        self.assertEqual(len([f for f in files if f.startswith("board-")]), 3)
        cards = json.loads((out / "samples.json").read_text())
        self.assertEqual(len(cards), 12)
        self.assertIn("A moment at Katsucon.", (out / "index.html").read_text())
