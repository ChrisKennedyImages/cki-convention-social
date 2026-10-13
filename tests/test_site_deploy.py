"""eventcaliber.com goes live from the Mini with nobody at a terminal (Chris, 2026-10-12: "do what you
can without needing me to respond or terminal anything"): `ccs site deploy`, the Publish button, and
the status card they both write for the Photos page."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import types
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from convention_social import cli
from convention_social.core import auth, config, db, runner, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.site import deploy
from tests._base import IsolatedCase
from tests.test_updater import Repos

REAL_START = deploy.start_in_background          # taken before any fixture patches it


def done(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess(["x"], code, stdout, stderr)


class Ready(IsolatedCase):
    def test_needs_the_live_config_from_go_live_and_node(self):
        repo = self.root / "repo"
        repo.mkdir()
        ok, why = deploy.ready(repo)
        self.assertFalse(ok)
        self.assertIn("no wrangler.live.jsonc on this machine: run scripts/go-live.sh once on the Mini", why)
        (repo / "wrangler.live.jsonc").write_text("{}")
        with mock.patch("convention_social.site.deploy.shutil.which", return_value=None):
            ok, why = deploy.ready(repo)
        self.assertFalse(ok)
        self.assertIn("npx is not on PATH", why)
        with mock.patch("convention_social.site.deploy.shutil.which", return_value="/opt/homebrew/bin/npx"):
            self.assertEqual(deploy.ready(repo), (True, "ready"))


class Status(IsolatedCase):
    def test_written_atomically_and_a_dead_run_reads_as_failed(self):
        self.assertEqual(deploy.read_status(), {})
        deploy.write_status("running", "building the pages", commit="abc")
        st = deploy.read_status()
        self.assertEqual((st["state"], st["message"], st["commit"]), ("running", "building the pages", "abc"))
        self.assertFalse(list((config.get_config().data_root / "site").glob("*.part")))
        old = (datetime.now() - timedelta(seconds=deploy.STALE_RUNNING + 60)).isoformat(timespec="seconds")
        (config.get_config().data_root / "site" / deploy.STATUS_FILE).write_text(json.dumps({"state": "running", "message": "x", "at": old}))
        st = deploy.read_status()
        self.assertEqual(st["state"], "failed")
        self.assertIn("stopped before it finished; press Publish again", st["message"])


class Wanted(Repos):
    def test_the_record_decides(self):
        head = self.head()
        self.assertEqual(deploy.wanted(self.conn, self.repo), (False, f"the site is on {head[:7]}, the same as the code"))
        settings.set(self.conn, deploy.DEPLOYED_KEY, "")
        self.assertEqual(deploy.wanted(self.conn, self.repo), (True, "the suite has not deployed the site yet"))
        settings.set(self.conn, deploy.DEPLOYED_KEY, "0" * 40)
        self.assertEqual(deploy.wanted(self.conn, self.repo), (True, f"the site was built from {'0' * 7}, which this checkout no longer has"))
        settings.set(self.conn, deploy.DEPLOYED_KEY, "")
        t0 = datetime(2026, 10, 13, 12, 0)
        self.assertEqual(deploy.record_failure(self.conn, head, now=t0), 1)
        want, why = deploy.wanted(self.conn, self.repo, now=t0 + timedelta(minutes=5))
        self.assertFalse(want)
        self.assertIn("failed (try 1 of 3); trying again 30 minutes after", why)
        want, why = deploy.wanted(self.conn, self.repo, now=t0 + timedelta(minutes=31))
        self.assertTrue(want)
        self.assertIn("failed (try 1 of 3); trying again", why)
        self.assertEqual(deploy.record_failure(self.conn, head, now=t0 + timedelta(minutes=31)), 2)
        self.assertEqual(deploy.record_failure(self.conn, head, now=t0 + timedelta(minutes=62)), 3)
        want, why = deploy.wanted(self.conn, self.repo, now=t0 + timedelta(hours=3))
        self.assertFalse(want)
        self.assertIn("failed 3 times; not trying again by itself (Publish on the Photos page does)", why)
        self.assertEqual(deploy.record_failure(self.conn, "f" * 40, now=t0), 1, "a new commit starts its own count")
        settings.set(self.conn, deploy.FAILED_KEY, head)                 # the record an older suite left: one failure, no time
        self.assertTrue(deploy.wanted(self.conn, self.repo, now=t0)[0])
        self.assertEqual(deploy.wanted(self.conn, self.root / "not-a-repo"), (False, "not a git checkout"))

    def test_only_a_site_file_between_the_two_commits_counts(self):
        first = self.head()
        self.commit("convention_social/agents/content.py", "# agent")
        subprocess.run(["git", "-C", str(self.repo), "pull", "-q", "--ff-only"], check=True)
        settings.set(self.conn, deploy.DEPLOYED_KEY, first)
        want, why = deploy.wanted(self.conn, self.repo)
        self.assertFalse(want)
        self.assertEqual(why, f"nothing since {first[:7]} changes the site")
        self.assertEqual(settings.get(self.conn, deploy.DEPLOYED_KEY), self.head(), "the record moves to the current code")
        second = self.head()
        self.commit("worker/index.js", "// worker")
        self.commit("convention_social/site/build.py", "# build")
        subprocess.run(["git", "-C", str(self.repo), "pull", "-q", "--ff-only"], check=True)
        want, why = deploy.wanted(self.conn, self.repo)
        self.assertTrue(want)
        self.assertEqual(why, f"2 site file(s) changed since {second[:7]}")


class Run(Repos):
    """build, wrangler, the check from outside, with the real lock, status file and record."""

    def setUp(self):
        super().setUp()
        (self.repo / "wrangler.live.jsonc").write_text("{}")
        patcher = mock.patch("convention_social.site.deploy.shutil.which", return_value="/opt/homebrew/bin/npx")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.said = []
        self.steps = []

    def go(self, *, build=None, deployer=None, checker=None, with_check=True):
        def build_(repo):
            self.steps.append(("build", str(repo)))
            return build or done("built site/dist (hero 1, coverage 3, venues 1)\nhero: your uploaded photo (checked by Claude)\n")

        def deploy_(repo):
            self.steps.append(("deploy", str(repo)))
            return deployer or done("Deployed eventcaliber\n")

        def check_():
            self.steps.append(("check", ""))
            return checker if checker is not None else (True, ["PASS  https://eventcaliber.com/", "PASS  booking API: accepted"])
        return deploy.run(repo=self.repo, conn=self.conn, say=self.said.append, with_check=with_check,
                          build=build_, deploy=deploy_, checker=check_)

    def test_live_records_the_commit_and_the_hero(self):
        settings.set(self.conn, deploy.DEPLOYED_KEY, "")
        settings.set(self.conn, deploy.FAILED_KEY, self.head())
        self.assertEqual(self.go(), 0)
        self.assertEqual([s for s, _ in self.steps], ["build", "deploy", "check"])
        self.assertTrue(all(r == str(self.repo) for s, r in self.steps if s != "check"), "from the checkout, never elsewhere")
        self.assertEqual(settings.get(self.conn, deploy.DEPLOYED_KEY), self.head())
        self.assertEqual(settings.get(self.conn, deploy.FAILED_KEY), "")
        st = deploy.read_status()
        self.assertEqual(st["state"], "done")
        self.assertEqual(st["message"], f"live on {self.head()[:7]}; hero: your uploaded photo (checked by Claude)")
        self.assertEqual(st["hero"], "your uploaded photo (checked by Claude)")
        self.assertIn(f"LIVE on {self.head()[:7]} (hero: your uploaded photo (checked by Claude))", self.said)
        self.assertIn("PASS  https://eventcaliber.com/", self.said)

    def test_no_check_skips_the_check_only(self):
        self.assertEqual(self.go(with_check=False), 0)
        self.assertEqual([s for s, _ in self.steps], ["build", "deploy"])
        self.assertEqual(deploy.read_status()["state"], "done")

    def test_each_failing_step_is_named_and_the_commit_is_not_retried_by_itself(self):
        settings.set(self.conn, deploy.DEPLOYED_KEY, "")
        self.assertEqual(self.go(build=done("Traceback\nValueError: no photos", 1)), 1)
        st = deploy.read_status()
        self.assertEqual((st["state"], st["message"]), ("failed", "the build failed (try 1 of 3)"))
        self.assertIn("ValueError: no photos", st["detail"])
        self.assertEqual((deploy.failure_record(self.conn)["commit"], deploy.failure_record(self.conn)["tries"]), (self.head(), 1))
        self.assertEqual(settings.get(self.conn, deploy.DEPLOYED_KEY), "")
        self.assertEqual([s for s, _ in self.steps], ["build"])
        self.assertIn("not live: the build failed (try 1 of 3)", self.said)

        self.steps.clear()
        self.assertEqual(self.go(deployer=done("", 1, "Authentication error [code: 10000]")), 1)
        self.assertEqual(deploy.read_status()["message"], "Cloudflare did not take the deploy (try 2 of 3)")
        self.assertIn("Authentication error", deploy.read_status()["detail"])
        self.assertEqual([s for s, _ in self.steps], ["build", "deploy"])

        self.steps.clear()
        self.assertEqual(self.go(checker=(False, ["FAIL  https://eventcaliber.com/about/  (404)"])), 1)
        self.assertEqual(deploy.read_status()["message"], "deployed, but the check from outside did not pass (try 3 of 3)")
        self.assertEqual(deploy.failure_record(self.conn)["tries"], 3)
        self.assertIn("FAIL  https://eventcaliber.com/about/", deploy.read_status()["detail"])
        self.assertEqual(settings.get(self.conn, deploy.DEPLOYED_KEY), "", "not recorded as live")

    def test_a_step_that_hangs_is_a_failure_not_a_hang(self):
        def slow(repo):
            raise subprocess.TimeoutExpired(cmd=["npx", "wrangler"], timeout=600)
        self.assertEqual(deploy.run(repo=self.repo, conn=self.conn, say=self.said.append, build=slow), 1)
        self.assertIn("a step took too long (npx, 600s)", deploy.read_status()["message"])
        self.assertEqual(deploy.failure_record(self.conn)["commit"], self.head())

    def test_one_at_a_time_and_never_without_a_go_live(self):
        lock = runner.Lock("site-deploy")
        self.assertTrue(lock.acquire())
        self.addCleanup(lock.release)
        self.assertEqual(self.go(), 2)
        self.assertEqual(self.steps, [])
        self.assertIn("a publish is already running; the Photos page says when it is done", self.said)
        lock.release()
        (self.repo / "wrangler.live.jsonc").unlink()
        self.assertEqual(self.go(), 2)
        self.assertEqual(self.steps, [])
        self.assertEqual(deploy.read_status()["state"], "failed")
        self.assertIn("run scripts/go-live.sh once on the Mini", deploy.read_status()["message"])


class TheCommand(IsolatedCase):
    def test_ccs_site_deploy_runs_it_with_or_without_the_check(self):
        calls = []
        with mock.patch("convention_social.site.deploy.run", side_effect=lambda **kw: (calls.append(kw), 0)[1]):
            self.assertEqual(cli.main(["site", "deploy"]), 0)
            self.assertEqual(cli.main(["site", "deploy", "--no-check"]), 0)
        self.assertEqual([c["with_check"] for c in calls], [True, False])

    def test_the_real_steps_are_the_build_and_the_pinned_wrangler_from_the_checkout(self):
        seen = []

        def fake(cmd, **kw):
            seen.append((cmd, kw.get("cwd"), kw.get("env", {}).get("CLOUDFLARE_ACCOUNT_ID")))
            return done("")
        with mock.patch("convention_social.site.deploy.subprocess.run", side_effect=fake), \
             mock.patch("convention_social.core.secrets.get_secret", side_effect=lambda k: "acct123" if k == "CLOUDFLARE_ACCOUNT_ID" else None):
            deploy._build(Path("/repo"))
            deploy._deploy(Path("/repo"))
        self.assertEqual(seen[0][0], [sys.executable, "-m", "convention_social.cli", "site", "build"])
        self.assertEqual(seen[1][0], ["npx", "--yes", "wrangler@4.149.0", "deploy", "-c", "wrangler.live.jsonc"])
        self.assertEqual({c[1] for c in seen}, {"/repo"})
        self.assertEqual(seen[1][2], "acct123", "the account go-live chose, from .env")
        self.assertEqual(deploy.WRANGLER[2], "wrangler@4.149.0", "the same pin as scripts/go-live.sh")
        self.assertIn("wrangler@4.149.0", (Path(__file__).resolve().parents[1] / "scripts" / "go-live.sh").read_text())

    def test_start_in_background_is_ccs_site_deploy_on_its_own(self):
        # the base fixture patches start_in_background away (no test may start a deploy); REAL_START is the real one
        with mock.patch("convention_social.site.deploy.subprocess.Popen") as popen:
            REAL_START()
        self.assertEqual(popen.call_count, 1)
        args, kw = popen.call_args
        self.assertEqual(args[0], [sys.executable, "-m", "convention_social.cli", "site", "deploy"])
        self.assertEqual(kw["cwd"], str(config.REPO_ROOT))
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(Path(kw["stdout"].name), config.get_config().data_root / "logs" / "site-deploy.log")


class TheCard(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def page(self):
        return self.client.get("/library?view=approved").text

    def test_publish_is_offered_only_where_go_live_has_run(self):
        with mock.patch("convention_social.site.deploy.ready", return_value=(False, "no wrangler.live.jsonc on this machine: run scripts/go-live.sh once on the Mini")):
            page = self.page()
            self.assertIn("<strong>Website</strong>", page)
            self.assertNotIn("Publish the site", page)
            self.assertIn("run scripts/go-live.sh once on the Mini", page)
            r = self.client.post("/site/publish", follow_redirects=False)
            self.assertIn("msg=Not+published%3A+no+wrangler.live.jsonc", r.headers["location"])
            self.assertEqual(deploy.read_status(), {})
        with mock.patch("convention_social.site.deploy.ready", return_value=(True, "ready")):
            page = self.page()
            self.assertIn('<form method="post" action="/site/publish"', page)
            self.assertIn(">Publish the site</button>", page)
            self.assertIn("published by itself after a code change that touches it", page)

    def test_publish_starts_one_run_and_the_card_follows_it(self):
        with mock.patch("convention_social.site.deploy.ready", return_value=(True, "ready")), \
             mock.patch("convention_social.site.deploy.start_in_background") as start:
            r = self.client.post("/site/publish", follow_redirects=False)
            self.assertEqual(r.status_code, 303)
            self.assertIn("msg=Publishing+the+site", r.headers["location"])
            self.assertEqual(start.call_count, 1)
            self.assertEqual(deploy.read_status()["state"], "running")
            page = self.page()
            self.assertIn("Publishing now (started", page)
            self.assertIn("disabled", page[page.index('action="/site/publish"'):][:300])
            r = self.client.post("/site/publish", follow_redirects=False)
            self.assertIn("already+running", r.headers["location"])
            self.assertEqual(start.call_count, 1, "one at a time")
            deploy.write_status("done", "live on abc1234; hero: your uploaded photo (checked by Claude)", commit="abc1234")
            settings.set(self.conn, deploy.DEPLOYED_KEY, "abc1234def")
            page = self.page()
            self.assertIn("Live: live on abc1234; hero: your uploaded photo (checked by Claude)", page)
            self.assertIn("The site is on code abc1234.", page)
            deploy.write_status("failed", "the build failed", detail="ValueError: no photos")
            page = self.page()
            self.assertIn("Not published: the build failed", page)
            self.assertIn("ValueError: no photos", page)
        anon = TestClient(create_app())
        self.assertNotEqual(anon.post("/site/publish", follow_redirects=False).status_code, 303)
