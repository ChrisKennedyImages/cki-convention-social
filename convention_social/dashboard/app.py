"""The review dashboard: 127.0.0.1 only, one password, built for a phone screen.

Server-rendered FastAPI + Jinja2, no JavaScript framework. Reached from
Chris's phone over Tailscale. With no DASHBOARD_PASSWORD_HASH the app
answers 503 to everything (fail closed).

Four tabs (2026-10-15): Today (every draft waiting on Chris, each with Post now,
Follow the pace and Skip, refused while a caption breaks a rule or a photo is no
longer eligible; what is scheduled this week; what went out), Photos (clear or
exclude folders, block single photos, music for reels, Do not use, Drive),
Bookings (requests, bookings, the calendar), Settings (Agents, Errors, Keys,
Buffer; Outreach, Scout, Search, Learner).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..agents import AGENTS, is_built
from ..ai import copy_rules, spend
from ..ai import names as ai_names
from ..ai.claude import NETWORKS
from ..buffer import payloads as buffer_payloads
from ..buffer.client import BufferBudgetExceeded, BufferClient, BufferError, BufferRateLimited
from ..core import access, approve_token, auth, config, db, runner, secrets, settings, state_io
from .. import music
from ..library import eligibility, report
from . import alerts
from . import today as today_view

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
TEMPLATES.env.filters["local"] = today_view.local_words       # a stored UTC time in his own words and time zone
COOKIE = "ccs_session"
SESSION_DAYS = 30
QUEUE_STATUSES = ("draft", "approved", "would_publish", "scheduled", "published", "failed", "rejected")
ID_IN_LINK = re.compile(r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_-]{2,})")


# ---------------------------------------------------------------------- session
_session_secret = approve_token.secret      # one secret file signs the session cookie and the pings' approve tokens


def make_token(user: str, now: Optional[float] = None) -> str:
    exp = int((now or time.time()) + SESSION_DAYS * 86400)
    body = f"{user}|{exp}"
    sig = hmac.new(_session_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def read_token(token: Optional[str]) -> Optional[str]:
    if not token or token.count("|") != 2:
        return None
    user, exp, sig = token.split("|")
    good = hmac.new(_session_secret(), f"{user}|{exp}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(good, sig):
        return None
    try:
        if int(exp) < time.time():
            return None
    except ValueError:
        return None
    return user


def password_configured() -> bool:
    return bool(secrets.get_secret("DASHBOARD_PASSWORD_HASH"))


def require_user(request: Request) -> str:
    if not password_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Dashboard password not set. Run `bin/ccs hash-password` and put the line in .env.")
    user = read_token(request.cookies.get(COOKIE))
    if user is None:
        if request.method == "GET":
            raise HTTPException(status.HTTP_307_TEMPORARY_REDIRECT, headers={"Location": f"/login?next={request.url.path}"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in")
    return user


def conn_dep():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


# Chris, 2026-10-11: "The navigation is not intuitive or smart!" Thirteen tabs became four, each
# with its own short row of pages, so every page is one tap from its section and two from anywhere.
# Chris, 2026-10-15: "we really need to fix this dashboard ... everything is just very confusing". Today is one
# page (the drafts, the week, what went out); More became Settings, its system pages first.
SECTIONS = (
    ("Today", "/", ("/queue", "/posts", "/send", "/history"), (("Today", "/"), ("Send a photo", "/send"), ("All posts", "/history"))),
    ("Photos", "/library", ("/library", "/donotuse", "/drive", "/music"),
     (("To review", "/library"), ("Approved", "/library?view=approved"), ("Blocked", "/library?view=blocked"),
      ("Folders", "/library?view=folders"), ("Music", "/music"), ("Do not use", "/donotuse"), ("Drive", "/drive"))),
    ("Bookings", "/inquiries", ("/inquiries", "/bookings", "/calendar"),
     (("Requests", "/inquiries"), ("Bookings", "/bookings"), ("Calendar", "/calendar"))),
    ("Settings", "/settings", ("/settings", "/more", "/outreach", "/scout", "/seo", "/learner", "/agents", "/buffer", "/keys", "/errors"),
     (("Agents", "/agents"), ("Errors", "/errors"), ("Keys", "/keys"), ("Buffer", "/buffer"),
      ("Outreach", "/outreach"), ("Scout", "/scout"), ("Search", "/seo"), ("Learner", "/learner"))),
)
# the Settings page, its pages in two groups (2026-10-15: "System pages grouped")
SETTINGS_GROUPS = (
    ("System", (("/agents", "Agents", "Every agent: run now, live or practice run."),
                ("/errors", "Errors", "What the agents could not do, each with its fix where there is one."),
                ("/keys", "Keys", "Accounts, addresses, passwords and the numbers the suite uses."),
                ("/buffer", "Buffer", "Link Instagram, pick the board, check the reel format."))),
    ("Finding work", (("/outreach", "Outreach", "Notes to event organizers, each sent only when you approve it."),
                      ("/scout", "Scout", "Upcoming conventions and conferences it found, with sources."),
                      ("/seo", "Search", "How eventcaliber.com shows up in search, and the words on your photos."),
                      ("/learner", "Learner", "What the post numbers say about times and kinds of photo."))),
)


def nav_for(request: Request) -> dict:
    path = request.url.path
    view = request.query_params.get("view", "")
    here = next((s for s in SECTIONS if (path == "/" and s[1] == "/") or any(path.startswith(p) for p in s[2])), SECTIONS[0])

    def on(href: str) -> bool:
        p, _, q = href.partition("?")
        if p != path and not (p != "/" and path.startswith(p + "/")):
            return False
        want = dict(x.split("=", 1) for x in q.split("&") if "=" in x).get("view", "")
        return want == view or (path.startswith("/library/folder/") and want == "folders")
    return {"tabs": [{"label": s[0], "href": s[1], "on": s is here} for s in SECTIONS],
            "chips": [{"label": label, "href": href, "on": on(href)} for label, href in here[3]] if len(here[3]) > 1 else []}


def practice_lines() -> Optional[dict]:
    """The banner on every page while the publisher or the content lane is in practice run (dry run): posts are not
    going out, and where to switch it on (2026-10-15). Fail closed: a database that cannot be read shows it."""
    try:
        conn = db.connect()
    except Exception:  # noqa: BLE001
        return today_view.practice(None)
    try:
        return today_view.practice(conn)
    finally:
        conn.close()


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("brand", config.get_config().brand_name)
    ctx.setdefault("nav", nav_for(request))
    ctx.setdefault("practice", practice_lines() if name != "login.html" else None)     # said once signed in, not to the door
    ctx.setdefault("status_words", today_view.STATUS_WORDS)
    return TEMPLATES.TemplateResponse(request, name, ctx)


# what Today says after a choice made elsewhere, by its short word; any other message is shown as it is
MSGS = {"redraft": "Fixed. That draft is set aside and a new one is being made with the right words; it shows here in a few "
                   "minutes, and your phone gets a ping."}


def designed_note(conn) -> str:
    from ..agents import designed
    try:
        return designed.status_line(conn)
    except Exception as e:  # noqa: BLE001  a line on the page, never a broken page
        return f"Designed drafts: the state could not be read ({type(e).__name__})."


def inside_data_root(p: Path) -> bool:
    try:
        return p.resolve().is_relative_to(config.get_config().data_root.resolve()) and p.exists()
    except OSError:
        return False


# ---------------------------------------------------------------------- queue helpers
def official_for(conn, row) -> bool:
    from ..agents.content import official_for as _official
    return _official(conn, row)


NOT_THUMBS = ("9:16", "cover", "stills")   # a reel plays as a video with its cover; the stills are for the art director


def queue_view(conn, row) -> dict:
    captions = json.loads(row["caption"] or "{}")
    targets = json.loads(row["targets"] or "[]")
    official = official_for(conn, row)
    known_names = ai_names.public_names(conn)
    reports = {n: copy_rules.check(captions.get(n, ""), official=official, names=known_names, social=True) for n in NETWORKS}
    photo_ids = json.loads(row["photo_ids"] or "[]")
    photo_checks = [(pid, *eligibility.is_eligible(conn, int(pid)), shot_type_of(conn, int(pid))) for pid in photo_ids]
    renders = json.loads(row["render_paths"] or "{}")
    try:
        meta = json.loads(row["rule_report"] or "{}")
    except ValueError:
        meta = {}
    art = meta.get("art") or {}
    mended = meta.get("mended") or []
    on = alerts.networks_on()
    return {**dict(row), "art": art, "captions": captions, "targets": targets, "reports": reports, "official": official,
            "design_name": DESIGN_WORDS.get(meta.get("design") or "", meta.get("design") or ""),
            "mended": mended[-1] if mended else None,
            "blocked_networks": [n for n in targets if not reports[n].ok],
            "photo_checks": photo_checks, "ineligible": [c for c in photo_checks if not c[1]],
            "video": any(str(x).lower().endswith(".mp4") for x in renders.get("9:16") or []), "cover": bool(renders.get("cover")),
            "music": music.credit(conn, meta.get("music")),          # the track the reel was made with, named under its player
            "renders": {a: list(range(1, len(ps) + 1)) for a, ps in renders.items()
                        if a not in NOT_THUMBS and (a != "2:3" or "pinterest" in on)}}     # the pin card only while Pinterest is on


MEDIA_TYPES = {".mp4": "video/mp4", ".png": "image/png"}
DESIGN_WORDS = {"single": "single photo"}       # every other design is called by its own name (fan, spotlight, carousel, reel)


# what a photo shows, in plain words, for the draft page's correction (Chris, 2026-10-11: "it calls a
# stage shot a portrait which, never can happen!")
SHOT_CHOICES = [("stage_panel", "Stage and panel"), ("backstage", "Backstage"), ("portrait", "Portrait or headshot"),
                ("group", "Group photo"), ("candid", "Candid moment"), ("crowd", "Crowd"),
                ("vendor_hall", "Exhibition hall, vendors or a booth"), ("dinner_reception", "Dinner and reception"), ("venue", "Venue"),
                ("building_exterior", "Building exterior"), ("building_interior", "Building interior"), ("other", "Other")]


def shot_type_of(conn, photo_id: int) -> str:
    row = db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (photo_id,))
    return (row["shot_type"] if row else None) or ""


start_agent = runner.start_agent      # one run now, exactly as its schedule would start it (core/runner.py)


def set_aside(conn, row, *, by: str, why: str) -> None:
    """A post out of the running, with who set it aside in its record (`rule_report.rejected_by`): the content
    agent counts its photo as used (agents/content.recent_use) and drafts the day again; the Queue shows why."""
    try:
        meta = json.loads(row["rule_report"] or "{}")
    except ValueError:
        meta = {}
    meta = meta if isinstance(meta, dict) else {}
    now = db.utcnow()
    meta.update(rejected_by=by, rejected_at=now)
    conn.execute("UPDATE content_queue SET status='rejected', rule_report=?, last_error=?, updated_at=? WHERE id=?",
                 (json.dumps(meta), why, now, row["id"]))


# Chris, 2026-10-13: posts and replies he approved in dry run go out when the lane is switched live. What the
# dry run marked would_publish / would_send is approved again (the publisher's door, reply.ready_to_send and
# compliance.problems check every one before it leaves); what was sent stays as it is.
DRY_RUN_RELEASES = {
    "publisher": "UPDATE content_queue SET status='approved', payload=NULL, last_error=NULL, updated_at=? WHERE status='would_publish'",
    "inbox": "UPDATE inquiries SET reply_status='approved', notes=NULL, updated_at=? WHERE reply_status='would_send'",
    "outreach": "UPDATE outreach SET status='approved', notes=NULL, updated_at=? WHERE status='would_send'",
}


def release_dry_run_approvals(conn, name: str) -> int:
    """How many things approved in dry run the lane `name` now sends for real."""
    sql = DRY_RUN_RELEASES.get(name)
    return conn.execute(sql, (db.utcnow(),)).rowcount if sql else 0


def released_note(n: int) -> str:
    if not n:
        return ""
    return f" {n} thing{'s' if n != 1 else ''} you approved in practice run go{'' if n != 1 else 'es'} out at {'their' if n != 1 else 'its'} time{'s' if n != 1 else ''}."


def photo_ids_of_row(row) -> list[int]:
    try:
        return [int(x) for x in json.loads(row["photo_ids"] or "[]")]
    except (TypeError, ValueError):
        return []


def load_queue_row(conn, qid: int):
    row = db.one(conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
    if row is None:
        raise HTTPException(404)
    return row


def drive_id_from(text: str) -> str:
    text = (text or "").strip()
    m = ID_IN_LINK.search(text)
    return m.group(1) if m else text


# ---------------------------------------------------------------------- app
RUNNABLE = {name for name in AGENTS if name not in ("dashboard", "art_director")}   # one-shot agents only
RENDER_NAME = re.compile(r"(library-report|contact-sheet|building-sheet)-\d{8}\.(html|jpg)")


def latest_renders() -> dict:
    """The newest library report, event contact sheet and building sheet in DATA_ROOT/renders, by name."""
    renders = config.get_config().data_root / "renders"
    found = {}
    for key, pattern in (("report", "library-report-*.html"), ("sheet", "contact-sheet-*.jpg"),
                         ("buildings", "building-sheet-*.jpg")):
        names = sorted(p.name for p in renders.glob(pattern) if RENDER_NAME.fullmatch(p.name)) if renders.is_dir() else []
        if names:
            found[key] = names[-1]
    return found


DESIGN_DIR = re.compile(r"design-\d{8}-\d{4}")
DESIGN_FILE = re.compile(r"(index\.html|about\.json|[a-z]+-post\.jpg|slide-\d{2}\.jpg|[a-z]+-reel\.mp4|[a-z]+-reel-cover\.jpg)")
DESIGN_TYPES = {".html": "text/html", ".json": "application/json", ".jpg": "image/jpeg", ".mp4": "video/mp4"}


PAGE = 48
SORTED = "c.method IN ('ollama', 'vision')"
# report.strength, in SQL: the old single score for a photo sorted before the strength questions,
# else quality + light + moment, minus 6 when the subject is soft, on 0 to 10.
STRENGTH = """CASE WHEN c.light IS NULL AND c.moment IS NULL THEN COALESCE(c.quality, 0) * 1.0
                   ELSE MAX(0.0, (COALESCE(c.quality, 0) + COALESCE(c.light, 0) + COALESCE(c.moment, 0)
                                  - CASE WHEN c.sharp = 0 THEN 6 ELSE 0 END) * 10.0 / 15) END"""
DECISION = ("CASE WHEN p.clearance = 'blocked' THEN 'blocked' WHEN fd.decision = 'excluded' THEN 'excluded' "
            "WHEN p.clearance = 'cleared' THEN 'cleared' ELSE COALESCE(fd.decision, 'not_cleared') END")
PAGE_FROM = """FROM photos p LEFT JOIN classifications c ON c.photo_id = p.id
               LEFT JOIN drive_folders f ON f.drive_id = p.folder_id
               LEFT JOIN temp.folder_decision fd ON fd.drive_id = p.folder_id"""
VIEWS = {
    # Sorted photos Chris has not decided on that could ever be used: no readable personal detail
    # (temp.hidden_photo). No age filter: he judges every photo himself (2026-10-15). Strongest first.
    "review": (f"p.trashed = 0 AND {SORTED} AND {DECISION} = 'not_cleared' "
               "AND COALESCE(c.shot_type, '') NOT IN ('cosplay_portrait') "
               "AND COALESCE(c.event_kind, '') NOT IN ('wedding', 'private') "
               "AND p.id NOT IN (SELECT id FROM temp.hidden_photo)",
               f"({STRENGTH}) DESC, p.id"),
    # Everything Chris cleared, by the photo itself or by its folder. Sorted ones first, strongest first.
    "approved": (f"p.trashed = 0 AND {DECISION} = 'cleared'",
                 f"CASE WHEN {SORTED} THEN 0 ELSE 1 END, CASE WHEN {SORTED} THEN ({STRENGTH}) ELSE 0 END DESC, p.id"),
    # Every photo Chris marked Don't use, newest decision first (2026-10-13: a Don't use was invisible afterwards).
    "blocked": (f"p.trashed = 0 AND {DECISION} = 'blocked'", "COALESCE(p.clearance_at, '') DESC, p.id DESC"),
}


def prepare_photo_views(conn, decisions) -> None:
    """Per connection: each folder's decision, and the photos a readable personal detail keeps off
    the review list (eligibility.blocking_details, read only for the few photos that list any)."""
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS folder_decision (drive_id TEXT PRIMARY KEY, decision TEXT NOT NULL)")
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS hidden_photo (id INTEGER PRIMARY KEY)")
    conn.execute("DELETE FROM temp.folder_decision")
    conn.execute("DELETE FROM temp.hidden_photo")
    conn.executemany("INSERT INTO temp.folder_decision VALUES (?, ?)", [(k, v) for k, v in decisions.items() if v != "not_cleared"])
    hidden = []
    for r in db.rows(conn, "SELECT c.photo_id, c.personal_details, c.subject FROM classifications c "
                           "WHERE c.personal_details IS NOT NULL AND TRIM(c.personal_details) NOT IN ('', '[]')"):
        try:
            details = json.loads(r["personal_details"])
        except ValueError:
            details = ["unreadable"]
        if eligibility.blocking_details(details, r["subject"]):
            hidden.append((r["photo_id"],))
    conn.executemany("INSERT INTO temp.hidden_photo VALUES (?)", hidden)


# Chris, 2026-10-11: "Architecture images should be separated from event/convention photos". Each
# list is shown in two parts: the event work, and the building work (the sorter's subject).
SUBJECTS = {"event": "COALESCE(c.subject, '') != 'architecture'", "architecture": "c.subject = 'architecture'"}
SUBJECT_WORDS = (("event", "Events"), ("architecture", "Buildings"))


def _where(view: str, subject: Optional[str]) -> str:
    where = VIEWS[view][0]
    return f"{where} AND {SUBJECTS[subject]}" if subject else where


def count_photos(conn, view: str, subject: Optional[str] = None) -> int:
    return db.one(conn, f"SELECT COUNT(*) AS n {PAGE_FROM} WHERE {_where(view, subject)}")["n"]


def photo_page(conn, view: str, page: int, size: int = PAGE, subject: Optional[str] = None) -> list[dict]:
    """One page of a photo list, read straight from the database: the Photos tab never loads the
    whole library (Chris, 2026-10-11: "Photos tab is dead")."""
    where, order = _where(view, subject), VIEWS[view][1]
    return [dict(r) for r in db.rows(conn, f"""SELECT p.*, c.method, c.subject, c.shot_type, c.quality, c.sharp, c.light, c.moment,
                                                      c.possible_minor, c.personal_details, f.name AS folder_name
                                               {PAGE_FROM} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""",
                                     (size, (page - 1) * size))]


# The Photos tab asks for 48 previews at once. Each Drive fetch happens once per photo (a second
# request for the same photo waits for the first), at most THUMB_FETCHES at a time, and the file is
# written whole before anyone can read it (2026-10-11: "Too many open files" and "Too little data for
# declared Content-Length" on /media/thumb).
THUMB_FETCHES = threading.BoundedSemaphore(6)
_thumb_locks: dict[str, threading.Lock] = {}
_thumb_locks_guard = threading.Lock()


def _thumb_lock(drive_id: str) -> threading.Lock:
    with _thumb_locks_guard:
        return _thumb_locks.setdefault(drive_id, threading.Lock())


def cached_thumb(drive_id: str, fetch) -> Optional[Path]:
    """The preview's file, fetched with `fetch(drive_id) -> bytes` only when it is not cached yet.
    None when there is nothing to show (no fetch, or Drive could not give it)."""
    path = config.get_config().data_root / "thumbs" / f"{drive_id}.jpg"
    if path.is_file() and path.stat().st_size > 0:
        return path
    if fetch is None:
        return None
    with _thumb_lock(drive_id):
        if path.is_file() and path.stat().st_size > 0:
            return path
        try:
            with THUMB_FETCHES:
                data = fetch(drive_id)
        except Exception:  # noqa: BLE001  not signed in, network: no picture, not a crash
            return None
        if not data:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
        tmp.write_bytes(data)
        os.replace(tmp, path)                   # readers see the whole file or none of it
        return path


def running_commit() -> str:
    """The commit of the code this process loaded ("" when git cannot say; never stops the dashboard)."""
    try:
        r = subprocess.run(["git", "-C", str(config.REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


RUNNING_COMMIT = running_commit()        # read once, when this process loads the code

BUFFER_ERRORS = (BufferError, BufferBudgetExceeded, BufferRateLimited)


def buffer_client(conn) -> Optional[BufferClient]:
    """The Buffer page's client (None until the key is set). Tests stand in for it."""
    return BufferClient.from_config(conn, agent="dashboard")


