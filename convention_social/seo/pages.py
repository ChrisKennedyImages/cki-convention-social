"""Part three of the SEO loop (Chris, 2026-11-01: "shouldn't we have it do it all. Why wouldn't we?", and "Pages from
real demand: searches you appear for with no page built for them: new venue or event-type pages proposed, ranked by how
often people search", each coming to him "with a rendered preview first since a new page carries photos"): a search
people make often that no page of the site answers gets a page of its own under /coverage/, proposed to him through
seo/changes.py like every change, Approve and Skip, one tap from his phone, with the page rendered on the dashboard first.

Which searches, from the newest Search Console window kept (seo/search_console.py), each one:
- shown at least MIN_SHOWINGS times in the window, summed over the pages it was shown on;
- one public words may use (photo_text.searchable, part four's rule: every word a trade or place word, never the brand's
  own name, no name the names gate knows; a search can carry a name the gate has never seen, so anything else is left
  out, whatever it is);
- asking for something the business offers. What a search asks for is its words less the trade's own (photographer,
  photography, photos), the places served (PLACES) and the small words (in, near me, best); every one of those must be a
  word offer.json names its kinds of event and its coverage with, or a kind of shot the coverage pages show
  (site/build.COVERAGE_SHOTS). Portraits are headshots, and exhibition halls are vendors and booths (Chris, 2026-10-12).
  Anything else, a wedding, any kind of event offer.json does not name (the conventions it never advertises, his ruling
  of 2026-10-12, included), or a place not served, is never proposed. A search that asks for the business as a whole
  ("event photographer dc") is the home page's;
- never for a venue (VENUE): a venue page needs the venue's name, and names are his to decide (2026-10-11), so a search
  for a hotel, a ballroom or a convention center is left out and counted, waiting for his ruling;
- that no page answers: the page Google showed it on most is the home page, or sits at an average place worse than
  ANSWERED_PLACE, and no public page's title carries what it asks for.
Searches asking for the same thing (the same words in any order, singular or plural) mean the same page: one page, its
showings added up, its address the most shown one's words (/coverage/trade-show/). The most shown first, at most
PER_WEEK drafted a week, after parts one and two; never an address the site has, or had and took down.

For it, Claude (MODEL, under the monthly cap through ai/spend, changes.ask) writes the page: its heading, its name (the
title is the name and the place, as every coverage page's), its description, its lead sentence, one or two short
paragraphs and the kinds of photo it shows. Every draft is checked before it is proposed (check): site/build's
added_page_problems (the copy rules, the names rule, the lengths, the kinds of photo), no name and no number the site
does not already say (leads.unsaid), a title that carries every word of what was searched for, a new address. A draft
that fails is dropped with the reason in the run's summary, never proposed. The weekly run calls this only live.

The proposal is pinged with Preview, Approve and Skip; Preview opens the page as the site would show it (preview: the
coverage page template, real approved photos of its kinds, PREVIEW-stamped and noindex, under the data root, never
published). On Approve the build adds it like a coverage page, after the listed rows in the coverage lists and never on
the home page's, to the public pages, the sitemap and the structured data (site/build.with_seo_changes, seo_pages).
A new page is judged on its own (changes.NEW_PAGE); one that did not earn its place is never taken off by itself:
taking it down is proposed (TAKE_DOWN), and once he approves, its address answers 301 to /coverage/ (worker/index.js).
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from PIL import Image

from .. import offer
from ..ai import names as ai_names
from ..core import config, db
from ..site import build
from . import changes, leads, photo_text, search_console

KIND = "page"
MEASURE = changes.NEW_PAGE
STATUS_WORDS, PREVIEW = changes.STATUS_WORDS, True
SAID = {"ping": "a new page to approve",
        "close": ("Preview shows the page as the site would. Approve puts it on the site, after the listed pages in the coverage "
                  "lists, never on the home page's. It is {promise}."),
        "approve": ("Approved. The new page {page} goes on the site when it next publishes, in about ten minutes, after the listed "
                    "pages in the coverage lists. It is {promise}."),
        "skip": "Skipped. The page is not added, and the agent leaves {page} alone for eight weeks.",
        "proposed": "a new page proposed, {page}. {reason}",
        "approved": "you approved the new page {page}.",
        "live": "the new page {page} is on the site, measured for eight weeks from now.",
        "skipped": "you skipped the new page {page}."}
MODEL = "claude-opus-5"      # parts one and two's model (seo/titles.py)
MIN_SHOWINGS = 20            # a search shown fewer times in the window, over every page, says too little
ANSWERED_PLACE = 20.0        # a page Google shows a search on at this average place or better answers it
PER_WEEK = 1                 # new pages drafted a week, at most
PREVIEWS = "page-previews"   # DATA_ROOT/site/page-previews/<change id>: the previews the dashboard serves
WORD = re.compile(r"[a-z0-9'’]+")
# the trade's own words: what the business is, never which page
TRADE = frozenset("photo photos photograph photographs photography photographer photographers image images coverage service "
                  "services company companies professional".split())
# the small words, and those a sentence leaves out (seo/leads.py SYSTEM: near me, best, hire)
SMALL = frozenset("a an the and or of at in on for with by from to into near me best hire during before after while".split())
# the places served (site/build.AREA_SERVED and AREA_LINE: DC, Maryland, Virginia, nationwide) and the towns around DC the
# searchers' vocabulary knows (photo_text.SEARCH_VOCAB): a search names one to say where, never what page
PLACES = frozenset("washington dc maryland virginia arlington alexandria baltimore bethesda nationwide local".split())
# the words of a search for a building: venue pages need the venue's name, which is Chris's decision (left for him)
VENUE = frozenset("venue building architecture architectural interior exterior hotel center centre ballroom lobby atrium office "
                  "tower facade entrance".split())
# one thing under two words (Chris, 2026-10-12: "Portraits and headshots are the same"; "Exhibition Halls, vendors and
# booths are all the same thing")
SAME = {"headshot": "portrait", "vendor": "exhibition", "booth": "exhibition"}

SYSTEM = """You write one new page for eventcaliber.com, for a search people make often in Google that no page of the site answers yet.
Event Caliber is Chris and Nic Kennedy, two brothers who photograph conventions, conferences, galas and award dinners. They are based in Washington, DC and travel nationwide.
The page stands under Coverage, beside the site's pages for each room of an event (the_business.coverage), and it is about what the searches ask for (what_they_ask_for). Write:
heading: the page's headline and its row in the coverage list, a few plain words, like "Main stage and keynotes" or "Portraits".
name: what the page is about, written the way the site's page titles are, like "Main stage and keynote photography". The site writes the page title as the name, then ", Washington, DC", then " | Event Caliber". It must carry every word of what_they_ask_for, singular or plural.
description: the line Google shows under the title, one or two sentences.
lead: the plain sentence under the headline.
paragraphs: one or two short paragraphs on how the two of them photograph it, from what the_business says.
shots: one to three kinds of photo the page shows, from photo_kinds, the ones that fit it best.
Rules:
1. Plain, short words in sentence case. No hype, no exclamation marks, no superlatives such as best, top or number one, nothing guaranteed or award winning.
2. Never a dash of any kind. Use commas and periods.
3. Never a price, a rate or a discount.
4. Never name an event, a conference, a company, a venue or a person, even when a search does; the name Event Caliber may stand. Say what kind of event it is.
5. Never say what a service includes or comes with, what anyone leaves with, how fast anything arrives, packages or turnaround. Never claim to be any event's official photographer or anyone's partner, and never name or claim a client.
6. Promise nothing the_business does not say, and say only what it says: no number, no name and no fact it does not give.
7. Write the searches' words the way a person writes them: "conference photography in Washington, DC", not "conference photographer dc".
8. Keep to the lengths given.
Return JSON."""
SCHEMA = {"type": "object",
          "properties": {"heading": {"type": "string"}, "name": {"type": "string"}, "description": {"type": "string"},
                         "lead": {"type": "string"}, "paragraphs": {"type": "array", "items": {"type": "string"}},
                         "shots": {"type": "array", "items": {"type": "string", "enum": list(build.SHOT_KINDS)}}},
          "required": ["heading", "name", "description", "lead", "paragraphs", "shots"], "additionalProperties": False}


class PreviewError(RuntimeError):
    """The preview could not be built; the message says why, for Chris."""


# ------------------------------------------------------------------ what a search asks for

def norm(word: str) -> str:
    """A word as the finder compares it: lower case, singular ("galas" is "gala", "companies" "company", "business" stays),
    one word for one thing (SAME)."""
    w = word.lower()
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        w = w[:-1]
    return SAME.get(w, w)


def norm_words(text: str) -> set[str]:
    return {norm(w) for w in WORD.findall((text or "").lower())}


def asked(search: str) -> list[str]:
    """What a search asks for: its words as typed, less the trade's own, the places and the small words."""
    return [w for w in WORD.findall(search.lower()) if w not in TRADE and w not in SMALL and w not in PLACES]


