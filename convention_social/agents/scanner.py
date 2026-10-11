"""Scanner agent: keep the library inventory current, sort new photos, sync credits.

Each run (hourly): sign in (read only), then the full inventory the first
time and once a week, the Changes API otherwise; the free folder pass on any
new photo; the sort pass (Ollama on the Mini, free, else Claude under the
spend cap) on up to CLASSIFY_PER_RUN photos; the credits sheet when CREDITS_SHEET_ID is set. A dead sign-in is
recorded for the watchdog and ends the run cleanly.

The scanner only reads. Dry run changes nothing about that; it only skips
the paid Claude sort; the free Ollama sort runs either way.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..core import config, runner, settings
from ..drive import oauth, scan
from ..drive.api import DriveReader
from ..library import classify, credits, report

FULL_EVERY = timedelta(days=7)


def needs_full(conn) -> bool:
    at = settings.get(conn, scan.INVENTORY_AT_KEY)
    if not at or not settings.get(conn, scan.CHANGES_TOKEN_KEY):
        return True
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(at) > FULL_EVERY
    except ValueError:
        return True


def run(ctx: runner.Context, reader: DriveReader | None = None) -> str:
    if reader is None:
        try:
            oauth.access_token(ctx.conn)   # fail the run now if the sign-in is dead, not photo by photo
        except oauth.DriveAuthError as e:
            runner.record_error_once(ctx.conn, ctx.agent, "drive_auth", str(e))
            return f"not signed in: {e}"
        reader = DriveReader(lambda: oauth.access_token(ctx.conn), conn=ctx.conn, agent=ctx.agent)
    full = needs_full(ctx.conn)
    stats = scan.full_inventory(ctx.conn, reader) if full else scan.incremental(ctx.conn, reader)
    sorted_free = classify.folder_pass(ctx.conn)
    vision = classify.PassStats(stopped="dry run")
    sorter = classify.pick_sorter(ctx.conn, agent=ctx.agent)
    if sorter is not None and (not ctx.dry_run or not sorter.paid()):   # the free local sort runs even in dry run
        limit = int(config.getenv("CLASSIFY_PER_RUN", "500" if not sorter.paid() else "200") or 200)
        vision = classify.sort_pass(ctx.conn, reader.thumbnail_for, limit=limit, sorter=sorter, log=ctx.log)
    report_note = refresh_report(ctx.conn, reader, changed=full or vision.done > 0, log=ctx.log)
    sheet = config.getenv("CREDITS_SHEET_ID", "")
    credit_note = "credits: no sheet set"
    if sheet:
        res = credits.sync(ctx.conn, reader.export_csv(sheet))
        credit_note = f"credits: {res.matched}/{res.rows} matched"
        if res.unmatched:
            settings.set(ctx.conn, "credits.unmatched", "; ".join(res.unmatched)[:2000])
    return (f"{'full' if full else 'changes'}: {stats.line()}; folder-sorted {sorted_free}; "
            f"vision {vision.done} done {vision.failed} failed{(' (' + vision.stopped + ')') if vision.stopped else ''}; "
            f"{report_note}; {credit_note}")


def refresh_report(conn, reader: DriveReader, *, changed: bool, log=None) -> str:
    """The library report and both contact sheets, remade after a pass that found or sorted
    something (or when today has none yet), so Chris sees them on the dashboard's Library page
    without running a command. A failure here never fails the scan."""
    renders = config.get_config().data_root / "renders"
    if not changed and (renders / f"library-report-{datetime.now():%Y%m%d}.html").exists():
        return "report: up to date"
    try:
        sheet = report.write_contact_sheet(conn, reader.thumbnail_for, n=30) if report.best(conn, 1) else None
        if report.best(conn, 1, subject="architecture"):
            report.write_contact_sheet(conn, reader.thumbnail_for, n=30, subject="architecture")
        return f"report: {report.write_report(conn, sheet=sheet).name}"
    except Exception as e:  # noqa: BLE001 — the inventory and the sort already landed
        if log is not None:
            log.warning("library report not made: %s: %s", type(e).__name__, e)
        return f"report: not made ({type(e).__name__})"


if __name__ == "__main__":
    runner.main_for("scanner", run)
