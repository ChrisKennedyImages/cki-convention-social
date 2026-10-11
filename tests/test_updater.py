"""The updater (Chris, 2026-10-11: no more typing commands on the Mini to update it). Proven against
real git repositories in a temporary folder: it tests the candidate commit before switching, only
fast-forwards a clean `main`, holds back on red tests, and never touches local work."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from convention_social.agents import updater
from convention_social.core import config, db, runner, settings
from tests._base import IsolatedCase

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.org"]


def git(cwd, *args):
    return subprocess.run(["git", *GIT_ID, *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


class Updater(IsolatedCase):
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
        self.calls = {"suite": [], "migrate": 0, "restart": 0, "requirements": 0}

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

    def run_updater(self, dry=False, suite_ok=True):
        def suite(worktree):
            self.calls["suite"].append({"files": sorted(p.name for p in worktree.iterdir()),
                                        "b": (worktree / "b.txt").read_text() if (worktree / "b.txt").exists() else None})
            return suite_ok, "Ran 3 tests" if suite_ok else "FAILED (failures=1)"

        def requirements(repo, worktree):
            self.calls["requirements"] += 1

        def migrations(repo):
            self.calls["migrate"] += 1

        def restart():
            self.calls["restart"] += 1
            return "dashboard: restarted"

        ctx = runner.Context("updater", self.conn, None, config.get_config(), dry, 0)
        return updater.run(ctx, repo=self.repo, suite=suite, requirements=requirements, migrations=migrations, restart=restart)

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")

    def test_up_to_date_does_nothing(self):
        self.assertIn("up to date", self.run_updater())
        self.assertEqual(self.calls["suite"], [])

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

    def test_github_out_of_reach_is_an_error_not_a_crash(self):
        git(self.repo, "remote", "set-url", "origin", str(self.root / "nowhere.git"))
        self.assertEqual(self.run_updater(), "fetch failed")
        self.assertEqual(db.one(self.conn, "SELECT kind FROM errors WHERE agent='updater'")["kind"], "update_fetch")


class RestartDashboard(IsolatedCase):
    def test_only_the_suites_dashboard_is_ever_signalled(self):
        pid_file = self.root / "dashboard.pid"
        pid_file.write_text(str(os.getpid()))                  # this test process is not a dashboard
        self.assertEqual(updater.restart_dashboard(pid_file), "dashboard: not running")
        fake = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "convention_social.cli", "dashboard"])
        try:
            pid_file.write_text(str(fake.pid))
            time.sleep(0.2)
            self.assertEqual(updater.restart_dashboard(pid_file), "dashboard: restarted")
            self.assertIsNotNone(fake.wait(timeout=5))
        finally:
            if fake.poll() is None:
                fake.kill()
        self.assertIn("no pid file", updater.restart_dashboard(self.root / "missing.pid"))
