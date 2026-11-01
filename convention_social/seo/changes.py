"""The changes the SEO agent makes to eventcaliber.com: each one approved by Chris, measured, then kept or put back.

Chris, 2026-11-01, on the Search Console numbers: "shouldn't we have it do it all. Why wouldn't we?" For every change he
chose "One tap from my phone": drafted and pinged with before and after and an Approve button, like posts; on Approve it
goes live, is measured four weeks, and is put back by itself if the numbers drop.

This module does not care what a change is. A change (table seo_changes) has a kind, the page it is on (the site path),
the words before and after, the searches that motivated it (and the one it was made for, if it was made for one) and
the reason in plain words. Part one's kind is "title", a
page's title and description (seo/titles.py); part two's is "lead", a page's lead sentence reworded for one search it
sits just off Google's first page for (seo/leads.py). Its life:

  proposed   drafted, checked and pinged: Approve and Skip on his phone (core/approve_token, signed and single use, under
             its own scope) and on the Search changes page. Nothing on the site changes.
  approved   his Approve; the site is stamped to republish (site/deploy.photos_pending) and the build lays the new words
             over the page's own (site/build.with_seo_changes)
  live       the deploy that carried it succeeded (went_live); the numbers it is judged on, from the last read before, are
             its baseline
  kept       31 days on (28 days of numbers and Search Console's 3-day lag), its kind's measure held: a title's page was
             shown at least 100 times since and its click rate did not fall by a fifth or more (CLICK_RATE); a lead's page
             was shown at least 30 times for its search since, at the same place or better (PLACE)
  reverted   it did not (a fifth fewer clicks; two places lower or more for the search): the page goes back to the words
             it had, and the site republishes
  skipped    his Skip, before it went live

Part three's kind is "page" (seo/pages.py): a page of its own under /coverage/ for a search people make often that no
page answers, shown to him as a rendered preview first since it carries photos. A new page has no before: it is judged
on its own (NEW_PAGE), and when it did not earn its place it is never taken off by itself. Its measure proposes taking it
down instead, a change of kind "takedown" (seo/pages.py TAKE_DOWN) with the same ping, Approve and Skip; nothing to
measure there, it is done when the deploy carries it.

One open change (proposed, approved or live) per page, which the database holds too. A page rests eight weeks after its
last change went live, or after he skipped one, whatever the kind. Each kind is a module (or an object) in _kind() with
problems(conn, row), shown(row), MEASURE (what it is judged on, None for nothing), SAID (how the ping, the answers and
the brief say it), STATUS_WORDS and PREVIEW (a rendered preview on the dashboard), and its own finder in the weekly run,
drafting through ask and draft_week here.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from .. import offer
from ..ai import spend
from ..ai.claude import FALLBACK_BETA, tidy
from ..core import approve_token, config, db, notify, runner, secrets, settings
from ..site import deploy
from . import search_console

KINDS = ("title", "lead", "page", "takedown")
OPEN = ("proposed", "approved", "live")
ON_SITE = ("approved", "live", "kept")
REST = timedelta(weeks=8)
MEASURE_AFTER = timedelta(days=31)        # 28 days of numbers and Search Console's 3-day lag
BUILT_KEY = "site.seo_change_ids"         # JSON list: the changes the last live build laid on the site, for went_live
PAGE = "/seo/changes"                     # the dashboard page
TOKENS = approve_token.Scope("seo_change", "the Search changes page",
                             "The change moved on since that ping (approved, skipped or measured).")
STATUS_WORDS = {"proposed": "waiting for your Approve", "approved": "approved, going on the site", "live": "live, being measured",
                "kept": "kept", "reverted": "put back", "skipped": "skipped"}
# How a change to a page's words is said (parts one and two; a kind with other words has its own SAID): the ping's title
# after the brand and its last line, the answer to his Approve and Skip, and the morning brief's lines after "Search: ".
# {page} is the page in his words (named), {Page} the same to start a sentence, {reason} why, {promise} its measure's.
SAID = {"ping": "new search words to approve",
        "close": "Approve puts it on the site. It is {promise}.",
        "approve": "Approved. The new words go on {page} when the site next publishes, in about ten minutes. The change is {promise}.",
        "skip": "Skipped. {Page} keeps its words, and the agent leaves it alone for eight weeks.",
        "proposed": "new words proposed for {page}. {reason}",
        "approved": "you approved the new words for {page}.",
        "live": "the new words for {page} are on the site, measured for four weeks from now.",
        "skipped": "you skipped the new words for {page}."}


class Refused(ValueError):
    """A change that may not be proposed now; the message says why."""


def _kind(kind: str):
    """What knows a kind of change: problems(conn, row), the reasons it may not go on the site now; shown(row), its before
    and after as Chris reads them; MEASURE, what it is judged on once live (None: nothing, it is done as it goes live);
    SAID, STATUS_WORDS and PREVIEW (module docstring)."""
    if kind == "title":
        from . import titles
        return titles
    if kind == "lead":
        from . import leads
        return leads
    if kind == "page":
        from . import pages
        return pages
    if kind == "takedown":
        from . import pages
        return pages.TAKE_DOWN
    raise ValueError(f"no kind of search change is called {kind!r}")


def said_of(row, what: str) -> str:
    """One of the kind's SAID lines for this change."""
    judge = measure_of(row)
    page = named(row["page"])
    return _kind(row["kind"]).SAID[what].format(page=page, Page=page[:1].upper() + page[1:], reason=row["reason"],
                                                 promise=judge.PROMISE if judge else "")


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _day(stamp: str) -> date:
    return datetime.fromisoformat(stamp).date()


