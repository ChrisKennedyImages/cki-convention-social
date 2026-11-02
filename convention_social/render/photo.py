"""The photo as shot, for LinkedIn. The coordinator suggested, 2026-11-01 evening: "On a personal profile, the photo alone
with your caption may read more like you and less like an ad. Instagram would stay as it is." Chris: "Let's do that."

No crop, no frame, no text, no mark, no Request a quote, and no light or effect over it (his standing rule: photos render
exactly as shot). It is the library copy's pixels, orientation applied, re-encoded as a fresh JPEG like every file the
suite publishes (no camera data, no GPS; our descriptive fields inside, render/meta.py), and made smaller only when a
limit asks for it.

The limits, read on 2026-11-01, never recalled: Buffer takes an image under 10 MB on LinkedIn (support.buffer.com, "Ideal
image sizes and formats for your Buffer posts", the LinkedIn table: JPG among the formats, 10 MB); LinkedIn's API takes
an image under 5 MB with fewer than 36,152,320 pixels (LinkedIn's media limits as ayrshare.com/docs/media-guidelines/linkedin
documents them). A library copy is at most storage.MAX_EDGE (3000 px) on its long side, six megapixels, so in practice
nothing here is resized; the guard stands for the day a copy comes in larger. LinkedIn's own note (quoted on Buffer's page)
says a 3:2 image displays whole on the mobile app.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from .meta import ImageMeta, save_jpeg

LINKEDIN_PHOTO = "linkedin"          # the render_paths key: the hero as shot, what LinkedIn posts
MAX_BYTES = 5 * 1024 * 1024          # LinkedIn's 5 MB; Buffer's own ceiling is 10 MB
MAX_PIXELS = 36_152_320              # LinkedIn's pixel ceiling
QUALITY = 92                         # the clean copy's quality (agents/publisher.clean_copy)
LEAST_QUALITY = 85                   # below this the picture shrinks instead


def as_shot(image: Image.Image, out: Path, *, meta: Optional[ImageMeta] = None) -> Path:
    """The photo whole, in its own aspect ratio, at the smallest change the limits allow: quality first, then size."""
    im = ImageOps.exif_transpose(image).convert("RGB")
    if im.width * im.height > MAX_PIXELS:
        scale = (MAX_PIXELS / (im.width * im.height)) ** 0.5
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    quality = QUALITY
    while True:
        save_jpeg(im, out, meta, quality=quality)
        if Path(out).stat().st_size <= MAX_BYTES:
            return Path(out)
        if quality > LEAST_QUALITY:
            quality -= 3
        else:
            im = im.resize((max(1, int(im.width * 0.85)), max(1, int(im.height * 0.85))), Image.LANCZOS)
