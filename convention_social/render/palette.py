"""Colour from the photo, and the contrast every word is checked against before it is drawn.

Chris, 2026-10-15: "come up with some new designs (like 4 so they arent all exactly the same design everytime)
and make sure you follow strict color theory and proper design". The four bold designs (render/bold.py) keep the
brand as their base, black, greys and white with one cyan (2026-10-10), and each adds one accent taken from the
photo it carries:

1. The photo is read small (64 px on its long side) and every pixel is turned into OKLab, a perceptual colour
   space in which equal steps look equal.
2. k-means (k = 6, seeded the same way every time) groups the pixels into the photo's own colours.
3. The photo's hue is the colour with the most weight times chroma (how much of the frame it covers, times how
   colourful it is), among the colours colourful enough to have a hue (chroma 0.04 or more) and neither near
   black nor near white.
4. The design's rule turns that hue (OKLCH degrees):
     complementary  +180
     split          +150 or +210 (split complementary) and
     triadic        +120 or +240: of the two, the one farthest from every other colour covering 8% or more of
                    the photo and from the brand's cyan, so the accent is the one new colour in the frame
     analogous      +30 or -30, whichever reaches the stronger colour at the design's lightness
5. The accent is built at the design's own lightness with as much chroma as sRGB can show, capped, never out of
   gamut. One that cannot reach MIN_ACCENT_CHROMA would be muddy and is not used: the brand's black and white.
6. A photo with no hue (a grey room, a black and white frame) takes the brand's cyan.

Contrast (WCAG 2): every word goes through Setter.text, which measures its colour against the flat colour under
it before it is drawn: 4.5 to 1 for small type, 3 to 1 for large type (LARGE_PX and up on a 1080 px post, about
24 pt on a phone). No word in these designs is ever set over a photo, so the colour under each word is known
exactly. A word that fails raises ContrastError and the design is drawn again in the brand's black and white
(fallback()). The setter also refuses a word that would leave the frame and a letter its typeface does not have.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional, Sequence

from PIL import Image, ImageDraw, ImageOps

K, G4, G5, W, C = (10, 10, 11), (140, 140, 147), (200, 200, 205), (243, 243, 241), (0, 225, 255)
SMALL, LARGE = 4.5, 3.0                  # WCAG 2 AA: small type, large type
LARGE_PX = 64                            # a font size at or above this, on a 1080 px wide post, is large type
RULES = ("complementary", "split", "triadic", "analogous")
MIN_CHROMA = 0.04                        # below this a colour has no hue worth answering
MAX_CHROMA = 0.26                        # the accent's chroma cap: vivid, never neon
CYAN_HUE = 211.7                         # the brand cyan's own OKLCH hue
MIN_ACCENT_CHROMA = 0.08                 # an accent duller than this would be muddy: the brand's black and white instead


# ------------------------------------------------------------------------------------------------ colour maths
def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(x: float) -> float:
    return 12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055


def oklab(rgb: Sequence[int]) -> tuple[float, float, float]:
    """sRGB 0..255 to OKLab (Ottosson, 2020)."""
    r, g, b = (_lin(v) for v in rgb[:3])
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _linear_from_oklab(L: float, a: float, b: float) -> tuple[float, float, float]:
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def in_gamut(L: float, C_: float, h: float) -> bool:
    a, b = C_ * math.cos(math.radians(h)), C_ * math.sin(math.radians(h))
    return all(-1e-6 <= v <= 1 + 1e-6 for v in _linear_from_oklab(L, a, b))


def from_oklch(L: float, C_: float, h: float) -> tuple[int, int, int]:
    a, b = C_ * math.cos(math.radians(h)), C_ * math.sin(math.radians(h))
    return tuple(max(0, min(255, round(255 * _gamma(max(0.0, min(1.0, v)))))) for v in _linear_from_oklab(L, a, b))


def lch(rgb: Sequence[int]) -> tuple[float, float, float]:
    L, a, b = oklab(rgb)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def max_chroma(L: float, h: float, cap: float = MAX_CHROMA) -> float:
    """The most chroma sRGB can show at this lightness and hue, up to `cap`."""
    lo, hi = 0.0, cap
    if in_gamut(L, hi, h):
        return hi
    for _ in range(24):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if in_gamut(L, mid, h) else (lo, mid)
    return lo


def luminance(rgb: Sequence[int]) -> float:
    r, g, b = (_lin(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: Sequence[int], bg: Sequence[int]) -> float:
    """The WCAG 2 contrast ratio, 1 to 21."""
    a, b = luminance(fg), luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


# ------------------------------------------------------------------------------------------------ the photo's colours
@dataclass(frozen=True)
class Swatch:
    rgb: tuple
    weight: float            # share of the frame
    L: float
    C: float
    h: float

    @property
    def chromatic(self) -> bool:
        return self.C >= MIN_CHROMA and 0.12 <= self.L <= 0.95


def _small(photo: Image.Image, side: int = 64) -> Image.Image:
    im = ImageOps.exif_transpose(photo).convert("RGB") if isinstance(photo, Image.Image) else photo
    im = im.copy()
    im.thumbnail((side, side), Image.BILINEAR, reducing_gap=3.0)
    return im


def kmeans(points: list, k: int = 6, iters: int = 12) -> list[tuple[tuple, int]]:
    """(centre, count) per cluster. Deterministic: the first centre is the pixel nearest the mean, each next one the
    pixel farthest from the centres so far."""
    if not points:
        return []
    n = len(points)
    mean = tuple(sum(p[i] for p in points) / n for i in range(3))

    def d2(p, q):
        return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2
    centres = [min(points, key=lambda p: d2(p, mean))]
    near = [d2(p, centres[0]) for p in points]
    while len(centres) < min(k, n):
        i = max(range(n), key=near.__getitem__)
        if near[i] <= 1e-12:
            break
        centres.append(points[i])
        near = [min(near[j], d2(points[j], points[i])) for j in range(n)]
    labels = [0] * n
    for _ in range(iters):
        labels = [min(range(len(centres)), key=lambda c: d2(p, centres[c])) for p in points]
        moved = False
        for c in range(len(centres)):
            members = [points[j] for j in range(n) if labels[j] == c]
            if members:
                new = tuple(sum(p[i] for p in members) / len(members) for i in range(3))
                moved = moved or d2(new, centres[c]) > 1e-10
                centres[c] = new
        if not moved:
            break
    counts = [labels.count(c) for c in range(len(centres))]
    return [(centres[c], counts[c]) for c in range(len(centres)) if counts[c]]


def swatches(photos: Iterable[Image.Image], k: int = 6) -> list[Swatch]:
    """The colours of one photo, or of several pooled (a multi-photo design answers the whole set), weight first."""
    pts = []
    for p in photos:
        im = _small(p)
        pts += [oklab(px) for px in im.getdata()]
    out = []
    for (L, a, b), count in kmeans(pts, k):
        C_ = math.hypot(a, b)
        h = math.degrees(math.atan2(b, a)) % 360
        out.append(Swatch(from_oklch(L, C_, h), count / len(pts), L, C_, h))
    return sorted(out, key=lambda s: -s.weight)


def dominant(sw: Sequence[Swatch]) -> Optional[Swatch]:
    """The photo's hue: the colourful swatch with the most weight times chroma; None for a photo with no hue."""
    colourful = [s for s in sw if s.chromatic]
    return max(colourful, key=lambda s: s.weight * s.C) if colourful else None


