"""The logos under the hero on the home page: "We've photographed for" (Chris, 2026-10-15).

Kept apart from site/build.py, which (like offer.json) never says the company is political (2026-10-12, pinned by
tests/test_seo_captions.py); this module is where the strip keeps political organizations from ever being most of it.
"""
from __future__ import annotations

import html
import re
import shutil
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from .. import offer


# ------------------------------------------------------------------ the logos under the hero (Chris, 2026-10-15)
# "should we add the companies we have worked for on the website? like their logos and say we have worked with them?",
# then "it can be political organizations, i just dont want them the only thing on the site". His answers when asked:
# under the top photo on the home page, in their own colours, headed "We've photographed for", no permission needed.
# The list is offer.json `clients`; the files are under site/clients/ as he sent them.
LOGO_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".svg")
LOGO_H = 120                       # stored height in pixels: twice the tallest a logo is shown (60 px on a computer)
SVG_UNSAFE = re.compile(rb"<script|javascript:|<foreignObject|\bon[a-z]+\s*=|(?:href|src)\s*=\s*[\"']?\s*(?:https?:)?//", re.I)


def logos_dir() -> Path:
    return offer.path().parent / "site" / "clients"


def client_logos(o: Optional[dict] = None) -> tuple[list[dict], list[str]]:
    """The logos the home page shows, in order, and why any listed one is left out (said on the Agents page).

    Nothing unless `clients.show` is true. A logo needs its name and its file (under site/clients/; an SVG with a
    script or a link to elsewhere is refused). Fail closed on politics: an entry counts as political unless it says
    `spread: false` (offer.json says "spread", not the word itself: nothing there positions the company, 2026-10-12). Political logos never outnumber the others ("i just dont want them the only thing on the site"):
    a non-political logo comes first, the political ones are spread evenly through the row and never side by side, and
    a political one past the count waits for another."""
    block = (o or offer.load()).get("clients") or {}
    if not block.get("show"):
        return [], []
    base, ok, why = logos_dir().resolve(), [], []
    for c in block.get("list") or []:
        name = " ".join(str(c.get("name") or "").split())
        file = str(c.get("logo") or "")
        path = (offer.path().parent / file).resolve() if file else None
        if not name:
            why.append(f"a logo with no name ({file or 'no file'})")
        elif path is None or not path.is_file() or path.suffix.lower() not in LOGO_TYPES or base not in path.parents:
            why.append(f"{name}: no logo file under site/clients/ ({file or 'none listed'})")
        elif path.suffix.lower() == ".svg" and SVG_UNSAFE.search(path.read_bytes()):
            why.append(f"{name}: its SVG carries a script or a link to elsewhere; send a PNG instead")
        else:
            ok.append({"name": name, "path": path, "political": c.get("spread") is not False})
    plain = [c for c in ok if not c["political"]]
    political = [c for c in ok if c["political"]]
    why += [f"{c['name']}: waits for another non-political logo (political logos never outnumber the others)"
            for c in political[len(plain):]]
    political = political[:len(plain)]
    after: dict[int, dict] = {}                 # the political logo set after the k-th non-political one
    k = 0
    for i, c in enumerate(political):
        k = max(k + 1, round((i + 1) * len(plain) / (len(political) + 1)))
        k = min(k, len(plain) - (len(political) - 1 - i))
        after[k] = c
    shown = []
    for j, c in enumerate(plain, start=1):
        shown.append(c)
        if j in after:
            shown.append(after[j])
    return shown, why


# Chris, 2026-10-16, on the strip live: "The white background on the logos are intense! Could it be a scroller too without the
# white background?"; asked how: "Their own colors, no tiles" and "Same speed as the ticker". Each logo sits on the site's
# black as itself; ink too dark to read there gets a light version, and the brand colours stay as they are.
SITE_BLACK, SITE_LIGHT = (10, 10, 11), (243, 243, 241)          # theme.CSS --k and --w
READS = 3.0           # the least a graphic needs to read on the black (WCAG 2 non-text contrast)
LIFT_TO = 4.5         # ink under this is lifted, and lifted to here, so it reads clearly rather than only just (Bozzuto's
#                       green sits on 3 to 1 itself, half its pixels either side, and would be split in two)
NEUTRAL = 0.04        # OKLCH chroma under this is black, grey or near it: it becomes the site's light
COLOUR = 0.15         # chroma at or over this is a brand colour (the Nationals red, the AHA red): kept as it is


def unbox(im: Image.Image) -> Image.Image:
    """A logo drawn on an opaque white box (the AP's) loses the box: white becomes clear and the ink keeps its own
    colour and edge (colour to alpha against white). A logo with a clear edge is left alone."""
    w, h = im.size
    px = im.load()
    edge = [px[x, y] for x in range(w) for y in (0, h - 1)] + [px[x, y] for x in (0, w - 1) for y in range(h)]
    if sum(1 for r, g, b, a in edge if a > 240 and min(r, g, b) > 240) < 0.9 * len(edge):
        return im
    out = Image.new("RGBA", im.size)
    o = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            alpha = max((255 - r), (255 - g), (255 - b)) / 255
            if alpha <= 0.02:
                o[x, y] = (0, 0, 0, 0)
                continue
            o[x, y] = tuple(max(0, min(255, round(255 - (255 - c) / alpha))) for c in (r, g, b)) + (round(a * alpha),)
    return out


def trim_logo(im: Image.Image) -> Image.Image:
    """The logo cut to its ink, a hair of margin kept, so the sizes compare like for like."""
    box = im.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
    if box is None:
        return im
    pad = max(2, round(0.02 * im.height))
    return im.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad)))


