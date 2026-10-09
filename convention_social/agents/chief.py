"""Chief of staff (daily at DIGEST_HOUR, local): one morning brief, leading with what needs Chris.

The crew's work in one place, ordered by what only Chris can do:

  Needs you     posts waiting for Approve, quote requests waiting for a reply,
                outreach drafts, new events the scout found, anything broken
                that an agent cannot fix (a dead Drive sign-in, a disconnected
                channel), and the Art director's turned-back drafts.
  Done          what was posted, replies sent, photos sorted, what the
                learner changed.
  Watching      spend against the cap, agents that missed a run, notes from
                the watchdog.

A three-sentence read of the day comes first: Claude writes it from the same
facts when live and under the cap; otherwise a plain sentence does. The brief
goes by email to ALERT_EMAIL (dry run: to the outbox) and as a phone push, and
is kept for the dashboard. The watchdog keeps the urgent alerts and hands its
daily digest to this agent.
"""
from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..ai import claude as claude_mod
from ..ai import copy_rules, spend
from ..core import config, db, mail, notify, runner, settings
from . import watchdog

SENT_KEY = "chief.brief_sent_on"
BRIEF_KEY = "chief.brief"
MODEL = "claude-opus-5-5"


def _count(conn, sql: str, params=()) -> int:
    try:
        return int(db.one(conn, sql, params)[0] or 0)
    except sqlite3.OperationalError:          # a table another agent owns may not exist yet
        return 0


def _rows(conn, sql: str, params=()) -> list:
    try:
        return [dict(r) for r in db.rows(conn, sql, params)]
    except sqlite3.OperationalError:
        return []


def gather(ctx: runner.Context, now: datetime) -> dict:
    conn = ctx.conn
    d = watchdog.digest_data(ctx, now)
    since = (now - timedelta(hours=24)).isoformat()
    turned_back = [r for r in _rows(conn, "SELECT id, rule_report FROM content_queue WHERE status='draft'")
                   if (json.loads(r["rule_report"] or "{}").get("art") or {}).get("verdict") in ("redo", "reject")]
    needs = []
    if d["waiting"]:
        needs.append((f"{len(d['waiting'])} post(s) waiting for your Approve.", "/"))
    req = _count(conn, "SELECT COUNT(*) FROM inquiries WHERE status IN ('new','drafted') AND reply_status IN ('none','draft')")
    if req:
        needs.append((f"{req} quote request(s) waiting for your reply.", "/inquiries"))
    outreach = _count(conn, "SELECT COUNT(*) FROM outreach WHERE status='draft'")
    if outreach:
        needs.append((f"{outreach} organizer email(s) drafted for your Approve.", "/outreach"))
    scout = _count(conn, "SELECT COUNT(*) FROM scout_events WHERE status='new'")
    if scout:
        needs.append((f"{scout} upcoming event(s) the scout found for you to look at.", "/scout"))
    if d["drive"] in ("expired", "missing"):
        needs.append(("Google Drive is " + ("signed out. Sign in again." if d["drive"] == "expired" else "not signed in yet."), "/drive"))
    for c in d["channels"]:
        if not c["connected"]:
            needs.append((f"{c['service'].capitalize()} is disconnected in Buffer. Reconnect it there.", "/agents"))
    if turned_back:
        needs.append((f"{len(turned_back)} draft(s) the Art director was not happy with.", "/"))
    done = []
    if d["published"]:
        done.append(f"Posted {len(d['published'])} time(s): " + ", ".join(sorted({p['service'] for p in d['published']})) + ".")
    sent = _count(conn, "SELECT COUNT(*) FROM inquiries WHERE reply_sent_at >= ?", (since,))
    if sent:
        done.append(f"Sent {sent} quote repl{'y' if sent == 1 else 'ies'}.")
    sorted_n = _count(conn, "SELECT COUNT(*) FROM classifications WHERE method IN ('ollama','vision') AND classified_at >= ?", (since,))
    if sorted_n:
        done.append(f"Sorted {sorted_n} photo(s) from the library.")
    learner = settings.get(conn, "learner.note") or ""
    if learner:
        done.append(f"Learner: {learner}")
    watching = [f"AI spend ${d['ai_mtd']:.2f} of the ${d['ai_cap']:.2f} monthly cap."]
    for a in d["agents"]:
        if a["built"] and a["last"] and a["last"]["ok"] == 0:
            watching.append(f"The {a['name']} agent's last run failed: {(a['last']['summary'] or '')[:100]}")
    try:
        watching += json.loads(settings.get(conn, "watchdog.notes") or "[]")[:6]
    except ValueError:
        pass
    return {"needs": needs, "done": done, "watching": watching, "failed": d["failed"], "errors": d["errors"],
            "would_publish": d["would_publish"]}


def plain_read(b: dict) -> str:
    if not b["needs"]:
        return "Nothing needs you this morning. The crew is on it."
    return f"{len(b['needs'])} thing(s) need you this morning. The first: {b['needs'][0][0]}"


