"""Content agent (daily, 08:00; Chris, 2026-10-11): tomorrow's post, drafted into the review queue for Chris.

1. The day: one post a day. BUILDING_WEEKDAY (default wednesday) is the
   building day, from the architecture work (Chris, 2026-10-09: one day a
   week); every other day is event work. When a day's kind has no photo
   ready, the other kind stands in.
2. The photo: candidates only (cleared, sorted, nobody possibly under 18, no
   readable details, not on the do-not-use list), never on a post inside
   the longer of PHOTO_REPEAT_DAYS and VARIETY_DAYS (config.repeat_window),
   and no event or credited person repeated inside VARIETY_DAYS. The least
   recently used first, quality breaking ties.
3. The final check: the full-size photo is downloaded (read only) and Claude
   looks once more, for its labels; nothing it says keeps out a photo Chris used (2026-11-08). A photo it cannot look
   at (no key, the cap) is skipped and the next one is tried.
4. Captions (ai/claude.py), the day's design from the motion set (render/motion.py:
   spotlight, single, carousel, fan, face match or a reel; see DESIGNS), and a draft row. Nothing leaves: the publisher sends only what Chris
   approves.

Dry run (the default): no paid call at all. The draft gets template captions
and no final check, so the dashboard shows it but refuses Approve until the
agent runs live. Live: the final check and Claude's captions, under the cap.
"""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from PIL import Image

from ..ai import claude, copy_rules, linkedin, names, seo_plan
from ..buffer import payloads
from ..core import approve_token, config, db, notify, runner, settings
from ..library import classify, copies, eligibility, moments, report

from . import art_director, learner
from .. import house_brief, music
from ..render import meta as image_meta

try:                                    # HEIC originals from a phone
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TARGETS = ("instagram", "facebook", "pinterest", "linkedin")
MAX_TRIES = 5
# 2026-10-13: the watchdog reads what the last run found (agents/watchdog.check_content_window) and starts this
# agent again inside the day's window when the reason was passing or the inputs changed
LAST_ATTEMPT_KEY = "content.last_attempt"
NO_DRAFT_PINGED_KEY = "content.no_draft_pinged"       # "day|reason": the phone hears each reason once a day
DRAFT_NOW_KEY = "content.draft_now_asked_at"          # Chris pressed Draft now on Today (2026-10-31); the next run drafts one more
REEL_STYLE_KEY = "reel.last_style"                     # the style the last reel was given, written the moment it is chosen
LINKEDIN_STYLE_KEY = "linkedin.last_style"             # the LinkedIn style the last draft was given (ai/linkedin.py), likewise
TRANSIENT_WORDS = ("could not run", "could not", "not signed in")


def target_day(cfg, now: Optional[datetime] = None) -> date:
    return (now or datetime.now(ZoneInfo(cfg.timezone))).astimezone(ZoneInfo(cfg.timezone)).date() + timedelta(days=1)


def subject_for(day: date) -> str:
    building = (config.getenv("BUILDING_WEEKDAY") or "wednesday").strip().lower()
    return "architecture" if WEEKDAYS[day.weekday()] == building else "event"


# The daily draft's own rows: a designed draft, a photo from the phone and Post this are drafted for today as well and
# carry their `source`; they never stand in for the day's post, nor make a set-aside day look drafted (2026-10-15).
DAILY = "json_extract(rule_report, '$.source') IS NULL"


def ask_draft_now(conn: sqlite3.Connection) -> None:
    """Draft now on Today (Chris, 2026-10-31: the one-touch samples "disappeared"; "Yes, bring it back"). The press is
    recorded; the content agent, started at once, drafts one more post for the day on the same road as the morning
    one, art director and all, and it lands in Needs you for his Approve. It never stands in for the day's post."""
    settings.set(conn, DRAFT_NOW_KEY, db.utcnow())


def draft_now_asked(conn: sqlite3.Connection) -> bool:
    return bool(settings.get(conn, DRAFT_NOW_KEY))


def already_drafted(conn: sqlite3.Connection, day: date) -> bool:
    return bool(db.one(conn, f"SELECT 1 FROM content_queue WHERE kind='photo' AND status != 'rejected' AND {DAILY} AND rule_report LIKE ?",
                       (f'%"for_day": "{day.isoformat()}"%',)))


def set_aside_for(conn: sqlite3.Connection, day: date) -> bool:
    """A post drafted for `day` that was set aside afterwards (Chris's reject, a do-not-use entry, a wrong shot;
    2026-10-13). The art director's own turn-backs carry no day and are drafted again inside their run."""
    return bool(db.one(conn, f"SELECT 1 FROM content_queue WHERE kind='photo' AND status='rejected' AND {DAILY} AND rule_report LIKE ?",
                       (f'%"for_day": "{day.isoformat()}"%',)))


def inputs_fingerprint(conn: sqlite3.Connection) -> str:
    """What a draft is made from, in one short string: the approved photos and folders, the sort, the final
    checks, the do-not-use list, the set-aside posts. When it changes, a day that found nothing is worth another try."""
    parts = []
    for sql in ("SELECT COUNT(*), MAX(clearance_at) FROM photos WHERE clearance != 'inherit'",
                "SELECT COUNT(*), MAX(clearance_at) FROM drive_folders WHERE clearance != 'not_cleared'",
                "SELECT COUNT(*), MAX(classified_at) FROM classifications WHERE method IN ('ollama', 'vision')",
                "SELECT COUNT(*), MAX(checked_at) FROM final_checks",
                "SELECT COUNT(*), MAX(added_at) FROM do_not_use",
                "SELECT COUNT(*), MAX(updated_at) FROM content_queue WHERE status = 'rejected'"):
        try:
            r = conn.execute(sql).fetchone()
            parts.append(f"{r[0]}:{r[1] or ''}")
        except sqlite3.OperationalError:
            parts.append("?")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


SKIPPED = "skip"          # rule_report.rejected_by of a post Chris skipped: its photos go back into the rotation (2026-10-15)

# Chris, 2026-10-16: "Why why why is it giving me this error when nothing was posted with this image!? Very frustrating
# because it's a good reel." The 8:00 daily draft picked its photos at 12:00 UTC and saved post 7 at 12:07; the designed
# draft started at 12:02, picked the same photo (both draw the least used first) and saved post 6 at 12:03. Each left out
# every photo in an open post; the other's picks did not exist yet. Now the roads that pick from the library hold one
# lock from the pick to the save (DRAFTING), and the save itself refuses a photo another post took meanwhile.
DRAFTING = "drafting"
DRAFTING_WAIT = 15 * 60          # seconds the daily draft and Post this wait for a draft being made to finish


class PhotosTaken(Exception):
    """A photo chosen for this draft went into another post while this one was being made (or, per network since
    2026-11-02, a person on it did), on every network the draft was for."""

    def __init__(self, photo: int, post: int, why: str = ""):
        super().__init__(why or f"photo {photo} went into post #{post} while this one was being drafted")
        self.photo, self.post = photo, post


def drafting_lock(wait: float):
    """The lock every road that picks from the library holds from its pick to its save; None when not had in `wait`
    seconds (0: no wait)."""
    import time as _time
    lock = runner.Lock(DRAFTING)
    deadline = _time.monotonic() + wait
    while not lock.acquire():
        if _time.monotonic() >= deadline:
            return None
        _time.sleep(5)
    return lock


def photo_holder(conn: sqlite3.Connection, photo_ids, days: int, network: Optional[str] = None) -> Optional[tuple[int, int]]:
    """(photo id, post id) when one of these photos is on another post inside the window, by the same rule as
    recent_use (open, sent, or set aside by the do-not-use list; a skipped one and one the art director turned back are
    not).
    With `network`, only a post that targets it: the window counts per network (Chris, 2026-11-02)."""
    wanted = moments.siblings(conn, photo_ids)          # a frame of the same moment on another post holds these too (2026-11-02)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    for r in db.rows(conn, "SELECT id, status, photo_ids, targets, rule_report FROM content_queue WHERE created_at >= ? AND "
                           "(status != 'rejected' OR rule_report LIKE '%\"rejected_by\"%') ORDER BY id", (since,)):
        if r["status"] == "rejected" and f'"rejected_by": "{SKIPPED}"' in (r["rule_report"] or ""):
            continue
        if network and network not in networks_of(r):
            continue
        hit = wanted & {int(p) for p in json.loads(r["photo_ids"] or "[]")}
        if hit:
            return min(hit), r["id"]
    return None


def networks_of(row) -> set[str]:
    """The networks a queue row counts on for the windows: its targets less the ones it was not sent to (rule_report
    skipped, the hold or skip said on the draft page). A row whose targets cannot be read counts everywhere."""
    try:
        targets = {str(n) for n in json.loads(row["targets"] or "[]")}
        meta = json.loads(row["rule_report"] or "{}")
    except (TypeError, ValueError):
        return set(payloads.NETWORKS)
    skipped = meta.get("skipped") if isinstance(meta, dict) and isinstance(meta.get("skipped"), dict) else {}
    return targets - set(skipped) if targets else set(payloads.NETWORKS)


def held_on(conn: sqlite3.Connection, photo_ids, days: int, people, variety_days: int) -> dict[str, dict]:
    """{network: {photo, post, why}} for every network a post of these photos may not go to now: a photo of it is on
    another post inside the repeat window that targets that network, or a person credited on it was on such a post
    inside VARIETY_DAYS. Chris, 2026-11-02: "LinkedIn and insta are two totally different platforms. That rule only
    applies to each platform Individually not all together"; the variety rule is read the same way."""
    out = {}
    for net in TARGETS:
        hit = photo_holder(conn, photo_ids, days, net)
        if hit:
            ours = {int(p) for p in photo_ids}
            frame = f"photo {hit[0]}" if hit[0] in ours else f"photo {hit[0]}, a frame of the same moment as one of these,"
            out[net] = {"photo": hit[0], "post": hit[1], "why": f"{frame} was on post #{hit[1]} inside the last {days} days; "
                                                                 f"a photo goes out once a network inside that window"}
            continue
        _, _, used_people = recent_use(conn, variety_days, net)
        named = next((c for c in people if c.lower() in used_people), None)
        if named:
            out[net] = {"photo": None, "post": 0, "why": f"{named} was on a post here inside the last {variety_days} days; "
                                                        "no person twice a network inside that window"}
    return out