def _loads(text: Optional[str], default):
    try:
        value = json.loads(text) if text else default
    except ValueError:
        return default
    return value if value is not None else default


def span(start: str, end: str) -> str:
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    return f"{s:%b} {s.day} to {e:%b} {e.day}"


def named(page: str) -> str:
    """A page in Chris's words: its path, or "the home page"."""
    return "the home page" if page == "/" else page


def get(conn: sqlite3.Connection, cid: int):
    return db.one(conn, "SELECT * FROM seo_changes WHERE id=?", (cid,))


def on_site(conn: sqlite3.Connection) -> list:
    """The changes the site carries (approved, live or kept), every kind, oldest first: the order they are laid in."""
    return db.rows(conn, f"SELECT * FROM seo_changes WHERE status IN ({','.join('?' * len(ON_SITE))}) ORDER BY id", ON_SITE)


def resting(conn: sqlite3.Connection, page: str, now: Optional[datetime] = None) -> str:
    """Why no change may be proposed for this page now; "" when one may."""
    row = db.one(conn, f"SELECT id, status FROM seo_changes WHERE page=? AND status IN ({','.join('?' * len(OPEN))})", (page, *OPEN))
    if row:
        return f"change {row['id']} for it is {STATUS_WORDS[row['status']]}"
    since = _iso(_now(now) - REST)
    row = db.one(conn, "SELECT id, status FROM seo_changes WHERE page=? AND (live_at >= ? OR (status='skipped' AND verdict_at >= ?)) "
                       "ORDER BY id DESC LIMIT 1", (page, since, since))
    if row:
        return f"its last change ({row['id']}) was {'skipped' if row['status'] == 'skipped' else 'put live'} less than eight weeks ago"
    return ""


def propose(conn: sqlite3.Connection, *, kind: str, page: str, before: dict, after: dict, queries: list, reason: str,
            search: str = "", now: Optional[datetime] = None) -> int:
    """A new change waiting for Chris; `search` is the one search it was made for, if it was (a lead). Raises Refused when
    the page has one open or is resting."""
    if kind not in KINDS:
        raise ValueError(f"no kind of search change is called {kind!r}")
    why = resting(conn, page, now)
    if why:
        raise Refused(f"{page}: {why}")
    stamp = _iso(_now(now))
    return db.insert(conn, "seo_changes", kind=kind, page=page, fields=json.dumps([f for f in after if after[f] != before.get(f)]),
                     before=json.dumps(before), after=json.dumps(after), queries=json.dumps(queries), reason=reason,
                     search=search, status="proposed", proposed_at=stamp, updated_at=stamp)


