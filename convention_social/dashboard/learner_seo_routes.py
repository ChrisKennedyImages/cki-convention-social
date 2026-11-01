"""Dashboard pages for the learner and the SEO agent. app.py calls register() once.

GET  /learner          the posting times in use and suggested, photo weights, the note, the history
GET  /seo              search text per photo (alt text editable) and the latest site check
POST /seo/{photo_id}   Chris corrects the alt text (and title or description); the same hard rules
                       apply, and the agent never rewrites a row he corrected
GET  /seo/changes      the search changes (seo/changes.py, 2026-11-01): each proposal's words before and after, why, its
                       searches, Approve and Skip; what is live and being measured; what was kept or put back
POST /seo/changes/{id}/approve | /skip                   his decision on the page
GET  /seo/changes/{id}/by-token/{approve|skip}           from the ping, a page with the buttons; decides nothing
POST /seo/changes/{id}/by-token/{approve|skip}           the ping's one tap: the signed single-use token in the body
"""
from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..agents import learner
from ..core import db, settings
from ..seo import changes, photo_text, site_check
from .team_routes import token_of

SEO_ROWS = 300
CHOICES = {"approve": "Approve", "skip": "Skip"}


def seo_rows(conn) -> list[dict]:
    rows = db.rows(conn, "SELECT s.*, p.name AS photo_name, c.subject, c.shot_type FROM photo_seo s "
                         "JOIN photos p ON p.id = s.photo_id LEFT JOIN classifications c ON c.photo_id = s.photo_id "
                         "ORDER BY s.edited_at IS NOT NULL, s.written_at DESC, s.photo_id DESC LIMIT ?", (SEO_ROWS,))
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["keywords"] = json.loads(r["keywords"] or "[]")
        except ValueError:
            d["keywords"] = []
        out.append(d)
    return out


def register(app, require_user, conn_dep, render) -> None:
    @app.get("/learner", response_class=HTMLResponse)
    def learner_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        return render(request, "learner_index.html", **learner.dashboard_view(conn))

    @app.get("/seo", response_class=HTMLResponse)
    def seo_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = "", why: str = ""):
        return render(request, "seo_index.html", rows=seo_rows(conn), check=site_check.latest(conn), msg=msg, why=why,
                      alt_max=photo_text.ALT_MAX, dry_run=settings.dry_run(conn, "seo"), waiting=changes.waiting(conn))

    @app.get("/seo/changes", response_class=HTMLResponse)
    def seo_changes_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep), msg: str = "", bad: str = ""):
        return render(request, "seo_changes.html", items=changes.view(conn), msg=msg, bad=bad,
                      dry_run=settings.dry_run(conn, "seo"))

    @app.post("/seo/changes/{cid}/{how}")
    def seo_change_decide(cid: int, how: str, user: str = Depends(require_user), conn=Depends(conn_dep)):
        if how not in CHOICES:
            raise HTTPException(404)
        ok, words = changes.approve(conn, cid) if how == "approve" else changes.skip(conn, cid)
        return RedirectResponse(f"/seo/changes?{'msg' if ok else 'bad'}={quote(words)}#c{cid}", status_code=303)

    @app.get("/seo/changes/{cid}/by-token/{how}", response_class=HTMLResponse)
    def seo_change_token_page(cid: int, how: str, request: Request, conn=Depends(conn_dep), token: str = ""):
        """A GET never decides anything (a link preview, a browser prefetch): the change and its two buttons."""
        row = changes.get(conn, cid)
        if row is None or how not in CHOICES:
            raise HTTPException(404)
        return render(request, "seo_change_token.html", c=changes.describe(row), token=token, how=how, choices=CHOICES)

    @app.post("/seo/changes/{cid}/by-token/{how}")
    async def seo_change_by_token(cid: int, how: str, request: Request, conn=Depends(conn_dep)):
        """Approve or Skip from the ping (Chris, 2026-11-01: "One tap from my phone"): the signed, single-use token in the
        body; the answer is a sentence for the phone."""
        if how not in CHOICES or changes.get(conn, cid) is None:
            raise HTTPException(404)
        ok, words = changes.decide_by_token(conn, cid, await token_of(request), how)
        return PlainTextResponse(words, status_code=200 if ok else 409)

    @app.post("/seo/{photo_id}")
    def seo_edit(photo_id: int, user: str = Depends(require_user), conn=Depends(conn_dep), alt: str = Form(...),
                 title: str = Form(default=""), description: str = Form(default="")):
        if db.one(conn, "SELECT 1 FROM photo_seo WHERE photo_id=?", (photo_id,)) is None:
            raise HTTPException(404)
        why = photo_text.edit(conn, photo_id, alt=alt, title=title, description=description)
        if why:
            return RedirectResponse(f"/seo?msg=refused&why={quote(why)}#p{photo_id}", status_code=303)
        return RedirectResponse(f"/seo?msg=saved#p{photo_id}", status_code=303)
