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
   looks once more; a photo that fails is skipped and the next one is tried.
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

from ..ai import claude, copy_rules, names, seo_plan
from ..core import approve_token, config, db, notify, runner, settings
from ..library import classify, eligibility, report

from . import art_director, learner
from .. import music
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
    """A photo chosen for this draft went into another post while this one was being made."""

    def __init__(self, photo: int, post: int):
        super().__init__(f"photo {photo} went into post #{post} while this one was being drafted")
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


def photo_holder(conn: sqlite3.Connection, photo_ids, days: int) -> Optional[tuple[int, int]]:
    """(photo id, post id) when one of these photos is on another post inside the window, by the same rule as
    recent_use (open, sent, turned back by the art director or set aside by the do-not-use list; a skipped one is not)."""
    wanted = {int(p) for p in photo_ids}
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    for r in db.rows(conn, "SELECT id, status, photo_ids, rule_report FROM content_queue WHERE created_at >= ? AND "
                           "(status != 'rejected' OR rule_report LIKE '%\"verdict\": \"reject\"%' "
                           "OR rule_report LIKE '%\"rejected_by\"%') ORDER BY id", (since,)):
        if r["status"] == "rejected" and f'"rejected_by": "{SKIPPED}"' in (r["rule_report"] or ""):
            continue
        hit = wanted & {int(p) for p in json.loads(r["photo_ids"] or "[]")}
        if hit:
            return min(hit), r["id"]
    return None


