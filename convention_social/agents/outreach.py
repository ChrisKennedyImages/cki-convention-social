"""Outreach agent (daily 09:00): notes to event organizers, drafted for Chris; each leaves only on his Approve.

1. Pull opt-outs from eventcaliber.com (outreach/site.py) and put each
   address on do-not-contact, closing its open rows. This happens in dry run
   too: it only moves the opt-out onto the Mini. A live run sends nothing if
   the opt-outs could not be pulled (fail closed).
2. Draft up to OUTREACH_DAILY_DRAFTS (default 5) a day: prospects Chris added
   by hand first, then scout events with an organizer email that is not on
   do-not-contact, one note per address per event (outreach/draft.py).
3. Send only what Chris approved, at most OUTREACH_DAILY_SENDS (default 10) a
   day, each through outreach.compliance (accurate From, postal address in
   the footer, opt-out link and reply STOP line, List-Unsubscribe headers,
   do-not-contact checked again, the one follow-up only 7 days or more after
   the first). Dry run writes the complete email to DATA_ROOT/outbox-dry
   (status would_send) and never sends.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..core import config, db, mail, runner
from ..outreach import compliance, draft, keys
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


def start_of_today(cfg: config.Config, now: datetime | None = None) -> str:
    """Local midnight (TIMEZONE) as a UTC timestamp in db.utcnow()'s format, for the daily caps."""
    try:
        tz = ZoneInfo(cfg.timezone)
    except Exception:  # noqa: BLE001
        tz = timezone.utc
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


def draft_new(ctx: runner.Context, client=None) -> dict:
    stats = {"drafted": 0, "claude": 0, "template": 0, "skipped_blocked": 0, "left_for_tomorrow": 0}
    made_today = db.one(ctx.conn, "SELECT COUNT(*) n FROM outreach WHERE kind='first' AND drafted_at >= ?",
                        (start_of_today(ctx.cfg),))["n"]
    room = max(0, daily_drafts() - made_today)
    today = datetime.now(timezone.utc).date().isoformat()

    def count(d: draft.OutreachDraft):
        stats["drafted"] += 1
        stats["template" if d.model == "template" else "claude"] += 1

    # prospects Chris added by hand
    for row in db.rows(ctx.conn, "SELECT * FROM outreach WHERE status='queued' ORDER BY id"):
        if compliance.blocked(ctx.conn, row["email"]):
            compliance.block(ctx.conn, row["email"])          # closes it with the reason
            stats["skipped_blocked"] += 1
            continue
        if room <= 0:
            stats["left_for_tomorrow"] += 1
            continue
        d = draft.draft_first(ctx.conn, row, client=client, agent=ctx.agent)
        _save_draft(ctx, row["id"], d)
        count(d)
        room -= 1

    # scout finds with an organizer email
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).replace(microsecond=0).isoformat()
    for ev in db.rows(ctx.conn, "SELECT * FROM scout_events WHERE status IN ('new','added') AND COALESCE(organizer_email,'') != '' "
                                "AND (start_date IS NULL OR start_date >= ?) ORDER BY COALESCE(start_date,'9999'), id", (today,)):
        email = keys.normalize_email(ev["organizer_email"])
        if not keys.valid_email(email):
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
        d = draft.draft_first(ctx.conn, facts, client=client, agent=ctx.agent)
        now = db.utcnow()
        db.insert(ctx.conn, "outreach", kind="first", scout_event_id=ev["id"], event_key=ev["dedup_key"], event_name=ev["name"],
                  event_kind=ev["kind"], start_date=ev["start_date"], end_date=ev["end_date"], city=ev["city"], venue=ev["venue"],
                  website=ev["website"], organizer=ev["organizer"], email=email, subject=d.subject, body=d.body,
                  status="draft", token=keys.new_token(), model=d.model, notes=d.note or None, drafted_at=now,
                  created_at=now, updated_at=now)
        count(d)
        room -= 1
    return stats


# ---------------------------------------------------------------------- 3. sends
def send_approved(ctx: runner.Context, *, opt_outs_synced: bool) -> dict:
    stats = {"sent": 0, "would_send": 0, "failed": 0, "held": 0, "redrafted": 0, "opted_out": 0, "over_cap": 0}
    used = db.one(ctx.conn, "SELECT COUNT(*) n FROM outreach WHERE status IN ('sent','would_send') AND last_attempt_at >= ?",
                  (start_of_today(ctx.cfg),))["n"]
    room = max(0, daily_sends() - used)
    for row in db.rows(ctx.conn, "SELECT * FROM outreach WHERE status='approved' ORDER BY approved_at, id"):
        found = compliance.problems(ctx.conn, row, cfg=ctx.cfg)
        codes = {p.code for p in found}
        now = db.utcnow()
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


def run(ctx: runner.Context, api: UnsubscribeAPI | None = None, client=None) -> str:
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
    d = draft_new(ctx, client=client)
    s = send_approved(ctx, opt_outs_synced=synced)
    return (f"{'DRY RUN ' if ctx.dry_run else ''}{opt}; drafted={d['drafted']} (claude={d['claude']} template={d['template']}, "
            f"left for tomorrow={d['left_for_tomorrow']}, on do-not-contact={d['skipped_blocked']}); "
            f"sent={s['sent']} would_send={s['would_send']} failed={s['failed']} held={s['held']} back to draft={s['redrafted']} "
            f"opted out={s['opted_out']} over the daily cap={s['over_cap']}")


if __name__ == "__main__":
    runner.main_for("outreach", run)
