"""Brand directions: type, colour and the mark, as data plus one drawing function each.

Chris chose Lens on 2026-10-09, then on 2026-10-10 asked for black, greys and
white with a touch of cyan: the Viewfinder direction (BRAND_DIRECTION, default
viewfinder). The others stay for reference. Every
direction draws the company name from config, so a rename is one setting.

  press    editorial: a high-contrast serif wordmark, brass rule, navy and bone.
           Reads as conference and gala work.
  marquee  energy: an extra-condensed all-caps wordmark inside viewfinder
           corners, signal orange on black. Reads as fan convention work.
  lens     modern: a ring monogram with an aperture tick, cobalt on graphite.
           Sits between the two.
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from ..core import config
from . import fonts


@dataclass(frozen=True)
class Direction:
    key: str
    label: str
    ink: tuple            # dark ground
    paper: tuple          # light ground
    accent: tuple
    on_accent: tuple
    display: str          # headline face
    display_upper: bool
    body: str
    body_bold: str
    tracking: float       # extra space between capitals in small labels, as a share of the size


DIRECTIONS = {
    "press": Direction("press", "Press", ink=(14, 26, 43), paper=(243, 239, 230), accent=(176, 141, 87), on_accent=(14, 26, 43),
                       display="Fraunces-SemiBold.ttf", display_upper=False, body="InterTight-Regular.ttf",
                       body_bold="InterTight-SemiBold.ttf", tracking=0.18),
    "marquee": Direction("marquee", "Marquee", ink=(11, 11, 13), paper=(246, 245, 241), accent=(255, 77, 28), on_accent=(11, 11, 13),
                         display="Archivo-XCondBlack.ttf", display_upper=True, body="Archivo-CondMedium.ttf",
                         body_bold="Archivo-XCondBlack.ttf", tracking=0.12),
    # Chris, 2026-10-10: black, greys and white with a touch of cyan; the Viewfinder mark
    "viewfinder": Direction("viewfinder", "Viewfinder", ink=(10, 10, 11), paper=(243, 243, 241), accent=(0, 225, 255),
                            on_accent=(10, 10, 11), display="Michroma-Regular.ttf", display_upper=True,
                            body="InterTight-Regular.ttf", body_bold="JetBrainsMono-Medium.ttf", tracking=0.16),
    "lens": Direction("lens", "Lens", ink=(27, 29, 34), paper=(233, 236, 242), accent=(47, 91, 255), on_accent=(255, 255, 255),
                      display="SpaceGrotesk-Bold.ttf", display_upper=False, body="SpaceGrotesk-Medium.ttf",
                      body_bold="SpaceGrotesk-Bold.ttf", tracking=0.14),
}
TAGLINE = "Event and convention photography"


def current() -> Direction | None:
    key = (config.getenv("BRAND_DIRECTION") or "viewfinder").strip().lower()   # Chris, 2026-10-10: mono with a touch of cyan
    return DIRECTIONS.get(key)


def tracked(d: ImageDraw.ImageDraw, xy, text: str, f, fill, tracking: float) -> float:
    """Draw letter-spaced text; return the x where it ended."""
    x, y = xy
    size = getattr(f, "size", 12)
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + tracking * size
    return x


def tracked_width(d, text: str, f, tracking: float) -> float:
    size = getattr(f, "size", 12)
    return sum(d.textlength(c, font=f) for c in text) + tracking * size * max(0, len(text) - 1)


def draw_mark(img: Image.Image, direction: Direction, x: int, y: int, height: int, *, on_dark: bool = True,
              with_tagline: bool = False) -> tuple[int, int]:
    """The company mark at (x, y), `height` tall (the wordmark's cap zone). Returns (width, height) drawn."""
    d = ImageDraw.Draw(img)
    name = config.get_config().brand_name
    fg = direction.paper if on_dark else direction.ink
    if direction.key == "press":
        f = fonts.face(direction.display, int(height * 1.25))
        d.text((x, y), name, font=f, fill=fg)
        w = int(d.textlength(name, font=f))
        rule_y = y + int(height * 1.55)
        d.line([(x, rule_y), (x + int(height * 1.2), rule_y)], fill=direction.accent, width=max(2, height // 18))
        h = rule_y - y
        if with_tagline:
            tf = fonts.face(direction.body_bold, max(10, int(height * 0.34)))
            tracked(d, (x, rule_y + int(height * 0.3)), TAGLINE.upper(), tf, fg, direction.tracking)
            h += int(height * 0.8)
        return w, h
    if direction.key == "viewfinder":
        # four corner brackets with a cyan focus point, then EVENT in grey over CALIBER (site/marks.py draws the same)
        s = int(height * 1.6)
        lw = max(2, height // 12)
        arm = int(s * 0.2)
        for cx, cy, sx, sy in ((x, y, 1, 1), (x + s, y, -1, 1), (x, y + s, 1, -1), (x + s, y + s, -1, -1)):
            d.line([(cx, cy), (cx + sx * arm, cy)], fill=fg, width=lw)
            d.line([(cx, cy), (cx, cy + sy * arm)], fill=fg, width=lw)
        r = max(3, int(s * 0.055))
        fx, fy = x + int(s * 0.64), y + int(s * 0.36)
        d.ellipse([fx - r, fy - r, fx + r, fy + r], fill=direction.accent)
        first, _, rest = name.upper().partition(" ")
        f = fonts.face(direction.display, max(10, int(height * 0.5)))
        tx = x + s + int(height * 0.5)
        tracked(d, (tx, y + int(height * 0.2)), first, f, (140, 140, 147), 0.22)
        tracked(d, (tx, y + int(height * 0.88)), rest or first, f, fg, 0.22)
        w = int(tx - x + max(tracked_width(d, first, f, 0.22), tracked_width(d, rest or first, f, 0.22)))
        h = s
        if with_tagline:
            tf = fonts.face(direction.body_bold, max(10, int(height * 0.34)))
            tracked(d, (x, y + s + int(height * 0.5)), TAGLINE.upper(), tf, fg, direction.tracking)
            h += int(height * 0.9)
        return w, h
    if direction.key == "marquee":
        f = fonts.face(direction.display, int(height * 1.35))
        text = name.upper()
        tw = int(tracked_width(d, text, f, 0.02))
        pad = int(height * 0.38)
        box = (x, y, x + tw + 2 * pad, y + int(height * 1.6) + pad)
        arm, lw = int(height * 0.42), max(3, height // 11)
        for cx, cy, sx, sy in ((box[0], box[1], 1, 1), (box[2], box[1], -1, 1), (box[0], box[3], 1, -1), (box[2], box[3], -1, -1)):
            d.line([(cx, cy), (cx + sx * arm, cy)], fill=direction.accent, width=lw)
            d.line([(cx, cy), (cx, cy + sy * arm)], fill=direction.accent, width=lw)
        tracked(d, (x + pad, y + int(pad * 0.55)), text, f, fg, 0.02)
        dot = max(6, height // 6)
        d.ellipse([box[2] - pad // 2 - dot, box[1] + pad // 2, box[2] - pad // 2, box[1] + pad // 2 + dot], fill=direction.accent)
        w, h = box[2] - box[0], box[3] - box[1]
        if with_tagline:
            tf = fonts.face(direction.body, max(10, int(height * 0.4)))
            tracked(d, (x, box[3] + int(height * 0.35)), TAGLINE.upper(), tf, fg, direction.tracking)
            h += int(height * 0.9)
        return w, h
    # lens: ring monogram + lowercase wordmark
    r = int(height * 0.95)
    lw = max(3, height // 12)
    cx, cy = x + r, y + r
    d.ellipse([x, y, x + 2 * r, y + 2 * r], outline=direction.accent, width=lw)
    tick = int(r * 0.32)
    d.line([(cx + int(r * 0.62), cy - int(r * 0.62)), (cx + int(r * 0.62) + tick // 2, cy - int(r * 0.62) - tick // 2)],
           fill=direction.accent, width=lw)
    initials = "".join(w[0] for w in name.split()[:2]).upper()
    mf = fonts.face(direction.display, int(r * 0.9))
    iw = d.textlength(initials, font=mf)
    asc, desc = mf.getmetrics()
    d.text((cx - iw / 2, cy - (asc + desc) / 2 + desc * 0.15), initials, font=mf, fill=fg)
    wf = fonts.face(direction.display, int(height * 0.95))
    tx = x + 2 * r + int(height * 0.45)
    d.text((tx, cy - int(height * 0.62)), name.lower(), font=wf, fill=fg)
    w = int(tx - x + d.textlength(name.lower(), font=wf))
    h = 2 * r
    if with_tagline:
        tf = fonts.face(direction.body, max(10, int(height * 0.34)))
        tracked(d, (tx, cy + int(height * 0.42)), TAGLINE.upper(), tf, fg, direction.tracking)
    return w, h
