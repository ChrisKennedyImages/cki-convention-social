"""The doctor (Chris, 2026-10-15: "a doctor agent too to auto fix anything that fails realtime").

It fixes the suite's known failures by itself, minutes after they happen, checks the same signal again
and says what it did; an exception in our own code becomes one GitHub issue per distinct error and a ping.
It never edits code, never runs git, never restarts anything that is not ours, never deletes outside the
data root, and starts in dry run. No network: Buffer, ntfy and GitHub are fakes here."""
from __future__ import annotations

import functools
import json
import os
import plistlib
import re
import signal
import subprocess
import unittest
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from convention_social.agents import AGENTS, chief, doctor, is_built, updater, watchdog
from convention_social.core import config, db, runner, secrets, settings
from tests._fakes import AgentCase, add_post, make_ctx

NOW = datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc)          # 12:00 in New York, a Thursday
Usage = namedtuple("Usage", "total used free")
PLENTY = Usage(10**12, 10**11, 9 * 10**11)
LOW = Usage(10**12, 10**12 - 2 * 1024**3, 2 * 1024**3)
REPO = Path(__file__).resolve().parents[1]
ISSUES = "https://api.github.com/repos/ChrisKennedyImages/cki-convention-social/issues"

TB = """Traceback (most recent call last):
  File "/Users/chris/Projects/cki-convention-social/convention_social/core/runner.py", line 101, in run
    summary = fn(ctx)
  File "/Users/chris/Projects/cki-convention-social/convention_social/agents/scanner.py", line 52, in run
    seen = rows[0]["id"]
IndexError: list index out of range
"""


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


class Pushes(list):
    """notify.push, recorded: (title, message, keywords)."""

    def __call__(self, title, message, **kw):
        self.append({"title": title, "message": message, **kw})
        return True


class GitHub:
    """The issues API, faked: POST opens #1, #2, ...; GET says open, or closed for the numbers in `closed`."""

    def __init__(self):
        self.calls = []
        self.status = 201
        self.closed = set()
        self.n = 0

    def __call__(self, method, url, headers, body):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if method == "GET":
            num = int(url.rsplit("/", 1)[1])
            return 200, {"number": num, "state": "closed" if num in self.closed else "open"}
        if self.status != 201:
            return self.status, {"message": "Bad credentials"}
        self.n += 1
        return 201, {"number": self.n, "html_url": f"https://github.com/ChrisKennedyImages/cki-convention-social/issues/{self.n}"}

    def posts(self):
        return [c for c in self.calls if c["method"] == "POST"]


class DoctorCase(AgentCase):
    dry = False

    def setUp(self):
        super().setUp()
        os.environ["ALERT_EMAIL"] = "owner@example.org"
        config.reset()
        self.free = PLENTY
        disk = mock.patch.object(watchdog.shutil, "disk_usage", side_effect=lambda path: self.free)
        disk.start()
        self.addCleanup(disk.stop)
        self.conn = self.connect()
        self.ctx = make_ctx(self.conn, agent="doctor", dry_run=self.dry)
        self.cfg = config.get_config()
        self.up = True
        self.pushes = Pushes()
        self.github = GitHub()
        self.start = mock.Mock()
        self.restart = mock.Mock(side_effect=self.fake_restart)
        self.sweep = mock.Mock(side_effect=lambda conn: {"freed_mb": {"originals": 0, "previews": 0, "renders": 0},
                                                         "data_mb": 1.0, "free_gb": self.free.free / 1024**3})
        self.redraw = mock.Mock(side_effect=self.fake_redraw)
        self.track = mock.Mock(return_value=Path("/music/track.mp3"))
        self.hands = doctor.Hands(start=self.start, probe=self.probe, restart=self.restart, push=self.pushes,
                                  github=self.github, sleep=lambda s: None, sweep=self.sweep, redraw=self.redraw,
                                  track=self.track)
        settings.set(self.conn, "drive.auth_state", "ok")
        self.healthy(NOW)

    # ------------------------------------------------------------ the world the doctor reads
    def probe(self, url):
        if not self.up:
            raise ConnectionRefusedError(url)
        return 200

    def fake_restart(self):
        self.up = True
        return True, "stopped the dashboard (pid 4242)"

    def fake_redraw(self, conn, row, meta, *, agent="content"):
        out = self.cfg.data_root / "renders" / "posts" / meta["for_day"]
        out.mkdir(parents=True, exist_ok=True)
        mp4, cover, card = out / f"{row['id']}-rooms.mp4", out / f"{row['id']}-cover.jpg", out / f"{row['id']}-23.jpg"
        for f in (mp4, cover, card):
            f.write_bytes(b"x" * 64)
        meta["music"] = "track.mp3"
        return {"9:16": [str(mp4)], "cover": [str(cover)], "2:3": [str(card)], "stills": []}, "card drawn again with today's words"

    def healthy(self, now, but=()):
        """Every watched agent ran a minute ago and a backup was made just now, except the ones named."""
        for name in watchdog.MAX_GAP:
            if name not in but:
                db.insert(self.conn, "agent_runs", agent=name, started_at=iso(now - timedelta(minutes=1)),
                          finished_at=iso(now - timedelta(seconds=30)), ok=1, dry_run=1)
        if "backup" not in but:
            self.backup_file(now)

    def backup_file(self, when):
        folder = self.cfg.data_root / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        f = folder / f"convention_social-{when:%Y%m%d-%H%M%S}.sqlite3"
        f.write_bytes(b"db")
        os.utime(f, (when.timestamp(), when.timestamp()))
        for old in folder.glob("*.sqlite3"):
            if old.stat().st_mtime > when.timestamp():
                old.unlink()

    def ran(self, name, at, ok=1, summary="ok"):
        db.insert(self.conn, "agent_runs", agent=name, started_at=iso(at), finished_at=iso(at + timedelta(seconds=20)),
                  ok=ok, dry_run=1, summary=summary)

    def doc(self, now=NOW):
        return doctor.run(self.ctx, now=now, hands=self.hands)

    def remedies(self, problem=None):
        sql = "SELECT * FROM doctor_remedies" + (" WHERE problem=?" if problem else "") + " ORDER BY id"
        return [dict(r) for r in db.rows(self.conn, sql, (problem,) if problem else ())]

    def said(self):
        return [p for p in self.pushes if p.get("priority") in ("high", "urgent")]


