"""SEO agent (weekly, Monday 05:00): search text for photos, and a read-only look at eventcaliber.com.

1. Search text (seo/photo_text.py): a slug, title, alt text, description and
   5 to 10 keywords for every postable photo and every photo on a queued
   post, stored in photo_seo for the site build, the sitemap and post alt
   text. Live: claude-haiku-4-5 under the monthly cap, every answer checked,
   the template where an answer fails. Dry run (the default): the template
   only, no paid call; the rows are internal, so they are written.
2. The site check (seo/site_check.py), live only: GET every public page
   (offer.public_pages), /sitemap.xml and /robots.txt on BRAND_DOMAIN,
   a site_checks row per page, an errors row for each page that fails. Dry
   run only says what it would check.
3. Search Console (seo/search_console.py), live only: the last 28 days for
   the morning brief, and every page's numbers kept for the window.
4. Search changes (2026-11-01, seo/changes.py), live only and only after
   this week's read: every change live for 31 days is measured and kept or
   put back; then the pages whose title and description lose the click get
   new words from Claude (seo/titles.py, part one), and the pages just off
   Google's first page for a search get their lead sentence reworded for it
   (seo/leads.py, part two), at most two of each a week, each proposed to
   Chris with a ping and changed on the site only on his Approve.

Nothing here publishes, uploads or sends anything without his Approve; a put
back (step 4) returns a page to the words it had before.
"""
from __future__ import annotations

from typing import Optional

from ..core import runner
from ..seo import changes, leads, photo_text, search_console, site_check, titles


def run(ctx: runner.Context, *, client=None, transport: Optional[site_check.Transport] = None,
        console: Optional[search_console.Transport] = None, changes_client=None) -> str:
    """`client` writes the photos' search text; `changes_client` drafts the search changes (tests pass fakes)."""
    s = photo_text.write_all(ctx.conn, ctx.cfg, dry_run=ctx.dry_run, client=client, agent=ctx.agent)
    text = (f"seo text: {s['written']} written ({s['claude']} by {s['model'] if s['claude'] else 'Claude'}, "
            f"{s['template']} template, {s['fell_back']} fell back), {s['kept']} kept, {s['edited']} edited by Chris, "
            f"{s['left_out']} queued photos no longer usable, {s['unsorted'] + s['refused']} skipped, "
            f"{s['shown_written']} of them on the site now"
            + (f", {s['refreshed']} rewritten in the words people search" if s.get("refreshed") else "")
            + (f"; stopped: {s['stopped']}" if s["stopped"] else ""))
    if ctx.dry_run:
        site = (f"site check not run in dry run; would GET {len(site_check.PATHS)} pages on {site_check.base_url(ctx.cfg)}: "
                f"{' '.join(site_check.PATHS)}")
    else:
        res = site_check.run_check(ctx.conn, ctx.cfg, transport=transport, run_id=ctx.run_id, agent=ctx.agent)
        site = f"site check: {res['checked'] - res['failed']} of {res['checked']} pages ok"
    # 2026-10-31, Chris chose "Search Console in the digest": Google's own numbers, read weekly, in the next brief
    if ctx.dry_run:
        google = "Search Console not read in dry run"
        loop = "search changes: none in dry run (nothing read, measured, paid for or proposed)"
    else:
        try:
            google = search_console.line(search_console.read(ctx.conn, ctx.cfg, transport=console))
        except search_console.SearchConsoleError as e:
            google = f"Search Console not read: {e}"
            loop = "search changes: nothing measured or proposed without this week's numbers"
        else:
            loop = search_changes(ctx, changes_client)
            # 2026-11-01, part five: which pages Google has in its index, named in the brief when one is missing
            try:
                google += " " + search_console.index_line(search_console.index_check(ctx.conn, ctx.cfg, transport=console))
            except search_console.SearchConsoleError as e:
                google += f" The index check did not run: {e}"
            except Exception as e:  # noqa: BLE001  the network: the week's numbers and changes are already done; said, tried next week
                google += f" The index check did not run ({type(e).__name__})."
    return f"{'DRY RUN ' if ctx.dry_run else ''}{text}; {site}; {google}; {loop}"


def search_changes(ctx: runner.Context, client=None) -> str:
    """Chris, 2026-11-01: "shouldn't we have it do it all. Why wouldn't we?" The changes live 31 days are measured first
    (kept, or put back with the site republishing), then this week's weak pages (part one) and near misses (part two)
    are drafted and proposed, one open change a page whatever its kind."""
    measured = [m["words"] for m in changes.measure(ctx.conn, cfg=ctx.cfg)]
    titled = titles.propose_week(ctx.conn, ctx.cfg, client=client, agent=ctx.agent)
    near = leads.propose_week(ctx.conn, ctx.cfg, client=client, agent=ctx.agent)
    return "search changes: " + " ".join(measured + [f"New words: {titled}.", f"Near misses: {near}.",
                                                     f"Standing: {changes.standing(ctx.conn)}."])


if __name__ == "__main__":
    runner.main_for("seo", run)
