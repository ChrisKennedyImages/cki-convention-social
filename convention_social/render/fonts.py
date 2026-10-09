"""Typefaces, found at run time. No font file lives in this repo.

`fetch()` downloads the open-source families the brand directions use from
Google Fonts into DATA_ROOT/fonts (run once by scripts/setup.sh, or
`bin/ccs fonts`). `face(name, size)` loads one of FACES by its file name from
DATA_ROOT/fonts, then the macOS and Linux system folders, and falls back to
Pillow's built-in face so a render never crashes for want of a font.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from ..core import config

# file name -> (family, CSS2 axis spec, the @font-face to keep: (weight, stretch))
FACES = {
    "Fraunces-SemiBold.ttf": ("Fraunces", "opsz,wght@144,600", ("600", "normal")),
    "Fraunces-Light.ttf": ("Fraunces", "opsz,wght@144,300", ("300", "normal")),
    "InterTight-Regular.ttf": ("Inter Tight", "wght@400", ("400", "normal")),
    "InterTight-SemiBold.ttf": ("Inter Tight", "wght@600", ("600", "normal")),
    "Archivo-XCondBlack.ttf": ("Archivo", "wdth,wght@62.5,900", ("900", "extra-condensed")),
    "Archivo-CondMedium.ttf": ("Archivo", "wdth,wght@75,500", ("500", "condensed")),
    "SpaceGrotesk-Bold.ttf": ("Space Grotesk", "wght@700", ("700", "normal")),
    "SpaceGrotesk-Medium.ttf": ("Space Grotesk", "wght@500", ("500", "normal")),
}
FALLBACKS = ("Inter-Bold.otf", "HelveticaNeue.ttc", "Helvetica.ttc", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf")
CSS = "https://fonts.googleapis.com/css2?family={family}:{axes}&display=swap"


def font_dir() -> Path:
    return config.get_config().data_root / "fonts"


def search_dirs() -> list[Path]:
    dirs = [font_dir(), Path.home() / "Library" / "Fonts", Path("/Library/Fonts"), Path("/System/Library/Fonts"),
            Path("/System/Library/Fonts/Supplemental"), Path("/usr/share/fonts")]
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=256)
def _find(name: str) -> str | None:
    for d in search_dirs():
        if (d / name).exists():
            return str(d / name)
        for hit in d.rglob(name):
            return str(hit)
    return None


def face(name: str, size: int) -> ImageFont.ImageFont:
    for candidate in (name, *FALLBACKS):
        path = _find(candidate)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def font(role: str, size: int) -> ImageFont.ImageFont:
    """Neutral faces for internal sheets (contact sheet, reports)."""
    return face({"display": "InterTight-SemiBold.ttf", "body_medium": "InterTight-SemiBold.ttf"}.get(role, "InterTight-Regular.ttf"), size)


def fetch(get=None) -> list[str]:
    """Download every face in FACES that is not already in DATA_ROOT/fonts. Returns the names fetched."""
    if get is None:
        import requests
        get = lambda url, **kw: requests.get(url, timeout=30, **kw)  # noqa: E731
    out = font_dir()
    out.mkdir(parents=True, exist_ok=True)
    fetched = []
    for name, (family, axes, (weight, stretch)) in FACES.items():
        if (out / name).exists():
            continue
        css = get(CSS.format(family=family.replace(" ", "+"), axes=axes), headers={"User-Agent": "Mozilla/4.0"}).text
        url = None
        for block in css.split("@font-face")[1:]:
            if f"font-weight: {weight};" in block and (f"font-stretch: {stretch};" in block or "font-stretch" not in block):
                m = re.search(r"url\((https://[^)]+\.ttf)\)", block)
                if m:
                    url = m.group(1)
                    break
        if not url:
            continue
        (out / name).write_bytes(get(url).content)
        fetched.append(name)
    _find.cache_clear()
    return fetched
