"""`bin/ccs`: the operator's command line.

  ccs init-db                 create/upgrade the database under DATA_ROOT
  ccs status                  agents, schedules, dry-run flags, last run, open errors
  ccs env-check               which secrets and settings resolve (values never shown)
  ccs dry-run <agent> on|off  flip an agent's dry-run flag (default is on)
  ccs settings [--set K V]    list or set a raw setting
  ccs run <agent> [--dry-run|--live]   run one agent once (flag overrides the setting)
  ccs hash-password           read a password from the terminal, print the hash for .env
  ccs dashboard               serve the review dashboard on 127.0.0.1:DASHBOARD_PORT
  ccs launchd status          which launchd services of this suite are loaded
  ccs drive login [--wait N]  sign in to Google Drive as Chris, read only
  ccs drive scan [--classify N]   inventory the library now; optionally sort N photos with Claude
  ccs drive report [--sheet N]    write the library report and a contact sheet of the best N
  ccs fonts                   download the brand typefaces into DATA_ROOT/fonts
  ccs samples                 render twelve sample posts and three brand boards from the best photos (for review)
"""
from __future__ import annotations

import argparse
import getpass
import importlib
import sys

from .agents import AGENTS, is_built
from .core import auth, config, db, secrets, settings

LAUNCHD_PREFIX = "com.chriskennedyimages.conventionsocial."


def cmd_init_db(_args) -> int:
    cfg = config.get_config()
    cfg.ensure_dirs()
    conn = db.connect(apply_migrations=False)
    applied = db.migrate(conn)
    print(f"database: {cfg.db_path}")
    print(f"tables:   {', '.join(db.table_names(conn))}")
    print(f"applied:  {', '.join(applied) if applied else 'nothing new'}")
    conn.close()
    return 0


def cmd_status(_args) -> int:
    cfg = config.get_config()
    if not cfg.db_path.exists():
        print(f"no database yet at {cfg.db_path}; run `ccs init-db`")
        return 1
    conn = db.connect()
    print(f"{cfg.brand_name}  data={cfg.data_root}")
    print(f"{'agent':<10} {'built':<6} {'dry_run':<8} {'last run':<26} {'ok':<4} schedule")
    for name, meta in AGENTS.items():
        last = db.one(conn, "SELECT started_at, ok FROM agent_runs WHERE agent=? ORDER BY id DESC LIMIT 1", (name,))
        dry = "on" if settings.dry_run(conn, name) else "OFF"
        if name not in settings.AGENTS_WITH_DRY_RUN:
            dry = "-"
        last_s = last["started_at"] if last else "never"
        ok_s = "" if not last else ("yes" if last["ok"] == 1 else ("no" if last["ok"] == 0 else "..."))
        print(f"{name:<10} {'yes' if is_built(name) else 'no':<6} {dry:<8} {last_s:<26} {ok_s:<4} {meta['schedule']}")
    open_errors = db.one(conn, "SELECT COUNT(*) AS n FROM errors WHERE alerted=0")["n"]
    print(f"open errors: {open_errors}")
    conn.close()
    return 0


def cmd_env_check(_args) -> int:
    cfg = config.get_config()
    print(f"env file: {config.env_file_path()} ({'present' if config.env_file_path().exists() else 'missing'})")
    print(f"data root: {cfg.data_root}")
    print(f"brand: {cfg.brand_name} <{cfg.brand_from_email or 'no sender yet'}>  postal: {'set' if cfg.brand_postal_address else 'MISSING'}")
    for name, ok in secrets.present().items():
        print(f"  {name:<28} {'set' if ok else 'missing'}")
    return 0


def cmd_dry_run(args) -> int:
    if args.agent not in settings.AGENTS_WITH_DRY_RUN:
        print(f"unknown agent {args.agent}; one of {', '.join(settings.AGENTS_WITH_DRY_RUN)}")
        return 2
    conn = db.connect()
    settings.set_dry_run(conn, args.agent, args.state == "on")
    print(f"{args.agent}.dry_run = {'on' if args.state == 'on' else 'OFF (live)'}")
    conn.close()
    return 0


def cmd_settings(args) -> int:
    conn = db.connect()
    if args.set:
        key, value = args.set
        settings.set(conn, key, value)
        print(f"{key} = {value}")
    else:
        for key, value in settings.all_settings(conn).items():
            print(f"{key} = {value}")
    conn.close()
    return 0


def cmd_run(args) -> int:
    if args.agent not in AGENTS:
        print(f"unknown agent {args.agent}")
        return 2
    if not is_built(args.agent):
        print(f"{args.agent} is not built yet")
        return 2
    module = importlib.import_module(AGENTS[args.agent]["module"])
    force = True if args.dry_run else (False if args.live else None)
    from .core import runner
    return runner.run(args.agent, module.run, force_dry_run=force)


def cmd_hash_password(_args) -> int:
    pw = getpass.getpass("dashboard password: ")
    if len(pw) < 8:
        print("use at least 8 characters")
        return 2
    print(f"DASHBOARD_PASSWORD_HASH={auth.hash_password(pw)}")
    return 0


def cmd_dashboard(_args) -> int:
    import uvicorn
    from .dashboard.app import create_app
    cfg = config.get_config()
    uvicorn.run(create_app(), host="127.0.0.1", port=cfg.dashboard_port, log_level="info")
    return 0


def cmd_launchd(_args) -> int:
    import glob
    import subprocess
    from pathlib import Path

    daemons = sorted(glob.glob(f"/Library/LaunchDaemons/{LAUNCHD_PREFIX}*.plist"))
    if not daemons:
        print("no services of this suite are installed (run scripts/install-daemons.sh on the runtime machine)")
        return 1
    for path in daemons:
        label = Path(path).stem
        r = subprocess.run(["launchctl", "print", f"system/{label}"], capture_output=True, text=True)
        state = "loaded" if r.returncode == 0 else ("not loaded" if "Could not find service" in (r.stderr + r.stdout) else "installed (sudo to read)")
        print(f"  {state:<28}{label}")
    return 0


