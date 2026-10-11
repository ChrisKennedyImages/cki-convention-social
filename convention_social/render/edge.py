"""Event Caliber post designs, second generation: built like a camera viewfinder and a measuring
instrument (a caliber), with heavy type and a hard call to action on every piece.

Chris, 2026-10-11: "super edgy and dynamic. Not boring". The daily photo post of posts.py
carried no ask on the image; every design here sells: what the coverage is, and Request a quote.

Designs (4:5 for Instagram and Facebook, 2:3 for Pinterest, 9:16 for stories):
  lockon    the daily post: the photo full frame inside viewfinder corners, a cyan focus box
            locked on the subject, a caliber scale on the edge, the service in heavy type, the ask
  slash     a statement post: the photo cut by a hard diagonal, the headline running along the cut
  iris      a hook post: the photo seen through aperture blades in a lens ring, the headline below
  carousel  a seamless swipe: a cover, one slide per part of the event, a closing ask; the photos
            cross the seams and one caliber scale runs under every slide

Brand: black, greys and white with one cyan (Chris, 2026-10-10); Unbounded for impact, JetBrains
Mono for the instrument read outs, Inter Tight for reading. Every word passes ai.copy_rules first.
Not wired to any agent until Chris approves the designs (show first).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance

from ..ai import copy_rules
from . import fonts
from .brand import DIRECTIONS, draw_mark, tracked, tracked_width
from .meta import ImageMeta, save_jpeg
from .posts import CopyRefused, cover, foot_gradient, open_photo, wrap

K, G1, G2, G3, G4, G5, W, C = ((10, 10, 11), (18, 18, 20), (28, 28, 32), (44, 44, 49), (140, 140, 147),
                               (200, 200, 205), (243, 243, 241), (0, 225, 255))
DISPLAY, MONO, BODY, BODY_SEMI = "Unbounded-ExtraBold.ttf", "JetBrainsMono-Medium.ttf", "InterTight-Regular.ttf", "InterTight-SemiBold.ttf"
SIZES = {"4:5": (1080, 1350), "2:3": (1000, 1500), "9:16": (1080, 1920), "1:1": (1080, 1080)}
APERTURE = DIRECTIONS["aperture"]


@dataclass
class EdgeCopy:
    service: str = ""            # what the frame shows: BACKSTAGE, PANELS, PORTRAITS ...
    headline: Sequence[str] = ()  # one or two short lines; the second is drawn hollow or in cyan
    line: str = ""               # one plain sentence
    kicker: str = ""             # the event and year, or a section label
    credit: str = ""             # exactly as recorded, e.g. "@handle"
    ask: str = "Request a quote"
    site: str = "eventcaliber.com"

    def words(self) -> str:
        return " ".join([self.service, *self.headline, self.line, self.kicker, self.credit, self.ask, self.site])


def check_copy(*texts: str, official: bool = False, social: bool = True) -> None:
    """Every card is social copy: nothing about a service, only the photo (Chris, 2026-10-11)."""
    report = copy_rules.check(" ".join(t for t in texts if t), official=official, social=social)
    if not report.ok:
        raise CopyRefused(report.blocks[0].message)


# --------------------------------------------------------------------------- the photo
def grade(im: Image.Image) -> Image.Image:
    """A touch more contrast, a touch less colour: night venue light without the neon cast."""
    im = ImageEnhance.Contrast(im).enhance(1.08)
    return ImageEnhance.Color(im).enhance(0.9)


def grain(im: Image.Image, amount: float = 0.35) -> Image.Image:
    noise = Image.effect_noise(im.size, 42).convert("RGB")
    return Image.blend(im, ImageChops.soft_light(im, noise), amount)


def shade(img: Image.Image, start: float, strength: float, curve: float = 1.2, top: bool = False) -> Image.Image:
    w, h = img.size
    m = foot_gradient(w, h, start, strength, curve)
    if top:
        m = m.transpose(Image.FLIP_TOP_BOTTOM)
    return Image.composite(Image.new("RGB", (w, h), K), img, m)


def framed(photo, w: int, h: int, focus=(0.5, 0.42)) -> Image.Image:
    return grain(grade(cover(open_photo(photo), w, h, focus)))


# --------------------------------------------------------------------------- type
def face(name: str, size: float):
    return fonts.face(name, max(8, int(size)))


def fit(d: ImageDraw.ImageDraw, lines: Sequence[str], name: str, max_w: float, start: float, floor: float):
    """The largest size at which every line fits max_w."""
    size = int(start)
    while size > floor:
        f = face(name, size)
        if all(d.textlength(t, font=f) <= max_w for t in lines):
            return f
        size -= 2
    return face(name, floor)


def hollow(img: Image.Image, xy, text: str, f, color, width: int, anchor: str = "ls") -> None:
    """Outline-only type: the stroke is drawn, the inside is punched back out."""
    layer = Image.new("L", img.size, 0)
    ImageDraw.Draw(layer).text(xy, text, font=f, fill=0, stroke_width=width, stroke_fill=255, anchor=anchor)
    img.paste(color, mask=layer)


def mono(d, xy, text: str, size: float, fill, tracking: float = 0.14) -> float:
    return tracked(d, xy, text.upper(), face(MONO, size), fill, tracking)


def mono_w(d, text: str, size: float, tracking: float = 0.14) -> float:
    return tracked_width(d, text.upper(), face(MONO, size), tracking)


# --------------------------------------------------------------------------- the instrument
def brackets(d, x0, y0, x1, y1, arm, lw, fill) -> None:
    for cx, cy, sx, sy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        d.line([(cx, cy), (cx + sx * arm, cy)], fill=fill, width=lw)
        d.line([(cx, cy), (cx, cy + sy * arm)], fill=fill, width=lw)


def af_box(d, cx, cy, bw, bh, lw, fill=C, label: str = "", s: float = 1.0) -> None:
    """The focus box locked on the subject: four cyan corners and a centre tick."""
    x0, y0, x1, y1 = cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2
    brackets(d, x0, y0, x1, y1, min(bw, bh) * 0.26, lw, fill)
    t = 9 * s
    d.line([(cx - t, cy), (cx + t, cy)], fill=fill, width=max(2, lw // 2))
    d.line([(cx, cy - t), (cx, cy + t)], fill=fill, width=max(2, lw // 2))
    if label:
        mono(d, (x0, y1 + 12 * s), label, 15 * s, fill, 0.18)


def rec(d, x, y, s: float, label: str = "REC", fill=W) -> float:
    r = 8 * s
    d.ellipse([x, y + 3 * s, x + 2 * r, y + 3 * s + 2 * r], fill=C)
    return mono(d, (x + 2 * r + 12 * s, y), label, 19 * s, fill, 0.18)


def scale_v(d, x, y0, y1, s: float, pointer: Optional[float] = None, side: int = -1, labels: bool = True) -> None:
    """A caliber scale: ticks every 14 px, a long one every fifth, numbered; a cyan pointer."""
    step = 14 * s
    n = int((y1 - y0) / step)
    for i in range(n + 1):
        y = y0 + i * step
        major = i % 5 == 0
        ln = (22 if major else 11) * s
        d.line([(x, y), (x + side * ln, y)], fill=W if major else G5, width=max(1, int(2 * s)))
        if major and labels:
            t = f"{i * 2:02d}"
            f = face(MONO, 13 * s)
            tx = x + side * (ln + 8 * s) - (d.textlength(t, font=f) if side < 0 else 0)
            d.text((tx, y - 8 * s), t, font=f, fill=G4)
    if pointer is not None:
        p = max(y0, min(y1, pointer))
        a = 12 * s
        d.polygon([(x + side * 26 * s, p), (x + side * (26 * s + a), p - a * 0.7), (x + side * (26 * s + a), p + a * 0.7)], fill=C)


def scale_h(d, x0, x1, y, s: float, pointers: Sequence[float] = (), labels: bool = True) -> None:
    step = 27 * s
    n = int((x1 - x0) / step)
    d.line([(x0, y), (x1, y)], fill=G3, width=max(1, int(2 * s)))
    for i in range(n + 1):
        x = x0 + i * step
        major = i % 5 == 0
        d.line([(x, y), (x, y - (20 if major else 9) * s)], fill=W if major else G4, width=max(1, int(2 * s)))
        if major and labels:
            d.text((x + 5 * s, y - 34 * s), f"{i // 5:02d}", font=face(MONO, 12 * s), fill=G4)
    for p in pointers:
        a = 11 * s
        d.polygon([(p, y + 6 * s), (p - a, y + 6 * s + a * 1.2), (p + a, y + 6 * s + a * 1.2)], fill=C)


def ask_row(img, d, x, y, s: float, ask: str, site: str, right: Optional[float] = None, mark: bool = True,
            size: float = 24) -> int:
    """The call to action: a hard cyan block, the address, the mark at the far right. Returns its height."""
    f = face(MONO, size * s)
    label = ask.upper() + "  ↗"
    tw = tracked_width(d, label, f, 0.08)
    padx, pady = 24 * s, 17 * s
    bh = int(size * s * 1.25 + 2 * pady)
    d.rectangle([x, y, x + tw + 2 * padx, y + bh], fill=C)
    tracked(d, (x + padx, y + pady - size * s * 0.05), label, f, K, 0.08)
    if site:
        mono(d, (x + tw + 2 * padx + 22 * s, y + bh / 2 - 11 * s), site, 20 * s, W, 0.16)
    if mark and right is not None:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        mw, mh = draw_mark(layer, APERTURE, 0, 0, int(30 * s))
        crop = layer.crop((0, 0, mw + 4, mh + 4))
        img.paste(crop, (int(right - mw), int(y + (bh - mh) / 2)), crop)
    return bh


def headline(img, d, x, y_base, lines: Sequence[str], f, s: float, second: str = "hollow") -> None:
    """Heavy type set bottom up from y_base: the last line is the first drawn."""
    lh = line_height(f)
    for i, t in enumerate(reversed(list(lines))):
        yb = y_base - i * lh
        is_second = len(lines) > 1 and i == 0
        if is_second and second == "hollow":
            hollow(img, (x, yb), t, f, W, max(2, int(3 * s)))
        elif is_second and second == "cyan":
            d.text((x, yb), t, font=f, fill=C, anchor="ls")
        else:
            solid(d, (x, yb), t, f, s)


def line_height(f) -> int:
    return int(f.size * 1.07)


def cap_height(f) -> int:
    return -f.getbbox("H", anchor="ls")[1]


def solid(d, xy, text: str, f, s: float, fill=W, ghost=C) -> None:
    """Heavy type with a cyan ghost a few pixels down and left, like a frame caught mid move."""
    if ghost:
        d.text((xy[0] - 6 * s, xy[1] + 4 * s), text, font=f, fill=ghost, anchor="ls")
    d.text(xy, text, font=f, fill=fill, anchor="ls")


def save(img: Image.Image, out: Path, meta: Optional[ImageMeta]) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    return save_jpeg(img, out, meta, quality=92)


# --------------------------------------------------------------------------- lockon: the daily post
def lockon(photo, copy: EdgeCopy, *, out: Path, aspect: str = "4:5", focus=(0.5, 0.42), af=(0.5, 0.4),
           official: bool = False, meta: Optional[ImageMeta] = None) -> Path:
    check_copy(copy.words(), official=official)
    w, h = SIZES[aspect]
    s = w / 1080
    img = framed(photo, w, h, focus)
    img = shade(img, 0.82, 0.6, 1.0, top=True)                  # a little dark at the top for the read outs
    img = shade(img, 0.46, 0.94, 1.15)                          # and a deep foot for the type
    d = ImageDraw.Draw(img)
    m = 40 * s
    brackets(d, m, m, w - m, h - m, 64 * s, max(3, int(4 * s)), W)
    ix = m + 28 * s
    rec(d, ix, m + 24 * s, s, "REC")
    mono(d, (ix + 92 * s, m + 24 * s), "EVENT CALIBER", 19 * s, G5, 0.18)
    if copy.service:
        sw = mono_w(d, copy.service, 19 * s, 0.18)
        d.rectangle([w - ix - sw - 26 * s, m + 29 * s, w - ix - sw - 14 * s, m + 41 * s], fill=C)
        mono(d, (w - ix - sw, m + 24 * s), copy.service, 19 * s, W, 0.18)
    ax, ay = af[0] * w, af[1] * h
    af_box(d, ax, ay, 210 * s, 160 * s, max(3, int(4 * s)), C, "AF LOCK", s)
    scale_v(d, w - m - 14 * s, h * 0.2, h * 0.5, s, pointer=ay, side=-1)

    # bottom up: the ask, the line, the headline, the kicker
    bottom = h - m - 30 * s
    bh = int(24 * s * 1.25 + 34 * s)
    ask_row(img, d, ix, bottom - bh, s, copy.ask, copy.site, right=w - ix)
    y = bottom - bh - 34 * s
    if copy.line:
        lf = face(BODY, 30 * s)
        lines = wrap(d, copy.line, lf, w - 2 * ix)[:2]
        for t in reversed(lines):
            d.text((ix, y), t, font=lf, fill=W, anchor="ls")
            y -= 40 * s
        y -= 26 * s
    heads = list(copy.headline) or [copy.service]
    hf = fit(d, heads, DISPLAY, w - 2 * ix, 150 * s, 70 * s)
    headline(img, d, ix, y, heads, hf, s, "hollow")
    top = y - line_height(hf) * (len(heads) - 1) - cap_height(hf)
    kick = "  ·  ".join(t for t in (copy.kicker, copy.credit) if t)
    if kick:
        mono(d, (ix, top - 52 * s), kick, 20 * s, C, 0.16)
    return save(img, out, meta)


# --------------------------------------------------------------------------- slash: the statement post
def slash(photo, copy: EdgeCopy, *, out: Path, aspect: str = "4:5", focus=(0.5, 0.4), af=None, number: str = "01",
          official: bool = False, meta: Optional[ImageMeta] = None) -> Path:
    check_copy(copy.words(), number, official=official)
    w, h = SIZES[aspect]
    s = w / 1080
    left_y, right_y = h * 0.6, h * 0.49
    img = Image.new("RGB", (w, h), K)
    ph = framed(photo, w, int(left_y) + 2, focus)
    m_ = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m_).polygon([(0, 0), (w, 0), (w, right_y), (0, left_y)], fill=255)
    img.paste(ph, (0, 0), m_.crop((0, 0, w, ph.height)))
    img = shade(img, 0.84, 0.55, 1.0, top=True)
    d = ImageDraw.Draw(img)
    m = 40 * s
    ix = m + 28 * s
    brackets(d, m, m, w - m, right_y - 30 * s, 54 * s, max(3, int(4 * s)), W)
    rec(d, ix, m + 24 * s, s, "REC")
    mono(d, (ix + 92 * s, m + 24 * s), "EVENT CALIBER", 19 * s, G5, 0.18)
    tag = f"N°{number}  {copy.service}".strip()
    mono(d, (w - ix - mono_w(d, tag, 19 * s, 0.18), m + 24 * s), tag, 19 * s, W, 0.18)
    if af:
        af_box(d, af[0] * w, af[1] * h, 190 * s, 150 * s, max(3, int(4 * s)), C, "AF LOCK", s)
    d.line([(0, left_y), (w, right_y)], fill=C, width=max(4, int(8 * s)))

    # the headline rides the cut: set flat, turned to the cut's angle, placed a fixed gap under it.
    # PIL turns a block counterclockwise about its centre; with expand=True its top-left corner
    # lands at (0, width * sin a), so the paste point is that far above where the corner should be.
    a = math.atan2(left_y - right_y, w)
    heads = list(copy.headline) or [copy.service]
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    hf = fit(probe, heads, DISPLAY, (w - 2 * ix - 30 * s) / math.cos(a), 140 * s, 64 * s)
    lh = line_height(hf)
    pad = int(hf.size * 0.95) - cap_height(hf)
    tw = int(max(probe.textlength(t, font=hf) for t in heads) + 40 * s)
    block = Image.new("RGBA", (tw, lh * len(heads) + int(40 * s)), (0, 0, 0, 0))
    bd = ImageDraw.Draw(block)
    for i, t in enumerate(heads):
        yb = int(hf.size * 0.95) + i * lh
        if i == len(heads) - 1 and len(heads) > 1:
            bd.text((8 * s, yb), t, font=hf, fill=C + (255,), anchor="ls")
        else:
            solid(bd, (8 * s, yb), t, hf, s, fill=W + (255,), ghost=C + (255,))
    rot = block.rotate(math.degrees(a), resample=Image.BICUBIC, expand=True)
    x0 = ix - 8 * s
    corner_y = left_y - (left_y - right_y) * (x0 / w) + 34 * s - pad
    img.paste(rot, (int(x0), int(corner_y - tw * math.sin(a))), rot)
    d = ImageDraw.Draw(img)
    last_base = corner_y + (int(hf.size * 0.95) + (len(heads) - 1) * lh) * math.cos(a)

    bottom = h - m - 30 * s
    bh = int(24 * s * 1.25 + 34 * s)
    ask_row(img, d, ix, bottom - bh, s, copy.ask, copy.site, right=w - ix)
    if copy.line:
        lf = face(BODY, 30 * s)
        y = last_base + 78 * s
        for t in wrap(d, copy.line, lf, w - 2 * ix)[:2]:
            d.text((ix, y), t, font=lf, fill=G5, anchor="ls")
            y += 40 * s
    return save(img, out, meta)


# --------------------------------------------------------------------------- iris: the hook post
def blades(d, cx, cy, r_open, r_out, n: int, phi: float, shades=(G2, G3)) -> None:
    """Aperture blades: the opening is an n-sided polygon; each side, carried on to the outer ring,
    is the edge of one blade."""
    pts = [(cx + r_open * math.cos(phi + 2 * math.pi * i / n), cy + r_open * math.sin(phi + 2 * math.pi * i / n)) for i in range(n)]

    def hit(p, q):                                 # where the ray p->q, carried past q, meets the outer circle
        dx, dy = q[0] - p[0], q[1] - p[1]
        fx, fy = q[0] - cx, q[1] - cy
        a, b, c = dx * dx + dy * dy, 2 * (fx * dx + fy * dy), fx * fx + fy * fy - r_out * r_out
        t = (-b + math.sqrt(max(0.0, b * b - 4 * a * c))) / (2 * a)
        return (q[0] + dx * t, q[1] + dy * t)
    ends = [hit(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        p1, p2 = pts[(i + 1) % n], pts[(i + 2) % n]
        q1, q2 = ends[i], ends[(i + 1) % n]
        a1, a2 = math.atan2(q1[1] - cy, q1[0] - cx), math.atan2(q2[1] - cy, q2[0] - cx)
        if a2 < a1:
            a2 += 2 * math.pi
        arc = [(cx + r_out * 1.02 * math.cos(a1 + (a2 - a1) * k / 12), cy + r_out * 1.02 * math.sin(a1 + (a2 - a1) * k / 12)) for k in range(13)]
        d.polygon([p1, *arc, p2], fill=shades[i % len(shades)])
    for i in range(n):
        d.line([pts[(i + 1) % n], ends[i]], fill=G4, width=2)


def iris(photo, copy: EdgeCopy, *, out: Path, aspect: str = "4:5", focus=(0.5, 0.45), opening: float = 0.74,
         official: bool = False, meta: Optional[ImageMeta] = None) -> Path:
    check_copy(copy.words(), official=official)
    w, h = SIZES[aspect]
    s = w / 1080
    img = Image.new("RGB", (w, h), K)
    cx, cy, R = w / 2, h * 0.335, w * 0.315
    ph = framed(photo, int(2 * R), int(2 * R), focus)
    disk = Image.new("L", ph.size, 0)
    ImageDraw.Draw(disk).ellipse([0, 0, ph.width - 1, ph.height - 1], fill=255)
    img.paste(ph, (int(cx - R), int(cy - R)), disk)
    d = ImageDraw.Draw(img)
    blades(d, cx, cy, R * opening, R, 7, -math.pi / 2 + 0.2, shades=((30, 30, 34), (44, 44, 50)))
    ring = 44 * s
    d.ellipse([cx - R - ring, cy - R - ring, cx + R + ring, cy + R + ring], outline=G3, width=int(ring))
    d.ellipse([cx - R - ring, cy - R - ring, cx + R + ring, cy + R + ring], outline=G4, width=max(1, int(2 * s)))
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=K, width=max(2, int(4 * s)))
    stops = ("1.4", "2", "2.8", "4", "5.6", "8", "11", "16")
    f = face(MONO, 17 * s)
    for i, t in enumerate(stops):                  # the aperture ring across the top
        a = math.radians(-150 + i * (120 / (len(stops) - 1)))
        tx, ty = cx + (R + ring / 2) * math.cos(a), cy + (R + ring / 2) * math.sin(a)
        d.text((tx, ty), t, font=f, fill=C if t == "2.8" else G5, anchor="mm")
    a = math.radians(-150 + 2 * (120 / (len(stops) - 1)))
    px, py = cx + (R + ring + 10 * s) * math.cos(a), cy + (R + ring + 10 * s) * math.sin(a)
    d.ellipse([px - 5 * s, py - 5 * s, px + 5 * s, py + 5 * s], fill=C)
    m = 40 * s
    ix = m + 28 * s
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    mw, mh = draw_mark(layer, APERTURE, 0, 0, int(30 * s))
    crop = layer.crop((0, 0, mw + 4, mh + 4))
    img.paste(crop, (int(ix), int(m + 10 * s)), crop)
    rec(d, w - ix - mono_w(d, "REC", 19 * s, 0.18) - 28 * s, m + 22 * s, s, "REC")

    bottom = h - m - 30 * s
    bh = int(24 * s * 1.25 + 34 * s)
    ask_row(img, d, ix, bottom - bh, s, copy.ask, copy.site, mark=False)
    heads = list(copy.headline) or [copy.service]
    hf = fit(d, heads, DISPLAY, w - 2 * ix, 104 * s, 56 * s)
    y = bottom - bh - 46 * s
    if copy.line:
        lf = face(BODY, 29 * s)
        for tline in reversed(wrap(d, copy.line, lf, w - 2 * ix)[:2]):
            d.text((ix, y), tline, font=lf, fill=G5, anchor="ls")
            y -= 39 * s
        y -= 18 * s
    headline(img, d, ix, y, heads, hf, s, "cyan")
    return save(img, out, meta)


# --------------------------------------------------------------------------- carousel: the seamless swipe
@dataclass
class Slide:
    photo: object
    service: str
    line: str
    focus: tuple = (0.5, 0.45)
    af: Optional[tuple] = None       # the subject inside this photo's own panel, 0 to 1


@dataclass
class CarouselCopy:
    """About the photos, never a service (Chris, 2026-10-11)."""
    cover: Sequence[str] = ("ONE", "EVENT.")
    cover_block: str = "ROOM BY ROOM."
    cover_line: str = "One event, one room at a time."
    close: Sequence[str] = ("REQUEST", "A QUOTE", "FOR YOUR", "EVENT.")
    close_line: str = ""
    ask: str = "Request a quote"
    site: str = "eventcaliber.com/book"

    def words(self) -> str:
        return " ".join([*self.cover, self.cover_block, self.cover_line, *self.close, self.close_line, self.ask, self.site])


def carousel(slides: Sequence[Slide], copy: CarouselCopy, *, out_dir: Path, official: bool = False,
             meta: Optional[ImageMeta] = None) -> list[Path]:
    """A cover, one slide per Slide, a closing ask; drawn as one long strip and cut at the seams so
    the photos and the scale run across them."""
    check_copy(copy.words(), *(f"{x.service} {x.line}" for x in slides), official=official)
    w, h = SIZES["4:5"]
    s = 1.0
    n = len(slides) + 2
    total = n
    CW = w * n
    BAND = 860
    img = Image.new("RGB", (CW, h), K)
    d = ImageDraw.Draw(img)

    # the photo band: photo k fills slide k+1 and peeks into slide k; a cyan slash at each edge
    peek, lean = 150, 46
    starts = [620] + [w * (k + 1) - peek for k in range(1, len(slides))]
    ends = starts[1:] + [w * (len(slides) + 1) - peek]
    for k, sl in enumerate(slides):
        x0, x1 = starts[k], ends[k]
        pw = int(x1 - x0 + 2 * lean)
        ph = framed(sl.photo, pw, BAND, sl.focus)
        m_ = Image.new("L", (pw, BAND), 0)
        ImageDraw.Draw(m_).polygon([(2 * lean, 0), (pw, 0), (pw - 2 * lean, BAND), (0, BAND)], fill=255)
        img.paste(ph, (int(x0 - lean), 0), m_)
    img = Image.composite(Image.new("RGB", img.size, K), img,
                          foot_gradient(CW, h, 0.42, 0.75, 1.3).crop((0, 0, CW, h)))
    d = ImageDraw.Draw(img)
    for k, x0 in enumerate(starts):
        d.line([(x0 + lean, 0), (x0 - lean, BAND)], fill=C, width=7)
    d.line([(ends[-1] + lean, 0), (ends[-1] - lean, BAND)], fill=C, width=7)

    # each service slide: viewfinder corners, the focus box, the number, the service, the line
    for k, sl in enumerate(slides):
        sx = w * (k + 1)
        m = 40
        brackets(d, sx + m, m, sx + w - m, BAND - 34, 52, 4, W)
        rec(d, sx + m + 28, m + 24, s, "REC")
        num = f"{k + 2:02d}"
        mono(d, (sx + w - m - 28 - mono_w(d, f"{num} / {total:02d}", 19, 0.18), m + 24), f"{num} / {total:02d}", 19, W, 0.18)
        if sl.af:
            af_box(d, sx + sl.af[0] * w, sl.af[1] * BAND, 190, 146, 4, C, "AF LOCK", s)
        ix = sx + 70
        mono(d, (ix, BAND + 66), f"N°{num}  ·  EVENTS", 22, C, 0.18)
        hf = fit(d, [sl.service], DISPLAY, w - 150, 116, 60)
        solid(d, (ix, BAND + 212), sl.service, hf, s)
        lf = face(BODY, 32)
        y = BAND + 280
        for t in wrap(d, sl.line, lf, w - 140)[:2]:
            d.text((ix, y), t, font=lf, fill=G5, anchor="ls")
            y += 42

    # the cover
    m = 40
    layer = Image.new("RGBA", (w, 200), (0, 0, 0, 0))
    mw, mh = draw_mark(layer, APERTURE, 0, 0, 34)
    crop = layer.crop((0, 0, mw + 4, mh + 4))
    img.paste(crop, (70, 70), crop)
    d = ImageDraw.Draw(img)
    mono(d, (w - 70 - mono_w(d, f"01 / {total:02d}", 19, 0.18), 84), f"01 / {total:02d}", 19, W, 0.18)
    cf = fit(d, list(copy.cover), DISPLAY, 940, 196, 100)
    y = 600
    for t in copy.cover:
        solid(d, (64, y), t, cf, s)
        y += int(cf.size * 1.0)
    bf = face(DISPLAY, int(cf.size * 0.56))
    bw = d.textlength(copy.cover_block, font=bf)
    d.rectangle([64, y - cf.size * 0.42, 64 + bw + 44, y + bf.size * 0.62], fill=C)
    d.text((86, y + bf.size * 0.42), copy.cover_block, font=bf, fill=K, anchor="ls")
    lf = face(BODY, 32)
    yy = y + bf.size * 0.62 + 80
    for t in wrap(d, copy.cover_line, lf, 900)[:2]:
        d.text((70, yy), t, font=lf, fill=W, anchor="ls")
        yy += 44
    mono(d, (w - 70 - mono_w(d, "SWIPE  →", 24, 0.2), h - 150), "SWIPE  →", 24, C, 0.2)

    # the close
    cx0 = w * (n - 1)
    layer = Image.new("RGBA", (w, 300), (0, 0, 0, 0))
    mw, mh = draw_mark(layer, APERTURE, 0, 0, 52)
    crop = layer.crop((0, 0, mw + 4, mh + 4))
    img.paste(crop, (cx0 + 70, 80), crop)
    d = ImageDraw.Draw(img)
    mono(d, (cx0 + w - 70 - mono_w(d, f"{total:02d} / {total:02d}", 19, 0.18), 96), f"{total:02d} / {total:02d}", 19, W, 0.18)
    ef = fit(d, list(copy.close), DISPLAY, w - 140, 112, 60)
    y = 330
    for i, t in enumerate(copy.close):
        d.text((cx0 + 66, y), t, font=ef, fill=C if i == len(copy.close) - 1 else W, anchor="ls")
        y += int(ef.size * 1.04)
    lf = face(BODY, 31)
    y += 10
    for t in wrap(d, copy.close_line, lf, w - 140)[:3]:
        d.text((cx0 + 70, y), t, font=lf, fill=G5, anchor="ls")
        y += 42
    f = face(MONO, 34)
    label = copy.ask.upper() + "  ↗"
    by = h - 330
    d.rectangle([cx0 + 70, by, cx0 + w - 70, by + 110], fill=C)
    tracked(d, (cx0 + 104, by + 34), label, f, K, 0.1)
    mono(d, (cx0 + 70, by + 150), copy.site, 26, W, 0.16)
    brackets(d, cx0 + 52, by - 18, cx0 + w - 52, by + 128, 30, 4, C)

    # one caliber scale under the whole strip, a pointer under each slide's name
    scale_h(d, 0, CW, h - 64, s, pointers=[w * k + 70 + 12 for k in range(1, n - 1)])

    out_dir = Path(out_dir)
    paths = []
    for k in range(n):
        paths.append(save(img.crop((w * k, 0, w * (k + 1), h)), out_dir / f"slide-{k + 1:02d}.jpg", meta))
    save(img.resize((CW // 4, h // 4), Image.LANCZOS), out_dir / "strip.jpg", None)
    return paths
