"""eventcaliber.com goes live from the Mini with nobody at a terminal.

Chris, 2026-10-12: "do what you can without needing me to respond or terminal anything". Until then
every change to the site waited for him to run scripts/go-live.sh. go-live still does the first deploy
(the Cloudflare sign-in, the bucket, the booking database, the secrets) and leaves wrangler.live.jsonc
behind: the deploy config with the real database id, untracked. Every deploy after that is the same
three steps, and this module is those steps:

  1. `ccs site build`   the pages, from the approved photos (Claude checks the hero upload)
  2. `wrangler deploy`  with wrangler.live.jsonc, signed in as the Mini's user (go-live did that once)
  3. the check from outside: every page, the sitemap, the booking API

Who runs it: the updater, after a merge that changes the site (and once after this arrives, since the
site on Cloudflare is older than the code); the Publish button on the Photos page, from a phone, after
the hero or the approved photos change; `bin/ccs site deploy` by hand. One at a time (a lock), and
what happened is written to a status file the Photos page reads. Without wrangler.live.jsonc there has
been no go-live: it refuses and says so. A deploy that fails is recorded once per commit and is not
tried again by itself for that commit; the Publish button tries again.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from ..core import config, db, runner, settings

WRANGLER = ("npx", "--yes", "wrangler@4.149.0")       # the same pin as scripts/go-live.sh
LIVE_CONFIG = "wrangler.live.jsonc"
STATUS_FILE = "site-deploy.json"                     # DATA_ROOT/site: what the last deploy did, for the Photos page
STALE_RUNNING = 40 * 60                              # a "running" status older than this was a run that died
DEPLOYED_KEY = "site.deployed_commit"                # the code commit the site on Cloudflare was built from
FAILED_KEY = "site.deploy_failed_for"                # JSON {commit, tries, last_at}: a failed deploy is tried again, up to MAX_TRIES
MAX_TRIES = 3                                        # per commit, by itself; Publish on the Photos page always tries
RETRY_AFTER = 30 * 60                                # seconds between tries
BUILD_TIMEOUT = 20 * 60
DEPLOY_TIMEOUT = 10 * 60
CHECK_WAIT = 5 * 60
# a change under these paths changes the site; anything else does not need a deploy
SITE_PATHS = ("convention_social/site/", "site/", "worker/", "offer.json", "wrangler.jsonc")


def live_config(repo: Optional[Path] = None) -> Path:
    return Path(repo or config.REPO_ROOT) / LIVE_CONFIG


def ready(repo: Optional[Path] = None) -> tuple[bool, str]:
    """Can this machine deploy? go-live must have run once here, and Node must be installed."""
    if not live_config(repo).is_file():
        return False, f"no {LIVE_CONFIG} on this machine: run scripts/go-live.sh once on the Mini (the first deploy signs in to Cloudflare)"
    if shutil.which("npx") is None:
        return False, "npx is not on PATH (Node is not installed, or PATH lacks /opt/homebrew/bin)"
    return True, "ready"


# ------------------------------------------------------------------ the status the Photos page reads

def _status_path() -> Path:
    return config.get_config().data_root / "site" / STATUS_FILE


def write_status(state: str, message: str, **extra) -> None:
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps({"state": state, "message": message, "at": datetime.now().isoformat(timespec="seconds"), **extra}))
    tmp.replace(path)


def read_status() -> dict:
    try:
        st = json.loads(_status_path().read_text())
    except (OSError, ValueError):
        return {}
    if st.get("state") == "running":
        try:
            if (datetime.now() - datetime.fromisoformat(st["at"])).total_seconds() > STALE_RUNNING:
                return {**st, "state": "failed", "message": "the last publish stopped before it finished; press Publish again"}
        except (KeyError, ValueError):
            pass
    return st


# ------------------------------------------------------------------ a failed deploy, tried again

def failure_record(conn) -> dict:
    """{commit, tries, last_at} of the last failed deploy, or {} when the last one went. A bare commit, as
    an older suite wrote it, counts as one failure at no known time."""
    raw = settings.get(conn, FAILED_KEY) or ""
    if not raw:
        return {}
    try:
        rec = json.loads(raw)
    except ValueError:
        rec = None
    if not isinstance(rec, dict):
        return {"commit": raw, "tries": 1, "last_at": None}
    return {"commit": rec.get("commit") or "", "tries": int(rec.get("tries") or 0), "last_at": rec.get("last_at")}


def record_failure(conn, head: str, now: Optional[datetime] = None) -> int:
    """One more failed try of this commit (a new commit starts at one). Returns the count."""
    rec = failure_record(conn)
    tries = rec["tries"] + 1 if rec.get("commit") == head else 1
    settings.set(conn, FAILED_KEY, json.dumps({"commit": head, "tries": tries,
                                               "last_at": (now or datetime.now()).isoformat(timespec="seconds")}))
    return tries


# ------------------------------------------------------------------ is the site behind the code?

def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60)
    return r.stdout.strip() if r.returncode == 0 else ""


def wanted(conn, repo: Optional[Path] = None, now: Optional[datetime] = None) -> tuple[bool, str]:
    """(deploy now?, why) for the updater: the site is behind the code when the commit it was built from
    is not this one and the commits in between touch the site, or when the suite has never deployed it.
    A failed deploy is tried again after RETRY_AFTER, up to MAX_TRIES per commit (2026-10-13)."""
    repo = Path(repo or config.REPO_ROOT)
    head = _git(repo, "rev-parse", "HEAD")
    if not head:
        return False, "not a git checkout"
    deployed = settings.get(conn, DEPLOYED_KEY) or ""
    if deployed == head:
        return False, f"the site is on {head[:7]}, the same as the code"
    failed = failure_record(conn)
    if failed.get("commit") == head:
        tries = failed["tries"]
        if tries >= MAX_TRIES:
            return False, f"the deploy of {head[:7]} failed {tries} times; not trying again by itself (Publish on the Photos page does)"
        last = None
        try:
            last = datetime.fromisoformat(failed["last_at"]) if failed.get("last_at") else None
        except ValueError:
            pass
        if last and ((now or datetime.now()) - last).total_seconds() < RETRY_AFTER:
            return False, (f"the deploy of {head[:7]} failed (try {tries} of {MAX_TRIES}); trying again "
                           f"{RETRY_AFTER // 60} minutes after {last.strftime('%H:%M')}")
        return True, f"the deploy of {head[:7]} failed (try {tries} of {MAX_TRIES}); trying again"
    if not deployed:
        return True, "the suite has not deployed the site yet"
    if _git(repo, "cat-file", "-t", deployed) != "commit":
        return True, f"the site was built from {deployed[:7]}, which this checkout no longer has"
    changed = [p for p in _git(repo, "diff", "--name-only", deployed, head).splitlines() if p.startswith(SITE_PATHS)]
    if not changed:
        settings.set(conn, DEPLOYED_KEY, head)       # nothing in between touches the site: it is current
        return False, f"nothing since {deployed[:7]} changes the site"
    return True, f"{len(changed)} site file(s) changed since {deployed[:7]}"


# ------------------------------------------------------------------ the deploy

def _tail(text: str, n: int = 12) -> str:
    lines = [ln for ln in (text or "").strip().splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _build(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "convention_social.cli", "site", "build"], cwd=str(repo),
                          capture_output=True, text=True, timeout=BUILD_TIMEOUT, stdin=subprocess.DEVNULL)


def _deploy(repo: Path) -> subprocess.CompletedProcess:
    from ..core import secrets
    env = {**os.environ, "WRANGLER_SEND_METRICS": "false"}
    account = secrets.get_secret("CLOUDFLARE_ACCOUNT_ID")       # go-live keeps it in .env when the sign-in has several
    if account and not env.get("CLOUDFLARE_ACCOUNT_ID"):
        env["CLOUDFLARE_ACCOUNT_ID"] = account
    return subprocess.run([*WRANGLER, "deploy", "-c", LIVE_CONFIG], cwd=str(repo), capture_output=True, text=True,
                          timeout=DEPLOY_TIMEOUT, stdin=subprocess.DEVNULL, env=env)


def check(wait: float = CHECK_WAIT, *, sleep: Optional[Callable[[float], None]] = None,
          say: Callable[[str], None] = lambda s: None) -> tuple[bool, list[str]]:
    """The live site from the outside: every page, the sitemap and robots.txt, then the booking API
    with the Mini's token. Retries until everything passes or the wait runs out (a new domain can take
    a few minutes to get its certificate). Writes nothing. Returns (all passed, the PASS/FAIL lines)."""
    from ..booking import remote
    from ..seo import site_check
    sleep = sleep or time.sleep
    deadline = time.monotonic() + max(0.0, wait)
    while True:
        results = site_check.check_all()
        api_ok, api_note = True, ""
        site = remote.SiteAPI.from_config()
        if site is None:
            api_ok, api_note = False, "no MEDIA_UPLOAD_TOKEN on this machine"
        else:
            try:
                waiting = len(site.pull())
                api_note = f"the Mini's token is accepted ({waiting} quote request(s) waiting)"
            except Exception as e:  # noqa: BLE001  any failure is a failed check, said plainly
                api_ok, api_note = False, f"the Mini could not read quote requests ({type(e).__name__}: {e})"
        ok = api_ok and all(r["ok"] for r in results)
        if ok or time.monotonic() >= deadline:
            break
        say("not all passing yet; trying again in 20 seconds")
        sleep(20)
    lines = [f"{'PASS' if r['ok'] else 'FAIL'}  {r['url']}" + ("" if r["ok"] else f"  ({'; '.join(r['problems'])})") for r in results]
    lines.append(f"{'PASS' if api_ok else 'FAIL'}  booking API: {api_note}")
    return ok, lines


def run(*, repo: Optional[Path] = None, conn=None, say: Callable[[str], None] = print, with_check: bool = True,
        build: Callable[[Path], subprocess.CompletedProcess] = _build,
        deploy: Callable[[Path], subprocess.CompletedProcess] = _deploy,
        checker: Callable[[], tuple[bool, list[str]]] = lambda: check()) -> int:
    """Build, deploy, check. Exit code 0 when the site is live on this commit; 2 when it cannot start
    (no go-live yet, or a deploy already running); 1 when a step failed (the status says which)."""
    repo = Path(repo or config.REPO_ROOT)
    ok, why = ready(repo)
    if not ok:
        write_status("failed", why)
        say(f"not deployed: {why}")
        return 2
    lock = runner.Lock("site-deploy")
    if not lock.acquire():
        say("a publish is already running; the Photos page says when it is done")
        return 2
    own = conn is None
    conn = conn or db.connect()
    head = _git(repo, "rev-parse", "HEAD")
    try:
        from ..seo import indexnow
        indexnow.ensure_key()                      # once: the key the site hosts and the pings carry (kept in .env)
        write_status("running", "building the pages", commit=head)
        say("building the site")
        r = build(repo)
        hero = next((ln[len("hero: "):] for ln in (r.stdout or "").splitlines() if ln.startswith("hero: ")), "")
        if r.returncode != 0:
            return _failed(conn, head, say, "the build failed", _tail((r.stdout or "") + "\n" + (r.stderr or "")))
        write_status("running", "sending the site to Cloudflare", commit=head, hero=hero)
        say("deploying to Cloudflare")
        r = deploy(repo)
        if r.returncode != 0:
            return _failed(conn, head, say, "Cloudflare did not take the deploy", _tail((r.stdout or "") + "\n" + (r.stderr or "")))
        if with_check:
            write_status("running", "checking the live site", commit=head, hero=hero)
            say("checking the live site")
            passed, lines = checker()
            for line in lines:
                say(line)
            if not passed:
                return _failed(conn, head, say, "deployed, but the check from outside did not pass", "\n".join(lines))
        settings.set(conn, DEPLOYED_KEY, head)
        settings.set(conn, FAILED_KEY, "")
        told, engines = tell_engines()            # the site is live either way; the card says whether they heard
        say(engines)
        write_status("done", f"live on {head[:7]}" + (f"; hero: {hero}" if hero else ""), commit=head, hero=hero,
                     engines=engines, engines_told=told)
        say(f"LIVE on {head[:7]}" + (f" (hero: {hero})" if hero else ""))
        return 0
    except subprocess.TimeoutExpired as e:
        return _failed(conn, head, say, f"a step took too long ({Path(str(e.cmd[0])).name}, {e.timeout:.0f}s)", "")
    finally:
        lock.release()
        if own:
            conn.close()


def tell_engines(post=None) -> tuple[bool, str]:
    """After a publish: the IndexNow engines hear which pages to read again. Google is not in that
    protocol; it reads the sitemap (its lastmod dates are true) once Search Console knows the site."""
    from ..seo import indexnow
    from ..site import build as site_build
    cfg = config.get_config()
    return indexnow.ping(f"https://{cfg.brand_domain}", site_build.PAGES, post=post)


def _failed(conn, head: str, say: Callable[[str], None], what: str, detail: str) -> int:
    tries = record_failure(conn, head)
    what = f"{what} (try {tries} of {MAX_TRIES})"
    write_status("failed", what, commit=head, detail=detail[:2000])
    say(f"not live: {what}")
    if detail:
        say(detail)
    return 1


def start_in_background() -> None:
    """`ccs site deploy` on its own, for the Publish button. The output goes to logs/site-deploy.log;
    what happened goes to the status file the Photos page reads."""
    cfg = config.get_config()
    cfg.ensure_dirs()
    with open(cfg.data_root / "logs" / "site-deploy.log", "ab") as log:
        subprocess.Popen([sys.executable, "-m", "convention_social.cli", "site", "deploy"], cwd=str(config.REPO_ROOT),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
