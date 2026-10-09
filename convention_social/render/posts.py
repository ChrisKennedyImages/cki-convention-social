"""Post designs built around Chris's photos. The photo leads; type and colour serve it.

Formats (every one at 4:5 for Instagram and Facebook, 2:3 for Pinterest):
  photo        the daily post: the photo edge to edge, clean, with a slim
               gradient foot carrying the event, the year, the credit and the mark
  appearance   "we'll be at": the photo on top, a panel in the brand ink with
               the event, dates and city, what the company covers, and the ask
  services     what the company covers: four photos in a mosaic over a panel
               listing the coverage, and the ask
  delivery     same-day delivery of approved images: one strong photo, one line

Every word drawn here must pass ai.copy_rules (no price, no dash, no
unconfirmed affiliation); render() refuses text that does not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageOps

from ..ai import copy_rules
from . import fonts
from .brand import Direction, draw_mark, tracked, tracked_width
from .meta import ImageMeta, save_jpeg

SIZES = {"4:5": (1080, 1350), "2:3": (1000, 1500), "1:1": (1080, 1080)}
FORMATS = ("photo", "appearance", "services", "delivery")
SERVICES = ("Backstage and green rooms", "Breakouts and panels", "Before, during and evening events",
            "Dinners and receptions", "Portraits", "Exhibition halls and vendors")


@dataclass
class PostText:
    kicker: str = ""            # small caps line, e.g. the event and year
    headline: str = ""
    lines: Sequence[str] = field(default_factory=tuple)
    credit: str = ""            # exactly as recorded, e.g. "@handle"
    ask: str = "Request a quote"
    site: str = ""              # the company domain, when there is one

    def all_text(self) -> str:
        return " ".join([self.kicker, self.headline, *self.lines, self.credit, self.ask, self.site])


class CopyRefused(ValueError):
    pass


def cover(im: Image.Image, w: int, h: int, focus=(0.5, 0.42)) -> Image.Image:
    im = ImageOps.exif_transpose(im).convert("RGB")
    r = max(w / im.width, h / im.height)
    im2 = im.resize((max(w, round(im.width * r)), max(h, round(im.height * r))), Image.LANCZOS)
    x = round((im2.width - w) * focus[0])
    y = round((im2.height - h) * focus[1])
    return im2.crop((x, y, x + w, y + h))


def open_photo(src) -> Image.Image:
    if isinstance(src, Image.Image):
        return src.copy()
    im = Image.open(src)
    im.load()
    return im


def foot_gradient(w: int, h: int, start: float, strength: float, curve: float = 1.4) -> Image.Image:
    """An alpha mask: clear above `start` (share of height), darkening to `strength` at the bottom."""
    top = int(h * start)
    ramp = Image.linear_gradient("L").resize((1, max(1, h - top)))
    lut = [int(255 * strength * (i / 255) ** curve) for i in range(256)]
    mask = Image.new("L", (1, h), 0)
    mask.paste(ramp.point(lut), (0, top))
    return mask.resize((w, h))


def wrap(d, text: str, f, max_w: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and d.textlength(trial, font=f) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    return lines + [cur] if cur else lines


def fit(d, text: str, face: str, max_w: float, max_lines: int, start: int, floor: int):
    for size in range(start, floor - 1, -4):
        f = fonts.face(face, size)
        lines = wrap(d, text, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = fonts.face(face, floor)
    return f, wrap(d, text, f, max_w)


def pill(d, x: int, y: int, text: str, f, bg, fg, pad=(30, 18)) -> tuple[int, int]:
    tw = d.textlength(text, font=f)
    asc, desc = f.getmetrics()
    w, h = int(tw + 2 * pad[0]), int(asc + desc + 2 * pad[1] - desc * 0.6)
    d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=bg)
    d.text((x + pad[0], y + pad[1] - desc * 0.15), text, font=f, fill=fg)
    return w, h


def _check_copy(text: PostText, official: bool) -> None:
    report = copy_rules.check(text.all_text(), official=official)
    if not report.ok:
        raise CopyRefused(report.blocks[0].message)


def render(fmt: str, photos: Sequence, text: PostText, direction: Direction, *, aspect: str = "4:5",
           out: Path, official: bool = False, focus=(0.5, 0.42), meta: Optional["ImageMeta"] = None) -> Path:
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt}")
    _check_copy(text, official)
    w, h = SIZES[aspect]
    img = {"photo": _photo, "appearance": _appearance, "services": _services, "delivery": _delivery}[fmt](
        [open_photo(p) for p in photos], text, direction, w, h, focus)
    # saved fresh from pixels: no camera data, no GPS; only our own descriptive fields (render/meta.py)
    return save_jpeg(img, out, meta, quality=92)


# --------------------------------------------------------------------------- formats
def _photo(photos, text, b: Direction, w, h, focus):
    img = cover(photos[0], w, h, focus)
    shade = Image.new("RGB", (w, h), (8, 8, 10))
    img = Image.composite(shade, img, foot_gradient(w, h, 0.62, 0.78))
    d = ImageDraw.Draw(img)
    m = int(w * 0.06)
    kf = fonts.face(b.body_bold, int(w * 0.024))
    base = h - m
    if text.credit:
        cf = fonts.face(b.body, int(w * 0.026))
        d.text((m, base - int(w * 0.03)), text.credit, font=cf, fill=(235, 235, 235))
        base -= int(w * 0.05)
    if text.kicker:
        k = text.kicker.upper() if b.display_upper or True else text.kicker
        tracked(d, (m, base - int(w * 0.035)), k, kf, b.accent if b.key != "press" else b.paper, b.tracking)
        if b.key == "press":
            d.line([(m, base - int(w * 0.05)), (m + int(w * 0.07), base - int(w * 0.05))], fill=b.accent, width=3)
    mark_h = int(w * 0.03)
    tmp = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mw, mh = draw_mark(tmp, b, 0, 0, mark_h)
    img.paste(tmp.crop((0, 0, mw + 4, mh + 4)), (w - m - mw, h - m - mh), tmp.crop((0, 0, mw + 4, mh + 4)))
    return img


def _panel_text(img, d, text, b: Direction, x, y, max_w, bottom, *, headline_size, line_size, draw=True):
    """Kicker, headline and lines from (x, y). Returns the y it ended at. With draw=False it only measures."""
    kf = fonts.face(b.body_bold, max(24, int(headline_size * 0.3)))
    if draw:
        tracked(d, (x, y), text.kicker.upper(), kf, b.accent, b.tracking)
    y += int(headline_size * 0.62)
    head = text.headline.upper() if b.display_upper else text.headline
    hf, lines = fit(d, head, b.display, max_w, 3, headline_size, int(headline_size * 0.6))
    asc, desc = hf.getmetrics()
    lh = int((asc + desc) * (0.92 if b.display_upper else 1.02))
    for ln in lines:
        if draw:
            d.text((x, y), ln, font=hf, fill=b.paper)
        y += lh
    y += int(line_size * 0.6)
    lf = fonts.face(b.body, line_size)
    for ln in text.lines:
        for sub in wrap(d, ln, lf, max_w):
            if draw:
                d.text((x, y), sub, font=lf, fill=b.paper)
            y += int(line_size * 1.38)
    return y


def _fit_panel(img, d, text, b, x, y, max_w, limit, headline_size, line_size):
    """Shrink the panel's type until it ends above `limit`, then draw it."""
    # the headline gives way first; the reading lines only once the headline is down to 60%
    steps = [(hs / 100, 1.0) for hs in range(100, 59, -5)] + [(0.6, ls / 100) for ls in range(95, 59, -5)]
    hs, ls = steps[-1]
    for hs_, ls_ in steps:
        if _panel_text(img, d, text, b, x, y, max_w, limit, headline_size=int(headline_size * hs_),
                       line_size=max(18, int(line_size * ls_)), draw=False) <= limit:
            hs, ls = hs_, ls_
            break
    return _panel_text(img, d, text, b, x, y, max_w, limit, headline_size=int(headline_size * hs),
                       line_size=max(18, int(line_size * ls)))


