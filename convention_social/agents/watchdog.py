"""Watchdog: hourly checks, immediate alerts, one digest a day. Reads everything, sends mail.

Checks: Google Drive sign-in (settings `drive.auth_state`), every Buffer
channel in `channels` still connected (Buffer's isDisconnected / isLocked),
posts newly `failed` or stuck in `scheduled`, the Buffer request budget, AI
spend against the monthly cap, each built agent's last run against its
schedule, the dashboard answering on localhost, disk free, backup age, and
errors the agents recorded since the last look.

Anything urgent goes out at once (one email to ALERT_EMAIL, plus a phone push
when NTFY_TOPIC is set), with a 6 hour suppression per problem so a broken
channel does not page every hour. An expired Drive sign-in is loud (urgent
push) and goes out once per local day. At DIGEST_HOUR local the digest goes
out once: posted, waiting, broke, spend. In dry run every email is written to
DATA_ROOT/outbox-dry instead.
"""
from __future__ import annotations

import html
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from ..agents import AGENTS, is_built
from ..ai import spend
from ..buffer import budget
from ..buffer.client import BufferClient, BufferError
from ..core import config, db, mail, notify, runner, settings
from . import pacing

# how long after its cadence an agent may be silent before we call it missed
MAX_GAP = {"scanner": timedelta(hours=3), "content": timedelta(hours=30), "publisher": timedelta(hours=1),
           "watchdog": timedelta(hours=2), "backup": timedelta(hours=36)}
STUCK_AFTER = timedelta(hours=6)       # a scheduled post this long past its time without being sent
SUPPRESS = timedelta(hours=6)
DISK_MIN_FREE = 10 * 1024 ** 3
BACKUP_MAX_AGE = timedelta(hours=36)

DRIVE_STATE_KEY = "drive.auth_state"   # written by drive/oauth.py (STATE_KEY): ok | expired | missing
DRIVE_ALERTED_KEY = "watchdog.drive_expired_alerted_on"
DRIVE_EXPIRED = "Google Drive sign-in has expired. Open the dashboard's Drive page and sign in again."
DRIVE_MISSING = "Google Drive is not signed in yet. Open the dashboard's Drive page and sign in."


def dashboard_url(cfg: config.Config) -> str:
    """The address Chris opens from his phone; the localhost one only when none is set."""
    return cfg.dashboard_public_url or f"http://127.0.0.1:{cfg.dashboard_port}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_now(cfg: config.Config, now: Optional[datetime] = None) -> datetime:
    return (now or now_utc()).astimezone(ZoneInfo(cfg.timezone))


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Findings:
    def __init__(self):
        self.alerts: list[tuple[str, str]] = []   # (code, message) urgent
        self.loud: set[str] = set()               # codes that push at urgent priority
        self.daily: set[str] = set()              # codes that go out once per local day, not every 6 hours
        self.notes: list[str] = []                # digest only

    def alert(self, code: str, message: str, *, loud: bool = False, daily: bool = False):
        self.alerts.append((code, message))
        if loud:
            self.loud.add(code)
        if daily:
            self.daily.add(code)

    def note(self, message: str):
        self.notes.append(message)


# ------------------------------------------------------------------ checks

def check_drive(ctx: runner.Context, f: Findings) -> None:
    state = (settings.get(ctx.conn, DRIVE_STATE_KEY) or "").strip().lower()
    if state == "expired":
        f.alert("drive_expired", DRIVE_EXPIRED, loud=True, daily=True)
    elif state == "missing":
        f.note(DRIVE_MISSING)


