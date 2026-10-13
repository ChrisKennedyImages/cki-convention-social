"""The updater (Chris, 2026-10-11: no more typing commands on the Mini to update it). Proven against
real git repositories in a temporary folder: it tests the candidate commit before switching, only
fast-forwards a clean `main`, holds back on red tests, and never touches local work."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from convention_social import cli
from convention_social.agents import updater
from convention_social.core import config, db, runner, settings
from convention_social.site import deploy as site_deploy
from tests._base import IsolatedCase

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.org"]


def git(cwd, *args):
    return subprocess.run(["git", *GIT_ID, *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


class Repos(IsolatedCase):
    """Real git repositories in a temporary folder: a bare origin, a seed clone that pushes to it, and
    the checkout the code under test moves."""
    def setUp(self):
        super().setUp()
        base = self.root / "git"
        base.mkdir()
        self.origin = base / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(self.origin)], check=True)
        self.seed = base / "seed"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.seed)], check=True, capture_output=True)
        git(self.seed, "checkout", "-q", "-b", "main")
        self.commit("a.txt", "one")
        self.repo = base / "checkout"
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.repo)], check=True)
        self.conn = db.connect()
        self.calls = {"suite": [], "migrate": 0, "restart": 0, "requirements": 0, "deploy": []}
        self.dash = self.head()          # the commit the running dashboard serves (None: not answering)
        self.deploy_ok = True
        settings.set(self.conn, site_deploy.DEPLOYED_KEY, self.head())     # the site is on the code (SiteFollows sets its own)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def commit(self, name, text):
        p = self.seed / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        git(self.seed, "add", name)
        git(self.seed, "commit", "-q", "-m", f"{name} {text}")
        git(self.seed, "push", "-q", "origin", "main")
        return git(self.seed, "rev-parse", "HEAD")

    def run_updater(self, dry=False, suite_ok=True, req_fail_on=None):
        def suite(worktree):
            self.calls["suite"].append({"files": sorted(p.name for p in worktree.iterdir()),
                                        "b": (worktree / "b.txt").read_text() if (worktree / "b.txt").exists() else None})
            return suite_ok, "Ran 3 tests" if suite_ok else "FAILED (failures=1)"

        def requirements(repo, worktree):
            self.calls["requirements"] += 1
            self.calls.setdefault("requirements_from", []).append(str(worktree))
            if self.calls["requirements"] == req_fail_on:
                raise OSError("pip: no network")

        def migrations(repo):
            self.calls["migrate"] += 1

        def restart():
            self.calls["restart"] += 1
            return "dashboard: restarted"

        def deploy(repo):
            self.calls["deploy"].append(git(repo, "rev-parse", "HEAD"))
            if self.deploy_ok:                 # the real one records the commit itself (site/deploy.py)
                settings.set(self.conn, site_deploy.DEPLOYED_KEY, self.calls["deploy"][-1])
            return self.deploy_ok, "LIVE on it" if self.deploy_ok else "not live: Cloudflare did not take the deploy"

        ctx = runner.Context("updater", self.conn, None, config.get_config(), dry, 0)
        return updater.run(ctx, repo=self.repo, suite=suite, requirements=requirements, migrations=migrations, restart=restart,
                           probe=lambda: self.dash, deploy=deploy)

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")


class Updater(Repos):
    def test_up_to_date_does_nothing(self):
        line = self.run_updater()
        self.assertIn("up to date", line)
        self.assertIn(f"dashboard: serving {self.head()[:7]}", line)
        self.assertEqual((self.calls["suite"], self.calls["restart"]), ([], 0))

    def test_a_dashboard_left_on_old_code_is_restarted_once_then_chris_is_told(self):
        # the bug of 2026-10-11: the checkout was current, the dashboard served old pages for good
        self.dash = ""                                                   # older than /healthz itself
        line = self.run_updater()
        self.assertIn("up to date", line)
        self.assertIn("dashboard was on older code; dashboard: restarted", line)
        self.assertEqual(self.calls["restart"], 1)
        self.assertIn("still on older code after a restart", self.run_updater())
        self.assertEqual(self.calls["restart"], 1, "never a restart loop")
        err = db.one(self.conn, "SELECT kind, message FROM errors WHERE agent='updater'")
        self.assertEqual(err["kind"], "dashboard_stale")
        self.assertIn(updater.KICKSTART, err["message"])
        self.dash = self.head()
        self.assertIn("dashboard: serving", self.run_updater())

    def test_a_dashboard_that_does_not_answer_is_reported_not_signalled(self):
        self.dash = None
        self.assertIn("dashboard: not answering", self.run_updater())
        self.assertEqual(self.calls["restart"], 0)
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors WHERE agent='updater'")["kind"], "dashboard_down")

    def test_dry_run_only_says_the_dashboard_is_stale(self):
        self.dash = "0" * 40
        self.assertIn("would restart it", self.run_updater(dry=True))
        self.assertEqual(self.calls["restart"], 0)

    def test_a_green_new_commit_is_tested_first_then_switched_to(self):
        target = self.commit("b.txt", "two")
        line = self.run_updater()
        self.assertIn(f"-> {target[:7]}", line)
        self.assertIn("tests passed", line)
        self.assertEqual(self.head(), target)
        self.assertEqual(len(self.calls["suite"]), 1)
        self.assertEqual(self.calls["suite"][0]["b"], "two")          # the suite ran on the NEW commit
        self.assertEqual((self.calls["migrate"], self.calls["restart"]), (1, 1))
        self.assertFalse((config.get_config().data_root / "cache" / "update-check").exists())

    def test_red_tests_hold_the_update_back(self):
        before = self.head()
        target = self.commit("b.txt", "broken")
        line = self.run_updater(suite_ok=False)
        self.assertIn("held back", line)
        self.assertEqual(self.head(), before)
        self.assertEqual((self.calls["migrate"], self.calls["restart"]), (0, 0))
        err = db.one(self.conn, "SELECT kind, message FROM errors WHERE agent='updater'")
        self.assertEqual(err["kind"], "update_tests")
        self.assertIn(target[:7], err["message"])
        self.assertEqual(self.calls["requirements"], 0, "no new requirements: nothing installed, nothing to put back")
        self.assertNotIn("put back", line)

    def test_dry_run_reports_and_changes_nothing(self):
        before = self.head()
        self.commit("b.txt", "two")
        self.assertIn("DRY RUN would test and update", self.run_updater(dry=True))
        self.assertEqual(self.head(), before)
        self.assertEqual(self.calls["suite"], [])

    def test_another_branch_or_local_changes_are_left_alone(self):
        self.commit("b.txt", "two")
        git(self.repo, "checkout", "-q", "-b", "work-in-progress")
        self.assertIn("on work-in-progress", self.run_updater())
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "a.txt").write_text("edited on the Mini")
        before = self.head()
        self.assertIn("local changes", self.run_updater())
        self.assertEqual(self.head(), before)
        self.assertEqual((self.repo / "a.txt").read_text(), "edited on the Mini")
        self.assertEqual(self.calls["suite"], [])

    def test_new_service_files_are_flagged_not_installed(self):
        target = self.commit("launchd/com.example.new.plist.template", "<plist/>")
        line = self.run_updater()
        self.assertIn("scripts/go-live.sh", line)
        self.assertEqual(settings.get(self.conn, updater.NEEDS_INSTALL_KEY), target)
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors WHERE agent='updater'")["kind"], "needs_install")

    def test_new_requirements_are_installed_before_the_tests(self):
        self.commit("requirements.txt", "requests\n")
        self.run_updater()
        self.assertEqual(self.calls["requirements"], 1)

    def test_a_red_run_puts_the_requirements_back(self):
        """8.1 (2026-10-13): new requirements went into the live venv before the tests; a red run left the venv
        on the new ones while the code stayed on the old. Now the checkout's own requirements are installed
        again, and the line says so."""
        head = self.head()
        self.commit("requirements.txt", "requests\n")
        line = self.run_updater(suite_ok=False)
        self.assertIn("tests failed", line)
        self.assertIn("requirements put back", line)
        self.assertEqual(self.calls["requirements"], 2)
        self.assertEqual(self.calls["requirements_from"][-1], str(self.repo), "from the checkout, which is still on the old commit")
        self.assertEqual(self.head(), head)
        self.calls["requirements"] = 0
        line = self.run_updater(suite_ok=True)
        self.assertIn("tests passed", line)
        self.assertNotIn("put back", line)
        self.assertEqual(self.calls["requirements"], 1, "a green run installs once and keeps them")

    def test_requirements_that_cannot_be_put_back_are_an_error_said_out_loud(self):
        """8.1: the venv then holds the new commit's requirements while the code stays on the old one; the Agents
        page says so, with the commits, and the line does too."""
        self.commit("requirements.txt", "requests\n")
        line = self.run_updater(suite_ok=False, req_fail_on=2)
        self.assertIn("tests failed", line)
        self.assertIn("could NOT be put back (OSError)", line)
        kinds = [e["kind"] for e in db.rows(self.conn, "SELECT kind FROM errors WHERE agent='updater' ORDER BY id")]
        self.assertEqual(kinds, ["update_requirements", "update_tests"])
        err = db.one(self.conn, "SELECT message FROM errors WHERE kind='update_requirements'")
        self.assertIn("pip: no network", err["message"])
        self.assertIn("requirements while the code is on", err["message"])

    def test_github_out_of_reach_is_an_error_not_a_crash(self):
        git(self.repo, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        self.assertEqual(self.run_updater(), "fetch failed")
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors WHERE agent='updater'")["kind"], "update_fetch")


class RestartDashboard(IsolatedCase):
    def test_only_the_suites_dashboard_is_ever_signalled(self):
        none = dict(processes=lambda: [], cwd_of=lambda pid: "")
        pid_file = self.root / "dashboard.pid"
        pid_file.write_text(str(os.getpid()))                  # this test process is not a dashboard
        self.assertEqual(updater.restart_dashboard(pid_file, **none), "dashboard: not found running")
        fake = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "-m", "convention_social.cli", "dashboard"])
        try:
            pid_file.write_text(str(fake.pid))
            time.sleep(0.2)
            self.assertEqual(updater.restart_dashboard(pid_file, **none), "dashboard: restarted")
            self.assertIsNotNone(fake.wait(timeout=5))
        finally:
            if fake.poll() is None:
                fake.kill()
        self.assertEqual(updater.restart_dashboard(self.root / "missing.pid", **none), "dashboard: not found running")

    def test_without_a_pid_file_only_a_dashboard_running_from_this_checkout_is_found(self):
        here = str(config.REPO_ROOT.resolve())
        procs = [(111, "/x/Python.app/Contents/MacOS/Python -m convention_social.cli dashboard"),
                 (222, "/y/python -m convention_social.cli dashboard"),          # another checkout, e.g. a test worktree
                 (333, "/x/python -m convention_social.agents.updater"),
                 (444, "/x/python -m convention_social.cli dashboard")]           # folder unreadable
        cwd = {111: here, 222: str(self.root), 333: here}
        self.assertEqual(updater.dashboard_pids(self.root / "missing.pid", processes=lambda: procs,
                                                cwd_of=lambda pid: cwd.get(pid, "")), [111])


class Probe(IsolatedCase):
    def test_the_dashboards_answer_is_read_as_its_commit(self):
        class R:
            def __init__(self, code, body):
                self.status_code, self.body = code, body

            def json(self):
                return self.body
        seen = []

        def get(url, **kw):
            seen.append((url, kw))
            return R(200, {"ok": True, "commit": "abc123"})
        self.assertEqual(updater.dashboard_commit(get), "abc123")
        self.assertEqual(seen[0], ("http://127.0.0.1:4610/healthz", {"timeout": 5, "allow_redirects": False}))
        self.assertEqual(updater.dashboard_commit(lambda url, **kw: R(404, {})), "")          # older than /healthz
        self.assertEqual(updater.dashboard_commit(lambda url, **kw: R(303, {})), "")

        def down(url, **kw):
            raise ConnectionError("refused")
        self.assertIsNone(updater.dashboard_commit(down))


class CodeState(Repos):
    """`ccs status` and go-live say where the code stands against GitHub main (2026-10-11: a go-live
    run on a checkout from before the last merge installed the old schedule, and nothing said so)."""

    def test_says_when_the_mini_is_behind_github(self):
        state = updater.code_state(self.repo)
        self.assertEqual((state["head"], state["branch"], state["behind"], state["dirty"]), (self.head(), "main", 0, False))
        self.assertIn("the same as GitHub main", updater.code_line(state))
        target = self.commit("b.txt", "two")
        self.assertEqual(updater.code_state(self.repo)["behind"], 0, "nothing fetched yet: as of the last fetch")
        git(self.repo, "fetch", "-q", "origin", "main")
        state = updater.code_state(self.repo)
        self.assertEqual((state["target"], state["behind"]), (target, 1))
        line = updater.code_line(state)
        self.assertIn(f"on main, 1 commit(s) BEHIND GitHub main {target[:7]}", line)
        self.assertIn("scripts/go-live.sh", line)
        (self.repo / "a.txt").write_text("edited")
        self.assertIn("(with local changes)", updater.code_line(updater.code_state(self.repo)))
        self.assertEqual(updater.code_line(updater.code_state(self.root)), "code: not a git checkout")

    def test_status_prints_it(self):
        self.commit("b.txt", "two")
        git(self.repo, "fetch", "-q", "origin", "main")
        out = io.StringIO()
        with mock.patch.object(config, "REPO_ROOT", self.repo), redirect_stdout(out):
            self.assertEqual(cli.main(["status"]), 0)
        self.assertIn("BEHIND GitHub main", out.getvalue())
        self.assertIn("updater", out.getvalue())


class Installed(Repos):
    def test_go_live_clears_the_ask_for_itself_until_new_service_files_arrive(self):
        target = self.commit("launchd/com.example.new.plist.template", "<plist/>")
        self.run_updater()
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE kind='needs_install' AND alerted=0")["n"], 1)

        def installed():
            out = io.StringIO()
            with mock.patch.object(config, "REPO_ROOT", self.repo), redirect_stdout(out):
                self.assertEqual(cli.main(["launchd", "installed"]), 0)
            return out.getvalue()
        self.assertIn(f"services installed from {target[:7]}; the Agents page no longer asks for scripts/go-live.sh", installed())
        self.assertEqual(settings.get(self.conn, updater.NEEDS_INSTALL_KEY), "")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE kind='needs_install' AND alerted=0")["n"], 0)
        self.assertIn("nothing was waiting on it", installed())
        self.commit("launchd/com.example.other.plist.template", "<plist/>")
        self.run_updater()
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE kind='needs_install' AND alerted=0")["n"], 1,
                         "the next update with new service files asks again")


class Sync(Repos):
    """`ccs sync`: go-live's first step, proven on real repositories like the updater itself."""

    def setUp(self):
        super().setUp()
        real = updater.run
        self.suite_ok = True

        self.deploys = []

        def fake_run(ctx, **kw):
            return real(ctx, repo=self.repo,
                        suite=lambda wt: (self.suite_ok, "Ran 3 tests" if self.suite_ok else "FAILED (failures=1)"),
                        requirements=lambda r, w: None, migrations=lambda r: None,
                        restart=lambda: "dashboard: restarted", probe=lambda: self.dash,
                        deploy=lambda repo: (self.deploys.append(1), (True, "LIVE"))[1], **kw)
        self.sleeps = []
        self.on_sleep = lambda s: None
        self.wait_seconds = 30 * 60

        def sleeping(s):
            self.sleeps.append(s)
            self.on_sleep(s)
        # the sync's own waits only: a patched time.sleep also caught subprocess's busy-wait inside a git
        # call on a slow runner (CI, 2026-10-11: [15, 15, 0.001])
        for target, value in (("convention_social.agents.updater.run", fake_run),
                              ("convention_social.core.config.REPO_ROOT", self.repo),
                              ("convention_social.cli.cmd_sync", lambda a: updater.sync(sleep=sleeping, wait_seconds=self.wait_seconds))):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sync(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(["sync"])
        return code, out.getvalue()

    def test_up_to_date_says_so(self):
        code, out = self.sync()
        self.assertEqual(code, 0)
        self.assertIn(f"code: {self.head()[:7]} on main, the same as GitHub main", out)
        self.assertEqual(self.sleeps, [])

    def test_a_green_new_commit_is_tested_and_switched_to(self):
        target = self.commit("b.txt", "two")
        code, out = self.sync()
        self.assertEqual((code, self.head()), (0, target))
        self.assertIn(f"code: {target[:7]} on main, the same as GitHub main", out)
        run = db.one(self.conn, "SELECT dry_run, ok, summary FROM agent_runs WHERE agent='updater' ORDER BY id DESC")
        self.assertEqual((run["dry_run"], run["ok"]), (0, 1), "live, whatever the updater's dry-run flag says")
        self.assertIn("tests passed", run["summary"])

    def test_red_tests_leave_the_checkout_where_it_was_and_say_why(self):
        before = self.head()
        self.commit("b.txt", "broken")
        self.suite_ok = False
        code, out = self.sync()
        self.assertEqual((code, self.head()), (1, before))
        self.assertIn("1 commit(s) BEHIND GitHub main", out)
        self.assertIn("not brought up to date: held back", out)

    def test_local_changes_stop_it_with_the_reason(self):
        self.commit("b.txt", "two")
        (self.repo / "a.txt").write_text("edited on the Mini")
        code, out = self.sync()
        self.assertEqual(code, 1)
        self.assertIn("(with local changes)", out)
        self.assertIn("not brought up to date: not updating: the checkout has local changes", out)

    def test_waits_for_a_running_updater_instead_of_failing(self):
        lock = runner.Lock("updater")
        self.assertTrue(lock.acquire())
        self.addCleanup(lock.release)
        self.on_sleep = lambda s: lock.release() if len(self.sleeps) == 2 else None
        code, out = self.sync()
        self.assertEqual(code, 0)
        self.assertEqual(self.sleeps, [15, 15])
        self.assertIn("the updater is running now", out)
        self.assertIn("the same as GitHub main", out)

    def test_an_updater_that_never_finishes_is_reported(self):
        lock = runner.Lock("updater")
        self.assertTrue(lock.acquire())
        self.addCleanup(lock.release)
        self.wait_seconds = 30
        code, out = self.sync()
        self.assertEqual(code, 1)
        self.assertEqual(self.sleeps, [15, 15])
        self.assertIn("the updater is still running; run this again", out)


class SiteFollows(Repos):
    """Chris, 2026-10-12: "do what you can without needing me to respond or terminal anything". The site
    on Cloudflare follows the code: deployed by the updater when a merge changes it, once when the suite
    has never deployed it, never twice for the same commit, and a failure is told and left for Publish."""

    def setUp(self):
        super().setUp()
        (self.repo / "wrangler.live.jsonc").write_text("{}")             # go-live ran here once
        patcher = mock.patch("convention_social.site.deploy.shutil.which", return_value="/opt/homebrew/bin/npx")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_merge_that_changes_the_site_deploys_it_once(self):
        before = self.head()
        target = self.commit("site/theme.css", "body{}")
        line = self.run_updater()
        self.assertIn("tests passed", line)
        self.assertIn(f"site: deployed (1 site file(s) changed since {before[:7]})", line)
        self.assertEqual(self.calls["deploy"], [target], "deployed from the NEW checkout")
        self.assertEqual(settings.get(self.conn, site_deploy.DEPLOYED_KEY), target)
        self.assertIn(f"site: the site is on {target[:7]}, the same as the code", self.run_updater())
        self.assertEqual(len(self.calls["deploy"]), 1, "never twice for one commit")

    def test_a_merge_off_the_site_is_not_deployed(self):
        target = self.commit("a.txt", "two")
        before = settings.get(self.conn, site_deploy.DEPLOYED_KEY)
        line = self.run_updater()
        self.assertIn(f"site: nothing since {before[:7]} changes the site", line)
        self.assertEqual(self.calls["deploy"], [])
        self.assertEqual(settings.get(self.conn, site_deploy.DEPLOYED_KEY), target, "the record moves with the code")

    def test_a_site_never_deployed_by_the_suite_is_deployed_on_the_next_pass(self):
        # the first pass after this arrives: an older updater did the merge, the site on Cloudflare is older still
        settings.set(self.conn, site_deploy.DEPLOYED_KEY, "")
        line = self.run_updater()
        self.assertIn("up to date", line)
        self.assertIn("site: deployed (the suite has not deployed the site yet)", line)
        self.assertEqual(self.calls["deploy"], [self.head()])

    def test_a_failed_deploy_is_an_error_and_waits_for_publish(self):
        self.deploy_ok = False
        target = self.commit("offer.json", "{}")
        line = self.run_updater()
        self.assertIn("site: deploy FAILED (1 site file(s) changed", line)
        err = db.one(self.conn, "SELECT kind, message FROM errors WHERE agent='updater' AND kind='site_deploy'")
        self.assertIn("Press Publish on the Photos page", err["message"])
        self.assertIn("Cloudflare did not take the deploy", err["message"])
        self.assertEqual((site_deploy.failure_record(self.conn)["commit"], site_deploy.failure_record(self.conn)["tries"]), (target, 1))
        self.assertIn(f"site: the deploy of {target[:7]} failed (try 1 of 3); trying again 30 minutes after", self.run_updater())
        self.assertEqual(len(self.calls["deploy"]), 1)
        rec = site_deploy.failure_record(self.conn)
        rec["last_at"] = (datetime.now() - timedelta(minutes=31)).isoformat(timespec="seconds")
        settings.set(self.conn, site_deploy.FAILED_KEY, json.dumps(rec))
        self.assertIn("site: deploy FAILED", self.run_updater(), "tried again on its own after half an hour")
        self.assertEqual(len(self.calls["deploy"]), 2)
        self.assertEqual(site_deploy.failure_record(self.conn)["tries"], 2)
        settings.set(self.conn, site_deploy.DEPLOYED_KEY, target)        # Publish succeeded (site/deploy.py records it)
        settings.set(self.conn, site_deploy.FAILED_KEY, "")
        self.assertIn("the same as the code", self.run_updater())

    def test_dry_run_only_says_it_would_deploy(self):
        settings.set(self.conn, site_deploy.DEPLOYED_KEY, "")
        self.assertIn("DRY RUN site: the suite has not deployed the site yet; would deploy", self.run_updater(dry=True))
        self.assertEqual(self.calls["deploy"], [])

    def test_without_a_go_live_the_site_is_behind_and_said_so(self):
        (self.repo / "wrangler.live.jsonc").unlink()
        settings.set(self.conn, site_deploy.DEPLOYED_KEY, "")
        line = self.run_updater()
        self.assertIn("site: behind the code, not deployable here (no wrangler.live.jsonc", line)
        self.assertEqual(self.calls["deploy"], [])
        err = db.one(self.conn, "SELECT message FROM errors WHERE agent='updater' AND kind='site_deploy'")
        self.assertIn("run scripts/go-live.sh once on the Mini", err["message"])
        self.run_updater()
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE kind='site_deploy'")["n"], 1, "one open line, not one per pass")


class SyncLeavesTheSite(Repos):
    """go-live's first step (`ccs sync`) brings the code over and leaves the site to go-live's own deploy step."""

    def test_sync_never_deploys_the_site(self):
        settings.set(self.conn, site_deploy.DEPLOYED_KEY, "")
        (self.repo / "wrangler.live.jsonc").write_text("{}")
        deploys = []
        real = updater.run

        def fake_run(ctx, **kw):
            return real(ctx, repo=self.repo, suite=lambda wt: (True, "Ran 3 tests"), requirements=lambda r, w: None,
                        migrations=lambda r: None, restart=lambda: "dashboard: restarted", probe=lambda: self.dash,
                        deploy=lambda repo: (deploys.append(1), (True, "LIVE"))[1], **kw)
        with mock.patch("convention_social.agents.updater.run", fake_run), \
             mock.patch("convention_social.core.config.REPO_ROOT", self.repo), \
             mock.patch("convention_social.site.deploy.shutil.which", return_value="/opt/homebrew/bin/npx"):
            self.assertEqual(updater.sync(sleep=lambda s: None, say=lambda s: None), 0)
        self.assertEqual(deploys, [])
        run = db.one(self.conn, "SELECT summary FROM agent_runs WHERE agent='updater' ORDER BY id DESC")
        self.assertNotIn("site:", run["summary"])
