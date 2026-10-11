"""The Event Caliber reel: 15 seconds, 9:16, cut like a camera at work.

  0.0 s  black; the viewfinder corners snap in, REC blinks, the focus box drops and locks
  1.2 s  six clips, one per part of the event: a push or pull on the photo, the focus box locking
         on the subject, the name of the room slamming in with a cyan ghost, one plain line;
         between clips an aperture closing and opening, a strobe flash, or an RGB tear
  9.2 s  a rapid montage, five frames a shot: EVERY ROOM. then COVERED.
 11.2 s  the end card: the Aperture logo draws itself, the ask wipes in, the address types on

Everything that must be read stays inside the area Instagram and Facebook leave clear of their
buttons and caption (no type below 1450 px or right of 960 px on a 1080 x 1920 frame).
Silent: music is a separate decision (a track we hold the rights to costs money; none is used without them).

Frames are drawn with Pillow and piped to ffmpeg (H.264, yuv420p, faststart). No ffmpeg, no reel:
`ffmpeg_path()` fails closed with the reason.
Not wired to any agent until Chris approves the design (show first).
"""
from __future__ import annotations

import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

from PIL import Image, ImageChops, ImageDraw

from .brand import tracked, tracked_width
from .edge import (C, DISPLAY, G3, G4, G5, K, MONO, BODY, W, af_box, blades, brackets, check_copy, face, fit, grade,
                   mono, mono_w, scale_v)
from .posts import cover, foot_gradient, open_photo, wrap

FW, FH, FPS = 1080, 1920, 30
SAFE_BOTTOM, SAFE_RIGHT = 1450, 960
INTRO, CLIP, MONTAGE_SHOT, MONTAGE_SHOTS, END = 36, 40, 5, 12, 114
TRANSITIONS = ("shutter", "flash", "tear", "shutter", "flash", "tear")


@dataclass
class Clip:
    photo: object
    word: str                 # MAIN STAGE, BACKSTAGE ...
    line: str                 # one plain sentence
    focus: tuple = (0.5, 0.45)
    af: tuple = (0.5, 0.42)   # the subject on the 1080 x 1920 frame, 0 to 1


@dataclass
class ReelCopy:
    montage: Sequence[str] = ("EVERY", "ROOM.")
    block: str = "COVERED."
    tagline: str = "Event and convention photography"
    ask: str = "Request a quote"
    site: str = "eventcaliber.com"

    def words(self) -> str:
        return " ".join([*self.montage, self.block, self.tagline, self.ask, self.site])


def ffmpeg_path() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg                     # a pip package that carries its own ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("ffmpeg is not installed on this machine, so no reel can be made")


# --------------------------------------------------------------------------- easing
def clamp(t: float) -> float:
    return max(0.0, min(1.0, t))


def ease_out(t: float) -> float:
    return 1 - (1 - clamp(t)) ** 3


def ease_back(t: float) -> float:
    t = clamp(t)
    c1 = 1.70158
    return 1 + (c1 + 1) * (t - 1) ** 3 + c1 * (t - 1) ** 2


# --------------------------------------------------------------------------- pieces
class Plate:
    """A photo prepared once at 1.3 x the frame, so every frame is a crop and a resize."""

    def __init__(self, photo, focus):
        self.im = grade(cover(open_photo(photo), int(FW * 1.3), int(FH * 1.3), focus))

    def frame(self, zoom: float, dx: float = 0.0, dy: float = 0.0) -> Image.Image:
        bw, bh = self.im.size
        cw, ch = bw / zoom, bh / zoom
        x0 = (bw - cw) / 2 + dx * (bw - cw) / 2
        y0 = (bh - ch) / 2 + dy * (bh - ch) / 2
        return self.im.resize((FW, FH), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch))


