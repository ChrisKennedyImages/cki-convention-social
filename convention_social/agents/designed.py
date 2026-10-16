"""Designed drafts: the suite designs up to DESIGNED_PER_DAY posts a day by itself and sends each to Chris's phone.

Chris, 2026-10-15: "design samples is completely in a different place then todays posts and today has no sign of
design examples. why are they examples? cant they just create them and send them to ntfy for me to approve and
watch?" The samples page made every design for review only; these are real drafts in the queue instead, each on
the daily draft's road and gates (agents/sample.py's path is the model), never a shortcut:

- the photos: approved and candidates (eligibility), never on any post inside the repeat window by any road (the
  daily draft, a designed draft, Post this, the phone; content.recent_use with config.repeat_window), no credited
  person twice inside VARIETY_DAYS, the least recently used first on any surface (library/report.rotate), and spread:
  one room and one event before any repeats, and a hero from an event no post had inside VARIETY_DAYS when one is
  left (spread). A designed draft never takes an event away from the daily post: the approved library holds 34
  events, most with one to four photos, and four posts a day under the daily post's hard 14-day event rule would
  leave mornings with nothing to post, so its event is kept as `designed_event`, read only by this lane;
- the design: the one the designed drafts used least lately, from every design the daily draft's renderer makes
  (content.NEEDS: a design added there joins by itself), the reel only with a music track (never silent);
- Claude's final check on every photo (a photo that fails is passed over, as on the daily draft), then
  content.make_draft: the captions through the same writer and copy rules, the same renderer, the art director, a
  queue row and the ping with the card (the reel's own cover for a reel) and his three choices: Post now, Follow the
  pace, Skip. The photos' use is recorded for the rotation.

The draft is for today. Nothing posts without one of his two approve choices. Skip sets it aside and its photos go
back into the rotation (never Don't use). The hourly scanner starts this agent from 08:00 to 20:00 while today has
fewer than DESIGNED_PER_DAY designed drafts and fewer than that many still wait for him (when he has not answered
them, no more pile up). The lane follows the content lane's dry-run switch: in dry run nothing is drafted, since
the final check is a paid look and a designed draft is never made without it.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from ..core import config, db, runner, settings
from ..library import classify, eligibility, report
from .. import music

SOURCE = "designed"
PER_DAY_KEY = "DESIGNED_PER_DAY"
DEFAULT_PER_DAY = 3
MOST_PER_DAY = 6
HOURS = (8, 20)                 # local hours the lane drafts in: the content agent's day window
RETRIES = 3                     # turned back by the art director: tried again inside the day, this many more times at most
MAX_TRIES = 5                   # photos beyond the design's own count tried when the final check passes some over
DRY_RUN = ("the content lane is in practice run, so Claude cannot give the photos their final check and no designed "
           "draft is made (switch the content lane live: Settings, Agents)")
PHOTO_SQL = """SELECT p.*, c.subject, c.convention_name, c.event_kind, c.shot_type, c.quality, c.people_count, c.summary
               FROM photos p JOIN classifications c ON c.photo_id = p.id
               WHERE p.trashed = 0 AND c.subject = 'event' AND c.method IN ('ollama', 'vision')
               ORDER BY COALESCE(c.quality, 0) DESC, COALESCE(c.people_count, 0) DESC, p.id"""


def per_day() -> int:
    """DESIGNED_PER_DAY on the Keys page (Posting): 3 when blank or unreadable, 0 stops the lane, never more than 6."""
    raw = (config.getenv(PER_DAY_KEY) or "").strip()
    try:
        n = int(raw) if raw else DEFAULT_PER_DAY
    except ValueError:
        n = DEFAULT_PER_DAY
    return max(0, min(n, MOST_PER_DAY))


def designs(has_music: bool) -> list[str]:
    """Every design the daily draft's renderer makes (content.NEEDS) but the plain single photo, in its order, so a
    design added to that list joins the designed drafts by itself (the four of 2026-10-15 did); the reel only with a
    music track."""
    from . import content
    return [d for d in content.NEEDS if d != "single" and (d != "reel" or has_music)]


def local_now(cfg, now: Optional[datetime] = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(cfg.timezone))


def _meta(row) -> dict:
    try:
        meta = json.loads(row["rule_report"] or "{}")
    except ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


def rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every designed draft, newest first."""
    return db.rows(conn, "SELECT * FROM content_queue WHERE kind='photo' AND json_extract(rule_report, '$.source') = ? "
                         "ORDER BY id DESC", (SOURCE,))