def _setting_json(conn, key: str, default):
    try:
        return json.loads(settings.get(conn, key) or "null") or default
    except ValueError:
        return default


def buffer_state(conn) -> dict:
    """Everything the Buffer page shows, read from this Mini only (no call to Buffer)."""
    cached = state_io.load_json(BufferClient.cache_path(), {}) or {}
    chosen = config.getenv("BUFFER_ORGANIZATION_ID", "") or ""
    same_org = not chosen or cached.get("organizationId") == chosen
    linked = {r["service"]: dict(r) for r in db.rows(conn, "SELECT * FROM channels ORDER BY id")}
    return {"key": bool(secrets.get_secret("BUFFER_API_KEY")), "orgs": _setting_json(conn, "buffer.organizations", []),
            "org": chosen, "found": (cached.get("channels") or []) if same_org else [],
            "fetched_at": cached.get("fetched_at") if same_org else None, "linked": linked,
            "linked_ids": {r["buffer_channel_id"] for r in linked.values()},
            "boards": _setting_json(conn, "buffer.pinterest_boards", []), "board": config.getenv("PINTEREST_BOARD_ID", "") or "",
            "video": _setting_json(conn, "buffer.video_fields", None),
            "image_alt": _setting_json(conn, "buffer.image_alt", None),
            "media": bool(config.getenv("MEDIA_BASE_URL") and secrets.get_secret("MEDIA_UPLOAD_TOKEN")),
            "publisher_live": not settings.dry_run(conn, "publisher"), "networks": buffer_payloads.NETWORKS}