def approve(conn: sqlite3.Connection, cid: int, now: Optional[datetime] = None) -> tuple[bool, str]:
    """His Approve: (True, what happens next) or (False, why not). The words are checked again now (the rules and the
    page's words may have moved since the draft); the site is stamped to republish."""
    row = get(conn, cid)
    if row is None:
        return False, "There is no such change."
    if row["status"] != "proposed":
        return False, f"Change {cid} is {STATUS_WORDS[row['status']]}; there is nothing to approve."
    why = _kind(row["kind"]).problems(conn, row)
    if why:
        return False, f"Not approved: on the site today it would not pass, because {'; '.join(why)}."
    stamp = _iso(_now(now))
    if not conn.execute("UPDATE seo_changes SET status='approved', approved_at=?, updated_at=? WHERE id=? AND status='proposed'",
                        (stamp, stamp, cid)).rowcount:
        return False, f"Change {cid} was decided a moment ago; there is nothing more to do."
    approve_token.spend(conn, cid, TOKENS)
    settings.set(conn, deploy.SEO_CHANGED_KEY, stamp)
    return True, said_of(row, "approve")


def skip(conn: sqlite3.Connection, cid: int, now: Optional[datetime] = None) -> tuple[bool, str]:
    """His Skip, before the change went live: the page keeps its words and rests eight weeks."""
    row = get(conn, cid)
    if row is None:
        return False, "There is no such change."
    if row["status"] not in ("proposed", "approved"):
        return False, f"Change {cid} is {STATUS_WORDS[row['status']]}; it can no longer be skipped."
    stamp = _iso(_now(now))
    if not conn.execute("UPDATE seo_changes SET status='skipped', verdict_at=?, updated_at=? WHERE id=? AND status=?",
                        (stamp, stamp, cid, row["status"])).rowcount:
        return False, f"Change {cid} was decided a moment ago; there is nothing more to do."
    approve_token.spend(conn, cid, TOKENS)
    if row["status"] == "approved":         # a build may already carry it: the site publishes again without it
        settings.set(conn, deploy.SEO_CHANGED_KEY, stamp)
    return True, said_of(row, "skip")


def decide_by_token(conn: sqlite3.Connection, cid: int, token: str, how: str) -> tuple[bool, str]:
    """Approve or Skip from the ping: the signed single-use token first, then the same decision as the page's buttons."""
    row = get(conn, cid)
    if row is None:
        return False, "There is no such change."
    ok, why = approve_token.check(conn, row, token, scope=TOKENS)
    if not ok:
        return False, why
    return approve(conn, cid) if how == "approve" else skip(conn, cid)


# ------------------------------------------------------------------ live, measured, kept or put back

class Measure:
    """What a kind of change is judged on, once it is live: AFTER it went live it is looked at weekly; numbers() in a kept
    window, verdict() on them against the baseline, words() for Chris; PROMISE, what his Approve says of it."""
    AFTER = MEASURE_AFTER

    def numbers_words(self, n: Optional[dict]) -> str:
        """A window's numbers in words, for the Search changes page."""
        return numbers_words(n)


class ClickRate(Measure):
    """Part one's measure, for a change to how a page shows in a search result (its title and description): the page's
    own click rate over every search. Shown at least MIN_SHOWINGS times since it went live: put back when the rate fell
    by DROP or more (relative), else kept. Fewer showings say nothing yet: measured again next week."""
    MIN_SHOWINGS = 100
    DROP = 0.20
    PROMISE = "measured for four weeks and put back by itself if fewer people click"

    def numbers(self, conn: sqlite3.Connection, win: tuple[str, str], row, cfg=None) -> dict:
        return search_console.page_numbers(conn, win, search_console.page_url(row["page"], cfg))

    def verdict(self, base: dict, since: dict) -> tuple[Optional[str], float]:
        """("kept" | "reverted", the click rate's change relative to before) once the page was shown MIN_SHOWINGS times
        since; (None, 0.0) before that. A page never clicked before cannot have fallen."""
        if since["impressions"] < self.MIN_SHOWINGS:
            return None, 0.0
        if not base.get("ctr"):
            return "kept", 0.0
        change = (since["clicks"] / since["impressions"] - base["ctr"]) / base["ctr"]
        return ("reverted" if change <= -self.DROP else "kept"), round(change, 4)

    def words(self, row, verdict: Optional[str], base: dict, since: dict, change: float) -> str:
        page = named(row["page"])
        then = f"{base['ctr']:.1%} of {base['impressions']} before"
        now = (f"{since['clicks'] / since['impressions']:.1%} of {since['impressions']} showings clicked from "
               f"{span(since['start'], since['end'])}") if since["impressions"] else ""
        if verdict == "kept":
            return f"The new words on {page} stay: {now}, against {then}."
        if verdict == "reverted":
            return (f"The new words on {page} were put back: {now}, against {then}, {-change:.0%} fewer. The page has the "
                    "words it had before again, and the site republishes.")
        return (f"{page.capitalize()} was shown {since['impressions']} times in Google since its new words went live "
                f"({span(since['start'], since['end'])}), fewer than {self.MIN_SHOWINGS}: measured again next week.")