def recent_use(conn: sqlite3.Connection, days: int, network: Optional[str] = None) -> tuple[set, set, set]:
    """(photo ids, event names, credited people) used by posts drafted inside the window, by any road (the daily
    draft, a designed draft, Post this, the phone): every post not rejected, and the photos of the ones set aside by the
    do-not-use list (`rule_report.rejected_by`, his decision; the event and the people of a set-aside post are not "used",
    since nothing of it aired). A post Chris skipped is not counted at all (2026-10-15: "Skip puts the photos back in
    rotation"), and neither is one the art director turned back (2026-11-08, his approval is final: nothing of it aired,
    and the art director never rules a photo he used unfit): their photos come round again, after the others, since
    their use stays on the rotation's record (library/report.photo_use). With `network`, only the posts that target it:
    the window counts per network (Chris, 2026-11-02)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    photos, events, people = set(), set(), set()
    for r in db.rows(conn, "SELECT status, photo_ids, targets, rule_report FROM content_queue WHERE created_at >= ? AND "
                           "(status != 'rejected' OR rule_report LIKE '%\"rejected_by\"%')", (since,)):
        if r["status"] == "rejected" and f'"rejected_by": "{SKIPPED}"' in (r["rule_report"] or ""):
            continue
        if network and network not in networks_of(r):
            continue
        photos.update(int(p) for p in json.loads(r["photo_ids"] or "[]"))
        if r["status"] == "rejected":
            continue                       # set aside: the photo sits out; the event and the people were never shown
        meta = json.loads(r["rule_report"] or "{}")
        if meta.get("event"):
            events.add(meta["event"].lower())
        people.update(x.lower() for x in meta.get("people") or [])
    # a moment is one photo (2026-11-02): the frames of one folder within MOMENT_MINUTES of a used one are used too, and a
    # picture that went out went out, whichever of its files was on the post (library/copies.py)
    return copies.every_copy(conn, moments.siblings(conn, photos)), events, people


def used_everywhere(conn: sqlite3.Connection, days: int, networks) -> tuple[set, set, set]:
    """(photos, events, people) used inside `days` on every one of `networks` (the ones that are on): the window counts per
    network (Chris, 2026-11-02), so only a photo or a person held everywhere that is on is out of the running; the events
    are the union, since they only order."""
    per = [recent_use(conn, days, net) for net in networks] or [recent_use(conn, days)]
    return (set.intersection(*(p[0] for p in per)), set.union(*(p[1] for p in per)), set.intersection(*(p[2] for p in per)))


def held_on_networks(conn: sqlite3.Connection, networks) -> Callable[[int, str], list[str]]:
    """`held(photo id, credit line) -> [networks]`: the networks, in posting order, where the photo is inside the repeat
    window or a person credited on it is inside VARIETY_DAYS (per network, Chris, 2026-11-02). Empty: free everywhere."""
    cfg = config.get_config()
    photos_on = {n: recent_use(conn, config.repeat_window(cfg), n)[0] for n in networks}
    people_on = {n: recent_use(conn, cfg.variety_days, n)[2] for n in networks}

    def held(pid: int, credit: str) -> list[str]:
        names = [c.lower() for c in credit.split()]
        return [n for n in networks if pid in photos_on[n] or any(c in people_on[n] for c in names)]
    return held


def instagram_first(rows: list[dict], networks) -> list[dict]:
    """The order kept inside each group: photos free on every network that is on, then the ones held only on a later
    network, then the ones held on the first (Instagram). 2026-11-02: the designed agent drafted post #62 as a reel held
    off Instagram, Facebook and Pinterest because photos already on Instagram but free on LinkedIn sat in one pool with
    fresh ones and the rotation picked them, with about 1,800 photos free on Instagram ready."""
    first = networks[0] if networks else ""
    return ([r for r in rows if not r.get("held_on")] + [r for r in rows if r.get("held_on") and first not in r["held_on"]]
            + [r for r in rows if first in (r.get("held_on") or [])])


def free_on_first(pool: list[dict], networks) -> tuple[list[dict], bool]:
    """(the photos a post may take, whether it had to fall back): the candidates free on the first network that is on
    (Instagram) while any is left; only when none is does a post go without it (2026-11-02). A post Chris chooses himself
    (Post this, the Send page, #61) is his to send where its photo is free."""
    first = networks[0] if networks else ""
    free = [r for r in pool if first not in (r.get("held_on") or [])]
    return (free, False) if free or not pool else (pool, True)


# The photos a post may take, before the rules, by kind of work (eligibility.WORK): sorted, in Drive, and only the file that
# stands for its picture (its largest sorted file), so a post never takes a small copy or two copies of one picture
# (library/copies.py, 2026-11-02). The designed drafts read it too.
CANDIDATE_SQL = {
    work: f"""SELECT p.*, c.subject, c.convention_name, c.event_kind, c.shot_type, c.quality, c.people_count, c.summary
              FROM photos p JOIN classifications c ON c.photo_id = p.id
              WHERE p.trashed = 0 AND {copies.STANDS_FOR_ITS_PICTURE} AND {where} AND c.method IN ('ollama', 'vision')
              ORDER BY COALESCE(c.quality, 0) DESC, COALESCE(c.people_count, 0) DESC, p.id"""
    for work, where in eligibility.WORK.items()}


def candidates(conn: sqlite3.Connection, subject: str) -> list[dict]:
    cfg = config.get_config()
    on = payloads.posting_networks()
    held = held_on_networks(conn, on)
    _, used_events, _ = used_everywhere(conn, cfg.variety_days, on)
    rows = db.rows(conn, CANDIDATE_SQL[subject])
    fresh, lately = [], []
    for r in rows:
        if not eligibility.is_candidate(conn, r["id"])[0]:
            continue
        credit = eligibility.credit_line(conn, r["id"])
        held_here = held(r["id"], credit)
        if len(held_here) == len(on):                  # inside the window on every network that is on: out of the running
            continue
        # an event a post had inside VARIETY_DAYS comes after every other event, not never: the designed drafts' rule
        # (2026-10-15, "while one is left"), now the daily draft's too. 2026-10-26: 1,481 of the 1,796 approved event
        # photos are one event, so the wall here left six candidates and the same six on every draft.
        shown = subject == "event" and bool(r["convention_name"]) and r["convention_name"].lower() in used_events
        (lately if shown else fresh).append({**dict(r), "credit": credit, "held_on": held_here})
    # what the learner found works, inside the founder's bounds
    def score(r):
        return -(r.get("quality") or 0) * learner.weight_for(conn, r.get("shot_type"), r.get("event_kind"))
    # then the rotation (2026-10-14, "the same photos for everything"; 2026-11-02, the shoot least recently used first):
    # the Drive folder least recently on a post for the networks that are on, then the least recently used photo on any
    # surface, so every shoot and every approved photo gets its turn; the score above only breaks ties, by chance
    last, shoots_last = report.last_uses(conn), shoot_uses(conn, on)
    return instagram_first(in_turn(conn, fresh, alike=score, last=last, shoots_last=shoots_last)
                           + in_turn(conn, lately, alike=score, last=last, shoots_last=shoots_last), on)


def shoot_uses(conn: sqlite3.Connection, networks) -> dict[str, str]:
    """{shoot (Drive folder): when a post for one of `networks` last took a photo of it}, by the posts recent_use counts
    (open, sent, or set aside by the do-not-use list; a skipped one and one the art director turned back are not), all
    time. A photo with no folder is its event's shoot (designed.shoot_of)."""
    from . import designed
    wanted = set(networks)
    by_photo: dict[int, str] = {}
    for r in db.rows(conn, "SELECT status, photo_ids, targets, rule_report, created_at FROM content_queue WHERE "
                           "(status != 'rejected' OR rule_report LIKE '%\"rejected_by\"%') ORDER BY created_at"):
        if r["status"] == "rejected" and f'"rejected_by": "{SKIPPED}"' in (r["rule_report"] or ""):
            continue
        if wanted and not (networks_of(r) & wanted):
            continue
        try:
            ids = [int(p) for p in json.loads(r["photo_ids"] or "[]")]
        except (TypeError, ValueError):
            continue
        for pid in ids:
            by_photo[pid] = max(by_photo.get(pid) or "", r["created_at"] or "")
    if not by_photo:
        return {}
    marks = ",".join("?" * len(by_photo))
    out: dict[str, str] = {}
    for p in db.rows(conn, f"SELECT p.id, p.folder_id, c.convention_name FROM photos p LEFT JOIN classifications c ON c.photo_id = p.id "
                           f"WHERE p.id IN ({marks})", list(by_photo)):
        shoot = designed.shoot_of(dict(p))
        out[shoot] = max(out.get(shoot) or "", by_photo[p["id"]])
    return out


def in_turn(conn: sqlite3.Connection, rows: list[dict], *, alike: Callable, last: Optional[dict] = None,
            shoots_last: Optional[dict] = None, rng=None) -> list[dict]:
    """The order a picker tries photos (2026-11-02, shoot rotation): the shoot least recently on a post first (never, then
    the oldest), then the photo least recently used on any surface (report.last_uses), then the caller's order (`alike`,
    the key it sorts by; photos it holds equal come in a chance order, as report.rotate has done since 2026-10-23)."""
    import random
    from . import designed
    last = report.last_uses(conn) if last is None else last
    shoots_last = shoot_uses(conn, payloads.posting_networks()) if shoots_last is None else shoots_last
    rng = rng or random.Random()
    rows = sorted(rows, key=alike)
    rank, prev, keyed = 0, object(), []
    for k, r in enumerate(rows):
        key = alike(r)
        if k and key != prev:
            rank += 1
        prev = key
        r["last_use"] = last.get(r["id"])
        keyed.append((shoots_last.get(designed.shoot_of(r)) or "", last.get(r["id"]) or "", rank, rng.random(), k))
    return [rows[i] for *_, i in sorted(keyed)]


class Picker:
    """The photos a post takes, in the pool's order, under the rules of 2026-11-02: never two frames of one moment, and
    at most moments.cap_for(need, shoots) photos from one shoot (FOLDER_CAP while enough shoots are free; more, spread
    evenly, when fewer shoots are free than the post needs, and `words()` says so for the run line). `candidates()`
    yields the rows worth trying next, against what `take()` has kept so far. A reel in one of the ten looks (`style`)
    takes the look's own count under the look's rule of portraits (render/reel_looks.photo_rule, 2026-11-08). A photo
    labelled a portrait with other than one person in it is never taken, by the sorter's label before the final check or
    by the check's after it: Portraits prints only over one person (house_brief.may_name, Chris, 2026-11-09)."""

    def __init__(self, pool: list[dict], design: str, *, style: Optional[str] = None):
        from . import designed
        from ..render import reel_looks
        look = style if design == "reel" and style in reel_looks.LOOKS else None
        self.pool, self.need, self.taken = list(pool), reel_looks.TAKES[look] if look else TAKES[design], []
        self.rule = reel_looks.photo_rule(look) if look else None
        self.shoot = designed.shoot_of
        sizes: dict[str, int] = {}
        for r in self.pool:
            sizes[self.shoot(r)] = sizes.get(self.shoot(r), 0) + 1
        self.shoots = len(sizes)
        self.cap = moments.cap_for(self.need, sizes.values())

    def fits(self, row: dict) -> bool:
        # A portrait of other than one person is drafted like any photo he approved (Chris, 2026-11-10: "Let them post,
        # without the word"; his approval is final). The word Portraits still prints only over one person: such a photo
        # is never a word photo (checked_rooms) and never in Axis, whose wall says Portraits (reel_looks.photo_rule).
        if any(r["id"] == row["id"] for r in self.taken) or any(moments.same_moment(row, r) for r in self.taken):
            return False
        if self.rule is not None and not self.rule(row, self.taken):
            return False
        return sum(1 for r in self.taken if self.shoot(r) == self.shoot(row)) < self.cap

    def candidates(self):
        for row in self.pool:
            if len(self.taken) >= self.need:
                return
            if self.fits(row):
                yield row

    def take(self, row: dict) -> None:
        self.taken.append(row)

    def words(self) -> str:
        """For the run line: when fewer shoots were free than the post needed, so one shoot gave more than FOLDER_CAP."""
        if self.cap <= moments.folder_cap() or self.need <= 1:
            return ""
        return f"{self.shoots} shoot{'s' if self.shoots != 1 else ''} free for {self.need} photos, so up to {self.cap} from one"


def use_why(hero: dict, ready: int) -> str:
    """Why this photo led, for the run line on the Agents page: its last use, and how many were ready."""
    when = f"last used {hero['last_use'][:10]}" if hero.get("last_use") else "never used before"
    held = hero.get("held_on") or []
    off = f"; no photo free on {' or '.join(payloads.name_of(n) for n in held)} is left, so this post is held off it" if held else ""
    return f"{when}; {ready} ready, least recently used first{off}"


def write_captions(drafter, facts: claude.PostFacts, photo: Path, known_names, *, conn=None,
                   agent: str = "content", judge_client=None) -> tuple[dict, str, dict, str]:
    """(captions, alt text, what happened, who wrote them). Chris, 2026-10-11: "Make sure the captions are SEO
    optimized painstakingly". The writer gets the post's search plan (ai/seo_plan.py); the hashtags and the
    link are put in place for it; a draft that misses the plan or breaks a rule is written once more with
    the misses named, and after a second miss the template, which meets the plan by construction, stands in.
    A writer that cannot write at all (the cap, a refusal, the API, the network) is the same: the template
    writes, and with `conn` the reason is recorded once (2026-10-13: never a dead run). The LinkedIn caption passes two more
    gates (ai/linkedin.py, 2026-11-01): his rhythm, and a he or she only when a separate look at the photo (`judge_client`,
    the art director's) says so; a miss is a miss like any other, and the LinkedIn fallback is a fixed line in his rhythm."""
    plan, link = facts.plan, facts.quote_link
    tries, notes, draft, caps, misses, writer_error = [], (), None, {}, [], ""
    looked: list = []                 # the photo's main person, as the art director sees it, asked once per write

    def main_subject():
        if not looked:
            looked.append(art_director.subject_of(conn, photo, client=judge_client, agent=agent)
                          if conn is not None and photo.is_file() else None)
        return looked[0]
    for _ in range(2):
        try:
            draft = drafter.draft(facts, photo, notes=notes)
        except claude.DraftError as e:
            writer_error = f"{type(e).__name__}: {e}"
            tries.append({"by": "template", "missed": [], "error": writer_error})
            misses = [f"the writer could not write ({writer_error})"]
            if conn is not None:
                runner.record_error_once(conn, agent, "captions",
                                         f"The caption writer could not write ({writer_error}); the template wrote instead.")
            break
        caps = seo_plan.finish(draft.captions, plan, link)
        misses = seo_plan.problems(caps, plan, facts.linkedin_style) + [f"the {n} caption {b.message}" for n, t in caps.items()
                                                  for b in copy_rules.check(t, names=known_names, social=True, linkedin=n == "linkedin").blocks]
        if "linkedin" in caps and linkedin.pronouns_in(caps["linkedin"]):
            misses += linkedin.pronoun_problems(caps["linkedin"], main_subject())
        # which networks' captions missed: only those take the template (2026-11-09 audit: one network's miss had thrown
        # away all four captions, so 13 of 30 posts carried the template somewhere)
        missed_on = {n for n, t in caps.items()
                     if seo_plan.problems({n: t}, plan, facts.linkedin_style)
                     or copy_rules.check(t, names=known_names, social=True, linkedin=n == "linkedin").blocks
                     or (n == "linkedin" and linkedin.pronouns_in(t) and linkedin.pronoun_problems(t, main_subject()))}
        tries.append({"by": draft.model, "missed": misses})
        if not misses or draft.model == "template":
            break
        notes = misses
    writer = draft.model if draft is not None else "template"
    by_template: list[str] = []
    if misses:
        template = seo_plan.template_captions(plan, link, facts.brand_name, facts.linkedin_style)
        if draft is None or caps is None or not missed_on or missed_on >= set(caps):
            caps, writer, by_template = template, "template", sorted(template)
        else:
            by_template = sorted(missed_on)
            caps = {**template, **{n: t for n, t in caps.items() if n not in missed_on}}
    from ..seo.photo_text import SHOT_WORDS
    alt = draft.alt_text if draft is not None else ""
    if not alt or len(alt) > 125 or not copy_rules.check(alt, names=known_names, social=True).ok:
        alt = seo_plan.alt_text(plan, SHOT_WORDS.get(facts.shot_type, ""), facts.brand_name)
    record = {"primary": plan.primary, "related": list(plan.related), "hashtags": list(plan.hashtags), "area": plan.area,
              "tries": tries, "fell_back": bool(misses), "by_template": by_template, **({"subject_check": looked[0]} if looked else {})}
    if writer_error:
        record["writer_error"] = writer_error
    return caps, alt, record, writer


# Chris, 2026-10-12: "the captions should auto correct themselves with the warnings they gave me before
# approval. I don't want to change any captions." A draft already in the queue whose captions break a rule
# (the rules grew after it was written: 2026-10-11 took every word about what is offered out of public copy)
# is rewritten by the suite with the rule's own words as the correction, the way a fresh draft is, and the
# template stands in when the writer misses twice. Never his hands.
MENDABLE = ("draft",)


def official_for(conn: sqlite3.Connection, row) -> bool:
    """A post may say "official" only for an event Chris marked official on the calendar."""
    if not row["convention_id"]:
        return False
    c = db.one(conn, "SELECT official FROM conventions WHERE id=?", (row["convention_id"],))
    return bool(c and c["official"])


def mend_captions(conn: sqlite3.Connection, row, *, drafter=None, agent: str = "content") -> Optional[dict]:
    """Rewrite a queued draft's captions when one breaks a rule now. Returns the mend record, or None
    when every caption passes (nothing is touched then, and nothing is spent)."""
    known_names = names.public_names(conn)
    official = official_for(conn, row)
    try:
        captions = json.loads(row["caption"] or "{}")
        meta = json.loads(row["rule_report"] or "{}")
    except ValueError:
        captions, meta = {}, {}
    broken = {n: [b.message for b in copy_rules.check(t, official=official, names=known_names, social=True, linkedin=n == "linkedin").blocks]
              for n, t in captions.items()}
    broken = {n: m for n, m in broken.items() if m}
    if not broken or row["kind"] != "photo":
        return None
    cfg = config.get_config()
    pids = [int(x) for x in json.loads(row["photo_ids"] or "[]")] if row["photo_ids"] else []
    hero = db.one(conn, """SELECT p.*, c.subject, c.event_kind, c.shot_type FROM photos p
                           LEFT JOIN classifications c ON c.photo_id = p.id WHERE p.id=?""", (pids[0],)) if pids else None
    subject = (hero["subject"] if hero and hero["subject"] else meta.get("subject")) or "event"
    design = meta.get("design") or "single"
    facts = claude.PostFacts(brand_name=cfg.brand_name, event_kind=(hero["event_kind"] if hero else None) or "unknown",
                             shot_type=(hero["shot_type"] if hero else None) or "", subject=subject, official=official,
                             quote_link=f"{cfg.brand_domain}/book" if cfg.brand_domain else "",
                             linkedin_style=meta.get("linkedin_style") or linkedin.STYLES[0])     # the draft keeps its style
    facts.plan = seo_plan.plan_for(subject=subject, event_kind=facts.event_kind, shot_type=facts.shot_type, design=design)
    photo = Path(hero["local_path"]) if hero and hero["local_path"] else (cfg.data_root / "photos" / f"{hero['drive_id']}.img" if hero else None)
    if drafter is None:
        # the writer looks at the photo; without a copy of it here the template, which cannot miss, writes
        drafter = claude.get_drafter(conn, agent=agent) if photo is not None and photo.exists() else claude.TemplateDrafter()
    # the cap, a refusal, the API: the template stands in and the record says so (write_captions)
    fixed, alt, record, writer = write_captions(drafter, facts, photo or Path("none"), known_names, conn=conn, agent=agent)
    fixed = {n: t for n, t in fixed.items() if n in captions}      # a network the draft never had (LinkedIn skipped) stays out
    reports = {n: copy_rules.check(t, names=known_names, social=True, linkedin=n == "linkedin").as_dict() for n, t in fixed.items()}
    mend = {"at": db.utcnow(), "by": writer, "fixed": broken, "was": {n: captions[n] for n in broken}}
    # the card comes from the same day as the captions: drawn again with today's words where the photos are here
    try:
        paths, note = redraw(conn, row, meta, agent=agent)
    except Exception as e:  # noqa: BLE001  a card that cannot be drawn again stays; the captions are still mended
        paths, note = None, f"card kept: it could not be drawn again ({type(e).__name__}: {e})"
    mend["card"] = note
    meta.update(rules=reports, alt_text=alt, seo={**(meta.get("seo") or {}), **record},
                mended=list(meta.get("mended") or []) + [mend])
    if paths is not None:
        conn.execute("UPDATE content_queue SET render_paths=? WHERE id=?", (json.dumps(paths), row["id"]))
    conn.execute("UPDATE content_queue SET caption=?, rule_report=?, updated_at=? WHERE id=?",
                 (json.dumps(fixed), json.dumps(meta), db.utcnow(), row["id"]))
    return mend


def mend_queue(conn: sqlite3.Connection, *, drafter=None, agent: str = "content") -> int:
    """Every open draft, mended where a rule now bites. The number rewritten."""
    rows = db.rows(conn, f"SELECT * FROM content_queue WHERE kind='photo' AND status IN ({','.join('?' * len(MENDABLE))}) ORDER BY id",
                   MENDABLE)
    return sum(1 for r in rows if mend_captions(conn, r, drafter=drafter, agent=agent) is not None)


def kicker_for(row: dict) -> str:
    """The small line printed on the post: the kind of work, never which event or who is in it.
    Chris, 2026-10-11: "i want to make sure the captions don't say the specific event or person", and on
    the cards: "It should say photography somewhere. Something in the middle"."""
    if row["subject"] == "architecture":
        return "Venue photography"
    return {"fan": "Convention photography", "business": "Conference photography"}.get(row.get("event_kind") or "", "Event photography")


# Chris, 2026-10-11: "Switch to new designs and it's ok to use 1 photo too sometimes." One design a
# day from the motion set (render/motion.py); a building day is always a single photo. A day whose
# design needs more approved photos than pass the final check falls back to a single photo.
# "Let's get the music and everything working (video format too)": Saturday is a reel once a music
# track is on (music.py); with none it stays a single photo, never a silent reel.
# The face match post (Sundays) and the face match reel (every other Saturday) are retired, 2026-10-11:
# they explained the delivery service, and a post keeps to what the photo shows.
# Chris, 2026-10-15, after "come up with some new designs (like 4 so they arent all exactly the same design everytime)":
# the four bold designs (render/bold.py: poster, slit scan, cascade, select) and, on his first round's renders,
# "perfect! and we still keep the original one we started with on the very first post to insta" (the spotlight, Buffer
# post 6ad00a04117064a577d1469f). No design two days running. The single, the carousel and the fan leave the week; they
# stay for a phone send, a Post this on a sample and a reel that cannot be made.
DESIGNS = {"monday": "spotlight", "tuesday": "poster", "wednesday": "scan", "thursday": "cascade",
           "friday": "select", "saturday": "reel", "sunday": "poster"}
NEEDS = {"single": 1, "spotlight": 3, "carousel": 4, "fan": 5, "reel": 4,       # fewest photos
         "poster": 1, "scan": 1, "cascade": 3, "select": 4}
TAKES = {"single": 1, "spotlight": 5, "carousel": 6, "fan": 7, "reel": 6,       # most
         "poster": 1, "scan": 1, "cascade": 3, "select": 6}
ONE_PHOTO = ("poster", "scan")                 # a day with too few photos, a building day, a Saturday with no music


def fallback_for(day: date) -> str:
    """The one-photo design a day falls back to: the first of ONE_PHOTO that is neither yesterday's nor tomorrow's design,
    so a fallback never puts the same design on two days running."""
    i = day.weekday()
    near = {DESIGNS[WEEKDAYS[(i - 1) % 7]], DESIGNS[WEEKDAYS[(i + 1) % 7]]}
    return next((d for d in ONE_PHOTO if d not in near), next(d for d in ONE_PHOTO if d != DESIGNS[WEEKDAYS[(i - 1) % 7]]))


def design_for(day: date, subject: str, has_music: bool = False) -> str:
    """A building day is always a one-photo design (2026-10-09: one building photo a week), and a reel never goes out
    silent (2026-10-11). Chris, 2026-10-23: "Mostly reels": every event day with a music track is a reel; the week's
    still designs are the days without one (and a day with too few photos falls back as before)."""
    if has_music and subject != "architecture":
        return "reel"
    design = DESIGNS[WEEKDAYS[day.weekday()]]
    if (design == "reel" and not has_music) or (subject == "architecture" and NEEDS[design] > 1):
        return fallback_for(day)
    return design


def reel_style(conn: sqlite3.Connection, rng=None, *, fits: Optional[Callable[[str], bool]] = None) -> str:
    """One of the five 3D styles at random, never the one the last reel had (Chris, 2026-10-23: "there should be 5
    different style reels (all very different)", used randomly). The rooms reel of before is out of the rotation.
    With REEL_LOOKS on (render/reel_looks.enabled; off by default) the ten looks Chris approved on 2026-11-08 join
    them: each look a track suits (music.for_look) and, when the caller says what its photos allow (`fits(look)`), one
    they allow. The chance of each is its learned weight (learner.look_weight, 0.5 to 1.5; 1.0 until learned), so a
    weight leans the rotation and never leaves a style out.
    Chosen and recorded in one write under the database's write lock: the daily and the designed lane run under
    different locks and a render takes minutes, so two reels that each read "the last reel's row" and wrote their own
    after the render could come out the same (2026-10-24 audit). A reel the art director turns back was the last too."""
    import random
    from ..render import reel_looks, reels3d
    looks = [look for look in reel_looks.LOOKS if music.for_look(conn, look) is not None and (fits is None or fits(look))] \
        if reel_looks.enabled() else []
    conn.execute("BEGIN IMMEDIATE")
    try:
        last = settings.get(conn, REEL_STYLE_KEY)
        choices = [s for s in (*reels3d.STYLES, *looks) if s != last]
        style = (rng or random.Random()).choices(choices, weights=[learner.look_weight(conn, s) for s in choices])[0]
        settings.set(conn, REEL_STYLE_KEY, style)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return style


def give_back_style(conn: sqlite3.Connection, style: Optional[str], before: Optional[str]) -> None:
    """A reel style chosen before its photos (reel_style) for a draft that then made no reel, too few photos having
    passed: the memory goes back to the style the last reel was given, so "the last reel" stays a reel that was made."""
    if style and settings.get(conn, REEL_STYLE_KEY) == style:
        settings.set(conn, REEL_STYLE_KEY, before or "")


def linkedin_style(conn: sqlite3.Connection) -> str:
    """The next LinkedIn style round robin (Chris, 2026-11-01 evening: "Mix all three"), chosen and recorded in one write under
    the database's write lock, like the reel's, so two drafts made at once never read the same way."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        style = linkedin.next_style(settings.get(conn, LINKEDIN_STYLE_KEY))
        settings.set(conn, LINKEDIN_STYLE_KEY, style)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return style


def order_pool(pool: list, design: str) -> list:
    """The order to try the photos in: for a post of several, one per shoot (Drive folder) and per room before any
    repeats (2026-10-23: post 27 took four frames of one folder), else as the rotation gave them."""
    if TAKES[design] <= 1:
        return pool
    from . import designed
    return designed.spread(pool, len(pool))


def checked_rooms(conn: sqlite3.Connection, photo_ids: list) -> dict[int, Optional[str]]:
    """{photo id: the room Claude's final check of the full photo says it plainly shows (a key of
    design_samples.ROOMS), else None}. A photo with no final check (a dry run), one checked before the question was
    asked, or one whose room was "none" has none; so has a portrait of other than one person, so no post or reel prints
    Portraits over a pair or a group and none takes one as a word photo (house_brief.may_name, Chris, 2026-11-09)."""
    from ..render import design_samples
    got = {}
    ids = [int(i) for i in photo_ids]
    if ids:
        marks = ",".join("?" * len(ids))
        got = {r["photo_id"]: r["room"] for r in db.rows(conn, "SELECT f.photo_id, f.room, c.people_count FROM final_checks f "
                                                               "LEFT JOIN classifications c ON c.photo_id = f.photo_id "
                                                               f"WHERE f.photo_id IN ({marks})", ids)
               if house_brief.may_name(r["room"], r["people_count"])}
    return {i: got.get(i) if got.get(i) in design_samples.ROOMS else None for i in ids}


def confirmed_rooms(conn: sqlite3.Connection, photo_ids: list) -> dict:
    """{photo id: (room, line)}: the room Claude's final check of the full photo says it plainly shows, else
    EVENT PHOTOGRAPHY (2026-10-15: the sorter's shot type had put "After Dark" on a sunny garden)."""
    from ..render import design_samples
    return {i: design_samples.ROOMS.get(room or "", design_samples.UNCONFIRMED) for i, room in checked_rooms(conn, photo_ids).items()}


def shot_for(row: dict, image: Image.Image, focus=(0.5, 0.45), words: Optional[tuple] = None):
    """The photo with the room and line printed on it: `words` from confirmed_rooms; without them nothing is named."""
    from ..render import design_samples, motion
    room, line = words or design_samples.UNCONFIRMED
    return motion.Shot(image, room, line, focus)


def middle_first(items: list, hero) -> list:
    """The hero in the middle of the rest, where the fan and the rail put the eye."""
    rest = [x for x in items if x is not hero]
    k = len(rest) // 2
    return rest[:k] + [hero] + rest[k:]


def aspects_for(targets, skipped=()) -> set[str]:
    """The render keys a draft needs: what each network it goes to receives (payloads.ASPECT_FOR), for the networks that are
    ticked, on (POST_NETWORKS) and not held off or skipped. Nothing is drawn for a network the draft is not going to
    (Chris, 2026-11-02: a LinkedIn-only draft's page led with the Instagram card, "a completely fully branded photo")."""
    on = payloads.posting_networks()
    return {payloads.ASPECT_FOR[n] for n in targets if n in on and n not in skipped and n in payloads.ASPECT_FOR}


def make_renderer(conn: sqlite3.Connection, agent: str, *, design: str, rows: list, hero: dict, images: dict, day: date,
                  track, out_dir: Path, seo, reel_style: Optional[str] = None, aspects: Optional[set] = None,
                  look_plan=None, reel_video: Optional[Path] = None) -> tuple[Callable[[tuple], dict], list]:
    """The day's design on its photos, as `render(focus) -> {aspect: [paths]}` for the art director, and the
    list a failed reel is written to (the same photos then go out as a carousel). Shared by the fresh draft
    and the mend, so a redrawn card is the same card the day would have made. `aspects`: the render keys wanted
    (aspects_for), the design at 4:5 for Instagram and Facebook (a reel there when the design is one), the 2:3 card
    for Pinterest, the photo as shot for LinkedIn; None draws everything. A reel in one of the ten looks is rendered
    with `look_plan` (render/reel_looks.Plan: its lines and its track); `reel_video`, a reel in a look rendered before
    (`ccs queue-reel`), is taken as it is, its cover and stills cut from it."""
    from ..render import bold, design_samples, motion, photo, reel_looks, reels3d
    words = confirmed_rooms(conn, [r["id"] for r in rows])
    rooms = checked_rooms(conn, [r["id"] for r in rows])
    kicker = kicker_for(hero).upper()
    if kicker == words[hero["id"]][0] or words[hero["id"]] == design_samples.UNCONFIRMED:
        # the small line never repeats the title under it: no room confirmed, the title is EVENT PHOTOGRAPHY and the small
        # line EVENT CALIBER (2026-10-15; "CONFERENCE PHOTOGRAPHY" over "EVENT PHOTOGRAPHY" was a near repeat)
        kicker = "EVENT CALIBER"
    copy = motion.MotionCopy(kicker=kicker)
    if design == "reel":
        # a reel prints a title over a photo only when it is that photo's own confirmed label; one with none carries no
        # title, never a stand-in (Chris, 2026-11-10: "Any photo title should just carry its sorted, but CORRECT name";
        # Gallery and Loop had printed EVENT PHOTOGRAPHY over such photos)
        words = {i: (("", "") if w == design_samples.UNCONFIRMED else w) for i, w in words.items()}
    tag = f"{hero['id']}-{design}"
    reel_failed: list[str] = []
    bare: dict = {}
    wanted = set(aspects) if aspects is not None else {"4:5", "2:3", photo.LINKEDIN_PHOTO}
    feed = "4:5" in wanted                   # Instagram or Facebook is going: the design (or the reel) is drawn

    def single(focus, aspects=("4:5", "2:3")):
        shot = shot_for(hero, images[hero["id"]], focus, words[hero["id"]])
        return {a: [str(motion.single_post(shot, copy, out=out_dir / f"{tag}-{a.replace(':', '')}.jpg", aspect=a,
                                           kicker=kicker, meta=seo))] for a in aspects if a in wanted}

    def as_shot():
        """LinkedIn's image beside the day's design: the hero as shot, no card (render_paths "linkedin"; 2026-11-01 evening,
        "Let's do that"), written once however often the crop is reworked."""
        if photo.LINKEDIN_PHOTO in wanted and not bare:
            bare[photo.LINKEDIN_PHOTO] = [str(photo.as_shot(images[hero["id"]], out_dir / f"{tag}-linkedin.jpg", meta=seo))]
        return dict(bare)

    def render(focus):
        if design == "single":
            return {**single(focus), **as_shot()}
        shots = [shot_for(r, images[r["id"]], words=words[r["id"]]) for r in rows]
        if design in bold.DESIGNS:
            # the four bold designs (2026-10-15), each with its own 2:3 card for Pinterest; the hero first, the photos whole
            return {**{a: [str(bold.post(design, shots, copy, out=out_dir / f"{tag}-{a.replace(':', '')}.jpg", aspect=a, meta=seo))]
                       for a in ("4:5", "2:3") if a in wanted}, **as_shot()}
        if design == "reel" and feed and not reel_failed:
            # Instagram and Facebook get the reel (render_paths "9:16"), with its cover; Pinterest the
            # hero as a 2:3 card and LinkedIn the hero as shot; the art director looks at the cover and the stills, never the mp4
            try:
                video_at = out_dir / f"{tag}-{reel_looks.file_name(reel_style)}.mp4"
                if reel_style in reel_looks.LOOKS:
                    if reel_video is not None:
                        video, word_frames = reel_looks.take_video(reel_video, video_at), None
                    else:
                        photos = [reel_looks.LookPhoto(images[r["id"]], rooms[r["id"]],
                                                       tuple(focus) if r["id"] == hero["id"] else reel_looks.DEFAULT_FOCUS) for r in rows]
                        # every slot a picture of its own: the look's other slots take fillers (2026-11-08, night)
                        made = reel_looks.render(reel_style, photos, plan=look_plan, out=video_at,
                                                 fillers=reel_looks.fillers(conn, reel_style, rows))
                        reels3d.record_wall(conn, [f.id for f in made.fillers])     # the ones it showed rotate on
                        video, word_frames = made.video, made.word_frames
                    stills = reel_looks.stills(reel_style, video, out_dir=out_dir / f"{tag}-stills", meta=seo, frames=word_frames)
                else:
                    # every picture a slot of its own: the style's other slots take fillers, as many as it shows (2026-11-09)
                    made = reels3d.render(reel_style, shots, out=video_at, audio=track,
                                          fillers=reels3d.fillers(conn, reel_style, len(shots), exclude=[r["id"] for r in rows]))
                    reels3d.record_wall(conn, [f.id for f in made.fillers])     # the ones it showed rotate on
                    video = made.video
                    stills = reels3d.stills(reel_style, video, out_dir=out_dir / f"{tag}-stills", meta=seo)
            except Exception as e:  # noqa: BLE001  a reel that cannot be made leaves a carousel of the same photos, said why
                reel_failed.append(f"{type(e).__name__}: {e}")
                runner.record_error(conn, agent, "reel", f"the {reel_style} reel for {day} was not made: {e}")
            else:
                return {"9:16": [str(video)], "cover": [str(stills[0])], **single(focus, ("2:3",)), **as_shot(),
                        "stills": [str(p) for p in stills[1:]]}
        # every design carries the hero as a 2:3 card for Pinterest (2026-10-13: without one the publisher fell back
        # to the photo's own .img copy, which it refuses, and the whole post failed on every network)
        if not feed:                               # neither Instagram nor Facebook is going: no design at all
            return {**single(focus, ("2:3",)), **as_shot()}
        if design in ("carousel", "reel"):        # the reel's fallback takes the same 4 to 6 photos
            return {"4:5": [str(p) for p in motion.carousel(shots, copy, out_dir=out_dir / tag, meta=seo)], **single(focus, ("2:3",)), **as_shot()}
        ordered = middle_first(shots, shots[0])
        mid = ordered.index(shots[0])
        if design == "fan":
            return {"4:5": [str(motion.fan_post(ordered, copy, out=out_dir / f"{tag}.jpg", focus=mid, meta=seo))],
                    **single(focus, ("2:3",)), **as_shot()}
        return {"4:5": [str(motion.spotlight_post(ordered, copy, out=out_dir / f"{tag}.jpg", index=mid, meta=seo))],
                **single(focus, ("2:3",)), **as_shot()}

    return render, reel_failed


# what the art director is told the still designs are; the bold four say it themselves (bold.DESIGNS[...].what)
BRIEFS = {
    "single": "One photo as one card in depth, turned a little toward you over a glossy floor, at 4:5 and at 2:3.",
    "carousel": "The first slides of a carousel: a fanned cover of its photos, then a rail slide per room, the next room "
                "waiting at the right.",
    "spotlight": "The spotlight: the hero photo at the centre of a rail of the post's photos, and the hero on a 2:3 card.",
    "fan": "The fan: the post's photos as cards fanned on a stage, and the hero on a 2:3 card.",
}


def brief_for(design: str, style: Optional[str], paths: dict) -> str:
    """What the art director is told it is looking at, from what `render` made. A reel says its style and what the
    style puts on the frame on purpose (reels3d.brief; a look's own, and the rule of its words: reel_looks.brief); a
    reel that could not be made is the carousel it fell back to."""
    from ..render import bold, reel_looks, reels3d
    if design == "reel":
        if "9:16" in paths:
            if style in reel_looks.LOOKS:
                return reel_looks.brief(style, card="2:3" in paths, stills=len(paths.get("stills") or []))
            return reels3d.brief(style)
        design = "carousel"
    if design in bold.DESIGNS:
        return f"The {design} design, {bold.DESIGNS[design].what}, at 4:5 and at 2:3."
    return BRIEFS[design]


def redraw(conn: sqlite3.Connection, row, meta: dict, *, agent: str = "content", only: Optional[set] = None) -> tuple[Optional[dict], str]:
    """The card of a queued draft drawn again with today's design copy, from the copies of its photos on
    this machine (the cards from before 2026-10-11 said "coverage", a word a card no longer carries).
    (new render_paths, note); None when a photo copy is missing, and the old card stays, said so. `only`: draw
    just these render keys and keep the rest (a network ticked after the draft, 2026-11-02)."""
    cfg = config.get_config()
    pids = [int(x) for x in json.loads(row["photo_ids"] or "[]")] if row["photo_ids"] else []
    rows = [db.one(conn, """SELECT p.*, c.subject, c.event_kind, c.shot_type, c.convention_name FROM photos p
                            LEFT JOIN classifications c ON c.photo_id = p.id WHERE p.id=?""", (pid,)) for pid in pids]
    if not rows or any(r is None for r in rows):
        return None, "card kept: a photo of it is no longer in the library"
    rows = [dict(r) for r in rows]
    images = {}
    for r in rows:
        path = Path(r["local_path"]) if r["local_path"] else cfg.data_root / "photos" / f"{r['drive_id']}.img"
        if not path.is_file():
            return None, f"card kept: no copy of photo {r['id']} on this machine"
        images[r["id"]] = Image.open(io.BytesIO(path.read_bytes()))
    try:
        day = date.fromisoformat(meta.get("for_day") or "")
    except ValueError:
        day = target_day(cfg)
    design = meta.get("design") or "single"
    hero = rows[0]
    track = music.current(conn) if design == "reel" else None
    from ..render import reel_looks, reels3d
    # a reel keeps its style or look; one with none known (made before either) gets the next its photos allow
    known = meta.get("reel") in (*reels3d.STYLES, *reel_looks.LOOKS)
    rooms, supply = checked_rooms(conn, [r["id"] for r in rows]), reel_looks.Supply(conn)
    style = meta["reel"] if known else (reel_style(conn, fits=lambda look: reel_looks.fits(look, rows, rooms=rooms, supply=supply))
                                         if design == "reel" else None)
    look_plan, reel_video = None, None
    if design == "reel" and style in reel_looks.LOOKS:
        look_plan, reel_video, track = look_parts(conn, row, meta, style)
    out_dir = cfg.data_root / "renders" / "posts" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = json.loads(row["targets"] or "[]")
    render, reel_failed = make_renderer(conn, agent, design=design, rows=rows, hero=hero, images=images, day=day, track=track,
                                        out_dir=out_dir, seo=image_meta.for_photo(conn, hero), reel_style=style,
                                        aspects=only if only is not None else aspects_for(targets, meta.get("skipped") or {}),
                                        look_plan=look_plan, reel_video=reel_video)
    art = meta.get("art") or {}
    focus = tuple(art["focus"]) if isinstance(art.get("focus"), list) and len(art["focus"]) == 2 else (0.5, 0.42)
    paths = render(focus)
    if design == "reel":
        meta["music"] = track.name if track else None       # the track this reel carries, named under its player
        meta["reel"] = style
        if look_plan is not None:
            meta["lines"] = look_plan.lines
    if reel_failed:
        meta["design"], meta["reel_failed"] = "carousel", reel_failed[0]
    if only is not None:
        return {**json.loads(row["render_paths"] or "{}"), **paths}, "drawn for the networks ticked now"
    return paths, "card drawn again with today's words"


def look_parts(conn: sqlite3.Connection, row, meta: dict, look: str) -> tuple:
    """(plan, reel_video, track) a reel in one of the ten looks is drawn again with. A reel queued ready-made
    (`reel_given`, ccs queue-reel) is taken again as it is: its copy beside the post, else the file it was queued from.
    Any other is rendered again with its own lines (another set when its own may not go on the look: reel_lines.fits)
    and track (the track it was made with while that is here, else the look's next one)."""
    from .. import reel_lines
    from ..render import reel_looks
    if meta.get("reel_given"):
        made = [Path(p) for p in json.loads(row["render_paths"] or "{}").get("9:16") or [] if Path(p).is_file()]
        given = made[0] if made else Path(meta["reel_given"])
        return None, given, (music.folder() / meta["music"]) if meta.get("music") else None
    played = music.played_as(conn, meta.get("music")) or music.for_look(conn, look, lambda f: learner.track_weight(conn, f))
    lines = meta["lines"] if reel_lines.fits(meta.get("lines"), look) else reel_lines.choose(conn, look)
    return (reel_looks.Plan(lines, played) if played else None), None, (played.path if played else None)


def draw_missing(conn: sqlite3.Connection, row, *, agent: str = "content") -> str:
    """A ticked network whose file is missing (ticked after the draft, or turned on since) gets it drawn now, so the draft
    page shows what it will receive (2026-11-02). On a reel row the video stands in for the 4:5 design. The note, or ""
    when nothing was missing."""
    meta = json.loads(row["rule_report"] or "{}") if row["rule_report"] else {}
    meta = meta if isinstance(meta, dict) else {}
    have = {k for k, v in json.loads(row["render_paths"] or "{}").items() if v}
    if "9:16" in have:
        have.add("4:5")
    missing = aspects_for(json.loads(row["targets"] or "[]"), meta.get("skipped") or {}) - have
    if not missing:
        return ""
    paths, note = redraw(conn, row, meta, agent=agent, only=missing)
    if paths is not None:
        conn.execute("UPDATE content_queue SET render_paths=?, rule_report=?, updated_at=? WHERE id=?",
                     (json.dumps(paths), json.dumps(meta), db.utcnow(), row["id"]))
    return note


def draft_one(ctx: runner.Context, fetch: Callable[[dict], bytes], *, now: Optional[datetime] = None,
              check_client=None, drafter=None, art_client=None, judge_client=None, extra: bool = False, _depth: int = 0) -> str:
    """`extra`: one more post for the day, asked for with Draft now (2026-10-31); it skips the one-a-day gate and is
    marked so it never counts as the day's post."""
    from ..render import reel_looks
    day = target_day(ctx.cfg, now)
    if not extra and already_drafted(ctx.conn, day):
        today = day - timedelta(days=1)
        if not (set_aside_for(ctx.conn, today) and not already_drafted(ctx.conn, today)):
            return f"a post for {day} is already drafted"
        day = today                  # today's post was set aside (a reject, a do-not-use entry): drafted again now, not lost
    want = subject_for(day)
    pool = candidates(ctx.conn, want)
    kind_used = want
    if not pool:
        kind_used = "event" if want == "architecture" else "architecture"
        pool = candidates(ctx.conn, kind_used)
    if not pool:
        return f"no photo ready for {day}: tap Use on photos in Photos, To review (nothing drafted)"
    pool, _ = free_on_first(pool, payloads.posting_networks())   # never held off Instagram while a photo free there is left (2026-11-02)
    track = music.current(ctx.conn)
    design = design_for(day, kind_used, track is not None)
    pool = order_pool(pool, design)
    # a reel's style is chosen before its photos: a look takes its photos under its own rule of portraits (2026-11-08)
    last_style = settings.get(ctx.conn, REEL_STYLE_KEY)
    supply = reel_looks.Supply(ctx.conn)          # the fillers' pool, read once if a look is weighed
    style = reel_style(ctx.conn, fits=lambda look: reel_looks.can_fill(look, pool, supply)) if design == "reel" else None
    chosen: list[tuple[dict, bytes]] = []
    check_errors: list[str] = []
    picker, tries = Picker(pool, design, style=style), 0   # one frame per moment, at most the cap per shoot (2026-11-02)
    for row in picker.candidates():
        if tries >= picker.need + MAX_TRIES - 1:
            break
        tries += 1
        data = fetch(row)
        if not ctx.dry_run:
            try:
                verdict = classify.final_check(ctx.conn, row["id"], data, client=check_client, agent=ctx.agent)
            except Exception as e:  # noqa: BLE001  the API or the network, not the photo: said once; the watchdog tries again
                check_errors.append(f"{type(e).__name__}: {e}")
                runner.record_error_once(ctx.conn, ctx.agent, "final_check",
                                         f"The final check could not run ({type(e).__name__}: {e}); nothing is drafted until it can.")
                continue
            if not (verdict and eligibility.is_eligible(ctx.conn, row["id"])[0]):
                continue
            if verdict.get("shot_type") in classify.SHOT_TYPES:
                row["shot_type"] = verdict["shot_type"]       # what the photo shows, by the model that looked at it in full
            if verdict.get("event_kind") in classify.KINDS and verdict["event_kind"] != "unknown":
                row["event_kind"] = verdict["event_kind"]     # and what kind of occasion, likewise
            if not picker.fits(row):
                continue                                      # the full look made it a portrait the look has no room for, or not of one person
        picker.take(row)
        chosen.append((row, data))
    if len(chosen) < NEEDS[design]:
        give_back_style(ctx.conn, style, last_style)      # no reel is made of these photos
    if not chosen:
        if check_errors:
            return f"the final check could not run for {day} ({check_errors[-1]})"
        return f"no photo passed the final check for {day} (tried {min(len(pool), MAX_TRIES)})"
    asked = design
    if len(chosen) < NEEDS[design]:
        design, chosen = fallback_for(day), chosen[:1]
    try:
        qid, art, line = make_draft(ctx, day, chosen, design, want=want, kind_used=kind_used, asked=asked, track=track, style=style,
                                    drafter=drafter, art_client=art_client, judge_client=judge_client, why=use_why(chosen[0][0], len(pool)),
                                    extra_meta={"source": "draft_now"} if extra else None,
                                    ping=(f"{ctx.cfg.brand_name}: the post you asked for, to approve",
                                          f"Drafted now, as you asked. Post now, follow the pace, or skip. Tap to see it.") if extra else None)
    except PhotosTaken as e:
        # said, and the watchdog's draft window tries the day again ("could not" is a passing reason)
        return f"the photos for {day} could not be kept: {e}; the day is drafted again"
    line += f"; {picker.words()}" if picker.words() else ""
    if art.get("verdict") == "reject":
        # the design did not work with these photos as arranged: make_draft kept a record of the try, the photos stay free
        # and this run draws the day again in another arrangement; no photo is ruled unfit (2026-11-08)
        if _depth + 1 >= MAX_TRIES:
            return f"{line}; the art director passed no arrangement for {day} in {MAX_TRIES} tries"
        return line + "; " + draft_one(ctx, fetch, now=now, check_client=check_client, drafter=drafter,
                                       art_client=art_client, judge_client=judge_client, extra=extra, _depth=_depth + 1)
    return line


def photo_file(cfg, row) -> Path:
    """Where a chosen photo's full-size copy lives: the file a phone send kept (agents/phone.py, its own file for
    good), else the cache of the Drive original (photos/<drive id>.img, swept after a week)."""
    if (row.get("source") or "drive") != "drive" and row.get("local_path"):
        return Path(row["local_path"])
    return cfg.data_root / "photos" / f"{row['drive_id']}.img"


def make_draft(ctx: runner.Context, day: date, chosen: list[tuple[dict, bytes]], design: str, *, want: str, kind_used: str,
               asked: str, track, drafter=None, art_client=None, judge_client=None, why: str = "", note: str = "",
               extra_meta: Optional[dict] = None, ping: Optional[tuple[str, str]] = None, quiet: bool = False,
               style: Optional[str] = None, reel_video: Optional[Path] = None,
               his_choice: bool = False) -> tuple[int, dict, str]:
    """One draft from photos already chosen and checked: the captions, the design, the art director, the queue row and
    the ping. (queue id, the art director's verdict, the run line). The daily draft (draft_one) and a photo sent from
    the phone (agents/phone.py) both end here. A draft the art director turned back is kept as a rejected row and said in
    the line, and its photos stay free (recent_use), so the day is drawn again in another arrangement. `his_choice`: the
    photos and the design are Chris's own (a send from his phone, Post this on a sample he chose, a reel he queued), so
    the art director's no is a note on the draft, never a turn-back (2026-11-08: his approval is final).
    `quiet`: no ping here; the caller pings (a photo from the share sheet is approved by his send, 2026-10-15).
    `style`: a reel's style or look, when the caller chose it before the photos (a look's photos follow its rule); else
    it is chosen here among those the photos allow. `reel_video`: a reel in a look rendered before (ccs queue-reel)."""
    for row, data in chosen:
        if (row.get("source") or "drive") != "drive":
            continue                        # a phone photo's own file is its copy for good; never the cache that is swept
        cache = ctx.cfg.data_root / "photos" / f"{row['drive_id']}.img"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists():
            cache.write_bytes(data)
        ctx.conn.execute("UPDATE photos SET local_path=? WHERE id=?", (str(cache), row["id"]))
    # never two frames of one moment on one post, by any road (2026-11-02): the later frame is left out, said in the line
    kept: list[tuple[dict, bytes]] = []
    left_out = [r["id"] for r, d in chosen if any(moments.same_moment(r, k) for k, _ in kept) or kept.append((r, d))]
    if left_out:
        chosen = kept
        if len(chosen) < NEEDS.get(design, 1):
            design, chosen = fallback_for(day), chosen[:1]
    hero = chosen[0][0]
    targets = list(TARGETS)            # every network he posts to: no model's look keeps a photo off one (2026-11-08)
    li_style = linkedin_style(ctx.conn) if "linkedin" in targets else ""   # his voice rotates (2026-11-01 evening)
    facts = claude.PostFacts(brand_name=ctx.cfg.brand_name, event_kind=hero.get("event_kind") or "unknown",
                             shot_type=hero.get("shot_type") or "", subject=hero["subject"],
                             quote_link=f"{ctx.cfg.brand_domain}/book" if ctx.cfg.brand_domain else "", note=note,
                             linkedin_style=li_style)
    drafter = drafter or (claude.TemplateDrafter() if ctx.dry_run else claude.get_drafter(ctx.conn, agent=ctx.agent))
    known_names = names.public_names(ctx.conn)
    plan = seo_plan.plan_for(subject=hero["subject"], event_kind=hero.get("event_kind"), shot_type=hero.get("shot_type"),
                             design=design)
    facts.plan = plan
    captions, alt, seo_record, writer = write_captions(drafter, facts, photo_file(ctx.cfg, hero), known_names, conn=ctx.conn,
                                                       agent=ctx.agent, judge_client=judge_client)
    captions = {n: t for n, t in captions.items() if n in targets}
    reports = {n: copy_rules.check(t, names=known_names, social=True, linkedin=n == "linkedin").as_dict() for n, t in captions.items()}
    images = {r["id"]: Image.open(io.BytesIO(d)) for r, d in chosen}
    out_dir = ctx.cfg.data_root / "renders" / "posts" / day.isoformat()
    seo = image_meta.for_photo(ctx.conn, hero)
    from .. import reel_lines
    from ..render import reel_looks
    look_plan = None
    if design == "reel":
        taken = [r for r, _ in chosen]
        rooms, supply = checked_rooms(ctx.conn, [r["id"] for r in taken]), reel_looks.Supply(ctx.conn)

        def makes(look: str) -> bool:
            return reel_looks.fits(look, taken, rooms=rooms, supply=supply)
        if style in reel_looks.LOOKS and reel_video is None and not makes(style):
            # the look chosen before its photos cannot be made of the ones that passed (too few confirmed rooms for its
            # words, too few fillers here): another style these photos allow, rather than a carousel
            style = None
        style = style or reel_style(ctx.conn, fits=makes)
        if style in reel_looks.LOOKS and reel_video is None:
            # a look takes a track that suits it and a set of lines, each the one the reels used least lately
            played = music.for_look(ctx.conn, style, lambda f: learner.track_weight(ctx.conn, f))
            if played is not None:
                look_plan, track = reel_looks.Plan(reel_lines.choose(ctx.conn, style), played), played.path
    else:
        style = None
    photo_ids = [r["id"] for r, _ in chosen]
    people = [c for r, _ in chosen for c in (r["credit"] or "").split()]
    # the networks the window holds are known before anything is drawn, so no card exists for a network the draft is not
    # going to (2026-11-02); the save checks the window again, in its own transaction, for a post made meanwhile
    held = held_on(ctx.conn, photo_ids, config.repeat_window(ctx.cfg), people, ctx.cfg.variety_days)
    render, reel_failed = make_renderer(ctx.conn, ctx.agent, design=design, rows=[r for r, _ in chosen], hero=hero, images=images,
                                        day=day, track=track, out_dir=out_dir, seo=seo, reel_style=style,
                                        aspects=aspects_for([n for n in targets if n not in held]), look_plan=look_plan,
                                        reel_video=reel_video)
    # a look's cover, its card and each frame its beat words are on (up to three); a 3D reel's cover, card and two stills
    pictures = 5 if style in reel_looks.LOOKS else 4
    render_paths, art = art_director.direct(ctx.conn, render, brief=lambda paths: brief_for(design, style, paths),
                                            dry_run=ctx.dry_run, client=art_client, agent=ctx.agent,
                                            allow_redo=design == "single", max_files=pictures)
    if reel_failed:
        design = "carousel"
    # the look and the track ride on the draft for the learner and the rotations (lines: the set of words it carried)
    reel_meta = ({"reel": style, "music": track.name, **({"lines": look_plan.lines} if look_plan else {}),
                  **({"reel_given": str(reel_video)} if reel_video else {})} if design == "reel" else {})
    if art.get("verdict") == "reject" and not his_choice:
        # the design did not work with these photos as arranged: a record of the try, the photos free for the next one
        now_r = db.utcnow()
        qid_r = db.insert(ctx.conn, "content_queue", kind="photo", photo_ids=json.dumps(photo_ids), targets=json.dumps(targets),
                          caption=json.dumps(captions), render_paths=json.dumps(render_paths), status="rejected",
                          last_error=f"Art director: {art.get('notes', '')}",
                          rule_report=json.dumps({"for_day": "turned back", "art": art, "subject": hero["subject"], "design": design,
                                                  **reel_meta, **(extra_meta or {})}),
                          created_at=now_r, updated_at=now_r)
        report.record_use(ctx.conn, "post", photo_ids, ref=f"post:{qid_r}")
        return qid_r, art, f"art director turned back photo {hero['id']}: {art.get('notes', '')}"
    meta = {"for_day": day.isoformat(), "subject": hero["subject"], "event": hero.get("convention_name") or "",
            "people": people, "model": writer, "rules": reports, "wanted": want, "art": art, "design": design,
            "design_wanted": asked, "seo": seo_record, "alt_text": alt, **reel_meta,
            **({"linkedin_style": li_style} if li_style else {}), **(extra_meta or {})}
    if reel_failed:
        meta["reel_failed"] = reel_failed[0]
    now_s = db.utcnow()
    # the save refuses a photo another post took while this one was being made (2026-10-16), in one write transaction so
    # no other process can slip a draft in between the look and the save
    began = not ctx.conn.in_transaction
    if began:
        ctx.conn.execute("BEGIN IMMEDIATE")
    try:
        # the window counts per network (Chris, 2026-11-02): the networks where a photo of this post, or a person on it, was on
        # another post inside the window drop off, with the reason on the draft page; held on every network that is on
        # (POST_NETWORKS), the photos are refused, since a post for switched-off networks alone goes nowhere
        held = held_on(ctx.conn, photo_ids, config.repeat_window(ctx.cfg), people, ctx.cfg.variety_days)
        going = [n for n in targets if n in payloads.posting_networks()] or targets
        targets = [n for n in targets if n not in held]
        if all(n in held for n in going):
            if began:
                ctx.conn.execute("ROLLBACK")
            first = next(iter(held.values()))
            raise PhotosTaken(first["photo"] or photo_ids[0], first["post"], f"{first['why']} (on every network this post was for)")
        if held:
            captions = {n: t for n, t in captions.items() if n in targets}
            meta["rules"] = {n: r for n, r in meta["rules"].items() if n in targets}
            meta["skipped"] = {**(meta.get("skipped") or {}), **{n: h["why"] for n, h in held.items()}}
        qid = db.insert(ctx.conn, "content_queue", kind="photo", photo_ids=json.dumps(photo_ids), targets=json.dumps(targets),
                        caption=json.dumps(captions), render_paths=json.dumps(render_paths), rule_report=json.dumps(meta),
                        created_at=now_s, updated_at=now_s)
        # the rotation's memory: every photo on this draft was used now (a dry-run draft too: approved in dry run, it goes
        # out when the lane is switched live), so the site, the samples and later drafts reach for the others first. The
        # moment is record_use's, to the microsecond like every surface's: the queue row's whole second sorted before a
        # site use made in the same second, and the fresh photo came round again (CI, 2026-10-25)
        report.record_use(ctx.conn, "post", photo_ids, ref=f"post:{qid}")
        if began:
            ctx.conn.execute("COMMIT")
    except BaseException:
        # 2026-11-09 audit: an error in here left the write transaction open, so the run's own error row and its
        # finish were lost when the connection closed and the run read as still going
        if began and ctx.conn.in_transaction:
            ctx.conn.execute("ROLLBACK")
        raise
    # the ping that opens the draft (Chris, 2026-10-11: "I haven't received any ntfy"); 2026-10-13: it carries the
    # card, and an Approve button when the art director passed the draft (core/approve_token: signed, single use)
    title, message = ping or ping_words(ctx.cfg.brand_name, design, len(photo_ids), f"{day:%A}", designed=False)
    if not quiet:
        notify.push(title, message, dry_run=ctx.dry_run, priority="default", click=ping_click(qid, design), conn=ctx.conn,
                    agent=ctx.agent, **ping_extras(ctx.conn, {"id": qid, "updated_at": now_s}, art))
    fell = (f", the reel could not be made ({reel_failed[0]})" if reel_failed
            else f", {asked} wanted but too few photos passed" if asked != design else "")
    fell += f", LinkedIn {linkedin.STYLE_WORDS[li_style]}" if li_style else ""
    fell += f", held off {' and '.join(payloads.name_of(n) for n in held)}" if held else ""
    fell += f", left out photo {' and '.join(str(p) for p in left_out)} (the same moment as another on this post)" if left_out else ""
    line = (f"{'DRY RUN ' if ctx.dry_run else ''}drafted post #{qid} for {day} ({kind_used}"
            f"{', instead of ' + want if kind_used != want else ''}): {design} with {len(photo_ids)} photo(s){fell}, "
            f"photo {hero['id']} first{' (' + why + ')' if why else ''}, captions by {writer} for \"{plan.primary}\", "
            f"art director: {art.get('verdict')}")
    return qid, art, line


def queue_reel(ctx: runner.Context, fetch: Callable[[dict], bytes], *, video: Path, look: str, photo_ids: list[int], day: date,
               track_file: str, quiet: bool = False, check_client=None, drafter=None, art_client=None,
               judge_client=None) -> tuple[Optional[int], str]:
    """A reel in one of the ten looks, rendered before, queued as the post for `day` on the daily draft's road (`ccs
    queue-reel`). Chris, 2026-11-08, of the ten finished preview reels: "You can use those as posts. The images were
    fine". Its photos (in order, the hero first) are read and checked as the daily draft checks the photos it picks (a
    candidate; live, Claude's final check and the eligibility after it): a photo that fails stops it, said why, and
    nothing is queued. Then make_draft with the reel as given: its cover and the stills cut from the look's own frames,
    the 2:3 card and the LinkedIn photo as every reel has them, the art director told the look, the repeat window and
    the rotation's record as for any post. (queue id or None, the line.)"""
    from ..render import reel_looks
    from .sample import PHOTO_SQL
    if look not in reel_looks.LOOKS:
        return None, f"not queued: no reel look {look!r} (one of {', '.join(reel_looks.LOOKS)})"
    if not Path(video).is_file() or Path(video).stat().st_size == 0:
        return None, f"not queued: no reel at {video}"
    if already_drafted(ctx.conn, day):
        return None, f"not queued: a post for {day} is already drafted"
    t = db.one(ctx.conn, "SELECT * FROM music_tracks WHERE file=?", (track_file,))
    if t is None or not music.usable(t):
        return None, f"not queued: no music track {track_file!r} with its record and its file here (the Music page)"
    if not photo_ids:
        return None, "not queued: name the reel's photos, the hero first"
    lock = drafting_lock(DRAFTING_WAIT)
    if lock is None:
        return None, "not queued: another draft was being made for 15 minutes; try again"
    try:
        chosen: list[tuple[dict, bytes]] = []
        for pid in photo_ids:
            row = db.one(ctx.conn, PHOTO_SQL, (pid,))
            if row is None:
                return None, f"not queued: photo {pid} is not in the library"
            ok, why = eligibility.is_candidate(ctx.conn, pid)
            if not ok:
                return None, f"not queued: photo {pid} is {why}"
            row = {**dict(row), "credit": eligibility.credit_line(ctx.conn, pid), "last_use": None}
            try:
                data = fetch(row)
                verdict = None if ctx.dry_run else classify.final_check(ctx.conn, pid, data, client=check_client, agent=ctx.agent)
            except Exception as e:  # noqa: BLE001  Drive, the disk or the API, not the photo: said, nothing queued
                return None, f"not queued: photo {pid} could not be read or checked ({type(e).__name__}: {e})"
            if not ctx.dry_run:
                if verdict is None:
                    return None, f"not queued: Claude could not look at photo {pid} (no key, or the monthly cap)"
                ok, why = eligibility.is_eligible(ctx.conn, pid)
                if not ok:
                    return None, f"not queued: photo {pid} cannot be posted: {why}"
                if verdict.get("shot_type") in classify.SHOT_TYPES:
                    row["shot_type"] = verdict["shot_type"]
                if verdict.get("event_kind") in classify.KINDS and verdict["event_kind"] != "unknown":
                    row["event_kind"] = verdict["event_kind"]
            chosen.append((row, data))
        qid, art, line = make_draft(ctx, day, chosen, "reel", want=subject_for(day), kind_used="event", asked="reel",
                                    track=music.folder() / track_file, drafter=drafter, art_client=art_client,
                                    judge_client=judge_client, why=f"queued from {Path(video).name}", style=look,
                                    reel_video=Path(video), quiet=quiet, his_choice=True)
    except PhotosTaken as e:
        return None, f"not queued: {e}"
    finally:
        lock.release()
    return qid, line


def ping_words(brand: str, design: str, n: int, when: str, *, designed: bool) -> tuple[str, str]:
    """The draft ping's title and line. Chris, 2026-10-23: a reel's ping says it is a reel (its picture is only the
    cover, and it looked like a still)."""
    what = "A single photo post" if design == "single" else f"A {design} on {n} of your photos"
    made = f"{what}, made for today" if designed else f"{what} for {when}"
    if design == "reel":
        return (f"Reel: {brand}, {'a designed reel' if designed else 'a reel'} to approve",
                f"{made}. Post now, follow the pace or skip. Tap to watch it; one more tap for the sound.")
    return (f"{brand}: {'a designed post' if designed else 'a post'} to approve", f"{made}. Post now, follow the pace or skip. Tap to see it.")


def ping_click(qid: int, design: str) -> str:
    """Where the ping opens: a reel opens on its draft already playing (silent; phones allow sound only after a tap)."""
    return notify.link(f"/queue/{qid}?play=1" if design == "reel" else f"/queue/{qid}")


def ping_extras(conn: sqlite3.Connection, row, art: Optional[dict]) -> dict:
    """What a draft's ping carries besides the words: the card (fetched by the phone from the dashboard with the
    token's card key, no login; a reel's own cover), and his three choices when the art director passed it (2026-10-15:
    Post now, Follow the pace, Skip); Open and Skip otherwise, so he looks himself before anything can go out."""
    token = approve_token.issue(conn, row)
    passed = (art or {}).get("verdict") == "pass"
    return {"actions": notify.choice_actions(row["id"], token) if passed else notify.look_actions(row["id"], token),
            "attach": notify.card_link(row, token), "filename": f"post-{row['id']}.jpg"}


def read_photo(cfg, row, download: Callable[[str], bytes]) -> bytes:
    """The full-size photo: the file a phone send kept, else the cache of the Drive original, else Drive."""
    own = photo_file(cfg, row)
    if own.exists():
        return own.read_bytes()
    return download(row["drive_id"])


def run(ctx: runner.Context, fetch: Optional[Callable[[dict], bytes]] = None) -> str:
    summary, mended = None, 0
    if fetch is None:
        from ..drive import oauth
        from ..drive.api import DriveReader
        try:
            oauth.access_token(ctx.conn)   # fail the run now if the sign-in is dead, not photo by photo
            reader = DriveReader(lambda: oauth.access_token(ctx.conn), conn=ctx.conn, agent=ctx.agent)
        except oauth.DriveAuthError as e:
            runner.record_error_once(ctx.conn, ctx.agent, "drive_auth", str(e))
            summary = f"not signed in: {e}"          # a no-draft morning like any other: said below, tried again
        else:
            def fetch(row):
                return read_photo(ctx.cfg, row, reader.download)
    if summary is None:
        mended = 0 if ctx.dry_run else mend_queue(ctx.conn, agent=ctx.agent)
        lock = drafting_lock(DRAFTING_WAIT)             # a designed draft or Post this being made finishes first
        if lock is None:
            summary = "could not start: another draft was being made for 15 minutes; tried again within the hour"
        else:
            try:
                if draft_now_asked(ctx.conn):
                    # Draft now (2026-10-31): one more post for the day, then nothing else this run; the day's own
                    # bookkeeping (the watchdog's draft window, the no-draft ping) belongs to the morning run
                    settings.set(ctx.conn, DRAFT_NOW_KEY, "")
                    return (f"rewrote the captions of {mended} queued draft(s) that broke a rule; " if mended else "") + \
                        "Draft now: " + draft_one(ctx, fetch, extra=True)
                summary = draft_one(ctx, fetch)
            finally:
                lock.release()
    day = target_day(ctx.cfg)
    # what this run found, for the watchdog's draft window (2026-10-13): a reason that was passing, or inputs that
    # changed since, mean another try inside the day; the same reason on the same inputs means waiting
    settings.set(ctx.conn, LAST_ATTEMPT_KEY, json.dumps({
        "day": day.isoformat(), "at": db.utcnow(), "summary": summary[:300], "fingerprint": inputs_fingerprint(ctx.conn),
        "transient": any(w in summary for w in TRANSIENT_WORDS)}))
    if "drafted post" not in summary and "already drafted" not in summary:
        # 2026-10-12: "the render didn't land this morning at 8am". A morning with no draft is said out loud, with
        # the reason, on the phone and on the Agents page; never a quiet summary line. The phone hears each
        # reason once a day; the Agents page keeps the line.
        from ..ai import spend
        why = summary + ("; the monthly AI cap is reached (Keys page, AI)" if spend.cap_reached(ctx.conn) else "")
        runner.record_error_once(ctx.conn, ctx.agent, "no_draft", f"No post was drafted for {day}: {why}")
        key = f"{day.isoformat()}|{why}"
        if settings.get(ctx.conn, NO_DRAFT_PINGED_KEY) != key:
            notify.push(f"{ctx.cfg.brand_name}: no post drafted for {day:%A}", why, dry_run=ctx.dry_run, click=notify.link("/agents"),
                        conn=ctx.conn, agent=ctx.agent)
            settings.set(ctx.conn, NO_DRAFT_PINGED_KEY, key)
    return (f"rewrote the captions of {mended} queued draft(s) that broke a rule; " if mended else "") + summary


if __name__ == "__main__":
    runner.main_for("content", run)
