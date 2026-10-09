"""Pure functions for the website build: sitemap.xml, robots.txt and JSON-LD blocks.

Nothing here reads the database or the network. Every piece of copy a
visitor or a search engine can read (image titles and captions in the
sitemap, the business description, the image credit) passes
ai.copy_rules.check first; a refusal raises SeoCopyRefused so the build stops
instead of publishing it (the same way site.build raises SiteCopyRefused).

No street address goes in the business block, and no telephone unless one is
passed in. The image block carries only contentUrl, creator, copyrightHolder,
copyrightNotice and creditText (founder ruling 2026-10-09: no field whose
name contains a word on the banned list, standard or not).
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional
from xml.sax.saxutils import escape

from ..ai import copy_rules

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
IMAGE_NS = "http://www.google.com/schemas/sitemap-image/1.1"
SCHEMA_CONTEXT = "https://schema.org"
DEFAULT_PAGES = ("/", "/book/", "/availability/", "/privacy/")
ROBOTS_DISALLOW = ("/api/", "/thanks/")
_ABSOLUTE = re.compile(r"^https?://", re.IGNORECASE)


class SeoCopyRefused(ValueError):
    pass


def public(text: str, what: str) -> str:
    """The text, stripped, when it passes the copy rules; else SeoCopyRefused."""
    text = (text or "").strip()
    report = copy_rules.check(text)
    if not report.ok:
        raise SeoCopyRefused(f"{what} {text[:60]!r}: {report.blocks[0].message}")
    return text


def absolute(base_url: str, path: str) -> str:
    """'/book/' -> 'https://eventcaliber.com/book/'; an absolute URL is kept as it is."""
    path = (path or "").strip()
    if _ABSOLUTE.match(path):
        return path
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _x(text: str) -> str:
    return escape(text, {'"': "&quot;"})


def sitemap_xml(base_url: str, pages: Iterable[str], images: Optional[dict[str, list[dict]]] = None) -> str:
    """A sitemap with an image:image entry (loc, title, caption) for each image on each page.

    `pages` are paths ('/', '/book/') or absolute URLs, in the order to list them. `images` maps a
    page, written the same way, to [{"loc": ..., "title": ..., "caption": ...}]; an image's loc may
    be a path. A page that has images but is missing from `pages` is listed after them. Each page
    is listed once. Titles and captions must pass the copy rules (SeoCopyRefused otherwise)."""
    images = images or {}
    order = list(pages) + [p for p in images if p not in list(pages)]
    seen: set[str] = set()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<urlset xmlns="{SITEMAP_NS}" xmlns:image="{IMAGE_NS}">']
    for page in order:
        loc = absolute(base_url, page)
        if loc in seen:
            continue
        seen.add(loc)
        lines.append("  <url>")
        lines.append(f"    <loc>{_x(loc)}</loc>")
        for img in images.get(page) or []:
            if not isinstance(img, dict) or not (img.get("loc") or "").strip():
                continue
            lines.append("    <image:image>")
            lines.append(f"      <image:loc>{_x(absolute(base_url, img['loc']))}</image:loc>")
            if (img.get("title") or "").strip():
                lines.append(f"      <image:title>{_x(public(img['title'], 'image title'))}</image:title>")
            if (img.get("caption") or "").strip():
                lines.append(f"      <image:caption>{_x(public(img['caption'], 'image caption'))}</image:caption>")
            lines.append("    </image:image>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def robots_txt(base_url: str) -> str:
    """Everything may be crawled except the form endpoints and the thank-you page; the sitemap is named."""
    lines = ["User-agent: *", "Allow: /"] + [f"Disallow: {p}" for p in ROBOTS_DISALLOW]
    lines += ["", f"Sitemap: {absolute(base_url, '/sitemap.xml')}"]
    return "\n".join(lines) + "\n"


def jsonld_business(brand: str, legal_name: str, url: str, email: str, description: str, *,
                    telephone: Optional[str] = None, same_as: Optional[list[str]] = None) -> dict:
    """schema.org ProfessionalService for the company. No address ever; a telephone only when given;
    sameAs may be empty. The description must pass the copy rules."""
    data = {
        "@context": SCHEMA_CONTEXT,
        "@type": "ProfessionalService",
        "name": brand,
        "legalName": legal_name,
        "url": url,
        "email": email,
        "description": public(description, "business description"),
        "sameAs": list(same_as or []),
    }
    if telephone and telephone.strip():
        data["telephone"] = telephone.strip()
    return data


def jsonld_image(url: str, creator: str, copyright_holder: str, credit: str) -> dict:
    """schema.org ImageObject for one photo: contentUrl, creator (an Organization), copyrightHolder,
    copyrightNotice and creditText, nothing else. `credit` is the visible credit (the brand, plus a
    recorded handle when there is one); it must pass the copy rules."""
    return {
        "@context": SCHEMA_CONTEXT,
        "@type": "ImageObject",
        "contentUrl": url,
        "creator": {"@type": "Organization", "name": creator},
        "copyrightHolder": {"@type": "Organization", "name": copyright_holder},
        "copyrightNotice": f"© {copyright_holder}",
        "creditText": public(credit or creator, "image credit"),
    }


def jsonld_script(data: dict) -> str:
    """The <script> tag for a JSON-LD block, safe to drop into a page."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'<script type="application/ld+json">{text}</script>'