class Place(Measure):
    """Part two's measure, for a change made for one search (a lead sentence, seo/leads.py): the page's average place in
    Google for that search (seo_changes.search). Shown for it at least MIN_SHOWINGS times since it went live: kept at the
    same place or better, put back DROP places lower or more; lower by less, or fewer showings: measured again next
    week."""
    MIN_SHOWINGS = 30
    DROP = 2.0
    PROMISE = f"measured for four weeks and put back by itself if the page drops {DROP:g} places or more in Google for that search"

    def numbers(self, conn: sqlite3.Connection, win: tuple[str, str], row, cfg=None) -> dict:
        return search_console.page_numbers(conn, win, search_console.page_url(row["page"], cfg), row["search"])

    def verdict(self, base: dict, since: dict) -> tuple[Optional[str], float]:
        """("kept" | "reverted" | None, how many places lower the page sits for the search than before; below nought it
        rose). A page not shown for the search before cannot have dropped."""
        if since["impressions"] < self.MIN_SHOWINGS:
            return None, 0.0
        if not base.get("position"):
            return "kept", 0.0
        lower = round(since["position"] - base["position"], 1)
        if lower <= 0:
            return "kept", lower
        return ("reverted" if lower >= self.DROP else None), lower

    def words(self, row, verdict: Optional[str], base: dict, since: dict, change: float) -> str:
        page, search, when = named(row["page"]), row["search"], span(since["start"], since["end"])
        if verdict == "kept":
            then = f"{base['position']:g} before" if base.get("position") else "no place for it before"
            return (f'The new lead on {page} stays: for "{search}" it sat at an average place of {since["position"]:g} in '
                    f"{since['impressions']} showings from {when}, against {then}.")
        if verdict == "reverted":
            return (f'The new lead on {page} was put back: for "{search}" its average place went from {base["position"]:g} to '
                    f"{since['position']:g} in {since['impressions']} showings from {when}, {change:g} places lower. The page "
                    "has the lead it had before again, and the site republishes.")
        if since["impressions"] < self.MIN_SHOWINGS:
            return (f'{page.capitalize()} was shown {since["impressions"]} times for "{search}" since its new lead went live '
                    f"({when}), fewer than {self.MIN_SHOWINGS}: measured again next week.")
        return (f'{page.capitalize()} sat at an average place of {since["position"]:g} for "{search}" since its new lead went '
                f"live ({when}), against {base['position']:g} before: lower, by less than {self.DROP:g} places, so measured "
                "again next week.")