def offered() -> set[str]:
    """The words of what the business offers: offer.json's kinds of event and its coverage labels and titles, and the
    kinds of shot the coverage pages show (site/build.COVERAGE_SHOTS); never the trade's own or a small word."""
    o = offer.load()
    texts = list(o.get("event_kinds") or []) + [c[k] for c in o["coverage"] for k in ("label", "title") if c.get(k)]
    texts += [w for key, shots in build.COVERAGE_SHOTS.items() for w in (key, *shots)]
    words = {norm(w) for t in texts for w in WORD.findall(t.replace("_", " ").lower())}
    return words - {norm(w) for w in TRADE | SMALL}


def taken_down(conn: sqlite3.Connection, path: str) -> bool:
    """A page at this address was taken down (or is being): never proposed again by itself."""
    return db.one(conn, "SELECT 1 FROM seo_changes WHERE kind='takedown' AND page=? AND status IN ('approved', 'live', 'kept')",
                  (path,)) is not None


def demand(conn: sqlite3.Connection, win: tuple[str, str], cfg=None) -> tuple[list[dict], dict[str, int]]:
    """The searches no page answers in a kept window, one entry per page they would want (its "path", its "searches" with
    their numbers summed over every page, its most shown "query", its total "impressions" and "clicks"), the most shown
    first; and how many searches shown MIN_SHOWINGS times or more were left out, by why."""
    cfg = cfg or config.get_config()
    brand, known = cfg.brand_name, ai_names.public_names(conn)
    public = build.public_pages(conn)
    paths = {search_console.page_url(p, cfg): p for p in public}
    words = build.site_words(conn)
    titles = [norm_words(words[build.rel_of(p)]["title"]) for p in public]
    wanted = offered()
    left_out = {"words": 0, "whole": 0, "venue": 0, "unoffered": 0, "answered": 0, "taken down": 0}
    per_search: dict[str, list[dict]] = {}
    for r in search_console.every_search(conn, win):
        per_search.setdefault(r["query"], []).append(r)
    groups: dict[frozenset, dict] = {}
    for query, rows in per_search.items():
        shown = sum(r["impressions"] for r in rows)
        if shown < MIN_SHOWINGS:
            continue
        if not photo_text.searchable(query, brand, known):
            left_out["words"] += 1
            continue
        want = frozenset(norm(w) for w in asked(query))
        if not want:
            left_out["whole"] += 1
        elif want & VENUE:
            left_out["venue"] += 1
        elif not want <= wanted:
            left_out["unoffered"] += 1
        else:
            top = max(rows, key=lambda r: (r["impressions"], -r["position"]))
            page = paths.get(top["page"], top["page"])
            group = groups.setdefault(want, {"searches": [], "answered": False})
            group["searches"].append({"query": query, "clicks": sum(r["clicks"] for r in rows), "impressions": shown,
                                      "position": top["position"], "page": page})
            group["answered"] |= page in public and page != "/" and top["position"] <= ANSWERED_PLACE
    found = []
    for want, group in groups.items():
        searches = sorted(group["searches"], key=lambda s: (-s["impressions"], s["query"]))
        slug = "-".join(asked(searches[0]["query"]))
        path = f"/coverage/{slug}/"
        if (group["answered"] or any(want <= t for t in titles) or path in public
                or slug.replace("-", "_") in offer.coverage_keys()):
            left_out["answered"] += len(searches)
        elif taken_down(conn, path):
            left_out["taken down"] += len(searches)
        else:
            found.append({"path": path, "query": searches[0]["query"], "searches": searches, "start": win[0], "end": win[1],
                          "impressions": sum(s["impressions"] for s in searches), "clicks": sum(s["clicks"] for s in searches)})
    return sorted(found, key=lambda r: (-r["impressions"], r["query"])), left_out


