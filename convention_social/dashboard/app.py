"""The review dashboard: 127.0.0.1 only, one password, built for a phone screen.

Server-rendered FastAPI + Jinja2, no JavaScript framework. Reached from
Chris's phone over Tailscale. With no DASHBOARD_PASSWORD_HASH the app
answers 503 to everything (fail closed).

Pages: Queue (Approve / Reject, refused while a caption breaks a rule or a
photo is no longer eligible), Library (clear or exclude folders, block single
photos), Do not use, Calendar (events, attending, official only on Chris's
word), Drive (sign-in state, last scan, the report), Agents (dry-run
switches, errors, spend), Keys (writes .env).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets as pysecrets
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..agents import AGENTS, is_built
from ..ai import copy_rules, spend
from ..ai import names as ai_names
from ..ai.claude import NETWORKS
from ..buffer import payloads as buffer_payloads
from ..buffer.client import BufferBudgetExceeded, BufferClient, BufferError, BufferRateLimited
from ..core import auth, config, db, secrets, settings, state_io
from .. import music
from ..library import eligibility, report

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
COOKIE = "ccs_session"
SESSION_DAYS = 30
QUEUE_STATUSES = ("draft", "approved", "would_publish", "scheduled", "published", "failed", "rejected")
ID_IN_LINK = re.compile(r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_-]{2,})")


# ---------------------------------------------------------------------- session
def _session_secret() -> bytes:
    cfg = config.get_config()
    cfg.locks_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.locks_dir / "dashboard.secret"
    if not path.exists():
        path.write_text(pysecrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


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
SECTIONS = (
    ("Today", "/", ("/queue",), (("Queue", "/"),)),
    ("Photos", "/library", ("/library", "/donotuse", "/drive"),
     (("To review", "/library"), ("Approved", "/library?view=approved"), ("Folders", "/library?view=folders"),
      ("Design", "/library?view=design"), ("Do not use", "/donotuse"), ("Drive", "/drive"))),
    ("Bookings", "/inquiries", ("/inquiries", "/bookings", "/calendar"),
     (("Requests", "/inquiries"), ("Bookings", "/bookings"), ("Calendar", "/calendar"))),
    ("More", "/more", ("/more", "/outreach", "/scout", "/seo", "/learner", "/agents", "/buffer", "/keys", "/errors"),
     (("Outreach", "/outreach"), ("Scout", "/scout"), ("Search", "/seo"), ("Learner", "/learner"),
      ("Agents", "/agents"), ("Buffer", "/buffer"), ("Keys", "/keys"))),
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


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("brand", config.get_config().brand_name)
    ctx.setdefault("nav", nav_for(request))
    return TEMPLATES.TemplateResponse(request, name, ctx)


def inside_data_root(p: Path) -> bool:
    try:
        return p.resolve().is_relative_to(config.get_config().data_root.resolve()) and p.exists()
    except OSError:
        return False


# ---------------------------------------------------------------------- queue helpers
def official_for(conn, row) -> bool:
    if not row["convention_id"]:
        return False
    c = db.one(conn, "SELECT official FROM conventions WHERE id=?", (row["convention_id"],))
    return bool(c and c["official"])


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
        art = json.loads(row["rule_report"] or "{}").get("art") or {}
    except ValueError:
        art = {}
    return {**dict(row), "art": art, "captions": captions, "targets": targets, "reports": reports, "official": official,
            "blocked_networks": [n for n in targets if not reports[n].ok],
            "photo_checks": photo_checks, "ineligible": [c for c in photo_checks if not c[1]],
            "video": any(str(x).lower().endswith(".mp4") for x in renders.get("9:16") or []), "cover": bool(renders.get("cover")),
            "renders": {a: list(range(1, len(ps) + 1)) for a, ps in renders.items() if a not in NOT_THUMBS}}


MEDIA_TYPES = {".mp4": "video/mp4", ".png": "image/png"}


# what a photo shows, in plain words, for the draft page's correction (Chris, 2026-10-11: "it calls a
# stage shot a portrait which, never can happen!")
SHOT_CHOICES = [("stage_panel", "Stage and panel"), ("backstage", "Backstage"), ("portrait", "Portrait"), ("headshot", "Headshot"),
                ("group", "Group photo"), ("candid", "Candid moment"), ("crowd", "Crowd"), ("vendor_hall", "Vendor hall"),
                ("booth", "Exhibitor booth"), ("dinner_reception", "Dinner and reception"), ("venue", "Venue"),
                ("building_exterior", "Building exterior"), ("building_interior", "Building interior"), ("other", "Other")]


def shot_type_of(conn, photo_id: int) -> str:
    row = db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (photo_id,))
    return (row["shot_type"] if row else None) or ""


def start_agent(name: str) -> None:
    """One run now, exactly as its schedule would start it: its own lock, its own dry-run switch,
    its own gates. The dashboard only starts it and returns."""
    cfg = config.get_config()
    cfg.ensure_dirs()
    with open(cfg.data_root / "logs" / f"{name}.manual.log", "ab") as log:
        subprocess.Popen([sys.executable, "-m", "convention_social.cli", "run", name], cwd=str(config.REPO_ROOT),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)


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
DESIGN_FILE = re.compile(r"(index\.html|about\.json|[a-z]+-post\.jpg|slide-\d{2}\.jpg|[a-z]+-reel\.mp4)")
DESIGN_TYPES = {".html": "text/html", ".json": "application/json", ".jpg": "image/jpeg", ".mp4": "video/mp4"}


def latest_design() -> Optional[str]:
    """The newest folder of design samples in DATA_ROOT/renders that has its page."""
    renders = config.get_config().data_root / "renders"
    if not renders.is_dir():
        return None
    names = sorted(p.name for p in renders.iterdir() if DESIGN_DIR.fullmatch(p.name) and (p / "index.html").is_file())
    return names[-1] if names else None


PAGE = 48
SORTED = "c.method IN ('ollama', 'vision')"
# report.strength, in SQL: the old single score for a photo sorted before the strength questions,
# else quality + light + moment, minus 6 when the subject is soft, on 0 to 10.
STRENGTH = """CASE WHEN c.light IS NULL AND c.moment IS NULL THEN COALESCE(c.quality, 0) * 1.0
                   ELSE MAX(0.0, (COALESCE(c.quality, 0) + COALESCE(c.light, 0) + COALESCE(c.moment, 0)
                                  - CASE WHEN c.sharp = 0 THEN 6 ELSE 0 END) * 10.0 / 15) END"""
DECISION = "CASE WHEN p.clearance IN ('blocked', 'cleared') THEN p.clearance ELSE COALESCE(fd.decision, 'not_cleared') END"
PAGE_FROM = """FROM photos p LEFT JOIN classifications c ON c.photo_id = p.id
               LEFT JOIN drive_folders f ON f.drive_id = p.folder_id
               LEFT JOIN temp.folder_decision fd ON fd.drive_id = p.folder_id"""
VIEWS = {
    # Sorted photos Chris has not decided on that could ever be used: nobody who may be under 18,
    # no readable personal detail (temp.hidden_photo). Strongest first.
    "review": (f"p.trashed = 0 AND {SORTED} AND c.possible_minor = 0 AND {DECISION} = 'not_cleared' "
               "AND COALESCE(c.shot_type, '') NOT IN ('cosplay_portrait') "
               "AND p.id NOT IN (SELECT id FROM temp.hidden_photo)",
               f"({STRENGTH}) DESC, p.id"),
    # Everything Chris cleared, by the photo itself or by its folder. Sorted ones first, strongest first.
    "approved": (f"p.trashed = 0 AND {DECISION} = 'cleared'",
                 f"CASE WHEN {SORTED} THEN 0 ELSE 1 END, CASE WHEN {SORTED} THEN ({STRENGTH}) ELSE 0 END DESC, p.id"),
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
        resp.set_cookie(COOKIE, make_token("chris"), max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax")
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

    # ------------------------------------------------------------------ queue
    @app.get("/", response_class=HTMLResponse)
    def queue(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), show: str = "open"):
        if show == "all":
            where, params = "1=1", ()
        elif show in QUEUE_STATUSES:
            where, params = "status = ?", (show,)
        else:
            where, params = "status IN ('draft','approved','scheduled','would_publish','failed')", ()
        rows = db.rows(conn, f"SELECT * FROM content_queue WHERE {where} ORDER BY id DESC LIMIT 100", params)
        auth_state = settings.get(conn, "drive.auth_state") or "missing"
        try:
            brief = json.loads(settings.get(conn, "chief.brief") or "{}")
        except ValueError:
            brief = {}
        return render(request, "queue.html", items=[queue_view(conn, r) for r in rows], show=show,
                      auth_state=auth_state, msg=request.query_params.get("msg", ""), brief=brief)

    @app.get("/queue/{qid}", response_class=HTMLResponse)
    def queue_detail(qid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        return render(request, "detail.html", item=queue_view(conn, load_queue_row(conn, qid)), networks=NETWORKS, msg=msg,
                      shot_choices=SHOT_CHOICES)

    @app.post("/queue/{qid}/save")
    async def queue_save(qid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        load_queue_row(conn, qid)
        form = await request.form()
        captions = {n: (form.get(f"caption_{n}") or "").strip() for n in NETWORKS}
        targets = [n for n in NETWORKS if form.get(f"target_{n}")]
        scheduled = (form.get("scheduled_for") or "").strip() or None
        conn.execute("UPDATE content_queue SET caption=?, targets=?, scheduled_for=?, updated_at=? WHERE id=?",
                     (json.dumps(captions), json.dumps(targets), scheduled, db.utcnow(), qid))
        return RedirectResponse(f"/queue/{qid}?msg=saved", status_code=303)

    @app.post("/queue/{qid}/approve")
    def queue_approve(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_queue_row(conn, qid)
        if row["status"] != "draft":
            return RedirectResponse(f"/queue/{qid}", status_code=303)
        item = queue_view(conn, row)
        if item["blocked_networks"]:
            return RedirectResponse(f"/queue/{qid}?msg=blocked", status_code=303)
        if item["ineligible"]:
            return RedirectResponse(f"/queue/{qid}?msg=ineligible", status_code=303)
        if not item["targets"]:
            return RedirectResponse(f"/queue/{qid}?msg=notargets", status_code=303)
        now = db.utcnow()
        conn.execute("UPDATE content_queue SET status='approved', approved_at=?, last_error=NULL, updated_at=? WHERE id=?", (now, now, qid))
        return RedirectResponse(f"/queue/{qid}?msg=approved", status_code=303)

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
            start_agent("content")
            return RedirectResponse(f"/?msg=redraft", status_code=303)
        return RedirectResponse(f"/queue/{qid}?msg=saved", status_code=303)

    @app.post("/queue/{qid}/reject")
    def queue_reject(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        load_queue_row(conn, qid)
        conn.execute("UPDATE content_queue SET status='rejected', updated_at=? WHERE id=?", (db.utcnow(), qid))
        return RedirectResponse("/?msg=rejected", status_code=303)

    # ------------------------------------------------------------------ media
    @app.get("/media/render/{qid}/{aspect}/{index}")
    def media_render(qid: int, aspect: str, index: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_queue_row(conn, qid)
        paths = json.loads(row["render_paths"] or "{}").get(aspect.replace("x", ":"), [])
        if not 1 <= index <= len(paths) or not inside_data_root(Path(paths[index - 1])):
            raise HTTPException(404)
        return FileResponse(paths[index - 1], media_type=MEDIA_TYPES.get(Path(paths[index - 1]).suffix.lower(), "image/jpeg"))

    @app.get("/media/thumb/{photo_id}")
    def media_thumb(photo_id: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """A cached small preview from Drive (read only). Fetched once, then served from DATA_ROOT/thumbs."""
        row = db.one(conn, "SELECT drive_id, thumbnail_link FROM photos WHERE id=?", (photo_id,))
        if not row:
            raise HTTPException(404)

        def fetch(drive_id: str) -> bytes:
            from ..drive import oauth
            from ..drive.api import DriveReader
            return DriveReader(oauth.access_token(conn), conn=conn, agent="dashboard").thumbnail_for(drive_id, 400)
        path = cached_thumb(row["drive_id"], fetch if row["thumbnail_link"] else None)
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
        prepare_photo_views(conn, eligibility.folder_decisions(conn))
        common = dict(view=view, msg=msg, counts={"approved": count_photos(conn, "approved")} if view == "design" else {},
                      drive_state=settings.get(conn, "drive.auth_state") or "missing")
        if view == "folders":
            where = "conv > 0" if show == "events" else ("f.clearance='cleared'" if show == "cleared" else "1=1")
            rows = db.rows(conn, f"""
                SELECT * FROM (
                  SELECT f.drive_id, f.name, f.path, f.clearance, f.image_count,
                         SUM(CASE WHEN c.is_convention=1 THEN 1 ELSE 0 END) AS conv,
                         SUM(CASE WHEN c.possible_minor=1 THEN 1 ELSE 0 END) AS minors
                  FROM drive_folders f LEFT JOIN photos p ON p.folder_id=f.drive_id AND p.trashed=0
                  LEFT JOIN classifications c ON c.photo_id=p.id
                  GROUP BY f.drive_id) f
                WHERE image_count > 0 AND {where} ORDER BY conv DESC, image_count DESC LIMIT 400""")
            note = ""
            if show == "events" and not rows:
                rows = db.rows(conn, """SELECT f.drive_id, f.name, f.path, f.clearance, f.image_count, 0 AS conv, 0 AS minors
                                        FROM drive_folders f WHERE f.image_count > 0 ORDER BY f.image_count DESC LIMIT 400""")
                if rows:
                    note = "No folder has been recognised as event work yet, so every folder with photos is shown."
            return render(request, "library.html", folders=rows, show=show, note=note, **common)
        if view == "design":
            from ..render import design_samples
            return render(request, "library.html", renders=latest_renders(), design=latest_design(), tracks=music.tracks(conn),
                          design_status=design_samples.read_status(), readiness=design_samples.readiness(conn), **common)
        view = "approved" if view == "approved" else "review"
        subject = subject if subject in SUBJECTS else "event"
        subject_counts = {s: count_photos(conn, view, s) for s, _ in SUBJECT_WORDS}
        total = subject_counts[subject]
        pages = max(1, (total + PAGE - 1) // PAGE)
        page = max(1, min(page, pages))
        shown = photo_page(conn, view, page, subject=subject)
        for i, p in enumerate(shown):
            # after a tap the page comes back to the next photo, since the one tapped may leave this list
            nxt = shown[i + 1]["id"] if i + 1 < len(shown) else p["id"]
            p["back"] = f"/library?view={view}&subject={subject}&page={page}#p{nxt}"
            p["why"] = eligibility.is_candidate(conn, p["id"]) if view == "approved" else None
        common["view"] = view
        return render(request, "library.html", items=shown, page=page, pages=pages, total=total, subject=subject,
                      subject_counts=subject_counts, subject_words=SUBJECT_WORDS, **common)

    @app.get("/more", response_class=HTMLResponse)
    def more(request: Request, user: str = Depends(require_user)):
        return render(request, "more.html")

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
            return RedirectResponse("/library?msg=Tick+that+you+have+the+right+to+use+the+track+in+posts", status_code=303)
        data = await file.read(music.MAX_BYTES + 1)
        try:
            music.add(conn, file.filename or "", data, title=title, artist=artist, source=source, terms=terms)
        except music.Refused as e:
            return RedirectResponse(f"/library?msg=Track+not+added:+{str(e).replace(' ', '+')}", status_code=303)
        return RedirectResponse("/library?msg=Track+added.+New+reels+use+the+newest+track.", status_code=303)

    @app.post("/library/music/{tid}/active")
    def library_music_active(tid: int, state: str = Form(...), user: str = Depends(require_user), conn=Depends(conn_dep)):
        music.set_active(conn, tid, state == "on")
        return RedirectResponse("/library", status_code=303)

    @app.post("/library/design")
    def library_design_make(user: str = Depends(require_user)):
        """Start `ccs design` (its own lock; a second press while one runs does nothing). It reads
        Drive's previews and writes only under DATA_ROOT/renders; nothing is posted."""
        from ..render import design_samples
        design_samples.write_status("running", "being made on your approved photos")
        design_samples.start_in_background()
        return RedirectResponse("/library?view=design&msg=Making+design+samples+on+your+approved+photos.+This+card+says+when+they+are+ready.",
                                status_code=303)

    @app.get("/library/design")
    def library_design(user: str = Depends(require_user)):
        latest = latest_design()
        if not latest:
            return RedirectResponse("/library?msg=No+design+samples+yet:+press+Make+design+samples", status_code=303)
        return RedirectResponse(f"/library/design/{latest}/index.html", status_code=303)

    @app.get("/library/design/{folder}/{name}")
    def library_design_file(folder: str, name: str, user: str = Depends(require_user)):
        # only a design folder and only the files the designer writes, by exact name
        if not DESIGN_DIR.fullmatch(folder) or not DESIGN_FILE.fullmatch(name):
            raise HTTPException(404)
        path = config.get_config().data_root / "renders" / folder / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type=DESIGN_TYPES[Path(name).suffix])

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
        return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else "/library", status_code=303)

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

    @app.post("/library/photo/{pid}/clearance")
    def photo_clearance(pid: int, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...),
                        back: str = Form(default="/library")):
        if state not in ("cleared", "blocked", "inherit"):
            raise HTTPException(400)
        conn.execute("UPDATE photos SET clearance=?, clearance_at=? WHERE id=?", (state, db.utcnow(), pid))
        return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else "/library", status_code=303)

    # ------------------------------------------------------------------ do not use
    @app.get("/donotuse", response_class=HTMLResponse)
    def donotuse(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        return render(request, "donotuse.html", rows=db.rows(conn, "SELECT * FROM do_not_use ORDER BY id DESC"))

    @app.post("/donotuse/add")
    def donotuse_add(user: str = Depends(require_user), conn=Depends(conn_dep), kind: str = Form(...), value: str = Form(...),
                     reason: str = Form(default="")):
        if kind not in ("photo", "folder", "person", "handle"):
            raise HTTPException(400)
        value = drive_id_from(value) if kind in ("photo", "folder") else value.strip().lower()
        if value:
            conn.execute("INSERT OR IGNORE INTO do_not_use (kind, value, reason, added_at) VALUES (?,?,?,?)",
                         (kind, value, reason.strip() or None, db.utcnow()))
            # anything waiting that this now covers goes back to drafts with the reason
            for q in db.rows(conn, "SELECT id, photo_ids FROM content_queue WHERE status IN ('draft','approved')"):
                bad = [p for p in json.loads(q["photo_ids"] or "[]") if not eligibility.is_eligible(conn, int(p))[0]]
                if bad:
                    conn.execute("UPDATE content_queue SET status='draft', last_error=?, updated_at=? WHERE id=?",
                                 ("A photo in this post is now on the do-not-use list.", db.utcnow(), q["id"]))
        return RedirectResponse("/donotuse", status_code=303)

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
                      body: str = Form(""), deposit_link: str = Form("")):
        row = db.one(conn, "SELECT reply_status FROM inquiries WHERE id=?", (iid,))
        if row is None:
            raise HTTPException(404)
        if row["reply_status"] in ("sent",):
            return RedirectResponse(f"/inquiries/{iid}?msg=already_sent", status_code=303)
        conn.execute("UPDATE inquiries SET reply_subject=?, reply_body=?, reply_status='draft', deposit_link=?, updated_at=? WHERE id=?",
                     (subject.strip(), body.replace("\r\n", "\n").strip(), deposit_link.strip() or None, db.utcnow(), iid))
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
    def drive(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        from ..library import report
        renders = sorted((config.get_config().data_root / "renders").glob("library-report-*.html"))
        return render(request, "drive.html", state=settings.get(conn, "drive.auth_state") or "missing",
                      detail=settings.get(conn, "drive.auth_detail") or "", summary=report.summary(conn),
                      report_name=renders[-1].name if renders else "",
                      unmatched=settings.get(conn, "credits.unmatched") or "")

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
        errors = [dict(e) for e in db.rows(conn, "SELECT * FROM errors WHERE alerted=0 ORDER BY id DESC LIMIT 50")]
        kinds = [dict(k) for k in db.rows(conn, "SELECT kind, COUNT(*) AS n FROM errors WHERE alerted=0 GROUP BY kind ORDER BY n DESC")]
        switches = [r for r in rows if r["dry_run"] is not None]
        return render(request, "agents.html", agents=rows, errors=errors, kinds=kinds, msg=request.query_params.get("msg", ""),
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
        for name in settings.AGENTS_WITH_DRY_RUN:
            settings.set_dry_run(conn, name, state != "off")
        word = "dry+run" if state != "off" else "LIVE"
        return RedirectResponse(f"/agents?msg=Every+agent+is+now+{word}.", status_code=303)

    @app.post("/agents/{name}/dry-run")
    def toggle_dry_run(name: str, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...)):
        if name not in settings.AGENTS_WITH_DRY_RUN:
            raise HTTPException(404)
        settings.set_dry_run(conn, name, state != "off")
        return RedirectResponse("/agents", status_code=303)

    @app.post("/errors/ack-kind")
    def ack_kind(kind: str = Form(...), user: str = Depends(require_user), conn=Depends(conn_dep)):
        """Dismiss every open error of one kind (Chris, 2026-10-11: "the terminal command to dismiss
        all the drive errors"). A dismissed error stays in the table; it only leaves this list."""
        n = conn.execute("UPDATE errors SET alerted=1 WHERE alerted=0 AND kind=?", (kind,)).rowcount
        return RedirectResponse(f"/agents?msg={n}+{kind.replace('_', '+')}+errors+dismissed", status_code=303)

    @app.post("/errors/{eid}/ack")
    def ack_error(eid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        conn.execute("UPDATE errors SET alerted=1 WHERE id=?", (eid,))
        return RedirectResponse("/agents", status_code=303)

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
            {"title": "Google Drive", "note": "From this company's own Google Cloud project. Read only.",
             "fields": [f("GOOGLE_OAUTH_CLIENT_ID", "OAuth client id"), f("GOOGLE_OAUTH_CLIENT_SECRET", "OAuth client secret", secret=True),
                        f("CREDITS_SHEET_ID", "Credits sheet (link or id)")]},
            {"title": "Mail", "note": "The company mailbox. An app password, never the account password.",
             "fields": [f("SMTP_HOST", "Mail server"), f("SMTP_USER", "Mailbox login"), f("SMTP_PASSWORD", "App password", secret=True)]},
            {"title": "AI", "note": "Chris's Anthropic key, the one his other suite uses (his choice, 2026-10-11): "
                                    "bin/ccs copy-key ANTHROPIC_API_KEY --from <that .env> copies it without showing it. "
                                    "This suite stops at its own monthly cap below.",
             "fields": [f("ANTHROPIC_API_KEY", "Anthropic API key", secret=True), f("AI_MONTHLY_CAP_USD", "Monthly cap, USD")]},
            {"title": "Buffer", "note": "This company's own Buffer account. After the key, link the channels on the Buffer page.",
             "fields": [f("BUFFER_API_KEY", "Buffer API key", secret=True), f("BUFFER_PLAN", "Buffer plan", choices=["free", "essentials", "team"]),
                        f("PINTEREST_BOARD_ID", "Pinterest board id")]},
            {"title": "Image hosting", "note": "Where Buffer fetches post images from.",
             "fields": [f("MEDIA_BASE_URL", "Image address"), f("MEDIA_UPLOAD_TOKEN", "Upload token", secret=True)]},
            {"title": "Phone alerts", "note": "This company's own ntfy topic. Pings: a post ready to approve, a post that went out, "
                                              "the watchdog's alerts and the morning brief. Save the topic, then send a test below.",
             "fields": [f("NTFY_TOPIC", "ntfy topic")]},
            {"title": "Local sorting", "note": "Ollama on this Mini sorts the photo library for free. Leave blank to use the first vision model it has.",
             "fields": [f("OLLAMA_MODEL", "Ollama model"), f("CLASSIFY_BACKEND", "Sorter", choices=["auto", "ollama", "claude"])]},
            {"title": "This dashboard", "note": "The address you open this dashboard at from your phone.",
             "fields": [f("DASHBOARD_PUBLIC_URL", "Dashboard address")]},
        ]

    key_names = {fld["name"] for g in key_groups() for fld in g["fields"]}

    @app.get("/keys", response_class=HTMLResponse)
    def keys(request: Request, user: str = Depends(require_user), msg: str = ""):
        return render(request, "keys.html", groups=key_groups(), msg=msg.replace("+", " "))

    @app.post("/keys")
    async def keys_save(request: Request, user: str = Depends(require_user)):
        form = await request.form()
        updates = {}
        for name in key_names:
            value = (form.get(name) or "").strip()
            if not value or value == (config.getenv(name) or ""):
                continue
            if name == "BUFFER_PLAN" and value not in ("free", "essentials", "team"):
                continue
            if name == "CREDITS_SHEET_ID":
                value = drive_id_from(value)
            updates[name] = value
        if updates:
            config.write_env(updates)
        return RedirectResponse(f"/keys?msg=saved+{len(updates)}", status_code=303)

    @app.post("/keys/test-alert")
    def keys_test_alert(user: str = Depends(require_user)):
        """Verified at the consumer: the phone. Says what happened, never only that it tried."""
        from ..core import notify
        result = notify.push_result(f"{config.get_config().brand_name}: test", "This is the dashboard's test ping. Tap to open it.",
                                    dry_run=False, priority="default", click=notify.link("/"))
        msg = "Test ping sent: it should be on your phone now" if result == "sent" else f"No ping: {result}"
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
