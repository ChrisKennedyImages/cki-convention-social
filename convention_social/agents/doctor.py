"""The doctor: fixes the suite's known failures by itself, minutes after they happen, checks each fix, says it.

Chris, 2026-10-15: "a doctor agent too to auto fix anything that fails realtime". Every five minutes it reads
the signals the watchdog reads (agents/watchdog.py: the Drive sign-in, failed posts, each agent's last run
against its schedule, the dashboard on localhost, disk free, backup age) and the errors table. For each
known failure, one remedy:

  an agent whose run failed or is overdue   run again (runner.start_agent: its own lock, its own dry-run switch)
  the backup overdue, or its file stale     the backup now; the nightly sweep runs inside it
  disk under the watchdog's threshold       the sweep (storage.sweep, inside the data root), under the backup's lock
  the dashboard not answering               its process stopped, only the one updater.dashboard_pids proves is this
                                            suite's dashboard; launchd's KeepAlive on its own label starts it again
  a post failed for a passing reason        back to approved (his Approve stands), so the publisher sends it at its
  (a Buffer timeout, a 5xx, a rate limit)   next slot; never a post that reached Buffer on any network
  a reel that failed to render              remade on its draft (content.redraw); never without a track
  the Drive sign-in expired                 code cannot sign in: a ping with the link to sign in

The content agent is not run again here: the watchdog's draft window does that (2026-10-13).

After each remedy it reads the same signal again and records fixed or not fixed (doctor_remedies). Never a
loop: at most TRIES_A_DAY tries per problem per day, BACKOFF apart. A remedy that did not work is said to
Chris once, with what it tried, when the day's tries are used; one that cannot run at all is said once, then.

An exception in our own code (an errors row with a traceback) has no remedy. It becomes one GitHub issue per
distinct error (agent, kind and the traceback's frames make the signature) in ChrisKennedyImages/cki-convention-social,
with the traceback, the agent, the time and the last log lines, every secret taken out, and a ping with the
link. A repeat is counted on the same issue; one that comes back after the issue was closed gets a new one.
The token is GITHUB_TOKEN on the Keys page (fine-grained, Issues only); without it, a ping instead.

It never edits code, never runs a command on the Mini's checkout, never stops a process that is not this
suite's dashboard, and deletes nothing itself. Dry run (the default): it says what it would do, at the cadence
it would do it, and does nothing. Chris switches it live on the Agents page. The digest and the morning brief
carry a line per remedy (digest_lines).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sqlite3
import time as clock
import traceback
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from ..core import config, db, notify, runner, secrets, settings
from . import updater, watchdog

AGENT = "doctor"
ISSUE_REPO = "ChrisKennedyImages/cki-convention-social"
GITHUB_API = "https://api.github.com"

TRIES_A_DAY = 3
BACKOFF = (timedelta(0), timedelta(minutes=30), timedelta(hours=2))     # before the 1st, 2nd and 3rd try of a day
LIMITS = {"drive": 1}                                                   # the sign-in link: once a day
VERIFY_BY = {"agent": timedelta(minutes=75), "backup": timedelta(minutes=30), "post": timedelta(minutes=40),
             "drive": timedelta(hours=12)}                              # how long a remedy's result may take to show
QUIET_FIX = ("drive", "reel")        # their fix is said in their own words (his sign-in; the reel's own ping)
CONFIRM_WAIT = 15                    # seconds: a second look before restarting (the updater restarts it after an update)
RESTART_WAIT, POLL, STOP_WAIT = 60, 5, 10
STARTS_A_RUN = 2                     # agents started per pass: after a reboot or a long sleep every agent looks overdue at
                                     # once, and the Mini's memory is shared by three suites; the rest wait five minutes
RERUN = tuple(n for n in watchdog.MAX_GAP if n not in ("content", "backup", AGENT))
PASSING = re.compile(r"HTTP 5\d\d|HTTP 429|rate limit|timed out|timeout|Connection ?(Error|aborted|reset|refused)|"
                     r"Max retries exceeded|RemoteDisconnected|Temporary failure in name resolution|"
                     r"nodename nor servname|Name or service not known|ProtocolError|ChunkedEncodingError", re.I)

SEEN_KEY = "doctor.errors_seen"      # the newest errors.id already read for issues
FIRST_LOOK = timedelta(hours=24)     # the very first run reads this far back
ISSUE_WINDOW = timedelta(days=3)     # an error older than this is not filed
ISSUES_A_DAY = 10
LOG_LINES = 40
FRAME = re.compile(r'File "([^"]+)", line \d+, in (\S+)')


# ------------------------------------------------------------------ what it may touch

def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def restart_dashboard(*, find: Optional[Callable[[], list]] = None, kill: Callable = os.kill, alive: Callable[[int], bool] = _alive,
                      sleep: Callable[[float], None] = clock.sleep) -> tuple[bool, str]:
    """Stop this suite's dashboard so launchd's KeepAlive on its own label starts it again. Only a pid that
    updater.dashboard_pids proves is ours (the pid it wrote, running our dashboard command from this checkout)
    is ever signalled: TERM, and KILL for the same pid when it will not stop. (stopped, what happened)."""
    pids = list((find or updater.dashboard_pids)())
    if not pids:
        return False, "No dashboard process of this suite is running, and launchd has not started it again by itself."
    try:
        for pid in pids:
            kill(pid, signal.SIGTERM)
        for _ in range(STOP_WAIT):
            if not any(alive(pid) for pid in pids):
                break
            sleep(1)
        else:
            for pid in pids:
                if alive(pid):
                    kill(pid, signal.SIGKILL)
    except OSError as e:
        return False, f"The dashboard could not be stopped ({type(e).__name__}: {e})."
    return True, f"stopped the dashboard (pid {', '.join(str(p) for p in pids)}); launchd's KeepAlive starts it again"


def _github(method: str, url: str, headers: dict, body: Optional[dict]) -> tuple[int, dict]:
    import requests
    r = requests.request(method, url, headers=headers, json=body, timeout=20)
    try:
        data = r.json()
    except ValueError:
        data = {}
    return r.status_code, data if isinstance(data, dict) else {}


def _sweep(conn: sqlite3.Connection) -> dict:
    from .. import storage
    return storage.sweep(conn)


def _redraw(conn, row, meta: dict, *, agent: str = AGENT):
    from . import content
    return content.redraw(conn, row, meta, agent=agent)


def _track(conn):
    from .. import music
    return music.current(conn)


@dataclass
class Hands:
    """Everything the doctor does to the world, in one place (the tests hand it fakes)."""
    start: Callable[[str], None] = runner.start_agent
    probe: Optional[Callable[[str], int]] = None          # None: the watchdog's own look at localhost
    restart: Callable[[], tuple[bool, str]] = restart_dashboard
    push: Callable[..., bool] = notify.push
    github: Callable[[str, str, dict, Optional[dict]], tuple[int, dict]] = _github
    sleep: Callable[[float], None] = clock.sleep
    sweep: Callable[[sqlite3.Connection], dict] = _sweep
    redraw: Callable = _redraw
    track: Callable = _track


@dataclass
class Problem:
    key: str        # agent:<name> | backup | disk | dashboard | post:<id> | reel:<id> | drive | issue:<signature>
    kind: str
    found: str      # the signal, in words
    target: str = ""


# ------------------------------------------------------------------ small helpers

def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def zone() -> ZoneInfo:
    return ZoneInfo(config.get_config().timezone)


def hhmm(value) -> str:
    dt = watchdog.parse_ts(value) if isinstance(value, str) else value
    return dt.astimezone(zone()).strftime("%H:%M") if dt else "?"


def day_start(now: datetime) -> datetime:
    local = now.astimezone(zone())
    return datetime.combine(local.date(), time(0, 0), tzinfo=local.tzinfo).astimezone(timezone.utc)


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def doing(p: Problem) -> str:
    return {"agent": f"run {p.target} again",
            "backup": "run the backup now (the nightly sweep runs inside it)",
            "disk": "run the sweep",
            "dashboard": "restart the dashboard",
            "post": f"send post {p.target} back to the publisher for its next slot",
            "reel": f"remake the reel on post {p.target}",
            "drive": "ping you the link to sign in to Drive",
            "issue": "open a GitHub issue"}[p.kind]


def did(p: Problem) -> str:
    return {"agent": f"ran {p.target} again",
            "backup": "ran the backup at once (the nightly sweep runs inside it)",
            "disk": "ran the sweep",
            "dashboard": "restarted the dashboard",
            "post": f"sent post {p.target} back to the publisher for its next slot",
            "reel": f"remade the reel on post {p.target}",
            "drive": "pinged you the link to sign in to Drive",
            "issue": "opened a GitHub issue"}[p.kind]


def problem_of(rem) -> Problem:
    kind, _, target = rem["problem"].partition(":")
    return Problem(rem["problem"], kind, rem["found"], target or ("backup" if kind == "backup" else ""))


def crash(ctx: runner.Context, e: Exception) -> None:
    """An exception inside a remedy is an exception in our code: recorded with its traceback, so it is filed."""
    runner.record_error(ctx.conn, AGENT, type(e).__name__, str(e), traceback.format_exc())


# ------------------------------------------------------------------ the signals

def codes(ctx: runner.Context, now: datetime) -> dict[str, str]:
    """The watchdog's own checks, read only: {code: message}. Not the channels (that asks Buffer), not the draft
    window (that starts the content agent), not the heartbeat (that posts to the site)."""
    f = watchdog.Findings()
    watchdog.check_drive(ctx, f)
    watchdog.check_posts(ctx, f, now)
    watchdog.check_agents(ctx, f, now)
    watchdog.check_disk_and_backups(ctx, f, now)
    return dict(f.alerts)


def dashboard_down(ctx: runner.Context, probe) -> Optional[str]:
    f = watchdog.Findings()
    watchdog.check_dashboard(ctx, f, probe)
    return dict(f.alerts).get("dashboard_down")


def last_run(conn, name: str):
    return db.one(conn, "SELECT * FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT 1", (name,))


def last_failed(conn, name: str) -> bool:
    last = last_run(conn, name)
    return bool(last and last["ok"] == 0)


def post_row(conn, qid):
    return db.one(conn, "SELECT * FROM content_queue WHERE id=?", (int(qid),))


def passing(why: Optional[str]) -> bool:
    return bool(why) and bool(PASSING.search(why))


def never_left(conn, row) -> bool:
    """Nothing of this post ever reached Buffer: sending it again cannot post twice. Unreadable ids fail closed."""
    try:
        ids = json.loads(row["buffer_post_ids"] or "{}")
    except (TypeError, ValueError):
        return False
    if ids:
        return False
    return db.one(conn, "SELECT 1 FROM post_history WHERE queue_id=?", (row["id"],)) is None


def reel_drafts(conn, now: datetime):
    today = now.astimezone(zone()).date()
    for r in db.rows(conn, "SELECT * FROM content_queue WHERE status='draft' AND kind='photo' ORDER BY id"):
        try:
            meta = json.loads(r["rule_report"] or "{}")
            day = date.fromisoformat((meta or {}).get("for_day") or "")
        except (TypeError, ValueError, AttributeError):
            continue
        if isinstance(meta, dict) and meta.get("reel_failed") and meta.get("design_wanted") == "reel" and day >= today:
            yield r, meta


def find(ctx: runner.Context, now: datetime, h: Hands) -> list[Problem]:
    seen = codes(ctx, now)
    out: dict[str, Problem] = {}

    def add(p: Problem) -> None:
        out.setdefault(p.key, p)

    if "drive_expired" in seen:
        add(Problem("drive", "drive", "The Google Drive sign-in has expired."))
    for code, message in seen.items():
        head, _, name = code.partition(":")
        if head in ("agent_missed", "agent_stuck"):
            if name == "backup":
                add(Problem("backup", "backup", message, "backup"))
            elif name in RERUN:
                add(Problem(f"agent:{name}", "agent", message, name))
        elif head == "post_failed":
            row = post_row(ctx.conn, name)
            if row and row["status"] == "failed" and passing(row["last_error"]) and never_left(ctx.conn, row):
                why = re.sub(r":\s*\{\}\s*$", "", row["last_error"].strip())[:160]
                add(Problem(f"post:{name}", "post", f"Post {name} did not go out because of a passing fault at Buffer or on "
                                                    f"the network ({why}).", name))
    if "backup_stale" in seen:
        add(Problem("backup", "backup", seen["backup_stale"], "backup"))
    if "disk_low" in seen:
        add(Problem("disk", "disk", seen["disk_low"]))
    for name in RERUN + ("backup",):
        last = last_run(ctx.conn, name)
        if last and last["ok"] == 0:
            key, kind = ("backup", "backup") if name == "backup" else (f"agent:{name}", "agent")
            add(Problem(key, kind, f"{name}'s last run failed: {(last['summary'] or 'see the errors list')[:160]}.", name))
    down = dashboard_down(ctx, h.probe)
    if down:
        add(Problem("dashboard", "dashboard", down))
    for row, meta in reel_drafts(ctx.conn, now):
        add(Problem(f"reel:{row['id']}", "reel", f"The reel on post {row['id']} was not made ({str(meta['reel_failed'])[:120]}); "
                                                 "the draft is a carousel for now.", str(row["id"])))
    return list(out.values())


def still(ctx: runner.Context, p: Problem, now: datetime) -> bool:
    """The same signal, read again."""
    c = codes(ctx, now)
    if p.kind == "agent":
        return f"agent_missed:{p.target}" in c or f"agent_stuck:{p.target}" in c or last_failed(ctx.conn, p.target)
    if p.kind == "backup":
        return ("backup_stale" in c or "agent_missed:backup" in c or "agent_stuck:backup" in c
                or last_failed(ctx.conn, "backup"))
    if p.kind == "disk":
        return "disk_low" in c
    if p.kind == "drive":
        return "drive_expired" in c
    return False


# ------------------------------------------------------------------ the record, the backoff, the saying

def record(conn, p: Problem, remedy: str, now: datetime, outcome: str, *, dry: bool, detail: Optional[str] = None) -> int:
    return db.insert(conn, "doctor_remedies", problem=p.key, found=p.found[:500], remedy=remedy[:300], started_at=iso(now),
                     dry_run=1 if dry else 0, outcome=outcome, detail=(detail or "")[:1000] or None,
                     checked_at=None if outcome == "pending" else iso(now))


def tries_today(conn, key: str, now: datetime) -> list:
    return db.rows(conn, "SELECT * FROM doctor_remedies WHERE problem=? AND started_at >= ? ORDER BY id", (key, iso(day_start(now))))


def may_try(ctx: runner.Context, p: Problem, now: datetime) -> bool:
    """Never a loop: nothing while a remedy is still being checked, at most the kind's tries a day, BACKOFF apart."""
    conn = ctx.conn
    if db.one(conn, "SELECT 1 FROM doctor_remedies WHERE problem=? AND outcome='pending'", (p.key,)):
        return False
    n = len(tries_today(conn, p.key, now))
    if n >= LIMITS.get(p.kind, TRIES_A_DAY):
        return False
    last = db.one(conn, "SELECT started_at FROM doctor_remedies WHERE problem=? ORDER BY id DESC LIMIT 1", (p.key,))
    when = watchdog.parse_ts(last["started_at"]) if last else None
    return not (when and now - when < BACKOFF[min(n, len(BACKOFF) - 1)])