class Grain:
    def __init__(self, n: int = 6):
        self.noise = [Image.effect_noise((FW, FH), 40).convert("RGB") for _ in range(n)]

    def __call__(self, img: Image.Image, i: int, amount: float = 0.26) -> Image.Image:
        return Image.blend(img, ImageChops.soft_light(img, self.noise[(i // 2) % len(self.noise)]), amount)


def timecode(i: int) -> str:
    sec, fr = divmod(i, FPS)
    return f"00:00:{sec:02d}:{fr:02d}"


def hud(d: ImageDraw.ImageDraw, i: int, counter: str = "", blink: bool = True) -> None:
    m = 56
    brackets(d, m, m + 60, FW - m, SAFE_BOTTOM + 60, 90, 5, W)
    x = m + 34
    if not blink or (i // 15) % 2 == 0:
        d.ellipse([x, m + 92, x + 18, m + 110], fill=C)
    mono(d, (x + 30, m + 89), "REC", 22, W, 0.18)
    mono(d, (x + 110, m + 89), timecode(i), 22, G5, 0.12)
    if counter:
        mono(d, (FW - m - 34 - mono_w(d, counter, 22, 0.18), m + 89), counter, 22, W, 0.18)


def slam(img: Image.Image, text: str, f, x: float, y: float, t: float, fill=W) -> None:
    """Type that lands: drawn large and settles to size in five frames, its cyan ghost closing in."""
    if t <= 0:
        return
    k = ease_back(t)
    size = int(f.size * (1.28 - 0.28 * k))
    ff = face(DISPLAY, size)
    g = 6 + 30 * (1 - ease_out(t))
    d = ImageDraw.Draw(img)
    d.text((x - g, y + g * 0.66), text, font=ff, fill=C, anchor="ls")
    d.text((x, y), text, font=ff, fill=fill, anchor="ls")


def fade_text(img: Image.Image, xy, text: str, f, fill, alpha: float, anchor: str = "ls") -> Image.Image:
    if alpha <= 0:
        return img
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=f, fill=fill + (int(255 * clamp(alpha)),), anchor=anchor)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def iris_over(img: Image.Image, opening: float) -> Image.Image:
    """Aperture blades over the frame; opening 1 is wide open, 0 is shut."""
    if opening >= 0.999:
        return img
    d = ImageDraw.Draw(img)
    R = math.hypot(FW, FH) / 2 + 40
    r = max(1.0, R * 0.98 * opening)
    blades(d, FW / 2, FH / 2, r, R, 7, -math.pi / 2 + 0.6 * (1 - opening), shades=((24, 24, 27), (38, 38, 43)))
    return img


def tear(img: Image.Image, strength: float, seed: int) -> Image.Image:
    """An RGB tear: the channels slip apart and bands of the frame jump sideways."""
    r, g, b = img.split()
    off = int(34 * strength)
    img = Image.merge("RGB", (ImageChops.offset(r, off, 0), g, ImageChops.offset(b, -off, 0)))
    out = img.copy()
    rnd = (seed * 9301 + 49297) % 233280
    for band in range(6):
        rnd = (rnd * 9301 + 49297) % 233280
        y0 = rnd % FH
        hgt = 30 + (rnd // 7) % 140
        shift = int(((rnd // 13) % 160 - 80) * strength)
        strip = img.crop((0, y0, FW, min(FH, y0 + hgt)))
        out.paste(ImageChops.offset(strip, shift, 0), (0, y0))
    return out


def logo(img: Image.Image, x: int, y: int, height: int, ring: float, blade: float, dot: float, word: float,
         name: str = "Event Caliber") -> int:
    """The Aperture logo drawn in stages (render/brand.py draws the finished one): the ring sweeps,
    the grey blade lands, the cyan point lights, the wordmark wipes on. Returns its width."""
    k = (height * 1.6) / 144.0
    ss = 3
    size = int(152 * k * ss)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy, r, w = 76 * k * ss, 76 * k * ss, 72 * k * ss, max(1, int(20 * k * ss))
    box = [cx - r, cy - r, cx + r, cy + r]
    if ring > 0:
        d.arc(box, start=50.8, end=50.8 + (309.2 - 50.8) * ease_out(ring), fill=W, width=w)
    if blade > 0:
        d.arc(box, start=307.0, end=307.0 + 19.4 * ease_out(blade), fill=(140, 140, 147), width=w)
    if dot > 0:
        rr = 13 * k * ss * ease_back(dot)
        dx, dy = cx - 6.8 * k * ss, cy
        if dot < 1:
            glow = rr * 2.4 * (1 - dot)
            d.ellipse([dx - glow, dy - glow, dx + glow, dy + glow], fill=C + (90,))
        d.ellipse([dx - rr, dy - rr, dx + rr, dy + rr], fill=C)
    layer = layer.resize((size // ss, size // ss), Image.LANCZOS)
    img.paste(layer, (x, y), layer)
    first, _, rest = name.upper().partition(" ")
    f = face(DISPLAY, int(40 * k))
    tx = x + int(146 * k)
    wd = int(max(tracked_width(ImageDraw.Draw(img), first, f, 0.05), tracked_width(ImageDraw.Draw(img), rest, f, 0.05)))
    if word > 0:
        words = Image.new("RGBA", (wd + 10, int(152 * k)), (0, 0, 0, 0))
        wdraw = ImageDraw.Draw(words)
        tracked(wdraw, (0, int(36 * k)), first, f, W, 0.05)
        tracked(wdraw, (0, int(88 * k)), rest, f, (140, 140, 147), 0.05)
        cut = int((wd + 10) * ease_out(word))
        if cut > 0:
            part = words.crop((0, 0, cut, words.height))
            img.paste(part, (tx, y), part)
    return tx - x + wd


# --------------------------------------------------------------------------- the reel
def total_frames(n_clips: int = len(TRANSITIONS)) -> int:
    return INTRO + CLIP * n_clips + MONTAGE_SHOT * MONTAGE_SHOTS + END


def make(clips: Sequence[Clip], copy: ReelCopy, *, out: Path, montage: Optional[Sequence] = None,
         official: bool = False, encoder: Optional[Callable] = None, frames_dir: Optional[Path] = None,
         only: Optional[Sequence[int]] = None) -> Path:
    """Render the reel to `out` (mp4). `encoder(frames, out)` replaces ffmpeg in tests and `only`
    draws just those frame numbers; `frames_dir` also keeps every 15th frame as a JPEG for review."""
    check_copy(copy.words(), *(f"{c.word} {c.line}" for c in clips), official=official)
    if len(clips) != len(TRANSITIONS):
        raise ValueError(f"the reel takes {len(TRANSITIONS)} clips")
    plates = [Plate(c.photo, c.focus) for c in clips]
    shots = [Plate(p, f) for p, f in (montage or [(c.photo, c.focus) for c in clips])]
    grain = Grain()
    shade = foot_gradient(FW, FH, 0.42, 0.9, 1.1)
    top_shade = foot_gradient(FW, FH, 0.86, 0.55, 1.0).transpose(Image.FLIP_TOP_BOTTOM)
    deep_top = foot_gradient(FW, FH, 0.4, 0.92, 0.6).transpose(Image.FLIP_TOP_BOTTOM)
    light_foot = foot_gradient(FW, FH, 0.7, 0.6, 1.2)
    black = Image.new("RGB", (FW, FH), K)
    clip_start = [INTRO + CLIP * k for k in range(len(clips))]
    m_start = INTRO + CLIP * len(clips)
    e_start = m_start + MONTAGE_SHOT * MONTAGE_SHOTS
    total = total_frames(len(clips))
    word_font = {id(c): fit(ImageDraw.Draw(black), [c.word], DISPLAY, 900, 176, 90) for c in clips}

    def clip_frame(k: int, f: int, i: int) -> Image.Image:
        c = clips[k]
        t = f / CLIP
        zoom = 1.0 + (0.1 * ease_out(t) if k % 2 == 0 else 0.12 * (1 - ease_out(t)))
        img = plates[k].frame(zoom, 0.25 * (t - 0.5) * (1 if k % 2 else -1), 0.0)
        upper = c.af[1] > 0.55                # the subject sits low: the type goes up, out of its way
        img = Image.composite(black, img, deep_top if upper else top_shade)
        img = Image.composite(black, img, light_foot if upper else shade)
        d = ImageDraw.Draw(img)
        hud(d, i, f"N°{k + 1:02d} / {len(clips):02d}")
        ax, ay = c.af[0] * FW, c.af[1] * FH
        lock = ease_back(f / 8)
        bw, bh = 250 * (1.9 - 0.9 * lock), 190 * (1.9 - 0.9 * lock)
        af_box(d, ax, ay, bw, bh, 5, C if f >= 8 else W, "AF LOCK" if f >= 9 else "", 1.25)
        scale_v(d, FW - 56 - 34, 330, 1000, 1.25, pointer=330 + (ay - 330) * ease_out(f / 10), side=-1)
        base = 560 if upper else 1300
        slam(img, c.word, word_font[id(c)], 76, base, (f - 4) / 5)
        lf = face(BODY, 40)
        lines = wrap(d, c.line, lf, SAFE_RIGHT - 80)[:2]
        for j, ln in enumerate(lines):
            img = fade_text(img, (80, base + 76 + j * 52), ln, lf, W if upper else G5, (f - 11) / 6)
        return img

    def montage_frame(n: int, f: int, i: int) -> Image.Image:
        z = 1.18 if n % 2 else 1.06
        img = shots[n % len(shots)].frame(z + 0.04 * f / MONTAGE_SHOT, 0.3 * ((n % 3) - 1), 0.1 * ((n % 2) * 2 - 1))
        img = Image.composite(black, img, shade)
        d = ImageDraw.Draw(img)
        hud(d, i, "", blink=False)
        mf = fit(d, list(copy.montage), DISPLAY, 920, 230, 120)
        if n < MONTAGE_SHOTS // 2:
            t0 = (n * MONTAGE_SHOT + f) / 4
            for j, t in enumerate(copy.montage):
                slam(img, t, mf, 70, 980 + j * int(mf.size * 1.0), t0 - j * 0.6)
        else:
            t0 = ((n - MONTAGE_SHOTS // 2) * MONTAGE_SHOT + f) / 4
            bf = fit(d, [copy.block], DISPLAY, 860, int(mf.size * 0.82), 80)
            tw = d.textlength(copy.block, font=bf)
            wipe = ease_out(t0)
            y = 1060
            d.rectangle([70, y - bf.size * 0.9, 70 + (tw + 60) * wipe, y + bf.size * 0.3], fill=C)
            if wipe > 0.6:
                d.text((100, y), copy.block, font=bf, fill=K, anchor="ls")
        if f == 0 and n % 3 == 0:
            img = Image.blend(img, Image.new("RGB", (FW, FH), W), 0.55)
        return img

    def end_frame(f: int, i: int) -> Image.Image:
        img = black.copy()
        d = ImageDraw.Draw(img)
        lh = 120
        lw = logo(Image.new("RGB", (10, 10)), 0, 0, lh, 1, 1, 1, 1)
        lx, ly = int((FW - lw) / 2), 560
        logo(img, lx, ly, lh, f / 16, (f - 14) / 5, (f - 18) / 7, (f - 22) / 12)
        d = ImageDraw.Draw(img)
        tg = copy.tagline.upper()
        tf = face(MONO, 26)
        tw = tracked_width(d, tg, tf, 0.2)
        if f > 34:
            n = int(len(tg) * clamp((f - 34) / 16))
            tracked(d, ((FW - tw) / 2, 900), tg[:n], tf, G5, 0.2)
        by, bw_, bh_ = 1080, 860, 128
        bx = (FW - bw_) / 2
        wipe = ease_out((f - 52) / 9)
        if wipe > 0:
            d.rectangle([bx, by, bx + bw_ * wipe, by + bh_], fill=C)
            if wipe > 0.95:
                af_ = face(MONO, 44)
                label = copy.ask.upper() + "  ↗"
                lw_ = tracked_width(d, label, af_, 0.1)
                tracked(d, (bx + (bw_ - lw_) / 2, by + 36), label, af_, K, 0.1)
                k2 = ease_back((f - 60) / 8)
                g = 26 * (1.4 - 0.4 * k2)
                brackets(d, bx - g, by - g, bx + bw_ + g, by + bh_ + g, 40, 5, C)
        if f > 66:
            site = copy.site.upper()
            sf = face(MONO, 38)
            n = int(len(site) * clamp((f - 66) / 14))
            sw = tracked_width(d, site, sf, 0.16)
            tracked(d, ((FW - sw) / 2, 1290), site[:n], sf, W, 0.16)
            if (i // 8) % 2 == 0 and n < len(site):
                cx = (FW - sw) / 2 + tracked_width(d, site[:n], sf, 0.16) + 6
                d.rectangle([cx, 1290, cx + 22, 1330], fill=C)
        brackets(d, 56, 116, FW - 56, SAFE_BOTTOM + 60, 90, 5, G3)
        return img

    def frame(i: int) -> Image.Image:
        if i < INTRO:
            img = black.copy()
            d = ImageDraw.Draw(img)
            t = ease_out(i / 10)
            m = 56
            cx, cy = FW / 2, FH / 2
            brackets(d, cx - (cx - m) * t, cy - (cy - m - 60) * t, cx + (cx - m) * t, cy + (SAFE_BOTTOM + 60 - cy) * t, 90, 5, W)
            if i > 8:
                x = m + 34
                if (i // 6) % 2 == 0:
                    d.ellipse([x, m + 92, x + 18, m + 110], fill=C)
                mono(d, (x + 30, m + 89), "REC", 22, W, 0.18)
                mono(d, (x + 110, m + 89), timecode(i), 22, G5, 0.12)
            if i > 12:
                name = "EVENT CALIBER"
                n = int(len(name) * clamp((i - 12) / 10))
                tf = face(MONO, 34)
                tw = tracked_width(d, name, tf, 0.3)
                tracked(d, ((FW - tw) / 2, cy + 190), name[:n], tf, W, 0.3)
            if i > 16:
                lock = ease_back((i - 16) / 8)
                af_box(d, cx, cy, 300 * (2 - lock), 230 * (2 - lock), 5, C if i > 24 else W, "AF LOCK" if i > 25 else "", 1.25)
            if i >= INTRO - 6:                     # the shutter opens on the first clip
                img = iris_over(clip_frame(0, 0, i), (i - (INTRO - 6)) / 6)
            return img
        if i < m_start:
            k = (i - INTRO) // CLIP
            f = (i - INTRO) % CLIP
            img = clip_frame(k, f, i)
            kind = TRANSITIONS[k]
            last = k == len(clips) - 1
            if kind == "shutter" and not last and f >= CLIP - 5:
                img = iris_over(img, 1 - (f - (CLIP - 6)) / 5)
            if k > 0 and TRANSITIONS[k - 1] == "shutter" and f < 5:
                img = iris_over(img, (f + 1) / 5)
            if k > 0 and TRANSITIONS[k - 1] == "flash" and f < 3:
                img = Image.blend(img, Image.new("RGB", (FW, FH), W), (1.0, 0.55, 0.2)[f])
            if k > 0 and TRANSITIONS[k - 1] == "tear" and f < 3:
                img = tear(img, (1.0, 0.6, 0.25)[f], i)
            if kind == "tear" and f >= CLIP - 2:
                img = tear(img, 0.5 + 0.5 * (f - (CLIP - 2)), i)
            return grain(img, i)
        if i < e_start:
            n = (i - m_start) // MONTAGE_SHOT
            return grain(montage_frame(n, (i - m_start) % MONTAGE_SHOT, i), i)
        return grain(end_frame(i - e_start, i), i, 0.22)

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

    return (encoder or encode)(frames(), out)


def encode(frames, out: Path, size=(FW, FH), fps: int = FPS) -> Path:
    """Pipe RGB frames to ffmpeg: H.264, yuv420p, faststart, what Instagram and Facebook take."""
    cmd = [ffmpeg_path(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for img in frames:
            proc.stdin.write(img.tobytes())
    finally:
        proc.stdin.close()
        code = proc.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg stopped with code {code}; no reel made")
    return out