def check_channels(ctx: runner.Context, f: Findings, client: Optional[BufferClient]) -> None:
    linked = db.rows(ctx.conn, "SELECT * FROM channels ORDER BY id")
    if not linked:
        return
    if client is None:
        f.note("The Buffer channel check was skipped because BUFFER_API_KEY is not set.")
        return
    try:
        live = {c["id"]: c for c in client.channels(refresh=True)}
    except BufferError as e:
        f.alert("buffer_unreachable", f"Could not list the Buffer channels: {e}")
        return
    for ch in linked:
        info = live.get(ch["buffer_channel_id"])
        ok = bool(info) and not info.get("isDisconnected") and not info.get("isLocked")
        ctx.conn.execute("UPDATE channels SET connected=?, last_checked_at=? WHERE id=?", (1 if ok else 0, db.utcnow(), ch["id"]))
        label = f"{ch['service']} ({ch['display_name'] or ch['buffer_channel_id']})"
        if not info:
            f.alert(f"channel_missing:{ch['id']}", f"The {label} channel is gone from Buffer. Connect it again in Buffer.")
        elif info.get("isDisconnected"):
            f.alert(f"channel_disconnected:{ch['id']}", f"The {label} channel is DISCONNECTED in Buffer. Reconnect it in Buffer.")
        elif info.get("isLocked"):
            f.alert(f"channel_locked:{ch['id']}", f"The {label} channel is locked in Buffer, usually a plan limit.")
        elif info.get("isQueuePaused"):
            f.note(f"The Buffer queue is paused for {label}. Scheduled posts will not go out until it is resumed.")


def check_posts(ctx: runner.Context, f: Findings, now: datetime) -> None:
    since = (now - timedelta(hours=24)).isoformat()
    for row in db.rows(ctx.conn, "SELECT id, last_error FROM content_queue WHERE status='failed' AND updated_at >= ?", (since,)):
        f.alert(f"post_failed:{row['id']}", f"Post {row['id']} failed: {row['last_error'] or 'see the errors list'}")
    tz = ZoneInfo(ctx.cfg.timezone)
    for row in db.rows(ctx.conn, "SELECT * FROM content_queue WHERE status='scheduled'"):
        times = pacing.due_times(row, tz)
        latest = max(times.values()) if times else parse_ts(row["updated_at"])
        if latest and now - latest > STUCK_AFTER:
            f.alert(f"post_stuck:{row['id']}", f"Post {row['id']} is still waiting in Buffer, more than "
                                               f"{int(STUCK_AFTER.total_seconds() // 3600)} hours after its time.")


def check_budgets(ctx: runner.Context, f: Findings, now: datetime) -> None:
    for b in budget.snapshot(ctx.conn):
        if b["used"] >= b["ceiling"]:
            f.alert(f"buffer_budget:{b['window']}", f"Buffer API {b['window']} window: {b['used']} of {b['limit']} requests used. The agents are holding.")
        elif b["used"] >= b["limit"] * 0.6:
            f.note(f"Buffer API {b['window']} window is at {b['used']} of {b['limit']}.")
    mtd = spend.month_to_date(ctx.conn)
    cap = ctx.cfg.ai_monthly_cap_usd
    if cap > 0 and mtd >= cap:
        f.alert("ai_cap", f"AI spend ${mtd:.2f} has reached the ${cap:.2f} monthly cap. Caption drafting is paused.")
    elif cap > 0 and mtd >= cap * 0.8:
        f.note(f"AI spend is ${mtd:.2f} of the ${cap:.2f} cap, past 80%.")
    zero = db.one(ctx.conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='anthropic' AND cost_usd=0 AND ts >= ?",
                  ((now - timedelta(days=1)).isoformat(),))["n"]
    if zero:
        f.note(f"{zero} AI call(s) in the last day were counted at no cost because the model has no known price.")


def check_agents(ctx: runner.Context, f: Findings, now: datetime) -> None:
    for name, gap in MAX_GAP.items():
        if name == ctx.agent or not is_built(name):
            continue
        last = db.one(ctx.conn, "SELECT started_at, ok FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT 1", (name,))
        if not last:
            f.note(f"{name} has never run.")
            continue
        started = parse_ts(last["started_at"])
        if started and now - started > gap:
            f.alert(f"agent_missed:{name}", f"{name} last ran {started.astimezone(ZoneInfo(ctx.cfg.timezone)).strftime('%b %d %H:%M')}. "
                                            f"It should run {AGENTS[name]['schedule']}.")
        elif last["ok"] == 0:
            f.note(f"{name} failed on its last run. See the errors list.")


def check_dashboard(ctx: runner.Context, f: Findings, probe=None) -> None:
    url = f"http://127.0.0.1:{ctx.cfg.dashboard_port}/login"
    try:
        if probe is None:
            import urllib.request
            with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310  localhost only
                code = r.status
        else:
            code = probe(url)
    except Exception as e:  # noqa: BLE001
        f.alert("dashboard_down", f"The review dashboard is not answering on {url} ({type(e).__name__}).")
        return
    if code == 503:
        f.alert("dashboard_no_password", "The dashboard is up but has no password set.")