def of_day(conn: sqlite3.Connection, day: date) -> tuple[int, int]:
    """(shown, tried) today: the designed drafts that reached him (waiting, chosen or skipped), and every try,
    the art director's turn-backs included."""
    shown = tried = 0
    for r in rows(conn):
        if _meta(r).get("designed_day") != day.isoformat():
            continue
        tried += 1
        if r["status"] != "rejected" or _meta(r).get("rejected_by"):
            shown += 1
    return shown, tried


def waiting(conn: sqlite3.Connection) -> int:
    return sum(1 for r in rows(conn) if r["status"] == "draft")


def due(conn: sqlite3.Connection, now: Optional[datetime] = None) -> tuple[bool, str]:
    """(True, "") when a designed draft should be made now; else (False, why, in plain words)."""
    n = per_day()
    if n == 0:
        return False, "designed drafts are off (Keys page, Designed drafts: 0 a day)"
    if settings.dry_run(conn, "content"):
        return False, DRY_RUN
    t = local_now(config.get_config(), now)
    if not HOURS[0] <= t.hour < HOURS[1]:
        return False, f"designed drafts are made from {HOURS[0]}:00 to {HOURS[1]}:00"
    shown, tried = of_day(conn, t.date())
    if shown >= n:
        return False, f"{shown} designed draft(s) made today, the most a day is {n}"
    if tried >= n + RETRIES:
        return False, f"the art director turned back {tried - shown} designed draft(s) today; no more tries until tomorrow"
    w = waiting(conn)
    if w >= n:
        return False, f"{w} designed draft(s) still wait for you; new ones come when you answer them"
    return True, ""


def status_line(conn: sqlite3.Connection, now: Optional[datetime] = None) -> str:
    """One line for the Today page: how many designed drafts today, and when the next one comes or why not."""
    n = per_day()
    if n == 0:
        return "Designed drafts are off. Set how many a day on the Keys page, under Designed drafts."
    if settings.dry_run(conn, "content"):
        return "No designed drafts while the content lane is in practice run."
    t = local_now(config.get_config(), now)
    shown, _ = of_day(conn, t.date())
    ok, why = due(conn, now)
    if ok:
        return f"{shown} of {n} designed drafts made today. The next one comes within the hour."
    if shown >= n:
        return f"All {n} designed drafts for today are made. More come tomorrow from {HOURS[0]}:00."
    if not HOURS[0] <= t.hour < HOURS[1]:
        return f"{shown} of {n} designed drafts made today. They are made from {HOURS[0]}:00 to {HOURS[1]}:00."
    return f"{shown} of {n} designed drafts made today: {why}."


def next_design(conn: sqlite3.Connection, has_music: bool) -> str:
    """The design the designed drafts used least lately (never used first), in the list's order on a tie."""
    choices = designs(has_music)
    last: dict[str, int] = {}
    for r in rows(conn):                       # newest first: the first sighting of a design is its last use
        d = _meta(r).get("design_wanted") or _meta(r).get("design")
        if d in choices and d not in last:
            last[d] = r["id"]
    return min(choices, key=lambda d: (last.get(d, 0), choices.index(d)))


def pool(conn: sqlite3.Connection) -> list[dict]:
    """Every event photo a designed draft may take, the least recently used first on any surface, quality breaking
    ties: a candidate (approved, sorted, nothing that keeps it out), never on a post inside the repeat window by any
    road, and no credited person who was on a post inside VARIETY_DAYS."""
    from . import content
    cfg = config.get_config()
    used, _, _ = content.recent_use(conn, config.repeat_window(cfg))
    _, _, people = content.recent_use(conn, cfg.variety_days)
    out = []
    for r in db.rows(conn, PHOTO_SQL):
        if r["id"] in used or not eligibility.is_candidate(conn, r["id"])[0]:
            continue
        credit = eligibility.credit_line(conn, r["id"])
        if any(c.lower() in people for c in credit.split()):
            continue
        out.append({**dict(r), "credit": credit})
    last = report.last_uses(conn)
    for r in out:
        r["last_use"] = last.get(r["id"])
    return report.rotate(conn, out, last=last)


