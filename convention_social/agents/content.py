"""Content agent (daily, 06:00): tomorrow's post, drafted into the review queue for Chris.

1. The day: one post a day. BUILDING_WEEKDAY (default wednesday) is the
   building day, from the architecture work (Chris, 2026-10-09: one day a
   week); every other day is event work. When a day's kind has no photo
   ready, the other kind stands in.
2. The photo: candidates only (cleared, sorted, nobody possibly under 18, no
   readable details, not on the do-not-use list), never used inside
   PHOTO_REPEAT_DAYS, and no event or credited person repeated inside
   VARIETY_DAYS. Best quality first.
3. The final check: the full-size photo is downloaded (read only) and Claude
   looks once more; a photo that fails is skipped and the next one is tried.
4. Captions (ai/claude.py), the Lens designs at 4:5 and 2:3 (render/posts.py),
   and a draft row. Nothing leaves: the publisher sends only what Chris
   approves.

Dry run (the default): no paid call at all. The draft gets template captions
and no final check, so the dashboard shows it but refuses Approve until the
agent runs live. Live: the final check and Claude's captions, under the cap.
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from PIL import Image

from ..ai import claude, copy_rules
from ..core import config, db, runner
from ..library import classify, eligibility
from ..render import brand, posts

try:                                    # HEIC originals from a phone
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover
    pass

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
TARGETS = ("instagram", "facebook", "pinterest")
MAX_TRIES = 5


def target_day(cfg, now: Optional[datetime] = None) -> date:
    return (now or datetime.now(ZoneInfo(cfg.timezone))).astimezone(ZoneInfo(cfg.timezone)).date() + timedelta(days=1)


def subject_for(day: date) -> str:
    building = (config.getenv("BUILDING_WEEKDAY") or "wednesday").strip().lower()
    return "architecture" if WEEKDAYS[day.weekday()] == building else "event"


def already_drafted(conn: sqlite3.Connection, day: date) -> bool:
    return bool(db.one(conn, "SELECT 1 FROM content_queue WHERE kind='photo' AND status != 'rejected' AND rule_report LIKE ?",
                       (f'%"for_day": "{day.isoformat()}"%',)))


def recent_use(conn: sqlite3.Connection, days: int) -> tuple[set, set, set]:
    """(photo ids, event names, credited people) used by posts drafted inside the window and not rejected."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    photos, events, people = set(), set(), set()
    for r in db.rows(conn, "SELECT photo_ids, rule_report FROM content_queue WHERE status != 'rejected' AND created_at >= ?", (since,)):
        photos.update(int(p) for p in json.loads(r["photo_ids"] or "[]"))
        meta = json.loads(r["rule_report"] or "{}")
        if meta.get("event"):
            events.add(meta["event"].lower())
        people.update(x.lower() for x in meta.get("people") or [])
    return photos, events, people


def candidates(conn: sqlite3.Connection, subject: str) -> list[dict]:
    cfg = config.get_config()
    used_photos, _, _ = recent_use(conn, cfg.photo_repeat_days)
    _, used_events, used_people = recent_use(conn, cfg.variety_days)
    rows = db.rows(conn, """SELECT p.*, c.subject, c.convention_name, c.event_kind, c.shot_type, c.quality, c.people_count, c.summary
                            FROM photos p JOIN classifications c ON c.photo_id = p.id
                            WHERE p.trashed = 0 AND c.subject = ? AND c.method IN ('ollama','vision')
                            ORDER BY COALESCE(c.quality,0) DESC, COALESCE(c.people_count,0) DESC, p.id""", (subject,))
    out = []
    for r in rows:
        if r["id"] in used_photos or not eligibility.is_candidate(conn, r["id"])[0]:
            continue
        if subject == "event" and (r["convention_name"] or "").lower() in used_events and r["convention_name"]:
            continue
        credit = eligibility.credit_line(conn, r["id"])
        if any(c.lower() in used_people for c in credit.split()):
            continue
        out.append({**dict(r), "credit": credit})
    return out


def kicker_for(row: dict) -> str:
    if row["subject"] == "architecture":
        return "Venues and buildings"
    year = (row.get("taken_at") or "")[:4]
    return " ".join(x for x in ((row.get("convention_name") or "").strip(), year if year.isdigit() else "") if x) or "On assignment"