def check_disk_and_backups(ctx: runner.Context, f: Findings, now: datetime) -> None:
    free = shutil.disk_usage(ctx.cfg.data_root).free
    if free < DISK_MIN_FREE:
        f.alert("disk_low", f"Only {free / 1024**3:.1f} GB free on the drive holding {ctx.cfg.data_root}.")
    backups = sorted((ctx.cfg.data_root / "backups").glob("*.sqlite3"))
    if backups:
        age = now - datetime.fromtimestamp(backups[-1].stat().st_mtime, tz=timezone.utc)
        if age > BACKUP_MAX_AGE:
            f.alert("backup_stale", f"The newest database backup is {age.days}d {age.seconds // 3600}h old.")
    elif is_built("backup"):
        f.note("No database backup exists yet.")


def collect_new_errors(ctx: runner.Context, f: Findings) -> list[int]:
    rows = db.rows(ctx.conn, "SELECT * FROM errors WHERE notified_at IS NULL ORDER BY id")
    ids = []
    for r in rows:
        ids.append(r["id"])
        if r["agent"] == ctx.agent:
            continue
        f.alert(f"error:{r['kind']}", f"{r['agent']}: {r['kind']}: {r['message'][:200]}")
    return ids


# ------------------------------------------------------------------ alerting

def suppressed(ctx: runner.Context, f: Findings, code: str, now: datetime) -> bool:
    last = parse_ts(settings.get(ctx.conn, f"watchdog.alert.{code}"))
    if code in f.daily:
        return bool(last and local_now(ctx.cfg, last).date() == local_now(ctx.cfg, now).date())
    return bool(last and now - last < SUPPRESS)


def send_alerts(ctx: runner.Context, f: Findings, now: datetime) -> int:
    fresh = [(c, m) for c, m in f.alerts if not suppressed(ctx, f, c, now)]
    if not fresh:
        return 0
    fresh.sort(key=lambda cm: cm[0] not in f.loud)       # the loud ones lead the subject
    body_lines = "".join(f"<li>{html.escape(m)}</li>" for _, m in fresh)
    plain = "\n".join(f"* {m}" for _, m in fresh)
    loud = any(c in f.loud for c, _ in fresh)
    subject = f"[{ctx.cfg.brand_name}] {len(fresh)} alert{'s' if len(fresh) != 1 else ''}: {fresh[0][1][:70]}"
    res = mail.send(subject, f"<h2>{html.escape(ctx.cfg.brand_name)} watchdog</h2><ul>{body_lines}</ul>"
                    f"<p style='color:#666'>Dashboard: {html.escape(dashboard_url(ctx.cfg))}/</p>",
                    to=ctx.cfg.alert_email, plain=plain, dry_run=ctx.dry_run)
    notify.push(f"{ctx.cfg.brand_name}: {fresh[0][1][:60]}" if loud else f"{ctx.cfg.brand_name}: {len(fresh)} alert(s)",
                plain[:500], dry_run=ctx.dry_run, priority="urgent" if loud else "high", click=dashboard_url(ctx.cfg))
    for code, _ in fresh:
        settings.set(ctx.conn, f"watchdog.alert.{code}", now.isoformat())
    ctx.log.warning("alerts %s: %s", "written to outbox-dry" if res.dry_run else ("sent" if res.sent else f"FAILED {res.error}"), plain)
    return len(fresh)


# ------------------------------------------------------------------ digest