# ---------------------------------------------------------------------------- the registry

class Registry(AgentCase):
    def test_the_doctor_is_an_agent_every_five_minutes_in_dry_run_until_chris_switches_it(self):
        self.assertEqual(AGENTS["doctor"]["schedule"], "every 5 min")
        self.assertEqual(AGENTS["doctor"]["module"], "convention_social.agents.doctor")
        self.assertTrue(is_built("doctor"))
        self.assertIn("doctor", settings.AGENTS_WITH_DRY_RUN)
        self.assertTrue(settings.dry_run(self.connect(), "doctor"))

    def test_the_watchdog_watches_the_doctor(self):
        self.assertIn("doctor", watchdog.MAX_GAP)
        self.assertLessEqual(watchdog.MAX_GAP["doctor"], timedelta(hours=1))

    def test_its_launchd_template_is_ours_and_runs_every_five_minutes(self):
        path = REPO / "launchd" / "com.chriskennedyimages.conventionsocial.doctor.plist.template"
        plist = plistlib.loads(path.read_bytes())
        self.assertEqual(plist["Label"], "com.chriskennedyimages.conventionsocial.doctor")
        self.assertEqual(plist["StartInterval"], 300)
        self.assertEqual(plist["ProgramArguments"][1:], ["-m", "convention_social.agents.doctor"])
        self.assertEqual(plist["UserName"], "__USER__")
        self.assertEqual(plist["EnvironmentVariables"]["CCS_DATA_ROOT"], "__DATA__")
        self.assertNotIn("KeepAlive", plist)

    def test_the_github_token_is_a_secret_the_keys_page_takes(self):
        self.assertIn("GITHUB_TOKEN", secrets.SECRET_NAMES)
        from fastapi.testclient import TestClient
        from convention_social.core import auth
        from convention_social.dashboard.app import COOKIE, create_app, make_token
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        page = client.get("/keys").text
        self.assertIn('name="GITHUB_TOKEN"', page)
        self.assertIn("Issues", page)


# ---------------------------------------------------------------------------- agents run again

