"""Post this on a design sample: a sample Chris likes becomes a real draft post, on the daily draft's road.

Chris, 2026-10-15: "Put a "Post this" on every design sample so I can turn a sample I like into a real draft post."
The samples (render/design_samples.py) are for review and had no road to Buffer; the only road was the daily draft.

Each sample on the samples page names its design and the photos it was made from (about.json `samples`). Post this
records the press (`sample_posts`, pending) and starts this agent (`ccs run sample --wait`: a press while one is being
drafted waits its turn, never lost). For each press this agent does what the daily draft does, never a shortcut:

- the sample must still stand: its folder is the newest samples and every photo in it is still approved
  (design_samples.stale), and none of its photos is on a post inside the repeat window by any road (used_lately,
  2026-10-15); else it says why and drafts nothing;
- the same photos, fetched again at full size (the cache of the Drive original, else Drive, read only);
- Claude's final check on every one (someone who may be under 18, a readable plate, a wedding) and eligibility; one
  photo that fails drops the draft and says which and why (one gone would change the design);
- then agents/content.make_draft: the captions through the same writer and copy rules, the same renderer with the
  same design (the reel with the current music track, the carousel when the reel fails; a reel never goes out
  silent, so with no track it is refused), the art director's look, a queue row and the ping with Approve, and the
  photos' use recorded for the rotation.

The draft is for today and marked `asap` like a photo from the phone: approved, it goes out as soon as Buffer takes
it. Nothing posts without his Approve. The lane follows the content lane's dry-run switch, and in dry run nothing is
drafted: the final check is a paid look, and a sample is never drafted without it.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from ..core import db, runner, settings
from ..library import classify, eligibility
from .. import music

STALE_DRAFTING = timedelta(minutes=20)       # a press left "drafting" this long was a run that died: tried again
DESIGNS = ("fan", "spotlight", "carousel", "reel")
DRY_RUN = ("the content lane is in practice run (dry run), so Claude cannot give the photos their final check and nothing "
           "is drafted (switch the content lane live: Settings, Agents)")
PHOTO_SQL = """SELECT p.*, c.subject, c.convention_name, c.event_kind, c.shot_type, c.quality, c.people_count, c.summary
               FROM photos p JOIN classifications c ON c.photo_id = p.id WHERE p.id=?"""


def ask(conn: sqlite3.Connection, folder: str, design: str, photo_ids: list[int], *, now: Optional[str] = None) -> int:
    """The press, recorded; the agent drafts it. The id."""
    now = now or db.utcnow()
    return db.insert(conn, "sample_posts", folder=folder, design=design, photo_ids=json.dumps([int(p) for p in photo_ids]),
                     status="pending", created_at=now, updated_at=now)


def pending(conn: sqlite3.Connection, now: Optional[str] = None) -> list[sqlite3.Row]:
    """The presses still to draft: new ones, and any a run left "drafting" too long ago (it died)."""
    stale = ((datetime.fromisoformat(now) if now else datetime.now(timezone.utc)) - STALE_DRAFTING).replace(microsecond=0).isoformat()
    return db.rows(conn, "SELECT * FROM sample_posts WHERE status = 'pending' OR (status = 'drafting' AND updated_at < ?) ORDER BY id",
                   (stale,))


def used_lately(conn: sqlite3.Connection, photo_ids: list[int]) -> Optional[str]:
    """Why these photos cannot go out now, or None: one of them is already on a post inside the repeat window, by any
    road (Chris, 2026-10-15: "we keep reusing the same photos too"; config.repeat_window)."""
    from ..core import config
    from . import content
    days = config.repeat_window(config.get_config())
    used, _, _ = content.recent_use(conn, days)
    again = [int(p) for p in photo_ids if int(p) in used]
    if again:
        return f"photo {again[0]} is already on a post inside {days} days, and a photo goes out once inside that window"
    return None


def _status(conn, sid: int, status: str, *, queue_id: Optional[int] = None, error: Optional[str] = None) -> None:
    conn.execute("UPDATE sample_posts SET status=?, queue_id=COALESCE(?, queue_id), error=?, updated_at=? WHERE id=?",
                 (status, queue_id, error, db.utcnow(), sid))


def _failed(ctx: runner.Context, rec, why: str, *, queue_id: Optional[int] = None) -> str:
    """Said on the samples page and on the Agents page, never only in a log."""
    _status(ctx.conn, rec["id"], "failed", queue_id=queue_id, error=why)
    runner.record_error(ctx.conn, ctx.agent, "sample", f"The {rec['design']} sample you chose was not drafted: {why}")
    return f"sample #{rec['id']} ({rec['design']}) not drafted: {why}"


def draft_sample(ctx: runner.Context, rec, fetch: Callable[[dict], bytes], *, check_client=None, drafter=None,
                 art_client=None) -> str:
    from ..render import design_samples
    from . import content
    conn = ctx.conn
    _status(conn, rec["id"], "drafting")
    design = rec["design"]
    if design not in DESIGNS:
        return _failed(ctx, rec, f"{design} is not a design the daily post makes")
    sample = design_samples.sample_of(rec["folder"], design)
    why = design_samples.stale(conn, rec["folder"], sample)
    if why:
        return _failed(ctx, rec, why)
    ids = [int(p) for p in json.loads(rec["photo_ids"] or "[]")]
    if ids != [int(p) for p in sample["photos"]]:
        return _failed(ctx, rec, "the photos asked for are not the photos this sample was made from")
    again = used_lately(conn, ids)
    if again:
        return _failed(ctx, rec, again)
    if ctx.dry_run:
        return _failed(ctx, rec, DRY_RUN)
    if len(ids) < content.NEEDS[design]:
        return _failed(ctx, rec, f"a {design} needs {content.NEEDS[design]} photos and this sample has {len(ids)}")
    track = music.current(conn) if design == "reel" else None
    if design == "reel" and track is None:
        return _failed(ctx, rec, "a reel never goes out silent and no music is added yet (Library page, Music for reels)")
    chosen: list[tuple[dict, bytes]] = []
    for pid in ids:
        row = db.one(conn, PHOTO_SQL, (pid,))
        if row is None:
            return _failed(ctx, rec, f"photo {pid} is no longer in the library")
        row = dict(row)
        try:
            data = fetch(row)
        except Exception as e:  # noqa: BLE001  Drive or the disk, not the photo: said, and he can press again
            return _failed(ctx, rec, f"photo {pid} could not be read ({type(e).__name__}: {e}); press Post this again in a few minutes")
        try:
            verdict = classify.final_check(conn, pid, data, client=check_client, agent=ctx.agent)
        except Exception as e:  # noqa: BLE001  the API or the network, not the photo
            return _failed(ctx, rec, f"Claude's final check could not run ({type(e).__name__}: {e}); press Post this again in a few minutes")
        if verdict is None:
            return _failed(ctx, rec, f"Claude could not look at photo {pid} (no key, the monthly cap, or a refusal: the Agents page says which)")
        ok, no = eligibility.is_eligible(conn, pid)
        if not ok:
            return _failed(ctx, rec, f"photo {pid} did not pass the final check: {no}")
        if verdict.get("shot_type") in classify.SHOT_TYPES:
            row["shot_type"] = verdict["shot_type"]          # what the photo shows, by the model that looked at it in full
        if verdict.get("event_kind") in classify.KINDS and verdict["event_kind"] != "unknown":
            row["event_kind"] = verdict["event_kind"]
        row["credit"] = eligibility.credit_line(conn, pid)
        chosen.append((row, data))
    hero = chosen[0][0]
    today = datetime.now(ZoneInfo(ctx.cfg.timezone)).date()
    qid, art, line = content.make_draft(
        ctx, today, chosen, design, want=hero["subject"], kind_used=hero["subject"], asked=design, track=track,
        drafter=drafter, art_client=art_client, why="from the design samples",
        extra_meta={"source": "sample", "asap": True, "sample_folder": rec["folder"], "sample_id": rec["id"]},
        ping=(f"{ctx.cfg.brand_name}: the sample you chose, a post to approve",
              f"The {design} idea, made into a post for today. Post now and it goes out as soon as Buffer takes it, or follow "
              "the pace, or skip. Tap to see it."))
    if art.get("verdict") == "reject":
        return _failed(ctx, rec, f"the art director turned it back: {art.get('notes', '')}", queue_id=qid)
    _status(conn, rec["id"], "drafted", queue_id=qid)
    return line


def run(ctx: runner.Context, fetch: Optional[Callable[[dict], bytes]] = None, **clients) -> str:
    """Every press waiting, one after the other, on the content lane's dry-run switch."""
    from . import content
    dry = settings.dry_run(ctx.conn, "content")
    if dry != ctx.dry_run:
        ctx = dataclasses.replace(ctx, dry_run=dry)
    if not pending(ctx.conn):
        return "no design sample is waiting to be drafted"
    if fetch is None and not ctx.dry_run:
        from ..drive import oauth
        from ..drive.api import DriveReader
        try:
            oauth.access_token(ctx.conn)
            reader = DriveReader(lambda: oauth.access_token(ctx.conn), conn=ctx.conn, agent=ctx.agent)
        except oauth.DriveAuthError as e:
            # the photos cannot be fetched again: every press waiting says so, rather than drafting from the samples' previews
            return "; ".join(_failed(ctx, r, f"Google Drive is signed out ({e}); sign in on the Drive page and press Post this again")
                             for r in pending(ctx.conn))

        def fetch(row):
            return content.read_photo(ctx.cfg, row, reader.download)
    lines = []
    while True:
        rows = pending(ctx.conn)
        if not rows:
            break
        lines.append(draft_sample(ctx, rows[0], fetch or (lambda row: b""), **clients))
    return "; ".join(lines)


if __name__ == "__main__":
    runner.main_for("sample", run)