# ------------------------------------------------------------------------------------------------ the palette
@dataclass(frozen=True)
class Palette:
    rule: str                   # complementary, split, analogous; "brand cyan" (no hue); "black and white" (fallback)
    ground: tuple               # the design's own ground: the brand black, or paper for a light design
    ink: tuple                  # words on the ground
    quiet: tuple                # second words on the ground (a grey that still passes for small type)
    accent: tuple               # the one colour the design adds
    on_accent: tuple            # words on the accent: black or white, whichever is the stronger
    hue: Optional[float] = None         # the photo's hue, OKLCH degrees
    accent_hue: Optional[float] = None
    swatches: tuple = field(default_factory=tuple)

    @property
    def fallback(self) -> bool:
        return self.rule == "black and white"

    def describe(self) -> str:
        if self.hue is None:
            return f"{self.rule}: accent {hexa(self.accent)}"
        return (f"{self.rule}: photo hue {self.hue:.0f}°, accent {self.accent_hue:.0f}° {hexa(self.accent)}, "
                f"words on it {'black' if self.on_accent == K else 'white'}")


def hexa(rgb) -> str:
    return "#%02X%02X%02X" % tuple(rgb[:3])


def _stronger(bg) -> tuple:
    return K if contrast(K, bg) >= contrast(W, bg) else W


