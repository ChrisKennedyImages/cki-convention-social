"""Outreach agent (daily 09:00): notes to event organizers, drafted for Chris; each leaves only on his Approve.

1. Pull opt-outs from eventcaliber.com (outreach/site.py) and put each
   address on do-not-contact, closing its open rows. This happens in dry run
   too: it only moves the opt-out onto the Mini. A live run sends nothing if
   the opt-outs could not be pulled (fail closed).
2. Draft up to OUTREACH_DAILY_DRAFTS (default 5) a day: prospects Chris added
   by hand first, then scout events with an organizer email that is not on
   do-not-contact, one note per address per event (outreach/draft.py).
   CPAC, the ACU and their affiliates are never drafted for, never sent to and
   never added by hand (outreach/compliance.never_contact; Chris, 2026-10-13).
3. Send only what Chris approved, at most OUTREACH_DAILY_SENDS (default 10) a
   day, each through outreach.compliance (accurate From, postal address in
   the footer, opt-out link and reply STOP line, List-Unsubscribe headers,
   do-not-contact checked again, the one follow-up only 7 days or more after
   the first). Dry run writes the complete email to DATA_ROOT/outbox-dry
   (status would_send) and never sends.
"""
from __future__ import annotations

import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..core import config, db, mail, notify, runner
from ..outreach import compliance, draft, emails, keys
from ..outreach.site import UnsubscribeAPI

DEFAULT_DAILY_DRAFTS = 5
DEFAULT_DAILY_SENDS = 10
RECENT_DAYS = 30            # an address with a note open, or sent this recently, is not drafted again for another event


def _int(key: str, default: int) -> int:
    try:
        return max(0, int(config.getenv(key) or default))
    except ValueError:
        return default


def daily_drafts() -> int:
    return _int("OUTREACH_DAILY_DRAFTS", DEFAULT_DAILY_DRAFTS)


def daily_sends() -> int:
    return _int("OUTREACH_DAILY_SENDS", DEFAULT_DAILY_SENDS)


def _tz(cfg: config.Config):
    try:
        return ZoneInfo(cfg.timezone)
    except Exception:  # noqa: BLE001
        return timezone.utc


def now_utc() -> datetime:
    """The clock the weekday gate reads; tests pin it to a known day."""
    return datetime.now(timezone.utc)


def sending_day(cfg: config.Config, now: datetime | None = None) -> bool:
    """Monday to Friday in the founder's zone. Chris, 2026-10-31: "I only want them sent Monday - Friday and not on weekends."
    The agent fires every day at 09:00; on a Saturday or Sunday the approved notes wait, and Monday's run sends them."""
    return (now or now_utc()).astimezone(_tz(cfg)).weekday() < 5


WEEKEND_NOTE = "Held for Monday: organizer notes go out Monday to Friday only."