def draft_one(ctx: runner.Context, fetch: Callable[[dict], bytes], *, now: Optional[datetime] = None,
              check_client=None, drafter=None) -> str:
    day = target_day(ctx.cfg, now)
    if already_drafted(ctx.conn, day):
        return f"a post for {day} is already drafted"
    want = subject_for(day)
    pool = candidates(ctx.conn, want)
    kind_used = want
    if not pool:
        kind_used = "event" if want == "architecture" else "architecture"
        pool = candidates(ctx.conn, kind_used)
    if not pool:
        return f"no photo ready for {day}: clear folders on the Library page (nothing drafted)"
    chosen, image_bytes = None, None
    for row in pool[:MAX_TRIES]:
        data = fetch(row)
        if ctx.dry_run:
            chosen, image_bytes = row, data
            break
        verdict = classify.final_check(ctx.conn, row["id"], data, client=check_client, agent=ctx.agent)
        if verdict and eligibility.is_eligible(ctx.conn, row["id"])[0]:
            chosen, image_bytes = row, data
            break
    if chosen is None:
        return f"no photo passed the final check for {day} (tried {min(len(pool), MAX_TRIES)})"
    cache = ctx.cfg.data_root / "photos" / f"{chosen['drive_id']}.img"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        cache.write_bytes(image_bytes)
    ctx.conn.execute("UPDATE photos SET local_path=? WHERE id=?", (str(cache), chosen["id"]))
    facts = claude.PostFacts(brand_name=ctx.cfg.brand_name, event_name=chosen.get("convention_name") or "",
                             event_kind=chosen.get("event_kind") or "unknown", credit=chosen["credit"],
                             shot_type=chosen.get("shot_type") or "", subject=chosen["subject"],
                             quote_link=f"{ctx.cfg.brand_domain}/book" if ctx.cfg.brand_domain else "",
                             services=("full event coverage", "backstage and green rooms", "breakouts and panels",
                                       "evening events and dinners", "portraits", "exhibition halls and vendors",
                                       "approved images delivered on site"))
    drafter = drafter or (claude.TemplateDrafter() if ctx.dry_run else claude.get_drafter(ctx.conn, agent=ctx.agent))
    draft = drafter.draft(facts, cache)
    reports = {n: copy_rules.check(t).as_dict() for n, t in draft.captions.items()}
    image = Image.open(io.BytesIO(image_bytes))
    direction = brand.current() or brand.DIRECTIONS["lens"]
    out_dir = ctx.cfg.data_root / "renders" / "posts" / day.isoformat()
    text = posts.PostText(kicker=kicker_for(chosen), credit=chosen["credit"])
    render_paths = {aspect: [str(posts.render("photo", [image], text, direction, aspect=aspect,
                                              out=out_dir / f"{chosen['id']}-{aspect.replace(':', '')}.jpg"))]
                    for aspect in ("4:5", "2:3")}
    meta = {"for_day": day.isoformat(), "subject": chosen["subject"], "event": chosen.get("convention_name") or "",
            "people": chosen["credit"].split(), "model": draft.model, "rules": reports, "wanted": want}
    now_s = db.utcnow()
    qid = db.insert(ctx.conn, "content_queue", kind="photo", photo_ids=json.dumps([chosen["id"]]), targets=json.dumps(list(TARGETS)),
                    caption=json.dumps(draft.captions), render_paths=json.dumps(render_paths), rule_report=json.dumps(meta),
                    created_at=now_s, updated_at=now_s)
    return (f"{'DRY RUN ' if ctx.dry_run else ''}drafted post #{qid} for {day} ({kind_used}"
            f"{', instead of ' + want if kind_used != want else ''}): photo {chosen['id']}, captions by {draft.model}")


def run(ctx: runner.Context, fetch: Optional[Callable[[dict], bytes]] = None) -> str:
    if fetch is None:
        from ..drive import oauth
        from ..drive.api import DriveReader
        try:
            reader = DriveReader(oauth.access_token(ctx.conn), conn=ctx.conn, agent=ctx.agent)
        except oauth.DriveAuthError as e:
            runner.record_error(ctx.conn, ctx.agent, "drive_auth", str(e))
            return f"not signed in: {e}"

        def fetch(row):
            cached = ctx.cfg.data_root / "photos" / f"{row['drive_id']}.img"
            return cached.read_bytes() if cached.exists() else reader.download(row["drive_id"])
    return draft_one(ctx, fetch)


if __name__ == "__main__":
    runner.main_for("content", run)
