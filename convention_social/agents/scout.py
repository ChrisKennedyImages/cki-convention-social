"""Scout agent (weekly, Sunday 07:00): upcoming conventions and conferences for Chris to consider.

1. Reads the region from SCOUT_REGION (free text, set on the Keys page) and
   the horizon from SCOUT_MONTHS (default 9). With no region it does nothing
   and says so.
2. Live only: one Claude research call with web search (outreach/research.py),
   under the monthly AI cap. Research has no outward effect but it costs
   money, so a dry run makes no call and only says what it would search.
3. Keeps only what a source backs (research.vet: no source URL, no row; an
   organizer email only when printed on the event's own site; dates only
   when real) and stores each event once in scout_events (status new),
   de-duplicated by normalized name and start date, and skipping anything
   already on the calendar.
Nothing reaches the calendar until Chris presses "Add to calendar" on the
dashboard's Scout page, and then with attending and official unticked.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..ai import spend
from ..core import config, db, runner, secrets
from ..outreach import keys, research

DEFAULT_MONTHS = 9


def region() -> str:
    return (config.getenv("SCOUT_REGION") or "").strip()


def months() -> int:
    try:
        n = int(config.getenv("SCOUT_MONTHS") or DEFAULT_MONTHS)
    except ValueError:
        n = DEFAULT_MONTHS
    return min(max(n, 1), 24)


def local_today(cfg: config.Config) -> date:
    try:
        return datetime.now(ZoneInfo(cfg.timezone)).date()
    except Exception:  # noqa: BLE001 — a bad TIMEZONE setting must not stop the run
        return datetime.now().date()


def horizon(today: date, n_months: int) -> date:
    month = today.month - 1 + n_months
    year, month = today.year + month // 12, month % 12 + 1
    for day in (today.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return today + timedelta(days=30 * n_months)


def known_names(conn) -> list[str]:
    names = [r["name"] for r in db.rows(conn, "SELECT name FROM scout_events ORDER BY id DESC LIMIT 200")]
    names += [r["name"] for r in db.rows(conn, "SELECT name FROM conventions ORDER BY id DESC LIMIT 200")]
    out: list[str] = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def on_calendar(conn) -> set[tuple[str, str]]:
    """(name key, start date or '') of every calendar event."""
    return {(keys.name_key(r["name"]), r["start_date"] or "") for r in db.rows(conn, "SELECT name, start_date FROM conventions")}


def store(conn, ev: dict, model: str, calendar: set[tuple[str, str]]) -> bool:
    """Insert one vetted event; False when it is already known (here or on the calendar)."""
    nk = keys.name_key(ev["name"])
    start = ev.get("start_date") or ""
    if not nk or (nk, start) in calendar or (not start and any(k == nk for k, _ in calendar)):
        return False
    key = keys.event_key(ev["name"], start)
    if db.one(conn, "SELECT 1 FROM scout_events WHERE dedup_key=?", (key,)):
        return False
    if not start and db.one(conn, "SELECT 1 FROM scout_events WHERE name_key=?", (nk,)):
        return False            # the same event without a date adds nothing to the one already here
    now = db.utcnow()
    db.insert(conn, "scout_events", dedup_key=key, name_key=nk, name=ev["name"], kind=ev["kind"],
              start_date=ev.get("start_date") or None, end_date=ev.get("end_date") or None,
              city=ev.get("city") or None, venue=ev.get("venue") or None, website=ev.get("website") or None,
              organizer=ev.get("organizer") or None, organizer_email=ev.get("organizer_email") or None,
              email_source_url=ev.get("email_source_url") or None, sources=json.dumps(ev["sources"]),
              status="new", model=model, found_at=now, updated_at=now)
    return True


def run(ctx: runner.Context, client=None) -> str:
    where = region()
    if not where:
        return "SCOUT_REGION is not set: add the region to search (for example Washington DC, Maryland, Virginia) on the Keys page. Nothing searched."
    today = local_today(ctx.cfg)
    until = horizon(today, months())
    plan = f"{where}, events starting {today.isoformat()} to {until.isoformat()}"
    if ctx.dry_run:
        return f"DRY RUN: would search {plan}. A dry run makes no paid research call; switch scout to live on the Agents page."
    if (config.getenv("AI_MODEL") or "").lower() == "template":
        return f"AI_MODEL=template: no research for {plan}."
    if client is None and not secrets.get_secret("ANTHROPIC_API_KEY"):
        return f"no ANTHROPIC_API_KEY: nothing searched for {plan}."
    if spend.cap_reached(ctx.conn):
        return f"monthly AI cap reached: nothing searched for {plan}."
    if client is None:
        import anthropic
        client = anthropic.Anthropic(api_key=secrets.get_secret("ANTHROPIC_API_KEY"))
    res = research.research(ctx.conn, client, region=where, today=today, horizon=until, known=known_names(ctx.conn),
                            agent=ctx.agent)
    if res.search_errors:
        runner.record_error(ctx.conn, ctx.agent, "web_search", "web search returned errors: " + ", ".join(res.search_errors[:5]))
    if res.refused:
        return f"the model declined the research for {plan}; nothing stored ({res.calls} call(s), {res.searches} search(es))."
    kept, dropped = research.vet(res, today=today, horizon=until)
    calendar = on_calendar(ctx.conn)
    new = sum(1 for ev in kept if store(ctx.conn, ev, res.model, calendar))
    with_email = sum(1 for ev in kept if ev["organizer_email"])
    gone = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in dropped.items() if v) or "none"
    notes = [n for n in (res.stopped, "structured by a second call" if res.structured else "",
                         "no source URLs came back from the searches" if not res.seen else "") if n]
    ctx.log.info("scout: %d candidates, %d kept, %d new, seen %d urls", len(res.candidates), len(kept), new, len(res.seen))
    return (f"searched {plan}: {res.searches} search(es) in {res.calls} call(s); {len(res.candidates)} found, "
            f"{len(kept)} backed by a source ({with_email} with an organizer email), {new} new; dropped: {gone}"
            + (f"; {'; '.join(notes)}" if notes else ""))


if __name__ == "__main__":
    runner.main_for("scout", run)
