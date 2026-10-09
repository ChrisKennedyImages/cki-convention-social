"""Review sheets for Chris: one brand board per direction, and the sample set.

brand_board()  the mark on dark and on light, the palette with its hex codes,
               the type, and the four post formats, on one image.
samples()      twelve sample posts (four formats in each of the three
               directions) from his strongest photos, with their captions, on
               one HTML page plus the JPEGs. For his eyes only: nothing here is
               cleared, queued or posted.
"""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image, ImageDraw

from ..core import config
from . import fonts, posts
from .brand import DIRECTIONS, TAGLINE, Direction, current, draw_mark, tracked


def _hex(c) -> str:
    return "#%02X%02X%02X" % tuple(c[:3])


def brand_board(direction: Direction, format_paths: Sequence[Path], out: Path, *, note: str = "") -> Path:
    W, m = 2400, 80
    tile_w = (W - 2 * m - 3 * 40) // 4
    H = 900 + int(tile_w * 1.25) + m
    img = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(img)
    d.text((m, 60), f"Direction: {direction.label}", font=fonts.face("InterTight-SemiBold.ttf", 56), fill=(20, 20, 22))
    if note:
        d.text((m, 132), note, font=fonts.face("InterTight-Regular.ttf", 28), fill=(110, 110, 115))
    # marks
    dark = (m, 200, m + 1080, 560)
    light = (m + 1120, 200, W - m, 560)
    d.rectangle(dark, fill=direction.ink)
    d.rectangle(light, fill=direction.paper)
    draw_mark(img, direction, dark[0] + 80, dark[1] + 110, 70, on_dark=True, with_tagline=True)
    draw_mark(img, direction, light[0] + 80, light[1] + 110, 70, on_dark=False, with_tagline=True)
    # palette
    y = 610
    for i, (name, c) in enumerate((("Ink", direction.ink), ("Paper", direction.paper), ("Accent", direction.accent))):
        x = m + i * 380
        d.rectangle((x, y, x + 340, y + 150), fill=c, outline=(210, 210, 210))
        d.text((x, y + 165), f"{name}  {_hex(c)}", font=fonts.face("InterTight-SemiBold.ttf", 28), fill=(40, 40, 44))
    # type
    tx = m + 1180
    d.text((tx, y), "Headlines", font=fonts.face("InterTight-Regular.ttf", 26), fill=(110, 110, 115))
    sample = "Every room, covered."
    sample = sample.upper() if direction.display_upper else sample
    size = 76
    while size > 30 and d.textlength(sample, font=fonts.face(direction.display, size)) > W - tx - m:
        size -= 4
    d.text((tx, y + 36), sample, font=fonts.face(direction.display, size), fill=direction.ink)
    d.text((tx, y + 150), "Body and labels", font=fonts.face("InterTight-Regular.ttf", 26), fill=(110, 110, 115))
    tracked(d, (tx, y + 190), TAGLINE.upper(), fonts.face(direction.body_bold, 28), direction.ink, direction.tracking)
    # formats
    y = 900
    for i, p in enumerate(format_paths[:4]):
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((tile_w, 1100))
            img.paste(im, (m + i * (tile_w + 40), y))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="JPEG", quality=90)
    return out


SAMPLE_COPY = {
    "appearance": posts.PostText(kicker="We'll be there", headline="{event}",
                                 lines=["{when}", "Full event coverage, with approved images delivered on site."]),
    "services": posts.PostText(kicker="Event coverage", headline="Every room of your event, covered.", lines=list(posts.SERVICES)),
    "delivery": posts.PostText(kicker="On site delivery", headline="Approved images in hand before the event ends.",
                               lines=["Attendees, staff, speakers and presenters get their photos while the event is still on."]),
}


def samples(conn: sqlite3.Connection, picks: Sequence[dict], fetch_photo: Callable[[dict], Image.Image], *,
            out_dir: Optional[Path] = None, captions: Optional[Callable[[dict, str], dict]] = None,
            event: str = "", when: str = "", site: str = "", note: str = "") -> Path:
    """`picks` are photo rows (dicts with at least id, convention_name, taken_at). Twelve posts in the chosen
    direction (four formats, three rounds of different photos) and its brand board."""
    out_dir = out_dir or config.get_config().data_root / "renders" / f"samples-{datetime.now():%Y%m%d-%H%M}"
    out_dir.mkdir(parents=True, exist_ok=True)
    photos = [fetch_photo(p) for p in picks[:6]]
    if not photos:
        raise ValueError("no photos to build samples from")
    cards = []
    chosen = current() or DIRECTIONS["aperture"]
    for di in range(3):
        key, b = f"{chosen.key}-{di + 1}", chosen
        made = []
        lead = picks[di % len(picks)]
        kicker = " ".join(x for x in ((lead.get("convention_name") or ""), (lead.get("taken_at") or "")[:4]) if x)
        jobs = [("photo", [photos[di % len(photos)]], posts.PostText(kicker=kicker or "On assignment", credit=lead.get("credit", ""), site=site)),
                ("appearance", [photos[(di + 1) % len(photos)]], posts.PostText(
                    kicker=SAMPLE_COPY["appearance"].kicker, headline=event or "Your next event",
                    lines=[when or "Dates and city from the calendar", SAMPLE_COPY["appearance"].lines[1]], site=site)),
                ("services", photos[:4], posts.PostText(kicker="Event coverage", headline=SAMPLE_COPY["services"].headline,
                                                        lines=list(posts.SERVICES), site=site)),
                ("delivery", [photos[(di + 2) % len(photos)]], posts.PostText(kicker="On site delivery", headline=SAMPLE_COPY["delivery"].headline,
                                                                               lines=SAMPLE_COPY["delivery"].lines, site=site))]
        for fmt, ph, text in jobs:
            path = posts.render(fmt, ph, text, b, out=out_dir / f"{key}-{fmt}.jpg")
            cap = captions(lead, fmt) if captions else {}
            made.append(path)
            cards.append({"direction": b.label, "format": fmt, "file": path.name, "captions": cap})
        if di == 0:
            brand_board(b, made, out_dir / f"board-{chosen.key}.jpg", note=note)
    e = html.escape
    items = "".join(
        f'<figure><img src="{e(c["file"])}"><figcaption><b>{e(c["direction"])}</b>, {e(c["format"])}'
        + "".join(f'<p><i>{e(n)}</i><br>{e(t)}</p>' for n, t in c["captions"].items()) + "</figcaption></figure>"
        for c in cards)
    boards = f'<p><img src="board-{chosen.key}.jpg" style="max-width:100%"></p>'
    (out_dir / "index.html").write_text(f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sample posts</title><style>body{{font:15px/1.5 -apple-system,Helvetica,Arial;margin:24px;color:#1c1c1e}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:20px}}figure{{margin:0}}img{{width:100%;border-radius:6px}}
p{{white-space:pre-wrap;font-size:14px}}</style>
<h1>{e(config.get_config().brand_name)}: twelve sample posts</h1>
<p>For review only. Nothing here is cleared, queued or posted.</p>{"<p><b>" + e(note) + "</b></p>" if note else ""}{boards}<div class="g">{items}</div>""",
                                           encoding="utf-8")
    (out_dir / "samples.json").write_text(json.dumps(cards, indent=2))
    return out_dir
