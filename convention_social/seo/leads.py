"""Part two of the SEO loop (Chris, 2026-11-01: "shouldn't we have it do it all. Why wouldn't we?"): near misses. A page
that sits just off Google's first page for a search gets its lead sentence reworded to work that search in, proposed to
him through seo/changes.py like every change: before and after, Approve and Skip, one tap from his phone.

Which, from the newest Search Console window kept (seo/search_console.py): a search a public page of the site was shown
for at least MIN_SHOWINGS times at an average place from PLACE_FROM to PLACE_TO, on a page that opens with a lead
sentence (the <p class="first">: the home page, the coverage index, each coverage page, Contact). Only a search public
words may use (photo_text.searchable, part four's rule: every word a trade or place word, never the brand's own name, no
name the names gate knows): a search can carry a person's or an event's name the gate has never seen, so anything else is
left out, whatever it is. One search a page, its most shown; the most shown first, at most PER_WEEK drafted a week. A
page with an open change of any kind, or resting, is left alone (changes.draft_week).

For each, Claude (MODEL, under the monthly cap through ai/spend, changes.ask) rewords the page's lead from its own words
so it works the search's words in, naturally and truthfully, in the brand's plain voice. Every draft is checked before
it is proposed (check): the copy rules (no price, no dash, no claim, no official role or client), the names rule and the
length (site/build.lead_problems); it names nothing the page does not say (unsaid: every capitalised word inside a
sentence and every number is one the page, the search or the site's area line already has); and it works in more of the
search's words than the lead had, losing none. A draft that fails is dropped with the reason in the run's summary, never
proposed. The weekly run calls this only live: a dry run reads nothing, pays nothing, proposes nothing.

A lead change is judged on the search it was made for (changes.PLACE): 31 days after it went live, shown for that search
at least 30 times since, it is kept at the same average place or better and put back two places lower or more; anything
between, or fewer showings, is measured again next week.
"""
from __future__ import annotations

import json
import re
import sqlite3

from .. import offer
from ..ai import names as ai_names
from ..core import config
from ..site import build
from . import changes, photo_text, search_console, titles

KIND = "lead"
MEASURE = changes.PLACE
MODEL = "claude-opus-5"      # part one's model (seo/titles.py)
PLACE_FROM, PLACE_TO = 8, 20  # an average place at the foot of Google's first page or just past it
MIN_SHOWINGS = 30            # a search shown fewer times on a page in the window says too little
PER_WEEK = 2                 # leads drafted a week, at most
WORD = re.compile(r"[a-z0-9'’]+")
TOKEN = re.compile(r"[A-Za-z][A-Za-z'’]*|\d+")

SYSTEM = """You reword the lead sentence of one page of eventcaliber.com: the plain sentence under the page's headline.
Event Caliber is Chris and Nic Kennedy, two brothers who photograph conventions, conferences, galas and award dinners. They are based in Washington, DC and travel nationwide.
People searching Google for the search given find this page just off the first page of results. Reword the lead so it works the words of that search in, naturally, the way a person writes them, and still says truthfully what the page is about.
Rules:
1. Keep the lead's meaning and as many of its own words as you can; change only what working the search in needs. One or two plain, short sentences in sentence case.
2. Write the search's words the way a person writes them, not the way they were typed: "conference photographers in Washington, DC", not "conference photographer dc". Leave out words such as near me, best or hire that do not belong in a sentence.
3. No hype, no exclamation marks, no superlatives such as best, top or number one, nothing guaranteed or award winning.
4. Never a dash of any kind. Use commas and periods.
5. Never a price, a rate or a discount.
6. Never name an event, a conference, a company, a venue or a person, even when the search does; the name Event Caliber may stay where the lead has it. Say what kind of event it is.
7. Never say what a service includes or comes with, what anyone leaves with, how fast anything arrives, packages or turnaround. Never claim to be any event's official photographer or anyone's partner, and never name or claim a client.
8. Say only what the page itself says. Invent nothing: no number, no name and no fact the page does not give.
9. At most lead_max_characters long.
Return JSON."""
SCHEMA = {"type": "object", "properties": {"lead": {"type": "string"}}, "required": ["lead"], "additionalProperties": False}


def near_misses(conn: sqlite3.Connection, win: tuple[str, str], cfg=None) -> tuple[list[dict], dict[str, int]]:
    """The near misses in a kept window, one a page (its most shown search), the most shown first; and how many more in
    that range were left out, by why: "words" (a search public words may not use), "no lead" (a page with no lead)."""
    cfg = cfg or config.get_config()
    paths = {search_console.page_url(p, cfg): p for p in offer.public_pages()}
    words = build.site_words(conn)
    known = ai_names.public_names(conn)
    found: dict[str, dict] = {}
    left_out = {"words": 0, "no lead": 0}
    for r in search_console.every_search(conn, win):
        path = paths.get(r["page"])
        if path is None or r["impressions"] < MIN_SHOWINGS or not PLACE_FROM <= r["position"] <= PLACE_TO:
            continue
        if "lead" not in words[build.rel_of(path)]:
            left_out["no lead"] += 1
        elif not photo_text.searchable(r["query"], cfg.brand_name, known):
            left_out["words"] += 1
        elif path not in found:
            found[path] = {**r, "path": path}
    return list(found.values()), left_out


def reason(r: dict) -> str:
    return (f'Shown {r["impressions"]} times in Google search for "{r["query"]}" from {changes.span(r["start"], r["end"])}, at an '
            f"average place of {r['position']:g}: at the foot of the first page or just past it, where few people look. Its lead "
            "sentence is reworded to work that search in.")


