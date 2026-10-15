"""Four bold post designs, flat and graphic, so the feed is not the same dark stage of cards every day.

Chris, 2026-10-15: "could you also come up with some new designs (like 4 so they arent all exactly the same
design everytime) and make sure you follow strict color theory and proper design and make them super super super
dynamic and punchy". The motion set (render/motion.py) is one look: near black, photos as cards in depth, Unbounded
with a cyan ghost. These four are its opposite in every way that shows in a feed: the photo whole and large, flat
colour taken from the photo, type on a strict grid, and each with its own rhythm and its own pair of brand typefaces.
On the first renders he kept three ("i like the design of 7,8,9 and 10") and asked for "one more thats radically
different with a new technique use"; on round 2: "perfect!".

  poster   type first: the room's name stacked word by word, each line set to the full width, on paper; the
           photo whole under it on a black block; black and white, as he picked     Unbounded, JetBrains Mono
  scan     slit scan, the new technique: the photo whole, its most colourful line of pixels drawn out into
           light streaks above and below it, the words on black tape                Unbounded, Inter Tight
  cascade  three photos whole on a staircase down the frame, the smallest first and the hero last and largest,
           a band of the set's split complementary colour running behind them      Michroma, JetBrains Mono
  select   the photographer's pick: the hero whole and large, every photo of the set whole on a contact strip
           under it with the pick boxed in the set's triadic colour                Michroma, Inter Tight

The rules every one keeps:
- Every photo is whole, its own shape, never cropped and never covered (Chris, 2026-10-14: "the horizontal images
  must not be cropped anywhere on any device"; on the site only the hero may be). The photo is shown as shot:
  nothing is drawn on it, nothing is graded.
- Colour (render/palette.py): the brand's black, greys and white and the cyan of the mark, plus one accent taken
  from the photo by the design's rule; every word is checked for WCAG contrast against the flat colour under it
  before it is drawn, and a palette that fails is dropped for the brand's black and white.
- Type: two families per design (the mark is the logo, not type), every word inside the frame, every letter one
  its typeface has; no word is ever set over a photo.
- The words are the cards' own (motion.MotionCopy and each Shot's room and line, the same path as the motion set)
  and pass ai.copy_rules first, as social copy. A room is named only when the final check confirmed it
  (agents/content.confirmed_rooms).
- 4:5 for Instagram and 2:3 for Pinterest, the same design at both sizes.

In the week since 2026-10-15 (agents/content.py DESIGNS), beside the spotlight he kept.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image, ImageDraw, ImageOps

from . import fonts
from . import palette as pal
from .brand import draw_mark
from .edge import APERTURE, check_copy
from .meta import ImageMeta, save_jpeg
from .motion import MotionCopy, Shot
from .palette import Clipped, ContrastError, Palette, Setter
from .posts import wrap

SIZES = {"4:5": (1080, 1350), "2:3": (1000, 1500)}
UNBOUNDED, INTER, INTER_SEMI, MONO, MICHROMA = ("Unbounded-ExtraBold.ttf", "InterTight-Regular.ttf",
                                                "InterTight-SemiBold.ttf", "JetBrainsMono-Medium.ttf",
                                                "Michroma-Regular.ttf")
FAMILY = {UNBOUNDED: "Unbounded", INTER: "Inter Tight", INTER_SEMI: "Inter Tight", MONO: "JetBrains Mono",
          MICHROMA: "Michroma"}
PICK = "PICK"                         # the label on the boxed frame of the select design


@dataclass(frozen=True)
class Design:
    name: str
    rule: str                         # how the accent is turned from the photo's hue (render/palette.py)
    lightness: float                  # the accent's OKLab lightness
    dark: bool                        # black ground (True) or paper
    faces: tuple                      # the typefaces it sets words in
    needs: int                        # fewest photos
    takes: int                        # most photos
    what: str


DESIGNS = {
    "poster": Design("poster", "black and white", 0.0, False, (UNBOUNDED, MONO), 1, 1,
                     "type first on paper, in black: the room's name stacked to the full width, the photo whole under it"),
    "cascade": Design("cascade", "split", 0.76, True, (MICHROMA, MONO), 3, 3,
                      "three photos whole on a staircase, the hero last and largest, a band of colour behind"),
    "select": Design("select", "triadic", 0.80, True, (MICHROMA, INTER, INTER_SEMI), 4, 6,
                     "the pick: the hero whole and large over a contact strip of the set, the pick boxed"),
    "scan": Design("scan", "the photo's own", 0.0, True, (UNBOUNDED, INTER, INTER_SEMI), 1, 1,
                   "slit scan: the photo whole, its most colourful line of pixels drawn out into streaks above "
                   "and below it, the words on black tape over them"),
}
# the rules that add no accent of their own: the palette is the brand's black and white
NO_ACCENT = ("black and white", "the photo's own")


@dataclass
class Made:
    """One render before it is saved: the picture, the palette it was drawn in, every word it set, and, when the
    photo's own palette failed a contrast check, why (the post is then in the brand's black and white)."""
    image: Image.Image
    palette: Palette
    words: list
    photos: list                      # where each photo landed, (x0, y0, x1, y1), in the order handed in
    fell_back: str = ""


# ------------------------------------------------------------------------------------------------ the photo
def picture(shot: Shot, longest: int = 2400) -> Image.Image:
    """The photo as shot, upright, in RGB, no larger than it needs to be. A shot without a photo is a plain grey
    plate (a placeholder in tests, never a made up picture)."""
    src = shot.photo
    if src is None:
        return Image.new("RGB", (1500, 1000), (70, 70, 76))
    if isinstance(src, Image.Image):
        im = src
    else:
        im = Image.open(src)
        im.draft("RGB", (longest, longest))
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > longest:
        im = im.copy()
        im.thumbnail((longest, longest), Image.LANCZOS, reducing_gap=3.0)
    return im


def whole(im: Image.Image, w: int, h: int) -> Image.Image:
    """The whole photo at w x h. The caller takes w and h from the photo's own shape, so nothing is cut: a
    rounding pixel at most."""
    if abs(w / h - im.width / im.height) > 0.02:
        raise ValueError(f"{w}x{h} is not the photo's shape ({im.width}x{im.height}); a photo is never cropped here")
    return im.resize((w, h), Image.LANCZOS, reducing_gap=3.0)


def fit_box(ar: float, max_w: float, max_h: float) -> tuple[int, int]:
    """The largest w x h of aspect `ar` inside max_w x max_h."""
    w = min(max_w, max_h * ar)
    return max(1, round(w)), max(1, round(w / ar))


def place(img: Image.Image, im: Image.Image, x: float, y: float, w: int, h: int) -> tuple:
    img.paste(whole(im, w, h), (round(x), round(y)))
    return (round(x), round(y), round(x) + w, round(y) + h)


# ------------------------------------------------------------------------------------------------ type
def face(name: str, size: float):
    return fonts.face(name, max(8, int(size)))


def cap(f) -> int:
    return -f.getbbox("H", anchor="ls")[1]


def splits(text: str, most: int) -> list[list[str]]:
    """Every way to set `text` on one line up to `most` lines, breaking only between words."""
    words = text.split()
    if most <= 1 or len(words) <= 1:
        return [[" ".join(words)]]
    out = [[" ".join(words)]]
    for i in range(1, len(words)):
        out += [[" ".join(words[:i])] + rest for rest in splits(" ".join(words[i:]), most - 1)]
    return out


def title(st: Setter, text: str, name: str, max_w: float, max_h: float, start: float, floor: float, *,
          most: int = 2, lead: float = 1.0) -> tuple:
    """The largest setting of `text` in `name` that fits max_w x max_h: (font, lines). Never below `floor`: a
    title that cannot fit is refused (Clipped), never cut."""
    return setting(st, splits(text, most), name, max_w, max_h, start, floor, lead=lead, what=text)


def setting(st: Setter, options: Sequence[Sequence[str]], name: str, max_w: float, max_h: float, start: float,
            floor: float, *, lead: float = 1.0, what: str = "") -> tuple:
    """Of several ways to break the same words into lines, the one that sets them largest inside max_w x max_h."""
    best = None
    for lines in options:
        lines = list(lines)
        lo, hi = int(floor), int(start)
        while lo <= hi:
            mid = (lo + hi) // 2
            f = face(name, mid)
            tall = cap(f) + (len(lines) - 1) * mid * lead
            if all(st.width(t, f) <= max_w for t in lines) and tall <= max_h:
                if best is None or mid > best[0].size:
                    best = (f, lines)
                lo = mid + 1
            else:
                hi = mid - 1
    if best is None:
        raise Clipped(f"{what!r} does not fit {max_w:.0f} x {max_h:.0f} at {floor:.0f} px")
    return best


def reading(st: Setter, text: str, name: str, max_w: float, size: float, floor: float, most: int = 2) -> tuple:
    """A sentence wrapped to max_w in no more than `most` lines, the size coming down to `floor` if it must."""
    s = int(size)
    while s >= floor:
        f = face(name, s)
        lines = wrap(st.d, text, f, max_w)
        if len(lines) <= most and all(st.width(t, f) <= max_w for t in lines):
            return f, lines
        s -= 2
    raise Clipped(f"{text!r} does not fit {most} lines of {max_w:.0f} px")


def mark(img: Image.Image, x: float, y: float, height: float, on_dark: bool, right: bool = False) -> tuple:
    """The company's mark at (x, y), or ending at x when `right`; only ever on the brand's black or paper."""
    layer = Image.new("RGBA", (int(height * 12), int(height * 4)), (0, 0, 0, 0))
    mw, mh = draw_mark(layer, APERTURE, 0, 0, int(height), on_dark=on_dark)
    crop = layer.crop((0, 0, mw + 4, mh + 4))
    px = int(x - mw) if right else int(x)
    img.paste(crop, (px, int(y)), crop)
    return px, int(y), px + mw, int(y) + mh


def ask_block(st: Setter, x: float, y: float, text: str, name: str, size: float, p: Palette, *,
              tracking: float = 0.08, pad: tuple = (26, 20)) -> tuple:
    """The ask as a solid block of the accent with its words in black or white. Returns its box."""
    f = face(name, size)
    label = text.upper() + "  ↗"
    tw = st.width(label, f, tracking)
    px, py = pad[0] * st.scale, pad[1] * st.scale
    box = (x, y, x + tw + 2 * px, y + cap(f) + 2 * py)
    st.d.rectangle(box, fill=p.accent)
    st.text((x + px, y + py + cap(f)), label, f, p.on_accent, p.accent, tracking=tracking)
    return box


# ------------------------------------------------------------------------------------------------ poster
def _poster(shots, ims, copy: MotionCopy, w, h, p: Palette) -> Made:
    """Type first: the room's name set word by word, each line as wide as the frame allows; the photo whole under
    it, set on a block of the accent stepped down and to the right; the ask a block of the accent at the foot."""
    shot, im = shots[0], ims[0]
    s = w / 1080
    img = Image.new("RGB", (w, h), p.ground)
    st = Setter(img, s)
    m = 64 * s
    mk = mark(img, m, m, 30 * s, False)
    kf = face(MONO, 22 * s)
    st.text((w - m, mk[3] - (mk[3] - mk[1]) / 2 + cap(kf) / 2), copy.kicker, kf, p.ink, p.ground, tracking=0.16,
            anchor="rs")
    # the foot: the ask and the address
    af = face(MONO, 26 * s)
    ask_h = cap(af) + 40 * s
    ab = ask_block(st, m, h - m - ask_h, copy.ask, MONO, 26 * s, p)
    sf = face(MONO, 20 * s)
    if ab[2] + 30 * s + st.width(copy.site, sf, 0.1) <= w - m:
        st.text((w - m, ab[3] - (ask_h - cap(sf)) / 2), copy.site, sf, p.ink, p.ground, tracking=0.1, anchor="rs")
    # measure the name at its full size (each word as wide as the frame, up to 330 px) and the line
    words = shot.room.split()
    gap = 16 * s
    sizes = []
    for wd in words:
        lo, hi = int(40 * s), int(330 * s)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if st.width(wd, face(UNBOUNDED, mid)) <= w - 2 * m else (lo, mid - 1)
        sizes.append(lo)
    caps = [cap(face(UNBOUNDED, z)) for z in sizes]
    lf, lines = reading(st, shot.line.upper(), MONO, w - 2 * m, 24 * s, 18 * s)
    line_h = 40 * s + (len(lines) - 1) * lf.size * 1.45 + cap(lf) + 26 * s
    # the photo: whole, on its block of the accent, as large as the name leaves room for: 40% of the frame's
    # height at least, half at most
    off = 22 * s
    ar = im.width / im.height
    left = ab[1] - 48 * s - off - (mk[3] + 56 * s) - sum(caps) - gap * (len(words) - 1) - line_h
    pw, ph = fit_box(ar, w - 2 * m - off, max(h * 0.40, min(h * 0.5, left)))
    px, py = m, ab[1] - 48 * s - off - ph
    st.d.rectangle([px + off, py + off, px + pw + off, py + ph + off], fill=p.accent)
    spot = place(img, im, px, py, pw, ph)
    # the line, in the mono, over the photo
    y = py - 40 * s
    for t in reversed(lines):
        st.text((m, y), t, lf, p.ink, p.ground, tracking=0.06)
        y -= lf.size * 1.45
    # the name: each word its own line, each line set to the full width, the last line in the accent
    top, bottom = mk[3] + 56 * s, y - 26 * s
    room = bottom - top - gap * (len(words) - 1)
    k = min(1.0, room / sum(caps))
    if k * min(sizes) < 40 * s:
        raise Clipped(f"{shot.room!r} has no room on the poster")
    fs = [face(UNBOUNDED, int(z * k)) for z in sizes]
    y = bottom - sum(cap(f) for f in fs) - gap * (len(fs) - 1)       # set from the foot up, so the name sits on the line
    for i, (wd, f) in enumerate(zip(words, fs)):
        y += cap(f)
        last = i == len(words) - 1 and len(words) > 1
        st.text((m - f.size * 0.03, y), wd, f, p.accent if last else p.ink, p.ground)
        y += gap
    return Made(img, p, st.words, [spot])


# ------------------------------------------------------------------------------------------------ cascade
def _cascade(shots, ims, copy: MotionCopy, w, h, p: Palette) -> Made:
    """Three photos whole, stepping down the frame from the top left to the bottom right, each larger than the
    last, the hero last; a band of the accent runs behind them along the step. The hook across the top, each room
    on a black tab beside its photo, the ask in the space the step leaves at the bottom left."""
    s = w / 1080
    img = Image.new("RGB", (w, h), p.ground)
    st = Setter(img, s)
    m = 56 * s
    n = len(ims)
    order = list(range(1, n)) + [0]                                   # the hero (handed in first) lands last and largest
    acc_text = p.accent if not p.fallback else pal.W
    # the hook across the top: each of its lines whole or broken once, whichever sets it largest
    kf = face(MONO, 20 * s)
    options = [sum(c, []) for c in itertools.product(*(splits(t, 2) for t in copy.hook))]
    hf, head = setting(st, options, MICHROMA, w - 2 * m, 220 * s, 76 * s, 34 * s, lead=1.25, what=" ".join(copy.hook))
    top = m + cap(kf) + 30 * s + cap(hf) + hf.size * 1.25 * (len(head) - 1) + 56 * s
    # the step: as wide as the frame's height allows, leaving the ask its full size beside the hero
    ars = [ims[k].width / ims[k].height for k in order]
    grow = [0.74 + 0.26 * i / max(1, n - 1) for i in range(n)]       # the widths step up to the hero's
    gap = 22 * s
    af = face(MONO, 24 * s)
    ask_w = st.width(copy.ask.upper() + "  ↗", af, 0.08) + 52 * s
    room = h - m - top
    hw = min((w - 2 * m) * 0.7, w - 2 * m - 40 * s - ask_w, (room - gap * (n - 1)) / sum(g / a for g, a in zip(grow, ars)))
    heights = [round(hw * g / a) for g, a in zip(grow, ars)]
    gap = min(64 * s, (room - sum(heights)) / max(1, n - 1))           # height to spare opens the step out
    boxes, y = [], top + (room - sum(heights) - gap * (n - 1)) / 2
    for i, (g, ph) in enumerate(zip(grow, heights)):
        pw = round(hw * g)
        x = m + (w - 2 * m - pw) * (i / max(1, n - 1))
        boxes.append((round(x), round(y), round(x) + pw, round(y) + ph))
        y += ph + gap
    # the band: through the first and last photos' centres, 60% of the hero wide, from edge to edge
    (x0, y0), (x1, y1) = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for b in (boxes[0], boxes[-1])]
    ang = math.atan2(y1 - y0, x1 - x0)
    half = (boxes[-1][2] - boxes[-1][0]) * 0.3
    nx, ny = -math.sin(ang) * half, math.cos(ang) * half
    ux, uy = math.cos(ang) * (w + h), math.sin(ang) * (w + h)
    st.d.polygon([(x0 - ux + nx, y0 - uy + ny), (x1 + ux + nx, y1 + uy + ny), (x1 + ux - nx, y1 + uy - ny),
                  (x0 - ux - nx, y0 - uy - ny)], fill=p.accent)
    spots = {}
    for b, k in zip(boxes, order):
        spots[k] = place(img, ims[k], b[0], b[1], b[2] - b[0], b[3] - b[1])
    # the hook, on the black over the band's top end
    st.d.rectangle([0, 0, w, top - 28 * s], fill=pal.K)
    y = m + cap(kf)
    st.text((m, y), copy.kicker, kf, acc_text, pal.K, tracking=0.18)
    y += 30 * s + cap(hf)
    for t in head:
        st.text((m - hf.size * 0.02, y), t, hf, pal.W, pal.K)
        y += hf.size * 1.25
    # each room on a black tab beside its photo, on the side with more room: its number over its name
    tabs = []
    for i, (b, k) in enumerate(zip(boxes, order)):
        num, name = f"{i + 1:02d}", shots[k].room
        right = (w - m - b[2]) >= (b[0] - m)
        side = max(w - m * 0.5 - b[2], b[0] - m * 0.5) - 14 * s - 24 * s      # the widest the words may be beside the photo
        # its number over its name; a long name breaks between words, then comes down in size (never below 16 px)
        for size in range(round(21 * s), round(16 * s) - 1, -1):
            lab = face(MONO, size)
            lines = next((ls for ls in splits(name, 3) if all(st.width(t, lab, 0.14) <= side for t in ls)), None)
            if lines:
                break
        else:
            raise Clipped(f"the tab for {name!r} has no room beside its photo")
        rows = [num, *lines]
        tw = max(st.width(t, lab, 0.14) for t in rows) + 24 * s
        th = len(rows) * cap(lab) + (len(rows) - 1) * 10 * s + 24 * s
        tx = b[2] + 14 * s if right else b[0] - 14 * s - tw
        st.d.rectangle([tx, b[1], tx + tw, b[1] + th], fill=pal.K)
        y = b[1] + 12 * s
        for j, t in enumerate(rows):
            y += cap(lab)
            st.text((tx + 12 * s, y), t, lab, acc_text if j == 0 else pal.W, pal.K, tracking=0.14)
            y += 10 * s
        tabs.append((tx, b[1], tx + tw, b[1] + th))
    # the ask in the bottom left, clear of the hero, with the mark and the address over it
    last = boxes[-1]
    room_r = last[0] - 40 * s
    ask_h = cap(af) + 40 * s
    ab = ask_block(st, m, last[3] - ask_h, copy.ask, MONO, 24 * s, p)
    sf = face(MONO, 18 * s)
    plate_top = ab[1] - 118 * s
    st.d.rectangle([m - 12 * s, plate_top, room_r, ab[1] - 6 * s], fill=pal.K)
    mark(img, m, plate_top + 10 * s, 28 * s, True)
    st.text((m, ab[1] - 26 * s), copy.site, sf, pal.G5, pal.K, tracking=0.12)
    if ab[2] > room_r + 1 or (plate_top < tabs[-1][3] + 8 * s and tabs[-1][0] < room_r):
        raise Clipped("the ask runs into the hero or its tab")
    return Made(img, p, st.words, [spots[k] for k in range(n)])


# ------------------------------------------------------------------------------------------------ select
def _select(shots, ims, copy: MotionCopy, w, h, p: Palette, index: int = 0) -> Made:
    """The pick: the hero whole and large, a contact strip of every photo of the set whole under it, the hero's
    frame boxed in the accent with a tick up to the enlargement; its number, its room and its line; the ask.
    Everything is measured first and the stack is centred over the ask."""
    s = w / 1080
    img = Image.new("RGB", (w, h), p.ground)
    st = Setter(img, s)
    m = 56 * s
    n = len(ims)
    hero, him = shots[index], ims[index]
    acc_text = p.accent if not p.fallback else pal.W
    # the foot: the ask, the address, the mark
    af = face(INTER_SEMI, 26 * s)
    ask_h = cap(af) + 40 * s
    ab = ask_block(st, m, h - m - ask_h, copy.ask, INTER_SEMI, 26 * s, p, tracking=0.1)
    sf = face(INTER, 22 * s)
    mk = mark(img, w - m, ab[1] + ask_h / 2 - 26 * s, 28 * s, True, right=True)
    if ab[2] + 26 * s + st.width(copy.site, sf) < mk[0] - 26 * s:
        st.text((ab[2] + 26 * s, ab[1] + ask_h / 2 + cap(sf) / 2), copy.site, sf, pal.G5, pal.K)
    # measure: the strip, the numbers, the kicker, the room, the line
    g = 12 * s
    ars = [im.width / im.height for im in ims]
    th = min(0.11 * h, (w - 2 * m - g * (n - 1)) / sum(ars))
    widths = [round(th * a) for a in ars]
    nf, kf = face(INTER_SEMI, 18 * s), face(INTER_SEMI, 20 * s)
    lf, lines = reading(st, hero.line, INTER, w - 2 * m, 34 * s, 24 * s)
    tf, tl = title(st, hero.room, MICHROMA, w - 2 * m, 240 * s, 112 * s, 40 * s, most=2, lead=1.15)
    below = (46 * s + th + 12 * s + cap(nf) + 44 * s + cap(kf) + 30 * s + cap(tf) + (len(tl) - 1) * tf.size * 1.15
             + 20 * s + len(lines) * lf.size * 1.32)
    space = ab[1] - 44 * s - m
    pw, ph = fit_box(ars[index], w - 2 * m, space - below)
    y = m + (space - ph - below) / 2
    # the hero, whole
    hero_box = place(img, him, (w - pw) / 2, y, pw, ph)
    # the strip, every photo whole at one height, its numbers under it
    y = hero_box[3] + 46 * s
    x = (w - sum(widths) - g * (n - 1)) / 2
    spots = []
    for i, (im, tw_) in enumerate(zip(ims, widths)):
        spots.append(place(img, im, x, y, tw_, round(th)))
        st.text((x, y + th + 12 * s + cap(nf)), f"{i + 1:02d}", nf, acc_text if i == index else pal.G4, p.ground,
                tracking=0.1)
        x += tw_ + g
    # N°, the room, the line
    y += th + 12 * s + cap(nf) + 44 * s + cap(kf)
    st.text((m, y), f"N°{index + 1:02d} / {n:02d}  ·  {copy.kicker}", kf, acc_text, p.ground, tracking=0.16)
    y += 30 * s + cap(tf)
    for i, t in enumerate(tl):
        st.text((m - tf.size * 0.02, y), t, tf, p.ink, p.ground)
        if i < len(tl) - 1:
            y += tf.size * 1.15
    y += 20 * s
    for t in lines:
        y += lf.size * 1.32
        st.text((m, y), t, lf, p.quiet, p.ground)
    if y > ab[1] - 30 * s:
        raise Clipped("the line runs into the ask")
    # the pick: the frame boxed in the accent, a tick from the box up to the enlargement, the hero's corners marked
    b = spots[index]
    o, lw = 7 * s, max(3, round(5 * s))
    st.d.rectangle([b[0] - o, b[1] - o, b[2] + o, b[3] + o], outline=acc_text, width=lw)
    cx = (b[0] + b[2]) / 2
    st.d.line([(cx, b[1] - o), (cx, hero_box[3] + 12 * s)], fill=acc_text, width=lw)
    arm, e = 46 * s, 12 * s
    for (ex, ey, sx, sy) in ((hero_box[0] - e, hero_box[1] - e, 1, 1), (hero_box[2] + e, hero_box[1] - e, -1, 1),
                             (hero_box[0] - e, hero_box[3] + e, 1, -1), (hero_box[2] + e, hero_box[3] + e, -1, -1)):
        st.d.line([(ex, ey), (ex + sx * arm, ey)], fill=acc_text, width=lw)
        st.d.line([(ex, ey), (ex, ey + sy * arm)], fill=acc_text, width=lw)
    return Made(img, p, st.words, spots)


# ------------------------------------------------------------------------------------------------ scan
FADE = 0.12                           # the streaks' brightness at the frame's edge, against 1 at the photo


def slit(im: Image.Image, across: bool) -> int:
    """The photo's most colourful line by mean OKLab chroma: a row (across) or a column, from 20% to 80% of the way
    in, so it runs through the subject. Its index in the photo's own pixels."""
    small = im.copy()
    small.thumbnail((200, 200), Image.BILINEAR)
    px, (sw, sh) = small.load(), small.size
    n = sh if across else sw
    best, pick = -1.0, n // 2
    for i in range(int(n * 0.2), int(n * 0.8) + 1):
        line = [px[x, i] for x in range(sw)] if across else [px[i, y] for y in range(sh)]
        c = sum(math.hypot(*pal.oklab(v)[1:]) for v in line) / len(line)
        if c > best:
            best, pick = c, i
    return min((im.height if across else im.width) - 1, int((pick + 0.5) / n * (im.height if across else im.width)))