def recent_use(conn: sqlite3.Connection, days: int) -> tuple[set, set, set]:
    """(photo ids, event names, credited people) used by posts drafted inside the window, by any road (the daily
    draft, a designed draft, Post this, the phone): every post not rejected, the ones the art director turned back,
    and the photos of the ones set aside by the do-not-use list (`rule_report.rejected_by`; the event and the people
    of a set-aside post are not "used", since nothing of it aired). A post Chris skipped is not counted at all
    (2026-10-15: "Skip puts the photos back in rotation"): its photos come round again, after the others, since
    their use stays on the rotation's record (library/report.photo_use)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    photos, events, people = set(), set(), set()
    for r in db.rows(conn, "SELECT status, photo_ids, rule_report FROM content_queue WHERE created_at >= ? AND "
                           "(status != 'rejected' OR rule_report LIKE '%\"verdict\": \"reject\"%' "
                           "OR rule_report LIKE '%\"rejected_by\"%')", (since,)):
        if r["status"] == "rejected" and f'"rejected_by": "{SKIPPED}"' in (r["rule_report"] or ""):
            continue
        photos.update(int(p) for p in json.loads(r["photo_ids"] or "[]"))
        if r["status"] == "rejected" and '"verdict": "reject"' not in (r["rule_report"] or ""):
            continue                       # set aside: the photo sits out; the event and the people were never shown
        meta = json.loads(r["rule_report"] or "{}")
        if meta.get("event"):
            events.add(meta["event"].lower())
        people.update(x.lower() for x in meta.get("people") or [])
    return copies(conn, photos), events, people


def copies(conn: sqlite3.Connection, photo_ids: set) -> set:
    """The ids with every identical copy of each added (same md5): a picture that went out went out, whichever of
    its files was on the post (2026-10-26)."""
    out = set(photo_ids)
    ids = sorted(photo_ids)
    for k in range(0, len(ids), 500):
        marks = ",".join("?" * len(ids[k:k + 500]))
        out.update(r["id"] for r in db.rows(conn, f"SELECT id FROM photos WHERE trashed = 0 AND md5 IS NOT NULL AND md5 IN "
                                                  f"(SELECT md5 FROM photos WHERE id IN ({marks}))", ids[k:k + 500]))
    return out


def candidates(conn: sqlite3.Connection, subject: str) -> list[dict]:
    cfg = config.get_config()
    used_photos, _, _ = recent_use(conn, config.repeat_window(cfg))
    _, used_events, used_people = recent_use(conn, cfg.variety_days)
    rows = db.rows(conn, """SELECT p.*, c.subject, c.convention_name, c.event_kind, c.shot_type, c.quality, c.people_count, c.summary
                            FROM photos p JOIN classifications c ON c.photo_id = p.id
                            WHERE p.trashed = 0 AND c.subject = ? AND c.method IN ('ollama','vision')
                            ORDER BY COALESCE(c.quality,0) DESC, COALESCE(c.people_count,0) DESC, p.id""", (subject,))
    fresh, lately = [], []
    for r in rows:
        if r["id"] in used_photos or not eligibility.is_candidate(conn, r["id"])[0]:
            continue
        credit = eligibility.credit_line(conn, r["id"])
        if any(c.lower() in used_people for c in credit.split()):
            continue
        # an event a post had inside VARIETY_DAYS comes after every other event, not never: the designed drafts' rule
        # (2026-10-15, "while one is left"), now the daily draft's too. 2026-10-26: 1,481 of the 1,796 approved event
        # photos are one event, so the wall here left six candidates and the same six on every draft.
        shown = subject == "event" and bool(r["convention_name"]) and r["convention_name"].lower() in used_events
        (lately if shown else fresh).append({**dict(r), "credit": credit})
    # what the learner found works, inside the founder's bounds
    def score(r):
        return -(r.get("quality") or 0) * learner.weight_for(conn, r.get("shot_type"), r.get("event_kind"))
    # then the rotation (2026-10-14, "the same photos for everything"): the least recently used photo first, on any
    # surface, so every approved photo gets its turn; the score above only breaks ties, and equal photos come by chance
    last = report.last_uses(conn)

    def in_turn(group: list[dict]) -> list[dict]:
        group.sort(key=score)
        for r in group:
            r["last_use"] = last.get(r["id"])
        return report.rotate(conn, group, last=last, alike=score)
    return in_turn(fresh) + in_turn(lately)


def use_why(hero: dict, ready: int) -> str:
    """Why this photo led, for the run line on the Agents page: its last use, and how many were ready."""
    when = f"last used {hero['last_use'][:10]}" if hero.get("last_use") else "never used before"
    return f"{when}; {ready} ready, least recently used first"


def write_captions(drafter, facts: claude.PostFacts, photo: Path, known_names, *, conn=None,
                   agent: str = "content") -> tuple[dict, str, dict, str]:
    """(captions, alt text, what happened, who wrote them). Chris, 2026-10-11: "Make sure the captions are SEO
    optimized painstakingly". The writer gets the post's search plan (ai/seo_plan.py); the hashtags and the
    link are put in place for it; a draft that misses the plan or breaks a rule is written once more with
    the misses named, and after a second miss the template, which meets the plan by construction, stands in.
    A writer that cannot write at all (the cap, a refusal, the API, the network) is the same: the template
    writes, and with `conn` the reason is recorded once (2026-10-13: never a dead run)."""
    plan, link = facts.plan, facts.quote_link
    tries, notes, draft, caps, misses, writer_error = [], (), None, {}, [], ""
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
        misses = seo_plan.problems(caps, plan) + [f"the {n} caption {b.message}" for n, t in caps.items()
                                                  for b in copy_rules.check(t, names=known_names, social=True).blocks]
        tries.append({"by": draft.model, "missed": misses})
        if not misses or draft.model == "template":
            break
        notes = misses
    writer = draft.model if draft is not None else "template"
    if misses:
        caps, writer = seo_plan.template_captions(plan, link, facts.brand_name), "template"
    from ..seo.photo_text import SHOT_WORDS
    alt = draft.alt_text if draft is not None else ""
    if not alt or len(alt) > 125 or not copy_rules.check(alt, names=known_names, social=True).ok:
        alt = seo_plan.alt_text(plan, SHOT_WORDS.get(facts.shot_type, ""), facts.brand_name)
    record = {"primary": plan.primary, "related": list(plan.related), "hashtags": list(plan.hashtags), "area": plan.area,
              "tries": tries, "fell_back": bool(misses)}
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
    broken = {n: [b.message for b in copy_rules.check(t, official=official, names=known_names, social=True).blocks]
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
                             quote_link=f"{cfg.brand_domain}/book" if cfg.brand_domain else "")
    facts.plan = seo_plan.plan_for(subject=subject, event_kind=facts.event_kind, shot_type=facts.shot_type, design=design)
    photo = Path(hero["local_path"]) if hero and hero["local_path"] else (cfg.data_root / "photos" / f"{hero['drive_id']}.img" if hero else None)
    if drafter is None:
        # the writer looks at the photo; without a copy of it here the template, which cannot miss, writes
        drafter = claude.get_drafter(conn, agent=agent) if photo is not None and photo.exists() else claude.TemplateDrafter()
    # the cap, a refusal, the API: the template stands in and the record says so (write_captions)
    fixed, alt, record, writer = write_captions(drafter, facts, photo or Path("none"), known_names, conn=conn, agent=agent)
    fixed = {n: t for n, t in fixed.items() if n in captions}      # a network the draft never had (LinkedIn skipped) stays out
    reports = {n: copy_rules.check(t, names=known_names, social=True).as_dict() for n, t in fixed.items()}
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


def reel_style(conn: sqlite3.Connection, rng=None) -> str:
    """One of the five 3D styles at random, never the one the last reel had (Chris, 2026-10-23: "there should be 5
    different style reels (all very different)", used randomly). The rooms reel of before is out of the rotation.
    Chosen and recorded in one write under the database's write lock: the daily and the designed lane run under
    different locks and a render takes minutes, so two reels that each read "the last reel's row" and wrote their own
    after the render could come out the same (2026-10-24 audit). A reel the art director turns back was the last too."""
    from ..render import reels3d
    conn.execute("BEGIN IMMEDIATE")
    try:
        style = reels3d.next_style(settings.get(conn, REEL_STYLE_KEY), rng)
        settings.set(conn, REEL_STYLE_KEY, style)
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


def confirmed_rooms(conn: sqlite3.Connection, photo_ids: list) -> dict:
    """{photo id: (room, line)}: the room Claude's final check of the full photo says it plainly shows, else
    EVENT PHOTOGRAPHY (2026-10-15: the sorter's shot type had put "After Dark" on a sunny garden). A photo with no
    final check (a dry run) or one checked before the question was asked names no room."""
    from ..render import design_samples
    got = {}
    ids = [int(i) for i in photo_ids]
    if ids:
        marks = ",".join("?" * len(ids))
        got = {r["photo_id"]: r["room"] for r in db.rows(conn, f"SELECT photo_id, room FROM final_checks WHERE photo_id IN ({marks})", ids)}
    return {i: design_samples.ROOM_WORDS.get(got.get(i) or "", design_samples.UNCONFIRMED) for i in ids}


def shot_for(row: dict, image: Image.Image, focus=(0.5, 0.45), words: Optional[tuple] = None):
    """The photo with the room and line printed on it: `words` from confirmed_rooms; without them nothing is named."""
    from ..render import design_samples, motion
    room, line = words or design_samples.UNCONFIRMED
    if room == "THE VENUE" and row.get("shot_type") == "building_exterior":
        line = design_samples.ROOMS["building_exterior"][1]
    return motion.Shot(image, room, line, focus)


def middle_first(items: list, hero) -> list:
    """The hero in the middle of the rest, where the fan and the rail put the eye."""
    rest = [x for x in items if x is not hero]
    k = len(rest) // 2
    return rest[:k] + [hero] + rest[k:]


def make_renderer(conn: sqlite3.Connection, agent: str, *, design: str, rows: list, hero: dict, images: dict, day: date,
                  track, out_dir: Path, seo, reel_style: Optional[str] = None, linkedin: bool = True) -> tuple[Callable[[tuple], dict], list]:
    """The day's design on its photos, as `render(focus) -> {aspect: [paths]}` for the art director, and the
    list a failed reel is written to (the same photos then go out as a carousel). Shared by the fresh draft
    and the mend, so a redrawn card is the same card the day would have made. `linkedin` False: no LinkedIn card
    (the hero's main subject is a recognisable public figure, 2026-11-01)."""
    from ..render import bold, design_samples, motion, reels3d
    words = confirmed_rooms(conn, [r["id"] for r in rows])
    kicker = kicker_for(hero).upper()
    if kicker == words[hero["id"]][0] or words[hero["id"]] == design_samples.UNCONFIRMED:
        # the small line never repeats the title under it: no room confirmed, the title is EVENT PHOTOGRAPHY and the small
        # line EVENT CALIBER (2026-10-15; "CONFERENCE PHOTOGRAPHY" over "EVENT PHOTOGRAPHY" was a near repeat)
        kicker = "EVENT CALIBER"
    copy = motion.MotionCopy(kicker=kicker)
    tag = f"{hero['id']}-{design}"
    reel_failed: list[str] = []
    # every design carries the hero alone on the single card twice over: at 2:3 for Pinterest and at 4:5 for LinkedIn
    # (render_paths "linkedin"; 2026-11-01, one photo per post there)
    hero_cards = ("2:3", motion.LINKEDIN_CARD) if linkedin else ("2:3",)
    card_aspect = {motion.LINKEDIN_CARD: "4:5"}

    def single(focus, cards=("4:5", *hero_cards)):
        shot = shot_for(hero, images[hero["id"]], focus, words[hero["id"]])
        return {c: [str(motion.single_post(shot, copy, out=out_dir / f"{tag}-{c.replace(':', '')}.jpg", aspect=card_aspect.get(c, c),
                                           kicker=kicker, meta=seo))] for c in cards}

    def render(focus):
        if design == "single":
            return single(focus)
        shots = [shot_for(r, images[r["id"]], words=words[r["id"]]) for r in rows]
        if design in bold.DESIGNS:
            # the four bold designs (2026-10-15), each with its own 2:3 card for Pinterest; the hero first, the photos whole
            return {**{a: [str(bold.post(design, shots, copy, out=out_dir / f"{tag}-{a.replace(':', '')}.jpg", aspect=a, meta=seo))]
                       for a in ("4:5", "2:3")}, **(single(focus, (motion.LINKEDIN_CARD,)) if linkedin else {})}
        if design == "reel" and not reel_failed:
            # Instagram and Facebook get the reel (render_paths "9:16"), with its cover; Pinterest the
            # hero as a 2:3 card and LinkedIn the hero still; the art director looks at the cover and the stills, never the mp4
            try:
                grid = reels3d.fillers(conn, exclude=[r["id"] for r in rows])
                video = reels3d.render(reel_style, shots, out=out_dir / f"{tag}-{reel_style}.mp4", audio=track, grid=grid)
                stills = reels3d.stills(reel_style, video, out_dir=out_dir / f"{tag}-stills", meta=seo)
            except Exception as e:  # noqa: BLE001  a reel that cannot be made leaves a carousel of the same photos, said why
                reel_failed.append(f"{type(e).__name__}: {e}")
                runner.record_error(conn, agent, "reel", f"the {reel_style} reel for {day} was not made: {e}")
            else:
                return {"9:16": [str(video)], "cover": [str(stills[0])], **single(focus, hero_cards),
                        "stills": [str(p) for p in stills[1:]]}
        # every design carries the hero as a 2:3 card for Pinterest (2026-10-13: without one the publisher fell back
        # to the photo's own .img copy, which it refuses, and the whole post failed on every network)
        if design in ("carousel", "reel"):        # the reel's fallback takes the same 4 to 6 photos
            return {"4:5": [str(p) for p in motion.carousel(shots, copy, out_dir=out_dir / tag, meta=seo)], **single(focus, hero_cards)}
        ordered = middle_first(shots, shots[0])
        mid = ordered.index(shots[0])
        if design == "fan":
            return {"4:5": [str(motion.fan_post(ordered, copy, out=out_dir / f"{tag}.jpg", focus=mid, meta=seo))],
                    **single(focus, hero_cards)}
        return {"4:5": [str(motion.spotlight_post(ordered, copy, out=out_dir / f"{tag}.jpg", index=mid, meta=seo))],
                **single(focus, hero_cards)}

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
    style puts on the frame on purpose (reels3d.brief); a reel that could not be made is the carousel it fell back to."""
    from ..render import bold, reels3d
    if design == "reel":
        if "9:16" in paths:
            return reels3d.brief(style)
        design = "carousel"
    if design in bold.DESIGNS:
        return f"The {design} design, {bold.DESIGNS[design].what}, at 4:5 and at 2:3."
    return BRIEFS[design]


def redraw(conn: sqlite3.Connection, row, meta: dict, *, agent: str = "content") -> tuple[Optional[dict], str]:
    """The card of a queued draft drawn again with today's design copy, from the copies of its photos on
    this machine (the cards from before 2026-10-11 said "coverage", a word a card no longer carries).
    (new render_paths, note); None when a photo copy is missing, and the old card stays, said so."""
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
    from ..render import reels3d
    style = meta["reel"] if meta.get("reel") in reels3d.STYLES else (reel_style(conn) if design == "reel" else None)
    out_dir = cfg.data_root / "renders" / "posts" / day.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    render, reel_failed = make_renderer(conn, agent, design=design, rows=rows, hero=hero, images=images, day=day, track=track,
                                        out_dir=out_dir, seo=image_meta.for_photo(conn, hero), reel_style=style,
                                        linkedin=not hero.get("public_figure"))
    art = meta.get("art") or {}
    focus = tuple(art["focus"]) if isinstance(art.get("focus"), list) and len(art["focus"]) == 2 else (0.5, 0.42)
    paths = render(focus)
    if design == "reel":
        meta["music"] = track.name if track else None       # the track this reel carries, named under its player
        meta["reel"] = style
    if reel_failed:
        meta["design"], meta["reel_failed"] = "carousel", reel_failed[0]
    return paths, "card drawn again with today's words"


def draft_one(ctx: runner.Context, fetch: Callable[[dict], bytes], *, now: Optional[datetime] = None,
              check_client=None, drafter=None, art_client=None, figure_client=None, extra: bool = False, _depth: int = 0) -> str:
    """`extra`: one more post for the day, asked for with Draft now (2026-10-31); it skips the one-a-day gate and is
    marked so it never counts as the day's post."""
    from ..render import motion
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
        return f"no photo ready for {day}: clear folders on the Library page (nothing drafted)"
    track = music.current(ctx.conn)
    design = design_for(day, kind_used, track is not None)
    pool = order_pool(pool, design)
    chosen: list[tuple[dict, bytes]] = []
    check_errors: list[str] = []
    for row in pool[:TAKES[design] + MAX_TRIES - 1]:
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
        chosen.append((row, data))
        if len(chosen) >= TAKES[design]:
            break
    if not chosen:
        if check_errors:
            return f"the final check could not run for {day} ({check_errors[-1]})"
        return f"no photo passed the final check for {day} (tried {min(len(pool), MAX_TRIES)})"
    asked = design
    if len(chosen) < NEEDS[design]:
        design, chosen = fallback_for(day), chosen[:1]
    try:
        qid, art, line = make_draft(ctx, day, chosen, design, want=want, kind_used=kind_used, asked=asked, track=track,
                                    drafter=drafter, art_client=art_client, figure_client=figure_client, why=use_why(chosen[0][0], len(pool)),
                                    extra_meta={"source": "draft_now"} if extra else None,
                                    ping=(f"{ctx.cfg.brand_name}: the post you asked for, to approve",
                                          f"Drafted now, as you asked. Post now, follow the pace, or skip. Tap to see it.") if extra else None)
    except PhotosTaken as e:
        # said, and the watchdog's draft window tries the day again ("could not" is a passing reason)
        return f"the photos for {day} could not be kept: {e}; the day is drafted again"
    if art.get("verdict") == "reject":
        # the photos do not hold up: they sit out like used ones (make_draft kept the row), and this run drafts again
        if _depth + 1 >= MAX_TRIES:
            return f"{line}; no photo passed for {day} after {MAX_TRIES} tries"
        return line + "; " + draft_one(ctx, fetch, now=now, check_client=check_client, drafter=drafter,
                                       art_client=art_client, figure_client=figure_client, extra=extra, _depth=_depth + 1)
    return line


def photo_file(cfg, row) -> Path:
    """Where a chosen photo's full-size copy lives: the file a phone send kept (agents/phone.py, its own file for
    good), else the cache of the Drive original (photos/<drive id>.img, swept after a week)."""
    if (row.get("source") or "drive") != "drive" and row.get("local_path"):
        return Path(row["local_path"])
    return cfg.data_root / "photos" / f"{row['drive_id']}.img"


def make_draft(ctx: runner.Context, day: date, chosen: list[tuple[dict, bytes]], design: str, *, want: str, kind_used: str,
               asked: str, track, drafter=None, art_client=None, figure_client=None, why: str = "", note: str = "",
               extra_meta: Optional[dict] = None, ping: Optional[tuple[str, str]] = None, quiet: bool = False) -> tuple[int, dict, str]:
    """One draft from photos already chosen and checked: the captions, the design, the art director, the queue row and
    the ping. (queue id, the art director's verdict, the run line). The daily draft (draft_one) and a photo sent from
    the phone (agents/phone.py) both end here. A turned-back draft is kept as a rejected row and said in the line.
    `quiet`: no ping here; the caller pings (a photo from the share sheet is approved by his send, 2026-10-15)."""
    for row, data in chosen:
        if (row.get("source") or "drive") != "drive":
            continue                        # a phone photo's own file is its copy for good; never the cache that is swept
        cache = ctx.cfg.data_root / "photos" / f"{row['drive_id']}.img"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists():
            cache.write_bytes(data)
        ctx.conn.execute("UPDATE photos SET local_path=? WHERE id=?", (str(cache), row["id"]))
    hero = chosen[0][0]
    # Chris, 2026-11-01: LinkedIn posts avoid photos whose main subject is a recognisable public figure. The art director judges
    # the hero once (stored on the photo; none in a dry run): judged so, the draft has no LinkedIn caption, card or tick, and
    # the draft page says why. Not judged yet: the publisher holds LinkedIn until it is (publisher.linkedin_hold).
    figure = None if ctx.dry_run else art_director.public_figure(ctx.conn, hero["id"], chosen[0][1], client=figure_client, agent=ctx.agent)
    targets = [n for n in TARGETS if not (n == "linkedin" and figure)]
    skipped = {"linkedin": art_director.FIGURE_SKIP} if figure else {}
    facts = claude.PostFacts(brand_name=ctx.cfg.brand_name, event_kind=hero.get("event_kind") or "unknown",
                             shot_type=hero.get("shot_type") or "", subject=hero["subject"],
                             quote_link=f"{ctx.cfg.brand_domain}/book" if ctx.cfg.brand_domain else "", note=note)
    drafter = drafter or (claude.TemplateDrafter() if ctx.dry_run else claude.get_drafter(ctx.conn, agent=ctx.agent))
    known_names = names.public_names(ctx.conn)
    plan = seo_plan.plan_for(subject=hero["subject"], event_kind=hero.get("event_kind"), shot_type=hero.get("shot_type"),
                             design=design)
    facts.plan = plan
    captions, alt, seo_record, writer = write_captions(drafter, facts, photo_file(ctx.cfg, hero), known_names, conn=ctx.conn,
                                                       agent=ctx.agent)
    captions = {n: t for n, t in captions.items() if n in targets}
    reports = {n: copy_rules.check(t, names=known_names, social=True).as_dict() for n, t in captions.items()}
    images = {r["id"]: Image.open(io.BytesIO(d)) for r, d in chosen}
    out_dir = ctx.cfg.data_root / "renders" / "posts" / day.isoformat()
    seo = image_meta.for_photo(ctx.conn, hero)
    style = reel_style(ctx.conn) if design == "reel" else None
    render, reel_failed = make_renderer(ctx.conn, ctx.agent, design=design, rows=[r for r, _ in chosen], hero=hero, images=images,
                                        day=day, track=track, out_dir=out_dir, seo=seo, reel_style=style, linkedin="linkedin" in targets)
    render_paths, art = art_director.direct(ctx.conn, render, brief=lambda paths: brief_for(design, style, paths),
                                            dry_run=ctx.dry_run, client=art_client, agent=ctx.agent,
                                            allow_redo=design == "single", max_files=4)
    if reel_failed:
        design = "carousel"
    photo_ids = [r["id"] for r, _ in chosen]
    reel_meta = {"reel": style, "music": track.name} if design == "reel" else {}
    if art.get("verdict") == "reject":
        # the photos do not hold up: they sit out like used ones
        now_r = db.utcnow()
        qid_r = db.insert(ctx.conn, "content_queue", kind="photo", photo_ids=json.dumps(photo_ids), targets=json.dumps(targets),
                          caption=json.dumps(captions), render_paths=json.dumps(render_paths), status="rejected",
                          last_error=f"Art director: {art.get('notes', '')}",
                          rule_report=json.dumps({"for_day": "turned back", "art": art, "subject": hero["subject"], "design": design,
                                                  **reel_meta, **({"skipped": skipped} if skipped else {}), **(extra_meta or {})}),
                          created_at=now_r, updated_at=now_r)
        report.record_use(ctx.conn, "post", photo_ids, ref=f"post:{qid_r}")
        return qid_r, art, f"art director turned back photo {hero['id']}: {art.get('notes', '')}"
    people = [c for r, _ in chosen for c in (r["credit"] or "").split()]
    meta = {"for_day": day.isoformat(), "subject": hero["subject"], "event": hero.get("convention_name") or "",
            "people": people, "model": writer, "rules": reports, "wanted": want, "art": art, "design": design,
            "design_wanted": asked, "seo": seo_record, "alt_text": alt, **reel_meta, **({"skipped": skipped} if skipped else {}),
            **(extra_meta or {})}
    if reel_failed:
        meta["reel_failed"] = reel_failed[0]
    now_s = db.utcnow()
    # the save refuses a photo another post took while this one was being made (2026-10-16), in one write transaction so
    # no other process can slip a draft in between the look and the save
    began = not ctx.conn.in_transaction
    if began:
        ctx.conn.execute("BEGIN IMMEDIATE")
    held = photo_holder(ctx.conn, photo_ids, config.repeat_window(ctx.cfg))
    if held:
        if began:
            ctx.conn.execute("ROLLBACK")
        raise PhotosTaken(*held)
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
    # the ping that opens the draft (Chris, 2026-10-11: "I haven't received any ntfy"); 2026-10-13: it carries the
    # card, and an Approve button when the art director passed the draft (core/approve_token: signed, single use)
    title, message = ping or ping_words(ctx.cfg.brand_name, design, len(photo_ids), f"{day:%A}", designed=False)
    if not quiet:
        notify.push(title, message, dry_run=ctx.dry_run, priority="default", click=ping_click(qid, design), conn=ctx.conn,
                    agent=ctx.agent, **ping_extras(ctx.conn, {"id": qid, "updated_at": now_s}, art))
    fell = (f", the reel could not be made ({reel_failed[0]})" if reel_failed
            else f", {asked} wanted but too few photos passed" if asked != design else "")
    fell += ", LinkedIn skipped (a public figure)" if skipped else ""
    line = (f"{'DRY RUN ' if ctx.dry_run else ''}drafted post #{qid} for {day} ({kind_used}"
            f"{', instead of ' + want if kind_used != want else ''}): {design} with {len(photo_ids)} photo(s){fell}, "
            f"photo {hero['id']} first{' (' + why + ')' if why else ''}, captions by {writer} for \"{plan.primary}\", "
            f"art director: {art.get('verdict')}")
    return qid, art, line


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