def accent_hue(rule: str, sw: Sequence[Swatch], base: Swatch, lightness: float) -> float:
    if rule == "complementary":
        return (base.h + 180) % 360
    if rule in ("split", "triadic"):
        # the accent is the one new colour in the frame: of the two candidates, the one farthest from every other
        # colour that covers some of the photo, and from the brand's cyan, which is in every frame
        others = [s.h for s in sw if s.chromatic and s is not base and s.weight >= 0.08] + [CYAN_HUE]
        turns = (150, 210) if rule == "split" else (120, 240)
        return max(((base.h + t) % 360 for t in turns), key=lambda h: min(hue_gap(h, o) for o in others))
    if rule == "analogous":
        return max(((base.h + 30) % 360, (base.h - 30) % 360), key=lambda h: max_chroma(lightness, h))
    raise ValueError(f"unknown colour rule {rule}")


def choose(photos: Sequence[Image.Image], rule: str, *, lightness: float, dark: bool = True) -> Palette:
    """The palette a design takes from its photos by its rule. `lightness` is the accent's OKLab L: light for an
    accent that carries black words or sits on black, deep for one that sits on paper."""
    sw = swatches(photos)
    base = dominant(sw)
    ground, ink, quiet = (K, W, G5) if dark else (W, K, (88, 88, 94))
    if base is None:
        return Palette("brand cyan", ground, ink, quiet, C, _stronger(C), None, None, tuple(sw))
    h = accent_hue(rule, sw, base, lightness)
    chroma = max_chroma(lightness, h)
    if chroma < MIN_ACCENT_CHROMA:
        return fallback(dark, tuple(sw))
    acc = from_oklch(lightness, chroma, h)
    return Palette(rule, ground, ink, quiet, acc, _stronger(acc), base.h, h, tuple(sw))


def fallback(dark: bool = True, sw: tuple = ()) -> Palette:
    """The brand's black and white: what a design is drawn in when its photo's palette fails a contrast check."""
    if dark:
        return Palette("black and white", K, W, G5, W, K, swatches=sw)
    return Palette("black and white", W, K, (88, 88, 94), K, W, swatches=sw)


# ------------------------------------------------------------------------------------------------ the setter
class ContrastError(ValueError):
    pass


class Clipped(ValueError):
    pass


@dataclass
class Word:
    text: str
    fill: tuple
    bg: tuple
    size: int
    ratio: float
    need: float
    box: tuple                  # (x0, y0, x1, y1) on the post


@lru_cache(maxsize=64)
def _tofu(path: str, size: int) -> bytes:
    from PIL import ImageFont
    return _glyph(ImageFont.truetype(path, size), "")