def room_of(row: dict) -> str:
    from ..render import design_samples
    return design_samples.ROOMS.get(row.get("shot_type") or "", design_samples.OTHER)[0]


def event_of(row: dict) -> str:
    return (row.get("convention_name") or "").strip().lower() or str(row.get("folder_id") or "")


def spread(pool_rows: list[dict], n: int, *, fresh_events: Callable[[str], bool] = lambda e: True,
           taken_rooms: frozenset = frozenset()) -> list[dict]:
    """Up to n photos in the order to try them, the pool's order (least recently used first) kept inside each pass.
    The hero: the first photo from an event no draft had inside VARIETY_DAYS and a room no other designed draft of
    today led with, else the first from such an event, else the first. Then one room and one event before any
    repeats: new room and new event, then a new room, then a new event, then the rest. A photo is never pinned to
    every draft by being the only one of its room: once on a post it sits out the whole repeat window (pool)."""
    if not pool_rows or n <= 0:
        return []
    hero = (next((r for r in pool_rows if fresh_events(event_of(r)) and room_of(r) not in taken_rooms), None)
            or next((r for r in pool_rows if fresh_events(event_of(r))), None) or pool_rows[0])
    picked, rooms, events = [hero], {room_of(hero)}, {event_of(hero)}
    for want_room, want_event in ((True, True), (True, False), (False, True), (False, False)):
        for r in pool_rows:
            if len(picked) >= n:
                return picked
            if any(r is p for p in picked) or (want_room and room_of(r) in rooms) or (want_event and event_of(r) in events):
                continue
            picked.append(r)
            rooms.add(room_of(r))
            events.add(event_of(r))
    return picked


def recent_events(conn: sqlite3.Connection, days: int) -> set[str]:
    """Events a post had inside `days`: the daily post's own record (content.recent_use) and the designed drafts'."""
    from . import content
    _, events, _ = content.recent_use(conn, days)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    for r in rows(conn):
        meta = _meta(r)
        if (r["created_at"] or "") >= since and meta.get("designed_event") and meta.get("rejected_by") != content.SKIPPED:
            events.add(meta["designed_event"])
    return events


def todays_hero_rooms(conn: sqlite3.Connection, day: date) -> frozenset:
    out = set()
    for r in rows(conn):
        if _meta(r).get("designed_day") != day.isoformat():
            continue
        try:
            hero = int(json.loads(r["photo_ids"] or "[]")[0])
        except (IndexError, TypeError, ValueError):
            continue
        row = db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (hero,))
        if row is not None:
            out.add(room_of(dict(row)))
    return frozenset(out)


def draft(ctx: runner.Context, fetch: Callable[[dict], bytes], *, now: Optional[datetime] = None, check_client=None,
          drafter=None, art_client=None) -> str:
    """One designed draft, or the plain reason none was made. It holds the drafting lock from its pick to its save
    (content.DRAFTING, 2026-10-16): while the daily post or an idea is being drafted it waits for the next hour, so two
    drafts never pick the same least-used photos at once."""
    from . import content
    ok, why = due(ctx.conn, now)
    if not ok:
        return f"no designed draft: {why}"
    lock = content.drafting_lock(0)
    if lock is None:
        return "no designed draft: another post is being drafted now (the daily post or an idea); the next one comes within the hour"
    try:
        return _draft(ctx, fetch, now=now, check_client=check_client, drafter=drafter, art_client=art_client)
    finally:
        lock.release()


