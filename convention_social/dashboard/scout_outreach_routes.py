"""Dashboard pages for the scout and outreach. app.py calls `register(app, require_user, conn_dep, render)`.

Scout: what the weekly scout found; "Add to calendar" puts an event on the
calendar with attending and official unticked (Chris ticks attending himself;
official only on his word), "Dismiss" hides it for good.

Outreach: drafts, approved, sent. Chris edits a note, then Approves or
Rejects it; Approve is refused while outreach.compliance finds a problem.
Editing an approved note sends it back to draft. The one follow-up can be
started only 7 days or more after the first note was really sent. Do not
contact: the list every draft and every send is checked against.
"""
from __future__ import annotations

import json

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..agents import outreach as outreach_agent
from ..agents import scout as scout_agent
from ..core import config, db
from ..outreach import compliance, draft, keys

EDITABLE = ("queued", "draft", "approved", "would_send", "failed")
APPROVABLE = ("draft", "would_send", "failed")
CALENDAR_KIND = {"fan": "fan", "business": "business", "other": "unknown"}     # conventions.kind has no 'other'


def _see(url: str, status: int = 303) -> RedirectResponse:
    return RedirectResponse(url, status_code=status)


def register(app, require_user, conn_dep, render) -> None:
    # ------------------------------------------------------------------ scout
    @app.get("/scout", response_class=HTMLResponse)
    def scout_list(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), show: str = "new", msg: str = ""):
        show = show if show in ("new", "added", "dismissed", "all") else "new"
        where, params = ("1=1", ()) if show == "all" else ("status=?", (show,))
        rows = db.rows(conn, f"SELECT * FROM scout_events WHERE {where} ORDER BY COALESCE(start_date,'9999'), id LIMIT 300", params)
        items = [{**dict(r), "source_list": json.loads(r["sources"] or "[]"),
                  "dates": keys.dates_in_words(r["start_date"], r["end_date"])} for r in rows]
        counts = {r["status"]: r["n"] for r in db.rows(conn, "SELECT status, COUNT(*) n FROM scout_events GROUP BY status")}
        last = db.one(conn, "SELECT * FROM agent_runs WHERE agent='scout' ORDER BY id DESC LIMIT 1")
        return render(request, "scout_list.html", items=items, show=show, counts=counts, msg=msg,
                      region=scout_agent.region(), months=scout_agent.months(), last=dict(last) if last else None)

    def load_scout(conn, sid: int):
        row = db.one(conn, "SELECT * FROM scout_events WHERE id=?", (sid,))
        if row is None:
            raise HTTPException(404)
        return row

    @app.post("/scout/{sid}/add")
    def scout_add(sid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_scout(conn, sid)
        if row["status"] == "added" and row["convention_id"]:
            return _see("/scout?msg=already")
        now = db.utcnow()
        sources = json.loads(row["sources"] or "[]")
        notes = "Found by the scout. Sources: " + " ".join(sources) if sources else "Found by the scout."
        cid = db.insert(conn, "conventions", name=row["name"], kind=CALENDAR_KIND.get(row["kind"], "unknown"),
                        start_date=row["start_date"], end_date=row["end_date"], city=row["city"], venue=row["venue"],
                        attending=0, official=0, url=row["website"], notes=notes[:1000], created_at=now, updated_at=now)
        conn.execute("UPDATE scout_events SET status='added', convention_id=?, updated_at=? WHERE id=?", (cid, now, sid))
        return _see("/scout?msg=added")

    @app.post("/scout/{sid}/dismiss")
    def scout_dismiss(sid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        load_scout(conn, sid)
        conn.execute("UPDATE scout_events SET status='dismissed', updated_at=? WHERE id=?", (db.utcnow(), sid))
        return _see("/scout?msg=dismissed")

    # ------------------------------------------------------------------ do not contact (before /outreach/{oid})
    @app.get("/outreach/donotcontact", response_class=HTMLResponse)
    def dnc_list(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        rows = db.rows(conn, "SELECT * FROM do_not_contact ORDER BY id DESC LIMIT 1000")
        return render(request, "outreach_donotcontact.html", rows=rows, msg=msg)

    @app.post("/outreach/donotcontact/add")
    def dnc_add(user: str = Depends(require_user), conn=Depends(conn_dep), email: str = Form(...), reason: str = Form(default=""),
                source: str = Form(default="manual")):
        email = keys.normalize_email(email)
        if not keys.valid_email(email):
            return _see("/outreach/donotcontact?msg=bad_email")
        compliance.block(conn, email, source=source if source in ("manual", "reply", "bounce") else "manual", reason=reason.strip())
        return _see("/outreach/donotcontact?msg=added")

    @app.post("/outreach/donotcontact/{rid}/remove")
    def dnc_remove(rid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        conn.execute("DELETE FROM do_not_contact WHERE id=?", (rid,))
        return _see("/outreach/donotcontact?msg=removed")

    # ------------------------------------------------------------------ outreach
    @app.post("/outreach/add")
    def outreach_add(user: str = Depends(require_user), conn=Depends(conn_dep), event_name: str = Form(...), email: str = Form(...),
                     organizer: str = Form(default=""), kind: str = Form(default="other"), start_date: str = Form(default=""),
                     end_date: str = Form(default=""), city: str = Form(default=""), venue: str = Form(default=""),
                     website: str = Form(default="")):
        name, email = event_name.strip()[:200], keys.normalize_email(email)
        if not name or not keys.valid_email(email):
            return _see("/outreach?msg=bad_prospect")
        if compliance.blocked(conn, email):
            return _see("/outreach?msg=blocked")
        start = keys.iso_day(start_date)
        key = keys.event_key(name, start)
        if db.one(conn, "SELECT 1 FROM outreach WHERE email=? AND event_key=? AND kind='first'", (email, key)):
            return _see("/outreach?msg=exists")
        now = db.utcnow()
        db.insert(conn, "outreach", kind="first", event_key=key, event_name=name,
                  event_kind=kind if kind in ("fan", "business", "other") else "other", start_date=start,
                  end_date=keys.iso_day(end_date), city=city.strip()[:120] or None, venue=venue.strip()[:200] or None,
                  website=website.strip()[:500] or None, organizer=organizer.strip()[:160] or None, email=email,
                  status="queued", token=keys.new_token(), notes="Added by hand; drafted on the next outreach run.",
                  created_at=now, updated_at=now)
        return _see("/outreach?msg=queued")

    @app.get("/outreach", response_class=HTMLResponse)
    def outreach_list(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        def group(statuses):
            marks = ",".join("?" for _ in statuses)
            return db.rows(conn, f"SELECT * FROM outreach WHERE status IN ({marks}) ORDER BY id DESC LIMIT 100", statuses)
        cfg = config.get_config()
        cfg_ok = {"sender": compliance.sender_ok(cfg), "address": bool(cfg.brand_postal_address.strip()),
                  "from": cfg.brand_from_email, "domain": cfg.brand_domain}
        return render(request, "outreach_list.html", msg=msg, cfg_ok=cfg_ok, daily_drafts=outreach_agent.daily_drafts(),
                      drafts=group(("queued", "draft")), approved=group(("approved",)),
                      sent=group(("sent", "would_send", "failed")), closed=group(("rejected", "opted_out")))

    def load_row(conn, oid: int):
        row = db.one(conn, "SELECT * FROM outreach WHERE id=?", (oid,))
        if row is None:
            raise HTTPException(404)
        return row

    @app.get("/outreach/{oid}", response_class=HTMLResponse)
    def outreach_detail(oid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = ""):
        row = load_row(conn, oid)
        found = compliance.problems(conn, row) if row["status"] in EDITABLE else []
        built = compliance.build(row)
        scout_row = db.one(conn, "SELECT * FROM scout_events WHERE id=?", (row["scout_event_id"],)) if row["scout_event_id"] else None
        follow_up = db.one(conn, "SELECT id, status FROM outreach WHERE parent_id=? AND kind='follow_up'", (oid,))
        follow_up_why = compliance.follow_up_allowed(conn, row) if row["kind"] == "first" and row["status"] == "sent" else None
        return render(request, "outreach_detail.html", row=row, msg=msg, problems=found, built=built,
                      footer="\n".join(compliance.footer_lines(row["token"])),
                      blocking=[p for p in found if p.code != "follow_up_wait"],
                      scout=dict(scout_row) if scout_row else None,
                      sources=json.loads(scout_row["sources"] or "[]") if scout_row else [],
                      dates=keys.dates_in_words(row["start_date"], row["end_date"]),
                      follow_up=follow_up, follow_up_why=follow_up_why, editable=row["status"] in EDITABLE,
                      approvable=row["status"] in APPROVABLE)

    @app.post("/outreach/{oid}/save")
    def outreach_save(oid: int, user: str = Depends(require_user), conn=Depends(conn_dep), subject: str = Form(""), body: str = Form("")):
        row = load_row(conn, oid)
        if row["status"] not in EDITABLE:
            return _see(f"/outreach/{oid}?msg=locked")
        # any edit needs a fresh Approve; a queued prospect Chris wrote himself is a draft the agent leaves alone
        model = "chris" if row["status"] == "queued" else row["model"]
        conn.execute("UPDATE outreach SET subject=?, body=?, status='draft', model=?, approved_at=NULL, updated_at=? WHERE id=?",
                     (subject.strip(), body.replace("\r\n", "\n").strip(), model, db.utcnow(), oid))
        return _see(f"/outreach/{oid}?msg=saved")

    @app.post("/outreach/{oid}/approve")
    def outreach_approve(oid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_row(conn, oid)
        if row["status"] not in APPROVABLE:
            return _see(f"/outreach/{oid}")
        if [p for p in compliance.problems(conn, row) if p.code != "follow_up_wait"]:
            return _see(f"/outreach/{oid}?msg=not_ready")
        now = db.utcnow()
        conn.execute("UPDATE outreach SET status='approved', approved_at=?, notes=NULL, updated_at=? WHERE id=?", (now, now, oid))
        return _see(f"/outreach/{oid}?msg=approved")

    @app.post("/outreach/{oid}/reject")
    def outreach_reject(oid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_row(conn, oid)
        if row["status"] in EDITABLE:
            conn.execute("UPDATE outreach SET status='rejected', updated_at=? WHERE id=?", (db.utcnow(), oid))
        return _see("/outreach?msg=rejected")

    @app.post("/outreach/{oid}/followup")
    def outreach_follow_up(oid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        row = load_row(conn, oid)
        if compliance.follow_up_allowed(conn, row):
            return _see(f"/outreach/{oid}?msg=no_follow_up")
        d = draft.template_follow_up(row)
        now = db.utcnow()
        fid = db.insert(conn, "outreach", kind="follow_up", parent_id=oid, scout_event_id=row["scout_event_id"],
                        event_key=row["event_key"], event_name=row["event_name"], event_kind=row["event_kind"],
                        start_date=row["start_date"], end_date=row["end_date"], city=row["city"], venue=row["venue"],
                        website=row["website"], organizer=row["organizer"], email=row["email"], subject=d.subject, body=d.body,
                        status="draft", token=keys.new_token(), model=d.model, drafted_at=now, created_at=now, updated_at=now)
        return _see(f"/outreach/{fid}?msg=follow_up")
