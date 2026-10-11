"""A small 3D stage for photo cards, in Pillow alone: perspective, depth order, soft shadows,
a glossy floor with reflections, and depth of field.

Chris, 2026-10-11, after a flat first round ("You just made a fucking grid"): the photos move as
physical cards in depth. A card is a face (the photo, cut to its shape) placed in space; the
camera sits FOCAL pixels in front of the frame, so a card at z = 0 is drawn at its own size.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageOps

FOCAL = 1500.0


@dataclass
class Card:
    face: Image.Image             # RGBA, the card as it looks head on
    x: float = 0.0                # centre, pixels from the middle of the frame (y down)
    y: float = 0.0
    z: float = 0.0                # depth: positive is further away
    yaw: float = 0.0              # degrees, turning left and right
    pitch: float = 0.0            # degrees, tipping toward and away
    roll: float = 0.0             # degrees, in the plane of the frame
    scale: float = 1.0
    alpha: float = 1.0
    light: float = 1.0            # 1 as shot, lower is darker
    blur: float = 0.0             # extra softness, pixels
    shadow: float = 0.6           # drop shadow strength
    reflect: float = 0.0          # reflection strength on the floor


# --------------------------------------------------------------------------- geometry
def _rotate(p, yaw: float, pitch: float, roll: float):
    x, y, z = p
    r = math.radians(roll)
    x, y = x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)
    a = math.radians(yaw)
    x, z = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
    b = math.radians(pitch)
    y, z = y * math.cos(b) - z * math.sin(b), y * math.sin(b) + z * math.cos(b)
    return x, y, z


def corners(card: Card) -> list[tuple[float, float, float]]:
    w, h = card.face.size
    hw, hh = w * card.scale / 2, h * card.scale / 2
    out = []
    for px, py in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        x, y, z = _rotate((px, py, 0.0), card.yaw, card.pitch, card.roll)
        out.append((x + card.x, y + card.y, z + card.z))
    return out


def project(p, cx: float, cy: float) -> tuple[float, float]:
    x, y, z = p
    k = FOCAL / max(1.0, FOCAL + z)
    return cx + x * k, cy + y * k


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-12:
            raise ValueError("degenerate card")
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def perspective_coeffs(screen: Sequence[tuple[float, float]], face: Sequence[tuple[float, float]]) -> list[float]:
    """Coefficients for Image.transform(PERSPECTIVE): each output (screen) point to its face point."""
    a, b = [], []
    for (x, y), (u, v) in zip(screen, face):
        a.append([x, y, 1, 0, 0, 0, -x * u, -y * u]); b.append(u)
        a.append([0, 0, 0, x, y, 1, -x * v, -y * v]); b.append(v)
    return _solve(a, b)


# --------------------------------------------------------------------------- drawing
def _warp(card: Card, cx: float, cy: float, frame_size, quality) -> Optional[tuple[Image.Image, int, int, list]]:
    pts = [project(p, cx, cy) for p in corners(card)]
    if any(FOCAL + p[2] <= 1 for p in corners(card)):
        return None
    x0, y0 = math.floor(min(p[0] for p in pts)) - 2, math.floor(min(p[1] for p in pts)) - 2
    x1, y1 = math.ceil(max(p[0] for p in pts)) + 2, math.ceil(max(p[1] for p in pts)) + 2
    fw, fh = frame_size
    if x1 < 0 or y1 < 0 or x0 > fw or y0 > fh or x1 - x0 < 2 or y1 - y0 < 2:
        return None
    w, h = card.face.size
    local = [(px - x0, py - y0) for px, py in pts]
    try:
        coeffs = perspective_coeffs(local, [(0, 0), (w, 0), (w, h), (0, h)])
    except ValueError:
        return None
    patch = card.face.transform((x1 - x0, y1 - y0), Image.PERSPECTIVE, coeffs, quality)
    return patch, x0, y0, local


def _with_alpha(patch: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 0.999:
        return patch
    a = patch.getchannel("A").point(lambda v: int(v * alpha))
    patch.putalpha(a)
    return patch


def _darken(patch: Image.Image, light: float) -> Image.Image:
    if abs(light - 1) < 0.01:
        return patch
    a = patch.getchannel("A")
    rgb = patch.convert("RGB").point(lambda v: max(0, min(255, int(v * light))))
    rgb.putalpha(a)
    return rgb


def shadow_of(local, size, strength: float, spread: int, dy: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon([(x, y + dy) for x, y in local], fill=int(255 * strength))
    small = m.resize((max(1, size[0] // 4), max(1, size[1] // 4)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(max(1, spread // 4)))
    return small.resize(size, Image.BILINEAR)


def draw(canvas: Image.Image, cards: Sequence[Card], *, cx: Optional[float] = None, cy: Optional[float] = None,
         floor: Optional[float] = None, fast: bool = False) -> Image.Image:
    """Draw cards far to near onto an RGB canvas. With `floor` (a y in space), cards marked to
    reflect are mirrored in it first, fading with distance from the floor."""
    cx = canvas.width / 2 if cx is None else cx
    cy = canvas.height / 2 if cy is None else cy
    quality = Image.BILINEAR if fast else Image.BICUBIC
    order = sorted(cards, key=lambda c: -c.z)
    if floor is not None:
        for c in order:
            if c.reflect <= 0:
                continue
            fade = Image.linear_gradient("L").resize(c.face.size).point(lambda v: int(v * 0.9))
            face = ImageOps.flip(c.face)
            a = Image.composite(face.getchannel("A"), Image.new("L", face.size, 0), fade)
            face.putalpha(a)
            mirror = replace(c, face=face, y=2 * floor - c.y, pitch=-c.pitch, roll=-c.roll, alpha=c.alpha * c.reflect,
                             blur=c.blur + 3, shadow=0)
            _paint(canvas, mirror, cx, cy, quality)
    for c in order:
        _paint(canvas, c, cx, cy, quality)
    return canvas


def _paint(canvas: Image.Image, c: Card, cx: float, cy: float, quality) -> None:
    if c.alpha <= 0.01:
        return
    got = _warp(c, cx, cy, canvas.size, quality)
    if got is None:
        return
    patch, x0, y0, local = got
    if c.shadow > 0:
        pad = 60
        sh = shadow_of([(x + pad, y + pad) for x, y in local], (patch.width + 2 * pad, patch.height + 2 * pad),
                       c.shadow * c.alpha * 0.8, 36, 26)
        canvas.paste((0, 0, 0), (x0 - pad, y0 - pad), sh)
    patch = _darken(patch, c.light)
    if c.blur > 0.4:
        patch = patch.filter(ImageFilter.GaussianBlur(c.blur))
    patch = _with_alpha(patch, c.alpha)
    canvas.paste(patch, (x0, y0), patch)


# --------------------------------------------------------------------------- faces
def rounded(im: Image.Image, radius: int, border: Optional[tuple] = (255, 255, 255, 46), pad: int = 3) -> Image.Image:
    """The card face: the picture with rounded corners, a hairline edge, and a clear margin so the
    edges stay smooth when the card turns."""
    w, h = im.size
    face = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ss = 3
    m = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius * ss, fill=255)
    m = m.resize((w, h), Image.LANCZOS)
    face.paste(im.convert("RGB"), (pad, pad), m)
    if border:
        line = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        ImageDraw.Draw(line).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], radius * ss, outline=border, width=2 * ss)
        line = line.resize((w, h), Image.LANCZOS)
        face.alpha_composite(line, (pad, pad))
    return face
