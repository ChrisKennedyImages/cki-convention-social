"""Synthetic photos for tests: a colored JPEG with optional EXIF (date + GPS)."""
from __future__ import annotations

import io

from PIL import Image


def jpeg_bytes(color=(120, 80, 40), size=(1600, 1200), *, with_exif: bool = True, seed: int = 0) -> bytes:
    im = Image.new("RGB", size, color)
    im.putpixel((seed % size[0], 0), (255, 255, 255))  # distinct bytes per seed
    buf = io.BytesIO()
    if with_exif:
        exif = Image.Exif()
        exif[306] = "2026:09:20 14:31:00"
        exif.get_ifd(0x8769)[36867] = "2026:09:20 14:31:00"
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"; gps[2] = (38.0, 30.0, 0.0); gps[3] = "W"; gps[4] = (76.0, 40.0, 0.0)
        im.save(buf, format="JPEG", quality=90, exif=exif.tobytes())
    else:
        im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()