def streaks(line: Image.Image, w: int, h: int, away: str) -> Image.Image:
    """One line of the photo drawn out to w x h, at full strength next to the photo and fading toward black away
    from it (`away`: up, down, left or right)."""
    out = line.resize((w, h), Image.BILINEAR)
    ramp = Image.linear_gradient("L").point(lambda v: int(255 * (FADE + (1 - FADE) * (v / 255) ** 1.7)))
    ramp = {"up": ramp, "down": ramp.transpose(Image.FLIP_TOP_BOTTOM), "left": ramp.transpose(Image.ROTATE_270),
            "right": ramp.transpose(Image.ROTATE_90)}[away].resize((w, h))
    return Image.composite(out, Image.new("RGB", (w, h), pal.K), ramp)


def tape(st: Setter, box, keep_off: Sequence[tuple]) -> tuple:
    """A strip of black tape for words to sit on over the streaks; never over the photo."""
    for b in keep_off:
        if box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3]:
            raise Clipped("a strip of tape runs over the photo")
    st.d.rectangle(box, fill=pal.K)
    return box


def _scan(shots, ims, copy: MotionCopy, w, h, p: Palette) -> Made:
    """Slit scan: the photo whole; its most colourful line of pixels drawn out into streaks from the photo to the
    frame's edges, fading to black, like light caught by a moving slit. A wide photo streaks up and down from a row,
    a tall one left and right from a column. The words on strips of black tape over the streaks."""
    shot, im = shots[0], ims[0]
    s = w / 1080
    img = Image.new("RGB", (w, h), pal.K)
    st = Setter(img, s)
    m = 60 * s
    gap = round(10 * s)
    ar = im.width / im.height
    if ar >= 1.0:
        pw, ph = fit_box(ar, w, h * 0.56)
        px, py = round((w - pw) / 2), round((h - ph) * 0.6)
        r = slit(im, across=True)
        line = im.crop((0, r, im.width, r + 1)).resize((pw, 1), Image.LANCZOS)
        img.paste(streaks(line, pw, py - gap, "up"), (px, 0))
        img.paste(streaks(line, pw, h - py - ph - gap, "down"), (px, py + ph + gap))
        top_end, low_start = py - gap, py + ph + gap
    else:
        pw, ph = fit_box(ar, w * 0.62, h * 0.62)
        px, py = round((w - pw) / 2), round((h - ph) * 0.55)
        c = slit(im, across=False)
        line = im.crop((c, 0, c + 1, im.height)).resize((1, ph), Image.LANCZOS)
        img.paste(streaks(line, px - gap, ph, "left"), (0, py))
        img.paste(streaks(line, w - px - pw - gap, ph, "right"), (px + pw + gap, py))
        top_end, low_start = py - gap, py + ph + gap
    spot = place(img, im, px, py, pw, ph)
    pad = 14 * s
    # the top: the kicker and the room's name, each line on its own tape
    kf = face(INTER_SEMI, 24 * s)
    y = m + cap(kf)
    kw = st.width(copy.kicker, kf, 0.2)
    tape(st, (m - pad, y - cap(kf) - pad, m + kw + pad, y + pad), [spot])
    st.text((m, y), copy.kicker, kf, pal.W, pal.K, tracking=0.2)
    y += pad + 26 * s
    tf, tl = title(st, shot.room, UNBOUNDED, w - 2 * m - 2 * pad, top_end - 18 * s - y - 2 * pad, 170 * s, 48 * s,
                   most=2, lead=1.12)
    y += pad + cap(tf)
    for t in tl:
        tw = st.width(t, tf)
        tape(st, (m - pad, y - cap(tf) - pad, m + tw + pad, y + pad), [spot])
        st.text((m, y), t, tf, pal.W, pal.K)
        y += tf.size * 1.12
    # the foot: the line, then the ask in white with the address and the mark
    af = face(INTER_SEMI, 26 * s)
    ask_h = cap(af) + 40 * s
    ay = h - m - ask_h
    probe = ask_block(st, m, ay, copy.ask, INTER_SEMI, 26 * s, p, tracking=0.1)
    sf = face(INTER, 22 * s)
    mk_x = w - m
    layer_w = mark(Image.new("RGB", (10, 10)), 0, 0, 28 * s, True)[2]
    tape(st, (mk_x - layer_w - pad, ay, mk_x + pad, ay + ask_h), [spot])
    mark(img, mk_x, ay + ask_h / 2 - 26 * s, 28 * s, True, right=True)
    sw_ = st.width(copy.site, sf)
    if probe[2] + 20 * s + sw_ + 2 * pad < mk_x - layer_w - 30 * s:
        tape(st, (probe[2] + 12 * s, ay, probe[2] + 12 * s + sw_ + 2 * pad, ay + ask_h), [spot])
        st.text((probe[2] + 12 * s + pad, ay + ask_h / 2 + cap(sf) / 2), copy.site, sf, pal.G5, pal.K)
    lf, lines = reading(st, shot.line, INTER, w - 2 * m - 2 * pad, 32 * s, 24 * s)
    y = ay - 22 * s - pad
    for t in reversed(lines):
        tw = st.width(t, lf)
        tape(st, (m - pad, y - cap(lf) - pad, m + tw + pad, y + pad + lf.size * 0.22), [spot])
        st.text((m, y), t, lf, pal.W, pal.K)
        y -= lf.size * 1.5
    if y + lf.size * 1.5 - cap(lf) - pad < low_start + 12 * s and ar >= 1.0:
        raise Clipped("the line runs into the photo")
    return Made(img, p, st.words, [spot])