class RunsAgentsAgain(DoctorCase):
    def test_an_overdue_agent_is_run_again_once_and_the_run_is_checked(self):
        self.healthy(NOW, but=("scanner",))
        self.ran("scanner", NOW - timedelta(hours=5))
        line = self.doc()
        self.start.assert_called_once_with("scanner")
        self.assertIn("scanner", line)
        [rem] = self.remedies("agent:scanner")
        self.assertEqual(rem["outcome"], "pending")
        self.assertIn("scanner last ran", rem["found"])

        later = NOW + timedelta(minutes=5)
        self.healthy(later, but=("scanner",))
        self.doc(later)                                            # its run has not happened yet: no second start
        self.start.assert_called_once_with("scanner")

        self.ran("scanner", NOW + timedelta(minutes=6))
        after = NOW + timedelta(minutes=10)
        self.healthy(after, but=("scanner",))
        self.doc(after)
        [rem] = self.remedies("agent:scanner")
        self.assertEqual(rem["outcome"], "fixed")
        self.assertTrue(any("scanner" in p["message"] and p["priority"] == "low" for p in self.pushes))

    def test_a_failed_run_is_run_again(self):
        self.healthy(NOW, but=("learner",))
        self.ran("learner", NOW - timedelta(minutes=30), ok=0, summary="KeyError: 'x'")
        self.doc()
        self.start.assert_called_once_with("learner")
        self.assertIn("failed", self.remedies("agent:learner")[0]["found"])

    def test_a_rerun_that_fails_again_is_not_fixed(self):
        self.healthy(NOW, but=("learner",))
        self.ran("learner", NOW - timedelta(minutes=30), ok=0, summary="KeyError: 'x'")
        self.doc()
        self.ran("learner", NOW + timedelta(minutes=2), ok=0, summary="KeyError: 'x' again")
        later = NOW + timedelta(minutes=5)
        self.healthy(later, but=("learner",))
        self.doc(later)
        self.assertEqual(self.remedies("agent:learner")[0]["outcome"], "not_fixed")
        self.assertIn("again", self.remedies("agent:learner")[0]["detail"])

    def test_at_most_two_agents_are_started_a_pass(self):
        """After a reboot every agent looks overdue at once; the Mini's memory is shared by three suites."""
        self.healthy(NOW, but=("scanner", "learner", "outreach"))
        for name in ("scanner", "learner", "outreach"):
            self.ran(name, NOW - timedelta(days=2))
        self.doc()
        self.assertEqual(self.start.call_count, 2)
        later = NOW + timedelta(minutes=5)
        self.healthy(later, but=("scanner", "learner", "outreach"))
        self.doc(later)
        self.assertEqual(sorted(c.args[0] for c in self.start.call_args_list), ["learner", "outreach", "scanner"])

    def test_content_is_left_to_the_watchdogs_draft_window(self):
        """2026-10-13: the watchdog starts the content agent again inside the day's window, up to four times."""
        self.healthy(NOW, but=("content",))
        self.ran("content", NOW - timedelta(hours=40), ok=0)
        self.doc()
        self.assertNotIn(mock.call("content"), self.start.call_args_list)

    def test_backoff_three_tries_a_day_then_said_once_and_tried_again_tomorrow(self):
        self.healthy(NOW, but=("scanner",))
        self.ran("scanner", NOW - timedelta(hours=5))
        starts = []
        for minutes in (0, 20, 80, 120, 160, 205, 260, 290, 330, 400):
            at = NOW + timedelta(minutes=minutes)
            self.healthy(at, but=("scanner",))
            self.doc(at)
            starts.append((minutes, self.start.call_count))
        # try 1 at once; try 2 once the first was found not fixed (75 min) and 30 min had passed; try 3 two hours later
        self.assertEqual(dict(starts), {0: 1, 20: 1, 80: 2, 120: 2, 160: 2, 205: 3, 260: 3, 290: 3, 330: 3, 400: 3})
        outcomes = [r["outcome"] for r in self.remedies("agent:scanner")]
        self.assertEqual(outcomes, ["not_fixed", "not_fixed", "not_fixed"])
        said = self.said()
        self.assertEqual(len(said), 1, said)                      # once, when the day's tries are used
        self.assertIn("scanner", said[0]["message"])
        self.assertIn("3 time", said[0]["message"])
        err = db.one(self.conn, "SELECT * FROM errors WHERE agent='doctor' AND kind='not_fixed'")
        self.assertIsNotNone(err["notified_at"], "the ping went, so the watchdog does not say it a second time")

        tomorrow = NOW + timedelta(days=1)
        self.healthy(tomorrow, but=("scanner",))
        self.doc(tomorrow)
        self.assertEqual(self.start.call_count, 4)


# ---------------------------------------------------------------------------- the backup and the sweep

