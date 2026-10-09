"""Inbox agent (every 10 minutes): quote requests in, approved replies out, booked dates up.

1. Pull new quote requests from eventcaliber.com (the site keeps them only
   until the Mini has them), store each once, then tell the site to delete
   them. Pulling happens in dry run too: it only moves the request onto the Mini.
2. Draft a reply for each new request (ai/reply.py). Chris edits and approves
   it on the dashboard; nothing is sent before that.
3. Send the replies Chris approved. Dry run writes the complete email to
   DATA_ROOT/outbox-dry instead (status would_send).
4. Push the booked dates (dates only, no names) to the public calendar when
   they changed. Dry run skips the push.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

from ..ai import reply
from ..booking.remote import SiteAPI
from ..core import db, mail, runner, settings

AVAILABILITY_HASH = "availability.pushed_hash"
COLUMNS = ("name", "email", "phone", "organization", "event_name", "event_kind", "start_date", "end_date",
           "city", "venue", "attendance", "message")


def store(conn, item: dict) -> bool:
    """Insert one pulled request; False when it was already here (a pull that was not acked)."""
    if db.one(conn, "SELECT 1 FROM inquiries WHERE remote_id=?", (item.get("id"),)):
        return False
    vals = {k: (str(item.get(k) or "").strip() or None) for k in COLUMNS}
    if not vals["name"] or not vals["email"]:
        return False
    db.insert(conn, "inquiries", remote_id=str(item["id"]), received_at=str(item.get("received_at") or db.utcnow()),
              coverage=json.dumps([c for c in (item.get("coverage") or []) if isinstance(c, str)]),
              updated_at=db.utcnow(), **vals)
    return True


def pull(ctx: runner.Context, api: SiteAPI) -> tuple[int, int]:
    items = api.pull()
    new = sum(1 for it in items if it.get("id") and store(ctx.conn, it))
    stored = [it["id"] for it in items if it.get("id") and db.one(ctx.conn, "SELECT 1 FROM inquiries WHERE remote_id=?", (it["id"],))]
    acked = api.ack(stored)       # only what is safely in the Mini's database is deleted from the site
    return new, acked


def draft_new(ctx: runner.Context, client=None) -> int:
    n = 0
    for inq in db.rows(ctx.conn, "SELECT * FROM inquiries WHERE reply_status='none' AND status='new' ORDER BY id"):
        d = reply.draft(ctx.conn, inq, client=client, agent=ctx.agent)
        ctx.conn.execute("UPDATE inquiries SET reply_subject=?, reply_body=?, reply_status='draft', status='drafted', updated_at=? WHERE id=?",
                         (d.subject, d.body, db.utcnow(), inq["id"]))
        n += 1
    return n


def send_approved(ctx: runner.Context) -> dict:
    stats = {"sent": 0, "would_send": 0, "failed": 0, "held": 0}
    for inq in db.rows(ctx.conn, "SELECT * FROM inquiries WHERE reply_status='approved' ORDER BY id"):
        why = reply.ready_to_send(inq["reply_subject"] or "", inq["reply_body"] or "")
        if why:      # edited after approval into something that may not go: back to draft
            ctx.conn.execute("UPDATE inquiries SET reply_status='draft', notes=?, updated_at=? WHERE id=?", (why, db.utcnow(), inq["id"]))
            stats["held"] += 1
            continue
        body = f"{inq['reply_body'].rstrip()}\n\n--\n{reply.footer()}"
        html = "<div style=\"font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;white-space:pre-wrap\">" + \
               body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "</div>"
        res = mail.send(inq["reply_subject"], html, to=inq["email"], plain=body, reply_to=ctx.cfg.brand_from_email or None,
                        dry_run=ctx.dry_run)
        if res.sent:
            ctx.conn.execute("UPDATE inquiries SET reply_status='sent', status='replied', reply_sent_at=?, reply_message_id=?, updated_at=? WHERE id=?",
                             (db.utcnow(), res.message_id, db.utcnow(), inq["id"]))
            stats["sent"] += 1
        elif res.dry_run:
            ctx.conn.execute("UPDATE inquiries SET reply_status='would_send', notes=?, updated_at=? WHERE id=?",
                             (f"dry run: written to {res.path.name if res.path else 'outbox'}", db.utcnow(), inq["id"]))
            stats["would_send"] += 1
        else:
            ctx.conn.execute("UPDATE inquiries SET reply_status='failed', notes=?, updated_at=? WHERE id=?", (res.error, db.utcnow(), inq["id"]))
            runner.record_error(ctx.conn, ctx.agent, "reply_send", f"inquiry {inq['id']}: {res.error}")
            stats["failed"] += 1
    return stats


def booked_days(conn) -> list[str]:
    days: set[str] = set()
    for b in db.rows(conn, "SELECT start_date, end_date FROM bookings WHERE status='booked'"):
        try:
            d, end = date.fromisoformat(b["start_date"]), date.fromisoformat(b["end_date"] or b["start_date"])
        except ValueError:
            continue
        while d <= end and len(days) < 2000:
            days.add(d.isoformat())
            d += timedelta(days=1)
    return sorted(days)


def sync_availability(ctx: runner.Context, api: SiteAPI) -> str:
    days = booked_days(ctx.conn)
    digest = hashlib.sha256(json.dumps(days).encode()).hexdigest()
    if settings.get(ctx.conn, AVAILABILITY_HASH) == digest:
        return "calendar unchanged"
    if ctx.dry_run:
        return f"calendar would show {len(days)} booked day(s) (dry run)"
    api.put_availability(days)
    settings.set(ctx.conn, AVAILABILITY_HASH, digest)
    return f"calendar now shows {len(days)} booked day(s)"


def run(ctx: runner.Context, api: SiteAPI | None = None, client=None) -> str:
    api = api or SiteAPI.from_config()
    if api is None:
        new = acked = 0
        cal = "no MEDIA_UPLOAD_TOKEN: the site is not reachable yet"
    else:
        new, acked = pull(ctx, api)
        cal = None
    drafted = draft_new(ctx, client=client)
    sent = send_approved(ctx)
    if api is not None:
        cal = sync_availability(ctx, api)
    return (f"{'DRY RUN ' if ctx.dry_run else ''}requests new={new} acked={acked}; drafted={drafted}; "
            f"replies sent={sent['sent']} would_send={sent['would_send']} failed={sent['failed']} held={sent['held']}; {cal}")


if __name__ == "__main__":
    runner.main_for("inbox", run)