def reason(r: dict) -> str:
    head, more = r["searches"][0], len(r["searches"]) - 1
    like = f" and {more} search{'es' if more > 1 else ''} like it" if more else ""
    where = changes.named(head["page"]) if head["page"] == "/" else f"{changes.named(head['page'])} at an average place of {head['position']:g}"
    return (f'Searched "{r["query"]}"{like} {r["impressions"]} times in Google from {changes.span(r["start"], r["end"])}, and no '
            f"page of the site answers it: Google showed {where}. A page of its own for it, under Coverage.")


# ------------------------------------------------------------------ drafting and the gate

def site_said() -> str:
    """Everything the site says that a new page may draw on: the offer (its kinds of event and every coverage page's
    words), the site's own lines (build.copy_text), where they are based and serve, and the brand."""
    o, t = offer.load(), build.copy_text()
    lines = [v if isinstance(v, str) else " ".join(x for pair in v for x in pair) for v in t.values()]
    lines += list(o.get("event_kinds") or []) + [c[k] for c in o["coverage"] for k in ("label", "note", "title", "first", "about") if c.get(k)]
    return " ".join([*lines, build.AREA_LINE, config.get_config().brand_name])


def written(raw: dict) -> dict:
    """Claude's page as the site would write it (changes.tidied); the title is its name and the place, as every coverage
    page's (site/build.page_words)."""
    name = changes.tidied(raw.get("name"))
    paragraphs = raw.get("paragraphs") if isinstance(raw.get("paragraphs"), list) else []
    shots = raw.get("shots") if isinstance(raw.get("shots"), list) else []
    return {"heading": changes.tidied(raw.get("heading")), "name": name, "title": f"{name}, {build.AREA}" if name else "",
            "description": changes.tidied(raw.get("description")), "lead": changes.tidied(raw.get("lead")),
            "paragraphs": [changes.tidied(p) for p in paragraphs], "shots": [str(s) for s in shots]}