DRAW: dict[str, Callable] = {"poster": _poster, "cascade": _cascade, "select": _select, "scan": _scan}


# ------------------------------------------------------------------------------------------------ making one
def words_of(name: str, shots: Sequence[Shot], copy: MotionCopy) -> list[str]:
    """Every word the design can set, for the copy rules."""
    extra = [PICK] if name == "select" else []
    return [copy.words(), *(f"{s.room} {s.line}" for s in shots), *extra]


def make(name: str, shots: Sequence[Shot], copy: MotionCopy, *, aspect: str = "4:5", index: int = 0,
         official: bool = False, palette: Optional[Palette] = None) -> Made:
    """Draw one design. The words pass the copy rules first; the palette comes from the photos by the design's
    rule; a palette that fails a contrast check is dropped and the post is drawn in the brand's black and white."""
    d = DESIGNS[name]
    if not d.needs <= len(shots) <= d.takes:
        raise ValueError(f"{name} takes {d.needs} to {d.takes} photos, not {len(shots)}")
    check_copy(*words_of(name, shots, copy), official=official, social=True)
    w, h = SIZES[aspect]
    ims = [picture(sh) for sh in shots]
    if palette is not None:
        p = palette
    elif d.rule in NO_ACCENT:
        p = replace(pal.fallback(d.dark, tuple(pal.swatches(ims))), rule=d.rule)
    else:
        p = pal.choose(ims, d.rule, lightness=d.lightness, dark=d.dark)
    kw = {"index": index} if name == "select" else {}
    try:
        made = DRAW[name](shots, ims, copy, w, h, p, **kw)
    except ContrastError as e:
        made = DRAW[name](shots, ims, copy, w, h, pal.fallback(d.dark, p.swatches), **kw)
        made.fell_back = str(e)
    for word in made.words:                   # no word is ever set over a photo: a layout that does is refused
        for box in made.photos:
            if word.box[0] < box[2] and box[0] < word.box[2] and word.box[1] < box[3] and box[1] < word.box[3]:
                raise Clipped(f"{word.text!r} is set over a photo")
    return made


def post(name: str, shots: Sequence[Shot], copy: MotionCopy, *, out: Path, aspect: str = "4:5", index: int = 0,
         official: bool = False, meta: Optional[ImageMeta] = None) -> Path:
    """Draw one design and save it fresh from its pixels (no camera data; our own fields only, render/meta.py)."""
    made = make(name, shots, copy, aspect=aspect, index=index, official=official)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    return save_jpeg(made.image, out, meta, quality=92)