def _draft(ctx: runner.Context, fetch: Callable[[dict], bytes], *, now: Optional[datetime], check_client, drafter,
           art_client) -> str:
    from . import content
    conn = ctx.conn
    day = local_now(ctx.cfg, now).date()
    track = music.current(conn)
    design = next_design(conn, track is not None)
    rows_ = pool(conn)
    if not rows_:
        return "no designed draft: no approved photo is free (every one is on a post inside the repeat window, or none is approved)"
    lately = recent_events(conn, ctx.cfg.variety_days)
    order = spread(rows_, content.TAKES[design] + MAX_TRIES, fresh_events=lambda e: e not in lately,
                   taken_rooms=todays_hero_rooms(conn, day))
    chosen: list[tuple[dict, bytes]] = []
    for row in order:
        try:
            data = fetch(row)
        except Exception as e:  # noqa: BLE001  Drive or the disk, not the photo: said once; the next hourly run tries again
            runner.record_error_once(conn, ctx.agent, "designed", f"A designed draft could not read photo {row['id']} "
                                                                  f"({type(e).__name__}: {e}); it tries again within the hour.")
            return f"no designed draft: photo {row['id']} could not be read ({type(e).__name__}: {e})"
        try:
            verdict = classify.final_check(conn, row["id"], data, client=check_client, agent=ctx.agent)
        except Exception as e:  # noqa: BLE001  the API or the network, not the photo
            runner.record_error_once(conn, ctx.agent, "final_check",
                                     f"The final check could not run ({type(e).__name__}: {e}); no designed draft until it can.")
            return f"no designed draft: the final check could not run ({type(e).__name__}: {e})"
        if not (verdict and eligibility.is_eligible(conn, row["id"])[0]):
            continue
        if verdict.get("shot_type") in classify.SHOT_TYPES:
            row["shot_type"] = verdict["shot_type"]          # what the photo shows, by the model that looked at it in full
        if verdict.get("event_kind") in classify.KINDS and verdict["event_kind"] != "unknown":
            row["event_kind"] = verdict["event_kind"]
        chosen.append((row, data))
        if len(chosen) >= content.TAKES[design]:
            break
    if not chosen:
        return f"no designed draft: no photo passed the final check (tried {len(order)})"
    asked = design
    if len(chosen) < content.NEEDS[design]:
        design, chosen = content.fallback_for(day), chosen[:1]      # too few passed: the day's one-photo design
    hero = chosen[0][0]
    words = {"reel": "Tap to watch it with its sound."}.get(design, "Tap to see it.")
    try:
        qid, art, line = content.make_draft(
            ctx, day, chosen, design, want="event", kind_used="event", asked=asked, track=track, drafter=drafter,
            art_client=art_client, why=f"designed draft; {content.use_why(hero, len(rows_))}",
            extra_meta={"source": SOURCE, "designed_day": day.isoformat(), "event": "", "designed_event": event_of(hero)},
            ping=(f"{ctx.cfg.brand_name}: a designed post to approve",
                  f"A {design} on {len(chosen)} of your photos, made for today. Post now, follow the pace or skip. {words}"))
    except content.PhotosTaken as e:
        return f"no designed draft: {e}; the next one comes within the hour"
    return line


def run(ctx: runner.Context, fetch: Optional[Callable[[dict], bytes]] = None, **clients) -> str:
    """One designed draft when one is due, on the content lane's dry-run switch."""
    from . import content
    dry = settings.dry_run(ctx.conn, "content")
    if dry != ctx.dry_run:
        ctx = dataclasses.replace(ctx, dry_run=dry)
    if ctx.dry_run:
        return f"no designed draft: {DRY_RUN}"
    ok, why = due(ctx.conn)
    if not ok:
        return f"no designed draft: {why}"
    if fetch is None:
        from ..drive import oauth
        from ..drive.api import DriveReader
        try:
            oauth.access_token(ctx.conn)
            reader = DriveReader(lambda: oauth.access_token(ctx.conn), conn=ctx.conn, agent=ctx.agent)
        except oauth.DriveAuthError as e:
            runner.record_error_once(ctx.conn, ctx.agent, "drive_auth", str(e))
            return f"no designed draft: Google Drive is signed out ({e})"

        def fetch(row):
            return content.read_photo(ctx.cfg, row, reader.download)
    return draft(ctx, fetch, **clients)


if __name__ == "__main__":
    runner.main_for(SOURCE, run)
