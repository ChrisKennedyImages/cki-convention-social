"""`bin/ccs`: the operator's command line.

  ccs init-db                 create/upgrade the database under DATA_ROOT
  ccs status                  agents, schedules, dry-run flags, last run, open errors
  ccs env-check               which secrets and settings resolve (values never shown)
  ccs dry-run <agent> on|off  flip an agent's dry-run flag (default is on)
  ccs settings [--set K V]    list or set a raw setting
  ccs run <agent> [--dry-run|--live]   run one agent once (flag overrides the setting)
  ccs hash-password [--save]  read a password from the terminal; print the hash for .env, or save it there
  ccs dashboard               serve the review dashboard on 127.0.0.1:DASHBOARD_PORT
  ccs sync                    bring this checkout up to date with GitHub main now, tested first (go-live's first step)
  ccs launchd status          which launchd services of this suite are loaded
  ccs launchd installed       record that the services were installed from this checkout (go-live runs it)
  ccs drive login [--wait N]  sign in to Google Drive as Chris, read only
  ccs drive scan [--classify N]   inventory the library now; optionally sort N photos with Claude
  ccs drive report [--sheet N]    write the library report and a contact sheet of the best N
  ccs fonts                   download the brand typefaces into DATA_ROOT/fonts
  ccs samples                 render twelve sample posts and three brand boards from the best photos (for review)
  ccs site build [--preview]  build eventcaliber.com into site/dist from postable photos (none yet: no photos)
  ccs site check [--wait S]   check the live site and its booking API from this machine (scripts/go-live.sh runs it)
  ccs copy-key NAME --from FILE [--as OTHER]   copy one key from another .env file into this suite's .env;
                              the other file is only read, and the value is never shown
"""
from __future__ import annotations

import argparse
import json
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
    from .agents import updater
    print(updater.code_line(updater.code_state()))
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


def cmd_sync(_args) -> int:
    from .agents import updater
    return updater.sync()


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


def cmd_hash_password(args) -> int:
    pw = getpass.getpass("dashboard password: ")
    if len(pw) < 8:
        print("use at least 8 characters")
        return 2
    if getattr(args, "save", False):
        if getpass.getpass("same password again: ") != pw:
            print("the two did not match; nothing saved")
            return 2
        config.write_env({"DASHBOARD_PASSWORD_HASH": auth.hash_password(pw)})
        print("saved to .env (only the hash; the password itself is not stored)")
        return 0
    print(f"DASHBOARD_PASSWORD_HASH={auth.hash_password(pw)}")
    return 0


def cmd_dashboard(_args) -> int:
    import os
    import uvicorn
    from .dashboard.app import create_app
    from .core import limits
    cfg = config.get_config()
    cfg.locks_dir.mkdir(parents=True, exist_ok=True)
    limits.raise_open_files()                                          # 48 thumbnails at once need more than macOS's 256
    (cfg.locks_dir / "dashboard.pid").write_text(str(os.getpid()))   # the updater restarts it after an update
    uvicorn.run(create_app(), host="127.0.0.1", port=cfg.dashboard_port, log_level="info")
    return 0


def cmd_launchd(args) -> int:
    if args.what == "installed":
        from .agents import updater
        conn = db.connect()
        try:
            print(updater.mark_installed(conn))
        finally:
            conn.close()
        return 0
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
        oauth.access_token(conn)        # fail now, with a clear message, if the sign-in is dead
        reader = DriveReader(lambda: oauth.access_token(conn), conn=conn, agent="cli")
        if args.what == "scan":
            from .agents import scanner
            from .core import logs, runner
            lock = runner.Lock("scanner")          # the same lock the hourly scanner takes: never two passes at once
            if not lock.acquire():
                print("the scanner is already running (the hourly agent); try again when it finishes")
                return 2
            try:
                ctx = runner.Context(agent="scanner", conn=conn, log=logs.get_logger("scanner"), cfg=config.get_config(),
                                     dry_run=True, run_id=0)
                print(scanner.run(ctx, reader=reader))
                if args.classify:
                    from .library import classify
                    st = classify.sort_pass(conn, reader.thumbnail_for, limit=args.classify, log=ctx.log)
                    print(f"sorted by {st.sorter or 'nothing'}: {st.done} done, {st.failed} failed {st.stopped}")
            finally:
                lock.release()
            return 0
        if args.what == "report":
            from .library import report
            sheet = (report.write_contact_sheet(conn, reader.thumbnail_for, n=args.sheet, subject=args.subject)
                     if args.sheet else None)
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
        reader = DriveReader(lambda: oauth.access_token(conn), conn=conn, agent="cli")
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
        facts = claude.PostFacts(brand_name=cfg.brand_name, event_kind=row.get("event_kind") or "unknown",
                                 shot_type=row.get("shot_type") or "")
        return drafter.draft(facts, cache / f"{row['drive_id']}.img").captions

    nxt = db.one(conn, "SELECT * FROM conventions WHERE attending=1 AND COALESCE(end_date, start_date) >= date('now') ORDER BY start_date LIMIT 1")
    when = ", ".join(x for x in ((nxt["start_date"] if nxt else ""), (nxt["city"] if nxt else "")) if x)
    out = board.samples(conn, picks, fetch, captions=captions, event=nxt["name"] if nxt else "", when=when,
                        site=cfg.brand_domain)
    print(f"samples: {out / 'index.html'}")
    conn.close()
    return 0


