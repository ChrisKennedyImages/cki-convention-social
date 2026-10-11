"""Event Caliber in motion: the photos as physical cards in depth (render/stage.py).

Chris, 2026-10-11, after a flat first round: "You just made a fucking grid!? ... Like these". The
direction he sent: a hand of cards fanned across the frame with the focused one lifted out, a ring
that spins, a spotlight rail whose middle frame opens out to carry its caption, numbered folders.

Scenes (each returns the cards for one moment, so a still and a frame of a reel are the same code):
  fan       the photos dealt as a hand, one lifted out and turned to face you
  ring      the photos on a tilted ring that spins over a glossy floor
  rail      the photos shingled on a rail; the middle one opens wide with its caption
  folders   three numbered folders: 01 scan, 02 selfie, 03 sent (face match delivery)

Pieces built from them:
  rooms_reel       15 s: deal, a lift per room, fan to ring, the ask
  facematch_reel   15 s: the badge, the scan, the selfie, the photos finding their person, the ask
  carousel         9 slides: a fanned cover, a rail slide per room, face match, the ask on a ring
  spotlight_post   the daily post: today's photo opened on the rail
  fan_post         a hook post: the hand of photos
  facematch_post   the three folders

Every word passes ai.copy_rules first. The daily draft (agents/content.py) uses these; a reel only once
a music track is on (music.py), and nothing leaves without Chris's Approve.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter

from . import stage
from .brand import tracked, tracked_width
from .edge import (BODY, C, DISPLAY, G2, G3, G4, G5, K, MONO, W, af_box, check_copy, face, fit, grade, mono,
                   mono_w, solid)
from .meta import ImageMeta, save_jpeg
from .posts import cover, open_photo, wrap
from .reel import FPS, Grain, clamp, ease_back, ease_out, encode, logo

SWATCHES = (((88, 60, 160), (22, 18, 44)), ((226, 118, 58), (58, 22, 28)), ((120, 130, 150), (28, 30, 38)),
            ((198, 66, 70), (42, 12, 20)), ((58, 140, 200), (10, 22, 42)), ((208, 168, 88), (52, 30, 12)),
            ((150, 80, 170), (32, 12, 42)), ((70, 170, 150), (10, 34, 32)))


def ease_io(t: float) -> float:
    t = clamp(t)
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@dataclass
class Shot:
    """One photo and what it shows. `photo` None draws a plain colour card (a placeholder, never
    a made up picture)."""
    photo: object
    room: str
    line: str = ""
    focus: tuple = (0.5, 0.45)


# --------------------------------------------------------------------------- faces
def card_face(shot: Shot, w: int, h: int, index: int = 0, label: bool = True, radius: int = 26) -> Image.Image:
    if shot.photo is not None:
        im = grade(cover(open_photo(shot.photo), w, h, shot.focus))
    else:
        top, bot = SWATCHES[index % len(SWATCHES)]
        g = Image.linear_gradient("L").resize((w, h))
        im = Image.composite(Image.new("RGB", (w, h), bot), Image.new("RGB", (w, h), top), g)
    if label:
        foot = Image.linear_gradient("L").resize((w, h)).point(lambda v: max(0, int((v - 150) * 2.2)))
        im = Image.composite(Image.new("RGB", (w, h), K), im, foot)
        d = ImageDraw.Draw(im)
        s = w / 400
        mono(d, (22 * s, h - 46 * s), f"{index + 1:02d}", 15 * s, C, 0.18)
        mono(d, (62 * s, h - 46 * s), shot.room, 15 * s, W, 0.18)
    return stage.rounded(im, radius)


def backdrop(w: int, h: int, glow: float = 1.0, floor: Optional[float] = None) -> Image.Image:
    """Near black with a soft light behind the cards and, below a floor line, a faint sheen."""
    img = Image.new("RGB", (w, h), K)
    halo = Image.radial_gradient("L").resize((int(w * 1.4), int(h * 0.9)))
    halo = halo.point(lambda v: int(max(0, 255 - v) * 0.16 * glow))
    tint = Image.new("RGB", halo.size, (60, 64, 76))
    img.paste(tint, (int(-w * 0.2), int(h * 0.05)), halo)
    if floor is not None:
        sheen = Image.linear_gradient("L").resize((w, max(1, h - int(floor)))).point(lambda v: int(max(0, 60 - v) * 0.5))
        img.paste((40, 42, 50), (0, int(floor)), sheen)
    return img


# --------------------------------------------------------------------------- scenes
def fan(faces: Sequence[Image.Image], *, focus: float, lift: float, deal: Optional[Sequence[float]] = None,
        y0: float = 120, spread: float = 9.5, radius: float = 1050, scale: float = 0.78, reflect: float = 0.28,
        lift_y: float = 230, center: Optional[float] = None) -> list:
    n = len(faces)
    middle = (n - 1) / 2 if center is None else center
    cards = []
    for i, f in enumerate(faces):
        th = (i - middle) * spread
        d = i - focus
        wgt = max(0.0, 1 - abs(d)) * lift
        if 0 < abs(d) < 2.2:
            th += math.copysign(4.5 * lift * (1 - wgt), d)
        r = math.radians(th)
        x = radius * math.sin(r)
        y = y0 + radius * (1 - math.cos(r))
        c = stage.Card(f, x=x, y=y - lift_y * wgt, z=28 * abs(d) - 260 * wgt + 40, roll=th * (1 - wgt), pitch=16 * (1 - wgt),
                       yaw=-th * 0.5 * (1 - wgt), scale=scale * (1 + 0.14 * wgt), light=0.55 + 0.45 * max(wgt, 1 - lift),
                       blur=1.1 * (1 - wgt) * lift, reflect=reflect, shadow=0.7)
        if deal is not None:
            t = ease_out(deal[i])
            c = replace(c, y=c.y + 1100 * (1 - t), roll=c.roll + 40 * (1 - t) * (1 if i % 2 else -1), alpha=clamp(deal[i] * 3))
        cards.append(c)
    return cards


def ring(faces: Sequence[Image.Image], *, angle: float, tilt: float = 12, radius: float = 560, zc: float = 520,
         y0: float = 0, scale: float = 0.62, reflect: float = 0.3) -> list:
    n = len(faces)
    t = math.radians(tilt)
    cards = []
    for i, f in enumerate(faces):
        ph = angle + 360 * i / n
        p = math.radians(ph)
        x, y, z = radius * math.sin(p), 0.0, -radius * math.cos(p)
        y, z = y * math.cos(t) - z * math.sin(t), y * math.sin(t) + z * math.cos(t)
        facing = math.cos(p)
        cards.append(stage.Card(f, x=x, y=y0 + y, z=zc + z, yaw=-ph, pitch=tilt, scale=scale,
                                light=0.22 + 0.78 * clamp(facing), blur=0 if facing > 0.3 else 2.5 * (0.3 - facing),
                                reflect=reflect * clamp(facing + 0.3), shadow=0.45 * clamp(facing)))
    return cards


def rail(shots: Sequence[Shot], *, center: float, open_: float, w: int = 330, h: int = 470, gap: float = 210,
         y0: float = -40, wide: float = 1.75) -> list:
    """Shingled frames; the one at `center` opens to `wide` times its width, re-cropped, never stretched."""
    cards = []
    ci = round(center)
    for i, sh in enumerate(shots):
        d = i - center
        o = open_ * max(0.0, 1 - abs(d))
        fw = int(w * (1 + (wide - 1) * o))
        f = card_face(sh, fw, h, i, label=o < 0.5)
        push = math.copysign((w * (wide - 1) / 2) * open_ * min(1.0, abs(d)), d) if abs(d) > 0.01 else 0
        x = d * gap + push
        side = max(-1.0, min(1.0, d))
        cards.append(stage.Card(f, x=x, y=y0, z=70 * min(3.0, abs(d)) - 80 * o, yaw=-38 * side * (1 - o), scale=1.0,
                                light=1.0 if o > 0.5 else 0.5 + 0.3 * (1 - min(1.0, abs(d) / 3)), blur=0 if o > 0.5 else 0.8,
                                reflect=0.25, shadow=0.7))
    return cards


def folder_face(number: str, word: str, inside: Optional[Image.Image], w: int = 360, h: int = 420, lit: float = 1.0) -> Image.Image:
    """A folder: a tab at the top left, a dark body, the number, the word, and what it holds rising out."""
    ss = 2
    W2, H2 = w * ss, h * ss
    tab_h = int(H2 * 0.09)
    img = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    if inside is not None:
        ins = inside.resize((int(W2 * 0.8), int(H2 * 0.62)), Image.LANCZOS)
        img.alpha_composite(ins.convert("RGBA") if ins.mode != "RGBA" else ins, (int(W2 * 0.1), int(tab_h * 0.4)))
    body = Image.new("L", (W2, H2), 0)
    d = ImageDraw.Draw(body)
    r = int(26 * ss)
    d.rounded_rectangle([0, tab_h, W2 - 1, H2 - 1], r, fill=255)
    d.rounded_rectangle([0, 0, int(W2 * 0.42), tab_h + r], r // 2, fill=255)
    front = Image.new("L", (W2, H2), 0)
    ImageDraw.Draw(front).rounded_rectangle([0, int(H2 * 0.46), W2 - 1, H2 - 1], r, fill=255)
    grad = Image.linear_gradient("L").resize((W2, H2))
    back_fill = Image.composite(Image.new("RGB", (W2, H2), (18, 18, 21)), Image.new("RGB", (W2, H2), (44, 44, 50)), grad)
    back = back_fill.convert("RGBA")
    back.putalpha(body)
    out = Image.new("RGBA", (W2, H2), (0, 0, 0, 0))
    out.alpha_composite(back)
    out.alpha_composite(img)
    front_fill = Image.composite(Image.new("RGB", (W2, H2), (14, 14, 16)), Image.new("RGB", (W2, H2), (52, 52, 60)), grad)
    fr = front_fill.convert("RGBA")
    fr.putalpha(front)
    out.alpha_composite(fr)
    dd = ImageDraw.Draw(out)
    dd.line([(r, int(H2 * 0.46)), (W2 - r, int(H2 * 0.46))], fill=C + (255,), width=2 * ss)
    dd.text((26 * ss, int(H2 * 0.46) + 30 * ss), number, font=face(MONO, 54 * ss), fill=C + (255,))
    wf = fit(dd, [word], DISPLAY, W2 - 52 * ss, 44 * ss, 20 * ss)
    dd.text((26 * ss, H2 - 34 * ss), word, font=wf, fill=W + (255,), anchor="ls")
    out = out.resize((w, h), Image.LANCZOS)
    if lit < 1:
        a = out.getchannel("A")
        out = out.convert("RGB").point(lambda v: int(v * lit)).convert("RGBA")
        out.putalpha(a)
    pad = Image.new("RGBA", (w + 6, h + 6), (0, 0, 0, 0))
    pad.alpha_composite(out, (3, 3))
    return pad


def barcode(w: int, h: int, seed: int = 7) -> Image.Image:
    """Bars like the code on a lanyard badge (a drawing; it scans as nothing)."""
    im = Image.new("RGB", (w, h), (240, 240, 236))
    d = ImageDraw.Draw(im)
    x, r = int(w * 0.08), seed
    while x < w * 0.92:
        r = (r * 1103515245 + 12345) % (2 ** 31)
        bw = 2 + r % 7
        if (r >> 5) % 3:
            d.rectangle([x, h * 0.12, x + bw, h * 0.88], fill=(12, 12, 14))
        x += bw + 2 + (r >> 9) % 4
    return im


def selfie_icon(w: int, h: int) -> Image.Image:
    """A selfie frame: a head and shoulders outline inside a ring, focus corners locked on it."""
    ss = 3
    im = Image.new("RGB", (w * ss, h * ss), (20, 22, 26))
    d = ImageDraw.Draw(im)
    cx, cy, R = w * ss / 2, h * ss * 0.48, min(w, h) * ss * 0.36
    d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=(90, 92, 100), width=3 * ss)
    hr = R * 0.36
    d.ellipse([cx - hr, cy - hr * 1.5, cx + hr, cy + hr * 0.5], fill=(150, 152, 160))
    d.pieslice([cx - R * 0.72, cy + R * 0.25, cx + R * 0.72, cy + R * 1.5], 180, 360, fill=(150, 152, 160))
    af_box(d, cx, cy - hr * 0.5, hr * 3.2, hr * 3.4, 3 * ss, C)
    return im.resize((w, h), Image.LANCZOS)


# --------------------------------------------------------------------------- type
def caption(img: Image.Image, x: float, y: float, kicker: str, title: str, line: str, *, width: float, s: float = 1.0,
            title_size: float = 92, align: str = "left") -> float:
    """Kicker, title and line, set from y down. Returns the y it ended at."""
    d = ImageDraw.Draw(img)
    def ax(tw: float) -> float:
        return x - tw / 2 if align == "center" else x
    if kicker:
        mono(d, (ax(mono_w(d, kicker, 20 * s, 0.18)), y), kicker, 20 * s, C, 0.18)
        y += 40 * s
    if title:
        tf = fit(d, [title], DISPLAY, width, title_size * s, 40 * s)
        y += tf.size * 0.86
        solid(d, (ax(d.textlength(title, font=tf)), y), title, tf, s)
        y += 24 * s
    if line:
        lf = face(BODY, 30 * s)
        for t in wrap(d, line, lf, width)[:2]:
            y += 40 * s
            d.text((ax(d.textlength(t, font=lf)), y), t, font=lf, fill=G5, anchor="ls")
    return y


def corner_marks(img: Image.Image, s: float, counter: str = "", mark: bool = True) -> None:
    from .brand import draw_mark
    from .edge import APERTURE
    d = ImageDraw.Draw(img)
    if mark:
        layer = Image.new("RGBA", (int(400 * s), int(120 * s)), (0, 0, 0, 0))
        mw, mh = draw_mark(layer, APERTURE, 0, 0, int(30 * s))
        crop = layer.crop((0, 0, mw + 4, mh + 4))
        img.paste(crop, (int(64 * s), int(60 * s)), crop)
    if counter:
        mono(d, (img.width - 64 * s - mono_w(d, counter, 19 * s, 0.18), 74 * s), counter, 19 * s, W, 0.18)


def ask_block(img: Image.Image, cx: float, y: float, ask: str, site: str, s: float = 1.0, wipe: float = 1.0,
              width: float = 760) -> None:
    d = ImageDraw.Draw(img)
    bw, bh = width * s, 104 * s
    x = cx - bw / 2
    if wipe <= 0:
        return
    d.rectangle([x, y, x + bw * ease_out(wipe), y + bh], fill=C)
    if wipe >= 0.95:
        f = face(MONO, 36 * s)
        label = ask.upper() + "  ↗"
        lw = tracked_width(d, label, f, 0.1)
        tracked(d, (cx - lw / 2, y + 30 * s), label, f, K, 0.1)
        sw = mono_w(d, site, 26 * s, 0.16)
        mono(d, (cx - sw / 2, y + bh + 34 * s), site, 26 * s, W, 0.16)


def save(img: Image.Image, out: Path, meta: Optional[ImageMeta] = None) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    return save_jpeg(img, out, meta, quality=92)


# --------------------------------------------------------------------------- copy
@dataclass
class MotionCopy:
    hook: Sequence[str] = ("EVERY ROOM", "OF YOUR EVENT.")
    covered: str = "COVERED."
    fm_title: str = "YOUR PHOTOS FIND YOU."
    fm_steps: Sequence[tuple] = (("01", "SCAN"), ("02", "SELFIE"), ("03", "SENT"))
    fm_line: str = "Scan the badge, three quick fields, a selfie. Every photo you are in comes straight to you."
    fm_choice: str = "Open to every attendee, or staff only. Your call before the event."
    tagline: str = "Event and convention photography"
    ask: str = "Request a quote"
    site: str = "eventcaliber.com"

    def words(self) -> str:
        return " ".join([*self.hook, self.covered, self.fm_title, *(f"{a} {b}" for a, b in self.fm_steps), self.fm_line,
                         self.fm_choice, self.tagline, self.ask, self.site])


def _check(shots: Sequence[Shot], copy: MotionCopy, official: bool) -> None:
    check_copy(copy.words(), *(f"{s.room} {s.line}" for s in shots), official=official)


# --------------------------------------------------------------------------- stills
def fan_post(shots: Sequence[Shot], copy: MotionCopy, *, out: Path, focus: int = 3, official: bool = False,
             meta: Optional[ImageMeta] = None) -> Path:
    _check(shots, copy, official)
    w, h = 1080, 1350
    img = backdrop(w, h, floor=h * 0.86)
    faces = [card_face(sh, 400, 540, i) for i, sh in enumerate(shots)]
    stage.draw(img, fan(faces, focus=focus, lift=1.0, y0=40, scale=0.62, spread=10, radius=1000, lift_y=150),
               cy=h * 0.6, floor=420)
    corner_marks(img, 1.0)
    y = caption(img, 70, 170, "EVENT CALIBER  ·  FULL COVERAGE", copy.hook[0], "", width=940, title_size=88)
    caption(img, 70, y - 20, "", copy.hook[1], "", width=940, title_size=88)
    ask_strip(img, h - 120, copy)
    return save(grain_still(img), out, meta)


def ask_strip(img: Image.Image, y: float, copy: MotionCopy, s: float = 1.0) -> None:
    from .edge import ask_row
    d = ImageDraw.Draw(img)
    ask_row(img, d, 70 * s, y, s, copy.ask, copy.site, right=img.width - 70 * s)


def grain_still(img: Image.Image) -> Image.Image:
    from .edge import grain
    return grain(img, 0.22)


POST_SIZES = {"4:5": (1080, 1350), "2:3": (1000, 1500)}


def single_post(shot: Shot, copy: MotionCopy, *, out: Path, aspect: str = "4:5", kicker: str = "", official: bool = False,
                meta: Optional[ImageMeta] = None) -> Path:
    """One photo as one card in depth (Chris, 2026-10-11: "it's ok to use 1 photo too sometimes"):
    turned a little toward you over a glossy floor, its room and line under it, the ask."""
    _check([shot], copy, official)
    check_copy(kicker, official=official)
    w, h = POST_SIZES[aspect]
    s = w / 1080
    img = backdrop(w, h, floor=h * 0.66)
    src = open_photo(shot.photo) if shot.photo is not None else None
    ratio = max(0.66, min(1.6, (src.width / src.height) if src is not None else 1.5))
    cap_top = h - 120 * s - 270 * s                 # the caption and the ask are set from the bottom up
    area_top, area_bot = 140 * s, cap_top - 60 * s  # the card takes what is left above them
    area_h = area_bot - area_top
    fh = area_h * 0.86
    fw = fh * ratio
    if fw > 900 * s:
        fw, fh = 900 * s, 900 * s / ratio
    face_img = card_face(shot, int(fw), int(fh), 0, label=False, radius=int(26 * s))
    cy = (area_top + area_bot) / 2
    card = stage.Card(face_img, x=0, y=0, z=0, yaw=-9, pitch=4, reflect=0.32, shadow=0.85)
    stage.draw(img, [card], cy=cy, floor=fh / 2 + 40 * s)
    corner_marks(img, s)
    caption(img, 70 * s, cap_top, kicker, shot.room, shot.line, width=w - 140 * s, s=s, title_size=84)
    ask_strip(img, h - 120 * s, copy, s)
    return save(grain_still(img), out, meta)


def spotlight_post(shots: Sequence[Shot], copy: MotionCopy, *, out: Path, index: int = 2, official: bool = False,
                   meta: Optional[ImageMeta] = None, counter: str = "") -> Path:
    _check(shots, copy, official)
    w, h = 1080, 1350
    img = backdrop(w, h, floor=h * 0.7)
    stage.draw(img, rail(shots, center=index, open_=1.0, w=300, h=430, gap=190, y0=-40), cy=h * 0.42, floor=230)
    corner_marks(img, 1.0, counter)
    sh = shots[index]
    caption(img, w / 2, h * 0.66, f"N°{index + 1:02d}  ·  COVERAGE", sh.room, sh.line, width=920, title_size=96, align="center")
    ask_strip(img, h - 120, copy)
    return save(grain_still(img), out, meta)


def facematch_post(shots: Sequence[Shot], copy: MotionCopy, *, out: Path, official: bool = False,
                   meta: Optional[ImageMeta] = None, counter: str = "") -> Path:
    _check(shots, copy, official)
    w, h = 1080, 1350
    img = backdrop(w, h, floor=h * 0.74)
    insides = [barcode(300, 160), selfie_icon(300, 260), card_face(shots[0], 300, 260, 0, label=False).convert("RGB")]
    faces = [folder_face(n, word, ins, 320, 400) for (n, word), ins in zip(copy.fm_steps, insides)]
    cards = [stage.Card(f, x=(i - 1) * 330, y=0, z=40 if i != 1 else -40, yaw=(1 - i) * 16, pitch=6, scale=1.0,
                        reflect=0.25, shadow=0.7, light=0.9 if i != 1 else 1.0) for i, f in enumerate(faces)]
    stage.draw(img, [replace(c, scale=1.12) for c in cards], cy=h * 0.56, floor=250)
    corner_marks(img, 1.0, counter)
    caption(img, 70, 190, "FACE MATCH DELIVERY", copy.fm_title, copy.fm_line, width=940, title_size=84)
    d = ImageDraw.Draw(img)
    lf = face(BODY, 30)
    for i, t in enumerate(wrap(d, copy.fm_choice, lf, 940)[:2]):
        d.text((70, h - 200 + i * 40), t, font=lf, fill=W, anchor="ls")
    ask_strip(img, h - 120, copy)
    return save(grain_still(img), out, meta)


def carousel(shots: Sequence[Shot], copy: MotionCopy, *, out_dir: Path, official: bool = False,
             meta: Optional[ImageMeta] = None) -> list[Path]:
    """A fanned cover, a rail slide per room (the next room waits on the right, so the swipe
    walks the rail), face match, and the ask on a ring of every room."""
    _check(shots, copy, official)
    out_dir = Path(out_dir)
    n = len(shots) + 3
    paths = [fan_post(shots, copy, out=out_dir / "slide-01.jpg", focus=len(shots) // 2, official=official, meta=meta)]
    # the cover carries the swipe cue in place of the ask
    cover_img = Image.open(paths[0]).convert("RGB")
    d = ImageDraw.Draw(cover_img)
    d.rectangle([0, 1350 - 170, 1080, 1350], fill=K)
    mono(d, (1080 - 70 - mono_w(d, "SWIPE  →", 24, 0.2), 1350 - 110), "SWIPE  →", 24, C, 0.2)
    mono(d, (70, 1350 - 110), f"01 / {n:02d}", 22, W, 0.18)
    save(cover_img, paths[0], meta)
    for i in range(len(shots)):
        paths.append(spotlight_post(shots, copy, out=out_dir / f"slide-{i + 2:02d}.jpg", index=i, official=official, meta=meta,
                                    counter=f"{i + 2:02d} / {n:02d}"))
    paths.append(facematch_post(shots, copy, out=out_dir / f"slide-{n - 1:02d}.jpg", official=official, meta=meta,
                                counter=f"{n - 1:02d} / {n:02d}"))
    w, h = 1080, 1350
    img = backdrop(w, h, floor=h * 0.6)
    faces = [card_face(sh, 360, 480, i) for i, sh in enumerate(shots)]
    stage.draw(img, ring(faces, angle=14, tilt=14, radius=470, zc=560, scale=0.66), cy=h * 0.36, floor=250)
    corner_marks(img, 1.0, f"{n:02d} / {n:02d}")
    y = caption(img, w / 2, h * 0.62, "EVERY ROOM  ·  EVERY GUEST", copy.covered, "", width=900, title_size=120, align="center")
    ask_block(img, w / 2, y + 60, copy.ask, copy.site + "/book")
    paths.append(save(grain_still(img), out_dir / f"slide-{n:02d}.jpg", meta))
    return paths


# --------------------------------------------------------------------------- reels
RW, RH = 1080, 1920


def _end_card(f: int, copy: MotionCopy, base: Image.Image) -> Image.Image:
    img = base
    lw = logo(Image.new("RGB", (10, 10)), 0, 0, 120, 1, 1, 1, 1)
    logo(img, int((RW - lw) / 2), 560, 120, f / 16, (f - 14) / 5, (f - 18) / 7, (f - 22) / 12)
    d = ImageDraw.Draw(img)
    tg = copy.tagline.upper()
    tf = face(MONO, 26)
    tw = tracked_width(d, tg, tf, 0.2)
    if f > 34:
        tracked(d, ((RW - tw) / 2, 900), tg[:int(len(tg) * clamp((f - 34) / 16))], tf, G5, 0.2)
    ask_block(img, RW / 2, 1080, copy.ask, copy.site, wipe=(f - 52) / 9, width=860)
    return img


def rooms_reel(shots: Sequence[Shot], copy: MotionCopy, *, out: Path, official: bool = False,
               encoder: Optional[Callable] = None, only: Optional[Sequence[int]] = None,
               frames_dir: Optional[Path] = None, audio: Optional[Path] = None) -> Path:
    """15 s: the photos deal into a hand, one lifts per room, the hand folds into a spinning ring,
    the logo and the ask."""
    _check(shots, copy, official)
    n = len(shots)
    faces = [card_face(sh, 400, 540, i) for i, sh in enumerate(shots)]
    big = [card_face(sh, 400, 540, i, label=False) for i, sh in enumerate(shots)]
    grain = Grain()
    DEAL, ROOM, MORPH, SPIN, END = ROOMS_TIMING
    total = total_frames("rooms", n)
    floor_y = 520
    HAND = dict(y0=60, scale=1.0, spread=10.5, radius=1250, lift_y=200)

    def frame(i: int) -> Image.Image:
        img = backdrop(RW, RH, floor=RH * 0.8)
        cy = RH * 0.6
        if i < DEAL:
            deal = [clamp((i - 3 * k) / 14) for k in range(n)]
            turn = lerp((n - 1) / 2, 0, ease_io((i - 24) / 16))       # the hand turns to the first room as it lands
            stage.draw(img, fan(faces, focus=0, lift=0.0, deal=deal, center=turn, **HAND), cy=cy, floor=floor_y, fast=True)
            for j, t in enumerate(copy.hook):
                tf = fit(ImageDraw.Draw(img), list(copy.hook), DISPLAY, 920, 110, 60)
                _slam(img, t, tf, 76, 360 + j * int(tf.size * 1.05), (i - 16 - 5 * j) / 6)
        elif i < DEAL + ROOM * n:
            k, f = divmod(i - DEAL, ROOM)
            prev = max(0, k - 1)
            fpos = lerp(prev, k, ease_io(f / 10))
            lift = ease_out(f / 8) if k == 0 else 1.0
            stage.draw(img, fan(faces, focus=fpos, lift=lift, center=fpos, **HAND), cy=cy, floor=floor_y, fast=True)
            sh = shots[k]
            d = ImageDraw.Draw(img)
            mono(d, (76, 300), f"N°{k + 1:02d} / {n:02d}", 22, C, 0.18)
            tf = fit(d, [sh.room], DISPLAY, 920, 130, 60)
            _slam(img, sh.room, tf, 76, 460, (f - 2) / 5)
            if sh.line and f > 8:
                lf = face(BODY, 38)
                for j, t in enumerate(wrap(d, sh.line, lf, 900)[:2]):
                    _fade(img, (80, 530 + j * 50), t, lf, G5, (f - 8) / 6)
        elif i < DEAL + ROOM * n + MORPH + SPIN:
            f = i - DEAL - ROOM * n
            m = ease_io(f / MORPH)
            a = fan(big, focus=n - 1, lift=1 - m, center=n - 1, **HAND)
            spin = 20 + 220 * ease_io(max(0, f - MORPH) / SPIN)
            b = ring(big, angle=spin, radius=560, zc=420, scale=0.92, tilt=13, y0=-60)
            cards = [replace(cb, x=lerp(ca.x, cb.x, m), y=lerp(ca.y, cb.y, m), z=lerp(ca.z, cb.z, m), yaw=lerp(ca.yaw, cb.yaw, m),
                             pitch=lerp(ca.pitch, cb.pitch, m), roll=lerp(ca.roll, cb.roll, m), scale=lerp(ca.scale, cb.scale, m),
                             light=lerp(ca.light, cb.light, m), blur=lerp(ca.blur, cb.blur, m)) for ca, cb in zip(a, b)]
            stage.draw(img, cards, cy=cy, floor=floor_y, fast=True)
            d = ImageDraw.Draw(img)
            tf = fit(d, [copy.covered], DISPLAY, 920, 170, 60)
            _block(img, copy.covered, tf, 76, 1450, (f - MORPH) / 6)
            if f > MORPH + 20:
                lf = face(BODY, 38)
                for j, t in enumerate(wrap(d, copy.fm_line, lf, 900)[:2]):
                    _fade(img, (80, 1540 + j * 50), t, lf, W, (f - MORPH - 20) / 8)
        else:
            f = i - (DEAL + ROOM * n + MORPH + SPIN)
            if f < 12:
                spin = 240 + 30 * f / 12
                cards = [replace(c, alpha=1 - f / 12) for c in ring(big, angle=spin, radius=560 + 240 * f / 12, zc=420, scale=0.92, tilt=13, y0=-60)]
                stage.draw(img, cards, cy=cy, floor=floor_y, fast=True)
            img = _end_card(f, copy, img)
        return grain(img, i, 0.2)

    return _render(frame, total, out, encoder, only, frames_dir, audio)


def facematch_reel(shots: Sequence[Shot], copy: MotionCopy, *, out: Path, official: bool = False,
               encoder: Optional[Callable] = None, only: Optional[Sequence[int]] = None,
               frames_dir: Optional[Path] = None, audio: Optional[Path] = None) -> Path:
    """15 s: a badge swings in, its code is scanned, three fields fill, a selfie locks, and the
    photos fly in from every side to land on one person's stack; then the organizer's choice and the ask."""
    _check(shots, copy, official)
    grain = Grain()
    faces = [card_face(sh, 360, 480, i, label=False) for i, sh in enumerate(shots)]
    BADGE, SCAN, FIELDS, SELFIE, STREAM, CHOICE, END = FACEMATCH_TIMING
    total = total_frames("facematch")
    bc = barcode(420, 150)

    def badge(img: Image.Image, swing: float, scan: Optional[float]) -> None:
        bw, bh = 520, 700
        b = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(b)
        d.rounded_rectangle([0, 0, bw - 1, bh - 1], 34, fill=(236, 236, 232, 255))
        d.rounded_rectangle([bw / 2 - 60, 26, bw / 2 + 60, 46], 10, fill=(170, 170, 170, 255))
        d.rectangle([0, 90, bw, 230], fill=(16, 16, 18, 255))
        mono(d, (40, 128), "ATTENDEE", 30, C, 0.3)
        mono(d, (40, 176), "SCAN FOR YOUR PHOTOS", 18, W, 0.18)
        d.rounded_rectangle([60, 300, bw - 60, 520], 18, fill=(255, 255, 255, 255))
        b.paste(bc, (50, 335))
        mono(d, (40, bh - 110), "GENERAL ADMISSION", 22, (60, 60, 64), 0.18)
        if scan is not None:
            y = 320 + 200 * scan
            glow = Image.new("RGBA", (bw, 60), C + (0,))
            gd = ImageDraw.Draw(glow)
            for k in range(30):
                gd.line([(40, 30 - k), (bw - 40, 30 - k)], fill=C + (int(120 * (1 - k / 30)),))
                gd.line([(40, 30 + k), (bw - 40, 30 + k)], fill=C + (int(120 * (1 - k / 30)),))
            b.alpha_composite(glow, (0, int(y - 30)))
            d.line([(30, y), (bw - 30, y)], fill=C + (255,), width=5)
        card = stage.Card(b, x=0, y=-60, z=0, roll=swing, scale=1.0, shadow=0.8)
        d2 = ImageDraw.Draw(img)
        attach = (RW / 2, RH * 0.46 - 410)
        d2.line([(RW / 2 - 70, 0), attach], fill=(20, 20, 24), width=26)
        d2.line([(RW / 2 + 70, 0), attach], fill=(20, 20, 24), width=26)
        d2.line([(RW / 2 - 70, 0), attach], fill=(0, 150, 170), width=4)
        stage.draw(img, [card], cy=RH * 0.46)

    def frame(i: int) -> Image.Image:
        img = backdrop(RW, RH)
        d = ImageDraw.Draw(img)
        t = i
        if t < BADGE + SCAN:
            sw = 18 * math.exp(-t / 18) * math.cos(t / 4.2)
            yoff = -900 * (1 - ease_out(t / 18))
            tmp = backdrop(RW, RH)
            badge(tmp, sw, (t - BADGE) / SCAN if t >= BADGE else None)
            img.paste(tmp.crop((0, max(0, -int(yoff)), RW, RH)), (0, max(0, int(yoff))))
            d = ImageDraw.Draw(img)
            mono(d, (76, 1500), "01  SCAN", 26, C, 0.2)
            tf = fit(d, ["SCAN YOUR BADGE."], DISPLAY, 920, 104, 50)
            _slam(img, "SCAN YOUR BADGE.", tf, 76, 1620, (t - 12) / 6)
            if BADGE <= t < BADGE + 4:
                img = Image.blend(img, Image.new("RGB", (RW, RH), C), 0.25 * (1 - (t - BADGE) / 4))
        elif t < BADGE + SCAN + FIELDS:
            f = t - BADGE - SCAN
            mono(d, (76, 500), "02  THREE QUICK FIELDS", 26, C, 0.2)
            for k in range(3):
                y = 640 + k * 190
                p = ease_out((f - 6 * k) / 14)
                d.rounded_rectangle([76, y, RW - 76, y + 120], 22, outline=G3, width=3)
                if p > 0:
                    d.rounded_rectangle([90, y + 14, 90 + (RW - 180) * p, y + 106], 16, fill=(24, 40, 46))
                    d.rectangle([90 + (RW - 180) * p - 4, y + 30, 90 + (RW - 180) * p, y + 90], fill=C)
                if p >= 1:
                    d.line([(RW - 160, y + 62), (RW - 144, y + 78), (RW - 116, y + 42)], fill=C, width=7, joint="curve")
            tf = fit(d, ["THREE QUICK FIELDS."], DISPLAY, 920, 96, 50)
            _slam(img, "THREE QUICK FIELDS.", tf, 76, 1400, f / 6)
        elif t < BADGE + SCAN + FIELDS + SELFIE:
            f = t - BADGE - SCAN - FIELDS
            mono(d, (76, 300), "03  A QUICK SELFIE", 26, C, 0.2)
            s_img = selfie_icon(620, 760)
            k = ease_back(f / 10)
            sz = (int(620 * (0.6 + 0.4 * k)), int(760 * (0.6 + 0.4 * k)))
            s_img = stage.rounded(s_img.resize(sz, Image.LANCZOS), 40)
            img.paste(s_img, (int(RW / 2 - sz[0] / 2), int(RH * 0.47 - sz[1] / 2)), s_img)
            if f > 14:
                d = ImageDraw.Draw(img)
                af_box(d, RW / 2, RH * 0.47 - 90, 360, 400, 6, C, "MATCH LOCKED" if f > 20 else "", 1.4)
            tf = fit(d, ["A QUICK SELFIE."], DISPLAY, 920, 104, 50)
            _slam(img, "A QUICK SELFIE.", tf, 76, 1400, f / 6)
            if f > 29:
                img = Image.blend(img, Image.new("RGB", (RW, RH), W), 0.9 * (1 - (f - 30) / 4))
        elif t < BADGE + SCAN + FIELDS + SELFIE + STREAM:
            f = t - BADGE - SCAN - FIELDS - SELFIE
            cards = []
            nn = len(faces)
            for k in range(nn * 2):
                start = 6 * k
                p = ease_out((f - start) / 20)
                if p <= 0:
                    continue
                ang = (k * 137) % 360
                fx, fy = 1400 * math.cos(math.radians(ang)), 1400 * math.sin(math.radians(ang))
                rot = ((k * 53) % 30) - 15
                cards.append(stage.Card(faces[k % nn], x=lerp(fx, (k % 3 - 1) * 14, p), y=lerp(fy, -120 - min(k, 12) * 3, p),
                                        z=lerp(600, -k * 4, p), roll=lerp(rot * 3, rot * 0.4, p), scale=1.3, shadow=0.7,
                                        alpha=clamp(p * 2), light=0.85 + 0.15 * p))
            stage.draw(img, cards, cy=RH * 0.44, fast=True)
            got = sum(1 for k in range(nn * 2) if f - 6 * k >= 20)
            d = ImageDraw.Draw(img)
            if got:
                af_box(d, RW / 2, RH * 0.44 - 300, 400, 340, 6, C, "", 1.4)
                pill = f"+{got}  YOUR PHOTOS"
                pw = mono_w(d, pill, 28, 0.16)
                d.rounded_rectangle([RW / 2 - pw / 2 - 28, 230, RW / 2 + pw / 2 + 28, 300], 35, fill=C)
                mono(d, (RW / 2 - pw / 2, 248), pill, 28, K, 0.16)
            tf = fit(d, [copy.fm_title], DISPLAY, 920, 100, 50)
            _slam(img, copy.fm_title, tf, 76, 1450, (f - 10) / 6)
            lf = face(BODY, 38)
            for j, tline in enumerate(wrap(d, copy.fm_line, lf, 900)[:3]):
                _fade(img, (80, 1530 + j * 50), tline, lf, G5, (f - 24) / 8)
        elif t < BADGE + SCAN + FIELDS + SELFIE + STREAM + CHOICE:
            f = t - BADGE - SCAN - FIELDS - SELFIE - STREAM
            opts = [("01", "EVERY GUEST"), ("02", "STAFF ONLY")]
            insides = [card_face(shots[0], 300, 260, 0, label=False).convert("RGB"), card_face(shots[1 % len(shots)], 300, 260, 1, label=False).convert("RGB")]
            pick = 0 if (f // 24) % 2 == 0 else 1
            cards = []
            for k, ((num, word), ins) in enumerate(zip(opts, insides)):
                p = ease_back((f - 4 * k) / 12)
                on = k == pick
                cards.append(stage.Card(folder_face(num, word, ins, 440, 540, lit=1.0 if on else 0.55), x=(k - 0.5) * 470,
                                        y=lerp(400, -60 if on else 0, p), z=-60 if on else 40, yaw=(0.5 - k) * 18, scale=1.0,
                                        alpha=clamp(p * 2), shadow=0.8, reflect=0.25))
            stage.draw(img, cards, cy=RH * 0.47, floor=330, fast=True)
            d = ImageDraw.Draw(img)
            mono(d, (76, 300), "FOR ORGANIZERS", 26, C, 0.2)
            tf = fit(d, ["YOUR CALL."], DISPLAY, 920, 150, 60)
            _slam(img, "YOUR CALL.", tf, 76, 1400, f / 6)
            lf = face(BODY, 38)
            for j, tline in enumerate(wrap(d, copy.fm_choice, lf, 900)[:2]):
                _fade(img, (80, 1480 + j * 50), tline, lf, W, (f - 10) / 8)
        else:
            img = _end_card(t - (BADGE + SCAN + FIELDS + SELFIE + STREAM + CHOICE), copy, img)
        return grain(img, i, 0.2)

    return _render(frame, total, out, encoder, only, frames_dir, audio)


def _slam(img: Image.Image, text: str, f, x: float, y: float, t: float) -> None:
    from .reel import slam
    slam(img, text, f, x, y, t)


def _block(img: Image.Image, text: str, f, x: float, y: float, t: float) -> None:
    if t <= 0:
        return
    d = ImageDraw.Draw(img)
    tw = d.textlength(text, font=f)
    wipe = ease_out(t)
    d.rectangle([x - 20, y - f.size * 0.9, x - 20 + (tw + 40) * wipe, y + f.size * 0.28], fill=C)
    if wipe > 0.7:
        d.text((x, y), text, font=f, fill=K, anchor="ls")


def _fade(img: Image.Image, xy, text: str, f, fill, alpha: float) -> None:
    if alpha <= 0:
        return
    a = clamp(alpha)
    col = tuple(int(K[i] + (fill[i] - K[i]) * a) for i in range(3))
    ImageDraw.Draw(img).text(xy, text, font=f, fill=col, anchor="ls")


def _render(frame: Callable[[int], Image.Image], total: int, out: Path, encoder, only, frames_dir, audio=None) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if frames_dir:
        Path(frames_dir).mkdir(parents=True, exist_ok=True)

    def frames():
        for i in (only if only is not None else range(total)):
            img = frame(i)
            if frames_dir and i % 15 == 0:
                img.save(Path(frames_dir) / f"f{i:03d}.jpg", quality=85)
            yield img

    if encoder:
        return encoder(frames(), out)
    # the track rides the reel: faded out over the reel's own last second and a half, not a fixed 15 s
    return encode(frames(), out, audio=audio, seconds=(len(only) if only is not None else total) / FPS)


ROOMS_TIMING = (40, 30, 24, 66, 140)                   # deal, each room, fan to ring, spin, end card
FACEMATCH_TIMING = (40, 30, 36, 34, 120, 70, 120)      # badge, scan, fields, selfie, photos arrive, choice, end card


def total_frames(kind: str, n: int = 6) -> int:
    """15 seconds at 30 frames a second for six rooms."""
    if kind == "rooms":
        deal, room, morph, spin, end = ROOMS_TIMING
        return deal + room * n + morph + spin + end
    return sum(FACEMATCH_TIMING)


REELS = {"rooms": rooms_reel, "facematch": facematch_reel}


def still_frames(kind: str, n: int) -> tuple[int, ...]:
    """The cover first (the first room opened out; the photos landing on one person), then the
    stills the art director looks at: the second room and the ring, or the organizer's choice."""
    if kind == "rooms":
        deal, room, morph, spin, _ = ROOMS_TIMING
        return (deal + 20, deal + room + 20, deal + room * n + morph + spin - 10)
    badge, scan, fields, selfie, stream, _, _ = FACEMATCH_TIMING
    return (badge + scan + fields + selfie + 100, badge + scan + fields + selfie + stream + 40)


def reel_stills(kind: str, shots: Sequence[Shot], copy: MotionCopy, *, out_dir: Path, official: bool = False,
                meta: Optional[ImageMeta] = None) -> list[Path]:
    """The reel's cover and stills, drawn by the reel's own frame code (not cut from the mp4), saved
    as JPEGs with the company's metadata. The cover is first."""
    picks = still_frames(kind, len(shots))
    out_dir = Path(out_dir)
    saved: list[Path] = []

    def keep(frames, _out):
        for i, img in zip(picks, frames):
            saved.append(save(img, out_dir / f"{kind}-{i:03d}.jpg", meta))
        return _out

    REELS[kind](shots, copy, out=out_dir / "unused.mp4", official=official, only=picks, encoder=keep)
    return saved