def _glyph(f, ch: str) -> bytes:
    im = Image.new("L", (int(f.size * 2), int(f.size * 2)))
    ImageDraw.Draw(im).text((f.size // 4, f.size // 4), ch, font=f, fill=255)
    return im.tobytes()


@lru_cache(maxsize=2048)
def _has(path: str, size: int, ch: str) -> bool:
    from PIL import ImageFont
    return ch.isspace() or _glyph(ImageFont.truetype(path, size), ch) != _tofu(path, size)


class Setter:
    """Draws every word of a design, each checked before it is drawn: its contrast against the flat colour under
    it, every letter in its typeface, and the whole word inside the frame. What it drew is kept in `words`."""

    def __init__(self, img: Image.Image, scale: float = 1.0):
        self.img = img
        self.d = ImageDraw.Draw(img)
        self.scale = scale
        self.words: list[Word] = []

    def need(self, f) -> float:
        return LARGE if f.size >= LARGE_PX * self.scale else SMALL

    def check(self, text: str, f, fill, bg) -> float:
        ratio = contrast(fill, bg)
        need = self.need(f)
        if ratio + 1e-9 < need:
            raise ContrastError(f"{text!r} is {ratio:.2f} to 1 on {hexa(bg)}, {need} needed")
        path = getattr(f, "path", None)
        if path:
            missing = [ch for ch in set(text) if not _has(path, 48, ch)]
            if missing:
                raise ValueError(f"{text!r}: the typeface has no {''.join(sorted(missing))!r}")
        return ratio

    def _inside(self, text: str, box) -> None:
        x0, y0, x1, y1 = box
        if x0 < -0.5 or y0 < -0.5 or x1 > self.img.width + 0.5 or y1 > self.img.height + 0.5:
            raise Clipped(f"{text!r} leaves the frame at {tuple(round(v) for v in box)}")

    def width(self, text: str, f, tracking: float = 0.0) -> float:
        if not tracking:
            return self.d.textlength(text, font=f)
        return sum(self.d.textlength(c, font=f) for c in text) + tracking * f.size * max(0, len(text) - 1)

    def text(self, xy, text: str, f, fill, bg, *, tracking: float = 0.0, anchor: str = "ls") -> tuple:
        """Draw `text` with its baseline at xy (left, or right with anchor 'rs'). Returns its box."""
        if not text:
            return (xy[0], xy[1], xy[0], xy[1])
        ratio = self.check(text, f, fill, bg)
        x, y = xy
        if anchor[0] == "r":
            x -= self.width(text, f, tracking)
        elif anchor[0] == "m":
            x -= self.width(text, f, tracking) / 2
        a = "l" + anchor[1]
        boxes = []
        if tracking:
            cx = x
            for ch in text:
                boxes.append(self.d.textbbox((cx, y), ch, font=f, anchor=a))
                cx += self.d.textlength(ch, font=f) + tracking * f.size
        else:
            boxes.append(self.d.textbbox((x, y), text, font=f, anchor=a))
        box = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        self._inside(text, box)
        if tracking:
            cx = x
            for ch in text:
                self.d.text((cx, y), ch, font=f, fill=fill, anchor=a)
                cx += self.d.textlength(ch, font=f) + tracking * f.size
        else:
            self.d.text((x, y), text, font=f, fill=fill, anchor=a)
        self.words.append(Word(text, tuple(fill), tuple(bg), f.size, ratio, self.need(f), box))
        return box

    def turned(self, xy, text: str, f, fill, bg, *, tracking: float = 0.0) -> tuple:
        """`text` turned a quarter to read upward, its baseline's start at xy (the bottom left of the run)."""
        ratio = self.check(text, f, fill, bg)
        tw = int(self.width(text, f, tracking)) + 4
        asc, desc = f.getmetrics()
        layer = Image.new("RGBA", (tw, asc + desc + 4), (0, 0, 0, 0))
        ld, cx = ImageDraw.Draw(layer), 0.0
        for run in (text,) if not tracking else tuple(text):
            ld.text((cx, asc), run, font=f, fill=tuple(fill) + (255,), anchor="ls")
            cx += ld.textlength(run, font=f) + tracking * f.size
        rot = layer.rotate(90, expand=True)          # a quarter turn left: the run reads upward
        x, y = xy
        px, py = int(x - asc), int(y - tw)
        box = (px, py, px + rot.width, py + rot.height)
        ink = rot.getbbox()
        if ink:
            self._inside(text, (px + ink[0], py + ink[1], px + ink[2], py + ink[3]))
        self.img.paste(rot, (px, py), rot)
        self.words.append(Word(text, tuple(fill), tuple(bg), f.size, ratio, self.need(f), box))
        return box