def check(conn: sqlite3.Connection, path: str, page: dict, searches: list[str]) -> list[str]:
    """Why a new page may not stand, in plain words; [] when it may: site/build.added_page_problems (the copy rules, the
    names rule, the lengths, the kinds of photo); a name or a number the site does not say; a title that does not carry
    what the searches ask for; a search public words may no longer use (the names gate knows more every week); an
    address the site has, or had and took down."""
    cfg = config.get_config()
    names = ai_names.public_names(conn)
    why = build.added_page_problems(path, page, cfg.brand_name, names)
    said, searched = site_said(), " ".join(searches)
    extra: list[str] = []
    for text in [page.get(f) for f in ("heading", "name", "description", "lead")] + list(page.get("paragraphs") or []):
        if isinstance(text, str):
            extra += [w for w in leads.unsaid(text, said, searched) if w not in extra]
    if extra:
        why.append(f"it says {', '.join(extra)}, which the site does not")
    missing = sorted({norm(w) for w in asked(searches[0])} - norm_words(page.get("title", "")))
    if missing:
        why.append(f"its title does not carry {', '.join(missing)}, which the search asks for")
    if any(not photo_text.searchable(q, cfg.brand_name, names) for q in searches):
        why.append("a search it was made for is not one public words may use")
    if build.rel_of(path) in build.site_words(conn):
        why.append(f"the site already has a page at {path}")
    elif taken_down(conn, path):
        why.append(f"a page at {path} was taken down")
    return why