def said_today(conn, key: str, now: datetime) -> bool:
    return bool(db.one(conn, "SELECT 1 FROM doctor_remedies WHERE problem=? AND said_at >= ?", (key, iso(day_start(now)))))


def say(ctx: runner.Context, p: Problem, rid: int, message: str, now: datetime, h: Hands, *, click: Optional[str] = None) -> None:
    """Once per problem per day: on the Agents page, and on the phone. When the ping went, the watchdog does not
    say it again; when it did not, the watchdog's mail does."""
    if said_today(ctx.conn, p.key, now):
        return
    eid = runner.record_error(ctx.conn, AGENT, "not_fixed", message)
    pushed = h.push(f"{ctx.cfg.brand_name}: the doctor could not fix this", message, dry_run=ctx.dry_run, priority="high",
                    click=click or notify.link("/agents"), conn=ctx.conn, agent=AGENT)
    ctx.conn.execute("UPDATE doctor_remedies SET said_at=? WHERE id=?", (iso(now), rid))
    if pushed:
        ctx.conn.execute("UPDATE errors SET notified_at=? WHERE id=?", (iso(now), eid))


def after(ctx: runner.Context, rid: int, p: Problem, outcome: str, detail: str, now: datetime, h: Hands) -> str:
    rem = db.one(ctx.conn, "SELECT * FROM doctor_remedies WHERE id=?", (rid,))
    if outcome == "fixed" and p.kind not in QUIET_FIX:
        h.push(f"{ctx.cfg.brand_name}: the doctor fixed it", f"{cap(p.found)} The doctor {rem['remedy']}. {cap(detail)}", dry_run=ctx.dry_run,
               priority="low", click=notify.link("/agents"), conn=ctx.conn, agent=AGENT)
    elif outcome == "not_fixed" and p.kind != "drive":
        tries = tries_today(ctx.conn, p.key, now)
        if len(tries) >= LIMITS.get(p.kind, TRIES_A_DAY):
            times = ", ".join(hhmm(t["started_at"]) for t in tries)
            say(ctx, p, rid, f"{cap(p.found)} The doctor tried to {doing(p)} {len(tries)} time{'s' if len(tries) != 1 else ''} "
                             f"today ({times}); it did not work. {cap(detail)} It tries again tomorrow; the Agents page has "
                             "the details.", now, h)
    elif outcome == "cannot" and p.kind != "issue":
        say(ctx, p, rid, f"{cap(p.found)} The doctor cannot fix this by itself. {cap(detail)}", now, h)
    word = {"fixed": "fixed", "not_fixed": "not fixed", "cannot": "cannot", "left": "left to you"}.get(outcome, outcome)
    return f"{rem['remedy']}: {word}"