class BackupAndSweep(DoctorCase):
    def test_a_stale_backup_runs_the_backup_now_which_runs_the_sweep(self):
        self.healthy(NOW, but=("backup",))
        self.ran("backup", NOW - timedelta(days=4))
        self.backup_file(NOW - timedelta(days=4))
        self.doc()
        self.start.assert_called_once_with("backup")              # one remedy for both signals
        [rem] = self.remedies("backup")
        self.assertIn("sweep", rem["remedy"])
        self.ran("backup", NOW + timedelta(minutes=2))
        self.backup_file(NOW + timedelta(minutes=3))
        later = NOW + timedelta(minutes=10)
        self.healthy(later, but=("backup",))
        self.doc(later)
        self.assertEqual(self.remedies("backup")[0]["outcome"], "fixed")

    def test_low_disk_runs_the_sweep_and_reads_the_disk_again(self):
        self.free = LOW

        def sweep(conn):
            self.free = PLENTY
            return {"freed_mb": {"originals": 900.0, "previews": 0, "renders": 0}, "data_mb": 1.0, "free_gb": 838.0}
        self.sweep.side_effect = sweep
        self.doc()
        self.sweep.assert_called_once_with(self.conn)
        [rem] = self.remedies("disk")
        self.assertEqual(rem["outcome"], "fixed")

    def test_a_sweep_that_cannot_free_enough_is_said_with_what_it_tried(self):
        self.free = LOW
        for minutes in (0, 31, 160):
            at = NOW + timedelta(minutes=minutes)
            self.healthy(at)
            self.doc(at)
        self.assertEqual(self.sweep.call_count, 3)
        self.assertEqual([r["outcome"] for r in self.remedies("disk")], ["not_fixed"] * 3)
        [said] = self.said()
        self.assertIn("sweep", said["message"])
        self.assertIn("not this suite's", said["message"])

    def test_the_sweep_waits_while_the_backup_holds_its_lock(self):
        self.free = LOW
        lock = runner.Lock("backup")
        self.assertTrue(lock.acquire())
        try:
            self.doc()
        finally:
            lock.release()
        self.sweep.assert_not_called()
        self.assertEqual(self.remedies("disk"), [])


# ---------------------------------------------------------------------------- the dashboard

class Dashboard(DoctorCase):
    def test_a_dashboard_that_does_not_answer_is_restarted_and_checked(self):
        self.up = False
        self.doc()
        self.restart.assert_called_once_with()
        [rem] = self.remedies("dashboard")
        self.assertEqual(rem["outcome"], "fixed")

    def test_one_that_answers_on_the_second_look_is_left_alone(self):
        """The updater restarts it after an update; that takes seconds."""
        answers = iter([False, True, True, True])

        def probe(url):
            if not next(answers):
                raise ConnectionRefusedError(url)
            return 200
        self.hands.probe = probe
        self.doc()
        self.restart.assert_not_called()
        self.assertEqual(self.remedies("dashboard"), [])

    def test_still_down_after_the_restart_is_not_fixed(self):
        self.up = False
        self.restart.side_effect = lambda: (True, "stopped the dashboard (pid 4242)")
        self.doc()
        self.assertEqual(self.remedies("dashboard")[0]["outcome"], "not_fixed")

    def test_no_process_of_ours_to_restart_is_said_once_with_the_command(self):
        self.up = False
        self.restart.side_effect = lambda: (False, "No dashboard process of this suite is running.")
        self.doc()
        self.doc(NOW + timedelta(minutes=40))
        [said] = self.said()
        self.assertIn(updater.KICKSTART, said["message"])
        self.assertEqual(self.remedies("dashboard")[0]["outcome"], "cannot")