def cmd_drive(args) -> int:
    from .drive import oauth
    from .drive.api import DriveReader
    conn = db.connect()
    try:
        if args.what == "login":
            oauth.login(conn, wait_seconds=args.wait)
            return 0
        token = oauth.access_token(conn)
        reader = DriveReader(token, conn=conn, agent="cli")
        if args.what == "scan":
            from .agents import scanner
            from .core import logs, runner
            ctx = runner.Context(agent="scanner", conn=conn, log=logs.get_logger("scanner"), cfg=config.get_config(),
                                 dry_run=True, run_id=0)
            print(scanner.run(ctx, reader=reader))
            if args.classify:
                from .library import classify
                st = classify.vision_pass(conn, reader.thumbnail, limit=args.classify, log=ctx.log)
                print(f"vision: {st.done} done, {st.failed} failed {st.stopped}")
            return 0
        if args.what == "report":
            from .library import report
            sheet = report.write_contact_sheet(conn, reader.thumbnail, n=args.sheet) if args.sheet else None
            out = report.write_report(conn, sheet=sheet)
            print(f"report: {out}")
            if sheet:
                print(f"contact sheet: {sheet}")
            return 0
    except oauth.DriveAuthError as e:
        print(str(e))
        return 2
    finally:
        conn.close()
    return 2


def cmd_fonts(_args) -> int:
    from .render import fonts
    got = fonts.fetch()
    print(f"fetched: {', '.join(got) if got else 'nothing new'} into {fonts.font_dir()}")
    return 0


def cmd_samples(_args) -> int:
    import io
    from PIL import Image
    from .ai import claude
    from .drive import oauth
    from .drive.api import DriveReader
    from .library import eligibility, report
    from .render import board
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    conn = db.connect()
    try:
        reader = DriveReader(oauth.access_token(conn), conn=conn, agent="cli")
    except oauth.DriveAuthError as e:
        print(str(e))
        return 2
    picks = [dict(r) for r in report.best(conn, 6)]
    if not picks:
        print("no sorted convention photos yet; run `ccs drive scan --classify 300` first")
        return 2
    cache = config.get_config().data_root / "photos"
    cache.mkdir(parents=True, exist_ok=True)

    def fetch(row):
        path = cache / f"{row['drive_id']}.img"
        if not path.exists():
            path.write_bytes(reader.download(row["drive_id"]))
        return Image.open(io.BytesIO(path.read_bytes()))

    for p in picks:
        p["credit"] = eligibility.credit_line(conn, p["id"])
    drafter = claude.get_drafter(conn, agent="cli")
    cfg = config.get_config()

    def captions(row, fmt):
        if fmt != "photo":
            return {}
        facts = claude.PostFacts(brand_name=cfg.brand_name, event_name=row.get("convention_name") or "",
                                 event_kind=row.get("event_kind") or "unknown", credit=row.get("credit", ""),
                                 shot_type=row.get("shot_type") or "", services=tuple(SERVICES_FOR_COPY))
        return drafter.draft(facts, cache / f"{row['drive_id']}.img").captions

    nxt = db.one(conn, "SELECT * FROM conventions WHERE attending=1 AND COALESCE(end_date, start_date) >= date('now') ORDER BY start_date LIMIT 1")
    when = ", ".join(x for x in ((nxt["start_date"] if nxt else ""), (nxt["city"] if nxt else "")) if x)
    out = board.samples(conn, picks, fetch, captions=captions, event=nxt["name"] if nxt else "", when=when,
                        site=cfg.brand_domain)
    print(f"samples: {out / 'index.html'}")
    conn.close()
    return 0


SERVICES_FOR_COPY = ("full event coverage", "backstage and green rooms", "breakouts", "evening events and dinners",
                     "portraits", "exhibition halls and vendors", "same day delivery of approved images")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ccs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db").set_defaults(fn=cmd_init_db)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("env-check").set_defaults(fn=cmd_env_check)
    d = sub.add_parser("dry-run"); d.add_argument("agent"); d.add_argument("state", choices=["on", "off"]); d.set_defaults(fn=cmd_dry_run)
    s = sub.add_parser("settings"); s.add_argument("--set", nargs=2, metavar=("KEY", "VALUE")); s.set_defaults(fn=cmd_settings)
    r = sub.add_parser("run"); r.add_argument("agent"); r.add_argument("--dry-run", action="store_true"); r.add_argument("--live", action="store_true"); r.set_defaults(fn=cmd_run)
    sub.add_parser("hash-password").set_defaults(fn=cmd_hash_password)
    sub.add_parser("dashboard").set_defaults(fn=cmd_dashboard)
    l = sub.add_parser("launchd"); l.add_argument("what", choices=["status"]); l.set_defaults(fn=cmd_launchd)
    dv = sub.add_parser("drive"); dv.add_argument("what", choices=["login", "scan", "report"])
    dv.add_argument("--wait", type=float, default=0, help="login: seconds to wait for the browser to return here")
    dv.add_argument("--classify", type=int, default=0, help="scan: sort this many photos with Claude (paid, under the cap)")
    dv.add_argument("--sheet", type=int, default=30, help="report: photos on the contact sheet (0 for none)")
    dv.set_defaults(fn=cmd_drive)
    sub.add_parser("fonts").set_defaults(fn=cmd_fonts)
    sub.add_parser("samples").set_defaults(fn=cmd_samples)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