def digest_data(ctx: runner.Context, now: datetime) -> dict:
    since = (now - timedelta(hours=24)).isoformat()
    conn = ctx.conn
    published = [dict(r) for r in db.rows(conn, "SELECT service, sent_at, caption FROM post_history WHERE sent_at >= ? ORDER BY sent_at DESC", (since,))]
    waiting = [dict(r) for r in db.rows(conn, "SELECT id, kind, created_at FROM content_queue WHERE status='draft' ORDER BY created_at")]
    approved = db.one(conn, "SELECT COUNT(*) n FROM content_queue WHERE status='approved'")["n"]
    scheduled = db.one(conn, "SELECT COUNT(*) n FROM content_queue WHERE status='scheduled'")["n"]
    would = db.one(conn, "SELECT COUNT(*) n FROM content_queue WHERE status='would_publish' AND updated_at >= ?", (since,))["n"]
    failed = [dict(r) for r in db.rows(conn, "SELECT id, last_error FROM content_queue WHERE status='failed' AND updated_at >= ?", (since,))]
    errors = [dict(r) for r in db.rows(conn, "SELECT agent, kind, message, ts FROM errors WHERE ts >= ? ORDER BY id DESC LIMIT 30", (since,))]
    agents = []
    for name, meta in AGENTS.items():
        last = db.one(conn, "SELECT started_at, ok, summary FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT 1", (name,))
        agents.append({"name": name, "schedule": meta["schedule"], "built": is_built(name),
                       "dry_run": settings.dry_run(conn, name) if name in settings.AGENTS_WITH_DRY_RUN else None,
                       "last": dict(last) if last else None})
    channels = [dict(r) for r in db.rows(conn, "SELECT service, display_name, connected, last_checked_at FROM channels ORDER BY service")]
    return {"published": published, "waiting": waiting, "approved": approved, "scheduled": scheduled, "would_publish": would,
            "failed": failed, "errors": errors, "agents": agents, "channels": channels,
            "drive": (settings.get(conn, DRIVE_STATE_KEY) or "unknown"),
            "ai_mtd": spend.month_to_date(conn), "ai_cap": ctx.cfg.ai_monthly_cap_usd, "buffer": budget.snapshot(conn)}


def digest_html(ctx: runner.Context, d: dict, notes: list[str], now: datetime) -> tuple[str, str]:
    """Plain, short sentences. No dashes anywhere in our own words."""
    e = html.escape
    local = local_now(ctx.cfg, now)

    def sect(title, inner):
        return f"<h3 style='margin:18px 0 6px'>{e(title)}</h3>{inner}"

    def ul(items):
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>" if items else "<p style='color:#666'>None.</p>"

    parts = [f"<h2>{e(ctx.cfg.brand_name)} daily digest, {e(local.strftime('%A %b %d, %Y'))}</h2>"]
    parts.append(sect(f"Posted in the last day ({len(d['published'])})",
                      ul([f"<b>{e(p['service'])}</b>: {e((p['caption'] or '')[:90])}" for p in d["published"]])))
    if d["would_publish"]:
        parts.append(f"<p>The publisher is in dry run. {d['would_publish']} post(s) would have gone out.</p>")
    parts.append(sect(f"Waiting for your Approve ({len(d['waiting'])})",
                      ul([f"Post {w['id']} ({e(w['kind'])}), drafted {e((w['created_at'] or '')[:10])}." for w in d["waiting"]])))
    parts.append(f"<p>Approved and not yet sent: {d['approved']}. Waiting in Buffer: {d['scheduled']}.</p>")
    parts.append(sect(f"Broke ({len(d['failed']) + len(d['errors'])})",
                      ul([f"Post {x['id']}: {e(x['last_error'] or 'no reason recorded')}" for x in d["failed"]] +
                         [f"{e(x['agent'])}, {e(x['kind'])}: {e(x['message'][:120])}" for x in d["errors"]])))
    drive = {"ok": "Google Drive is signed in.", "expired": "Google Drive sign-in has EXPIRED. Sign in again on the Drive page.",
             "missing": "Google Drive is not signed in yet."}.get(d["drive"], "Google Drive sign-in has not been checked yet.")
    parts.append(sect("Drive", f"<p>{e(drive)}</p>"))
    parts.append(sect("Spend", f"<p>AI spend is ${d['ai_mtd']:.2f} of the ${d['ai_cap']:.2f} cap this month.<br>Buffer requests used: " +
                      ", ".join(f"{b['window']} {b['used']} of {b['limit']}" for b in d["buffer"]) + ".</p>"))
    parts.append(sect("Channels", ul([f"<b>{e(c['service'])}</b>, {e(c['display_name'] or '')}: "
                                      f"{'connected.' if c['connected'] else '<span style=color:#c62828>DISCONNECTED.</span>'}"
                                      for c in d["channels"]])))
    rows = "".join(f"<tr><td>{e(a['name'])}</td><td>{'' if a['dry_run'] is None else ('dry run' if a['dry_run'] else '<b style=color:#c62828>LIVE</b>')}</td>"
                   f"<td>{e(a['last']['started_at'][:16].replace('T', ' ')) if a['last'] else ('not built' if not a['built'] else 'never')}</td>"
                   f"<td>{'' if not a['last'] else ('ok' if a['last']['ok'] == 1 else 'failed')}</td></tr>" for a in d["agents"])
    parts.append(sect("Agents", f"<table cellpadding=4><tr><th align=left>agent</th><th align=left>mode</th>"
                                f"<th align=left>last run (UTC)</th><th></th></tr>{rows}</table>"))
    if notes:
        parts.append(sect("Notes", ul([e(n) for n in notes])))
    parts.append(f"<p style='color:#666'>Dashboard: {e(dashboard_url(ctx.cfg))}/</p>")
    plain = (f"{ctx.cfg.brand_name} digest for {local.date()}. Posted {len(d['published'])}. Waiting {len(d['waiting'])}. "
             f"Failed {len(d['failed'])}. Errors {len(d['errors'])}. AI ${d['ai_mtd']:.2f} of ${d['ai_cap']:.2f}. {drive}")
    return "".join(parts), plain


