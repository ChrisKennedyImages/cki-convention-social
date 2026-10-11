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
import re
import secrets as pysecrets
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..agents import AGENTS, is_built
from ..ai import copy_rules, spend
from ..ai.claude import NETWORKS
from ..core import auth, config, db, secrets, settings
from ..library import eligibility

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


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("brand", config.get_config().brand_name)
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


def queue_view(conn, row) -> dict:
    captions = json.loads(row["caption"] or "{}")
    targets = json.loads(row["targets"] or "[]")
    official = official_for(conn, row)
    reports = {n: copy_rules.check(captions.get(n, ""), official=official) for n in NETWORKS}
    photo_ids = json.loads(row["photo_ids"] or "[]")
    photo_checks = [(pid, *eligibility.is_eligible(conn, int(pid))) for pid in photo_ids]
    renders = json.loads(row["render_paths"] or "{}")
    try:
        art = json.loads(row["rule_report"] or "{}").get("art") or {}
    except ValueError:
        art = {}
    return {**dict(row), "art": art, "captions": captions, "targets": targets, "reports": reports, "official": official,
            "blocked_networks": [n for n in targets if not reports[n].ok],
            "photo_checks": photo_checks, "ineligible": [c for c in photo_checks if not c[1]],
            "renders": {a: list(range(1, len(ps) + 1)) for a, ps in renders.items()}}


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
def create_app() -> FastAPI:
    app = FastAPI(title="review", docs_url=None, redoc_url=None, openapi_url=None)

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
        return render(request, "detail.html", item=queue_view(conn, load_queue_row(conn, qid)), networks=NETWORKS, msg=msg)

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
        return FileResponse(paths[index - 1], media_type="image/jpeg")

    @app.get("/media/thumb/{photo_id}")
    def media_thumb(photo_id: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        """A cached small preview from Drive (read only). Fetched once, then served from DATA_ROOT/thumbs."""
        row = db.one(conn, "SELECT drive_id, thumbnail_link FROM photos WHERE id=?", (photo_id,))
        if not row:
            raise HTTPException(404)
        path = config.get_config().data_root / "thumbs" / f"{row['drive_id']}.jpg"
        if not path.exists():
            if not row["thumbnail_link"]:
                raise HTTPException(404)
            from ..drive import oauth
            from ..drive.api import DriveReader
            try:
                data = DriveReader(oauth.access_token(conn), conn=conn, agent="dashboard").thumbnail_for(row["drive_id"], 400)
            except Exception:  # noqa: BLE001 — not signed in, network: no picture, not a crash
                raise HTTPException(404)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return FileResponse(path, media_type="image/jpeg")

    # ------------------------------------------------------------------ library
    @app.get("/library", response_class=HTMLResponse)
    def library(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), show: str = "events"):
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
        return render(request, "library.html", folders=rows, show=show, msg=request.query_params.get("msg", ""))

    @app.post("/library/folder/{fid}/clearance")
    def folder_clearance(fid: str, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...),
                         back: str = Form(default="/library")):
        if state not in ("cleared", "excluded", "not_cleared"):
            raise HTTPException(400)
        conn.execute("UPDATE drive_folders SET clearance=?, clearance_at=? WHERE drive_id=?", (state, db.utcnow(), fid))
        return RedirectResponse(back if back.startswith("/") else "/library", status_code=303)

    @app.get("/library/folder/{fid}", response_class=HTMLResponse)
    def folder(fid: str, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        f = db.one(conn, "SELECT * FROM drive_folders WHERE drive_id=?", (fid,))
        if f is None:
            raise HTTPException(404)
        photos = db.rows(conn, "SELECT p.*, c.shot_type, c.quality, c.possible_minor, c.summary, c.method FROM photos p "
                               "LEFT JOIN classifications c ON c.photo_id=p.id WHERE p.folder_id=? AND p.trashed=0 "
                               "ORDER BY COALESCE(c.quality,0) DESC, p.taken_at LIMIT 300", (fid,))
        items = [{**dict(p), "eligible": eligibility.is_candidate(conn, p["id"])} for p in photos]
        return render(request, "folder.html", folder=f, items=items)

    @app.post("/library/photo/{pid}/clearance")
    def photo_clearance(pid: int, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...),
                        back: str = Form(default="/library")):
        if state not in ("cleared", "blocked", "inherit"):
            raise HTTPException(400)
        conn.execute("UPDATE photos SET clearance=?, clearance_at=? WHERE id=?", (state, db.utcnow(), pid))
        return RedirectResponse(back if back.startswith("/") else "/library", status_code=303)

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
            rows.append({"name": name, "meta": meta, "built": is_built(name),
                         "dry_run": settings.dry_run(conn, name) if name in settings.AGENTS_WITH_DRY_RUN else None,
                         "last": dict(last) if last else None})
        errors = [dict(e) for e in db.rows(conn, "SELECT * FROM errors WHERE alerted=0 ORDER BY id DESC LIMIT 50")]
        return render(request, "agents.html", agents=rows, errors=errors,
                      ai_mtd=spend.month_to_date(conn), ai_cap=config.get_config().ai_monthly_cap_usd)

    @app.post("/agents/{name}/dry-run")
    def toggle_dry_run(name: str, user: str = Depends(require_user), conn=Depends(conn_dep), state: str = Form(...)):
        if name not in settings.AGENTS_WITH_DRY_RUN:
            raise HTTPException(404)
        settings.set_dry_run(conn, name, state != "off")
        return RedirectResponse("/agents", status_code=303)

    @app.post("/errors/{eid}/ack")
    def ack_error(eid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        conn.execute("UPDATE errors SET alerted=1 WHERE id=?", (eid,))
        return RedirectResponse("/agents", status_code=303)

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
                        f("ALERT_EMAIL", "Alerts and the daily summary go to")]},
            {"title": "Google Drive", "note": "From this company's own Google Cloud project. Read only.",
             "fields": [f("GOOGLE_OAUTH_CLIENT_ID", "OAuth client id"), f("GOOGLE_OAUTH_CLIENT_SECRET", "OAuth client secret", secret=True),
                        f("CREDITS_SHEET_ID", "Credits sheet (link or id)")]},
            {"title": "Mail", "note": "The company mailbox. An app password, never the account password.",
             "fields": [f("SMTP_HOST", "Mail server"), f("SMTP_USER", "Mailbox login"), f("SMTP_PASSWORD", "App password", secret=True)]},
            {"title": "AI", "note": "This company's own Anthropic key.",
             "fields": [f("ANTHROPIC_API_KEY", "Anthropic API key", secret=True), f("AI_MONTHLY_CAP_USD", "Monthly cap, USD")]},
            {"title": "Buffer", "note": "This company's own Buffer account.",
             "fields": [f("BUFFER_API_KEY", "Buffer API key", secret=True), f("BUFFER_PLAN", "Buffer plan", choices=["free", "essentials", "team"]),
                        f("PINTEREST_BOARD_ID", "Pinterest board id")]},
            {"title": "Image hosting", "note": "Where Buffer fetches post images from.",
             "fields": [f("MEDIA_BASE_URL", "Image address"), f("MEDIA_UPLOAD_TOKEN", "Upload token", secret=True)]},
            {"title": "Phone alerts", "note": "This company's own ntfy topic.", "fields": [f("NTFY_TOPIC", "ntfy topic")]},
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