CRASH_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Something broke</title><style>body{{margin:0;padding:18px;font:16px/1.5 -apple-system,Helvetica,Arial,sans-serif;background:#f4f4f2;color:#17171a}}
.card{{background:#fff;border:1px solid #e2e1dc;border-radius:12px;padding:14px;margin:0 0 14px}}code{{word-break:break-word}}a{{color:#1f4fd1;font-weight:600}}</style></head>
<body><h1>This page broke</h1><div class="card">Page: <code>{path}</code><br>What failed: <code>{what}</code></div>
<div class="card">It is recorded on <a href="/agents">Agents</a> (error {eid}), with the details. Nothing was changed by it.</div>
<a href="/">Back to Today</a></body></html>"""


def record_crash(path: str, exc: BaseException) -> Optional[int]:
    """A page that fails says so and leaves its trace on the Agents page, instead of a dead screen."""
    import traceback
    from ..core import runner
    try:
        conn = db.connect()
        try:
            return runner.record_error(conn, "dashboard", "page_error", f"{path}: {type(exc).__name__}: {exc}"[:500],
                                       tb="".join(traceback.format_exception(exc))[-8000:])
        finally:
            conn.close()
    except Exception:  # noqa: BLE001  the page still answers when even the database cannot be reached
        return None


def create_app() -> FastAPI:
    app = FastAPI(title="review", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(Exception)
    async def crashed(request: Request, exc: Exception):
        import html as html_mod
        eid = record_crash(request.url.path, exc)
        return HTMLResponse(CRASH_PAGE.format(path=html_mod.escape(request.url.path),
                                              what=html_mod.escape(f"{type(exc).__name__}: {exc}"[:300]),
                                              eid=eid if eid is not None else "not saved"), status_code=500)

    @app.middleware("http")
    async def never_stale(request: Request, call_next):
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("text/html") or response.status_code in (303, 307):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def through_access_only(request: Request, call_next):
        """Chris, 2026-10-15: the dashboard away from home is never public without Access. Whatever came through
        Cloudflare (the tunnel) without a valid Access token for him is refused before any page, the login
        included (core/access.py). Tailscale and the Mini itself carry no Cloudflare header: untouched."""
        from starlette.concurrency import run_in_threadpool
        if not access.from_outside(request.headers):
            return await call_next(request)
        why = await run_in_threadpool(access.refusal, request.headers, request.cookies)     # may read Cloudflare's keys
        if why:
            return HTMLResponse(access.refused_page(why), status_code=403, headers={"Cache-Control": access.PRIVATE})
        response = await call_next(request)
        # Cloudflare keeps .jpg and .mp4 for two hours unless told otherwise (developers.cloudflare.com/cache/concepts/
        # default-cache-behavior/): his photos, renders, samples and reels never stay in its cache
        response.headers["Cache-Control"] = access.PRIVATE
        return response

    # ------------------------------------------------------------------ login
    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/", bad: str = ""):
        if not password_configured():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Dashboard password not set. Run `bin/ccs hash-password`.")
        return render(request, "login.html", next=next, bad=bad)

    @app.post("/login")
    def login(request: Request, password: str = Form(...), next: str = Form(default="/")):
        stored = secrets.get_secret("DASHBOARD_PASSWORD_HASH")
        if not stored:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Dashboard password not set.")
        if not auth.verify_password(password, stored):
            time.sleep(0.5)
            return RedirectResponse(f"/login?bad=1&next={next}", status_code=303)
        resp = RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)
        resp.set_cookie(COOKIE, make_token("chris"), max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax",
                        secure=access.secure_request(request.url.scheme, request.headers))     # https: never sent in the clear
        return resp

    @app.get("/healthz")
    def healthz():
        """For the updater on this Mini: which commit this running dashboard was started on."""
        return {"ok": True, "commit": RUNNING_COMMIT}

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    # ------------------------------------------------------------------ today
    @app.get("/", response_class=HTMLResponse)
    def today(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), show: str = "", msg: str = ""):
        """Chris, 2026-10-15: one Today page. Needs you (every draft waiting on his approve, newest first, with Post now,
        Follow the pace and Skip; what else needs him, each alert with its fix), This week, Went out."""
        if show:
            return RedirectResponse(f"/history?show={quote_plus(show)}", status_code=303)     # the old Queue's filters
        from ..agents import chief
        from ..buffer import metrics
        drafts = []
        for r in db.rows(conn, "SELECT * FROM content_queue WHERE kind='photo' AND status='draft' ORDER BY id DESC LIMIT 30"):
            item = queue_view(conn, r)
            item.update(origin=today_view.origin(r), choosable=today_view.choosable(item), card=today_view.card_path(r))
            pace = today_view.pace_slot(conn, r) if item["choosable"] else None
            item["pace_words"] = f"{today_view.day_words(pace)} {today_view.clock(pace)}" if pace else ""
            drafts.append(item)
        others = [(text, href) for text, href in chief.needs(conn) if href not in ("/", "/drive")]
        return render(request, "today.html", drafts=drafts, others=others, alerts=alerts.open_alerts(conn),
                      auth_state=settings.get(conn, "drive.auth_state") or "missing", msg=MSGS.get(msg, msg)[:400],
                      week=today_view.week(conn), went=today_view.went_out(conn), summary=metrics.summary(conn, 30),
                      designed_note=designed_note(conn), schedule=today_view.schedule(conn), sent_checked=today_view.sent_checked(conn))

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), show: str = "all"):
        """Every post, in plain words, with the old Queue's filters and the numbers by week (the old Posts page)."""
        from ..buffer import metrics
        if show in QUEUE_STATUSES:
            where, params = "status = ?", (show,)
        else:
            show, where, params = "all", "1=1", ()
        rows = db.rows(conn, f"SELECT * FROM content_queue WHERE {where} ORDER BY id DESC LIMIT 200", params)
        items = [{**dict(r), "origin": today_view.origin(r), "card": today_view.card_path(r)} for r in rows]
        return render(request, "history.html", items=items, show=show, trend=metrics.trend(conn, 12),
                      filters=[("all", "All")] + [(k, today_view.STATUS_WORDS[k]) for k in
                                                  ("draft", "approved", "scheduled", "published", "would_publish", "rejected", "failed")])

    @app.get("/queue")
    def queue_list():
        return RedirectResponse("/", status_code=303)

    @app.get("/send", response_class=HTMLResponse)
    def send_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Chris, 2026-10-14: a photo from his phone while he is shooting becomes a draft post (agents/phone.py)."""
        from ..agents import phone
        return render(request, "send.html", sends=phone.recent(conn), msg=request.query_params.get("msg", ""),
                      waiting=phone.waiting(conn), lane_dry=settings.dry_run(conn, "content"))

    @app.post("/send")
    async def send_photo(file: UploadFile = File(...), note: str = Form(""), user: str = Depends(require_user), conn=Depends(conn_dep)):
        """The picture is kept on the Mini (never Drive) as a cleared photo of its own, and the phone agent drafts it now:
        sorted, Claude's final check, captions with his line, the design, the art director, the ping with Approve."""
        from ..agents import phone
        data = await file.read(phone.MAX_BYTES + 1)
        try:
            phone.keep(conn, data, note)
        except phone.Refused as e:
            return RedirectResponse("/send?msg=" + quote_plus(f"Not kept: {e}"), status_code=303)
        start_agent("phone", wait=True)
        return RedirectResponse("/send?msg=" + quote_plus("Sent. It is being sorted, checked and drafted now; your phone gets a ping "
                                                          "with the post in a few minutes."), status_code=303)

    @app.get("/posts")
    def posts():
        """The old Posts page lives on Today now: Went out, with the numbers (2026-10-15)."""
        return RedirectResponse("/#went-out", status_code=303)

    @app.post("/queue/{qid}/pullback")
    def queue_pullback(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """7.5: a post Buffer already holds comes back here as a draft, deleted in Buffer first (one network at a
        time; what Buffer kept stays scheduled, with the reason on the Agents page)."""
        row = load_queue_row(conn, qid)
        if row["status"] != "scheduled":
            return RedirectResponse(f"/queue/{qid}", status_code=303)
        client = BufferClient.from_config(conn, "dashboard")
        if client is None:
            return RedirectResponse(f"/queue/{qid}?msg=no_buffer", status_code=303)
        ids = dict(json.loads(row["buffer_post_ids"] or "{}"))
        for net, pid in list(ids.items()):
            try:
                client.delete_post(pid)
            except (BufferError, BufferBudgetExceeded, BufferRateLimited, OSError) as e:
                runner.record_error(conn, "dashboard", "pullback", f"post {qid}, {net}: Buffer kept it: {e}")
                conn.execute("UPDATE content_queue SET buffer_post_ids=?, updated_at=? WHERE id=?", (json.dumps(ids), db.utcnow(), qid))
                return RedirectResponse(f"/queue/{qid}?msg=pullback_failed", status_code=303)
            ids.pop(net)
        conn.execute("UPDATE content_queue SET status='draft', buffer_post_ids=NULL, payload=NULL, last_error=?, updated_at=? WHERE id=?",
                     ("Pulled back from Buffer by you. It will not go out until you approve it again.", db.utcnow(), qid))
        return RedirectResponse(f"/queue/{qid}?msg=pulled_back", status_code=303)

    def mended_row(conn, row):
        """Chris, 2026-10-12: "the captions should auto correct themselves with the warnings they gave me
        before approval. I don't want to change any captions." A draft he opens or approves whose captions
        break a rule now is rewritten by the suite first (agents/content.mend_captions); he never edits."""
        from ..agents import content
        if row["status"] in content.MENDABLE and queue_view(conn, row)["blocked_networks"]:
            try:
                mended = content.mend_captions(conn, row, agent="dashboard")
            except Exception as e:  # noqa: BLE001  the rewrite could not run (the API, the network): the page still answers
                runner.record_error_once(conn, "dashboard", "mend",
                                         f"The suite could not rewrite the captions of post {row['id']}: {type(e).__name__}: {e}")
                return row, "mend_failed"
            if mended is not None:
                return load_queue_row(conn, row["id"]), "mended"
        return row, ""

    @app.get("/queue/{qid}", response_class=HTMLResponse)
    def queue_detail(qid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        row, mended = mended_row(conn, load_queue_row(conn, qid))
        item = queue_view(conn, row)
        pace = today_view.pace_slot(conn, row) if row["status"] == "draft" else None
        return render(request, "detail.html", item=item, networks=NETWORKS, msg=msg or mended, shot_choices=SHOT_CHOICES,
                      networks_on=alerts.networks_on(),
                      origin=today_view.origin(row), can_approve=not item["blocked_networks"] and not item["ineligible"] and bool(item["targets"]),
                      pace_words=f"{today_view.day_words(pace)} {today_view.clock(pace)}" if pace else "",
                      goes_out=goes_out_words(conn, row) if row["status"] == "approved" else "")

    def approve_gates(conn, row, how: str = "pace") -> str:
        """The one Approve, wherever it is pressed (Today, the draft page, Save and approve, the ping's buttons): the
        suite's rewrite first, then the rules, the photos and the targets. The message word. `how` is his choice
        (Chris, 2026-10-15: "an option to post immediately or to follow the pace"): "now" goes out as soon as Buffer
        takes it (`rule_report.asap`, as a photo from the phone), "pace" at the next open slot, one post a slot."""
        row, mended = mended_row(conn, row)
        item = queue_view(conn, row)
        if item["blocked_networks"]:
            return "mend_failed" if mended == "mend_failed" else "blocked"
        if item["ineligible"]:
            return "ineligible"
        if not item["targets"]:
            return "notargets"
        try:
            meta = json.loads(row["rule_report"] or "{}")
        except ValueError:
            meta = {}
        meta = meta if isinstance(meta, dict) else {}
        meta.update(asap=how == "now", approved_how="now" if how == "now" else "pace")
        now = db.utcnow()
        conn.execute("UPDATE content_queue SET status='approved', approved_at=?, last_error=NULL, rule_report=?, "
                     "scheduled_for=CASE WHEN ? THEN NULL ELSE scheduled_for END, updated_at=? WHERE id=?",
                     (now, json.dumps(meta), how == "now", now, row["id"]))
        if how == "now":
            start_agent("publisher")         # "post immediately": not at the publisher's next ten-minute run
        return "approved"

    def skip_post(conn, row) -> str:
        """Skip (Chris, 2026-10-15): the draft is set aside and its photos go back into the rotation, never Don't use
        (agents/content.recent_use leaves a skipped post out; its use stays on the rotation's record, so the photos
        come round again after the others). A skipped daily post is drafted again at once. What happened, in words."""
        from ..agents import content
        set_aside(conn, row, by=content.SKIPPED, why="Skipped by you. Its photos go back into the rotation.")
        said = f"Skipped post {row['id']}. Its photos go back into the rotation."
        if today_view.meta_of(row).get("source") is None:
            start_agent("content")
            said += " A new daily post is being made in its place; your phone gets a ping."
        return said

    def back_to(conn, back: str, qid: int, word: str) -> RedirectResponse:
        """Where a choice returns: Today (with the message) when it was made there, else the draft's own page."""
        if back == "/":
            text = (f"Approved post {qid}. {goes_out_words(conn, load_queue_row(conn, qid))}" if word == "approved"
                    else APPROVED_WORDS.get(word, word))
            return RedirectResponse(f"/?msg={quote_plus(text)}#needs", status_code=303)
        return RedirectResponse(f"/queue/{qid}?msg={word}", status_code=303)

    @app.post("/queue/{qid}/save")
    async def queue_save(qid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Save, or save and choose (2026-10-13: one form; an edit without Save used to be lost; 2026-10-15: Post now
        and Follow the pace are this form's buttons, so an edit is never lost on either)."""
        load_queue_row(conn, qid)
        form = await request.form()
        captions = {n: (form.get(f"caption_{n}") or "").strip() for n in NETWORKS}
        targets = [n for n in NETWORKS if form.get(f"target_{n}")]
        scheduled = (form.get("scheduled_for") or "").strip() or None
        conn.execute("UPDATE content_queue SET caption=?, targets=?, scheduled_for=?, updated_at=? WHERE id=?",
                     (json.dumps(captions), json.dumps(targets), scheduled, db.utcnow(), qid))
        do = form.get("do") or "save"
        if do in ("approve", "now", "pace"):
            row = load_queue_row(conn, qid)
            if row["status"] == "draft":
                return RedirectResponse(f"/queue/{qid}?msg={approve_gates(conn, row, 'now' if do == 'now' else 'pace')}", status_code=303)
        return RedirectResponse(f"/queue/{qid}?msg=saved", status_code=303)

    @app.post("/queue/{qid}/approve")
    def queue_approve(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep), how: str = Form("pace"),
                      back: str = Form("")):
        """Post now or Follow the pace, from Today or the draft page."""
        row = load_queue_row(conn, qid)
        if row["status"] != "draft":
            return RedirectResponse("/" if back == "/" else f"/queue/{qid}", status_code=303)
        return back_to(conn, back, qid, approve_gates(conn, row, "now" if how == "now" else "pace"))

    @app.post("/queue/{qid}/retry")
    def queue_retry(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep), back: str = Form("")):
        """A post that did not go out, approved again (2026-10-15: a fix on its alert): the same gates, the publisher
        tries again on its next run, and the alerts about it are dismissed (said again if it fails again)."""
        row = load_queue_row(conn, qid)
        if row["status"] != "failed":
            return RedirectResponse("/" if back == "/" else f"/queue/{qid}", status_code=303)
        word = approve_gates(conn, row, "now" if today_view.meta_of(row).get("asap") else "pace")
        if word == "approved":
            dismiss_post_alerts(conn, qid)
        return back_to(conn, back, qid, word)

    def dismiss_post_alerts(conn, qid: int) -> None:
        for e in db.rows(conn, "SELECT id, message FROM errors WHERE alerted=0"):
            if alerts.post_of(e["message"]) == qid:
                conn.execute("UPDATE errors SET alerted=1 WHERE id=?", (e["id"],))

    APPROVED_WORDS = {"blocked": "Not approved: a caption still breaks a rule after the suite rewrote it. It tries again on its next run.",
                      "mend_failed": "Not approved: a caption breaks a rule and the suite could not rewrite it just now. Its next run tries again.",
                      "ineligible": "Not approved: a photo in it can no longer be used. Open the draft.",
                      "notargets": "Not approved: no network is picked for it. Open the draft."}
    TOKEN_REFUSALS = {"blocked": "A caption still breaks a rule after the suite rewrote it; it tries again on its next run. Open the draft to see it.",
                      "mend_failed": "A caption breaks a rule and the suite could not rewrite it just now. Open the draft to see it.",
                      "ineligible": "A photo in it can no longer be used. Open the draft.",
                      "notargets": "No network is picked for it. Open the draft."}

    def goes_out_words(conn, row) -> str:
        from ..agents import publisher
        dry = settings.dry_run(conn, "publisher")
        later = " Posting is off (practice run), so it waits as a practice run until the publisher is switched on." if dry else ""
        if today_view.meta_of(row).get("approved_how") == "now" and not row["scheduled_for"]:
            return f"It goes out now.{later}"
        if today_view.meta_of(row).get("asap") and not row["scheduled_for"]:
            return f"It goes out as soon as Buffer takes it.{later}"
        when = today_view.goes_out_at(conn, row, publisher_dry=dry)
        if when is not None:
            return f"It goes out {when:%A} {when:%H:%M}, the next open slot.{later}"
        return f"It goes out at its time.{later}"

    CHOICE_WORDS = {"now": "Post now", "pace": "Follow the pace", "skip": "Skip"}

    @app.get("/queue/{qid}/approve-by-token", response_class=HTMLResponse)
    @app.get("/queue/{qid}/choose-by-token/{how}", response_class=HTMLResponse)
    def queue_choose_by_token_page(qid: int, request: Request, conn=Depends(conn_dep), token: str = "", how: str = ""):
        """A GET never decides anything (a link preview, a browser prefetch): a page with the buttons, and nothing more."""
        row = load_queue_row(conn, qid)
        return render(request, "approve_token.html", qid=qid, token=token, status=row["status"], choices=CHOICE_WORDS,
                      how=how if how in CHOICE_WORDS else "")

    async def token_of(request: Request) -> str:
        from urllib.parse import parse_qs
        raw = (await request.body()).decode("utf-8", "replace")
        return (parse_qs(raw).get("token") or [raw.strip()])[0]

    def choose_by_token(conn, qid: int, token: str, how: str) -> PlainTextResponse:
        """Chris, 2026-10-15: Post now, Follow the pace or Skip from the ping. The body carries the signed, single-use
        token (core/approve_token); the gates are the page's own; the answer is a sentence for the phone."""
        row = load_queue_row(conn, qid)
        ok, why = approve_token.check(conn, row, token)
        if not ok:
            return PlainTextResponse(why, status_code=409)
        if row["status"] != "draft":
            return PlainTextResponse(f"Post {qid} is {today_view.STATUS_WORDS.get(row['status'], row['status']).lower()}; "
                                     "nothing to choose.", status_code=409)
        if how == "skip":
            approve_token.spend(conn, qid)
            return PlainTextResponse(skip_post(conn, row))
        word = approve_gates(conn, row, how)
        if word != "approved":
            return PlainTextResponse(TOKEN_REFUSALS.get(word, word), status_code=409)
        approve_token.spend(conn, qid)
        return PlainTextResponse(f"Approved post {qid}. {goes_out_words(conn, load_queue_row(conn, qid))}")

    @app.post("/queue/{qid}/choose-by-token/{how}")
    async def queue_choose_by_token(qid: int, how: str, request: Request, conn=Depends(conn_dep)):
        if how not in CHOICE_WORDS:
            raise HTTPException(404)
        return choose_by_token(conn, qid, await token_of(request), how)

    @app.post("/queue/{qid}/approve-by-token")
    async def queue_approve_by_token(qid: int, request: Request, conn=Depends(conn_dep)):
        """The Approve button of a ping sent before 2026-10-15: Follow the pace."""
        return choose_by_token(conn, qid, await token_of(request), "pace")

    @app.post("/queue/{qid}/requeue")
    def queue_requeue(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_queue_row(conn, qid)
        if row["status"] in ("would_publish", "failed"):
            conn.execute("UPDATE content_queue SET status='draft', last_error=NULL, payload=NULL, updated_at=? WHERE id=?", (db.utcnow(), qid))
        return RedirectResponse(f"/queue/{qid}?msg=requeued", status_code=303)

    @app.post("/queue/{qid}/photo/{pid}/shot")
    def queue_fix_shot(qid: int, pid: int, user: str = Depends(require_user), conn=Depends(conn_dep), shot_type: str = Form(...)):
        """Chris says what the photo shows. The word is corrected everywhere it is read, this draft is
        set aside, and a new one is drafted with the right words (the photo is free to be picked again)."""
        row = load_queue_row(conn, qid)
        from ..library import classify
        if pid not in (photo_ids_of_row(row) or []) or not classify.set_shot_type(conn, pid, shot_type):
            raise HTTPException(400)
        words = dict(SHOT_CHOICES).get(shot_type, shot_type)
        if row["status"] == "draft":
            conn.execute("UPDATE content_queue SET status='rejected', last_error=?, updated_at=? WHERE id=?",
                         (f"Set aside: photo {pid} shows {words}, not what the caption said. Drafted again.", db.utcnow(), qid))
            report.forget_use(conn, f"post:{qid}")      # the draft is undone: its photos are first in line again, not last
            start_agent("content")
            return RedirectResponse(f"/?msg=redraft", status_code=303)
        return RedirectResponse(f"/queue/{qid}?msg=saved", status_code=303)

    @app.post("/queue/{qid}/skip")
    @app.post("/queue/{qid}/reject")
    def queue_skip(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep), back: str = Form("")):
        """Skip (Chris, 2026-10-15; Reject before): set aside with him on the record, its photos back in the rotation, and
        a skipped daily post drafted again at once instead of the day waiting for 08:00."""
        row = load_queue_row(conn, qid)
        if row["status"] not in ("draft", "approved"):
            return RedirectResponse(f"/queue/{qid}", status_code=303)
        return RedirectResponse(f"/?msg={quote_plus(skip_post(conn, row))}#needs", status_code=303)

    @app.post("/queue/{qid}/unapprove")
    def queue_unapprove(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """An Approve taken back before the publisher picked the post up. One Buffer already holds is pulled
        back from Buffer, not from here."""
        row = load_queue_row(conn, qid)
        if row["status"] != "approved":
            return RedirectResponse(f"/queue/{qid}", status_code=303)
        conn.execute("UPDATE content_queue SET status='draft', approved_at=NULL, updated_at=? WHERE id=?", (db.utcnow(), qid))
        return RedirectResponse(f"/queue/{qid}?msg=unapproved", status_code=303)

    # ------------------------------------------------------------------ media
    @app.get("/media/render/{qid}/{aspect}/{index}")
    def media_render(qid: int, aspect: str, index: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_queue_row(conn, qid)
        paths = json.loads(row["render_paths"] or "{}").get(aspect.replace("x", ":"), [])
        if not 1 <= index <= len(paths) or not inside_data_root(Path(paths[index - 1])):
            raise HTTPException(404)
        return FileResponse(paths[index - 1], media_type=MEDIA_TYPES.get(Path(paths[index - 1]).suffix.lower(), "image/jpeg"))

    @app.get("/media/card/{qid}/{name}")
    def media_card(qid: int, name: str, conn=Depends(conn_dep)):
        """The draft's card for the ping (ntfy `Attach`): fetched by the phone with the ping's token, no login.
        The token is checked like the button's, so an old or spent one serves nothing."""
        if not name.endswith(".jpg"):
            raise HTTPException(404)
        row = db.one(conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        if row is None or not approve_token.check(conn, row, name[:-4])[0]:
            raise HTTPException(404)
        renders = json.loads(row["render_paths"] or "{}")
        # a reel's own cover first (2026-10-15: the ping showed the reel's Pinterest card), else the post's card
        for aspect in (("cover", "4:5", "2:3") if renders.get("9:16") else ("4:5", "2:3", "cover")):
            paths = renders.get(aspect) or []
            if paths and inside_data_root(Path(paths[0])):
                return FileResponse(paths[0], media_type=MEDIA_TYPES.get(Path(paths[0]).suffix.lower(), "image/jpeg"))
        raise HTTPException(404)

    @app.get("/media/thumb/{photo_id}")
    def media_thumb(photo_id: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """A cached small preview from Drive (read only). Fetched once, then served from DATA_ROOT/thumbs."""
        row = db.one(conn, "SELECT drive_id, thumbnail_link, local_path, source FROM photos WHERE id=?", (photo_id,))
        if not row:
            raise HTTPException(404)

        def fetch(drive_id: str) -> bytes:
            from ..drive import oauth
            from ..drive.api import DriveReader
            return DriveReader(oauth.access_token(conn), conn=conn, agent="dashboard").thumbnail_for(drive_id, 400)
        path = cached_thumb(row["drive_id"], fetch if row["thumbnail_link"] else None)
        if path is None and row["source"] == "phone":
            from ..agents import phone
            path = phone.ensure_thumb(row)              # from its own file, after the nightly sweep took the preview
        if path is None:
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    # ------------------------------------------------------------------ library
    @app.get("/library", response_class=HTMLResponse)
    def library(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), view: str = "review",
                show: str = "events", page: int = 1, subject: str = "event"):
        """Photos. Chris, 2026-10-11: "I only want to choose what I approve and if it's not approved then
        don't use it yet or at all". To review: the sorted photos he has not decided on, best first,
        each with Use and Don't use. Approved: everything cleared, by the photo or its folder.
        Folders: clear a whole shoot at once. Design and music: samples on approved photos only."""
        msg = request.query_params.get("msg", "")
        if view == "design":
            return RedirectResponse("/", status_code=303)       # 2026-10-15: the samples became designed drafts on Today
        prepare_photo_views(conn, eligibility.folder_decisions(conn))
        common = dict(view=view, msg=msg, drive_state=settings.get(conn, "drive.auth_state") or "missing")
        if view == "folders":
            where = "conv > 0" if show == "events" else ("f.clearance='cleared'" if show == "cleared" else "1=1")
            rows = db.rows(conn, f"""
                SELECT * FROM (
                  SELECT f.drive_id, f.name, f.path, f.clearance, f.image_count, f.shared_by,
                         SUM(CASE WHEN c.is_convention=1 THEN 1 ELSE 0 END) AS conv
                  FROM drive_folders f LEFT JOIN photos p ON p.folder_id=f.drive_id AND p.trashed=0
                  LEFT JOIN classifications c ON c.photo_id=p.id
                  GROUP BY f.drive_id) f
                WHERE image_count > 0 AND {where} ORDER BY conv DESC, image_count DESC LIMIT 400""")
            note = ""
            if show == "events" and not rows:
                rows = db.rows(conn, """SELECT f.drive_id, f.name, f.path, f.clearance, f.image_count, f.shared_by, 0 AS conv
                                        FROM drive_folders f WHERE f.image_count > 0 ORDER BY f.image_count DESC LIMIT 400""")
                if rows:
                    note = "No folder has been recognised as event work yet, so every folder with photos is shown."
            return render(request, "library.html", folders=rows, show=show, note=note, **common)
        view = view if view in ("approved", "blocked") else "review"
        subject = subject if subject in SUBJECTS else "event"
        subject_counts = {s: count_photos(conn, view, s) for s, _ in SUBJECT_WORDS}
        total = subject_counts[subject]
        pages = max(1, (total + PAGE - 1) // PAGE)
        page = max(1, min(page, pages))
        shown = photo_page(conn, view, page, subject=subject)
        uses = report.use_of(conn, [p["id"] for p in shown]) if view == "approved" else {}
        for i, p in enumerate(shown):
            # after a tap the page comes back to the next photo, since the one tapped may leave this list
            nxt = shown[i + 1]["id"] if i + 1 < len(shown) else p["id"]
            p["back"] = f"/library?view={view}&subject={subject}&page={page}#p{nxt}"
            p["why"] = eligibility.is_candidate(conn, p["id"]) if view == "approved" else None
            p["use_line"] = report.use_line(uses.get(p["id"])) if view == "approved" else ""   # the spread, photo by photo
        common["view"] = view
        hero = settings.get(conn, "site.hero_photo_id")
        from ..site import deploy
        from ..site import hero as hero_upload
        from ..seo import indexnow
        from ..site import build as site_build
        site = {"status": deploy.read_status(), "ready": deploy.ready(), "deployed": (settings.get(conn, deploy.DEPLOYED_KEY) or "")[:7],
                "google": bool(site_build.verification_value()), "google_file": site_build.verification_file(),
                "google_problem": site_build.verification_problem(), "indexnow": bool(indexnow.key()),
                "photos_pending": deploy.photos_pending(conn)}
        return render(request, "library.html", items=shown, page=page, pages=pages, total=total, subject=subject,
                      subject_counts=subject_counts, subject_words=SUBJECT_WORDS, site=site,
                      hero_id=int(hero) if hero and hero.isdigit() else None, hero_upload=hero_upload.status(conn), **common)

    @app.get("/more")
    def more():
        return RedirectResponse("/settings", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """More became Settings (2026-10-15): the system pages first, then the pages that find work."""
        return render(request, "settings.html", groups=SETTINGS_GROUPS, open_n=len(alerts.open_alerts(conn)))

    @app.get("/music", response_class=HTMLResponse)
    def music_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        """Music for reels, and the library report the scanner makes (both lived on the Design card until 2026-10-15)."""
        return render(request, "music.html", tracks=music.tracks(conn), renders=latest_renders(), msg=msg)

    @app.get("/library/report")
    def library_report(user: str = Depends(require_user)):
        latest = latest_renders().get("report")
        if not latest:
            return RedirectResponse("/library?msg=No+report+yet:+the+scanner+makes+one+after+its+next+pass", status_code=303)
        return RedirectResponse(f"/library/renders/{latest}", status_code=303)

    @app.post("/library/music")
    async def library_music_add(file: UploadFile = File(...), title: str = Form(""), artist: str = Form(""),
                                source: str = Form(""), terms: str = Form(""), rights: str = Form(""),
                                user: str = Depends(require_user), conn=Depends(conn_dep)):
        """A track for the reels, kept only with its record: where it came from and what that allows."""
        if rights != "yes":
            return RedirectResponse("/music?msg=Tick+that+you+have+the+right+to+use+the+track+in+posts", status_code=303)
        data = await file.read(music.MAX_BYTES + 1)
        try:
            music.add(conn, file.filename or "", data, title=title, artist=artist, source=source, terms=terms)
        except music.Refused as e:
            return RedirectResponse(f"/music?msg=Track+not+added:+{str(e).replace(' ', '+')}", status_code=303)
        return RedirectResponse("/music?msg=Track+added.+New+reels+use+the+newest+track.", status_code=303)

    @app.post("/library/music/{tid}/active")
    def library_music_active(tid: int, state: str = Form(...), user: str = Depends(require_user), conn=Depends(conn_dep)):
        music.set_active(conn, tid, state == "on")
        return RedirectResponse("/music", status_code=303)

    @app.get("/library/design")
    def library_design(user: str = Depends(require_user)):
        return RedirectResponse("/", status_code=303)       # 2026-10-15: the samples became designed drafts on Today

    @app.get("/library/design/{folder}/{name}")
    def library_design_file(folder: str, name: str, user: str = Depends(require_user)):
        # only a design folder and only the files the designer writes, by exact name
        if not DESIGN_DIR.fullmatch(folder) or not DESIGN_FILE.fullmatch(name):
            raise HTTPException(404)
        if name == "index.html":
            return RedirectResponse("/", status_code=303)   # 2026-10-15: no samples page; the designed drafts are on Today
        path = config.get_config().data_root / "renders" / folder / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type=DESIGN_TYPES[Path(name).suffix])

    @app.post("/library/design/{folder}/post")
    def library_design_post(folder: str, user: str = Depends(require_user), conn=Depends(conn_dep), design: str = Form(...),
                            photos: str = Form("")):
        """Chris, 2026-10-15: "Put a Post this on every design sample so I can turn a sample I like into a real draft
        post." The press is recorded and the sample agent drafts it on the daily post's road (agents/sample.py); a
        sample made again since, or with a photo no longer approved, or a lane in dry run, says so and drafts nothing."""
        from ..agents import sample
        from ..render import design_samples
        if not DESIGN_DIR.fullmatch(folder) or design not in sample.DESIGNS:
            raise HTTPException(404)
        back = "/?msg="
        rec = design_samples.sample_of(folder, design)
        why = design_samples.stale(conn, folder, rec)
        if why:
            return RedirectResponse(back + quote_plus(f"Not drafted: {why}."), status_code=303)
        try:
            ids = [int(x) for x in photos.split(",") if x.strip()]
        except ValueError:
            ids = []
        if ids != [int(p) for p in rec["photos"]]:
            return RedirectResponse(back + quote_plus("Not drafted: the photos asked for are not the photos this sample was made from."),
                                    status_code=303)
        again = sample.used_lately(conn, ids)
        if again:
            return RedirectResponse(back + quote_plus(f"Not drafted: {again}."), status_code=303)
        if settings.dry_run(conn, "content"):
            return RedirectResponse(back + quote_plus(f"Not drafted: {sample.DRY_RUN}."), status_code=303)
        sample.ask(conn, folder, design, ids)
        start_agent("sample", wait=True)
        return RedirectResponse(back + quote_plus(f"The {design} idea is being checked and drafted now, on the same road as the daily "
                                                  "post. Your phone gets a ping in a few minutes."), status_code=303)

    @app.get("/library/renders/{name}")
    def library_render(name: str, user: str = Depends(require_user)):
        # only the report and the two sheets, by exact name: nothing else under DATA_ROOT is reachable
        if not RENDER_NAME.fullmatch(name):
            raise HTTPException(404)
        path = config.get_config().data_root / "renders" / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="text/html" if name.endswith(".html") else "image/jpeg")

    @app.post("/library/folder/{fid}/clearance")
    def folder_clearance(fid: str, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...),
                         back: str = Form(default="/library")):
        if state not in ("cleared", "excluded", "not_cleared"):
            raise HTTPException(400)
        conn.execute("UPDATE drive_folders SET clearance=?, clearance_at=? WHERE drive_id=?", (state, db.utcnow(), fid))
        photos_changed(conn)
        return RedirectResponse(safe_back(back), status_code=303)

    @app.get("/library/folder/{fid}", response_class=HTMLResponse)
    def folder(fid: str, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        f = db.one(conn, "SELECT * FROM drive_folders WHERE drive_id=?", (fid,))
        if f is None:
            raise HTTPException(404)
        photos = db.rows(conn, "SELECT p.*, c.shot_type, c.quality, c.possible_minor, c.summary, c.method FROM photos p "
                               "LEFT JOIN classifications c ON c.photo_id=p.id WHERE p.folder_id=? AND p.trashed=0 "
                               "ORDER BY COALESCE(c.quality,0) DESC, p.taken_at LIMIT 300", (fid,))
        items = [{**dict(p), "eligible": eligibility.is_candidate(conn, p["id"])} for p in photos]
        picked = sum(1 for p in photos if p["clearance"] == "cleared")
        return render(request, "folder.html", folder=f, items=items, picked=picked)

    TAP_WORDS = {"cleared": "Approved.", "blocked": "Kept out.", "inherit": "Back where it was."}

    def photos_changed(conn) -> None:
        """Chris, 2026-10-13: the site follows the photos by itself (site/deploy.photos_pending reads this)."""
        from ..site import deploy
        settings.set(conn, deploy.PHOTOS_CHANGED_KEY, db.utcnow())

    def safe_back(back: str, default: str = "/library") -> str:
        return back if back.startswith("/") and not back.startswith("//") else default

    @app.post("/library/photo/{pid}/clearance")
    def photo_clearance(pid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...),
                        back: str = Form(default="/library")):
        """One tap. The page's own script asks for JSON and swaps the badge in place (2026-10-13: a tap was a
        whole page); the plain form, with no script, still gets the redirect."""
        if state not in TAP_WORDS:
            raise HTTPException(400)
        conn.execute("UPDATE photos SET clearance=?, clearance_at=? WHERE id=?", (state, db.utcnow(), pid))
        photos_changed(conn)
        if "application/json" in request.headers.get("accept", ""):
            return {"id": pid, "state": state, "words": TAP_WORDS[state]}
        return RedirectResponse(safe_back(back), status_code=303)

    @app.post("/library/photos/clearance")
    async def photos_clearance(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Use selected / Don't use selected: the ticked photos, one tap (2026-10-13)."""
        form = await request.form()
        state = form.get("state") or ""
        if state not in ("cleared", "blocked"):
            raise HTTPException(400)
        ids = [int(x) for x in form.getlist("ids") if str(x).isdigit()]
        now = db.utcnow()
        for pid in ids:
            conn.execute("UPDATE photos SET clearance=?, clearance_at=? WHERE id=?", (state, now, pid))
        if ids:
            photos_changed(conn)
        return RedirectResponse(safe_back(form.get("back") or "/library"), status_code=303)

    def publish_now() -> str:
        """Chris, 2026-10-12: a hero he sends, removes or picks reaches the site by itself, with nobody at a
        terminal and no second button. What happened, for the message: publishing, or why not."""
        from ..site import deploy
        ready, why = deploy.ready()
        if not ready:
            return f"The site is not published from here ({why})."
        if deploy.read_status().get("state") == "running":
            return "A publish is already running; it takes this with it on the next one. Press Publish the site after it ends."
        deploy.write_status("running", "starting")
        deploy.start_in_background()
        return "Publishing the site with it now. The Website card says when it is live."

    @app.post("/library/hero/upload")
    async def hero_upload_add(file: UploadFile = File(...), user: str = Depends(require_user), conn=Depends(conn_dep)):
        """The website's main photo straight from Chris's phone (2026-10-12). It IS the hero; Claude looks at
        it during the publish for the alt text and a note, never to hold it back. The publish starts now."""
        from ..site import hero as hero_upload
        data = await file.read(hero_upload.MAX_BYTES + 1)
        try:
            hero_upload.save(data)
            settings.set(conn, hero_upload.CHECK_KEY, "")
        except hero_upload.Refused as e:
            return RedirectResponse(f"/library?view=approved&msg=Not+kept:+{str(e).replace(' ', '+')}", status_code=303)
        return RedirectResponse("/library?view=approved&msg=" + quote_plus(f"Kept. It is the site's hero. {publish_now()}"), status_code=303)

    @app.post("/library/hero/remove")
    def hero_upload_remove(user: str = Depends(require_user), conn=Depends(conn_dep)):
        from ..site import hero as hero_upload
        hero_upload.remove(conn)
        msg = ("Removed. The photo that came with the code is the hero again." if hero_upload.present()
               else "Removed. The build chooses the hero again.")
        return RedirectResponse("/library?view=approved&msg=" + quote_plus(f"{msg} {publish_now()}"), status_code=303)

    @app.post("/site/publish")
    def site_publish(user: str = Depends(require_user)):
        """Chris, 2026-10-12: the site goes live from a phone, with nobody at a terminal. `ccs site deploy`
        runs on its own (one at a time); the Website card on the Approved page says what happened."""
        from ..site import deploy
        ready, why = deploy.ready()
        if not ready:
            return RedirectResponse("/library?view=approved&msg=" + quote_plus(f"Not published: {why}"), status_code=303)
        if deploy.read_status().get("state") == "running":
            return RedirectResponse("/library?view=approved&msg=A+publish+is+already+running.", status_code=303)
        deploy.write_status("running", "starting")
        deploy.start_in_background()
        return RedirectResponse("/library?view=approved&msg=Publishing+the+site.+The+Website+card+says+when+it+is+live.",
                                status_code=303)

    @app.post("/library/photo/{pid}/hero")
    def photo_hero(pid: int, user: str = Depends(require_user), conn=Depends(conn_dep), back: str = Form(default="/library")):
        """Chris's own pick for the website's main photo (2026-10-11: "the most colorful and dynamic photo, a
        wide stage panorama shot or a very powerful [keynote] shot"). Tapping the chosen one again lets the
        build choose. It takes effect on the next go-live, and only while the photo is usable."""
        from ..site.build import HERO_KEY
        if settings.get(conn, HERO_KEY) == str(pid):
            settings.set(conn, HERO_KEY, "")
            msg = "Site hero: the build chooses again."
        else:
            settings.set(conn, HERO_KEY, str(pid))
            msg = "Site hero: this photo."
        photos_changed(conn)
        msg = f"{msg} {publish_now()}"
        back = back if back.startswith("/") and not back.startswith("//") else "/library"
        path, _, anchor = back.partition("#")
        return RedirectResponse(f"{path}{'&' if '?' in path else '?'}msg={quote_plus(msg)}" + (f"#{anchor}" if anchor else ""),
                                status_code=303)

    # ------------------------------------------------------------------ do not use
    @app.get("/donotuse", response_class=HTMLResponse)
    def donotuse(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        return render(request, "donotuse.html", rows=db.rows(conn, "SELECT * FROM do_not_use ORDER BY id DESC"))

    @app.post("/donotuse/add")
    def donotuse_add(user: str = Depends(require_user), conn=Depends(conn_dep), kind: str = Form(...), value: str = Form(...),
                     reason: str = Form(default=""), back: str = Form(default="")):
        if kind not in ("photo", "folder", "person", "handle"):
            raise HTTPException(400)
        value = drive_id_from(value) if kind in ("photo", "folder") else value.strip().lower()
        if value:
            conn.execute("INSERT OR IGNORE INTO do_not_use (kind, value, reason, added_at) VALUES (?,?,?,?)",
                         (kind, value, reason.strip() or None, db.utcnow()))
            # anything waiting that this now covers is set aside with the reason, and the day is drafted again
            hit = False
            for q in db.rows(conn, "SELECT * FROM content_queue WHERE status IN ('draft','approved')"):
                bad = [p for p in json.loads(q["photo_ids"] or "[]") if not eligibility.is_eligible(conn, int(p))[0]]
                if bad:
                    set_aside(conn, q, by="donotuse", why="A photo in this post is now on the do-not-use list. Set aside; a new one is being drafted.")
                    hit = True
            if hit:
                start_agent("content")
            photos_changed(conn)
        return RedirectResponse(safe_back(back, "/donotuse") if back else "/donotuse", status_code=303)

    @app.post("/donotuse/{rid}/remove")
    def donotuse_remove(rid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        conn.execute("DELETE FROM do_not_use WHERE id=?", (rid,))
        return RedirectResponse("/donotuse", status_code=303)

    # ------------------------------------------------------------------ calendar
    @app.get("/calendar", response_class=HTMLResponse)
    def calendar(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), edit: int = 0):
        rows = db.rows(conn, "SELECT * FROM conventions ORDER BY COALESCE(start_date,'9999') ASC")
        current = db.one(conn, "SELECT * FROM conventions WHERE id=?", (edit,)) if edit else None
        return render(request, "calendar.html", rows=rows, current=current)

    @app.post("/calendar/save")
    async def calendar_save(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        form = await request.form()
        name = (form.get("name") or "").strip()
        if not name:
            return RedirectResponse("/calendar", status_code=303)
        kind = form.get("kind") if form.get("kind") in ("fan", "business", "unknown") else "unknown"
        vals = dict(name=name, kind=kind, start_date=(form.get("start_date") or None), end_date=(form.get("end_date") or None),
                    city=(form.get("city") or "").strip() or None, venue=(form.get("venue") or "").strip() or None,
                    attending=1 if form.get("attending") else 0, official=1 if form.get("official") else 0,
                    url=(form.get("url") or "").strip() or None, notes=(form.get("notes") or "").strip() or None)
        now = db.utcnow()
        cid = int(form.get("id") or 0)
        if cid:
            sets = ", ".join(f"{k}=?" for k in vals)
            conn.execute(f"UPDATE conventions SET {sets}, updated_at=? WHERE id=?", (*vals.values(), now, cid))
        else:
            db.insert(conn, "conventions", **vals, created_at=now, updated_at=now)
        return RedirectResponse("/calendar", status_code=303)

    @app.post("/calendar/{cid}/delete")
    def calendar_delete(cid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        conn.execute("DELETE FROM conventions WHERE id=?", (cid,))
        return RedirectResponse("/calendar", status_code=303)

    # ------------------------------------------------------------------ booking
    @app.get("/inquiries", response_class=HTMLResponse)
    def inquiries(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), show: str = "open"):
        where = "status NOT IN ('declined','spam','booked')" if show == "open" else "1=1"
        rows = db.rows(conn, f"SELECT * FROM inquiries WHERE {where} ORDER BY id DESC LIMIT 200")
        return render(request, "inquiries.html", rows=rows, show=show)

    @app.get("/inquiries/{iid}", response_class=HTMLResponse)
    def inquiry(iid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        from .. import offer
        from ..ai import reply as reply_mod
        row = db.one(conn, "SELECT * FROM inquiries WHERE id=?", (iid,))
        if row is None:
            raise HTTPException(404)
        asked = offer.coverage_labels(json.loads(row["coverage"] or "[]"))
        bookings = db.rows(conn, "SELECT * FROM bookings WHERE inquiry_id=? ORDER BY start_date", (iid,))
        why = reply_mod.ready_to_send(row["reply_subject"] or "", row["reply_body"] or "") if row["reply_body"] else None
        return render(request, "inquiry.html", row=row, asked=asked, bookings=bookings, msg=msg, why=why,
                      footer=reply_mod.footer(), deposits=bool(config.getenv("PAYMENT_PROVIDER")))

    @app.post("/inquiries/{iid}/reply")
    def inquiry_reply(iid: int, user: str = Depends(require_user), conn=Depends(conn_dep), subject: str = Form(""),
                      body: str = Form(""), deposit_link: str = Form(""), do: str = Form("save")):
        """Save, or Save and approve (2026-10-13): the price he typed is kept either way."""
        row = db.one(conn, "SELECT reply_status FROM inquiries WHERE id=?", (iid,))
        if row is None:
            raise HTTPException(404)
        if row["reply_status"] in ("sent",):
            return RedirectResponse(f"/inquiries/{iid}?msg=already_sent", status_code=303)
        subject, body = subject.strip(), body.replace("\r\n", "\n").strip()
        conn.execute("UPDATE inquiries SET reply_subject=?, reply_body=?, reply_status='draft', deposit_link=?, updated_at=? WHERE id=?",
                     (subject, body, deposit_link.strip() or None, db.utcnow(), iid))
        if do == "approve":
            from ..ai import reply as reply_mod
            if reply_mod.ready_to_send(subject, body):
                return RedirectResponse(f"/inquiries/{iid}?msg=not_ready", status_code=303)
            conn.execute("UPDATE inquiries SET reply_status='approved', updated_at=? WHERE id=?", (db.utcnow(), iid))
            return RedirectResponse(f"/inquiries/{iid}?msg=approved", status_code=303)
        return RedirectResponse(f"/inquiries/{iid}?msg=saved", status_code=303)

    @app.post("/inquiries/{iid}/approve")
    def inquiry_approve(iid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        from ..ai import reply as reply_mod
        row = db.one(conn, "SELECT * FROM inquiries WHERE id=?", (iid,))
        if row is None:
            raise HTTPException(404)
        if row["reply_status"] != "draft":
            return RedirectResponse(f"/inquiries/{iid}", status_code=303)
        if reply_mod.ready_to_send(row["reply_subject"] or "", row["reply_body"] or ""):
            return RedirectResponse(f"/inquiries/{iid}?msg=not_ready", status_code=303)
        conn.execute("UPDATE inquiries SET reply_status='approved', updated_at=? WHERE id=?", (db.utcnow(), iid))
        return RedirectResponse(f"/inquiries/{iid}?msg=approved", status_code=303)

    @app.post("/inquiries/{iid}/status")
    def inquiry_status(iid: int, user: str = Depends(require_user), conn=Depends(conn_dep), status_: str = Form(..., alias="status")):
        if status_ not in ("drafted", "replied", "quoted", "booked", "declined", "spam"):
            raise HTTPException(400)
        conn.execute("UPDATE inquiries SET status=?, updated_at=? WHERE id=?", (status_, db.utcnow(), iid))
        return RedirectResponse(f"/inquiries/{iid}", status_code=303)

    @app.get("/bookings", response_class=HTMLResponse)
    def bookings(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        rows = db.rows(conn, "SELECT b.*, i.name AS who FROM bookings b LEFT JOIN inquiries i ON i.id=b.inquiry_id "
                             "ORDER BY b.start_date")
        return render(request, "bookings.html", rows=rows)

    @app.post("/bookings/add")
    def booking_add(user: str = Depends(require_user), conn=Depends(conn_dep), title: str = Form(...), start_date: str = Form(...),
                    end_date: str = Form(""), status_: str = Form("booked", alias="status"), inquiry_id: str = Form("")):
        from datetime import date as _date
        try:
            start = _date.fromisoformat(start_date)
            end = _date.fromisoformat(end_date) if end_date else start
        except ValueError:
            raise HTTPException(400, "dates must be YYYY-MM-DD")
        if end < start or status_ not in ("hold", "booked"):
            raise HTTPException(400)
        now = db.utcnow()
        iid = int(inquiry_id) if inquiry_id.strip().isdigit() else None
        db.insert(conn, "bookings", inquiry_id=iid, title=title.strip() or "Booking", start_date=start.isoformat(),
                  end_date=end.isoformat(), status=status_, created_at=now, updated_at=now)
        if iid and status_ == "booked":
            conn.execute("UPDATE inquiries SET status='booked', updated_at=? WHERE id=?", (now, iid))
        return RedirectResponse(f"/inquiries/{iid}" if iid else "/bookings", status_code=303)

    @app.post("/bookings/{bid}/status")
    def booking_status(bid: int, user: str = Depends(require_user), conn=Depends(conn_dep), status_: str = Form(..., alias="status")):
        if status_ not in ("hold", "booked", "cancelled"):
            raise HTTPException(400)
        conn.execute("UPDATE bookings SET status=?, updated_at=? WHERE id=?", (status_, db.utcnow(), bid))
        return RedirectResponse("/bookings", status_code=303)

    # ------------------------------------------------------------------ drive
    @app.get("/drive", response_class=HTMLResponse)
    def drive(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        from ..drive import oauth
        from ..library import report
        renders = sorted((config.get_config().data_root / "renders").glob("library-report-*.html"))
        # 2026-10-14: the galleries shared with this account, by whom (a name only)
        shared = [dict(r) for r in db.rows(conn, "SELECT name, shared_by FROM drive_folders "
                                                 "WHERE shared_by IS NOT NULL AND parent_id IS NULL ORDER BY name")]
        return render(request, "drive.html", state=settings.get(conn, "drive.auth_state") or "missing",
                      detail=settings.get(conn, "drive.auth_detail") or "", summary=report.summary(conn), shared=shared,
                      sharers=sorted({r["shared_by"] for r in shared}),
                      report_name=renders[-1].name if renders else "", msg=msg,
                      pending=oauth.pending_login(conn) is not None, client_set=oauth.client_config() is not None,
                      unmatched=settings.get(conn, "credits.unmatched") or "")

    @app.get("/drive/login")
    def drive_login(user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Chris, 2026-10-13: the Drive sign-in from the phone, no terminal and no Google console change. Google
        sends the browser to the loopback return page, which does not load on the phone; he pastes its address
        below (drive/oauth.start_login, finish_login). Scope: drive.readonly, as ever."""
        from ..drive import oauth
        try:
            url, _pending = oauth.start_login(conn)
        except oauth.DriveAuthError as e:
            return RedirectResponse("/drive?msg=" + quote_plus(str(e)), status_code=303)
        return RedirectResponse(url, status_code=303)

    @app.post("/drive/login/finish")
    def drive_login_finish(user: str = Depends(require_user), conn=Depends(conn_dep), address: str = Form("")):
        from ..drive import oauth
        try:
            oauth.finish_login(conn, address, detail="signed in from the dashboard")
        except oauth.DriveAuthError as e:
            return RedirectResponse("/drive?msg=" + quote_plus(str(e)), status_code=303)
        except Exception as e:  # noqa: BLE001  Google refused the code, the network: said on the page, nothing saved
            return RedirectResponse("/drive?msg=" + quote_plus(f"Google did not complete the sign-in ({type(e).__name__}: {str(e)[:160]}). Try again."),
                                    status_code=303)
        return RedirectResponse("/drive?msg=signed_in", status_code=303)

    @app.get("/drive/report/{name}")
    def drive_report(name: str, user: str = Depends(require_user)):
        if "/" in name or not re.fullmatch(r"(library-report|contact-sheet|building-sheet)-\d{8}\.(html|jpg)", name):
            raise HTTPException(404)
        p = config.get_config().data_root / "renders" / name
        if not inside_data_root(p):
            raise HTTPException(404)
        return FileResponse(p)

    # ------------------------------------------------------------------ agents
    @app.get("/agents", response_class=HTMLResponse)
    def agents(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        rows = []
        for name, meta in AGENTS.items():
            last = db.one(conn, "SELECT * FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT 1", (name,))
            rows.append({"name": name, "meta": meta, "built": is_built(name), "runnable": name in RUNNABLE,
                         "dry_run": settings.dry_run(conn, name) if name in settings.AGENTS_WITH_DRY_RUN else None,
                         "last": dict(last) if last else None})
        switches = [r for r in rows if r["dry_run"] is not None]
        return render(request, "agents.html", agents=rows, alerts=alerts.open_alerts(conn), back="/agents", msg=request.query_params.get("msg", ""),
                      live_n=sum(1 for r in switches if not r["dry_run"]), switch_n=len(switches),
                      ai_mtd=spend.month_to_date(conn), ai_cap=config.get_config().ai_monthly_cap_usd)

    @app.post("/agents/{name}/run")
    def run_now(name: str, user: str = Depends(require_user)):
        """One run now, exactly as its schedule would start it: its own lock, its own dry-run switch,
        its own gates. The dashboard only starts it and returns; the run shows here when it ends."""
        if name not in RUNNABLE or not is_built(name):
            raise HTTPException(404)
        start_agent(name)
        return RedirectResponse(f"/agents?msg={name}+started.+Its+result+shows+here+when+it+ends.", status_code=303)

    @app.post("/agents/all/dry-run")
    def all_dry_run(user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...)):
        """Chris, 2026-10-11: "Everything should be live now too so we can see the damn thing work!"
        Every switch at once. Approve still gates every post, email and reply; the AI cap still holds."""
        released = 0
        for name in settings.AGENTS_WITH_DRY_RUN:
            settings.set_dry_run(conn, name, state != "off")
            if state == "off":
                released += release_dry_run_approvals(conn, name)
        word = "in practice run" if state != "off" else "LIVE"
        return RedirectResponse(f"/agents?msg={quote_plus(f'Every agent is now {word}.' + released_note(released))}", status_code=303)

    @app.post("/agents/{name}/dry-run")
    def toggle_dry_run(name: str, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...)):
        if name not in settings.AGENTS_WITH_DRY_RUN:
            raise HTTPException(404)
        settings.set_dry_run(conn, name, state != "off")
        released = release_dry_run_approvals(conn, name) if state == "off" else 0
        word = "in practice run" if state != "off" else "LIVE"
        return RedirectResponse(f"/agents?msg={quote_plus(f'{name} is now {word}.' + released_note(released))}", status_code=303)

    ERROR_PAGES = ("/agents", "/errors", "/")

    def error_back(back: str, msg: str) -> RedirectResponse:
        page = back if back in ERROR_PAGES else "/errors"
        return RedirectResponse(f"{page}?msg={quote_plus(msg)}" + ("#needs" if page == "/" else ""), status_code=303)

    @app.get("/errors", response_class=HTMLResponse)
    def errors_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Every open alert, one card per kind, each with its fix where there is one (2026-10-15)."""
        return render(request, "errors.html", alerts=alerts.open_alerts(conn), back="/errors", msg=request.query_params.get("msg", ""))

    @app.post("/errors/fix")
    def fix_alert(kind: str = Form(...), back: str = Form(default="/errors"), user: str = Depends(require_user), conn=Depends(conn_dep)):
        """The fix on an alert the suite can do itself: a failed post approved again, or an agent run again. The kind is
        dismissed with it; if it happens again it is said again."""
        group = next((g for g in alerts.open_alerts(conn) if g["kind"] == kind), None)
        fix = (group or {}).get("fix") or {}
        if fix.get("action") == "retry":
            row = load_queue_row(conn, fix["qid"])
            if row["status"] != "failed":
                return error_back(back, f"Post {fix['qid']} is not waiting on a fix any more.")
            word = approve_gates(conn, row, "now" if today_view.meta_of(row).get("asap") else "pace")
            if word != "approved":
                return error_back(back, APPROVED_WORDS.get(word, word))
            dismiss_post_alerts(conn, fix["qid"])
            return error_back(back, f"Approved post {fix['qid']} again. {goes_out_words(conn, load_queue_row(conn, fix['qid']))}")
        if fix.get("action") == "run" and fix["agent"] in RUNNABLE and is_built(fix["agent"]):
            start_agent(fix["agent"])
            conn.execute("UPDATE errors SET alerted=1 WHERE alerted=0 AND kind=?", (kind,))
            return error_back(back, f"Started the {fix['agent']} again. If it fails again, it is said again here.")
        return error_back(back, "That alert has no fix the suite can do itself; its page or Dismiss is the way.")

    @app.post("/errors/ack-kind")
    def ack_kind(kind: str = Form(...), back: str = Form(default="/agents"), user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Dismiss every open error of one kind (Chris, 2026-10-11: "the terminal command to dismiss
        all the drive errors"). A dismissed error stays in the table; it only leaves this list."""
        n = conn.execute("UPDATE errors SET alerted=1 WHERE alerted=0 AND kind=?", (kind,)).rowcount
        return error_back(back, f"Dismissed {n}: {alerts.TITLES.get(kind, kind.replace('_', ' '))}.")

    @app.post("/errors/{eid}/ack")
    def ack_error(eid: int, back: str = Form(default="/agents"), user: str = Depends(require_user), conn=Depends(conn_dep)):
        conn.execute("UPDATE errors SET alerted=1 WHERE id=?", (eid,))
        return RedirectResponse(back if back in ERROR_PAGES else "/agents", status_code=303)

    # ------------------------------------------------------------------ buffer
    # Chris, 2026-10-11: "A Buffer channel is not set up for this yet, but definitely get the plumbing in
    # so we can just add it quickly when I do." Key on the Keys page, then here: find the channels, tap
    # Use on this company's own, pick the Pinterest board, check the video format. Nothing is linked by
    # itself: a key that also sees another company's channels must never post to them.
    def back(msg: str) -> RedirectResponse:
        return RedirectResponse("/buffer?msg=" + quote_plus(msg.strip()[:300]), status_code=303)

    @app.get("/buffer", response_class=HTMLResponse)
    def buffer_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        return render(request, "buffer.html", b=buffer_state(conn), msg=msg.replace("+", " "))

    @app.post("/buffer/find")
    def buffer_find(user: str = Depends(require_user), conn=Depends(conn_dep)):
        client = buffer_client(conn)
        if client is None:
            return back("Paste the Buffer API key on the Keys page first.")
        try:
            orgs = client.organizations()
            settings.set(conn, "buffer.organizations", json.dumps(orgs))
            chosen = config.getenv("BUFFER_ORGANIZATION_ID", "") or ""
            if chosen and chosen not in {o["id"] for o in orgs}:
                config.write_env({"BUFFER_ORGANIZATION_ID": ""})
                conn.execute("DELETE FROM channels")
                return back("The organization chosen before is not visible to this key any more. Choose again below.")
            if not orgs:
                return back("This Buffer key sees no organization.")
            if not chosen and len(orgs) > 1:
                return back(f"This key sees {len(orgs)} Buffer organizations. Choose this company's below, then Find channels again.")
            client._org = chosen or orgs[0]["id"]
            found = client.channels(refresh=True)
        except BUFFER_ERRORS as e:
            return back(f"Buffer said: {e}")
        now = db.utcnow()
        for ch in found:
            conn.execute("UPDATE channels SET connected=?, display_name=?, last_checked_at=? WHERE buffer_channel_id=?",
                         (0 if ch.get("isDisconnected") or ch.get("isLocked") else 1, ch.get("displayName") or ch.get("name"), now, ch.get("id")))
        return back(f"Found {len(found)} channel(s) in Buffer.")

    @app.post("/buffer/org")
    def buffer_org(user: str = Depends(require_user), conn=Depends(conn_dep), org_id: str = Form(...)):
        orgs = {o["id"]: o for o in buffer_state(conn)["orgs"]}
        if org_id not in orgs:
            return back("That organization is not one this key sees. Tap Find channels.")
        if org_id != (config.getenv("BUFFER_ORGANIZATION_ID", "") or ""):
            config.write_env({"BUFFER_ORGANIZATION_ID": org_id})
            conn.execute("DELETE FROM channels")          # channels linked from another organization are unlinked
        return back(f"Using {orgs[org_id].get('name') or org_id}. Tap Find channels.")

    @app.post("/buffer/link")
    def buffer_link(user: str = Depends(require_user), conn=Depends(conn_dep), channel_id: str = Form(...)):
        ch = next((c for c in buffer_state(conn)["found"] if c.get("id") == channel_id), None)
        if ch is None or ch.get("service") not in buffer_payloads.NETWORKS:
            return back("That channel is not one Buffer listed for this suite. Tap Find channels.")
        name = ch.get("displayName") or ch.get("name") or channel_id
        conn.execute("DELETE FROM channels WHERE service=? OR buffer_channel_id=?", (ch["service"], channel_id))
        db.insert(conn, "channels", buffer_channel_id=channel_id, service=ch["service"], display_name=name,
                  connected=0 if ch.get("isDisconnected") or ch.get("isLocked") else 1, last_checked_at=db.utcnow())
        if ch["service"] == "pinterest":
            settings.set(conn, "buffer.pinterest_boards", "[]")
        return back(f"{ch['service'].capitalize()} posts go to {name}.")

    @app.post("/buffer/unlink")
    def buffer_unlink(user: str = Depends(require_user), conn=Depends(conn_dep), service: str = Form(...)):
        conn.execute("DELETE FROM channels WHERE service=?", (service,))
        return back(f"Nothing goes to {service} now.")

    @app.post("/buffer/boards")
    def buffer_boards(user: str = Depends(require_user), conn=Depends(conn_dep)):
        client, pin = buffer_client(conn), buffer_state(conn)["linked"].get("pinterest")
        if client is None or pin is None:
            return back("Link a Pinterest channel first.")
        try:
            boards = client.pinterest_boards(pin["buffer_channel_id"])
        except BUFFER_ERRORS as e:
            return back(f"Buffer said: {e}")
        settings.set(conn, "buffer.pinterest_boards", json.dumps(boards))
        return back(f"Found {len(boards)} board(s). Tap Use on the one pins go to.")

    @app.post("/buffer/board")
    def buffer_board(user: str = Depends(require_user), conn=Depends(conn_dep), board_id: str = Form(...)):
        board = next((b for b in buffer_state(conn)["boards"] if b.get("serviceId") == board_id), None)
        if board is None:
            return back("That board is not one Buffer listed. Tap Find boards.")
        config.write_env({"PINTEREST_BOARD_ID": board_id})
        return back(f"Pins go to the board {board.get('name') or board_id}.")

    @app.post("/buffer/video")
    def buffer_video(user: str = Depends(require_user), conn=Depends(conn_dep)):
        client = buffer_client(conn)
        if client is None:
            return back("Paste the Buffer API key on the Keys page first.")
        try:
            alt = client.image_alt_path()
            settings.set(conn, "buffer.image_alt", json.dumps({"path": alt, "checked_at": db.utcnow()}))
            fields = client.video_asset_fields()
            buffer_payloads.video_asset(fields, "https://check.invalid/v.mp4", "https://check.invalid/c.jpg")
        except buffer_payloads.PayloadError as e:
            settings.set(conn, "buffer.video_fields", json.dumps({"fields": fields, "checked_at": db.utcnow(), "problem": str(e)}))
            return back(f"Buffer's video format needs something this suite does not fill yet: {e}")
        except BUFFER_ERRORS as e:
            return back(f"Buffer said: {e}")
        settings.set(conn, "buffer.video_fields", json.dumps({"fields": fields, "checked_at": db.utcnow()}))
        return back("Buffer's post formats read. Reels can post; " + (f"alt text goes in {'.'.join(alt)}."
                     if alt else "Buffer offers no alt text field, so posts go without it."))

    # ------------------------------------------------------------------ keys
    def key_groups() -> list[dict]:
        have = secrets.present()

        def f(name, label, secret=False, choices=None):
            return {"name": name, "label": label, "secret": secret, "choices": choices,
                    "set": have.get(name, bool(config.getenv(name))), "value": "" if secret else (config.getenv(name) or "")}

        return [
            {"title": "Company", "note": "The public name can change here at any time.",
             "fields": [f("BRAND_NAME", "Company name"), f("BRAND_DOMAIN", "Website domain"),
                        f("BRAND_FROM_EMAIL", "Mail sent from"), f("BRAND_POSTAL_ADDRESS", "Postal address on emails"),
                        f("ALERT_EMAIL", "Alerts and the daily summary go to"),
                        f("SERVICE_AREA", "Where you work, for search (for example: Washington DC)")]},
            {"title": "Website contact", "note": "Shown on eventcaliber.com (2026-10-14): the phone number at the top on phones, on the "
                                                 "Contact page, in the footer and in the business details search engines read; the social "
                                                 "addresses in the footer. Blank hides each one. A change republishes the site within minutes.",
             "fields": [f("BRAND_PHONE", "Phone number on the website"), f("SOCIAL_INSTAGRAM", "Instagram address"),
                        f("SOCIAL_FACEBOOK", "Facebook address"), f("SOCIAL_PINTEREST", "Pinterest address")]},
            {"title": "Google Drive", "note": "From this company's own Google Cloud project. Read only.",
             "fields": [f("GOOGLE_OAUTH_CLIENT_ID", "OAuth client id"), f("GOOGLE_OAUTH_CLIENT_SECRET", "OAuth client secret", secret=True),
                        f("CREDITS_SHEET_ID", "Credits sheet (link or id)")]},
            {"title": "Mail", "note": "The company mailbox on Google Workspace (Chris, 2026-10-13): server smtp.gmail.com, login the "
                                      "address itself, and a Google app password (2-Step Verification on), never the account password. "
                                      "Mail sent from (Company) is that address, or a Send mail as alias Google has verified.",
             "fields": [f("SMTP_HOST", "Mail server"), f("SMTP_USER", "Mailbox login"), f("SMTP_PASSWORD", "App password", secret=True)]},
            {"title": "AI", "note": "Chris's Anthropic key, the one his other suite uses (his choice, 2026-10-11): "
                                    "bin/ccs copy-key ANTHROPIC_API_KEY --from <that .env> copies it without showing it. "
                                    "This suite stops at its own monthly cap below.",
             "fields": [f("ANTHROPIC_API_KEY", "Anthropic API key", secret=True), f("AI_MONTHLY_CAP_USD", "Monthly cap, USD")]},
            {"title": "Buffer", "note": "This company's own Buffer account. After the key, link the channels on the Buffer page.",
             "fields": [f("BUFFER_API_KEY", "Buffer API key", secret=True), f("BUFFER_PLAN", "Buffer plan", choices=["free", "essentials", "team"]),
                        f("PINTEREST_BOARD_ID", "Pinterest board id"), f("PINTEREST_LINK", "Page a pin opens (blank: the quote page)")]},
            {"title": "Posting", "note": "Blank keeps the default. Times are local. Post times: one per network (facebook=09:30) or "
                                         "weekdays/weekends (instagram=11:30/10:00); the building day is the weekday for building photos.",
             "fields": [f("POST_NETWORKS", "Networks posts go to, comma separated (blank: instagram only; add facebook or pinterest once connected)"),
                        f("POST_TIMES", "Post times (default instagram 11:30 weekdays and 10:00 weekends, facebook 09:30, pinterest 20:30)"),
                        f("BUILDING_WEEKDAY", "Building day (default wednesday)"), f("VARIETY_DAYS", "No same event or person twice inside, days (default 14)"),
                        f("PHOTO_REPEAT_DAYS", "A photo sits out after it airs, days (default 180)"),
                        f("TIMEZONE", "Time zone (default America/New_York)"), f("DIGEST_HOUR", "Morning brief hour (default 7)")]},
            {"title": "Scout and outreach", "note": "Where the scout looks for events, in plain words; how far ahead; the daily caps on "
                                                    "organizer drafts and approved sends. Notes still leave only on your Approve.",
             "fields": [f("SCOUT_REGION", "Region to search (for example Washington DC, Maryland and Virginia)"),
                        f("SCOUT_MONTHS", "Months ahead (default 9)"), f("OUTREACH_DAILY_DRAFTS", "Organizer drafts a day (default 5)"),
                        f("OUTREACH_DAILY_SENDS", "Approved sends a day (default 10)")]},
            {"title": "Image hosting", "note": "Where Buffer fetches post images from.",
             "fields": [f("MEDIA_BASE_URL", "Image address"), f("MEDIA_UPLOAD_TOKEN", "Upload token", secret=True)]},
            {"title": "Phone alerts", "note": "This company's own ntfy topic. Pings: a post ready to approve, a post that went out, "
                                              "the watchdog's alerts and the morning brief. Save the topic, then send a test below.",
             "fields": [f("NTFY_TOPIC", "ntfy topic")]},
            {"title": "GitHub", "note": "For the doctor (2026-10-15): an error in the code becomes an issue in "
                                        "ChrisKennedyImages/cki-convention-social with the traceback, and your phone gets the link. "
                                        "A fine-grained token for that one repository with one permission, Issues: Read and write. "
                                        "Without it the doctor pings you instead.",
             "fields": [f("GITHUB_TOKEN", "Fine-grained token (Issues only)", secret=True)]},
            {"title": "Designed drafts", "note": "The suite designs posts by itself from 8:00 to 20:00, one an hour, each on your "
                                                 "approved photos with Claude's final check, and sends each to your phone with Post now, "
                                                 "Follow the pace and Skip. No more are made while that many still wait for you. A photo "
                                                 "is never on two posts inside the longer of the two windows under Posting.",
             "fields": [f("DESIGNED_PER_DAY", "Designed drafts a day (default 3; 0 stops them; 6 at most)")]},
            {"title": "Local sorting", "note": "Ollama on this Mini sorts the photo library for free. Leave blank to use the first vision model it has.",
             "fields": [f("OLLAMA_MODEL", "Ollama model"), f("CLASSIFY_BACKEND", "Sorter", choices=["auto", "ollama", "claude"])]},
            {"title": "This dashboard", "note": "The address you open this dashboard at from your phone.",
             "fields": [f("DASHBOARD_PUBLIC_URL", "Dashboard address")]},
            {"title": "Search engines", "note": "Google: if Search Console verified the property by itself (through Cloudflare's DNS), "
                                               "nothing goes here; submit sitemap.xml there once and you are done. If it asks you to prove "
                                               "ownership, paste what it shows for one of its methods: the HTML tag or its content value, "
                                               "the TXT record (google-site-verification=...) or the HTML file's name (google....html); "
                                               "the site republishes itself within minutes, then press Verify there. Bing and the other "
                                               "IndexNow engines are told after every publish with the key below, made by itself.",
             "fields": [f("GOOGLE_SITE_VERIFICATION", "Google Search Console tag"), f("INDEXNOW_KEY", "IndexNow key (made on the first publish)")]},
        ]

    key_names = {fld["name"] for g in key_groups() for fld in g["fields"]}
    clearable = {fld["name"] for g in key_groups() for fld in g["fields"] if not fld["secret"] and not fld["choices"]}

    @app.get("/keys", response_class=HTMLResponse)
    def keys(request: Request, user: str = Depends(require_user), msg: str = ""):
        return render(request, "keys.html", groups=key_groups(), msg=msg.replace("+", " "))

    @app.post("/keys")
    async def keys_save(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Blank keeps what is there; the Clear box next to a plain setting writes it empty, so the default
        stands again (2026-10-13: a value could never be taken back from here). Secrets are replaced, never cleared.
        The Search Console value is checked here, where he pastes it: a value that is none of Google's forms is
        refused with the reason, and a good one makes the site republish itself (deploy.photos_pending)."""
        from ..site import build as site_build
        from ..site import deploy
        form = await request.form()
        updates, cleared, refused = {}, 0, ""
        for name in key_names:
            if name in clearable and form.get(f"clear_{name}"):
                if config.getenv(name) is not None:
                    updates[name] = ""
                    cleared += 1
                continue
            value = (form.get(name) or "").strip()
            if not value or value == (config.getenv(name) or ""):
                continue
            if name == "BUFFER_PLAN" and value not in ("free", "essentials", "team"):
                continue
            if name == "CREDITS_SHEET_ID":
                value = drive_id_from(value)
            if name == site_build.VERIFICATION_KEY:
                parsed = site_build.parse_verification(value)
                if parsed[2]:
                    refused = f"the Search Console value was not saved: {parsed[2]}"
                    continue
                if parsed[:2] == site_build.parse_verification(config.getenv(name) or "")[:2]:
                    continue                      # the same tag in another of Google's forms: nothing changes for the site
            updates[name] = value
        if updates:
            config.write_env(updates)
            if site_build.VERIFICATION_KEY in updates:
                settings.set(conn, deploy.TAG_CHANGED_KEY, db.utcnow())
            if any(k in updates for k in deploy.SITE_KEYS):
                settings.set(conn, deploy.KEYS_CHANGED_KEY, db.utcnow())     # the site shows these: it republishes itself
        note = f"saved {len(updates) - cleared}" + (f", cleared {cleared}" if cleared else "")
        if site_build.VERIFICATION_KEY in updates:
            note += "; the site republishes itself in a few minutes with the Search Console change, then press Verify there"
        elif any(k in updates for k in deploy.SITE_KEYS):
            note += "; the site republishes itself in a few minutes with the new contact details"
        if refused:
            note += "; " + refused
        return RedirectResponse("/keys?msg=" + quote_plus(note), status_code=303)

    @app.post("/keys/test-alert")
    def keys_test_alert(user: str = Depends(require_user)):
        """Verified at the consumer: the phone. Says what happened, never only that it tried."""
        from ..core import notify
        result = notify.push_result(f"{config.get_config().brand_name}: test", "This is the dashboard's test ping. Tap to open it.",
                                    dry_run=False, priority="default", click=notify.link("/"))
        msg = "Test ping sent: it should be on your phone now" if result == "sent" else f"No ping: {result}"
        return RedirectResponse("/keys?msg=" + quote_plus(msg), status_code=303)

    @app.post("/keys/test-watch")
    def keys_test_watch(user: str = Depends(require_user)):
        """7.4: the outside watch's test ping, sent by the site at once. Verified at the consumer: the phone."""
        from ..booking.remote import SiteAPI
        api = SiteAPI.from_config()
        if api is None:
            msg = "No site token (MEDIA_UPLOAD_TOKEN is not set): the site cannot be asked."
        else:
            try:
                res = api.test_watch()
            except Exception as e:  # noqa: BLE001
                msg = f"The site did not answer ({type(e).__name__}: {str(e)[:120]})."
            else:
                msg = ("Test sent by the site: the outside watch's ping should be on your phone now." if res.get("sent")
                       else "The site answered but sent nothing: its NTFY_TOPIC secret is not set yet (it is put on the next deploy).")
        return RedirectResponse("/keys?msg=" + quote_plus(msg), status_code=303)

    @app.post("/keys/password")
    def keys_password(user: str = Depends(require_user), password: str = Form(...), confirm: str = Form(default="")):
        if len(password) < 8:
            return RedirectResponse("/keys?msg=password+needs+8+characters", status_code=303)
        if password != confirm:
            return RedirectResponse("/keys?msg=passwords+did+not+match", status_code=303)
        config.write_env({"DASHBOARD_PASSWORD_HASH": auth.hash_password(password)})
        return RedirectResponse("/keys?msg=password+changed", status_code=303)

    from . import learner_seo_routes, scout_outreach_routes
    learner_seo_routes.register(app, require_user, conn_dep, render)
    scout_outreach_routes.register(app, require_user, conn_dep, render)
    return app


app = None  # uvicorn convention_social.dashboard.app:create_app --factory


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=config.get_config().dashboard_port)