def worked_in(text: str, search: str) -> set[str]:
    """The search's words the text says, singular or plural alike ("photographer" is in "photographers")."""
    def stem(w: str) -> str:
        return w[:-1] if len(w) > 3 and w.endswith("s") else w
    said = {stem(w) for w in WORD.findall(text.lower())}
    return {w for w in WORD.findall(search.lower()) if stem(w) in said}


def unsaid(lead: str, said: str, search: str) -> list[str]:
    """The names and numbers in a lead that the page's own words (`said`) and the search do not have: every capitalised
    word inside a sentence (a name, a place, a client) and every number. A sentence's first word is capitalised anyway
    and is looked at only when it is a number."""
    known, searched = set(TOKEN.findall(said)), set(WORD.findall(search.lower()))
    out: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", lead.strip()):
        for i, w in enumerate(TOKEN.findall(sentence)):
            if (w[0].isdigit() or (i and w[0].isupper())) and w not in known and w.lower() not in searched and w not in out:
                out.append(w)
    return out


def page_said(path: str, words: dict[str, str]) -> str:
    """Everything the page says that a lead may draw on: its title, description and lead, a coverage page's text, and
    the line every page carries (where they are based and serve) and the brand."""
    return " ".join([*words.values(), titles.page_text(path), build.AREA_LINE, config.get_config().brand_name])


def check(conn: sqlite3.Connection, path: str, lead_now: str, lead: str, search: str) -> list[str]:
    """Why a new lead may not stand on a page, in plain words; [] when it may: site/build.lead_problems (the copy rules,
    the names rule, the length); a name or a number the page does not say; a search public words may not use (the names
    gate knows more every week); and it must work in more of the search's words than the lead has now, losing none."""
    names = ai_names.public_names(conn)
    why = build.lead_problems(lead, names)
    extra = unsaid(lead, page_said(path, build.site_words(conn).get(build.rel_of(path), {})), search)
    if extra:
        why.append(f"it says {', '.join(extra)}, which the page does not")
    if not photo_text.searchable(search, config.get_config().brand_name, names):
        why.append("the search it was made for is not one public words may use")
    had, has = worked_in(lead_now, search), worked_in(lead, search)
    if had - has:
        why.append(f"it drops {', '.join(sorted(had - has))}, which the search has and the lead had")
    elif not has - had:
        why.append(f'it works in none of the words of "{search}" the lead lacks')
    return why


def draft(conn: sqlite3.Connection, client, r: dict, win: tuple[str, str], *, agent: str = "seo", cfg=None) -> str:
    """One near miss: Claude's lead, checked, proposed and pinged; or dropped with the reason. What happened, in words."""
    path, search = r["path"], r["query"]
    now = build.site_words(conn)[build.rel_of(path)]
    facts = {"page": path, "lead_now": now["lead"], "page_title": now["title"], "page_description": now["description"],
             "page_text": titles.page_text(path), "search": search,
             "numbers": {"shown": r["impressions"], "clicked": r["clicks"], "average_place": r["position"]},
             "lead_max_characters": build.LEAD_MAX}
    raw = changes.ask(conn, client, model=MODEL, system=SYSTEM, schema=SCHEMA, facts=facts, detail=f"seo lead {path}", agent=agent)
    if raw is None:
        return f"{path}: dropped, Claude refused or gave nothing readable"
    lead = changes.tidied(raw.get("lead"))
    why = ["Claude kept the lead the page has"] if lead == now["lead"] else check(conn, path, now["lead"], lead, search)
    if why:
        return f"{path}: dropped, {'; '.join(why)}"
    cid = changes.propose(conn, kind=KIND, page=path, before={"lead": now["lead"]}, after={"lead": lead}, search=search,
                          queries=[{"query": search, "clicks": r["clicks"], "impressions": r["impressions"], "position": r["position"]}],
                          reason=reason(r))
    pushed = changes.ping(conn, cid, dry_run=False, agent=agent)
    return f'{path}: proposed (change {cid}) for "{search}", ping {pushed}'


def propose_week(conn: sqlite3.Connection, cfg=None, *, client=None, agent: str = "seo") -> str:
    """The weekly finding, live only: the near misses in the newest kept window, at most PER_WEEK drafted. What happened."""
    cfg = cfg or config.get_config()
    win = search_console.latest_window(conn)
    if win is None:
        return "no Search Console numbers kept yet"
    found, left_out = near_misses(conn, win, cfg)
    notes = ([f"{left_out['words']} more left out, a word in the search is not a trade or place word"] if left_out["words"] else []) \
        + ([f"{left_out['no lead']} more on pages with no lead sentence"] if left_out["no lead"] else [])
    if not found:
        return "; ".join([f"no page sat just off the first page for a search from {changes.span(*win)}", *notes])
    return "; ".join(changes.draft_week(conn, found, lambda c, r: draft(conn, c, r, win, agent=agent, cfg=cfg), client=client,
                                        agent=agent, error_kind="seo_lead", per_week=PER_WEEK) + notes)


# ------------------------------------------------------------------ the kind, for seo/changes.py

def problems(conn: sqlite3.Connection, row) -> list[str]:
    """Why this change may not go on the site now: its lead against today's rules (check), and the page still opening
    with the lead it replaces."""
    before, after = json.loads(row["before"]), json.loads(row["after"])
    now = build.site_words(conn).get(build.rel_of(row["page"]))
    if now is None:
        return [f"the site no longer has the page {row['page']}"]
    why = check(conn, row["page"], before["lead"], after["lead"], row["search"])
    if now.get("lead") != before["lead"]:
        why.insert(0, "the page's lead changed since this was drafted")
    return why


def shown(row) -> list[tuple[str, str, str]]:
    """(what, before, after) as Chris reads them: the page's lead sentence."""
    before, after = json.loads(row["before"]), json.loads(row["after"])
    return [("Lead sentence", before["lead"], after["lead"])]