def light_version(rgb: tuple) -> tuple:
    """The colour a logo's ink takes on the black: as it is when it reads clearly (LIFT_TO) or is a brand colour; the
    site's light for black and grey; for a dark colour (a navy, a dark green) the same hue lifted until it reads at
    LIFT_TO."""
    from ..render import palette as pal
    if pal.contrast(rgb, SITE_BLACK) >= LIFT_TO:
        return rgb
    L, C, h = pal.lch(rgb)
    if C >= COLOUR:
        return rgb
    if C < NEUTRAL:
        return SITE_LIGHT
    for step in range(1, 60):
        L2 = min(0.97, L + 0.01 * step)
        out = pal.from_oklch(L2, min(C, pal.max_chroma(L2, h)), h)
        if pal.contrast(out, SITE_BLACK) >= LIFT_TO:
            return out
    return SITE_LIGHT


ON_THE_BLACK = 0.5    # an area of dark ink is on the site's black when at least half of what borders it is clear
SEE_THROUGH = 192     # a border pixel under this alpha lets the black through (a soft letter edge counts as the page)


def relight(im: Image.Image) -> tuple[Image.Image, float]:
    """The logo's dark ink in its light version, area by area; the share of the ink that changed (0 when the logo reads
    as it is). An area of dark ink (pixels light_version() would change, joined side to side) is relit only when it sits
    on the site's black: when at least half of what borders it is clear or see-through. Dark ink set inside the logo's own light ink
    (C.A.S.E.'s green letters on its pale tree) already reads there and keeps its colour."""
    px = im.load()
    w, h = im.size
    seen: dict[tuple, tuple] = {}

    def wanted(x: int, y: int) -> Optional[tuple]:
        r, g, b, a = px[x, y]
        if a < 16:
            return None
        got = seen.get((r, g, b))
        if got is None:
            got = seen[(r, g, b)] = light_version((r, g, b))
        return got if got != (r, g, b) else None

    ink = sum(1 for y in range(h) for x in range(w) if px[x, y][3] >= 16)
    done: set[tuple[int, int]] = set()
    changed = 0
    for y0 in range(h):
        for x0 in range(w):
            if (x0, y0) in done or wanted(x0, y0) is None:
                continue
            area, todo, clear, other = [], [(x0, y0)], 0, 0
            done.add((x0, y0))
            while todo:
                x, y = todo.pop()
                area.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if not (0 <= nx < w and 0 <= ny < h):
                        clear += 1
                    elif (nx, ny) in done:
                        continue
                    elif wanted(nx, ny) is not None:
                        done.add((nx, ny))
                        todo.append((nx, ny))
                    elif px[nx, ny][3] < SEE_THROUGH:
                        clear += 1
                    else:
                        other += 1
            if clear >= ON_THE_BLACK * (clear + other):
                for x, y in area:
                    r, g, b, a = px[x, y]
                    px[x, y] = seen[(r, g, b)] + (a,)
                changed += len(area)
    return im, (changed / ink if ink else 0.0)


def prepared(path: Path) -> tuple[Image.Image, float]:
    """The logo as the strip shows it: upright, out of any white box, cut to its ink, LOGO_H tall, relit. (image, share
    of its ink relit)."""
    with Image.open(path) as src:
        im = ImageOps.exif_transpose(src).convert("RGBA")
    if im.height > 4 * LOGO_H:
        im = im.resize((max(1, round(im.width * 4 * LOGO_H / im.height)), 4 * LOGO_H), Image.LANCZOS)
    im = trim_logo(unbox(im))
    if im.height > LOGO_H:
        im = im.resize((max(1, round(im.width * LOGO_H / im.height)), LOGO_H), Image.LANCZOS)
    return relight(im)


def optical(w: int, h: int) -> float:
    """How tall a logo is set against the strip's base height, so a wide wordmark and a square mark weigh the same:
    the height follows the square root of the area, within 0.6 and 1.3 of the base."""
    return round(max(0.6, min(1.3, (2.2 / (w / h)) ** 0.5)), 3) if w and h else 1.0


def save_logo(c: dict, out_dir: Path) -> tuple[str, int, int]:
    """The logo saved for the web under assets/clients as the strip shows it (prepared()), re-encoded from its pixels
    (no metadata travels); an SVG as sent. (file name, width, height); 0 x 0 for an SVG (its own box sizes it)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-") or "logo"
    if c["path"].suffix.lower() == ".svg":
        shutil.copyfile(c["path"], out_dir / f"{slug}.svg")
        return f"{slug}.svg", 0, 0
    im, _ = prepared(c["path"])
    im.save(out_dir / f"{slug}.png", format="PNG", optimize=True)
    return f"{slug}.png", im.width, im.height


def clients_body(heading: str, logos: list[tuple[str, str, int, int]]) -> str:
    """The strip under the hero: the heading, then the logos rolling like the ticker under it (the ticker's own class and
    keyframes; theme.CSS .ticker.logos and theme.JS set it to the ticker's speed and pause it under a hand). The run is
    doubled for the loop and the copy is hidden from readers. `logos`: (file, name, w, h)."""
    if not logos:
        return ""
    e = html.escape

    def run(copy: bool) -> str:
        return "".join(f'<li{" aria-hidden=\"true\"" if copy else ""}><img src="/assets/clients/{e(file)}" alt="{"" if copy else e(name)}"'
                       + (f' width="{w}" height="{h}" style="--k:{optical(w, h)}"' if w and h else "")
                       + ' decoding="async"></li>' for file, name, w, h in logos)      # never lazy: a lazy copy loads late as it rolls in
    return (f'<section class="clients" aria-label="{e(heading)}"><div class="kick mono c">{e(heading)}</div>'
            f'<div class="ticker logos"><ul class="track">{run(False)}{run(True)}</ul></div></section>')