def finish(ctx: runner.Context, p: Problem, remedy: str, outcome: str, detail: str, now: datetime, h: Hands) -> str:
    """A remedy whose result is known at once."""
    return after(ctx, record(ctx.conn, p, remedy, now, outcome, dry=False, detail=detail), p, outcome, detail, now, h)


def settle(ctx: runner.Context, rem, outcome: str, detail: str, now: datetime, h: Hands) -> str:
    ctx.conn.execute("UPDATE doctor_remedies SET outcome=?, detail=?, checked_at=? WHERE id=?",
                     (outcome, detail[:1000], iso(now), rem["id"]))
    return after(ctx, rem["id"], problem_of(rem), outcome, detail, now, h)


# ------------------------------------------------------------------ checking a remedy that takes time

def judge(ctx: runner.Context, p: Problem, rem, now: datetime) -> Optional[tuple[str, str]]:
    """(outcome, detail) once the remedy has had its chance; None while it is still under way."""
    conn = ctx.conn
    if p.kind in ("agent", "backup"):
        run = db.one(conn, "SELECT * FROM agent_runs WHERE agent=? AND started_at >= ? AND finished_at IS NOT NULL "
                           "ORDER BY id DESC LIMIT 1", (p.target, rem["started_at"]))
        if run is None:
            return None
        if run["ok"] == 0:
            return "not_fixed", f"It ran at {hhmm(run['started_at'])} and failed: {(run['summary'] or '')[:200]}"
        if still(ctx, p, now):
            return "not_fixed", f"It ran at {hhmm(run['started_at'])}, and the signal is still there."
        return "fixed", (f"{cap(p.target)} ran at {hhmm(run['started_at'])} and finished well"
                         + ("; a fresh backup is there." if p.kind == "backup" else "."))
    if p.kind == "post":
        row = post_row(conn, p.target)
        status = row["status"] if row else "gone"
        if status in ("scheduled", "published", "would_publish"):
            return "fixed", f"The publisher has it now ({status})."
        if status == "failed":
            return "not_fixed", f"It failed again: {(row['last_error'] or '')[:200]}"
        if status == "approved":
            return None
        return "left", f"It is {status} now."
    if p.kind == "drive":
        return None if still(ctx, p, now) else ("fixed", "You signed in again.")
    return None