def facts(r: dict, cfg) -> dict:
    o = offer.load()
    rel = build.rel_of(r["path"])
    return {"address": r["path"], "what_they_ask_for": " ".join(asked(r["query"])),
            "searches": [{"search": s["query"], "shown": s["impressions"], "clicked": s["clicks"], "average_place": s["position"],
                          "page_google_showed": changes.named(s["page"])} for s in r["searches"]],
            "the_business": {"event_kinds": o.get("event_kinds") or [],
                             "coverage": [{"label": c["label"], "first": c["first"]} for c in offer.listed_coverage()]},
            "area": build.AREA_LINE, "photo_kinds": {k: photo_text.SHOT_WORDS[k] for k in build.SHOT_KINDS},
            "heading_max_characters": build.HEADING_MAX,
            "name_max_characters": build.TITLE_MAX - len(build.full_title(rel, f", {build.AREA}", cfg.brand_name)),
            "description_max_characters": build.DESCRIPTION_MAX, "lead_max_characters": build.LEAD_MAX,
            "paragraph_max_characters": build.PARAGRAPH_MAX, "paragraphs": f"one to {build.PARAGRAPHS_MAX}",
            "shots": f"one to {build.SHOTS_MAX}"}


def draft(conn: sqlite3.Connection, client, r: dict, *, agent: str = "seo", cfg=None) -> str:
    """One page the searches want: Claude's page, checked, proposed, its preview built and pinged; or dropped with the
    reason. What happened, in words."""
    cfg = cfg or config.get_config()
    path = r["path"]
    raw = changes.ask(conn, client, model=MODEL, system=SYSTEM, schema=SCHEMA, facts=facts(r, cfg), detail=f"seo page {path}",
                      agent=agent)
    if raw is None:
        return f"{path}: dropped, Claude refused or gave nothing readable"
    page = written(raw)
    searches = [s["query"] for s in r["searches"]]
    why = check(conn, path, page, searches)
    if why:
        return f"{path}: dropped, {'; '.join(why)}"
    cid = changes.propose(conn, kind=KIND, page=path, before={}, after=page, search=r["query"], reason=reason(r),
                          queries=[{k: s[k] for k in ("query", "clicks", "impressions", "position")} for s in r["searches"]])
    try:
        preview(conn, cid)
        seen = ""
    except PreviewError as e:
        seen = f"; no preview yet ({e}), it is built when the page is opened"
    pushed = changes.ping(conn, cid, dry_run=False, agent=agent)
    return f'{path}: proposed (change {cid}) for "{r["query"]}", ping {pushed}{seen}'


LEFT_OUT = {"words": "a word in the search is not a trade or place word",
            "whole": "asking for the business as a whole, the home page's",
            "venue": "for a venue, waiting for you: a venue page needs the venue's name",
            "unoffered": "for something offer.json does not name, or a place not served",
            "answered": "answered by a page of the site",
            "taken down": "for a page taken down before"}


def propose_week(conn: sqlite3.Connection, cfg=None, *, client=None, agent: str = "seo") -> str:
    """The weekly finding, live only, after parts one and two: the searches no page answers in the newest kept window, at
    most PER_WEEK pages drafted. What happened, with what was left out and why."""
    cfg = cfg or config.get_config()
    prune_previews(conn)
    win = search_console.latest_window(conn)
    if win is None:
        return "no Search Console numbers kept yet"
    found, left_out = demand(conn, win, cfg)
    notes = [f"{n} more left out, {LEFT_OUT[why]}" for why, n in left_out.items() if n]
    if not found:
        return "; ".join([f"no search without a page of its own was shown {MIN_SHOWINGS} times or more from {changes.span(*win)}",
                          *notes])
    return "; ".join(changes.draft_week(conn, found, lambda c, r: draft(conn, c, r, agent=agent, cfg=cfg), client=client,
                                        agent=agent, error_kind="seo_page", per_week=PER_WEEK) + notes)


# ------------------------------------------------------------------ the preview on the dashboard

def preview_dir(cid: int) -> Path:
    return config.get_config().data_root / "site" / PREVIEWS / str(int(cid))


