"""Search for eventcaliber.com and the post images.

  markup.py      pure functions the site build calls: sitemap.xml, robots.txt, JSON-LD
  photo_text.py  slug, title, alt text, description and keywords per photo (table photo_seo)
  site_check.py  the weekly read-only look at the public pages (table site_checks)

The agent that runs the last two is agents/seo.py.
"""
from .markup import (DEFAULT_PAGES, SeoCopyRefused, absolute, jsonld_business, jsonld_image, jsonld_script,
                     robots_txt, sitemap_xml)

__all__ = ["DEFAULT_PAGES", "SeoCopyRefused", "absolute", "jsonld_business", "jsonld_image", "jsonld_script",
           "robots_txt", "sitemap_xml"]