def _ask_row(img, d, text, b: Direction, x, y, w, m):
    af = fonts.face(b.body_bold, int(w * 0.03))
    pw, ph = pill(d, x, y, text.ask, af, b.accent, b.on_accent)
    if text.site:
        sf = fonts.face(b.body, int(w * 0.026))
        d.text((x + pw + int(w * 0.03), y + ph // 2 - int(w * 0.017)), text.site, font=sf, fill=b.paper)
    mark_h = int(w * 0.026)
    tmp = Image.new("RGBA", img.size, (0, 0, 0, 0))
    mw, mh = draw_mark(tmp, b, 0, 0, mark_h)
    crop = tmp.crop((0, 0, mw + 4, mh + 4))
    img.paste(crop, (w - m - mw, y + (ph - mh) // 2), crop)
    return ph


def _appearance(photos, text, b: Direction, w, h, focus):
    img = Image.new("RGB", (w, h), b.ink)
    split = int(h * (0.52 if h / w > 1.3 else 0.5))
    img.paste(cover(photos[0], w, split, focus), (0, 0))
    d = ImageDraw.Draw(img)
    if b.key == "marquee":
        d.polygon([(0, split - int(h * 0.05)), (w, split), (0, split)], fill=b.ink)
    elif b.key == "press":
        d.rectangle([0, split, w, split + 6], fill=b.accent)
    else:
        d.rectangle([0, split - 8, int(w * 0.28), split], fill=b.accent)
    m = int(w * 0.075)
    y = split + int(h * 0.05)
    ask_y = h - m - int(w * 0.08)
    _fit_panel(img, d, text, b, m, y, w - 2 * m, ask_y - int(w * 0.05), int(w * 0.105), int(w * 0.032))
    _ask_row(img, d, text, b, m, ask_y, w, m)
    return img


def _services(photos, text, b: Direction, w, h, focus):
    img = Image.new("RGB", (w, h), b.ink)
    g = 8
    top_h = int(h * 0.44)
    cells = list(photos[:4]) or [Image.new("RGB", (10, 10), (60, 60, 60))]
    while len(cells) < 4:
        cells.append(cells[len(cells) % max(1, len(photos))])
    cw = (w - g) // 2
    ch = (top_h - g) // 2
    for i, p in enumerate(cells[:4]):
        img.paste(cover(p, cw, ch, focus), ((i % 2) * (cw + g), (i // 2) * (ch + g)))
    d = ImageDraw.Draw(img)
    m = int(w * 0.075)
    y = top_h + int(h * 0.045)
    kf = fonts.face(b.body_bold, int(w * 0.026))
    tracked(d, (m, y), text.kicker.upper(), kf, b.accent, b.tracking)
    y += int(w * 0.06)
    head = text.headline.upper() if b.display_upper else text.headline
    hf, lines = fit(d, head, b.display, w - 2 * m, 2, int(w * 0.085), int(w * 0.055))
    asc, desc = hf.getmetrics()
    for ln in lines:
        d.text((m, y), ln, font=hf, fill=b.paper)
        y += int((asc + desc) * 0.98)
    y += int(w * 0.025)
    col_w = (w - 2 * m) // 2
    rows = (len(text.lines) + 1) // 2
    limit = h - m - int(w * 0.08) - int(w * 0.04)
    for pct in range(31, 21, -1):           # the list shrinks until it clears the ask row
        lf = fonts.face(b.body, int(w * pct / 1000))
        line_h = int(w * pct / 1000 * 1.18)
        wrapped = [wrap(d, item, lf, col_w - int(w * 0.05))[:2] for item in text.lines]
        row_h = [max(len(wrapped[i]) for i in (r, r + rows) if i < len(wrapped)) * line_h + int(w * 0.022) for r in range(rows)]
        if y + sum(row_h) <= limit:
            break
    for i, sub in enumerate(wrapped):
        col, r = i // rows, i % rows
        cx = m + col * col_w
        cy = y + sum(row_h[:r])
        d.rectangle([cx, cy + int(w * 0.012), cx + int(w * 0.012), cy + int(w * 0.024)], fill=b.accent)
        for j, s_ in enumerate(sub):
            d.text((cx + int(w * 0.028), cy + j * line_h), s_, font=lf, fill=b.paper)
    _ask_row(img, d, text, b, m, h - m - int(w * 0.08), w, m)
    return img


def _delivery(photos, text, b: Direction, w, h, focus):
    img = cover(photos[0], w, h, focus)
    d = ImageDraw.Draw(img)
    m = int(w * 0.075)
    head = text.headline.upper() if b.display_upper else text.headline
    hf, lines = fit(d, head, b.display, w - 2 * m, 4, int(w * 0.095), int(w * 0.06))
    asc, desc = hf.getmetrics()
    lh = int((asc + desc) * (0.92 if b.display_upper else 1.02))
    lf = fonts.face(b.body, int(w * 0.032))
    body = [s for ln in text.lines for s in wrap(d, ln, lf, w - 2 * m)]
    block = int(w * 0.06) + len(lines) * lh + int(w * 0.03) + len(body) * int(w * 0.045)
    y = h - m - int(w * 0.11) - block
    start = max(0.0, (y - int(h * 0.28)) / h)
    img = Image.composite(Image.new("RGB", (w, h), b.ink), img, foot_gradient(w, h, start, 0.94, 0.55))
    d = ImageDraw.Draw(img)
    kf = fonts.face(b.body_bold, int(w * 0.026))
    tracked(d, (m, y), text.kicker.upper(), kf, b.accent if b.key == "marquee" else b.paper, b.tracking)
    y += int(w * 0.06)
    for ln in lines:
        d.text((m, y), ln, font=hf, fill=b.paper)
        y += lh
    y += int(w * 0.03)
    for s in body:
        d.text((m, y), s, font=lf, fill=b.paper)
        y += int(w * 0.045)
    _ask_row(img, d, text, b, m, h - m - int(w * 0.08), w, m)
    return img