def digest_due(ctx: runner.Context, now: datetime, force: bool = False) -> bool:
    if force:
        return True
    local = local_now(ctx.cfg, now)
    if local.hour != ctx.cfg.digest_hour:
        return False
    return settings.get(ctx.conn, "watchdog.digest_sent_on") != local.date().isoformat()


def send_digest(ctx: runner.Context, notes: list[str], now: datetime) -> bool:
    d = digest_data(ctx, now)
    body, plain = digest_html(ctx, d, notes, now)
    local = local_now(ctx.cfg, now)
    res = mail.send(f"[{ctx.cfg.brand_name}] Daily digest {local.strftime('%a %b %d')}: {len(d['published'])} posted, "
                    f"{len(d['waiting'])} waiting, {len(d['failed']) + len(d['errors'])} broke", body, to=ctx.cfg.alert_email,
                    plain=plain, dry_run=ctx.dry_run)
    settings.set(ctx.conn, "watchdog.digest_sent_on", local.date().isoformat())
    ctx.log.info("digest %s", "written to outbox-dry" if res.dry_run else ("sent" if res.sent else f"FAILED {res.error}"))
    return res.sent or res.dry_run


# ------------------------------------------------------------------ entry

def run(ctx: runner.Context, *, now: Optional[datetime] = None, client: Optional[BufferClient] = None,
        probe=None, force_digest: Optional[bool] = None) -> str:
    now = now or now_utc()
    if force_digest is None:
        force_digest = "--digest" in sys.argv
    f = Findings()
    client = client if client is not None else BufferClient.from_config(ctx.conn, ctx.agent)
    check_drive(ctx, f)
    check_channels(ctx, f, client)
    check_posts(ctx, f, now)
    check_budgets(ctx, f, now)
    check_agents(ctx, f, now)
    check_dashboard(ctx, f, probe)
    check_disk_and_backups(ctx, f, now)
    if client is not None:
        from ..buffer import metrics
        local_today = local_now(ctx.cfg, now).date()
        if metrics.due(ctx.conn, local_today):
            try:
                m = metrics.pull(ctx, client, today=local_today)
                f.note(f"Post numbers refreshed from Buffer: {m['posts']} posts on {m['channels']} channel(s), {m['ours']} of them ours.")
            except Exception as e:  # noqa: BLE001
                f.note(f"The post numbers refresh failed: {e}")
    error_ids = collect_new_errors(ctx, f)
    sent = send_alerts(ctx, f, now)
    if error_ids:
        ctx.conn.execute(f"UPDATE errors SET notified_at=? WHERE id IN ({','.join('?' * len(error_ids))})", (db.utcnow(), *error_ids))
    settings.set(ctx.conn, "watchdog.notes", json.dumps(f.notes[:20]))      # the chief's brief reads these
    digest = False
    # the Chief of staff's morning brief replaces this digest once that agent exists
    if digest_due(ctx, now, force_digest) and (force_digest or not is_built("chief")):
        digest = send_digest(ctx, f.notes, now)
    return f"alerts: {len(f.alerts)} found, {sent} sent; notes: {len(f.notes)}; digest: {'sent' if digest else 'not due'}"


if __name__ == "__main__":
    runner.main_for("watchdog", run)