class OnlyOurs(DoctorCase):
    def test_restart_signals_only_the_dashboard_this_suite_runs(self):
        kills = []
        ok, how = doctor.restart_dashboard(find=lambda: [4242], kill=lambda pid, sig: kills.append((pid, sig)),
                                           alive=lambda pid: False, sleep=lambda s: None)
        self.assertTrue(ok)
        self.assertEqual(kills, [(4242, signal.SIGTERM)])
        self.assertIn("KeepAlive", how)

        kills.clear()
        ok, how = doctor.restart_dashboard(find=lambda: [], kill=lambda pid, sig: kills.append((pid, sig)),
                                           alive=lambda pid: False, sleep=lambda s: None)
        self.assertFalse(ok)
        self.assertEqual(kills, [])

        kills.clear()                                              # a dashboard that will not stop: KILL, the same pid only
        doctor.restart_dashboard(find=lambda: [4242], kill=lambda pid, sig: kills.append((pid, sig)),
                                 alive=lambda pid: True, sleep=lambda s: None)
        self.assertEqual(kills, [(4242, signal.SIGTERM), (4242, signal.SIGKILL)])

    def test_the_finder_is_the_updaters_which_checks_the_command_and_the_folder(self):
        kills = []
        with mock.patch.object(updater, "dashboard_pids", return_value=[]) as find:
            ok, _ = doctor.restart_dashboard(kill=lambda pid, sig: kills.append(pid), alive=lambda pid: False, sleep=lambda s: None)
        find.assert_called_once_with()
        self.assertFalse(ok)
        self.assertEqual(kills, [])

    def test_the_doctor_names_no_label_but_ours_and_runs_no_command(self):
        src = Path(doctor.__file__).read_text()
        labels = re.findall(r"com\.[a-z0-9]+\.[a-z0-9.]+", src)
        self.assertTrue(all(lbl.startswith("com.chriskennedyimages.conventionsocial.") for lbl in labels), labels)
        self.assertNotIn("subprocess", src)
        self.assertNotIn("launchctl", src)
        self.assertNotRegex(src, r"[\"']git[\"']")
        for word in ("unlink(", "rmtree(", "write_text(", "write_bytes(", "os.remove", "rename("):
            self.assertNotIn(word, src, f"the doctor itself writes or deletes no file: {word}")

    def test_a_live_run_with_every_problem_stays_inside_the_data_root_and_runs_no_git(self):
        from convention_social import storage
        outside = self.root / "elsewhere"
        outside.mkdir()
        keep = outside / "keep.img"
        keep.write_bytes(b"not ours")
        old = (NOW - timedelta(days=30)).timestamp()
        os.utime(keep, (old, old))
        cached = self.cfg.data_root / "photos" / "gone.img"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(b"x")
        os.utime(cached, (old, old))
        # every problem at once
        self.healthy(NOW, but=("scanner", "backup"))
        self.ran("scanner", NOW - timedelta(hours=5))
        self.backup_file(NOW - timedelta(days=4))
        self.free = LOW
        self.up = False
        settings.set(self.conn, "drive.auth_state", "expired")
        failed = add_post(self.conn, [1], status="failed")
        self.conn.execute("UPDATE content_queue SET last_error='Buffer HTTP 502: {}', updated_at=? WHERE id=?", (iso(NOW), failed))
        RemakesReels.reel_draft(self)
        runner.record_error(self.conn, "scanner", "IndexError", "list index out of range", TB)
        os.environ["GITHUB_TOKEN"] = "github_pat_0123456789abcdef"
        config.reset()
        kills = []
        self.hands.restart = functools.partial(doctor.restart_dashboard, find=lambda: [4242],
                                               kill=lambda pid, sig: kills.append((pid, sig)),
                                               alive=lambda pid: False, sleep=lambda s: None)
        self.hands.sweep = storage.sweep
        commands = []
        real_run, real_popen = subprocess.run, subprocess.Popen

        def watch_run(args, *a, **kw):
            commands.append(list(args) if isinstance(args, (list, tuple)) else [args])
            return real_run(args, *a, **kw)

        def watch_popen(args, *a, **kw):
            commands.append(list(args) if isinstance(args, (list, tuple)) else [args])
            return real_popen(args, *a, **kw)
        with mock.patch.object(subprocess, "run", watch_run), mock.patch.object(subprocess, "Popen", watch_popen):
            self.doc()
        self.assertTrue(keep.exists(), "a file outside the data root is never touched")
        self.assertFalse(cached.exists(), "the sweep ran, inside the data root")
        self.assertEqual(kills, [(4242, signal.SIGTERM)])
        self.assertFalse([c for c in commands if c and Path(str(c[0])).name in ("git", "launchctl")], commands)
        self.assertTrue(all(c.args[0] in AGENTS for c in self.start.call_args_list))
        kinds = {r["problem"].split(":")[0] for r in self.remedies()}
        self.assertEqual(kinds, {"agent", "backup", "disk", "dashboard", "post", "reel", "drive", "issue"})


# ---------------------------------------------------------------------------- posts