def start_of_today(cfg: config.Config, now: datetime | None = None) -> str:
    """Local midnight (TIMEZONE) as a UTC timestamp in db.utcnow()'s format, for the daily caps."""
    tz = _tz(cfg)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    midnight = datetime.combine(local.date(), time(0, 0), tzinfo=tz)
    return midnight.astimezone(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------- 1. opt-outs
def sync_opt_outs(ctx: runner.Context, api: UnsubscribeAPI) -> dict:
    stats = {"pulled": 0, "blocked": 0, "unknown": 0, "acked": 0}
    items = api.pull()
    done: list[str] = []
    for item in items:
        token = str(item.get("token") or "")
        if not keys.TOKEN.match(token):
            continue
        stats["pulled"] += 1
        row = db.one(ctx.conn, "SELECT email FROM outreach WHERE token=?", (token,))
        if row is None:
            stats["unknown"] += 1
        else:
            compliance.block(ctx.conn, row["email"], source="unsubscribe", reason=f"opt-out link {str(item.get('received_at') or '')[:10]}".strip())
            stats["blocked"] += 1
        done.append(token)
    stats["acked"] = api.ack(done)     # only after each address is safely on do-not-contact here
    return stats


# ---------------------------------------------------------------------- 2. drafts
def busy(conn, email: str, since: str) -> bool:
    """A note to this address is open, or one was sent recently: do not start another for a different event."""
    return db.one(conn, "SELECT 1 FROM outreach WHERE email=? AND (status IN ('queued','draft','approved') OR "
                        "(status IN ('sent','would_send') AND COALESCE(sent_at, last_attempt_at, '') >= ?))",
                  (email, since)) is not None


def _save_draft(ctx: runner.Context, row_id: int, d: draft.OutreachDraft) -> None:
    now = db.utcnow()
    ctx.conn.execute("UPDATE outreach SET subject=?, body=?, model=?, notes=?, status='draft', drafted_at=?, updated_at=? WHERE id=?",
                     (d.subject, d.body, d.model, d.note or None, now, now, row_id))


def retemplate_unapproved(conn) -> int:
    """2026-10-31: first notes Claude drafted that Chris has not touched are rewritten in his template (draft.py), so what he
    reads on the Outreach page is the note he asked for. An edited draft (updated since it was drafted) is his and stays."""
    n = 0
    for row in db.rows(conn, "SELECT * FROM outreach WHERE kind='first' AND status='draft' AND model NOT IN ('template', 'chris') "
                            "AND updated_at = drafted_at ORDER BY id"):
        d = draft.draft_first(row)
        conn.execute("UPDATE outreach SET subject=?, body=?, model=?, notes=?, updated_at=? WHERE id=?",
                     (d.subject, d.body, d.model, d.note or None, db.utcnow(), row["id"]))
        n += 1
    return n


def draft_new(ctx: runner.Context) -> dict:
    stats = {"drafted": 0, "rewritten": retemplate_unapproved(ctx.conn), "skipped_blocked": 0, "skipped_never": 0, "left_for_tomorrow": 0}
    made_today = db.one(ctx.conn, "SELECT COUNT(*) n FROM outreach WHERE kind='first' AND drafted_at >= ?",
                        (start_of_today(ctx.cfg),))["n"]
    room = max(0, daily_drafts() - made_today)
    today = datetime.now(timezone.utc).date().isoformat()

    # prospects Chris added by hand
    for row in db.rows(ctx.conn, "SELECT * FROM outreach WHERE status='queued' ORDER BY id"):
        never = compliance.never_for_row(row)
        if never:
            ctx.conn.execute("UPDATE outreach SET status='rejected', notes=?, updated_at=? WHERE id=?", (never, db.utcnow(), row["id"]))
            stats["skipped_never"] += 1
            continue
        if compliance.blocked(ctx.conn, row["email"]):
            compliance.block(ctx.conn, row["email"])          # closes it with the reason
            stats["skipped_blocked"] += 1
            continue
        if room <= 0:
            stats["left_for_tomorrow"] += 1
            continue
        d = draft.draft_first(row)
        _save_draft(ctx, row["id"], d)
        stats["drafted"] += 1
        room -= 1

    # scout finds with an organizer email
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).replace(microsecond=0).isoformat()
    for ev in db.rows(ctx.conn, "SELECT * FROM scout_events WHERE status IN ('new','added') AND COALESCE(organizer_email,'') != '' "
                                "AND (start_date IS NULL OR start_date >= ?) ORDER BY COALESCE(start_date,'9999'), id", (today,)):
        email = keys.normalize_email(ev["organizer_email"])
        if not keys.valid_email(email):
            continue
        if compliance.never_for_event(ev):
            stats["skipped_never"] += 1
            continue
        if compliance.blocked(ctx.conn, email):
            stats["skipped_blocked"] += 1
            continue
        if db.one(ctx.conn, "SELECT 1 FROM outreach WHERE email=? AND event_key=? AND kind='first'", (email, ev["dedup_key"])):
            continue
        if busy(ctx.conn, email, since):
            continue
        if room <= 0:
            stats["left_for_tomorrow"] += 1
            continue
        facts = {"event_name": ev["name"], "event_kind": ev["kind"], "start_date": ev["start_date"], "end_date": ev["end_date"],
                 "city": ev["city"], "venue": ev["venue"], "organizer": ev["organizer"]}
        d = draft.draft_first(facts)
        now = db.utcnow()
        db.insert(ctx.conn, "outreach", kind="first", scout_event_id=ev["id"], event_key=ev["dedup_key"], event_name=ev["name"],
                  event_kind=ev["kind"], start_date=ev["start_date"], end_date=ev["end_date"], city=ev["city"], venue=ev["venue"],
                  website=ev["website"], organizer=ev["organizer"], email=email, subject=d.subject, body=d.body,
                  status="draft", token=keys.new_token(), model=d.model, notes=d.note or None, drafted_at=now,
                  created_at=now, updated_at=now)
        stats["drafted"] += 1
        room -= 1
    return stats