def cmd_design(args) -> int:
    """Every motion design on the strongest frames of the library, for the dashboard's Library page.
    Reads Drive's previews only; posts nothing."""
    from .core import runner
    from .drive import oauth
    from .drive.api import DriveReader
    from .render import design_samples
    conn = db.connect()
    lock = runner.Lock("designer")
    if not lock.acquire():
        print("design samples are already being made; they show on the Library page when done")
        return 2

    def failed(why: str) -> int:
        """Said on the Design card and on the Agents page, never only in a log."""
        design_samples.write_status("failed", why)
        runner.record_error_once(conn, "designer", "design_samples", f"Design samples not made: {why}")
        print(why)
        return 2
    try:
        design_samples.write_status("running", "being made on your approved photos")
        try:
            oauth.access_token(conn)
        except oauth.DriveAuthError as e:
            return failed(f"Google Drive is signed out ({e}); sign in on the Drive page")
        reader = DriveReader(lambda: oauth.access_token(conn), conn=conn, agent="designer")
        try:
            out = design_samples.make(conn, lambda fid: reader.thumbnail_for(fid, 1600), reels=not args.no_reels)
        except Exception as e:  # noqa: BLE001  whatever stopped it is said where Chris looks
            return failed(str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}")
        about = json.loads((out / "about.json").read_text())
        design_samples.write_status("done", f"made on {len(about['photos'])} of your approved photos", folder=out.name,
                                    failed=about.get("failed") or [])
        print(f"design samples: {out / 'index.html'}")
        return 0
    finally:
        lock.release()
        conn.close()


def cmd_site(args) -> int:
    if args.what == "check":
        return cmd_site_check(args)
    if args.what == "deploy":
        # Chris, 2026-10-12: the site goes live from the Mini with nobody at a terminal (site/deploy.py)
        from .site import deploy
        return deploy.run(with_check=not args.no_check)
    import io
    from PIL import Image
    from .drive import oauth
    from .drive.api import DriveReader
    from .site import build
    conn = db.connect()
    try:
        oauth.access_token(conn)           # fail now, before the build, if the sign-in is dead
        reader = DriveReader(lambda: oauth.access_token(conn), conn=conn, agent="cli")
    except oauth.DriveAuthError as e:
        print(f"{e} Building without photos.")
        reader = None
    cache = config.get_config().data_root / "photos"
    cache.mkdir(parents=True, exist_ok=True)

    def fetch(row):
        path = cache / f"{row['drive_id']}.img"
        if not path.exists():
            path.write_bytes(reader.download(row["drive_id"]))
        return Image.open(io.BytesIO(path.read_bytes()))

    def recheck(row, image):
        # Claude's final check, for a photo it has not yet judged for the kind of occasion (a wedding is never used)
        from .library import classify
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "JPEG", quality=90)
        return classify.final_check(conn, row["id"], buf.getvalue(), agent="site")

    # Chris, 2026-10-09: the site goes live before any photo is cleared; photos join on the next build
    def look(data):
        from .library import classify
        return classify.look(conn, data, agent="site")

    has_key = bool(secrets.get_secret("ANTHROPIC_API_KEY"))
    photos = build.pick_photos(conn, fetch, recheck=recheck if has_key else None, look=look if has_key else None) \
        if reader else build.SitePhotos()
    if not photos.hero:
        print("no postable photos yet, so the site is built without photos; they join on the next build "
              "once folders are cleared on the Library page and the final check has passed")
    out = build.build(conn, photos, preview=args.preview)
    print(f"built {out} (hero {len(photos.hero)}, coverage {len(photos.coverage)}, venues {len(photos.venues)})"
          f"{' PREVIEW' if args.preview else ''}")
    if photos.hero_note:
        print(f"hero: {photos.hero_note}")
    conn.close()
    return 0



