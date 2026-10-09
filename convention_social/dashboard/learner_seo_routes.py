"""Dashboard pages for the learner and the SEO agent. app.py calls register() once.

GET  /learner          the posting times in use and suggested, photo weights, the note, the history
GET  /seo              search text per photo (alt text editable) and the latest site check
POST /seo/{photo_id}   Chris corrects the alt text (and title or description); the same hard rules
                       apply, and the agent never rewrites a row he corrected
"""
from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..agents import learner
from ..core import db, settings
from ..seo import photo_text, site_check

SEO_ROWS = 300


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
                      alt_max=photo_text.ALT_MAX, dry_run=settings.dry_run(conn, "seo"))

    @app.post("/seo/{photo_id}")
    def seo_edit(photo_id: int, user: str = Depends(require_user), conn=Depends(conn_dep), alt: str = Form(...),
                 title: str = Form(default=""), description: str = Form(default="")):
        if db.one(conn, "SELECT 1 FROM photo_seo WHERE photo_id=?", (photo_id,)) is None:
            raise HTTPException(404)
        why = photo_text.edit(conn, photo_id, alt=alt, title=title, description=description)
        if why:
            return RedirectResponse(f"/seo?msg=refused&why={quote(why)}#p{photo_id}", status_code=303)
        return RedirectResponse(f"/seo?msg=saved#p{photo_id}", status_code=303)