class RetriesPosts(DoctorCase):
    def failed_post(self, why, **kw):
        qid = add_post(self.conn, [1], status="failed", **kw)
        self.conn.execute("UPDATE content_queue SET last_error=?, approved_at=?, updated_at=? WHERE id=?",
                          (why, iso(NOW - timedelta(hours=3)), iso(NOW - timedelta(minutes=10)), qid))
        return qid

    def row(self, qid):
        return db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))

    def test_a_passing_failure_goes_back_to_the_publisher_for_its_next_slot(self):
        for why in ("Buffer HTTP 502: {}",
                    "HTTPSConnectionPool(host='api.buffer.com', port=443): Read timed out. (read timeout=30)",
                    "Buffer HTTP 429: {}"):
            with self.subTest(why=why):
                qid = self.failed_post(why, scheduled_for="2026-10-15T09:30")
                self.doc()
                row = self.row(qid)
                self.assertEqual(row["status"], "approved")
                self.assertIsNone(row["scheduled_for"], "a time already gone is cleared, so the planner finds the next slot")
                self.assertEqual(row["approved_at"], iso(NOW - timedelta(hours=3)), "his Approve stands")
                self.assertIn("doctor", row["last_error"])
                self.conn.execute("UPDATE content_queue SET status='scheduled', updated_at=? WHERE id=?", (iso(NOW), qid))
                self.doc(NOW + timedelta(minutes=12))
                self.assertEqual(self.remedies(f"post:{qid}")[0]["outcome"], "fixed")

    def test_a_chosen_time_still_ahead_is_kept(self):
        qid = self.failed_post("Buffer HTTP 503: {}", scheduled_for="2026-10-16T10:00")
        self.doc()
        self.assertEqual(self.row(qid)["scheduled_for"], "2026-10-16T10:00")

    def test_a_post_buffer_refused_is_left_for_chris(self):
        qid = self.failed_post("createPost rejected (InvalidInputError): carousel of mixed media")
        self.doc()
        self.assertEqual(self.row(qid)["status"], "failed")
        self.assertEqual(self.remedies(f"post:{qid}"), [])

    def test_a_post_that_reached_buffer_is_never_sent_again(self):
        sent = self.failed_post("Buffer HTTP 502: {}")
        self.conn.execute("UPDATE content_queue SET buffer_post_ids=? WHERE id=?", (json.dumps({"instagram": "b1"}), sent))
        half = self.failed_post("Buffer HTTP 502: {}")
        db.insert(self.conn, "post_history", buffer_post_id="b2", queue_id=half, service="facebook", sent_at=iso(NOW))
        self.doc()
        self.assertEqual(self.row(sent)["status"], "failed")
        self.assertEqual(self.row(half)["status"], "failed")

    def test_failed_again_is_not_fixed(self):
        qid = self.failed_post("Buffer HTTP 502: {}")
        self.doc()
        self.conn.execute("UPDATE content_queue SET status='failed', last_error='Buffer HTTP 502: {}', updated_at=? WHERE id=?",
                          (iso(NOW + timedelta(minutes=10)), qid))
        self.doc(NOW + timedelta(minutes=12))
        self.assertEqual(self.remedies(f"post:{qid}")[0]["outcome"], "not_fixed")


# ---------------------------------------------------------------------------- reels

class RemakesReels(DoctorCase):
    def reel_draft(self, status="draft", for_day="2026-10-17"):
        qid = add_post(self.conn, [1], status=status, render_paths={"4:5": ["/tmp/a.jpg"], "2:3": ["/tmp/b.jpg"]})
        meta = {"for_day": for_day, "design": "carousel", "design_wanted": "reel", "art": {"verdict": "pass"},
                "reel_failed": "CalledProcessError: ffmpeg returned 1"}
        self.conn.execute("UPDATE content_queue SET rule_report=? WHERE id=?", (json.dumps(meta), qid))
        return qid

    def meta(self, qid):
        return json.loads(db.one(self.conn, "SELECT rule_report FROM content_queue WHERE id=?", (qid,))["rule_report"])

    def test_a_reel_that_failed_is_remade_on_its_draft(self):
        qid = self.reel_draft()
        self.doc()
        args = self.redraw.call_args
        self.assertEqual(args.args[2]["design"], "reel")
        paths = json.loads(db.one(self.conn, "SELECT render_paths FROM content_queue WHERE id=?", (qid,))["render_paths"])
        self.assertTrue(Path(paths["9:16"][0]).is_file())
        meta = self.meta(qid)
        self.assertEqual(meta["design"], "reel")
        self.assertNotIn("reel_failed", meta)
        self.assertEqual(meta["reel_remade"]["by"], "doctor")
        self.assertEqual(self.remedies(f"reel:{qid}")[0]["outcome"], "fixed")
        [ping] = [p for p in self.pushes if "reel" in p["message"]]
        self.assertIn(f"/queue/{qid}", ping["click"])
        self.assertNotIn("Approve", ping.get("actions") or "", "the art director has not seen the reel: Open only")

    def test_no_music_no_reel(self):
        """A reel never goes out silent (2026-10-11): the carousel stands."""
        self.track.return_value = None
        qid = self.reel_draft()
        self.doc()
        self.redraw.assert_not_called()
        self.assertEqual(self.meta(qid)["design"], "carousel")
        self.assertEqual(self.remedies(f"reel:{qid}")[0]["outcome"], "cannot")

    def test_an_approved_carousel_is_left_as_he_approved_it(self):
        self.reel_draft(status="approved")
        self.doc()
        self.redraw.assert_not_called()

    def test_a_remake_that_fails_again_keeps_the_carousel(self):
        def fails(conn, row, meta, *, agent="content"):
            meta["design"], meta["reel_failed"] = "carousel", "CalledProcessError: again"
            return {"4:5": ["/tmp/a.jpg"]}, "card drawn again with today's words"
        self.redraw.side_effect = fails
        qid = self.reel_draft()
        self.doc()
        self.assertEqual(self.meta(qid)["design"], "carousel")
        self.assertEqual(self.remedies(f"reel:{qid}")[0]["outcome"], "not_fixed")
        self.assertIn("again", self.remedies(f"reel:{qid}")[0]["detail"])


# ---------------------------------------------------------------------------- Drive

