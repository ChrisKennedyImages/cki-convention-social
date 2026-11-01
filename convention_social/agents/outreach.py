"""Outreach agent (daily 09:00): notes to event organizers, drafted for Chris; each leaves only on his Approve.

1. Pull opt-outs from eventcaliber.com (outreach/site.py) and put each
   address on do-not-contact, closing its open rows. This happens in dry run
   too: it only moves the opt-out onto the Mini. A live run sends nothing if
   the opt-outs could not be pulled (fail closed).
2. Read the scout's events off their own sites (outreach/emails.py): a person's
   address before a shared inbox, and the dates of an event that has none
   (outreach/dates.py, one small Claude read, live only). A waiting draft
   follows its event: a person's address found on a second look, dates found
   (follow_events).
3. Draft up to OUTREACH_DAILY_DRAFTS (default 5) a day, no asking (Chris,
   2026-11-01: "I would rather them all just be converted to drafts and the
   events need to be at least 3 months out"): prospects Chris added by hand
   first, then every scout event dated three calendar months or more out
   (scout.earliest_start) with an organizer email that is not on
   do-not-contact, one note per address per event (outreach/draft.py). A
   draft whose event is now under three months away, or whose dates were not
   found, is taken out of the drafts with a note. CPAC, the ACU and their
   affiliates are never drafted for, never sent to and never added by hand
   (outreach/compliance.never_contact; Chris, 2026-10-13).
4. Send only what Chris approved, at most OUTREACH_DAILY_SENDS (default 10) a
   day, Monday to Friday, each through outreach.compliance (accurate From,
   postal address in the footer, opt-out link and reply STOP line,
   List-Unsubscribe headers, do-not-contact checked again, the one follow-up
   only 7 days or more after the first). A first note whose event is now
   under three months away is not sent, and never goes. Dry run writes the
   complete email to DATA_ROOT/outbox-dry (status would_send) and never sends.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..core import config, db, mail, notify, runner
from ..outreach import compliance, dates, draft, emails, keys
from ..outreach.site import UnsubscribeAPI
from . import scout

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
    """The clock the weekday gate and the three-month rule read; tests pin it to a known day."""
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


# ---------------------------------------------------------------------- the three-month rule
THREE_MONTHS = "Organizer notes go only for events three months or more away (Chris, 2026-11-01)."


def earliest_start(cfg: config.Config, now: datetime | None = None) -> date:
    """Three calendar months after today in the founder's zone, on this agent's clock (scout.earliest_start)."""
    return scout.earliest_start(scout.local_today(cfg, now or now_utc()))


def too_soon(row, earliest: date) -> Optional[str]:
    """Why the three-month rule stops this first note, or None. An event that starts before `earliest` never gets one; an
    event the scout found needs its dates known; a prospect Chris added by hand may be undated (his own call)."""
    start = keys.iso_day(row["start_date"])
    if start and start < earliest.isoformat():
        return f"the event starts {keys.in_words(start)}, under three months away"
    if not start and row["scout_event_id"]:
        return "the event's dates were not found on its site"
    return None


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


def follow_events(ctx: runner.Context, earliest: date) -> dict:
    """2026-11-01: a first note waiting for Chris follows its event. Dates found on the event's site go on the note (an
    untouched note is written again in his template, so its first line names them; one he edited keeps his words); a
    person's address found on a second look takes the place of the shared inbox; and a note the three-month rule now
    stops (dated under three months away, or a scouted event whose dates were not found) is taken out of the drafts with
    the reason. A scouted event whose dates are still to be read (the cap or the API stopped the read) keeps its note
    waiting, and the send step would refuse it undated. An approved note is never touched here: the send step checks it."""
    stats = {"moved": 0, "redated": 0, "withdrawn": 0, "waiting": 0}
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).replace(microsecond=0).isoformat()
    for row in db.rows(ctx.conn, """
            SELECT o.*, e.organizer_email AS ev_email, e.email_source_url AS ev_page, e.start_date AS ev_start, e.end_date AS ev_end,
                   e.dates_checked_at AS ev_dates_checked, e.dates_note AS ev_dates_note, COALESCE(e.website, '') AS ev_site
            FROM outreach o LEFT JOIN scout_events e ON e.id = o.scout_event_id
            WHERE o.kind = 'first' AND o.status = 'draft' ORDER BY o.id"""):
        now = db.utcnow()
        untouched = row["updated_at"] == row["drafted_at"]
        # a change the agent makes keeps an untouched note untouched (drafted_at moves with updated_at), so it is
        # still written again in the template later; an edit of Chris's stays his
        stamp = "drafted_at = CASE WHEN updated_at = drafted_at THEN ? ELSE drafted_at END, updated_at = ?"
        facts = dict(row)
        if row["scout_event_id"] and row["ev_start"]:
            facts.update(start_date=row["ev_start"], end_date=row["ev_end"])
        why = too_soon(facts, earliest)
        if why and not facts["start_date"] and row["ev_site"] and not row["ev_dates_checked"]:
            ctx.conn.execute(f"UPDATE outreach SET notes=?, {stamp} WHERE id=?",
                             (f"Waiting for the event's dates to be read off its site ({row['ev_dates_note'] or 'not read yet'}). "
                              f"{THREE_MONTHS}", now, now, row["id"]))
            stats["waiting"] += 1
            continue
        if why:
            ctx.conn.execute("UPDATE outreach SET status='rejected', notes=?, updated_at=? WHERE id=?",
                             (f"Taken out of the drafts: {why}. {THREE_MONTHS}", now, row["id"]))
            stats["withdrawn"] += 1
            continue
        if (facts["start_date"], facts["end_date"]) != (row["start_date"], row["end_date"]):
            stats["redated"] += 1
            if untouched:
                d = draft.draft_first(facts)
                ctx.conn.execute(f"UPDATE outreach SET start_date=?, end_date=?, subject=?, body=?, model=?, notes=?, {stamp} WHERE id=?",
                                 (facts["start_date"], facts["end_date"], d.subject, d.body, d.model, d.note or None, now, now, row["id"]))
            else:
                ctx.conn.execute(f"UPDATE outreach SET start_date=?, end_date=?, notes=?, {stamp} WHERE id=?",
                                 (facts["start_date"], facts["end_date"],
                                  f"Dates found on their site: {keys.dates_in_words(facts['start_date'], facts['end_date'])}. "
                                  "Your words are kept as you wrote them.", now, now, row["id"]))
        new = keys.normalize_email(row["ev_email"] or "")
        if row["scout_event_id"] and keys.valid_email(new) and new != row["email"] and emails.is_role(row["email"]) \
                and not emails.is_role(new):
            held = (compliance.never_contact(email=new, names=(row["event_name"], row["organizer"] or ""), urls=(row["website"] or "",))
                    or ("on the do-not-contact list" if compliance.blocked(ctx.conn, new) else None)
                    or ("there is already a note to that address for this event" if db.one(
                        ctx.conn, "SELECT 1 FROM outreach WHERE email=? AND event_key=? AND kind='first'", (new, row["event_key"])) else None)
                    or ("a note to that address is open, or went out lately" if busy(ctx.conn, new, since) else None))
            if held:
                ctx.conn.execute(f"UPDATE outreach SET notes=?, {stamp} WHERE id=?",
                                 (f"A person's address was found on their site, {new}, but it is not used: {held}.", now, now, row["id"]))
                continue
            ctx.conn.execute(f"UPDATE outreach SET email=?, notes=?, {stamp} WHERE id=?",
                             (new, f"Now to {new}, a person's address on their site ({row['ev_page'] or row['website']}), "
                                   f"not the shared inbox {row['email']}.", now, now, row["id"]))
            stats["moved"] += 1
    return stats


def draft_new(ctx: runner.Context) -> dict:
    stats = {"drafted": 0, "rewritten": retemplate_unapproved(ctx.conn), "skipped_blocked": 0, "skipped_never": 0,
             "too_soon": 0, "left_for_tomorrow": 0}
    made_today = db.one(ctx.conn, "SELECT COUNT(*) n FROM outreach WHERE kind='first' AND drafted_at >= ?",
                        (start_of_today(ctx.cfg),))["n"]
    room = max(0, daily_drafts() - made_today)
    earliest = earliest_start(ctx.cfg)

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
        why = too_soon(row, earliest)
        if why:
            ctx.conn.execute("UPDATE outreach SET status='rejected', notes=?, updated_at=? WHERE id=?",
                             (f"Not drafted: {why}. {THREE_MONTHS}", db.utcnow(), row["id"]))
            stats["too_soon"] += 1
            continue
        if room <= 0:
            stats["left_for_tomorrow"] += 1
            continue
        d = draft.draft_first(row)
        _save_draft(ctx, row["id"], d)
        stats["drafted"] += 1
        room -= 1

    # every scout find dated three months or more out with an organizer email: no asking (2026-11-01)
    since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).replace(microsecond=0).isoformat()
    for ev in db.rows(ctx.conn, "SELECT * FROM scout_events WHERE status IN ('new','added') AND COALESCE(organizer_email,'') != '' "
                                "AND start_date IS NOT NULL AND start_date >= ? ORDER BY start_date, id", (earliest.isoformat(),)):
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
    stats = {"sent": 0, "would_send": 0, "failed": 0, "held": 0, "redrafted": 0, "opted_out": 0, "never": 0, "too_soon": 0,
             "over_cap": 0, "weekend": 0}
    if not sending_day(ctx.cfg):
        for row in db.rows(ctx.conn, "SELECT id FROM outreach WHERE status='approved' ORDER BY id"):
            ctx.conn.execute("UPDATE outreach SET notes=?, updated_at=? WHERE id=?", (WEEKEND_NOTE, db.utcnow(), row["id"]))
            stats["weekend"] += 1
        return stats
    used = db.one(ctx.conn, "SELECT COUNT(*) n FROM outreach WHERE status IN ('sent','would_send') AND last_attempt_at >= ?",
                  (start_of_today(ctx.cfg),))["n"]
    room = max(0, daily_sends() - used)
    earliest = earliest_start(ctx.cfg)
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
        why = too_soon(row, earliest) if row["kind"] == "first" else None
        if why:                                    # approved, but the event is now too near: closed, so it never goes
            ctx.conn.execute("UPDATE outreach SET status='rejected', notes=?, updated_at=? WHERE id=?",
                             (f"Not sent: {why}. {THREE_MONTHS}", now, row["id"]))
            stats["too_soon"] += 1
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
    # 2026-10-30: the organizer's address is read off the event's own site first (outreach/emails.py); the scout had found
    # eight events and an address for none, so nothing was ever drafted ("Not one outreach email has been sent").
    # 2026-11-01: a person's address before a shared inbox, and the dates of an event that has none (outreach/dates.py)
    earliest = earliest_start(ctx.cfg)
    reader, no_dates = dates.reader(ctx.conn, dry_run=ctx.dry_run, client=client, agent=ctx.agent)
    looked = emails.look_up(ctx.conn, today=scout.local_today(ctx.cfg, now_utc()), earliest=earliest, reader=reader)
    followed = follow_events(ctx, earliest)
    d = draft_new(ctx)
    if d["drafted"]:
        n = d["drafted"]
        notify.push(f"{ctx.cfg.brand_name}: organizer notes to approve", f"{n} organizer note{'s' if n != 1 else ''} drafted. Tap to read them; nothing leaves without your Approve.",
                    dry_run=ctx.dry_run, priority="default", click=notify.link("/outreach"), conn=ctx.conn, agent=ctx.agent)
    s = send_approved(ctx, opt_outs_synced=synced)
    return (f"{'DRY RUN ' if ctx.dry_run else ''}{opt}; events three months or more out from {earliest.isoformat()}; "
            f"sites walked={looked['looked']} addresses found={looked['found']} people={looked['people']} "
            f"second looks={looked['second_looks']} refused={looked['refused']}; dates read={looked['dates_read']} "
            f"found={looked['dated']}{'' if reader else f' ({no_dates})'}; drafts moved to a person={followed['moved']} "
            f"given dates={followed['redated']} taken out={followed['withdrawn']} waiting for dates={followed['waiting']}; "
            f"drafted={d['drafted']} (rewritten in the template={d['rewritten']}, "
            f"left for tomorrow={d['left_for_tomorrow']}, on do-not-contact={d['skipped_blocked']}, never contacted={d['skipped_never']}, "
            f"under three months={d['too_soon']}); "
            f"sent={s['sent']} would_send={s['would_send']} failed={s['failed']} held={s['held']} back to draft={s['redrafted']} "
            f"opted out={s['opted_out']} never={s['never']} under three months={s['too_soon']} over the daily cap={s['over_cap']} "
            f"held for Monday={s['weekend']}")


if __name__ == "__main__":
    runner.main_for("outreach", run)
