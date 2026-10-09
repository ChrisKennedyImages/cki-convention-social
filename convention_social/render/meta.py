"""What travels inside every image the suite publishes: our words, never the camera's.

The original's EXIF (GPS, camera, lens, serial numbers, capture time) never
leaves the Mini: every published JPEG is saved fresh from pixels. Into that
fresh file go only descriptive fields that help search and credit the work:

  XMP (IPTC Core / Dublin Core): title, description, keywords, creator,
  copyright notice, credit line, headline, rights marked and the web
  statement (Google Images reads these for the creator and credit).
  EXIF: ImageDescription, Artist, Copyright, the same words.

`save_jpeg(img, path, meta)` is the one way a published image is written.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Sequence
from xml.sax.saxutils import escape

from PIL import Image

from ..core import config

TAG_DESCRIPTION, TAG_ARTIST, TAG_COPYRIGHT = 0x010E, 0x013B, 0x8298


@dataclass
class ImageMeta:
    title: str = ""
    description: str = ""
    keywords: Sequence[str] = field(default_factory=tuple)
    credit: str = ""              # e.g. "Cosplay: @handle"; the photographer credit is always the company

    def creator(self) -> str:
        return config.get_config().brand_name

    def rights(self) -> str:
        cfg = config.get_config()
        return f"© {date.today().year} {cfg.legal_name}. All rights reserved."

    def site(self) -> str:
        return f"https://{config.get_config().brand_domain}"


def _bag(items: Sequence[str]) -> str:
    return "".join(f"<rdf:li>{escape(i)}</rdf:li>" for i in items if i)


def _alt(text: str) -> str:
    return f'<rdf:Alt><rdf:li xml:lang="x-default">{escape(text)}</rdf:li></rdf:Alt>'


def xmp_packet(meta: ImageMeta) -> bytes:
    site = meta.site()
    credit = " ".join(x for x in (meta.creator(), meta.credit) if x)
    body = f"""<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about=""
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
 xmlns:xmpRights="http://ns.adobe.com/xap/1.0/rights/"
 photoshop:Credit="{escape(credit)}" photoshop:Headline="{escape(meta.title)}"
 xmpRights:Marked="True" xmpRights:WebStatement="{escape(site)}/privacy/">
<dc:title>{_alt(meta.title)}</dc:title>
<dc:description>{_alt(meta.description)}</dc:description>
<dc:creator><rdf:Seq><rdf:li>{escape(meta.creator())}</rdf:li></rdf:Seq></dc:creator>
<dc:rights>{_alt(meta.rights())}</dc:rights>
<dc:subject><rdf:Bag>{_bag(meta.keywords)}</rdf:Bag></dc:subject>
</rdf:Description></rdf:RDF></x:xmpmeta>"""
    return body.encode("utf-8")


def exif_for(meta: ImageMeta) -> bytes:
    ex = Image.Exif()
    if meta.description or meta.title:
        ex[TAG_DESCRIPTION] = (meta.description or meta.title)[:500]
    ex[TAG_ARTIST] = meta.creator()
    ex[TAG_COPYRIGHT] = meta.rights()
    return ex.tobytes()


def save_jpeg(img: Image.Image, path: Path, meta: Optional[ImageMeta] = None, *, quality: int = 90) -> Path:
    """A fresh JPEG from pixels: no camera data, no GPS; our descriptive fields when `meta` is given."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = meta or ImageMeta()
    img.convert("RGB").save(path, format="JPEG", quality=quality, optimize=True, progressive=True,
                            exif=exif_for(meta), xmp=xmp_packet(meta))
    return path


def is_clean(path: Path) -> list[str]:
    """What should not be in a published file, if anything: [] means clean (no GPS, no camera, no capture time)."""
    found = []
    with Image.open(path) as im:
        ex = im.getexif()
        if 0x8825 in ex or ex.get_ifd(0x8825):
            found.append("gps")
        for tag, name in ((271, "camera make"), (272, "camera model"), (0xA431, "serial")):
            if tag in ex:
                found.append(name)
        sub = ex.get_ifd(0x8769)
        for tag, name in ((36867, "capture time"), (0xA431, "serial"), (0xA434, "lens")):
            if tag in sub:
                found.append(name)
    return found


SHOT_WORDS = {"cosplay_portrait": "Cosplay portrait", "portrait": "Portrait", "group": "Group photo", "candid": "Candid moment",
              "stage_panel": "Stage and panel", "vendor_hall": "Vendor hall", "booth": "Booth", "backstage": "Backstage",
              "dinner_reception": "Dinner and reception", "headshot": "Headshot", "crowd": "Crowd", "venue": "Venue",
              "building_exterior": "Building exterior", "building_interior": "Building interior"}


def for_photo(conn, row) -> ImageMeta:
    """Our descriptive fields for one library photo: the SEO agent's text when it has written some
    (photo_seo), else plain words from the photo's sorting."""
    row = dict(row)
    pid = row.get("id")
    try:
        seo = conn.execute("SELECT * FROM photo_seo WHERE photo_id=?", (pid,)).fetchone()
    except Exception:  # noqa: BLE001 — the SEO table may not exist yet
        seo = None
    credit = row.get("credit") or ""
    credit_line = f"Cosplay: {credit}" if credit and row.get("shot_type") == "cosplay_portrait" else (f"Featuring {credit}" if credit else "")
    if seo is not None:
        import json as _json
        try:
            kws = _json.loads(seo["keywords"] or "[]")
        except ValueError:
            kws = []
        return ImageMeta(title=seo["title"] or "", description=seo["alt"] or seo["description"] or "", keywords=kws, credit=credit_line)
    shot = SHOT_WORDS.get(row.get("shot_type") or "", "")
    year = (row.get("taken_at") or "")[:4]
    if row.get("subject") == "architecture":
        title = f"{shot or 'Architecture'} photography"
        kws = ["architectural photography", "venue photography", "event venue", "building photography"]
    else:
        event = row.get("convention_name") or ""
        title = " ".join(x for x in (shot or "Event photography", f"at {event}" if event else "", year if year.isdigit() else "") if x)
        kws = ["event photography", "convention photography"] + (["cosplay photography"] if row.get("event_kind") == "fan" else
                                                                  ["conference photography"] if row.get("event_kind") == "business" else [])
        if event:
            kws.append(event)
    return ImageMeta(title=title, description=row.get("summary") or title, keywords=kws, credit=credit_line)
