"""eventcaliber.com, built on the Mini into site/dist and served by the Worker.

`build(conn, photos)` writes every page, the stylesheet, the script, the mark
and the photos. The look lives in site/theme.py (black, greys and white with
one cyan, built like a camera viewfinder; Chris, 2026-10-10) and the logo in
site/marks.py (Aperture, Chris's choice; BRAND_MARK). Photos on the site are public, so they pass the same gate as a
post: only postable photos (cleared, sorted, Claude's final check passed),
saved fresh from pixels at web size so no EXIF or GPS travels. With
`preview=True` it takes whatever photos it is handed (the stand-ins for Chris's
first look) and stamps every page PREVIEW so it can never be mistaken for live.

Every word on every page passes ai.copy_rules: no price, no dash, no claim of
an official role. The one list of organizations is the logo strip under the hero
(Chris, 2026-10-15: "should we add the companies we have worked for on the
website? like their logos"), off until he turns it on in offer.json.

Each page's title, description and lead sentence are written in one place (page_words).
A search change Chris approved (seo/changes.py, 2026-11-01: a title and description,
or a lead sentence) is laid over them by with_seo_changes, still through the copy rules,
the names rule and the lengths; one that no longer passes is left off with a note, and
the page keeps its own words. A page a search change adds (seo/pages.py, part three) is
built like the coverage pages offer.json lists, after them in the coverage lists and
never on the home page's; one taken down is left out, and the Worker sends its address
to the coverage index (REMOVED_FILE).
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from PIL import Image, ImageOps, ImageStat

from .. import offer
from ..ai import copy_rules
from ..ai import names as ai_names
from ..core import config, db
from ..seo import changes as seo_changes
from ..seo import indexnow, markup
from ..library import eligibility
from ..render import fonts
from ..render.meta import ImageMeta, save_jpeg
from . import marks, theme
from .clients import client_logos, clients_body, optical, save_logo  # noqa: F401  the strip under the hero

DIST = config.REPO_ROOT / "site" / "dist"
PAGES = offer.public_pages()        # the public pages, in sitemap order (2026-10-14: the coverage pages and Contact too)
# Cloudflare Turnstile on the quote form (2026-10-24): the widget "eventcaliber.com quote form", managed mode, for
# eventcaliber.com and www. The site key is public (it is on the page for everyone); the secret key is a Worker secret
# and nothing else (TURNSTILE_SECRET_KEY, docs/SETUP.md). The Worker refuses a token solved for any other action.
TURNSTILE_SITE_KEY = "0x4AAAAAAFkmbrAUupO81Nil"
TURNSTILE_ACTION = "quote"
AREA = "Washington, DC"                                                   # where the two of them are based, in every title
AREA_SERVED = ("Washington, DC", "Maryland", "Virginia", "United States")
AREA_LINE = "Based in Washington, DC. Serving DC, Maryland and Virginia, and travelling nationwide."
TITLE_MAX, DESCRIPTION_MAX = 75, 160       # what a search result shows whole; a longer one stops the build (said, never silently cut)
LEAD_MAX = 200     # a lead sentence a search change writes: one or two plain sentences (the longest of the site's own is 180)
# which kinds of shot a coverage page shows (2026-10-14): the library's own shot words, by the room the page is about
COVERAGE_SHOTS = {
    "backstage": ("backstage",), "green_room": ("backstage",),
    "breakouts": ("breakout",), "stage": ("main_stage", "stage_panel"),
    "evening_events": ("reception", "candid"), "dinners": ("reception",),
    "portraits": ("portrait",), "exhibition_hall": (),               # no expo title in the eight: the page fills from the pool
    "on_site_delivery": ("candid",),
    "selects": ("main_stage", "portrait"),                       # what an organizer asks for first: the stage and the people
}
PAGE_ROWS, PAGE_MIN = 6, 3                 # photos on a coverage page: six of its room; under three, the rest of the pool fills in
SHOT_KINDS = tuple(dict.fromkeys(shot for shots in COVERAGE_SHOTS.values() for shot in shots))   # every kind a page may show
# a page a search change adds (2026-11-01, seo/pages.py): a new address under /coverage/, its heading (its row in the
# coverage lists, like the labels offer.json gives, the longest 33), one or two paragraphs (the site's own run 189 to 326),
# one to three kinds of photo
ADDED_PATH = re.compile(r"/coverage/([a-z0-9]+(?:-[a-z0-9]+)*)/")
HEADING_MAX, PARAGRAPH_MAX, PARAGRAPHS_MAX, SHOTS_MAX = 35, 350, 2, 3
REMOVED_FILE = "removed-pages.json"     # the addresses of pages taken down: the Worker sends them to /coverage/ (worker/index.js)
LASTMOD_FILE = "lastmod.json"      # DATA_ROOT/site: each page's content hash and the date it last changed
VERIFICATION_KEY = "GOOGLE_SITE_VERIFICATION"   # the Search Console HTML tag's content value (Keys page)
WIDTHS = (800, 1600)
# the booked dates on the quote page (Chris, 2026-10-15: the Availability page was six empty calendars, "a very bad look",
# and its own tab; redone 2026-10-31). One line under the quote page's opening: the label, then the dates and nothing else,
# read from GET /api/availability (dates only, never a name; the page keeps only what reads as a date and is not past).
# Hidden in the page itself, so with nothing booked, no script, or the API down or in error, nothing shows at all. Days in
# a row read as one run ("Nov 7 to 9"); a year is said only when it is not this one; each run is held together by
# no-break spaces and its dot stays with it, so a line never starts with a dot. No dash anywhere (ai.copy_rules).
BOOKED_LINE = r"""<p class="booked" id="booked" hidden><span class="mono c">Dates already booked</span><span class="when" id="booked-when"></span></p>
<script>(function(){const M=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"],NB="\u00a0";
const n=new Date(),p=v=>String(v).padStart(2,"0"),today=n.getFullYear()+"-"+p(n.getMonth()+1)+"-"+p(n.getDate());
const day=s=>Date.UTC(+s.slice(0,4),+s.slice(5,7)-1,+s.slice(8,10))/864e5,mon=s=>M[+s.slice(5,7)-1],dd=s=>+s.slice(8,10);
function say(a,b){let t=mon(a)+NB+dd(a);if(b!==a)t+=NB+"to"+NB+(b.slice(0,7)===a.slice(0,7)?"":mon(b)+NB)+dd(b);
return +b.slice(0,4)===n.getFullYear()?t:t+","+NB+b.slice(0,4);}
function show(booked){const days=[...new Set(booked.filter(d=>/^\d{4}-\d{2}-\d{2}$/.test(d)&&d>=today))].sort();if(!days.length)return;
const runs=[];for(const d of days){const r=runs[runs.length-1];if(r&&day(d)-day(r[1])===1)r[1]=d;else runs.push([d,d]);}
document.getElementById("booked-when").textContent=runs.map(r=>say(r[0],r[1])).join(NB+"\u00b7 ");document.getElementById("booked").hidden=false;}
fetch("/api/availability").then(r=>r.ok?r.json():{}).then(j=>{if(Array.isArray(j.booked))show(j.booked);}).catch(()=>{});})();</script>"""


@dataclass
class SitePhotos:
    hero: list = field(default_factory=list)       # [(image, alt)] or [(image, alt, ImageMeta)]
    coverage: list = field(default_factory=list)
    venues: list = field(default_factory=list)
    hero_note: str = ""                            # which photo is the hero and why, for the go-live output
    grid_note: str = ""                            # Chris's gallery picks: which lead the grid, which were left out and why (2026-10-29)
    ids: list = field(default_factory=list)        # every library photo shown (hero when from the library, grid, venues, coverage pages)
    grid_ids: list = field(default_factory=list)   # the home page's own: hero when from the library, grid, venues; a build records their use
    links: list = field(default_factory=list)      # the coverage page each grid frame opens, one per coverage entry (2026-10-14)
    pages: dict = field(default_factory=dict)      # coverage key -> [(image, alt)], the photos of that kind of room (2026-10-14)


class SiteCopyRefused(ValueError):
    pass


HERO_ROWS, COVERAGE_ROWS, VENUE_ROWS = 1, 12, 2      # 2026-10-14: the strip grew from six to twelve (Chris: "expand the gallery to more images");
# 2026-10-15, the venues: "Just one or two venue picks at most and not labeled on the image itself"
EVENT_POOL = 20               # eligible event photos the hero is chosen among; the strip draws from the whole usable pool
HERO_CANDIDATES = 12          # landscape frames looked at (fetched) for the hero's colour and punch
RECHECKS = 12                 # Claude calls one site build may spend asking what kind of occasion a photo is from
HERO_KEY = "site.hero_photo_id"   # Chris's own pick for the hero (Photos tab, Approved: Site hero); it wins while it is usable
SHOWN_KEY = "site.shown_photo_ids"   # JSON list: every library photo the last live build showed (2026-10-31), for the writer
STAGE = ("main_stage", "stage_panel")


def colorfulness(im: Image.Image) -> float:
    """How much colour and punch a frame has, 0 to about 1.5: the mean saturation of its pixels plus
    half the spread of their brightness (a flat grey frame scores near 0, a lit stage with colour high)."""
    small = im.convert("RGB").copy()
    small.thumbnail((320, 320))
    _, s, v = small.convert("HSV").split()
    return ImageStat.Stat(s).mean[0] / 255 + min(1.0, ImageStat.Stat(v).stddev[0] / 128) / 2


def hero_score(row: dict, im: Image.Image) -> float:
    """The hero on its own merit (Chris, 2026-10-11: "the most colorful and dynamic photo, a wide stage
    panorama shot or a very powerful [keynote] shot"): the frame's strength, its colour and punch, a
    stage or panel, and a wide frame."""
    from ..library import report
    wide = (row.get("width") or 0) >= 1.5 * (row.get("height") or 1)
    return report.strength(row) / 10 + colorfulness(im) + (0.5 if row.get("shot_type") in STAGE else 0.0) + (0.25 if wide else 0.0)


def spread(rows: list[dict], key: Callable[[dict], object]) -> list[dict]:
    """The same rows, one per key before any key repeats, each round in the order given (the website's
    grid and the samples never lead with one event on everything: Chris, 2026-10-11)."""
    out, pending = [], list(rows)
    while pending:
        seen, rest = set(), []
        for r in pending:
            k = key(r)
            if k in seen:
                rest.append(r)
            else:
                seen.add(k)
                out.append(r)
        pending = rest
    return out


def event_of(row: dict) -> object:
    return (row.get("convention_name") or "").strip().lower() or row.get("folder_id") or row.get("id")


def shot_of(row: dict) -> str:
    return row.get("shot_type") or ""


def one_per_picture(rows: list[dict], last: dict[int, str], keep: Optional[set] = None) -> tuple[list[dict], dict[int, str]]:
    """The same picture under two ids is one photo (Chris, 2026-10-14, on the live strip: "same picked twice"; the
    library holds the same file in two Drive folders, or a copy in a shared gallery, 1,431 such groups that day).
    One row stands for each md5 group, the first in the order given (an id in `keep`, Chris's own hero pick, wins),
    and the group's last use on any surface is the latest of its rows', so a picture shown under one id sits out
    under the others too. A row with no md5 (a photo from the phone) is its own group."""
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r.get("md5") or f"id:{r['id']}", []).append(r)
    kept, shared = [], dict(last)
    for members in groups.values():
        latest = max((last.get(m["id"]) or "" for m in members), default="")
        if latest:
            for m in members:
                shared[m["id"]] = latest
        kept.append(next((m for m in members if keep and m["id"] in keep), members[0]))
    return kept, shared


def pick_grid(rows: list[dict]) -> list[dict]:
    """The home page's strip (Chris, 2026-10-14: "the website gallery has duplicate images and lets expand the gallery
    to more images and a variety"): COVERAGE_ROWS photos drawn across the rooms (the kinds of shot) and across events,
    one of each room before any room repeats and, within a round, one per event before any event repeats; the pool's
    own order (the least recently used first) decides within a room. So the strip shows backstage, the stage, dinners,
    portraits and halls rather than several of one room, and never the same photo twice (the rows are distinct photos)."""
    return spread(spread(rows, event_of), shot_of)[:COVERAGE_ROWS]


def site_picks(conn: sqlite3.Connection, pool: list[dict], *, hero_id: Optional[int] = None) -> tuple[list[dict], str]:
    """Chris's own picks for the home page's gallery (2026-10-29: "a tab for the approved photos that I can click to add
    to the site's gallery"): the pool's rows he tapped Site gallery on, in the order he tapped them. A pick the pool no
    longer holds (blocked, gone from Drive, unsorted, a building) is left out and said, and so is a pick that is the
    hero (the gallery never shows the hero again). One picture under two ids is one pick. (picks, what to say)"""
    by_id = {r["id"]: r for r in pool}
    by_md5 = {r["md5"]: r for r in pool if r.get("md5")}
    picks, said, seen = [], [], set()
    for w in db.rows(conn, "SELECT id, md5 FROM photos WHERE site_pick_at IS NOT NULL ORDER BY site_pick_at, id"):
        key = w["md5"] or f"id:{w['id']}"
        if key in seen:
            continue
        seen.add(key)
        row = by_id.get(w["id"]) or by_md5.get(w["md5"])
        if row is None:
            ok, why = eligibility.is_eligible(conn, w["id"])
            said.append(f"your Site gallery pick (photo {w['id']}) could not be used: {why if not ok else 'not an event photo in the library'}")
        elif row["id"] == hero_id:
            said.append(f"your Site gallery pick (photo {row['id']}) is the hero, so the gallery does not show it again")
        else:
            picks.append(row)
    if picks:
        ids = ", ".join(str(r["id"]) for r in picks)
        said.insert(0, f"your Site gallery picks lead the gallery, in your order: photos {ids}")
    return picks, "; ".join(said)


def lead_with_picks(picks: list[dict], pool: list[dict], hero: Optional[dict]) -> list[dict]:
    """The home page's gallery: Chris's picks first, in his order, then pick_grid fills the rest of the COVERAGE_ROWS
    frames from the pool as before; never the hero and never a photo twice."""
    skip = {r["id"] for r in picks} | ({hero["id"]} if hero is not None else set())
    return (picks + pick_grid([r for r in pool if r["id"] not in skip]))[:COVERAGE_ROWS]


def strength_order(r: dict) -> tuple:
    """The library's photos for the site, best first: a known conference or convention before an unknown kind, then the
    strongest frame (sharp, lit, a moment), then the widest."""
    from ..library import report
    return (0 if r["event_kind"] in ("fan", "business") else 1, -report.strength(r), -(r["width"] or 0))


def library_rows(conn: sqlite3.Connection, keep: Optional[set] = None) -> list[dict]:
    """The library's sorted event and building photos, one row per picture (one_per_picture; an id in `keep` stands for
    its picture), the least recently used first on any surface (the rotation, 2026-10-14), strength_order among equals."""
    from ..library import report
    rows = db.rows(conn, """
        SELECT p.*, c.subject, c.quality, c.sharp, c.light, c.moment, c.event_kind, c.shot_type, c.convention_name, c.summary
        FROM photos p JOIN classifications c ON c.photo_id=p.id WHERE p.trashed=0 AND c.subject IN ('event','architecture')
        ORDER BY COALESCE(c.quality,0) DESC, p.width DESC LIMIT 600""")
    rows = sorted((dict(r) for r in rows), key=strength_order)
    # the same picture under two ids is one photo, and its use under any id counts (2026-10-14: "same picked twice")
    rows, last = one_per_picture(rows, report.last_uses(conn), keep=keep)
    # the rotation (2026-10-14): the least recently used first, on any surface, so each publish shows photos the posts
    # and the last build did not; the strength order above only breaks ties, and equal frames come by chance
    return report.rotate(conn, rows, last=last, alike=strength_order)


def page_pool(conn: sqlite3.Connection) -> list[dict]:
    """Every usable event photo, least recently used first: the pool the coverage pages draw from (pick_photos), for a
    preview of a page a search change proposes (seo/pages.py). Nothing is paid for here: a photo Claude has not yet judged
    for its kind of occasion waits, as it does in any build without the key."""
    return [r for r in library_rows(conn) if r["subject"] == "event" and eligibility.is_eligible(conn, r["id"])[0]]


def pick_photos(conn: sqlite3.Connection, fetch: Callable[[dict], Image.Image],
                recheck: Optional[Callable[[dict, Image.Image], Optional[dict]]] = None,
                look: Optional[Callable[[bytes], Optional[dict]]] = None) -> SitePhotos:
    """Postable photos only: event work for the hero and the grid, building work for venues. Each photo
    is judged on its own: the strongest frame first (sharp, lit, a moment), a known conference or
    convention before an unknown kind, and never a wedding or a private occasion (Chris, 2026-10-11:
    "The main photo when you open the website is from a damn wedding! That one needs to be the best of
    the best"). The hero is Chris's own pick when he made one and it is usable; otherwise the landscape
    frame with the highest hero_score among the strongest HERO_CANDIDATES. The grid is spread across
    events, so no one event is the first thing on everything. `recheck` gives Claude's final check to a
    photo it has not yet judged for its kind, up to RECHECKS per build; without it such a photo waits."""
    from ..core import settings
    chosen = settings.get(conn, HERO_KEY)
    chosen_id = int(chosen) if chosen and str(chosen).isdigit() else None
    rows = library_rows(conn, keep={chosen_id} if chosen_id is not None else None)
    added = [(p["key"], tuple(p["shots"])) for p in added_pages(conn)]     # the pages search changes added (2026-11-01)
    out, images, rechecks = SitePhotos(), {}, 0
    events: list[dict] = []
    venues: list[dict] = []

    def usable(r) -> bool:
        nonlocal rechecks
        if not eligibility.is_candidate(conn, r["id"])[0]:
            return False
        if recheck is not None and rechecks < RECHECKS and eligibility.needs_kind_check(conn, r["id"]):
            rechecks += 1
            images[r["id"]] = fetch(r)
            if recheck(r, images[r["id"]]) is None:
                return False                                # Claude could not look: not used
        return eligibility.is_eligible(conn, r["id"])[0]

    pool: list[dict] = []                               # every usable event photo, least recently used first (the coverage pages draw here)
    for r in rows:
        if r["subject"] == "architecture":
            if len(venues) < VENUE_ROWS and usable(r):
                venues.append(r)
            continue
        if usable(r):
            pool.append(r)
    events = pool[:EVENT_POOL]

    def image_of(r):
        if r["id"] not in images:
            images[r["id"]] = fetch(r)
        return images[r["id"]]

    hero = None
    words = lambda r: words_for(conn, r)      # noqa: E731  what each library photo says on the site, on every path out of here
    from . import hero as upload
    if upload.present():
        # Chris, 2026-10-12: the photo he sent is the hero, full stop; Claude's look only words the alt text and a note
        _, why = upload.checked(conn, look)
        yours = "your uploaded photo" if upload.status(conn)["source"] == "phone" else "the photo you sent, shipped with the code"
        from ..seo.photo_text import SHOT_WORDS
        rec = upload.record(conn) or {}
        out.hero = [(upload.image(), SHOT_WORDS.get(rec.get("shot_type") or "", "Event photography"))]
        out.hero_note = f"{yours} ({why})"
        picks, out.grid_note = site_picks(conn, pool)
        return _finish(out, lead_with_picks(picks, pool, None), venues[:VENUE_ROWS], None, pool, image_of, words, added)

    def note(text):
        out.hero_note = (out.hero_note + "; " if out.hero_note else "") + text
    if chosen_id is not None:
        picked = next((r for r in rows if r["id"] == chosen_id and r["subject"] == "event"), None)
        if picked is None:
            note(f"your Site hero pick (photo {chosen_id}) is not an event photo in the library; the build chose instead")
        elif picked in events or usable(picked):
            hero = picked
            note(f"your Site hero pick (photo {chosen_id}, {site_alt(picked).lower()})")
        else:
            ok, why = eligibility.is_candidate(conn, picked["id"])
            why = why if not ok else eligibility.is_eligible(conn, picked["id"])[1]
            note(f"your Site hero pick (photo {chosen_id}) could not be used: {why}; the build chose instead")
    if hero is None:
        wide = [r for r in events if (r["width"] or 0) > (r["height"] or 0)]
        # his gallery picks are for the gallery: the build's own hero is another frame while there is one (2026-10-29)
        land = ([r for r in wide if not r.get("site_pick_at")] or wide)[:HERO_CANDIDATES]
        if land:
            scores = {r["id"]: hero_score(r, image_of(r)) for r in land}
            hero = max(land, key=lambda r: scores[r["id"]])
            note(f"the build's choice: photo {hero['id']} ({site_alt(hero).lower()}, score {scores[hero['id']]:.2f} of {len(land)} looked at)")
        else:
            note("no usable landscape event photo for the hero")
    if hero is not None:
        out.hero = [(image_of(hero), *words(hero))]
    # Chris's gallery picks lead the grid (2026-10-29); the grid never shows the hero, so a pick that is the hero is said
    picks, out.grid_note = site_picks(conn, pool, hero_id=hero["id"] if hero is not None else None)
    return _finish(out, lead_with_picks(picks, pool, hero), venues[:VENUE_ROWS], hero, pool, image_of, words, added)


def coverage_key_for(row: dict) -> str:
    """The coverage page a photo belongs on, by its kind of shot: the page that lists the shot first (a stage shot is
    the main stage, a panel is breakouts), else the first page that lists it at all; the index when no page claims it."""
    shot = row.get("shot_type") or ""
    if not shot:
        return ""
    for key, shots in COVERAGE_SHOTS.items():
        if shots and shots[0] == shot:
            return key
    for key, shots in COVERAGE_SHOTS.items():
        if shot in shots:
            return key
    return ""


def pick_room(pool: list[dict], shots: tuple, taken: set) -> list[dict]:
    """The photos of one coverage page (2026-10-14): up to PAGE_ROWS of its kinds of shot, its first kind before the kinds
    it borrows, in the pool's order (least recently used first), photos no page has `taken` before those another page
    shows; under PAGE_MIN of its own, the rest of the pool fills in, so a page is never empty while the library has photos."""
    fit = [r for r in pool if (r.get("shot_type") or "") in shots]
    fit.sort(key=lambda r: shots.index(r["shot_type"]))        # the room's own kind of shot before the kinds it borrows (a stable sort: the pool's order within a kind)
    pick = [r for r in fit if r["id"] not in taken][:PAGE_ROWS]
    if len(pick) < PAGE_ROWS:
        pick += [r for r in fit if r not in pick][:PAGE_ROWS - len(pick)]           # the same room again before another room
    if len(pick) < PAGE_MIN:
        pick += [r for r in pool if r not in pick and r["id"] not in taken][:PAGE_ROWS - len(pick)]
    if len(pick) < PAGE_MIN:
        pick += [r for r in pool if r not in pick][:PAGE_ROWS - len(pick)]
    return pick


def pick_page_photos(pool: list[dict], added: list[tuple[str, tuple]] = ()) -> dict[str, list[dict]]:
    """The photos of each coverage page (pick_room), the pages offer.json lists in its order, then the pages search
    changes added (`added`: (key, kinds of shot) each, 2026-11-01), each photo on one page before any page repeats one."""
    pages: dict[str, list[dict]] = {}
    taken: set[int] = set()
    for key, shots in [(k, COVERAGE_SHOTS.get(k, ())) for k in offer.coverage_keys()] + list(added):
        pick = pick_room(pool, tuple(shots), taken)
        taken.update(r["id"] for r in pick)
        pages[key] = pick
    return pages


def _finish(out: SitePhotos, grid: list[dict], rooms: list[dict], hero: Optional[dict], pool: list[dict], image_of,
            words: Callable[[dict], tuple], added: list[tuple[str, tuple]]) -> SitePhotos:
    """`words(row)` gives what a photo says on the site: (alt, meta, slug, label), see words_for. It is required: the
    first version gave it a default and the path with an uploaded hero, the one production takes, went out without it
    (2026-10-31: the deployed page still said "Main stage" four times). `added`: the pages search changes added, each
    (key, kinds of shot), required on every path for the same reason."""
    out.coverage = [(image_of(r), *words(r)) for r in grid]
    out.links = [f"/coverage/{coverage_key_for(r)}/" if coverage_key_for(r) else "/coverage/" for r in grid]
    out.venues = [(image_of(r), *words(r)) for r in rooms]
    out.grid_ids = [r["id"] for r in ([hero] if hero is not None else []) + grid + rooms]
    pages = pick_page_photos(pool, added)
    out.pages = {key: [(image_of(r), *words(r)) for r in picked] for key, picked in pages.items()}
    out.ids = list(dict.fromkeys(out.grid_ids + [r["id"] for picked in pages.values() for r in picked]))
    return out


GENERIC_KEYWORDS = ("event photography", "convention photography")


def words_for(conn: Optional[sqlite3.Connection], row: dict) -> tuple[str, ImageMeta, str, str]:
    """What a photo says on the site: (alt, meta, slug, label).

    The weekly writer's words when the photo has them (seo/photo_text.py, photo_seo: alt text, a title, a description and
    keywords for the file's own metadata and the sitemap, and a slug for the file name; each checked against the names
    rule and the copy rules when written, and Chris can edit them on the dashboard). Before 2026-10-31 every photo said
    only the kind of shot, so four photos on a page all read "Main stage" and the files were cover-stage-0.jpg (Chris:
    "SEO is VERY important for this website!"). The kind of shot stays as the label: the strip's captions keep it, and
    a photo without the writer's words, or whose words no longer pass the copy rules, says it everywhere, as before."""
    label = site_alt(row)
    generic = ImageMeta(title=label, description=label, keywords=GENERIC_KEYWORDS)
    seo = db.one(conn, "SELECT slug, title, alt, description, keywords FROM photo_seo WHERE photo_id=?", (row["id"],)) if conn is not None and row.get("id") is not None else None
    if seo is None:
        return label, generic, "", label
    title, alt, description = (seo["title"] or "").strip(), (seo["alt"] or "").strip(), (seo["description"] or "").strip()
    if not (title and alt and description) or any(not copy_rules.check(t).ok for t in (title, alt, description)):
        return label, generic, "", label
    try:
        keywords = tuple(str(k) for k in json.loads(seo["keywords"] or "[]") if str(k).strip()) or GENERIC_KEYWORDS
    except ValueError:
        keywords = GENERIC_KEYWORDS
    return alt, ImageMeta(title=title, description=description, keywords=keywords), (seo["slug"] or "").strip(), label


def site_alt(row: dict) -> str:
    """Alt text from the kind of shot, never the sorter's own description, which may name the event or
    a person (Chris, 2026-10-11: no public words say which event or who; ai/names.py)."""
    from ..seo.photo_text import SHOT_WORDS
    if row.get("subject") == "architecture":
        return "Venue and architecture photography"
    return SHOT_WORDS.get(row.get("shot_type") or "", "Event photography")


def dodge_shadows(im: Image.Image, amount: float = 0.06) -> Image.Image:
    """Lift the shadows a touch, as a dodge would: the darkest values rise by up to `amount` of the
    range, the mid tones a little, the highlights not at all (Chris, 2026-10-12: "dodge shadows a tad", then
    "Way too much dodging": 0.14 became 0.06)."""
    lut = [min(255, round(v + amount * 255 * (1 - v / 255) ** 2)) for v in range(256)]
    return im.convert("RGB").point(lut * 3)


def save_web(im: Image.Image, out_dir: Path, stem: str, meta: Optional[ImageMeta] = None) -> dict:
    """JPEGs at each width, from pixels only: no camera data or GPS, our SEO fields inside. {width: filename}."""
    im = ImageOps.exif_transpose(im).convert("RGB")
    made = {}
    for w in WIDTHS:
        copy = im.copy()
        copy.thumbnail((w, w * 2))
        name = f"{stem}-{w}.jpg"
        save_jpeg(copy, out_dir / name, meta, quality=82)
        made[w] = name
    return made


def aspect(im: Image.Image) -> str:
    """The photo's width over its height as a CSS number, after the EXIF orientation (the shape of the saved file), so
    the frame on the site has the photo's own shape and nothing is cropped (Chris, 2026-10-14: "the horizontal images
    must not be cropped anywhere on any device"; the hero is the one picture he allows a crop)."""
    w, h = im.size
    if im.getexif().get(0x0112, 1) in (5, 6, 7, 8):
        w, h = h, w
    return f"{w / h:.4f}"


def img_tag(files: dict, alt: str, sizes: str, cls: str = "", eager: bool = False, extra: str = "") -> str:
    srcset = ", ".join(f"/assets/{n} {w}w" for w, n in sorted(files.items()))
    load = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    return (f'<img class="{cls}" src="/assets/{files[max(files)]}" srcset="{srcset}" sizes="{sizes}" '
            f'alt="{html.escape(alt)}" {load} decoding="async"{extra}>')


def contact_email() -> str:
    cfg = config.get_config()
    return cfg.brand_from_email or f"hello@{cfg.brand_domain}"


def contact_phone() -> str:
    """The number on the website (Keys page, BRAND_PHONE; 2026-10-14). Empty hides it everywhere."""
    return (config.getenv("BRAND_PHONE") or "").strip()


def social_links() -> tuple[tuple[str, str], ...]:
    """(label, address) for each social address set on the Keys page (2026-10-14); only https addresses."""
    out = []
    for key, label in (("SOCIAL_INSTAGRAM", "Instagram"), ("SOCIAL_FACEBOOK", "Facebook"), ("SOCIAL_PINTEREST", "Pinterest")):
        url = (config.getenv(key) or "").strip()
        if url.startswith("https://"):
            out.append((label, url))
    return tuple(out)


def copy_text() -> dict:
    o = offer.load()
    return {
        # 2026-10-14: the place in the title, a plain first sentence a search engine or an AI can quote, a description that fits
        "title": f"{o['tagline']} in {AREA} | {o['company']}",
        "description": (f"{o['company']} photographs conventions, conferences and galas in {AREA} and nationwide. "
                        "Photos reach attendees while the event is on. Request a quote."),
        "kicker": f"Event and convention photography, {AREA} and nationwide",
        # 2026-10-31, SEO: the headline carries the words people search ("convention photographers", the city); his line and
        # the years, the site's voice since 2026-10-12, are the display line under it ("Where does it say two brothers now each
        # with 30+ years in the business?"; a paragraph was not it: "There is no large lead to see")
        "sub": "Two brothers, every room. More than thirty years each.",
        "first": f"{o['company']} photographs conventions, conferences, galas and award dinners in {AREA} and nationwide.",
        # Chris, 2026-10-12: the site is the two of them, in their own voice; no "fan conventions" on the main page; one of them
        # writes back within 24 hours. 2026-10-30: "Instant delivery needs to be a top priority for getting customers": it leads,
        # as the outcome and the organizer's choice; never the method, never a price, never proof. The hour for selects is not
        # in the hero ("Don't include the selects part in the top"). 2026-10-31: the lede is in two parts because the link to
        # the delivery page sits between them ("a link at the top where the instant delivery also lives to the detailed page").
        "lede_delivery": ("Your attendees have the photos while the event is still on, and post them as it happens: all attendees, or "
                          "your staff only, your choice."),
        "lede_brothers": ("We've photographed conventions, conferences, galas and award dinners for more than thirty years each, "
                          "room by room, across the country. Tell us about your event and one of us will write back within 24 hours."),
        "coverage_first": ("Backstage, green rooms, breakouts, the main stage, evening events, dinners, portraits and exhibition halls: "
                           "every room of a conference or convention, photographed by the two of us."),
        "coverage_description": ("Backstage, green rooms, breakouts, the main stage, evening events, dinners, portraits and exhibition "
                                 f"halls, photographed by two brothers in {AREA}."),
        "contact_first": "Email or call, and one of us writes back within 24 hours.",
        "contact_p": "We are based in Washington, DC and travel wherever the event is. For dates and a quote, the form is quickest.",
        "who": "One of us is at every event. The event is staffed with our photographers, and we shoot when we're needed.",
        # Chris, 2026-10-14, on the Privacy page's Who we are, one line long: "should be more than two fucking words!"
        "who_we_are": ("Event Caliber is the brand of Chris and Nic Kennedy, brothers and event photographers based in Washington, DC. "
                       "The company behind it is CKI, LLC. Questions about this page, a photo or the form go to {email}."),
        "thanks": "Your request is in. One of us reads it and writes back to you by email within 24 hours.",
        "thanks_p": "Until then, the coverage pages show what each room of an event looks like in our photographs.",
        "not_found": "There is no page at this address. The pages are in the menu, and the coverage pages are a tap away.",
        "about": ("We're Chris and Nic Kennedy, brothers, and we have photographed events for more than thirty years each.\n\n"
                  "We learned on film. Both of us studied photography at the Corcoran in Washington, DC, where our father taught "
                  "and had graduated before us. Nic finished in 1999, Chris in 2002. Many of the events in our early years were "
                  "shot on film, and we developed and printed our own black-and-white work in a large darkroom at home.\n\n"
                  "Today we photograph conventions, conferences, galas and award dinners across the country, room by room. "
                  "We are based in Washington, DC and travel wherever the event is.\n\n"
                  "Tell us about your event and one of us will write back within 24 hours."),
        "coverage_p": "Tell us which rooms matter. Coverage is planned around your schedule, and every event is quoted on its own.",
        # Chris, 2026-10-31: "The bottom one was suppose to be replaced with 1 hour selects": "the selects for the clients in 1
        # hour during the event". The organizer's selects, when the moments are known before the event; attendee delivery is
        # said once, in the hero, and in full on its coverage page. Never the method, never a price, never proof.
        "selects_p": ("Tell us before the event which moments you want: the keynote, the awards, the people on stage. "
                      "During the event, the selects from those moments are yours within the hour. "
                      "The finished set follows after the event."),
        "steps": [("Tell us about your event", "Dates, venue, the rooms and moments that matter, and who needs images."),
                  ("A quote within 24 hours", "One of us writes back with a clear quote for the coverage you need, nothing bundled you did not ask for."),
                  ("Photos during the event, the full set after", "Selects go out while the event is on, and the finished set follows.")],
        "venues_p": ("Years of architectural work mean the venue gets shot as carefully as the people in it: "
                     "exteriors, lobbies, halls and ballrooms."),
        "cta_p": "Send the dates and the details. One of us writes back within 24 hours with a quote for the coverage you asked for.",
    }


def check_copy(texts) -> None:
    for t in texts:
        r = copy_rules.check(t)
        if not r.ok:
            raise SiteCopyRefused(f"{t[:60]!r}: {r.blocks[0].message}")


def rel_of(path: str) -> str:
    """The file a site path is written to: "/" is index.html, "/coverage/stage/" is coverage/stage/index.html."""
    return "index.html" if path == "/" else path.strip("/") + "/index.html"


def page_words(o: dict, t: dict, brand: str) -> dict[str, dict[str, str]]:
    """Every page's own words, by the file it is written to: its "title" and "description" (the build adds " | brand"
    after every title but the home page's, full_title) and, on a page that opens with one, its "lead" sentence (the
    <p class="first"> under the headline)."""
    def page(title: str, description: str, lead: Optional[str] = None) -> dict[str, str]:
        return {"title": title, "description": description, **({"lead": lead} if lead is not None else {})}
    words = {"index.html": page(t["title"], t["description"], t["first"]),
             "coverage/index.html": page(f"Event photography coverage in {AREA}", t["coverage_description"], t["coverage_first"])}
    for c in o["coverage"]:
        words[f"coverage/{c['key']}/index.html"] = page(f"{c['title']}, {AREA}", c["first"], c["first"])
    words["contact/index.html"] = page("Contact us", f"Email or call {brand}, event and convention photographers based in {AREA}. "
                                                     "One of us writes back within 24 hours.", t["contact_first"])
    words["book/index.html"] = page("Request a quote for event photography",
                                    f"Send the dates, the venue and the rooms that matter. One of us writes back within 24 hours "
                                    f"with a quote, in {AREA} or wherever your event is.")
    words["about/index.html"] = page("About us: two brothers, event photographers",
                                     f"Chris and Nic Kennedy, brothers, more than thirty years each behind the camera, based in {AREA} "
                                     "and travelling nationwide.")
    words["thanks/index.html"] = page("Thank you", "Your request is in.", t["thanks"])
    words["privacy/index.html"] = page("Privacy and photo removal", "How quote requests are handled, and how to have a photo taken down.")
    words["404.html"] = page("Not found", "Not found.", t["not_found"])
    return words


def full_title(rel: str, title: str, brand: str) -> str:
    """The title as a search result shows it: the page's own, then " | brand"; the home page's title is whole."""
    return title if rel == "index.html" else f"{title} | {brand}"


def words_problems(rel: str, title: str, description: str, brand: str, names) -> list[str]:
    """Why a title and description may not stand on a page, in plain words; [] when they may: the copy rules, the names
    rule (Chris, 2026-10-11: no public word names an event or a person; ai/names.py) and the lengths a search result
    shows whole. The home page's title keeps the company's name."""
    why = []
    for what, text in (("title", title), ("description", description)):
        if not (text or "").strip():
            why.append(f"the {what} is empty")
            continue
        why += [f"the {what} {b.message}" for b in copy_rules.check(text, names=names).blocks]
    shown = full_title(rel, title, brand)
    if len(shown) > TITLE_MAX:
        why.append(f"the title is {len(shown)} characters in a search result, {TITLE_MAX} at most")
    if len(description or "") > DESCRIPTION_MAX:
        why.append(f"the description is {len(description)} characters, {DESCRIPTION_MAX} at most")
    if rel == "index.html" and brand.lower() not in (title or "").lower():
        why.append(f"the home page's title must keep the name {brand}")
    return why


def lead_problems(lead: str, names) -> list[str]:
    """Why a lead sentence a search change writes may not stand on a page, in plain words; [] when it may: the copy rules
    (no price, no dash, no claim, no official role or client), the names rule and its length."""
    if not (lead or "").strip():
        return ["the lead is empty"]
    why = [f"the lead {b.message}" for b in copy_rules.check(lead, names=names).blocks]
    if len(lead) > LEAD_MAX:
        why.append(f"the lead is {len(lead)} characters, {LEAD_MAX} at most")
    return why


def change_problems(rel: str, words: dict[str, str], fields, brand: str, names) -> list[str]:
    """Why a page's words, with a change laid, may not stand: each field the change sets (`fields`) by its own rule, the
    title and description by words_problems, the lead by lead_problems."""
    why = []
    if {"title", "description"} & set(fields):
        why += words_problems(rel, words.get("title", ""), words.get("description", ""), brand, names)
    if "lead" in fields:
        why += lead_problems(words.get("lead", ""), names)
    return why


def added_page_problems(path: str, page: dict, brand: str, names) -> list[str]:
    """Why a page a search change adds (seo/pages.py) may not stand on the site, in plain words; [] when it may: a new
    address under /coverage/; its title and description (words_problems) and its lead (lead_problems); its heading, its
    name (what it offers, the Service a search engine reads) and its one or two paragraphs by the copy rules, the names
    rule and their lengths; and one to three kinds of photo the site shows (SHOT_KINDS)."""
    why = [] if ADDED_PATH.fullmatch(path) else [f"{path} is not a new address under /coverage/"]
    why += words_problems(rel_of(path), page.get("title", ""), page.get("description", ""), brand, names)
    why += lead_problems(page.get("lead", ""), names)
    paragraphs = page.get("paragraphs")
    if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= PARAGRAPHS_MAX:
        why.append(f"it needs one or two paragraphs, not {len(paragraphs) if isinstance(paragraphs, list) else 'none'}")
        paragraphs = []
    for what, text, most in ([("heading", page.get("heading"), HEADING_MAX), ("name", page.get("name"), TITLE_MAX)]
                             + [(f"paragraph {i}", t, PARAGRAPH_MAX) for i, t in enumerate(paragraphs, start=1)]):
        if not isinstance(text, str) or not text.strip():
            why.append(f"the {what} is empty")
            continue
        why += [f"the {what} {b.message}" for b in copy_rules.check(text, names=names).blocks]
        if len(text) > most:
            why.append(f"the {what} is {len(text)} characters, {most} at most")
    shots = page.get("shots")
    if (not isinstance(shots, list) or not 1 <= len(shots) <= SHOTS_MAX or len(set(map(str, shots))) != len(shots)
            or any(shot not in SHOT_KINDS for shot in shots)):
        why.append(f"its photos must be one to {SHOTS_MAX} of the kinds the site shows ({', '.join(SHOT_KINDS)})")
    return why


def with_seo_changes(conn: sqlite3.Connection, words: dict[str, dict[str, str]],
                     brand: str) -> tuple[dict[str, dict[str, str]], list[int], dict[int, str]]:
    """The pages' words with the search changes Chris approved laid over them (seo/changes.py: approved, live or kept,
    every kind, oldest first): (the words, the changes laid, and why for each change left off). A change is laid only
    while the page still says what it replaced (an older change on the same page counts) and its words pass
    change_problems today; otherwise the page keeps the words it has. A new page (kind "page") is added at an address
    the site does not have while it passes added_page_problems; a page taken down (kind "takedown") leaves, and only a
    page a search change added can."""
    out = {rel: dict(w) for rel, w in words.items()}
    names = ai_names.public_names(conn)
    laid, left_off, added = [], {}, set()
    for ch in seo_changes.on_site(conn):
        rel = rel_of(ch["page"])
        before, after = json.loads(ch["before"]), json.loads(ch["after"])
        if ch["kind"] == "page":
            if rel in out:
                left_off[ch["id"]] = f"the site already has a page at {ch['page']}"
            elif why := added_page_problems(ch["page"], after, brand, names):
                left_off[ch["id"]] = f"its words no longer pass: {'; '.join(why)}"
            else:
                out[rel] = {f: after[f] for f in ("title", "description", "lead")}
                added.add(rel)
                laid.append(ch["id"])
        elif ch["kind"] == "takedown":
            if rel in out and rel not in added:
                left_off[ch["id"]] = f"{ch['page']} is not a page a search change added"
            else:
                out.pop(rel, None)
                added.discard(rel)
                laid.append(ch["id"])
        elif rel not in out:
            left_off[ch["id"]] = f"the site no longer has the page {ch['page']}"
        elif any(out[rel].get(f) != v for f, v in before.items()):
            left_off[ch["id"]] = f"{ch['page']} no longer has the words it replaced"
        elif why := change_problems(rel, {**out[rel], **after}, after, brand, names):
            left_off[ch["id"]] = f"its words no longer pass: {'; '.join(why)}"
        else:
            out[rel].update(after)
            laid.append(ch["id"])
    return out, laid, left_off


def site_words(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Every page's words (page_words) as the next live build writes them: its own, with the approved changes."""
    brand = config.get_config().brand_name
    return with_seo_changes(conn, page_words(offer.load(), copy_text(), brand), brand)[0]


def seo_pages(conn: sqlite3.Connection, words: dict[str, dict[str, str]], laid: list[int]) -> tuple[list[dict], list[str]]:
    """From with_seo_changes' words and the changes it laid: the pages search changes added that the site carries, in
    the order he approved them, each what its change sets (heading, name, title, description, lead, paragraphs, shots)
    with its "key" (the last part of its address), "path" and "rel"; and the addresses taken down, for the Worker."""
    added, removed = [], []
    for ch in seo_changes.on_site(conn):
        rel = rel_of(ch["page"])
        if ch["id"] not in laid:
            continue
        if ch["kind"] == "page" and rel in words:
            added.append({**json.loads(ch["after"]), "key": ADDED_PATH.fullmatch(ch["page"]).group(1), "path": ch["page"], "rel": rel})
        elif ch["kind"] == "takedown" and rel not in words:
            removed.append(ch["page"])
    return added, removed


def added_pages(conn: sqlite3.Connection) -> list[dict]:
    """The pages search changes added that the next live build carries (seo_pages)."""
    brand = config.get_config().brand_name
    words, laid, _ = with_seo_changes(conn, page_words(offer.load(), copy_text(), brand), brand)
    return seo_pages(conn, words, laid)[0]


def public_pages(conn: sqlite3.Connection) -> tuple[str, ...]:
    """Every public page: the ones offer.json makes (PAGES, in sitemap order), then the pages search changes added. The
    sitemap, IndexNow, the outside check, Google's index check and the search changes' finders read this list."""
    return PAGES + tuple(p["path"] for p in added_pages(conn))


def _photo(entry):
    """(image, alt[, meta[, slug[, label]]]) -> (image, alt, meta, slug, label); fixtures and older callers pass two or three."""
    im, alt = entry[0], entry[1]
    meta = entry[2] if len(entry) > 2 else ImageMeta(title=alt, description=alt, keywords=GENERIC_KEYWORDS)
    slug = entry[3] if len(entry) > 3 else ""
    label = entry[4] if len(entry) > 4 else alt
    return im, alt, meta, slug, label


def _ticker(labels: list[str], rev: bool = False) -> str:
    items = []
    for i, label in enumerate(labels):
        items.append(f'<span class="{"o" if i % 2 else ""}">{html.escape(label)}</span><span class="dot">&#9679;</span>')
    run = "".join(items)
    return f'<div class="ticker{" rev" if rev else ""}" aria-hidden="true"><div class="track">{run}{run}</div></div>'


def coverage_rows(coverage: list[dict], skip: str = "", added: list[dict] = ()) -> str:
    """The coverage list, each row opening its own page (2026-10-14; it led to the quote form). An entry with "listed":
    false in offer.json is a page, not a row (2026-10-31: instant delivery is the hero's detailed page, and the bottom
    service is the selects: "the instant delivery doesn't need to be at the bottom service anymore that is the selects
    option now"). `added`: the pages search changes added ({"key", "label"} each, 2026-11-01), after the listed rows so
    the order Chris set stands; the home page's list never passes them."""
    e = html.escape
    rows = [c for c in coverage if c.get("listed", True)] + list(added)
    return "".join(
        f'<a href="/coverage/{e(c["key"])}/"><span class="mono g">{i + 1:02d}</span>'
        f'<span class="t">{e(c["label"])}{f"<em>{e(c["note"])}</em>" if c.get("note") else ""}</span><span class="mono">&#8599;</span></a>'
        for i, c in enumerate(rows) if c["key"] != skip)


def coverage_body(label: str, lead: str, paragraphs: list[str], photos: list, rows: str) -> str:
    """A coverage page (2026-10-14), one template for the pages offer.json lists and the pages search changes add
    (2026-11-01, seo/pages.py): the label as its headline, the lead sentence, its paragraphs, its photos (`photos`: (the
    saved widths, alt, meta, shape) each, every one in its own shape), the quote button and the rest of the coverage
    (`rows`, coverage_rows)."""
    e = html.escape
    figures = "".join(f'<figure style="--ar:{ar}">{img_tag(files, alt, "(max-width:760px) 50vw, (max-width:1100px) 50vw, 33vw")}</figure>'
                      for files, alt, _m, ar in photos)
    prose = "".join(f"<p>{e(p)}</p>" for p in paragraphs)
    return f"""
<section class="page cover"><div class="kick mono c"><a href="/coverage/">Coverage</a></div><h1>{e(label)}<b>.</b></h1>
<p class="first">{e(lead)}</p><div class="prose">{prose}</div>
{f'<div class="grid">{figures}</div>' if figures else ''}
<p style="margin-top:50px"><a class="btn fill" href="/book/">Request a quote <span class="arr">&#8599;</span></a></p>
<div class="more"><div class="kick mono c">The rest of the coverage</div><div class="list">{rows}</div></div></section>"""


def home_body(t: dict, lead: str, hero: str, frames: list[tuple[str, str, str, str]], stack: list[tuple[str, str]],
              venues: list[tuple[str, str]], clients: str = "") -> str:
    """`lead`: the sentence under the headline (page_words, with any approved search change). `frames`: (img tag,
    caption, the coverage page it opens, the photo's shape); `stack`: (img tag, shape); `venues`: (img tag, label,
    shape). The shape (--ar) gives every frame the photo's own proportions, so nothing is cropped. `clients`: the logo
    strip under the hero (clients_body), or nothing."""
    e = html.escape
    coverage = offer.load()["coverage"]
    rows = coverage_rows(coverage)
    reel = "".join(f'<div class="frame"><a href="{href}"><div class="ph" style="--ar:{ar}">{img}</div><div class="cap mono"><span>FR {i + 1:02d} / {len(frames):02d}</span>'
                   f'<span>{e(cap)}</span></div></a></div>' for i, (img, cap, href, ar) in enumerate(frames))
    # the strip doubled, so it rolls round without a jump; the copy is hidden from readers and the keyboard
    again = reel.replace('<div class="frame">', '<div class="frame" aria-hidden="true">').replace("<a href=", '<a tabindex="-1" href=')
    stack_html = "".join(f'<figure style="--ar:{ar}">{img}</figure>' for img, ar in stack[:3])
    # no word on the picture (2026-10-15: it said Interior over a building's outside, by position, never by the photo)
    venue_html = "".join(f'<figure style="--ar:{ar}">{img}</figure>' for img, ar in venues[:VENUE_ROWS])
    steps = "".join(f'<div class="rv"><div class="n">{i:02d}</div><h3>{e(h)}</h3><p>{e(p)}</p></div>'
                    for i, (h, p) in enumerate(t["steps"], start=1))
    # the ticker says the rows in their order (2026-10-31: "Start with main stage... backstage and green rooms should be the
    # bottom two", then "keep selects at the end")
    short = ["Main stage", "Breakouts", "Evening events", "Dinners", "Portraits", "Exhibition halls", "Backstage",
             "Green rooms", "Selects within the hour"]
    return f"""
<section class="hero"><div class="photo"><div class="img">{hero}</div><canvas class="web" aria-hidden="true"></canvas>
<div class="vf" aria-hidden="true"><i></i><i></i><i></i><i></i></div></div>
<div class="copy"><div class="kick mono c">{e(t['kicker'])}</div>
<h1 class="mega"><span><em>Convention</em></span><span class="o"><em>photographers,</em></span><span><em>Washington, DC<b>.</b></em></span></h1>
<p class="sub">{e(t['sub'])}</p>
<p class="first">{e(lead)}</p>
<div class="row"><p class="lede">{e(t['lede_delivery'])} <a class="c" href="{e(offer.coverage_page('on_site_delivery'))}">More about instant delivery &#8599;</a> {e(t['lede_brothers'])}</p><a class="btn fill" href="/book/">Request a quote <span class="arr">&#8599;</span></a></div></div></section>
{clients}{_ticker(short)}
<section id="coverage" class="index"><div class="head rv"><div><div class="kick mono c">Coverage</div>
<h2>From the green room<br><span class="o">to the last</span> reception.</h2></div><p>{e(t['coverage_p'])}</p></div>
<div class="list rv">{rows}</div></section>
{f'<section id="work" class="reel"><div class="bar"><div class="kick mono c" style="margin:0">Work</div><span class="hint mono">Rolls on its own. Swipe, or use the arrows.</span><div class="arrows"><button type="button" data-dir="prev" aria-label="Previous photos">&#8592;</button><button type="button" data-dir="next" aria-label="Next photos">&#8594;</button></div></div><div class="track" aria-label="Photographs from our events">{reel}{again}</div><div class="sprocket" style="margin-top:22px"></div></section>' if reel else ''}
<section><div class="rv"><div class="kick mono c">Who will be at your event</div><h2>One of us, <span class="o">every</span> time.</h2>
<p class="g" style="max-width:640px;margin-top:22px">{e(t['who'])}</p>
<p class="mono g" style="margin-top:14px">References available on request. <a class="c" href="/about/">About the two of us &#8599;</a></p></div></section>
<section class="deliver"><div class="rv"><div class="kick mono c">Selects during the event</div>
<h2>Your selects, <span class="o">within</span> the hour.</h2><p>{e(t['selects_p'])}</p></div>
{f'<div class="stack rv">{stack_html}<span class="stamp mono">Selects</span></div>' if stack_html else ''}</section>
{f'<section id="venues" class="venues"><div class="head rv"><div><div class="kick mono c">Venues</div><h2>The building is <span class="o">part of</span> the story.</h2></div><p>{e(t["venues_p"])}</p></div><div class="grid{' one' if len(venues[:VENUE_ROWS]) == 1 else ''}">{venue_html}</div></section>' if venue_html else ''}
<section><div class="kick mono c rv">How it works</div><h2 class="rv">Three steps.</h2><div class="steps">{steps}</div></section>
{_ticker(list(reversed(short)), rev=True)}
<section class="cta"><div class="kick mono c" style="justify-content:center">Planning an event</div>
<a class="huge" href="/book/">Request a quote</a><p>{e(t['cta_p'])}</p></section>"""


TOKEN = r"[A-Za-z0-9_-]{8,128}"                 # the content value of the HTML tag, or the TXT record's value
FILE_NAME = r"google[0-9a-f]{16}\.html"          # the HTML file method: the file's name, served at the root
VERIFICATION_HELP = ("paste what Search Console shows for one of its methods: the HTML tag or its content value, "
                     "the TXT record (google-site-verification=...), or the HTML file's name (google....html)")


def parse_verification(raw: str) -> tuple[str, str, str]:
    """(token, file name, problem) from what was pasted on the Keys page. Chris may paste the whole <meta>
    tag, only its content value, the TXT record Search Console offers for a Domain property, or the HTML
    file's name or content; only the token or the file name survives, and only a value that could not break
    the page. A value that is none of these is a problem said in plain words, never a silent blank
    (2026-10-13: the Website card said "tag missing" over a filled field, and nothing said why)."""
    raw = "".join((raw or "").split())            # a secret never carries whitespace (core/secrets); the same here
    if not raw:
        return "", "", ""
    m = re.search(r'content=["\']?([^"\'>/\s]+)', raw)
    if m:
        token = m.group(1)
    elif raw.lower().startswith("google-site-verification="):
        token = raw.split("=", 1)[1]
    elif raw.lower().startswith("google-site-verification:"):
        name = raw.split(":", 1)[1]
        return ("", name, "") if re.fullmatch(FILE_NAME, name) else ("", "", f"not a Search Console value; {VERIFICATION_HELP}")
    elif re.fullmatch(FILE_NAME, raw):
        return "", raw, ""
    else:
        token = raw
    if re.fullmatch(TOKEN, token):
        return token, "", ""
    return "", "", f"not a Search Console value; {VERIFICATION_HELP}"


def _verification() -> tuple[str, str, str]:
    from ..core import secrets
    return parse_verification(secrets.get_secret(VERIFICATION_KEY) or "")


def verification_value() -> str:
    """The Google Search Console tag's content value from the Keys page ("" when none, or when the HTML file
    method was pasted instead)."""
    return _verification()[0]


def verification_file() -> str:
    """The HTML file method's file name from the Keys page, or ""."""
    return _verification()[1]


def verification_problem() -> str:
    """Why the Keys page's value cannot reach the site, or "" when it is empty or usable."""
    return _verification()[2]


def _lastmod_path() -> Path:
    return config.get_config().data_root / "site" / LASTMOD_FILE


def page_dates(out: Path, rels: dict[str, str], *, preview: bool, today: Optional[str] = None) -> dict[str, str]:
    """{path: YYYY-MM-DD} the date each page's content last changed, for the sitemap's lastmod.

    A page's content is its HTML plus every /assets/ file its body shows (a new hero changes the home
    page even when the file name does not; the head's og:image, the same on every page, does not
    count). The record under DATA_ROOT/site is updated only by a live build; a preview reads it and
    never writes (so a preview is side-effect free)."""
    today = today or datetime.now(timezone.utc).date().isoformat()
    try:
        record = json.loads(_lastmod_path().read_text())
    except (OSError, ValueError):
        record = {}
    dates, changed = {}, False
    for path, rel in rels.items():
        page = out / rel
        text = page.read_text(encoding="utf-8")
        body = text[text.index("<main>"):] if "<main>" in text else text
        h = hashlib.sha256(page.read_bytes())
        for ref in sorted(set(re.findall(r'/assets/[A-Za-z0-9_./-]+', body))):
            asset = out / ref.lstrip("/")
            if asset.is_file():
                h.update(ref.encode()); h.update(asset.read_bytes())
        digest = h.hexdigest()
        known = record.get(path) or {}
        if known.get("sha") == digest and known.get("date"):
            dates[path] = known["date"]
        else:
            dates[path] = today
            if not preview:
                record[path] = {"sha": digest, "date": today}
                changed = True
    if changed:
        _lastmod_path().parent.mkdir(parents=True, exist_ok=True)
        _lastmod_path().write_text(json.dumps(record, indent=0, sort_keys=True))
    return dates


def mark_file(mark_key: str, brand: str) -> str:
    """The mark as its own file (/assets/mark.svg: the favicon, the logo search engines read, the upload page's icon). A
    file needs the SVG namespace that an inline <svg> does without; without it a browser draws nothing (2026-10-15)."""
    return marks.mark(mark_key, brand, light="#0A0A0B", size=64, word=False).replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)


def site_assets(assets: Path, brand: str, at: str = "/assets/") -> tuple[str, str]:
    """The files every page uses, written into `assets`: the fonts, the stylesheet, the script and the mark. `at`: where
    they are served, when not at /assets/ (a preview on the dashboard). (the mark's key, the mark for the page header)"""
    (assets / "fonts").mkdir(parents=True)
    for name in ("Michroma-Regular.ttf", "JetBrainsMono-Medium.ttf", "InterTight-Light.ttf", "InterTight-Regular.ttf",
                 "InterTight-SemiBold.ttf", "Unbounded-ExtraBold.ttf"):
        src = fonts._find(name)
        if src:
            shutil.copyfile(src, assets / "fonts" / name)
    (assets / "site.css").write_text(theme.CSS.replace("/assets/", at))
    (assets / "site.js").write_text(theme.JS)
    mark_key = (config.getenv("BRAND_MARK") or "aperture").lower()       # Chris chose Aperture, 2026-10-10
    (assets / "mark.svg").write_text(mark_file(mark_key, brand))
    return mark_key, marks.mark(mark_key, brand, size=40)


def build(conn: Optional[sqlite3.Connection], photos: SitePhotos, *, out: Path = DIST, preview: bool = False,
          head_extra: str = "") -> Path:
    o = offer.load()
    cfg = config.get_config()
    brand = cfg.brand_name
    verification, verification_name, verification_bad = _verification()
    if verification_bad and conn is not None and not preview:
        from ..core import runner
        runner.record_error_once(conn, "site", "verification_tag",
                                 f"The Google Search Console value on the Keys page is {verification_bad}. The site is built without it.")
    t = copy_text()
    check_copy([v if isinstance(v, str) else " ".join(x for pair in v for x in pair) for v in t.values()] + offer.coverage_labels()
               + [c[k] for c in o["coverage"] for k in ("note", "title", "first", "about") if c.get(k)] + [AREA_LINE])
    if out.exists():
        shutil.rmtree(out)
    assets = out / "assets"
    mark_key, mark_svg = site_assets(assets, brand)
    e = html.escape
    hero, frames, stack, venues = "", [], [], []
    shown: list[tuple[str, str, ImageMeta]] = []          # (published path, alt, meta) for the sitemap and JSON-LD
    if photos.hero:
        im, alt, m, _slug, _label = _photo(photos.hero[0])      # the hero file keeps its name: og:image and the preload point at it
        files = save_web(dodge_shadows(im), assets, "hero", m)
        hero = img_tag(files, alt, "100vw", eager=True)
        shown.append((f"/assets/{files[max(files)]}", alt, m))
    for i, entry in enumerate(photos.coverage):
        im, alt, m, slug, label = _photo(entry)
        files = save_web(im, assets, slug or f"work-{i}", m)             # the file is named by the writer's slug when there is one
        shown.append((f"/assets/{files[max(files)]}", alt, m))
        tag = img_tag(files, alt, "(max-width:760px) 92vw, 62vw")        # a wide frame can be most of the screen: never a soft copy
        frames.append((tag, label[:34], photos.links[i] if i < len(photos.links) else "/coverage/", aspect(im)))   # the caption stays the kind of shot
        if i < 3:
            stack.append((tag, aspect(im)))
    # the coverage pages' photos (2026-10-14), each saved once however many pages show it
    page_files: dict[str, list[tuple[dict, str, ImageMeta]]] = {}
    saved: dict[int, dict] = {}
    for key, entries in photos.pages.items():
        page_files[key] = []
        for j, entry in enumerate(entries):
            im, alt, m, slug, _label = _photo(entry)
            if id(im) not in saved:
                saved[id(im)] = save_web(im, assets, slug or f"cover-{key}-{j}", m)
            page_files[key].append((saved[id(im)], alt, m, aspect(im)))
    for i, entry in enumerate(photos.venues[:VENUE_ROWS]):
        im, alt, m, slug, _label = _photo(entry)
        files = save_web(im, assets, slug or f"venue-{i}", m)
        shown.append((f"/assets/{files[max(files)]}", alt, m))
        venues.append((img_tag(files, alt, "(max-width:760px) 100vw, 50vw"), aspect(im)))
    logos, left_out = client_logos(o)
    heading = (o.get("clients") or {}).get("heading") or "We've photographed for"
    if logos:
        check_copy([heading])
    saved_logos = []
    for c in logos:
        file, lw, lh = save_logo(c, assets / "clients")
        saved_logos.append((file, c["name"], lw, lh))
    strip = clients_body(heading, saved_logos)
    if left_out and conn is not None and not preview:
        from ..core import runner
        runner.record_error_once(conn, "site", "client_logos", "Logos left off the home page: " + "; ".join(left_out) + ".")
    base = f"https://{cfg.brand_domain}"
    words = page_words(o, t, brand)
    laid, not_laid, added, removed = [], {}, [], []
    if conn is not None:
        words, laid, not_laid = with_seo_changes(conn, words, brand)       # the search changes Chris approved (2026-11-01)
        added, removed = seo_pages(conn, words, laid)
    rows_after = [{"key": p["key"], "label": p["heading"]} for p in added]   # the added pages, after the listed rows
    def head(rel: str) -> tuple[str, str]:
        return words[rel]["title"], words[rel]["description"]
    pages = {"index.html": (*head("index.html"), home_body(t, words["index.html"]["lead"], hero, frames, stack, venues, strip))}
    page_shown: dict[str, list[tuple[str, str, ImageMeta]]] = {"/": list(shown)}     # per page, for the sitemap and the image blocks
    page_og: dict[str, str] = {}
    page_jsonld: dict[str, str] = {}
    page_noindex: set[str] = set()
    coverage_list = tuple((c["key"], c["label"]) for c in offer.listed_coverage())      # the footer: rows, not every page
    # the coverage index and one page per coverage item (2026-10-14: every row led to the quote form)
    pages["coverage/index.html"] = (*head("coverage/index.html"), f"""
<section class="page cover"><div class="kick mono c">Coverage</div><h1>Every<br><span class="o">room</span><b>.</b></h1>
<p class="first">{e(words['coverage/index.html']['lead'])}</p>
<p class="g" style="max-width:640px;margin:18px 0 0">{e(t['coverage_p'])}</p>
<div class="list" style="margin-top:50px">{coverage_rows(o['coverage'], added=rows_after)}</div>
<p style="margin-top:50px"><a class="btn fill" href="/book/">Request a quote <span class="arr">&#8599;</span></a></p></section>""")
    page_jsonld["coverage/index.html"] = markup.jsonld_script(markup.jsonld_breadcrumbs([(brand, base + "/"), ("Coverage", base + "/coverage/")]))
    # one page per coverage item, then the pages search changes added (2026-11-01), each built the same way: its label,
    # its lead, its paragraphs, its photos, the rest of the coverage, and its Service, BreadcrumbList and photo blocks
    cover = ([{"key": c["key"], "label": c["label"], "service": c["title"], "summary": c["first"], "paragraphs": [c["about"]]}
              for c in o["coverage"]]
             + [{"key": p["key"], "label": p["heading"], "service": p["name"], "summary": words[p["rel"]]["description"],
                 "paragraphs": p["paragraphs"]} for p in added])
    for c in cover:
        rel = f"coverage/{c['key']}/index.html"
        pages[rel] = (*head(rel), coverage_body(c["label"], words[rel]["lead"], c["paragraphs"], page_files.get(c["key"], []),
                                                coverage_rows(o["coverage"], skip=c["key"], added=rows_after)))
        page_shown["/" + rel.replace("index.html", "")] = [(f"/assets/{files[max(files)]}", alt, m) for files, alt, m, _ in page_files.get(c["key"], [])]
        first_photo = page_shown["/" + rel.replace("index.html", "")]
        page_og[rel] = (base + first_photo[0][0]) if first_photo else ""
        page_url = f"{base}/coverage/{c['key']}/"
        blocks = [markup.jsonld_service(c["service"], c["summary"], page_url, brand, base + "/", area_served=list(AREA_SERVED),
                                        image=page_og[rel]),
                  markup.jsonld_breadcrumbs([(brand, base + "/"), ("Coverage", base + "/coverage/"), (c["label"], page_url)])]
        blocks += [markup.jsonld_image(markup.absolute(base, loc), brand, cfg.legal_name, m.credit or brand, markup.absolute(base, "/contact/")) for loc, _, m in first_photo]
        page_jsonld[rel] = "".join(markup.jsonld_script(b) for b in blocks)
    # the contact page (2026-10-14): email and phone, no form (his decision); the quote form for dates
    phone = contact_phone()
    pages["contact/index.html"] = (*head("contact/index.html"), f"""
<section class="page contact"><div class="kick mono c">Contact</div><h1>Get in<br><span class="o">touch</span><b>.</b></h1>
<p class="first">{e(words['contact/index.html']['lead'])}</p>
<div class="hand"><div><div class="mono c">Email</div><a class="l" href="mailto:{e(contact_email())}">{e(contact_email())}</a></div>
{f'<div><div class="mono c">Phone</div><a class="l" href="{theme.tel_href(phone)}">{e(phone)}</a></div>' if phone else ''}</div>
<p class="g" style="max-width:640px;margin-top:30px">{e(t['contact_p'])}</p>
<p style="margin-top:30px"><a class="btn fill" href="/book/">Request a quote <span class="arr">&#8599;</span></a></p>
<p class="mono g" style="margin-top:30px">{e(AREA_LINE)} <a href="/privacy/" class="c">Privacy and photo removal</a>.</p></section>""")
    chips = "".join(f'<label><input type="checkbox" name="coverage" value="{e(c["key"])}"><span>{e(c["label"])}</span></label>'
                    for c in o["coverage"])
    mail_link = f'<a href="mailto:{e(contact_email())}" class="c">{e(contact_email())}</a>'
    # Cloudflare Turnstile (2026-10-24): managed, shown only when Cloudflare wants the visitor to tick a box, above Send;
    # the Worker refuses a request without its token (worker/index.js turnstileRefusal)
    turnstile = (f'<div class="cf-turnstile" data-sitekey="{TURNSTILE_SITE_KEY}" data-action="{TURNSTILE_ACTION}" data-theme="dark" '
                 'data-size="flexible" data-appearance="interaction-only" data-callback="checkPassed" '
                 'data-expired-callback="checkExpired" data-error-callback="checkFailed"></div>'
                 f'<noscript><p class="mono g" style="margin-bottom:22px">This form needs JavaScript. Without it, email us at {mail_link}.</p></noscript>')
    questions = "".join(f"<li>{e(q)}</li>" for q in (o.get("quote_questions") or [])[:4])
    pages["book/index.html"] = (*head("book/index.html"), f"""
<section class="page"><div class="kick mono c">Request a quote</div><h1>Tell us about<br><span class="o">your</span> event<b>.</b></h1>
<p class="g" style="max-width:640px;margin:18px 0 30px">Send the dates, the venue and the rooms that matter, and one of us writes back within 24 hours.
What moves the quote: the days and hours, the rooms covered at the same time, how many photographers, how fast you need selects, and where the images will be used.</p>
{BOOKED_LINE}
<div class="split2"><aside class="side"><div class="mono c">What helps the quote</div><ol>{questions}</ol>
<p class="mono g" style="margin-top:22px">Every event is quoted on its own.</p></aside>
<div><div id="err"></div><form class="book" method="post" action="/api/quote">
<div class="f"><label class="mono" for="name">Your name</label><input id="name" name="name" required maxlength="120" autocomplete="name"></div>
<div class="f"><label class="mono" for="email">Email</label><input id="email" name="email" type="email" required maxlength="200" autocomplete="email"></div>
<div class="f"><label class="mono" for="phone">Phone, optional</label><input id="phone" name="phone" maxlength="40" autocomplete="tel"></div>
<div class="f"><label class="mono" for="organization">Organization</label><input id="organization" name="organization" maxlength="160" autocomplete="organization"></div>
<div class="f full"><label class="mono" for="event_name">Event name</label><input id="event_name" name="event_name" maxlength="200"></div>
<div class="f full"><label class="mono" for="event_kind">Kind of event</label><select id="event_kind" name="event_kind"><option value="business">Conference, convention or corporate event</option>
<option value="other">Gala, reception or something else</option></select></div>
<div class="f"><label class="mono" for="attendance">Expected attendance</label><input id="attendance" name="attendance" maxlength="40"></div>
<div class="f"><label class="mono" for="start_date">First day</label><input id="start_date" name="start_date" type="date"></div>
<div class="f"><label class="mono" for="end_date">Last day</label><input id="end_date" name="end_date" type="date"></div>
<div class="f"><label class="mono" for="venue">Venue</label><input id="venue" name="venue" maxlength="200"></div>
<div class="f"><label class="mono" for="city">City</label><input id="city" name="city" maxlength="120"></div>
<div class="f full"><label class="mono">What should be covered</label><div class="chips">{chips}</div></div>
<div class="f full"><label class="mono" for="message">Anything else</label><textarea id="message" name="message" maxlength="4000"></textarea></div>
<div class="hp" aria-hidden="true"><label for="website">Leave this empty</label><input id="website" name="website" tabindex="-1" autocomplete="off"></div>
<div class="full">{turnstile}<button class="btn fill" type="submit">Send the request <span class="arr">&#8599;</span></button>
<p class="mono g" style="margin-top:16px">Used only to reply to you and put your quote together. <a href="/privacy/" class="c">Privacy</a>.</p></div>
</form></div></div></section>
<script>const q=new URLSearchParams(location.search).get("error");const m={{missing:"Please add your name and a working email.",busy:"A few requests just came from here. Please try again in an hour, or email us.",check:"The spam check did not pass. Please try again.",closed:'The form is not taking requests right now. Please email us at {mail_link}.',unreadable:"Something went wrong. Please try again."}};
const err=document.getElementById("err"),say=t=>{{err.innerHTML=t?'<div class="err mono">'+t+'</div>':""}};if(q)say(m[q]||m.unreadable);
// the spam check runs while the form is filled in; Send waits for its token when it has to, and says so
const book=document.querySelector("form.book"),box=book.querySelector(".cf-turnstile");let token="",waiting=false,failed=false,timer=0;
new ResizeObserver(([en])=>box.classList.toggle("shown",en.contentRect.height>0)).observe(box);   // room above Send only while the box shows
function checkPassed(t){{token=t;if(failed){{failed=false;say("")}}if(waiting){{waiting=false;clearTimeout(timer);book.submit()}}}}
function checkExpired(){{token=""}}
function checkFailed(){{token="";waiting=false;failed=true;clearTimeout(timer);say('Our spam check could not load in this browser. Please email us at {mail_link}.')}}
book.addEventListener("submit",ev=>{{if(token)return;ev.preventDefault();waiting=true;say("One moment: checking the connection before sending.");timer=setTimeout(checkFailed,20000)}});</script>
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer onerror="checkFailed()"></script>""")
    about_photos = "".join(f'<figure style="--ar:{ar}">{img}</figure>' for img, _, _, ar in frames[:2])
    about_paras = "".join(f"<p>{e(p)}</p>" for p in t["about"].split("\n\n"))
    pages["about/index.html"] = (*head("about/index.html"), f"""
<section class="page cover"><div class="kick mono c">About</div><h1>Two<br><span class="o">brothers</span><b>.</b></h1>
<div class="prose" style="max-width:640px;margin-top:30px">{about_paras}
<h3>Who will be at your event</h3><p>{e(t['who'])}</p><p>References available on request.</p></div>
{f'<div class="grid" style="margin-top:50px">{about_photos}</div>' if about_photos else ''}
<p style="margin-top:50px"><a class="btn fill" href="/book/">Request a quote <span class="arr">&#8599;</span></a></p></section>""")
    pages["thanks/index.html"] = (*head("thanks/index.html"), f"""<section class="page">
<div class="kick mono c">Request received</div><h1>Thank<br><span class="o">you</span><b>.</b></h1>
<p class="first">{e(words['thanks/index.html']['lead'])}</p>
<p class="g" style="max-width:560px;margin-top:18px">{e(t['thanks_p'])}</p>
<p style="margin-top:30px"><a class="btn" href="/coverage/">The coverage <span class="arr">&#8599;</span></a> <a class="btn" href="/">Back to the site <span class="arr">&#8599;</span></a></p></section>""")
    pages["privacy/index.html"] = (*head("privacy/index.html"), f"""
<section class="page"><div class="kick mono c">Privacy</div><h1>Privacy<b>.</b></h1><div class="prose">
<h3>The quote form</h3><p>What you send through the form is used only to reply to you and to prepare your quote.
It is never sold or shared. The website holds it only until the booking inbox collects it, which it does every ten minutes.</p>
<h3>Photos of you</h3><p>If you appear in a photo shared by {e(brand)} and want it taken down, email
<a class="c" href="mailto:{e(contact_email())}">{e(contact_email())}</a> with a link to it. It comes down, and it stays out of anything shared after that.</p>
<h3>Who we are</h3><p>{e(t['who_we_are'].format(email=contact_email()))}</p></div></section>""")
    pages["404.html"] = (*head("404.html"), f"""<section class="page"><div class="kick mono c">Out of frame</div>
<h1>Not<br><span class="o">found</span><b>.</b></h1><p class="first">{e(words['404.html']['lead'])}</p>
<p style="margin-top:30px"><a class="btn" href="/">Back to the site <span class="arr">&#8599;</span></a> <a class="btn" href="/coverage/">The coverage <span class="arr">&#8599;</span></a> <a class="btn" href="/contact/">Contact <span class="arr">&#8599;</span></a></p></section>""")
    og = f"{base}/assets/hero-1600.jpg" if hero else ""
    preload = ", ".join(f"/assets/hero-{w}.jpg {w}w" for w in WIDTHS) if hero else ""
    sections = tuple(name for name, there in (("work", frames), ("venues", venues)) if there)
    socials = social_links()
    if not head_extra:
        blocks = [markup.jsonld_business(brand, cfg.legal_name, base + "/", contact_email(), t["description"],
                                         telephone=phone or None, same_as=[url for _, url in socials], area_served=list(AREA_SERVED),
                                         locality="Washington", region="DC", country="US", image=og, logo=f"{base}/assets/mark.svg")]
        blocks += [markup.jsonld_image(markup.absolute(base, loc), brand, cfg.legal_name, m.credit or brand, markup.absolute(base, "/contact/"))
                   for loc, _, m in shown]
        head_extra = "".join(markup.jsonld_script(b) for b in blocks)
    page_jsonld["index.html"] = head_extra
    page_jsonld["about/index.html"] = "".join(markup.jsonld_script(markup.jsonld_person(
        name, "Photographer", brand, base + "/", base + "/about/", alumni_of="The Corcoran, Washington, DC")) for name in ("Chris Kennedy", "Nic Kennedy"))
    page_noindex.update({"thanks/index.html", "404.html"})
    titles: dict[str, str] = {}
    for rel, (title, desc, body) in pages.items():                  # every page is judged before any is written
        check_copy([desc])
        titles[rel] = full_title(rel, title, brand)
        if len(titles[rel]) > TITLE_MAX or len(desc) > DESCRIPTION_MAX:
            raise SiteCopyRefused(f"{rel}: the title ({len(titles[rel])} characters, {TITLE_MAX} at most) or the description "
                                  f"({len(desc)}, {DESCRIPTION_MAX} at most) is too long for a search result")
    for rel, (title, desc, body) in pages.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        path = "/" + rel.replace("index.html", "")
        dest.write_text(theme.shell(title=e(titles[rel]), description=e(desc), body=body,
                                    mark_svg=mark_svg, brand=e(brand), legal=e(cfg.legal_name), email=e(contact_email()),
                                    preview=preview, canonical=base + path, jsonld=page_jsonld.get(rel, ""),
                                    og_image=page_og.get(rel) or og, sections=sections, verification=verification, path=path,
                                    phone=e(phone), socials=tuple((e(a), e(b)) for a, b in socials), coverage=tuple((e(a), e(b)) for a, b in coverage_list),
                                    area_line=e(AREA_LINE), noindex=rel in page_noindex,
                                    preload=preload if rel == "index.html" else ""), encoding="utf-8")
    # a preview is never crawled; the live site lists its public pages and every photo on them, each with the
    # date its content last changed (Chris, 2026-10-12: "no site map or Google search indexing")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n" if preview else markup.robots_txt(base))
    if verification_name and not preview:
        # the HTML file method: Search Console reads this file at the root, with this one line in it
        (out / verification_name).write_text(f"google-site-verification: {verification_name}\n")
    listed = PAGES + tuple(p["path"] for p in added)        # every public page (public_pages): the added ones too
    rels = {p: rel_of(p) for p in listed}
    (out / "sitemap.xml").write_text(markup.sitemap_xml(
        base, list(listed),
        {page: [{"loc": loc, "title": m.title or alt, "caption": m.description or alt} for loc, alt, m in entries]
         for page, entries in page_shown.items() if entries},
        lastmod=page_dates(out, rels, preview=preview)))
    # the pages Chris took down (2026-11-01): their addresses answer 301 to the coverage index, from the Worker
    (out / REMOVED_FILE).write_text(json.dumps({"pages": removed}))
    if not preview and indexnow.key():
        indexnow.write_key_file(out, indexnow.key())        # /<key>.txt: the proof the IndexNow pings are ours
    if conn is not None and not preview and photos.grid_ids:
        # the rotation's memory (2026-10-14): the photos the home page shows were used now, so the next build and the
        # other surfaces reach for the rest first; a preview is a look, not a use. The coverage pages are a view of
        # the whole usable pool (six a room, least recently used first) and are not written here: recording them would
        # put every approved photo on the same footing after each build, and the home page would stop rotating.
        from ..library import report
        report.record_use(conn, "site", photos.grid_ids, ref=f"site:{db.utcnow()}")
    if conn is not None and not preview and photos.ids:
        # 2026-10-31: every library photo the site shows, home page and coverage pages, so the weekly writer gives them their
        # words first (seo/photo_text.wanted_photos); a note, not a use, so the rotation is untouched
        from ..core import settings
        settings.set(conn, SHOWN_KEY, json.dumps(photos.ids))
    if conn is not None and not preview:
        # the search changes this build carried: the deploy that sends it marks them live (seo/changes.went_live), and
        # one left off is said on the Errors page
        from ..core import runner, settings
        settings.set(conn, seo_changes.BUILT_KEY, json.dumps(laid))
        for cid, why in not_laid.items():
            runner.record_error_once(conn, "site", "seo_change", f"Search change {cid} is not on the site: {why}. "
                                                                 "The page keeps the words it had.")
    (out / "build.json").write_text(json.dumps({"preview": preview, "hero": len(photos.hero), "coverage": len(photos.coverage),
                                                "venues": len(photos.venues), "mark": mark_key}))
    return out


def library_fetch(conn: sqlite3.Connection, agent: str) -> tuple[Optional[Callable[[dict], Image.Image]], str]:
    """(fetch, "") where fetch(row) gives a library photo's pixels for the site: its own file (a phone photo) or the copy
    cached under the data root, else downloaded from Drive (read only) into that cache; (None, why) when Drive's sign-in
    cannot be used."""
    from ..agents import content
    from ..drive import oauth
    from ..drive.api import DriveReader
    try:
        oauth.access_token(conn)           # fail now, before any photo is asked for, if the sign-in is dead
        reader = DriveReader(lambda: oauth.access_token(conn), conn=conn, agent=agent)
    except oauth.DriveAuthError as e:
        return None, str(e)
    cfg = config.get_config()
    (cfg.data_root / "photos").mkdir(parents=True, exist_ok=True)

    def fetch(row: dict) -> Image.Image:
        own = content.photo_file(cfg, row)
        if not own.exists():
            own.write_bytes(reader.download(row["drive_id"]))
        return Image.open(io.BytesIO(own.read_bytes()))
    return fetch, ""


def page_preview(conn: sqlite3.Connection, path: str, page: dict, photos: list, out: Path, at: str) -> Path:
    """A page a search change proposes (seo/pages.py), as the site would show it, for Chris to see before he taps
    Approve (2026-11-01: "with a rendered preview first since a new page carries photos"). Written into `out`, never
    into site/dist and never published: the coverage page template (coverage_body) with the site's own stylesheet,
    script, fonts and mark, PREVIEW-stamped and noindex like every preview build; `photos` are its photos (image, alt[,
    meta, slug, label] each). The coverage lists are the site's, with this page after the listed rows as it would stand.
    The site's asset addresses (/assets/...) are written under `at`, where the dashboard serves them. The page file."""
    o, cfg = offer.load(), config.get_config()
    brand, e = cfg.brand_name, html.escape
    if out.exists():
        shutil.rmtree(out)
    assets = out / "assets"
    _, mark_svg = site_assets(assets, brand, at)
    key = ADDED_PATH.fullmatch(path).group(1)
    shown = []
    for j, entry in enumerate(photos):
        im, alt, m, slug, _label = _photo(entry)
        shown.append((save_web(im, assets, slug or f"cover-{key}-{j}", m), alt, m, aspect(im)))
    rows = [{"key": p["key"], "label": p["heading"]} for p in added_pages(conn)] + [{"key": key, "label": page["heading"]}]
    body = coverage_body(page["heading"], page["lead"], page["paragraphs"], shown, coverage_rows(o["coverage"], skip=key, added=rows))
    phone, socials = contact_phone(), social_links()
    text = theme.shell(title=e(full_title(rel_of(path), page["title"], brand)), description=e(page["description"]), body=body,
                       mark_svg=mark_svg, brand=e(brand), legal=e(cfg.legal_name), email=e(contact_email()), preview=True,
                       canonical=f"https://{cfg.brand_domain}{path}", path=path, phone=e(phone),
                       socials=tuple((e(a), e(b)) for a, b in socials),
                       coverage=tuple((e(c["key"]), e(c["label"])) for c in offer.listed_coverage()), area_line=e(AREA_LINE))
    (out / "index.html").write_text(text.replace("/assets/", at), encoding="utf-8")
    return out / "index.html"