def timed_out(p: Problem) -> tuple[str, str]:
    minutes = int(VERIFY_BY.get(p.kind, timedelta(hours=1)).total_seconds() // 60)
    if p.kind in ("agent", "backup"):
        return "not_fixed", (f"{cap(p.target)} did not start within {minutes} minutes: an earlier run may still be going, or "
                             f"it could not start (logs/{p.target}.manual.log).")
    if p.kind == "post":
        return "not_fixed", f"The publisher did not pick it up within {minutes} minutes."
    return "not_fixed", "Still signed out."


def verify_pending(ctx: runner.Context, now: datetime, h: Hands) -> list[str]:
    lines = []
    for rem in db.rows(ctx.conn, "SELECT * FROM doctor_remedies WHERE outcome='pending' ORDER BY id"):
        p = problem_of(rem)
        verdict = judge(ctx, p, rem, now)
        if verdict is None:
            started = watchdog.parse_ts(rem["started_at"])
            if started and now - started < VERIFY_BY.get(p.kind, timedelta(hours=1)):
                continue
            verdict = timed_out(p)
        lines.append(settle(ctx, rem, verdict[0], verdict[1], now, h))
    return lines


# ------------------------------------------------------------------ the remedies

def treat(ctx: runner.Context, p: Problem, now: datetime, h: Hands) -> Optional[str]:
    if p.kind == "dashboard":
        h.sleep(CONFIRM_WAIT)                          # the updater restarts it after an update; that takes seconds
        if dashboard_down(ctx, h.probe) is None:
            return None
    if ctx.dry_run:
        record(ctx.conn, p, f"would {doing(p)}", now, "would", dry=True)
        return f"would {doing(p)} ({p.found[:90]})"
    return {"agent": treat_agent, "backup": treat_agent, "disk": treat_disk, "dashboard": treat_dashboard,
            "post": treat_post, "reel": treat_reel, "drive": treat_drive}[p.kind](ctx, p, now, h)


def treat_agent(ctx: runner.Context, p: Problem, now: datetime, h: Hands) -> str:
    try:
        h.start(p.target)
    except Exception as e:  # noqa: BLE001  it could not even be started: said, and the traceback filed
        crash(ctx, e)
        return finish(ctx, p, f"could not {doing(p)}", "cannot", f"It could not be started ({type(e).__name__}: {e}).", now, h)
    record(ctx.conn, p, did(p), now, "pending", dry=False)
    return f"{did(p)}; checking"


def treat_disk(ctx: runner.Context, p: Problem, now: datetime, h: Hands) -> Optional[str]:
    lock = runner.Lock("backup")
    if not lock.acquire():
        return None                                    # the backup is running, and its sweep with it
    try:
        result = h.sweep(ctx.conn)
    except Exception as e:  # noqa: BLE001
        crash(ctx, e)
        return finish(ctx, p, did(p), "not_fixed", f"The sweep raised {type(e).__name__}: {e}", now, h)
    finally:
        lock.release()
    freed = sum((result.get("freed_mb") or {}).values())
    low = codes(ctx, now).get("disk_low")
    if low:
        return finish(ctx, p, did(p), "not_fixed", f"The sweep freed {freed:.0f} MB, and the disk is still low. What fills it "
                                                   "now is not this suite's to delete.", now, h)
    return finish(ctx, p, did(p), "fixed", f"The sweep freed {freed:.0f} MB; the disk has room again.", now, h)


def treat_dashboard(ctx: runner.Context, p: Problem, now: datetime, h: Hands) -> str:
    stopped, how = h.restart()
    if not stopped:
        return finish(ctx, p, f"could not {doing(p)}", "cannot", f"{how} On the Mini, run: {updater.KICKSTART}", now, h)
    for _ in range(RESTART_WAIT // POLL):
        h.sleep(POLL)
        if dashboard_down(ctx, h.probe) is None:
            return finish(ctx, p, did(p), "fixed", "It answers again.", now, h)
    return finish(ctx, p, did(p), "not_fixed", f"{cap(how)}, and it still does not answer after {RESTART_WAIT} seconds. "
                                               f"On the Mini, run: {updater.KICKSTART}", now, h)


def gone(when: str, now: datetime) -> bool:
    try:
        return datetime.fromisoformat(when).replace(tzinfo=zone()) <= now
    except (TypeError, ValueError):
        return True


def treat_post(ctx: runner.Context, p: Problem, now: datetime, h: Hands) -> Optional[str]:
    row = post_row(ctx.conn, p.target)
    if row is None or row["status"] != "failed" or not never_left(ctx.conn, row):
        return None
    keep = row["scheduled_for"] if row["scheduled_for"] and not gone(row["scheduled_for"], now) else None
    note = (f"The doctor sent this back to the publisher after a passing failure ({(row['last_error'] or '')[:200]}); "
            "it goes at its next slot.")
    moved = ctx.conn.execute("UPDATE content_queue SET status='approved', scheduled_for=?, last_error=?, updated_at=? "
                             "WHERE id=? AND status='failed'", (keep, note, iso(now), row["id"])).rowcount
    if not moved:
        return None
    record(ctx.conn, p, did(p), now, "pending", dry=False)
    return f"{did(p)}; checking"


def treat_reel(ctx: runner.Context, p: Problem, now: datetime, h: Hands) -> Optional[str]:
    row = post_row(ctx.conn, p.target)
    try:
        meta = json.loads(row["rule_report"] or "{}") if row else {}
    except ValueError:
        meta = {}
    if row is None or row["status"] != "draft" or not meta.get("reel_failed"):
        return None
    if h.track(ctx.conn) is None:
        return finish(ctx, p, f"could not {doing(p)}", "cannot", "No music track is on (the Music page): a reel never goes "
                                                                 "out silent, so the carousel stands.", now, h)
    remade = dict(meta)
    remade["design"] = "reel"
    was = remade.pop("reel_failed")
    try:
        paths, note = h.redraw(ctx.conn, row, remade, agent=AGENT)
    except Exception as e:  # noqa: BLE001
        crash(ctx, e)
        return finish(ctx, p, did(p), "not_fixed", f"The remake raised {type(e).__name__}: {e}. The carousel stands.", now, h)
    if paths is None:
        return finish(ctx, p, f"could not {doing(p)}", "cannot", f"{note}. The carousel stands.", now, h)
    video = [Path(v) for v in (paths.get("9:16") or [])]
    if remade.get("reel_failed") or not video or not video[0].is_file() or video[0].stat().st_size == 0:
        why = remade.get("reel_failed") or "no video file came out"
        return finish(ctx, p, did(p), "not_fixed", f"The reel failed again ({why}). The carousel stands.", now, h)
    from . import content
    day = date.fromisoformat(meta["for_day"])
    remade.update(reel=content.reel_kind(day), reel_remade={"by": AGENT, "at": iso(now), "was": was})
    ctx.conn.execute("UPDATE content_queue SET render_paths=?, rule_report=?, updated_at=? WHERE id=? AND status='draft'",
                     (json.dumps(paths), json.dumps(remade), iso(now), row["id"]))
    h.push(f"{ctx.cfg.brand_name}: the reel is made", f"The reel for {day:%A} (post {row['id']}) did not render the first time; "
           "it is made now. Tap to see it before you approve.", dry_run=ctx.dry_run, priority="default",
           click=notify.link(f"/queue/{row['id']}"), actions=notify.open_action(row["id"]), conn=ctx.conn, agent=AGENT)
    return finish(ctx, p, did(p), "fixed", "The reel is on the draft now, with its cover. The art director saw the carousel, "
                                           "not the reel: look at it before you approve.", now, h)


def treat_drive(ctx: runner.Context, p: Problem, now: datetime, h: Hands) -> str:
    h.push(f"{ctx.cfg.brand_name}: sign in to Google Drive again",
           "The Drive sign-in expired, so no photo can be read and no post drafted. Tap to sign in again; it takes a minute.",
           dry_run=ctx.dry_run, priority="high", click=notify.link("/drive"), conn=ctx.conn, agent=AGENT)
    rid = record(ctx.conn, p, did(p), now, "pending", dry=False)
    ctx.conn.execute("UPDATE doctor_remedies SET said_at=? WHERE id=?", (iso(now), rid))
    return f"{did(p)}; waiting for the sign-in"


# ------------------------------------------------------------------ an exception in our code: a GitHub issue

def signature(agent: str, kind: str, tb: str) -> str:
    """The same error however its line numbers move or its message varies: the agent, the kind and the frames."""
    frames = []
    for path, fn in FRAME.findall(tb or ""):
        path = path.replace("\\", "/")
        path = path[path.index("convention_social/"):] if "convention_social/" in path else path.rsplit("/", 1)[-1]
        frames.append(f"{path}:{fn}")
    return hashlib.sha256(f"{agent}|{kind}|{'>'.join(frames)}".encode()).hexdigest()[:16]


def scrub(text: str) -> str:
    """Every secret this suite knows, taken out by value; anything that looks like a token, by its shape."""
    for name in secrets.SECRET_NAMES:
        value = secrets.get_secret(name)
        if value and len(value) >= 6:
            text = text.replace(value, f"[{name}]")
    topic = config.get_config().ntfy_topic
    if topic and len(topic) >= 6:
        text = text.replace(topic, "[NTFY_TOPIC]")
    text = re.sub(r"\b(github_pat|ghp|gho|ghs|sk-ant)[_-][A-Za-z0-9_-]{6,}", "[redacted]", text)
    return re.sub(r"(?i)\b(bearer|token)(\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1\2[redacted]", text)


def first_line(text: Optional[str]) -> str:
    return ((text or "").strip().splitlines() or [""])[0][:100]


def note_errors(ctx: runner.Context, now: datetime) -> None:
    """Every new error with a traceback counted under its signature (dry run too: bookkeeping, nothing leaves)."""
    conn = ctx.conn
    top = db.one(conn, "SELECT COALESCE(MAX(id), 0) AS n FROM errors")["n"]
    seen = settings.get(conn, SEEN_KEY)
    where, args = ("id > ?", int(seen)) if seen is not None and seen.isdigit() else ("ts >= ?", iso(now - FIRST_LOOK))
    for r in db.rows(conn, f"SELECT * FROM errors WHERE traceback IS NOT NULL AND traceback != '' AND {where} AND id <= ? "
                           "ORDER BY id", (args, top)):
        sig = signature(r["agent"], r["kind"], r["traceback"])
        conn.execute("INSERT OR IGNORE INTO doctor_issues (signature, agent, kind, title, first_error, last_error, seen, last_seen_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                     (sig, r["agent"], r["kind"], f"{r['agent']}: {r['kind']}: {first_line(r['message'])}", r["id"], r["id"], r["ts"]))
        conn.execute("UPDATE doctor_issues SET seen=seen+1, last_error=?, last_seen_at=? WHERE signature=?", (r["id"], r["ts"], sig))
    settings.set(conn, SEEN_KEY, str(top))


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "event-caliber-doctor"}


def tail_log(agent: str) -> tuple[str, str]:
    logs_dir = config.get_config().logs_dir
    for name in (f"{agent}.log", f"{agent}.launchd.log"):
        path = logs_dir / name
        if path.is_file():
            with path.open("rb") as fh:
                fh.seek(max(0, path.stat().st_size - 65536))
                text = fh.read().decode("utf-8", "replace")
            return name, "\n".join(text.splitlines()[-LOG_LINES:])
    return f"{agent}.log", ""


def issue_body(issue, err) -> str:
    cfg = config.get_config()
    when = watchdog.parse_ts(err["ts"]) if err else None
    log_name, log = tail_log(issue["agent"])
    parts = [f"**{issue['agent']}** raised **{issue['kind']}** on the Mini at "
             f"{when.astimezone(zone()):%Y-%m-%d %H:%M} ({cfg.timezone})." if when else f"**{issue['agent']}** raised **{issue['kind']}**.",
             "", (err["message"] if err else ""), "", "Traceback:", "```", ((err["traceback"] if err else "") or "").strip(), "```", "",
             f"The last {LOG_LINES} lines of `logs/{log_name}` on the Mini:", "```", log or "(no log file)", "```", "",
             f"Seen {issue['seen']} time(s); the newest is errors row {err['id'] if err else '?'} on the Agents page. Signature "
             f"`{issue['signature']}`: the doctor opens one issue per distinct error and never a second one for a repeat."]
    if issue["reopened_from"]:
        parts.append(f"It came back after #{issue['reopened_from']} was closed.")
    parts += ["", "Filed by the doctor (`convention_social/agents/doctor.py`). It never edits code on the Mini: the fix comes "
                  "as a pull request."]
    return scrub("\n".join(parts))[:60000]


def came_back(ctx: runner.Context, now: datetime, h: Hands, token: str) -> list[str]:
    """A filed error seen again: once a day its issue is read; closed means Chris thought it fixed, so it is filed anew."""
    lines, today = [], now.astimezone(zone()).date().isoformat()
    for r in db.rows(ctx.conn, "SELECT * FROM doctor_issues WHERE url IS NOT NULL AND number IS NOT NULL "
                               "AND last_error > COALESCE(checked_error, 0) AND COALESCE(checked_on, '') != ?", (today,)):
        try:
            status, data = h.github("GET", f"{GITHUB_API}/repos/{ISSUE_REPO}/issues/{r['number']}", headers(token), None)
        except Exception:  # noqa: BLE001  the network: read again tomorrow
            continue
        ctx.conn.execute("UPDATE doctor_issues SET checked_on=?, checked_error=? WHERE signature=?", (today, r["last_error"], r["signature"]))
        if status == 200 and data.get("state") == "closed":
            ctx.conn.execute("UPDATE doctor_issues SET url=NULL, number=NULL, reopened_from=? WHERE signature=?",
                             (r["number"], r["signature"]))
            lines.append(f"{r['title']} came back after issue #{r['number']} was closed")
    return lines


def file_issues(ctx: runner.Context, now: datetime, h: Hands) -> list[str]:
    conn = ctx.conn
    note_errors(ctx, now)
    token = secrets.get_secret("GITHUB_TOKEN")
    lines = came_back(ctx, now, h, token) if token and not ctx.dry_run else []
    for r in db.rows(conn, "SELECT * FROM doctor_issues WHERE url IS NULL AND last_seen_at >= ? ORDER BY first_error",
                     (iso(now - ISSUE_WINDOW),)):
        title = scrub(r["title"])[:120]
        p = Problem(f"issue:{r['signature']}", "issue", f"An error in our code: {title}.")
        if not may_try(ctx, p, now):
            continue
        if ctx.dry_run:
            record(conn, p, f"would {doing(p)}", now, "would", dry=True)
            lines.append(f"would open a GitHub issue for {title}")
            continue
        if not token:
            record(conn, p, f"could not {doing(p)}", now, "cannot", dry=False,
                   detail="No GITHUB_TOKEN on the Keys page, so no issue was opened.")
            if not r["pinged_at"]:
                h.push(f"{ctx.cfg.brand_name}: an error in the code", f"{title}. No GitHub token on the Keys page, so no issue "
                       "was opened; the Errors page has the traceback.", dry_run=ctx.dry_run, priority="high",
                       click=notify.link("/errors"), conn=conn, agent=AGENT)
                conn.execute("UPDATE doctor_issues SET pinged_at=? WHERE signature=?", (iso(now), r["signature"]))
            lines.append(f"no GitHub token: pinged about {title}")
            continue
        filed = db.one(conn, "SELECT COUNT(*) AS n FROM doctor_remedies WHERE problem LIKE 'issue:%' AND outcome='filed' "
                             "AND started_at >= ?", (iso(day_start(now)),))["n"]
        if filed >= ISSUES_A_DAY:
            runner.record_error_once(conn, AGENT, "github_issue", f"More than {ISSUES_A_DAY} distinct errors in the code today; "
                                     "the doctor files no more issues until tomorrow. The Errors page has them all.")
            continue
        err = db.one(conn, "SELECT * FROM errors WHERE id=?", (r["last_error"],))
        try:
            status, data = h.github("POST", f"{GITHUB_API}/repos/{ISSUE_REPO}/issues", headers(token),
                                    {"title": title, "body": issue_body(r, err)})
        except Exception as e:  # noqa: BLE001  the network
            status, data = 0, {"message": f"{type(e).__name__}: {e}"}
        if status == 201 and data.get("html_url"):
            number, url = data.get("number"), data["html_url"]
            conn.execute("UPDATE doctor_issues SET number=?, url=?, opened_at=?, checked_error=? WHERE signature=?",
                         (number, url, iso(now), r["last_error"], r["signature"]))
            record(conn, p, f"opened issue #{number} {url}", now, "filed", dry=False, detail=url)
            h.push(f"{ctx.cfg.brand_name}: an error in the code", f"{title}. Issue #{number} holds the traceback and the last "
                   "log lines; the fix comes as a pull request.", dry_run=ctx.dry_run, priority="high",
                   click=url, conn=conn, agent=AGENT)
            lines.append(f"opened issue #{number} for {title}")
            continue
        why = scrub(f"GitHub answered HTTP {status}: {str(data.get('message') or '')[:120]}")
        runner.record_error_once(conn, AGENT, "github_issue", f"No GitHub issue for {title}: {why}." + (
            " The GITHUB_TOKEN on the Keys page may have expired or may lack Issues access." if status in (401, 403, 404) else ""))
        lines.append(finish(ctx, p, f"could not {doing(p)}", "not_fixed", why, now, h))
    return lines


# ------------------------------------------------------------------ the digest

VERDICT = {"would": " (dry run)", "pending": "; checking", "fixed": ": fixed", "not_fixed": ": not fixed",
           "cannot": "", "left": "; then you took it from there", "filed": ""}


def digest_lines(conn: sqlite3.Connection, since: datetime) -> list[str]:
    """One plain line per remedy since `since`, for the watchdog's digest and the morning brief."""
    try:
        rows = db.rows(conn, "SELECT * FROM doctor_remedies WHERE started_at >= ? ORDER BY id", (iso(since),))
    except sqlite3.OperationalError:          # the table arrives with this agent's migration
        return []
    out = []
    for r in rows:
        detail = f" {cap(r['detail'])}" if r["detail"] and r["outcome"] in ("fixed", "not_fixed", "cannot", "left") else ""
        out.append(f"{hhmm(r['started_at'])}: {cap(r['found'])} {cap(r['remedy'])}{VERDICT.get(r['outcome'], '')}.{detail}")
    return out


# ------------------------------------------------------------------ entry

def run(ctx: runner.Context, *, now: Optional[datetime] = None, hands: Optional[Hands] = None) -> str:
    now = now or datetime.now(timezone.utc)
    h = hands or Hands()
    lines = verify_pending(ctx, now, h)
    starts = 0
    for p in find(ctx, now, h):
        if not may_try(ctx, p, now):
            continue
        if p.kind in ("agent", "backup"):
            if starts >= STARTS_A_RUN:
                continue
            starts += 1
        line = treat(ctx, p, now, h)
        if line:
            lines.append(line)
    lines += file_issues(ctx, now, h)
    return ("DRY RUN " if ctx.dry_run else "") + ("; ".join(lines) if lines else "nothing to fix")


if __name__ == "__main__":
    runner.main_for(AGENT, run)
