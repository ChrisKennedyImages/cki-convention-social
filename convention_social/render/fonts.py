"""Finding typefaces at run time. No font file lives in this repo.

Search order: DATA_ROOT/fonts (where scripts/setup.sh puts the brand fonts
Chris picks), then the macOS and Linux system font folders. `font(role, size)`
returns the first face that exists for that role, falling back to Pillow's
built-in face so a render never crashes for want of a font.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from ..core import config

ROLES = {
    "display": ("InterDisplay-Bold.otf", "Inter-Bold.otf", "HelveticaNeue.ttc", "Helvetica.ttc", "DejaVuSans-Bold.ttf"),
    "display_black": ("InterDisplay-Black.otf", "Inter-Black.otf", "HelveticaNeue.ttc", "DejaVuSans-Bold.ttf"),
    "body": ("Inter-Regular.otf", "InterDisplay-Regular.otf", "HelveticaNeue.ttc", "Helvetica.ttc", "DejaVuSans.ttf"),
    "body_medium": ("Inter-Medium.otf", "InterDisplay-Medium.otf", "HelveticaNeue.ttc", "DejaVuSans.ttf"),
    "serif": ("Caladea-Regular.ttf", "LiberationSerif-Regular.ttf", "NewYork.ttf", "Georgia.ttf", "DejaVuSerif.ttf"),
    "serif_bold": ("Caladea-Bold.ttf", "LiberationSerif-Bold.ttf", "Georgia Bold.ttf", "DejaVuSerif-Bold.ttf"),
    "mono": ("DejaVuSansMono.ttf", "Menlo.ttc", "LiberationMono-Regular.ttf"),
}


def search_dirs() -> list[Path]:
    dirs = [config.get_config().data_root / "fonts", Path.home() / "Library" / "Fonts", Path("/Library/Fonts"),
            Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/usr/share/fonts")]
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=256)
def _find(name: str) -> str | None:
    for d in search_dirs():
        direct = d / name
        if direct.exists():
            return str(direct)
        for hit in d.rglob(name):
            return str(hit)
    return None


def font(role: str, size: int) -> ImageFont.ImageFont:
    for name in ROLES.get(role, ROLES["body"]):
        path = _find(name)
        if path:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)
