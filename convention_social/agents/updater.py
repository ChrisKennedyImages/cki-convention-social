"""Updater: the Mini keeps itself on the latest `main`, so Chris never types a command to update.

Every 10 minutes it fetches `origin/main`. When that has moved on, and this checkout is on `main`
with nothing changed locally, the new commit is tested first, in a separate worktree, with the
full suite (`bin/test`). Only a green run moves the checkout forward (fast-forward only); then the
database migrations run and the always-on dashboard is told to stop, so launchd's KeepAlive starts
it again on the new code. The one-shot agents pick up new code on their next run by themselves.

Every run also asks the running dashboard which commit it serves (/healthz on 127.0.0.1). One that
is on older code than the checkout is restarted, found by its pid file or else by its process, so a
dashboard that missed a restart catches up within ten minutes instead of serving old pages for good.
If it is still on older code after that, Chris gets the one command that restarts it.

A red run, a checkout on another branch or with local changes, or a history that is not a plain
fast-forward leaves everything exactly as it is. A red run and a failed fetch are recorded as
errors, which the watchdog pushes to Chris. New service files (`launchd/` templates) need one
`scripts/go-live.sh` on the Mini with his Mac password: that is flagged, never attempted.

Dry run (the default, like every agent) fetches and reports what it would do, and changes nothing.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Callable, Optional

from ..core import config, runner, settings

FETCH_TIMEOUT = 120
TEST_TIMEOUT = 30 * 60
NEEDS_INSTALL_KEY = "updater.needs_install"
RESTARTED_KEY = "updater.dashboard_restarted_for"
DASHBOARD_PROCESS = "-m convention_social.cli dashboard"
KICKSTART = "sudo launchctl kickstart -k system/com.chriskennedyimages.conventionsocial.dashboard"
INSTALL_PATHS = ("launchd/", "scripts/install-daemons.sh")


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def _out(repo: Path, *args: str) -> str:
    r = _git(repo, *args)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def run_suite(worktree: Path) -> tuple[bool, str]:
    """The suite on the candidate commit, with the checkout's own venv (bin/test reads .venv)."""
    try:
        r = subprocess.run([str(worktree / "bin" / "test")], cwd=str(worktree), capture_output=True,
                           text=True, timeout=TEST_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "the test run took too long"
    tail = " ".join((r.stdout or r.stderr or "").strip().splitlines()[-3:])[:300]
    return r.returncode == 0, tail


def install_requirements(repo: Path, worktree: Path) -> None:
    pip = repo / ".venv" / "bin" / "pip"
    if pip.exists():
        subprocess.run([str(pip), "install", "-q", "-r", str(worktree / "requirements.txt")],
                       capture_output=True, text=True, timeout=15 * 60, check=True)


def migrate(repo: Path) -> None:
    subprocess.run([str(repo / "bin" / "ccs"), "init-db"], cwd=str(repo), capture_output=True, text=True,
                   timeout=300, check=True)


def _is_dashboard(cmd: str) -> bool:
    return DASHBOARD_PROCESS in cmd


def _processes() -> list[tuple[int, str]]:
    out = subprocess.run(["ps", "-x", "-o", "pid=,command="], capture_output=True, text=True).stdout
    procs = []
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].isdigit():
            procs.append((int(parts[0]), parts[1]))
    return procs


def _cwd_of(pid: int) -> str:
    """A process's working folder (lsof, on the Mini); "" when it cannot be read."""
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return next((line[1:] for line in out.splitlines() if line.startswith("n")), "")


def dashboard_pids(pid_file: Optional[Path] = None, *, processes: Callable[[], list] = _processes,
                   cwd_of: Callable[[int], str] = _cwd_of) -> list[int]:
    """This suite's dashboard: the pid it wrote at start, or else a process of this user running
    `-m convention_social.cli dashboard` from this very checkout (launchd starts it in the repo).
    A dashboard older than the pid file wrote none. The folder check keeps a test run in another
    folder (the updater's own worktree) from ever finding the real one."""
    pid_file = pid_file or config.get_config().locks_dir / "dashboard.pid"
    try:
        pid = int(pid_file.read_text().strip())
        cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True).stdout
        if _is_dashboard(cmd):
            return [pid]
    except (OSError, ValueError):
        pass
    here = str(config.REPO_ROOT.resolve())
    return [pid for pid, cmd in processes() if _is_dashboard(cmd) and pid != os.getpid() and cwd_of(pid) == here]


def restart_dashboard(pid_file: Optional[Path] = None, **find) -> str:
    """Stop the running dashboard; launchd's KeepAlive starts it again on the new code. Only a
    process that is really this suite's dashboard is ever signalled."""
    pids = dashboard_pids(pid_file, **find)
    if not pids:
        return "dashboard: not found running"
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as e:
            return f"dashboard: could not be stopped ({e})"
    return "dashboard: restarted"


def dashboard_commit(get: Optional[Callable] = None) -> Optional[str]:
    """The commit the running dashboard serves; "" when it is older than /healthz; None when it does
    not answer at all."""
    if get is None:
        import requests
        get = requests.get
    url = f"http://127.0.0.1:{config.get_config().dashboard_port}/healthz"
    try:
        r = get(url, timeout=5, allow_redirects=False)
    except Exception:  # noqa: BLE001  not answering is an answer
        return None
    if getattr(r, "status_code", 0) != 200:
        return ""
    try:
        return str((r.json() or {}).get("commit") or "")
    except ValueError:
        return ""