def written_read(conn, b: dict, client=None, agent: str = "chief") -> str:
    """Claude's three sentences, or the plain one. Never a promise, never a dash."""
    if spend.cap_reached(conn):
        return plain_read(b)
    if client is None:
        from ..core import secrets
        if not secrets.get_secret("ANTHROPIC_API_KEY"):
            return plain_read(b)
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    facts = json.dumps({"needs": [n for n, _ in b["needs"]], "done": b["done"], "watching": b["watching"]})
    response = client.beta.messages.create(
        model=MODEL, max_tokens=1500, betas=[claude_mod.FALLBACK_BETA], fallbacks="default", thinking={"type": "adaptive"},
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
            "type": "object", "properties": {"read": {"type": "string"}}, "required": ["read"], "additionalProperties": False}}},
        system=("You are the chief of staff for a one-person photography company. From the facts, write at most three short, "
                "plain sentences for the owner's morning: what matters most today and why. Use only the facts given. "
                "No dashes, no hype, no exclamation marks. Return JSON."),
        messages=[{"role": "user", "content": facts}])
    u = response.usage
    spend.record(conn, agent, getattr(response, "model", None) or MODEL, int(u.input_tokens or 0), int(u.output_tokens or 0), "brief")
    text = next((x.text for x in response.content if x.type == "text"), None)
    if response.stop_reason == "refusal" or not text:
        return plain_read(b)
    read = claude_mod.tidy(json.loads(text).get("read") or "")
    return read if read and copy_rules.check(read).ok else plain_read(b)


def brief_html(cfg, b: dict, read: str, local: datetime) -> tuple[str, str]:
    e = html.escape
    base = watchdog.dashboard_url(cfg)

    def ul(items):
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else "<p style='color:#666'>Nothing.</p>"
    parts = [f"<h2>{e(cfg.brand_name)}, {e(local.strftime('%A %b %d'))}</h2>", f"<p style='font-size:17px'>{e(read)}</p>",
             "<h3>Needs you</h3>", ul([f"<a href='{e(base)}{e(href)}'>{e(text)}</a>" for text, href in b["needs"]]),
             "<h3>Done</h3>", ul([e(x) for x in b["done"]]),
             "<h3>Watching</h3>", ul([e(x) for x in b["watching"]])]
    if b["would_publish"]:
        parts.append(f"<p>The publisher is in dry run: {b['would_publish']} post(s) would have gone out.</p>")
    if b["failed"] or b["errors"]:
        parts.append("<h3>Broke</h3>" + ul([f"Post {x['id']}: {e(x['last_error'] or '')}" for x in b["failed"]] +
                                          [f"{e(x['agent'])}: {e(x['message'][:140])}" for x in b["errors"][:10]]))
    plain = read + "\n\nNeeds you:\n" + "\n".join(f"  {t}" for t, _ in b["needs"]) + "\n\nDone:\n" + "\n".join(f"  {x}" for x in b["done"])
    return "".join(parts), plain


def due(ctx: runner.Context, now: datetime) -> bool:
    local = watchdog.local_now(ctx.cfg, now)
    return local.hour >= ctx.cfg.digest_hour and settings.get(ctx.conn, SENT_KEY) != local.date().isoformat()


def run(ctx: runner.Context, *, now: Optional[datetime] = None, client=None, force: bool = False) -> str:
    now = now or datetime.now(timezone.utc)
    if not force and not due(ctx, now):
        return "brief not due"
    b = gather(ctx, now)
    read = plain_read(b) if ctx.dry_run else written_read(ctx.conn, b, client=client, agent=ctx.agent)
    local = watchdog.local_now(ctx.cfg, now)
    body, plain = brief_html(ctx.cfg, b, read, local)
    settings.set(ctx.conn, BRIEF_KEY, json.dumps({"date": local.date().isoformat(), "read": read, "needs": b["needs"],
                                                   "done": b["done"], "watching": b["watching"]}))
    res = mail.send(f"[{ctx.cfg.brand_name}] Morning brief: {len(b['needs'])} need you", body, to=ctx.cfg.alert_email or "",
                    plain=plain, dry_run=ctx.dry_run or not ctx.cfg.alert_email)
    notify.push(f"{ctx.cfg.brand_name}: {len(b['needs'])} need you", read, dry_run=ctx.dry_run, priority="default",
                click=watchdog.dashboard_url(ctx.cfg) + "/")
    settings.set(ctx.conn, SENT_KEY, local.date().isoformat())
    return f"{'DRY RUN ' if ctx.dry_run else ''}brief: {len(b['needs'])} need you, {len(b['done'])} done; mail {'written to outbox' if res.dry_run else ('sent' if res.sent else 'FAILED')}"


if __name__ == "__main__":
    import sys
    runner.main_for("chief", lambda ctx: run(ctx, force="--now" in sys.argv))