class NewPage(Measure):
    """Part three's measure, for a page a search change added (seo/pages.py). A new page has no before, so it is judged
    on its own: the searches it was made for (seo_changes.queries) and the new page's average place in Google for them.
    AFTER it went live (56 days of numbers and Search Console's 3-day lag), with at least MIN_SHOWINGS showings of those
    searches on any page of the site in the newest window: kept when Google showed the new page for them at PLACE_MAX or
    better; otherwise "down". Fewer showings: measured again next week, and "down" once LONGEST of numbers are in. "down"
    is never done by itself: a page coming off the site is a visible change, so taking it down is proposed to Chris
    (measure, a change of kind "takedown")."""
    AFTER = timedelta(days=59)
    MIN_SHOWINGS = 50
    PLACE_MAX = 20.0
    LONGEST = timedelta(weeks=16)
    PROMISE = ("measured for eight weeks; if Google does not show it for its searches at an average place of 20 or better, "
               "taking it down comes to you to approve")

    def numbers(self, conn: sqlite3.Connection, win: tuple[str, str], row, cfg=None) -> dict:
        """Its searches' numbers on every page of the site; "position" and "page_impressions" are the new page's own for
        them; "days", the days of numbers since it went live."""
        searches = [q["query"] for q in _loads(row["queries"], [])]
        own = search_console.search_numbers(conn, win, searches, search_console.page_url(row["page"], cfg))
        days = (date.fromisoformat(win[1]) - _day(row["live_at"])).days if row["live_at"] else 0
        return {**search_console.search_numbers(conn, win, searches), "position": own["position"],
                "page_impressions": own["impressions"], "days": days}

    def verdict(self, base: dict, since: dict) -> tuple[Optional[str], float]:
        """("kept" | "down" | None, the new page's average place for its searches)."""
        if since["impressions"] < self.MIN_SHOWINGS:
            return ("down" if since["days"] >= self.LONGEST.days else None), 0.0
        if since["page_impressions"] and since["position"] <= self.PLACE_MAX:
            return "kept", since["position"]
        return "down", since["position"]

    def words(self, row, verdict: Optional[str], base: dict, since: dict, change: float) -> str:
        page, when, shown = named(row["page"]), span(since["start"], since["end"]), since["impressions"]
        more = len(_loads(row["queries"], [])) - 1
        searches = f'"{row["search"]}"' + (f" and {more} search{'es' if more > 1 else ''} like it" if more > 0 else "")
        if verdict == "kept":
            return (f"The new page {page} stays: Google showed it for {searches} at an average place of {since['position']:g} "
                    f"in {since['page_impressions']} of their {shown} showings from {when}.")
        if verdict == "down" and shown < self.MIN_SHOWINGS:
            return (f"The new page {page} is not earning its place: {searches} was shown {shown} times from {when}, fewer than "
                    f"{self.MIN_SHOWINGS} sixteen weeks after it went live. Taking it down is proposed to you.")
        if verdict == "down":
            where = f"at an average place of {since['position']:g}" if since["page_impressions"] else "nowhere"
            return (f"The new page {page} did not reach Google's first two pages: for {searches}, shown {shown} times from "
                    f"{when}, Google showed it {where}. Taking it down is proposed to you.")
        return (f"{page.capitalize()}: {searches} was shown {shown} times from {when}, fewer than {self.MIN_SHOWINGS}: "
                "measured again next week.")

    def numbers_words(self, n: Optional[dict]) -> str:
        if not n or not n.get("start"):
            return ""
        return (f"its searches were shown {n['impressions']} times from {span(n['start'], n['end'])}"
                + (f", this page at an average place of {n['position']:g}" if n.get("page_impressions") else ", never on this page"))


CLICK_RATE, PLACE, NEW_PAGE = ClickRate(), Place(), NewPage()


def measure_of(row) -> Optional[Measure]:
    """What a change is judged on: its kind's MEASURE (CLICK_RATE, PLACE or NEW_PAGE); None for a change with nothing to
    measure (a page taken down)."""
    return _kind(row["kind"]).MEASURE


