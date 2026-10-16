"""Dashboard pages for Chris's photographers (2026-10-15, agents/team.py). app.py calls `register(app, require_user, conn_dep,
render)`.

The Team page (beside Keys): add a photographer by first name, switch one off, make a new token or a one-time phone
link; a token or a link is shown once, on the answer itself, never in an address a log keeps. The ping's one-tap
buttons: Approve and Skip for a photo from the team, Also post to the feed for an instant photo's Story; each is a POST
with the ping's signed single-use token (core/approve_token), and a GET approves nothing. The draft page's own Also
post to the feed.
"""
from __future__ import annotations

import json
import logging
from urllib.parse import parse_qs, quote_plus

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from ..agents import publisher, team
from ..core import approve_token, config, db, runner, settings


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

    @app.post("/queue/{qid}/team-approve-by-token")
    async def team_approve(qid: int, request: Request, conn=Depends(conn_dep)):
        """Approve on a team photo's ping: the same door as his own sends (the captions, one rewrite; the photo; a
        repeat) and the day's cap, then it goes out as a Story right away."""
        row = _row(conn, qid)
        ok, why = approve_token.check(conn, row, await _token(request))
        if not ok:
            return PlainTextResponse(why, status_code=409)
        if row["status"] != "draft":
            return PlainTextResponse(f"Post {qid} is {row['status'].replace('_', ' ')}; nothing to approve.", status_code=409)
        if publisher.instant_format(row) != "story":
            return PlainTextResponse("Only a photo from the team is approved here. Open the draft.", status_code=409)
        room, why = team.room_for(conn, "story")
        if not room:
            conn.execute("UPDATE content_queue SET last_error=?, updated_at=? WHERE id=?", (why, db.utcnow(), qid))
            return PlainTextResponse(f"Not approved: {why}.", status_code=409)
        ctx = runner.Context("dashboard", conn, logging.getLogger("dashboard"), config.get_config(), settings.dry_run(conn, "content"), 0)
        stop, row = publisher.check_in(ctx, row)
        if stop:
            conn.execute("UPDATE content_queue SET last_error=?, updated_at=? WHERE id=?", (stop[1], db.utcnow(), qid))
            return PlainTextResponse(f"Not approved: {stop[1]}", status_code=409)
        meta = json.loads(row["rule_report"] or "{}")
        meta["approved_by"] = "chris"
        now = db.utcnow()
        conn.execute("UPDATE content_queue SET status='approved', approved_at=?, last_error=NULL, rule_report=?, updated_at=? WHERE id=?",
                     (now, json.dumps(meta), now, qid))
        approve_token.spend(conn, qid)
        runner.start_agent("publisher", wait=True)
        return PlainTextResponse(f"Approved post {qid}. It goes out as an Instagram Story now.")

    @app.post("/queue/{qid}/skip-by-token")
    async def team_skip(qid: int, request: Request, conn=Depends(conn_dep)):
        row = _row(conn, qid)
        ok, why = approve_token.check(conn, row, await _token(request))
        if not ok:
            return PlainTextResponse(why, status_code=409)
        if row["status"] != "draft":
            return PlainTextResponse(f"Post {qid} is {row['status'].replace('_', ' ')}; nothing to skip.", status_code=409)
        conn.execute("UPDATE content_queue SET status='rejected', last_error=?, updated_at=? WHERE id=?",
                     ("Skipped by you. It does not go out.", db.utcnow(), qid))
        approve_token.spend(conn, qid)
        return PlainTextResponse(f"Skipped post {qid}. It does not go out.")

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
