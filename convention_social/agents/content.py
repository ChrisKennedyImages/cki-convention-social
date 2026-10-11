"""Content agent (daily, 08:00; Chris, 2026-10-11): tomorrow's post, drafted into the review queue for Chris.

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
4. Captions (ai/claude.py), the day's design from the motion set (render/motion.py:
   spotlight, single, carousel, fan, face match or a reel; see DESIGNS), and a draft row. Nothing leaves: the publisher sends only what Chris
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

from ..ai import claude, copy_rules, names, seo_plan
from ..core import config, db, notify, runner
from ..library import classify, eligibility

from . import art_director, learner
from .. import music
from ..render import meta as image_meta

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
    for r in db.rows(conn, "SELECT photo_ids, rule_report FROM content_queue WHERE created_at >= ? AND "
                           "(status != 'rejected' OR rule_report LIKE '%\"verdict\": \"reject\"%')", (since,)):
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
    # what the learner found works, inside the founder's bounds; a stable sort, so ties keep quality order
    out.sort(key=lambda r: (r.get("quality") or 0) * learner.weight_for(conn, r.get("shot_type"), r.get("event_kind")), reverse=True)
    return out


def write_captions(drafter, facts: claude.PostFacts, photo: Path, known_names) -> tuple[dict, str, dict, str]:
    """(captions, alt text, what happened, who wrote them). Chris, 2026-10-11: "Make sure the captions are SEO
    optimized painstakingly". The writer gets the post's search plan (ai/seo_plan.py); the hashtags and the
    link are put in place for it; a draft that misses the plan or breaks a rule is written once more with
    the misses named, and after a second miss the template, which meets the plan by construction, stands in."""
    plan, link = facts.plan, facts.quote_link
    tries, notes, draft, caps, misses = [], (), None, {}, []
    for _ in range(2):
        draft = drafter.draft(facts, photo, notes=notes)
        caps = seo_plan.finish(draft.captions, plan, link)
        misses = seo_plan.problems(caps, plan) + [f"the {n} caption {b.message}" for n, t in caps.items()
                                                  for b in copy_rules.check(t, names=known_names, social=True).blocks]
        tries.append({"by": draft.model, "missed": misses})
        if not misses or draft.model == "template":
            break
        notes = misses
    writer = draft.model
    if misses:
        caps, writer = seo_plan.template_captions(plan, link, facts.brand_name), "template"
    from ..seo.photo_text import SHOT_WORDS
    alt = draft.alt_text
    if not alt or len(alt) > 125 or not copy_rules.check(alt, names=known_names, social=True).ok:
        alt = seo_plan.alt_text(plan, SHOT_WORDS.get(facts.shot_type, ""), facts.brand_name)
    record = {"primary": plan.primary, "related": list(plan.related), "hashtags": list(plan.hashtags), "area": plan.area,
              "tries": tries, "fell_back": bool(misses)}
    return caps, alt, record, writer


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
DESIGNS = {"monday": "spotlight", "tuesday": "single", "wednesday": "single", "thursday": "carousel",
           "friday": "fan", "saturday": "reel", "sunday": "single"}
NEEDS = {"single": 1, "spotlight": 3, "carousel": 4, "fan": 5, "reel": 4}      # fewest photos
TAKES = {"single": 1, "spotlight": 5, "carousel": 6, "fan": 7, "reel": 6}      # most


def design_for(day: date, subject: str, has_music: bool = False) -> str:
    if subject == "architecture":
        return "single"
    design = DESIGNS[WEEKDAYS[day.weekday()]]
    return "single" if design == "reel" and not has_music else design


def reel_kind(day: date) -> str:
    """The rooms reel, every time: the face match reel is retired (2026-10-11, it explained a service)."""
    return "rooms"


def rooms_first(pool: list) -> list:
    """Best first, but one photo per room before any room repeats, so a post of several photos
    shows the range of the coverage (the rooms reel names a room per photo)."""
    from ..render import design_samples
    seen, first, rest = set(), [], []
    for r in pool:
        room = design_samples.ROOMS.get(r.get("shot_type") or "", design_samples.OTHER)[0]
        (rest if room in seen else first).append(r)
        seen.add(room)
    return first + rest


def shot_for(row: dict, image: Image.Image, focus=(0.5, 0.45)):
    from ..render import design_samples, motion
    room, line = design_samples.ROOMS.get(row.get("shot_type") or "", design_samples.OTHER)
    if row.get("subject") == "architecture":
        room, line = design_samples.ROOMS["venue"]
    return motion.Shot(image, room, line, focus)


def middle_first(items: list, hero) -> list:
    """The hero in the middle of the rest, where the fan and the rail put the eye."""
    rest = [x for x in items if x is not hero]
    k = len(rest) // 2
    return rest[:k] + [hero] + rest[k:]


def draft_one(ctx: runner.Context, fetch: Callable[[dict], bytes], *, now: Optional[datetime] = None,
              check_client=None, drafter=None, art_client=None, _depth: int = 0) -> str:
    from ..render import motion
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
    track = music.current(ctx.conn)
    design = design_for(day, kind_used, track is not None)
    if TAKES[design] > 1:
        pool = rooms_first(pool)
    chosen: list[tuple[dict, bytes]] = []
    for row in pool[:TAKES[design] + MAX_TRIES - 1]:
        data = fetch(row)
        if not ctx.dry_run:
            verdict = classify.final_check(ctx.conn, row["id"], data, client=check_client, agent=ctx.agent)
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
        return f"no photo passed the final check for {day} (tried {min(len(pool), MAX_TRIES)})"
    asked = design
    if len(chosen) < NEEDS[design]:
        design, chosen = "single", chosen[:1]
    for row, data in chosen:
        cache = ctx.cfg.data_root / "photos" / f"{row['drive_id']}.img"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists():
            cache.write_bytes(data)
        ctx.conn.execute("UPDATE photos SET local_path=? WHERE id=?", (str(cache), row["id"]))
    hero = chosen[0][0]
    facts = claude.PostFacts(brand_name=ctx.cfg.brand_name, event_kind=hero.get("event_kind") or "unknown",
                             shot_type=hero.get("shot_type") or "", subject=hero["subject"],
                             quote_link=f"{ctx.cfg.brand_domain}/book" if ctx.cfg.brand_domain else "")
    drafter = drafter or (claude.TemplateDrafter() if ctx.dry_run else claude.get_drafter(ctx.conn, agent=ctx.agent))
    known_names = names.public_names(ctx.conn)
    plan = seo_plan.plan_for(subject=hero["subject"], event_kind=hero.get("event_kind"), shot_type=hero.get("shot_type"),
                             design=design)
    facts.plan = plan
    captions, alt, seo_record, writer = write_captions(drafter, facts, ctx.cfg.data_root / "photos" / f"{hero['drive_id']}.img",
                                                       known_names)
    reports = {n: copy_rules.check(t, names=known_names, social=True).as_dict() for n, t in captions.items()}
    images = {r["id"]: Image.open(io.BytesIO(d)) for r, d in chosen}
    out_dir = ctx.cfg.data_root / "renders" / "posts" / day.isoformat()
    seo = image_meta.for_photo(ctx.conn, hero)
    kicker = kicker_for(hero).upper()
    copy = motion.MotionCopy(kicker=kicker)
    tag = f"{hero['id']}-{design}"

    reel_failed: list[str] = []

    def single(focus, aspects=("4:5", "2:3")):
        shot = shot_for(hero, images[hero["id"]], focus)
        return {a: [str(motion.single_post(shot, copy, out=out_dir / f"{tag}-{a.replace(':', '')}.jpg", aspect=a,
                                           kicker=kicker, meta=seo))] for a in aspects}

    def render(focus):
        if design == "single":
            return single(focus)
        shots = [shot_for(r, images[r["id"]]) for r, _ in chosen]
        if design == "reel" and not reel_failed:
            # Instagram and Facebook get the reel (render_paths "9:16"), with its cover; Pinterest the
            # hero as a 2:3 card; the art director looks at the cover and the stills, never the mp4
            kind = reel_kind(day)
            try:
                video = motion.REELS[kind](shots, copy, out=out_dir / f"{tag}-{kind}.mp4", audio=track)
                stills = motion.reel_stills(kind, shots, copy, out_dir=out_dir / f"{tag}-stills", meta=seo)
            except Exception as e:  # noqa: BLE001  a reel that cannot be made leaves a carousel of the same photos, said why
                reel_failed.append(f"{type(e).__name__}: {e}")
                runner.record_error(ctx.conn, ctx.agent, "reel", f"the {kind} reel for {day} was not made: {e}")
            else:
                return {"9:16": [str(video)], "cover": [str(stills[0])], **single(focus, ("2:3",)),
                        "stills": [str(p) for p in stills[1:]]}
        if design in ("carousel", "reel"):        # the reel's fallback takes the same 4 to 6 photos
            return {"4:5": [str(p) for p in motion.carousel(shots, copy, out_dir=out_dir / tag, meta=seo)]}
        ordered = middle_first(shots, shots[0])
        mid = ordered.index(shots[0])
        if design == "fan":
            return {"4:5": [str(motion.fan_post(ordered, copy, out=out_dir / f"{tag}.jpg", focus=mid, meta=seo))]}
        return {"4:5": [str(motion.spotlight_post(ordered, copy, out=out_dir / f"{tag}.jpg", index=mid, meta=seo))]}

    render_paths, art = art_director.direct(ctx.conn, render, dry_run=ctx.dry_run, client=art_client, agent=ctx.agent,
                                            allow_redo=design == "single", max_files=4)
    if reel_failed:
        design = "carousel"
    photo_ids = [r["id"] for r, _ in chosen]
    if art.get("verdict") == "reject":
        # the photos do not hold up: they sit out like used ones, and the next run drafts again
        now_r = db.utcnow()
        db.insert(ctx.conn, "content_queue", kind="photo", photo_ids=json.dumps(photo_ids), targets=json.dumps(list(TARGETS)),
                  caption=json.dumps(captions), render_paths=json.dumps(render_paths), status="rejected",
                  last_error=f"Art director: {art.get('notes', '')}",
                  rule_report=json.dumps({"for_day": "turned back", "art": art, "subject": hero["subject"], "design": design}),
                  created_at=now_r, updated_at=now_r)
        note = f"art director turned back photo {hero['id']}: {art.get('notes', '')}"
        if _depth + 1 >= MAX_TRIES:
            return f"{note}; no photo passed for {day} after {MAX_TRIES} tries"
        return note + "; " + draft_one(ctx, fetch, now=now, check_client=check_client, drafter=drafter,
                                       art_client=art_client, _depth=_depth + 1)
    people = [c for r, _ in chosen for c in (r["credit"] or "").split()]
    meta = {"for_day": day.isoformat(), "subject": hero["subject"], "event": hero.get("convention_name") or "",
            "people": people, "model": writer, "rules": reports, "wanted": want, "art": art, "design": design,
            "design_wanted": asked, "seo": seo_record, "alt_text": alt}
    if design == "reel":
        meta.update(reel=reel_kind(day), music=track.name)
    if reel_failed:
        meta["reel_failed"] = reel_failed[0]
    now_s = db.utcnow()
    qid = db.insert(ctx.conn, "content_queue", kind="photo", photo_ids=json.dumps(photo_ids), targets=json.dumps(list(TARGETS)),
                    caption=json.dumps(captions), render_paths=json.dumps(render_paths), rule_report=json.dumps(meta),
                    created_at=now_s, updated_at=now_s)
    # the ping that opens the draft (Chris, 2026-10-11: "I haven't received any ntfy")
    notify.push(f"{ctx.cfg.brand_name}: a post to approve", f"{design} with {len(photo_ids)} photo(s) for {day:%A}. Tap to see it.",
                dry_run=ctx.dry_run, priority="default", click=notify.link(f"/queue/{qid}"))
    fell = (f", the reel could not be made ({reel_failed[0]})" if reel_failed
            else f", {asked} wanted but too few photos passed" if asked != design else "")
    return (f"{'DRY RUN ' if ctx.dry_run else ''}drafted post #{qid} for {day} ({kind_used}"
            f"{', instead of ' + want if kind_used != want else ''}): {design} with {len(photo_ids)} photo(s){fell}, "
            f"photo {hero['id']} first, captions by {writer} for \"{plan.primary}\", art director: {art.get('verdict')}")


def run(ctx: runner.Context, fetch: Optional[Callable[[dict], bytes]] = None) -> str:
    if fetch is None:
        from ..drive import oauth
        from ..drive.api import DriveReader
        try:
            oauth.access_token(ctx.conn)   # fail the run now if the sign-in is dead, not photo by photo
            reader = DriveReader(lambda: oauth.access_token(ctx.conn), conn=ctx.conn, agent=ctx.agent)
        except oauth.DriveAuthError as e:
            runner.record_error_once(ctx.conn, ctx.agent, "drive_auth", str(e))
            return f"not signed in: {e}"

        def fetch(row):
            cached = ctx.cfg.data_root / "photos" / f"{row['drive_id']}.img"
            return cached.read_bytes() if cached.exists() else reader.download(row["drive_id"])
    return draft_one(ctx, fetch)


if __name__ == "__main__":
    runner.main_for("content", run)
