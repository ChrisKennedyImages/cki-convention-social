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
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