def cmd_site_check(args) -> int:
    """The live site, from the outside: every page, the sitemap and robots.txt, then the booking API
    with the Mini's token. With --wait it retries until everything passes or the time runs out (a new
    custom domain can take a few minutes to get its certificate). Writes nothing."""
    from .site import deploy
    ok, lines = deploy.check(args.wait, say=print)
    for line in lines:
        print(line)
    print("LIVE: every check passed" if ok else "NOT LIVE YET: see the FAIL lines above")
    return 0 if ok else 1


KEY_ALIASES = {"ANTHROPIC_API_KEY": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY")}


def _fingerprint(path) -> tuple:
    import hashlib
    st = path.stat()
    return st.st_size, st.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def check_anthropic_key(key: str) -> str:
    """One free call (the model list; no tokens, no cost) to see that Anthropic accepts the key."""
    import anthropic
    try:
        anthropic.Anthropic(api_key=key).models.list(limit=1)
    except anthropic.APIError as e:
        return f"Anthropic did not accept it ({type(e).__name__})"
    return "Anthropic accepted it"


def cmd_copy_key(args) -> int:
    """Chris, 2026-10-11: "Use my Anthropic key from [my other suite's] .env (DO NOT TOUCH ANYTHING IN
    THAT ENV)". The source file is opened for reading only and checked unchanged afterwards; the value
    goes into this suite's own .env and is never printed."""
    from pathlib import Path
    from dotenv import dotenv_values
    name = args.name
    if name not in secrets.SECRET_NAMES:
        print(f"{name} is not a key this suite uses ({', '.join(secrets.SECRET_NAMES)})")
        return 2
    src = Path(args.source).expanduser()
    ours = config.env_file_path()
    if not src.is_file():
        print(f"no file at {src}; nothing copied")
        return 1
    if ours.exists() and src.resolve() == ours.resolve():
        print("that is this suite's own .env; nothing to copy")
        return 2
    before = _fingerprint(src)
    found = {k: v for k, v in dotenv_values(src).items() if v}
    after = _fingerprint(src)
    if before != after:
        print(f"{src} changed while it was read; nothing copied")
        return 1
    names = [args.as_name] if args.as_name else list(KEY_ALIASES.get(name, (name,)))
    hit = next((n for n in names if n in found), None)
    if hit is None:
        print(f"none of {', '.join(names)} is set in {src}; nothing copied")
        return 1
    value = "".join(found[hit].split())
    config.write_env({name: value})
    print(f"{name} saved to {ours} (read as {hit} from {src}; that file was only read and is unchanged)")
    if name == "ANTHROPIC_API_KEY" and not args.no_check:
        print(check_anthropic_key(value))
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
    hp = sub.add_parser("hash-password"); hp.add_argument("--save", action="store_true", help="write the hash into .env")
    hp.set_defaults(fn=cmd_hash_password)
    sub.add_parser("dashboard").set_defaults(fn=cmd_dashboard)
    sub.add_parser("sync").set_defaults(fn=cmd_sync)
    l = sub.add_parser("launchd"); l.add_argument("what", choices=["status", "installed"]); l.set_defaults(fn=cmd_launchd)
    dv = sub.add_parser("drive"); dv.add_argument("what", choices=["login", "scan", "report"])
    dv.add_argument("--wait", type=float, default=0, help="login: seconds to wait for the browser to return here")
    dv.add_argument("--classify", type=int, default=0, help="scan: sort this many photos (Ollama free; Claude under the cap)")
    dv.add_argument("--sheet", type=int, default=30, help="report: photos on the contact sheet (0 for none)")
    dv.add_argument("--subject", choices=["event", "architecture"], default="event",
                    help="report: which sheet, the convention frames or Chris's building work")
    dv.set_defaults(fn=cmd_drive)
    sub.add_parser("fonts").set_defaults(fn=cmd_fonts)
    sub.add_parser("samples").set_defaults(fn=cmd_samples)
    dz = sub.add_parser("design", help="motion design samples on your own photos, shown on the Library page")
    dz.add_argument("--no-reels", action="store_true"); dz.set_defaults(fn=cmd_design)
    st = sub.add_parser("site"); st.add_argument("what", choices=["build", "check", "deploy"]); st.add_argument("--preview", action="store_true")
    st.add_argument("--no-check", action="store_true", help="deploy: skip the check from outside (go-live checks after the secrets)")
    st.add_argument("--wait", type=float, default=0, help="check: keep retrying this many seconds until everything passes")
    st.set_defaults(fn=cmd_site)
    ck = sub.add_parser("copy-key", help="copy one key from another .env file (only read) into this suite's .env")
    ck.add_argument("name"); ck.add_argument("--from", dest="source", required=True)
    ck.add_argument("--as", dest="as_name", default="", help="the key's name in that file, if it differs")
    ck.add_argument("--no-check", action="store_true", help="skip the free check that Anthropic accepts the key")
    ck.set_defaults(fn=cmd_copy_key)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