def baseline(conn: sqlite3.Connection, row, live_day: date, cfg=None) -> dict:
    """The numbers a change is judged on, in the newest kept window that ended before it went live (nought when none
    was kept)."""
    win = search_console.latest_window(conn, ending_before=live_day.isoformat())
    if win is None:
        return {"start": None, "end": None, "clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
    return measure_of(row).numbers(conn, win, row, cfg)


def went_live(conn: sqlite3.Connection, now: Optional[datetime] = None, cfg=None) -> list[str]:
    """After a deploy succeeded (site/deploy.run): the approved changes its build laid (BUILT_KEY) are live from now,
    each with its baseline and the day it is measured (its measure's AFTER); one with nothing to measure (a page taken
    down) is done now. The pages they are on."""
    t = _now(now)
    stamp, went = _iso(t), []
    for cid in _loads(settings.get(conn, BUILT_KEY), []):
        row = get(conn, int(cid))
        if row is None or row["status"] != "approved":
            continue
        judge = measure_of(row)
        if judge is None:
            done = conn.execute("UPDATE seo_changes SET status='kept', live_at=?, verdict_at=?, result=?, updated_at=? "
                                "WHERE id=? AND status='approved'",
                                (stamp, stamp, json.dumps({"at": stamp, "verdict": "kept", "words": said_of(row, "done")}), stamp,
                                 row["id"])).rowcount
        else:
            done = conn.execute("UPDATE seo_changes SET status='live', live_at=?, measure_after=?, baseline=?, updated_at=? "
                                "WHERE id=? AND status='approved'",
                                (stamp, _iso(t + judge.AFTER), json.dumps(baseline(conn, row, t.date(), cfg)), stamp,
                                 row["id"])).rowcount
        if done:
            went.append(row["page"])
    return went


def measure(conn: sqlite3.Connection, now: Optional[datetime] = None, cfg=None) -> list[dict]:
    """The weekly look at every live change its measure's AFTER old: the numbers its kind is judged on (measure_of) in
    the newest kept window that starts on or after the day it went live, against its baseline. Kept, put back (the site
    republishes), or measured again next week; a new page that did not earn its place ("down") stays on the site, its
    measuring ends, and taking it down is proposed and pinged to Chris (Chris, 2026-11-01: removing a page is a visible
    change, his Skip or Approve). One {"id", "page", "verdict", "words"} per change looked at."""
    t = _now(now)
    stamp, out = _iso(t), []
    for row in db.rows(conn, "SELECT * FROM seo_changes WHERE status='live' AND measure_after <= ? ORDER BY id", (stamp,)):
        win = search_console.latest_window(conn, starting_from=_day(row["live_at"]).isoformat())
        if win is None:
            verdict, words = None, f"{named(row['page']).capitalize()}: no Search Console read of the days since its new words went live yet."
            result = {"at": stamp, "verdict": None, "words": words}
        else:
            judge = measure_of(row)
            base = _loads(row["baseline"], {}) or baseline(conn, row, _day(row["live_at"]), cfg)
            since = judge.numbers(conn, win, row, cfg)
            verdict, change = judge.verdict(base, since)
            words = judge.words(row, verdict, base, since, change)
            result = {"at": stamp, **since, "change": change, "verdict": verdict, "words": words}
        if verdict == "down":
            conn.execute("UPDATE seo_changes SET status='kept', verdict_at=?, result=?, updated_at=? WHERE id=? AND status='live'",
                         (stamp, json.dumps(result), stamp, row["id"]))
            down = propose(conn, kind="takedown", page=row["page"], before={"title": _loads(row["after"], {}).get("title", "")},
                           after={"removed": True}, queries=_loads(row["queries"], []), search=row["search"], reason=words, now=t)
            ping(conn, down, dry_run=False)
        elif verdict:
            conn.execute("UPDATE seo_changes SET status=?, verdict_at=?, result=?, updated_at=? WHERE id=? AND status='live'",
                         (verdict, stamp, json.dumps(result), stamp, row["id"]))
            if verdict == "reverted":
                settings.set(conn, deploy.SEO_CHANGED_KEY, stamp)
        else:
            conn.execute("UPDATE seo_changes SET result=? WHERE id=?", (json.dumps(result), row["id"]))
        out.append({"id": row["id"], "page": row["page"], "verdict": verdict, "words": words})
    return out


# ------------------------------------------------------------------ drafting, for every kind's weekly finder

class CapReached(RuntimeError):
    """The monthly AI cap would be passed by one more call."""


def ask(conn: sqlite3.Connection, client, *, model: str, system: str, schema: dict, facts: dict, detail: str,
        agent: str) -> Optional[dict]:
    """Claude's answer for one change (raw), or None when it refused or answered nothing readable. Paid through ai/spend:
    reserved before the call, recorded after it under `detail`. Raises CapReached before a call that would pass the cap;
    any failure of the call itself is raised after the reservation is released."""
    held = spend.reserve(conn, agent, model)
    if held is None:
        raise CapReached("the monthly AI cap is reached")
    try:
        response = client.beta.messages.create(
            model=model, max_tokens=3000, betas=[FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            system=system, messages=[{"role": "user", "content": json.dumps(facts, indent=1)}])
    except Exception:
        spend.release(conn, held)
        raise
    u = response.usage
    spend.record(conn, agent, getattr(response, "model", None) or model, int(u.input_tokens or 0), int(u.output_tokens or 0),
                 detail, reservation=held)
    text = next((b.text for b in response.content if b.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def tidied(value) -> str:
    """Claude's words as the site would write them: a dash tidied into a comma (ai/claude.tidy), single spaces."""
    return " ".join(tidy(value).split()) if isinstance(value, str) else ""


def draft_week(conn: sqlite3.Connection, found: list[dict], draft: Callable[[object, dict], str], *, client, agent: str,
               error_kind: str, per_week: int) -> list[str]:
    """A kind's weekly drafting, live only: each page found (r["path"]) in turn, at most `per_week` drafted; a page with an
    open change of any kind, or resting, is left alone. The key and the SDK are reached for only when there is a page to
    draft. What happened to each, in words."""
    said, tried = [], 0
    for r in found:
        if tried >= per_week:
            break
        why = resting(conn, r["path"])
        if why:
            said.append(f"{r['path']}: left alone, {why}")
            continue
        if client is None:
            if not secrets.get_secret("ANTHROPIC_API_KEY"):
                said.append("no Anthropic key, so nothing drafted")
                break
            import anthropic  # here, so a week with nothing to draft needs neither key nor SDK
            client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
        tried += 1
        try:
            said.append(draft(client, r))
        except CapReached as e:
            said.append(f"{e}, so nothing more drafted")
            break
        except Exception as e:  # noqa: BLE001  the API or the network: this page waits a week, said once, never a dead run
            runner.record_error_once(conn, agent, error_kind, f"New search words for {r['path']} could not be drafted "
                                                              f"({type(e).__name__}: {e}); tried again next week.")
            said.append(f"{r['path']}: Claude could not be asked ({type(e).__name__})")
    return said


# ------------------------------------------------------------------ telling Chris

def actions(cid: int, token: str, view: Optional[tuple[str, str]] = None) -> str:
    """The ping's buttons: Approve and Skip (one token; the first used spends it), and `view` (label, dashboard path):
    Open, the change on the Search changes page, unless its kind has a preview to see first (view_of)."""
    label, path = view or ("Open", f"{PAGE}#c{cid}")
    return "; ".join((notify.token_action(f"{PAGE}/{cid}/by-token/approve", token, "Approve"),
                      notify.token_action(f"{PAGE}/{cid}/by-token/skip", token, "Skip"),
                      f"view, {label}, {notify.link(path)}"))


def preview_path(cid: int) -> str:
    """The dashboard page that shows a proposed new page as the site would (seo/pages.py preview)."""
    return f"{PAGE}/{cid}/preview"


def view_of(row) -> tuple[str, str]:
    """Where the ping opens: the rendered preview for a kind that has one (a new page carries photos: Chris, 2026-11-01,
    sees it before he taps Approve), else the change on the Search changes page."""
    return ("Preview", preview_path(row["id"])) if _kind(row["kind"]).PREVIEW else ("Open", f"{PAGE}#c{row['id']}")


def shown(row) -> list[tuple[str, str, str]]:
    """(what, before, after) for each thing the change alters, as Chris reads it; the first is the headline. A thing
    with no before (a new page's) is said once."""
    return _kind(row["kind"]).shown(row)


def ping_words(row) -> tuple[str, str]:
    lines = [f"{named(row['page']).capitalize()}: {row['reason']}", ""]
    for label, before, after in shown(row):
        lines += ([f"{label} now: {before}", f"{label} new: {after}"] if before else [f"{label}: {after}"]) + [""]
    lines.append(said_of(row, "close"))
    return f"{config.get_config().brand_name}: {said_of(row, 'ping')}", "\n".join(lines)


def ping(conn: sqlite3.Connection, cid: int, *, dry_run: bool, agent: str = "seo") -> str:
    """The proposal on his phone, with its signed Approve and Skip. What happened to the push."""
    row = get(conn, cid)
    title, message = ping_words(row)
    view = view_of(row)
    return notify.push_result(title, message, dry_run=dry_run, priority="default", click=notify.link(view[1]),
                              conn=conn, agent=agent, actions=actions(cid, approve_token.issue(conn, row, scope=TOKENS), view))


def waiting(conn: sqlite3.Connection) -> int:
    return int(db.one(conn, "SELECT COUNT(*) AS n FROM seo_changes WHERE status='proposed'")["n"])


def standing(conn: sqlite3.Connection) -> str:
    """How many changes stand where, for the SEO agent's summary: "1 waiting for your Approve, 2 live, being measured"."""
    counts = {r["status"]: r["n"] for r in db.rows(conn, "SELECT status, COUNT(*) AS n FROM seo_changes WHERE status IN "
                                                         f"({','.join('?' * len(OPEN))}) GROUP BY status", OPEN)}
    return ", ".join(f"{counts[s]} {STATUS_WORDS[s]}" for s in OPEN if counts.get(s)) or "none open"


def brief(conn: sqlite3.Connection, since: datetime) -> tuple[list[str], list[str]]:
    """(done, watching) for the morning brief: what was proposed, approved, put live, kept, put back or skipped since
    `since`, with the numbers; and each live change measured since then without a verdict yet."""
    s = _iso(since)
    done, watching = [], []
    for r in db.rows(conn, "SELECT * FROM seo_changes WHERE proposed_at >= ? OR approved_at >= ? OR live_at >= ? OR verdict_at >= ? "
                           "OR status='live' ORDER BY id", (s, s, s, s)):
        if r["proposed_at"] >= s:
            done.append(f"Search: {said_of(r, 'proposed')}")
        if (r["approved_at"] or "") >= s:
            done.append(f"Search: {said_of(r, 'approved')}")
        if (r["live_at"] or "") >= s and r["verdict_at"] != r["live_at"]:      # one done as it went live is said by its verdict
            done.append(f"Search: {said_of(r, 'live')}")
        if (r["verdict_at"] or "") >= s:
            done.append(f"Search: {said_of(r, 'skipped')}" if r["status"] == "skipped"
                        else f"Search: {_loads(r['result'], {}).get('words', '')}")
        result = _loads(r["result"], {})
        if r["status"] == "live" and result.get("at", "") >= s and not result.get("verdict"):
            watching.append(f"Search: {result.get('words', '')}")
    return done, watching


def numbers_words(n: Optional[dict]) -> str:
    """A page's numbers in a window, in words: "0.6% of 340 showings clicked from Oct 3 to Oct 30, average place 4.2"."""
    if not n or not n.get("start"):
        return ""
    return (f"{n['ctr']:.1%} of {n['impressions']} showings clicked from {span(n['start'], n['end'])}, "
            f"average place {n['position']:g}")


def describe(row) -> dict:
    """A change as Chris reads it: the words before and after (and what it sets, "words"), why, its searches (or the one
    it was made for), where it stands, its numbers, and its preview when its kind has one."""
    kind, judge = _kind(row["kind"]), measure_of(row)
    return {**dict(row), "name": named(row["page"]).capitalize(), "shown": shown(row), "queries": _loads(row["queries"], []),
            "words": _loads(row["after"], {}), "status_words": kind.STATUS_WORDS[row["status"]],
            "url": search_console.page_url(row["page"]), "preview": preview_path(row["id"]) if kind.PREVIEW else "",
            "baseline_words": judge.numbers_words(_loads(row["baseline"], None)) if judge else "",
            "result": _loads(row["result"], None)}


def view(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    """Every change for the Search changes page, those waiting first, then newest first; for one the site should carry
    and does not (site/build.with_seo_changes), why not."""
    from ..site import build
    brand = config.get_config().brand_name
    _, _, off_site = build.with_seo_changes(conn, build.page_words(offer.load(), build.copy_text(), brand), brand)
    return [{**describe(r), "off_site": off_site.get(r["id"], "")}
            for r in db.rows(conn, "SELECT * FROM seo_changes ORDER BY status != 'proposed', id DESC LIMIT ?", (limit,))]
