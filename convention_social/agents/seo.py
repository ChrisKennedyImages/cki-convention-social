"""SEO agent (weekly, Monday 05:00): search text for photos, and a read-only look at eventcaliber.com.

1. Search text (seo/photo_text.py): a slug, title, alt text, description and
   5 to 10 keywords for every postable photo and every photo on a queued
   post, stored in photo_seo for the site build, the sitemap and post alt
   text. Live: claude-haiku-5-5 under the monthly cap, every answer checked,
   the template where an answer fails. Dry run (the default): the template
   only, no paid call; the rows are internal, so they are written.
2. The site check (seo/site_check.py), live only: GET /, /book/,
   /availability/, /privacy/, /sitemap.xml and /robots.txt on BRAND_DOMAIN,
   a site_checks row per page, an errors row for each page that fails. Dry
   run only says what it would check.

Nothing here publishes, uploads or sends anything.
"""
from __future__ import annotations

from typing import Optional

from ..core import runner
from ..seo import photo_text, site_check


def run(ctx: runner.Context, *, client=None, transport: Optional[site_check.Transport] = None) -> str:
    s = photo_text.write_all(ctx.conn, ctx.cfg, dry_run=ctx.dry_run, client=client, agent=ctx.agent)
    text = (f"seo text: {s['written']} written ({s['claude']} by {s['model'] if s['claude'] else 'Claude'}, "
            f"{s['template']} template, {s['fell_back']} fell back), {s['kept']} kept, {s['edited']} edited by Chris, "
            f"{s['left_out']} queued photos no longer usable, {s['unsorted'] + s['refused']} skipped"
            + (f"; stopped: {s['stopped']}" if s["stopped"] else ""))
    if ctx.dry_run:
        site = (f"site check not run in dry run; would GET {len(site_check.PATHS)} pages on {site_check.base_url(ctx.cfg)}: "
                f"{' '.join(site_check.PATHS)}")
    else:
        res = site_check.run_check(ctx.conn, ctx.cfg, transport=transport, run_id=ctx.run_id, agent=ctx.agent)
        site = f"site check: {res['checked'] - res['failed']} of {res['checked']} pages ok"
    return f"{'DRY RUN ' if ctx.dry_run else ''}{text}; {site}"


if __name__ == "__main__":
    runner.main_for("seo", run)
