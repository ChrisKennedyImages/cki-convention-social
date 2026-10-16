"""Dashboard pages for Chris's photographers (2026-10-15, agents/team.py). app.py calls `register(app, require_user, conn_dep,
render)`.

The Team page (beside Keys): add a photographer by first name, switch one off, make a new token or a one-time phone
link; a token or a link is shown once, on the answer itself, never in an address a log keeps. A team photo's
Approve and Skip are the drafts' own choice route (app.py choose-by-token). Also post to the feed, from the Story's ping
(a POST with its signed single-use token; a GET decides nothing) and from the draft page.
"""
from __future__ import annotations

from urllib.parse import parse_qs, quote_plus

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..agents import team
from ..core import approve_token, db


def _row(conn, qid: int):
    row = db.one(conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
    if row is None:
        raise HTTPException(404)
    return row


async def _token(request: Request) -> str:
    raw = (await request.body()).decode("utf-8", "replace")
    return (parse_qs(raw).get("token") or [raw.strip()])[0]


def _feed_word(why: str) -> str:
    return "feed_full" if "feed posts" in why else "feed_dup" if "already" in why else "feed_no"


def register(app, require_user, conn_dep, render) -> None:
    def page(request, conn, **extra):
        return render(request, "team.html", members=team.members(conn), shortcut_link=team.shortcut_link(conn),
                      msg=extra.pop("msg", request.query_params.get("msg", "")), **extra)

    @app.get("/team", response_class=HTMLResponse)
    def team_page(request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        return page(request, conn)

    @app.post("/team/add", response_class=HTMLResponse)
    def team_add(request: Request, name: str = Form(""), user: str = Depends(require_user), conn=Depends(conn_dep)):
        try:
            mid, token = team.add(conn, name)
        except team.Refused as e:
            return page(request, conn, msg=f"Not added: {e}")
        ok, why = team.push(conn)
        return page(request, conn, new_token=token, who=team.name_of(conn, mid),
                    msg="" if ok else f"Added, but the token is {why}. It works once the site has the list.")

    @app.post("/team/{mid}/active")
    def team_active(mid: int, active: str = Form("0"), user: str = Depends(require_user), conn=Depends(conn_dep)):
        ok, why = team.set_active(conn, mid, active == "1")
        return RedirectResponse("/team?msg=" + quote_plus(("Switched on." if active == "1" else "Switched off: their sends are refused.")
                                                          + ("" if ok else f" The site does not know yet: {why}.")), status_code=303)

    @app.post("/team/{mid}/token", response_class=HTMLResponse)
    def team_token(mid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        token = team.new_token(conn, mid)
        return page(request, conn, new_token=token, who=team.name_of(conn, mid), msg="A new token: the old one stops working.")

    @app.post("/team/{mid}/link", response_class=HTMLResponse)
    def team_link(mid: int, request: Request, user: str = Depends(require_user), conn=Depends(conn_dep)):
        return page(request, conn, new_link=team.phone_link(conn, mid), who=team.name_of(conn, mid))

    @app.post("/team/shortcut-link")
    def team_shortcut(link: str = Form(""), user: str = Depends(require_user), conn=Depends(conn_dep)):
        try:
            team.set_shortcut_link(conn, link)
        except team.Refused as e:
            return RedirectResponse("/team?msg=" + quote_plus(f"Not saved: {e}"), status_code=303)
        return RedirectResponse("/team?msg=" + quote_plus("Saved: it is shown with every new token."), status_code=303)

    # ------------------------------------------------------------------ the ping's one-tap buttons

    @app.post("/queue/{qid}/feed-by-token")
    async def feed_by_token(qid: int, request: Request, conn=Depends(conn_dep)):
        row = _row(conn, qid)
        ok, why = approve_token.check(conn, row, await _token(request))
        if not ok:
            return PlainTextResponse(why, status_code=409)
        new, why = team.also_feed(conn, qid)
        if new is None:
            return PlainTextResponse(f"Not posted to the feed: {why}.", status_code=409)
        approve_token.spend(conn, qid)
        return PlainTextResponse(f"Going to the feed now, as post {new}.")

    @app.post("/queue/{qid}/feed")
    def feed(qid: int, user: str = Depends(require_user), conn=Depends(conn_dep)):
        _row(conn, qid)
        new, why = team.also_feed(conn, qid)
        if new is None:
            return RedirectResponse(f"/queue/{qid}?msg={_feed_word(why)}", status_code=303)
        return RedirectResponse(f"/queue/{new}?msg=feed", status_code=303)