# ---------------------------------------------------------------------- 3. sends
def send_approved(ctx: runner.Context, *, opt_outs_synced: bool) -> dict:
    stats = {"sent": 0, "would_send": 0, "failed": 0, "held": 0, "redrafted": 0, "opted_out": 0, "never": 0, "over_cap": 0, "weekend": 0}
    if not sending_day(ctx.cfg):
        for row in db.rows(ctx.conn, "SELECT id FROM outreach WHERE status='approved' ORDER BY id"):
            ctx.conn.execute("UPDATE outreach SET notes=?, updated_at=? WHERE id=?", (WEEKEND_NOTE, db.utcnow(), row["id"]))
            stats["weekend"] += 1
        return stats
    used = db.one(ctx.conn, "SELECT COUNT(*) n FROM outreach WHERE status IN ('sent','would_send') AND last_attempt_at >= ?",
                  (start_of_today(ctx.cfg),))["n"]
    room = max(0, daily_sends() - used)
    for row in db.rows(ctx.conn, "SELECT * FROM outreach WHERE status='approved' ORDER BY approved_at, id"):
        found = compliance.problems(ctx.conn, row, cfg=ctx.cfg)
        codes = {p.code for p in found}
        now = db.utcnow()
        if "never" in codes:                       # the hard rule, checked again at the door, whatever was approved
            ctx.conn.execute("UPDATE outreach SET status='rejected', notes=?, updated_at=? WHERE id=?",
                             (next(p.message for p in found if p.code == "never"), now, row["id"]))
            stats["never"] += 1
            continue
        if "blocked" in codes:
            ctx.conn.execute("UPDATE outreach SET status='opted_out', notes=?, updated_at=? WHERE id=?",
                             ("On the do-not-contact list; not sent.", now, row["id"]))
            stats["opted_out"] += 1
            continue
        if codes & compliance.REDRAFT_CODES:       # edited into something that may not go: back to Chris
            ctx.conn.execute("UPDATE outreach SET status='draft', notes=?, updated_at=? WHERE id=?",
                             (" ".join(p.message for p in found), now, row["id"]))
            stats["redrafted"] += 1
            continue
        if found:                                  # a missing setting, or a follow-up not due yet: wait, still approved
            ctx.conn.execute("UPDATE outreach SET notes=?, updated_at=? WHERE id=?", (" ".join(p.message for p in found), now, row["id"]))
            stats["held"] += 1
            continue
        if not ctx.dry_run and not opt_outs_synced:
            ctx.conn.execute("UPDATE outreach SET notes=?, updated_at=? WHERE id=?",
                             ("Held: the opt-outs on the site could not be checked this run.", now, row["id"]))
            stats["held"] += 1
            continue
        if room <= 0:
            stats["over_cap"] += 1
            continue
        msg = compliance.build(row, ctx.cfg)
        res = mail.send(msg.subject, msg.html, to=row["email"], plain=msg.plain, reply_to=ctx.cfg.brand_from_email,
                        headers=msg.headers, dry_run=ctx.dry_run)
        now = db.utcnow()
        if res.sent:
            ctx.conn.execute("UPDATE outreach SET status='sent', sent_at=?, last_attempt_at=?, message_id=?, notes=NULL, updated_at=? WHERE id=?",
                             (now, now, res.message_id, now, row["id"]))
            stats["sent"] += 1
            room -= 1
        elif res.dry_run:
            ctx.conn.execute("UPDATE outreach SET status='would_send', last_attempt_at=?, notes=?, updated_at=? WHERE id=?",
                             (now, f"dry run: written to {res.path.name if res.path else 'outbox'}", now, row["id"]))
            stats["would_send"] += 1
            room -= 1
        else:
            ctx.conn.execute("UPDATE outreach SET status='failed', last_attempt_at=?, notes=?, updated_at=? WHERE id=?",
                             (now, res.error, now, row["id"]))
            runner.record_error(ctx.conn, ctx.agent, "outreach_send", f"outreach {row['id']}: {res.error}")
            stats["failed"] += 1
    return stats


def run(ctx: runner.Context, api: UnsubscribeAPI | None = None) -> str:
    api = api or UnsubscribeAPI.from_config()
    synced = False
    if api is None:
        opt = "opt-outs not pulled: no MEDIA_UPLOAD_TOKEN"
    else:
        try:
            s = sync_opt_outs(ctx, api)
            synced = True
            opt = f"opt-outs pulled={s['pulled']} blocked={s['blocked']} unknown={s['unknown']} acked={s['acked']}"
        except Exception as e:  # noqa: BLE001 — the site being down must not stop drafting; sends then hold
            runner.record_error(ctx.conn, ctx.agent, "opt_out_pull", f"{type(e).__name__}: {e}")
            opt = f"opt-outs not pulled ({type(e).__name__})"
    # 2026-10-30: the organizer's address is read off the event's own site first (outreach/emails.py); the scout had found
    # eight events and an address for none, so nothing was ever drafted ("Not one outreach email has been sent")
    looked = emails.lookup_missing(ctx.conn)
    d = draft_new(ctx)
    if d["drafted"]:
        n = d["drafted"]
        notify.push(f"{ctx.cfg.brand_name}: organizer notes to approve", f"{n} organizer note{'s' if n != 1 else ''} drafted. Tap to read them; nothing leaves without your Approve.",
                    dry_run=ctx.dry_run, priority="default", click=notify.link("/outreach"), conn=ctx.conn, agent=ctx.agent)
    s = send_approved(ctx, opt_outs_synced=synced)
    return (f"{'DRY RUN ' if ctx.dry_run else ''}{opt}; addresses looked for={looked['looked']} found={looked['found']} "
            f"refused={looked['refused']}; drafted={d['drafted']} (rewritten in the template={d['rewritten']}, "
            f"left for tomorrow={d['left_for_tomorrow']}, on do-not-contact={d['skipped_blocked']}, never contacted={d['skipped_never']}); "
            f"sent={s['sent']} would_send={s['would_send']} failed={s['failed']} held={s['held']} back to draft={s['redrafted']} "
            f"opted out={s['opted_out']} never={s['never']} over the daily cap={s['over_cap']} held for Monday={s['weekend']}")


if __name__ == "__main__":
    runner.main_for("outreach", run)