class DriveSignIn(DoctorCase):
    def test_an_expired_sign_in_pings_the_link_once_a_day_and_sees_him_sign_in(self):
        settings.set(self.conn, "drive.auth_state", "expired")
        self.doc()
        [ping] = self.said()
        self.assertTrue(ping["click"].endswith("/drive"), ping)
        self.doc(NOW + timedelta(minutes=30))
        self.assertEqual(len(self.said()), 1)
        settings.set(self.conn, "drive.auth_state", "ok")
        self.doc(NOW + timedelta(minutes=40))
        self.assertEqual(self.remedies("drive")[0]["outcome"], "fixed")


# ---------------------------------------------------------------------------- issues

class FilesIssues(DoctorCase):
    def setUp(self):
        super().setUp()
        os.environ["GITHUB_TOKEN"] = "github_pat_0123456789abcdef"
        os.environ["BUFFER_API_KEY"] = "buffer-secret-value-42"
        config.reset()

    def crash(self, tb=TB, agent="scanner", kind="IndexError", message="list index out of range", at=None):
        eid = runner.record_error(self.conn, agent, kind, message, tb)
        self.conn.execute("UPDATE errors SET ts=? WHERE id=?", (iso(at or NOW - timedelta(minutes=2)), eid))
        return eid

    def test_an_exception_in_our_code_opens_one_issue_and_pings_the_link(self):
        logs = self.cfg.data_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "scanner.log").write_text("".join(f"line {i}\n" for i in range(100)) + "used key buffer-secret-value-42\n")
        self.crash()
        self.doc()
        [call] = self.github.posts()
        self.assertEqual(call["url"], ISSUES)
        self.assertEqual(call["headers"]["Authorization"], "Bearer github_pat_0123456789abcdef")
        body, title = call["body"]["body"], call["body"]["title"]
        self.assertIn("scanner", title)
        self.assertIn("IndexError", title)
        self.assertIn('seen = rows[0]["id"]', body)                      # the traceback
        self.assertIn("12:00", body.replace("11:58", "12:00"))           # the time, local
        self.assertIn("line 99", body)                                   # the last log lines
        self.assertNotIn("line 10\n", body)
        self.assertNotIn("buffer-secret-value-42", body)
        self.assertIn("[BUFFER_API_KEY]", body)
        [ping] = [p for p in self.pushes if "issues/1" in (p.get("click") or "")]
        self.assertIn("#1", ping["message"])
        [rem] = [r for r in self.remedies() if r["problem"].startswith("issue:")]
        self.assertEqual(rem["outcome"], "filed")

    def test_the_same_error_again_is_the_same_issue(self):
        self.crash()
        self.doc()
        moved = TB.replace("line 52", "line 57").replace("line 101", "line 99")
        self.crash(tb=moved, message="list index out of range (post 12)", at=NOW + timedelta(minutes=3))
        self.doc(NOW + timedelta(minutes=5))
        self.assertEqual(len(self.github.posts()), 1)
        row = db.one(self.conn, "SELECT * FROM doctor_issues")
        self.assertEqual(row["seen"], 2)

    def test_a_different_error_is_its_own_issue(self):
        self.crash()
        other = TB.replace("in run\n    seen", "in pick\n    seen").replace("IndexError: list index", "KeyError: 'id'\n#")
        self.crash(tb=other, kind="KeyError", message="'id'")
        self.doc()
        self.assertEqual(len(self.github.posts()), 2)

    def test_an_error_without_a_traceback_is_not_an_issue(self):
        runner.record_error(self.conn, "publisher", "no_channel", "post 3: no connected Buffer channel")
        self.doc()
        self.assertEqual(self.github.calls, [])

    def test_no_token_means_a_ping_instead(self):
        os.environ.pop("GITHUB_TOKEN")
        config.reset()
        self.crash()
        self.doc()
        self.doc(NOW + timedelta(minutes=40))
        self.assertEqual(self.github.calls, [])
        [ping] = [p for p in self.pushes if "GitHub" in p["message"]]
        self.assertIn("Keys page", ping["message"])

    def test_github_refusing_is_said_and_tried_again_later(self):
        self.github.status = 401
        self.crash()
        self.doc()
        err = db.one(self.conn, "SELECT * FROM errors WHERE agent='doctor' AND kind='github_issue'")
        self.assertIn("401", err["message"])
        self.assertNotIn("github_pat_", err["message"])
        self.github.status = 201
        self.doc(NOW + timedelta(minutes=5))                             # inside the backoff: not yet
        self.assertEqual(len(self.github.posts()), 1)
        self.doc(NOW + timedelta(minutes=35))
        self.assertEqual(len(self.github.posts()), 2)
        self.assertTrue(db.one(self.conn, "SELECT url FROM doctor_issues")["url"].endswith("/issues/1"))

    def test_a_closed_issue_that_comes_back_is_filed_again(self):
        self.crash()
        self.doc()
        self.github.closed = {1}
        tomorrow = NOW + timedelta(days=1)
        self.healthy(tomorrow)
        self.crash(at=tomorrow - timedelta(minutes=1))
        self.doc(tomorrow)
        posts = self.github.posts()
        self.assertEqual(len(posts), 2)
        self.assertIn("#1", posts[1]["body"]["body"])

    def test_the_token_is_never_in_a_ping_or_an_issue(self):
        self.crash(tb=TB + "\nAuthorization: Bearer github_pat_0123456789abcdef\n")
        self.doc()
        everything = json.dumps(self.github.calls[0]["body"]) + json.dumps([{k: str(v) for k, v in x.items() if k != "conn"}
                                                                          for x in self.pushes])
        self.assertNotIn("github_pat_0123456789abcdef", everything)


