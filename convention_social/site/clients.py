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

from PIL import Image, ImageChops, ImageOps

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
            ok.append({"name": name, "path": path, "political": c.get("spread") is not False,
                       "tile": "dark" if c.get("tile") == "dark" else "light"})
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


TILE_COLOURS = {"light": (255, 255, 255), "dark": (28, 28, 32)}       # theme.CSS .clients .tile and .tile.dark


def trim_logo(im: Image.Image, tile: str) -> Image.Image:
    """The logo cut to what shows on its tile, a hair of margin kept; on a white tile a white box behind the mark goes
    clear, so every logo sits on the tile itself and the sizes compare like for like."""
    bg = TILE_COLOURS[tile]
    shown = Image.alpha_composite(Image.new("RGBA", im.size, bg + (255,)), im).convert("RGB")
    ink = ImageChops.difference(shown, Image.new("RGB", im.size, bg)).convert("L").point(lambda v: 255 if v > 18 else 0)
    box = ink.getbbox()
    if box is None:
        return im
    pad = max(2, round(0.02 * im.height))
    im = im.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
    if tile == "light":
        r, g, b, a = im.split()
        near_white = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v > 246 else 0)
        im.putalpha(ImageChops.subtract(a, near_white))
    return im


def optical(w: int, h: int) -> float:
    """How tall a logo is set against the strip's base height, so a wide wordmark and a square mark weigh the same:
    the height follows the square root of the area, within 0.6 and 1.3 of the base."""
    return round(max(0.6, min(1.3, (2.2 / (w / h)) ** 0.5)), 3) if w and h else 1.0


def save_logo(c: dict, out_dir: Path) -> tuple[str, int, int]:
    """The logo saved for the web under assets/clients: a picture trimmed to what shows on its tile and re-encoded from
    its pixels at LOGO_H tall (no metadata travels), an SVG as sent. (file name, width, height); 0 x 0 for an SVG (its
    own box sizes it)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", c["name"].lower()).strip("-") or "logo"
    if c["path"].suffix.lower() == ".svg":
        shutil.copyfile(c["path"], out_dir / f"{slug}.svg")
        return f"{slug}.svg", 0, 0
    with Image.open(c["path"]) as src:
        im = ImageOps.exif_transpose(src).convert("RGBA")
    if im.height > 4 * LOGO_H:
        im = im.resize((max(1, round(im.width * 4 * LOGO_H / im.height)), 4 * LOGO_H), Image.LANCZOS)
    im = trim_logo(im, c.get("tile", "light"))
    if im.height > LOGO_H:
        im = im.resize((max(1, round(im.width * LOGO_H / im.height)), LOGO_H), Image.LANCZOS)
    im.save(out_dir / f"{slug}.png", format="PNG", optimize=True)
    return f"{slug}.png", im.width, im.height


def clients_body(heading: str, logos: list[tuple[str, str, str, int, int]]) -> str:
    """The strip under the hero: the heading and each logo on its own tile. `logos`: (file, name, tile, w, h)."""
    if not logos:
        return ""
    e = html.escape
    items = "".join(f'<li class="tile {tile}"><img src="/assets/clients/{e(file)}" alt="{e(name)}"'
                    + (f' width="{w}" height="{h}" style="--k:{optical(w, h)}"' if w and h else "")
                    + ' loading="lazy" decoding="async"></li>' for file, name, tile, w, h in logos)
    return (f'<section class="clients" aria-label="{e(heading)}"><div class="kick mono c">{e(heading)}</div>'
            f'<ul class="logos">{items}</ul></section>')