def preview(conn: sqlite3.Connection, cid: int, fetch: Optional[Callable[[dict], Image.Image]] = None) -> Path:
    """The page change `cid` proposes, as the site would show it (site/build.page_preview), under the data root for the
    dashboard: built the first time it is asked for, with real approved photos of its kinds, picked as a coverage page's
    are (site/build.page_pool, pick_room) and fetched as the build fetches them (library_fetch: Drive, read only). The
    page file. Raises PreviewError, in words for Chris, when the photos cannot be had; nothing is left half written."""
    row = changes.get(conn, cid)
    page_file = preview_dir(cid) / "index.html"
    if page_file.is_file():
        return page_file
    if fetch is None:
        fetch, why = build.library_fetch(conn, "seo")
        if fetch is None:
            raise PreviewError(f"the photos could not be fetched: {why}")
    page = json.loads(row["after"])
    picked = build.pick_room(build.page_pool(conn), tuple(page["shots"]), set())
    try:
        photos = [(fetch(r), *build.words_for(conn, r)) for r in picked]
    except Exception as e:  # noqa: BLE001  Drive or the network: said, and tried again when the page is opened
        raise PreviewError(f"a photo could not be fetched ({type(e).__name__})") from e
    return build.page_preview(conn, row["page"], page, photos, preview_dir(cid), f"{changes.preview_path(cid)}/assets/")


def preview_asset(cid: int, name: str) -> Optional[Path]:
    """A file of a built preview (its stylesheet, fonts, mark, photos), or None for anything outside it."""
    base = (preview_dir(cid) / "assets").resolve()
    path = (base / name).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


def prune_previews(conn: sqlite3.Connection) -> None:
    """The previews of changes no longer waiting (on the site, skipped, gone) are removed; one opened again is rebuilt."""
    root = config.get_config().data_root / "site" / PREVIEWS
    if not root.is_dir():
        return
    for d in root.iterdir():
        row = changes.get(conn, int(d.name)) if d.name.isdigit() else None
        if row is None or row["status"] not in ("proposed", "approved"):
            shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------ the kinds, for seo/changes.py

def problems(conn: sqlite3.Connection, row) -> list[str]:
    """Why this page may not go on the site now: check, against today's rules, names and pages."""
    return check(conn, row["page"], json.loads(row["after"]), [q["query"] for q in json.loads(row["queries"])])


def shown(row) -> list[tuple[str, str, str]]:
    """(what, before, after) as Chris reads them: a new page has no before; its title as a search result shows it, its
    description, its lead sentence and the kinds of photo it shows (the paragraphs are on the preview)."""
    page = json.loads(row["after"])
    return [("Title", "", build.full_title(build.rel_of(row["page"]), page["title"], config.get_config().brand_name)),
            ("Description", "", page["description"]), ("Lead sentence", "", page["lead"]),
            ("Photos", "", ", ".join(photo_text.SHOT_WORDS.get(k, k) for k in page["shots"]))]


class TakeDown:
    """Taking down a page a search change added, when its measure says it did not earn its place (changes.NEW_PAGE):
    proposed to Chris like any change, Skip or Approve (2026-11-01: removing a page is a visible change). On Approve the
    build leaves the page out and lists its address for the Worker, which answers 301 to /coverage/ (worker/index.js).
    Nothing to measure: it is done when the deploy carries it."""
    MEASURE = None
    PREVIEW = False
    STATUS_WORDS = {**changes.STATUS_WORDS, "approved": "approved, coming off the site", "kept": "taken down"}
    SAID = {"ping": "a page to take down",
            "close": "Approve takes it off the site, and its address then sends visitors to the coverage page. Skip keeps it.",
            "approve": ("Approved. {Page} comes off the site when it next publishes, in about ten minutes, and its address then "
                        "sends visitors to the coverage page."),
            "skip": "Skipped. {Page} stays on the site.",
            "proposed": "taking down {page} proposed; it waits for your Approve.",
            "approved": "you approved taking down {page}.",
            "live": "{page} is off the site.",
            "done": "{Page} is off the site; its address sends visitors to the coverage page.",
            "skipped": "you kept {page}: its taking down skipped."}

    def problems(self, conn: sqlite3.Connection, row) -> list[str]:
        if row["page"] not in [p["path"] for p in build.added_pages(conn)]:
            return [f"the site carries no page a search change added at {row['page']}"]
        return []

    def shown(self, row) -> list[tuple[str, str, str]]:
        title = json.loads(row["before"]).get("title", "")
        return [("Page", "", f"{title}, at {search_console.page_url(row['page'])}")]


TAKE_DOWN = TakeDown()