# ---------------------------------------------------------------------------- dry run

class DryRun(DoctorCase):
    dry = True

    def test_dry_run_says_what_it_would_do_and_does_nothing(self):
        self.healthy(NOW, but=("scanner", "backup"))
        self.ran("scanner", NOW - timedelta(hours=5))
        self.backup_file(NOW - timedelta(days=4))
        self.free = LOW
        self.up = False
        settings.set(self.conn, "drive.auth_state", "expired")
        failed = add_post(self.conn, [1], status="failed")
        self.conn.execute("UPDATE content_queue SET last_error='Buffer HTTP 502: {}', updated_at=? WHERE id=?", (iso(NOW), failed))
        reel = RemakesReels.reel_draft(self)
        os.environ["GITHUB_TOKEN"] = "github_pat_0123456789abcdef"
        config.reset()
        runner.record_error(self.conn, "scanner", "IndexError", "list index out of range", TB)
        line = self.doc()
        self.assertTrue(line.startswith("DRY RUN"), line)
        for word in ("scanner", "backup", "sweep", "dashboard", f"post {failed}", "reel", "Drive", "issue"):
            self.assertIn(word, line)
        self.start.assert_not_called()
        self.restart.assert_not_called()
        self.sweep.assert_not_called()
        self.redraw.assert_not_called()
        self.assertEqual(self.github.calls, [])
        self.assertEqual(list(self.pushes), [])
        self.assertEqual(db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (failed,))["status"], "failed")
        self.assertIn("reel_failed", RemakesReels.meta(self, reel))
        self.assertEqual({r["outcome"] for r in self.remedies()}, {"would"})
        n = len(self.remedies())
        self.doc(NOW + timedelta(minutes=5))
        self.assertEqual(len(self.remedies()), n, "the would-lines keep the live cadence: not every five minutes")


# ---------------------------------------------------------------------------- the digest

class Digest(DoctorCase):
    def test_the_digest_and_the_brief_carry_a_line_per_remedy(self):
        self.up = False
        self.doc()
        lines = doctor.digest_lines(self.conn, NOW - timedelta(hours=24))
        self.assertEqual(len(lines), 1)
        self.assertIn("dashboard", lines[0].lower())
        self.assertIn("fixed", lines[0])
        wctx = make_ctx(self.conn, agent="watchdog")
        d = watchdog.digest_data(wctx, NOW + timedelta(minutes=1))
        self.assertEqual(d["doctor"], lines)
        body, _ = watchdog.digest_html(wctx, d, [], NOW)
        self.assertIn(lines[0].split(": ", 1)[1][:30], body)
        cctx = make_ctx(self.conn, agent="chief")
        self.assertTrue(any(lines[0] in x for x in chief.gather(cctx, NOW + timedelta(minutes=1))["done"]))


# ---------------------------------------------------------------------------- the words

class Words(unittest.TestCase):
    def test_founder_decisions_record_his_ask_and_the_scope(self):
        text = (REPO / "FOUNDER_DECISIONS.md").read_text()
        section = text.split("## 2026-10-15: the doctor")[1].split("\n## ")[0]
        for words in ("a doctor agent too to auto fix anything that fails realtime", "agents/doctor.py", "GitHub issue",
                      "never edits", "dry run", "scripts/go-live.sh"):
            self.assertIn(words, section, words)

    def test_setup_names_the_token_and_the_one_go_live(self):
        guide = (REPO / "docs" / "SETUP.md").read_text()
        self.assertIn("GITHUB_TOKEN", guide)
        at = guide.index("GITHUB_TOKEN")
        part = guide[max(0, at - 1500):at + 1500]
        self.assertIn("Issues", part)
        self.assertIn("scripts/go-live.sh", guide.split("doctor", 1)[1])