def ensure_dashboard(ctx: runner.Context, head: str, *, probe: Callable[[], Optional[str]] = dashboard_commit,
                     restart: Callable[[], str] = restart_dashboard) -> str:
    """Verified where it is used: the dashboard Chris opens must serve the checkout's commit."""
    running = probe()
    if running is None:
        runner.record_error_once(ctx.conn, ctx.agent, "dashboard_down",
                                 f"The dashboard is not answering on this Mini. On the Mini: {KICKSTART}")
        return "dashboard: not answering"
    if running == head:
        return f"dashboard: serving {head[:7]}"
    was = running[:7] or "older code"
    if settings.get(ctx.conn, RESTARTED_KEY) == head:
        runner.record_error_once(ctx.conn, ctx.agent, "dashboard_stale",
                                 f"The dashboard still serves {was}, not {head[:7]}, after a restart. On the Mini: {KICKSTART}")
        return f"dashboard: still on {was} after a restart"
    if ctx.dry_run:
        return f"DRY RUN dashboard serves {was}, not {head[:7]}; would restart it"
    note = restart()
    settings.set(ctx.conn, RESTARTED_KEY, head)
    return f"dashboard was on {was}; {note}"


def run(ctx: runner.Context, *, repo: Optional[Path] = None,
        suite: Callable[[Path], tuple[bool, str]] = run_suite,
        requirements: Callable[[Path, Path], None] = install_requirements,
        migrations: Callable[[Path], None] = migrate,
        restart: Callable[[], str] = restart_dashboard,
        probe: Callable[[], Optional[str]] = dashboard_commit) -> str:
    repo = Path(repo or config.REPO_ROOT)
    summary = update(ctx, repo, suite=suite, requirements=requirements, migrations=migrations)
    if summary == "fetch failed":
        return summary
    return f"{summary}; {ensure_dashboard(ctx, _out(repo, 'rev-parse', 'HEAD'), probe=probe, restart=restart)}"


def update(ctx: runner.Context, repo: Path, *, suite: Callable[[Path], tuple[bool, str]],
           requirements: Callable[[Path, Path], None], migrations: Callable[[Path], None]) -> str:
    fetch = _git(repo, "fetch", "--quiet", "origin", "main", timeout=FETCH_TIMEOUT)
    if fetch.returncode != 0:
        runner.record_error_once(ctx.conn, ctx.agent, "update_fetch",
                                 "Could not reach GitHub to check for updates: " + (fetch.stderr or "").strip()[:300])
        return "fetch failed"
    head, target = _out(repo, "rev-parse", "HEAD"), _out(repo, "rev-parse", "origin/main")
    if head == target:
        return f"up to date at {head[:7]}"
    branch = _out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch != "main":
        return f"not updating: the checkout is on {branch}, not main"
    if _out(repo, "status", "--porcelain", "--untracked-files=no"):
        return "not updating: the checkout has local changes"
    if _git(repo, "merge-base", "--is-ancestor", head, target).returncode != 0:
        return "not updating: main on the Mini and on GitHub have gone different ways"
    changed = _out(repo, "diff", "--name-only", head, target).splitlines()
    install = [p for p in changed if p.startswith(INSTALL_PATHS)]
    if ctx.dry_run:
        return (f"DRY RUN would test and update {head[:7]} -> {target[:7]} ({len(changed)} file(s))"
                + ("; new service files need scripts/go-live.sh" if install else ""))

    worktree = config.get_config().data_root / "cache" / "update-check"
    _git(repo, "worktree", "remove", "--force", str(worktree))
    shutil.rmtree(worktree, ignore_errors=True)
    _out(repo, "worktree", "add", "--detach", str(worktree), target)
    try:
        venv = repo / ".venv"
        if venv.exists():
            (worktree / ".venv").symlink_to(venv)
        if "requirements.txt" in changed:
            requirements(repo, worktree)
        ok, tail = suite(worktree)
    finally:
        _git(repo, "worktree", "remove", "--force", str(worktree))
        shutil.rmtree(worktree, ignore_errors=True)
    if not ok:
        runner.record_error(ctx.conn, ctx.agent, "update_tests",
                            f"Update {target[:7]} held back: its tests did not pass on the Mini. {tail}")
        return f"held back {target[:7]}: tests failed"

    _out(repo, "merge", "--ff-only", "--quiet", target)
    migrations(repo)
    if install:
        settings.set(ctx.conn, NEEDS_INSTALL_KEY, target)
        runner.record_error_once(ctx.conn, ctx.agent, "needs_install",
                                 "New service files arrived. Run scripts/go-live.sh once on the Mini "
                                 "(it asks for your Mac password) to install them.")
    return f"updated {head[:7]} -> {target[:7]} ({len(changed)} file(s)); tests passed" + (
        "; new service files need scripts/go-live.sh" if install else "")


if __name__ == "__main__":
    runner.main_for("updater", run)
