"""What the watchdog's first real alerts (2026-10-11, 4:38 PM) uncovered: the dashboard out of file
handles on the Photos tab, a thumbnail half written while another request read it, and a scanner run
that went on for hours while the watchdog called it "last ran"."""
from __future__ import annotations

import logging
import resource
import threading
import time
from datetime import timedelta

from convention_social.agents import watchdog
from convention_social.core import config, db, limits, runner
from convention_social.dashboard import app as dash
from convention_social.drive import scan
from convention_social.drive.api import DriveReader
from convention_social.library import classify
from tests._base import IsolatedCase
from tests.test_library import _ollama_ok, library
from tests.test_watchdog import NOON_UTC


class OpenFiles(IsolatedCase):
    def test_the_soft_limit_is_raised_as_far_as_the_system_allows(self):
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, hard))          # what macOS gives a launchd process
            got = limits.raise_open_files()
            want = limits.OPEN_FILES_WANTED if hard == resource.RLIM_INFINITY else min(limits.OPEN_FILES_WANTED, hard)
            self.assertEqual(got, want)
            self.assertEqual(resource.getrlimit(resource.RLIMIT_NOFILE)[0], want)
        finally:
            resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


class Thumbs(IsolatedCase):
    def test_one_fetch_per_photo_however_many_ask_and_the_file_lands_whole(self):
        calls = []
        data = b"\xff\xd8" + b"x" * 50_000

        def fetch(drive_id):
            calls.append(drive_id)
            time.sleep(0.3)
            return data
        got = []
        threads = [threading.Thread(target=lambda: got.append(dash.cached_thumb("d1", fetch))) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(calls, ["d1"], "six requests, one Drive fetch")
        self.assertEqual(len(got), 6)
        self.assertTrue(all(p == got[0] for p in got))
        self.assertEqual(got[0].read_bytes(), data)
        self.assertEqual([p.name for p in got[0].parent.iterdir()], ["d1.jpg"], "no part file is left behind")

    def test_nothing_to_show_is_none_and_a_bad_file_is_fetched_again(self):
        self.assertIsNone(dash.cached_thumb("d2", None))

        def fails(drive_id):
            raise ConnectionError("Drive is down")
        self.assertIsNone(dash.cached_thumb("d2", fails))
        folder = config.get_config().data_root / "thumbs"
        folder.mkdir(parents=True)
        (folder / "d3.jpg").write_bytes(b"")                           # left by a run that died mid-way
        self.assertEqual(dash.cached_thumb("d3", lambda d: b"fresh").read_bytes(), b"fresh")


class Stuck(IsolatedCase):
    def test_a_run_that_never_finished_is_called_stuck_not_last_ran(self):
        conn = db.connect()
        ctx = runner.Context("watchdog", conn, logging.getLogger("t"), config.get_config(), True, 0)
        db.insert(conn, "agent_runs", agent="scanner", started_at=(NOON_UTC - timedelta(hours=4)).isoformat(), dry_run=0)
        f = watchdog.Findings()
        watchdog.check_agents(ctx, f, NOON_UTC)
        codes = dict(f.alerts)
        self.assertIn("agent_stuck:scanner", codes)
        self.assertIn("has not finished", codes["agent_stuck:scanner"])
        self.assertNotIn("agent_missed:scanner", codes)
        conn.execute("UPDATE agent_runs SET finished_at=?, ok=1", ((NOON_UTC - timedelta(hours=3)).isoformat(),))
        f = watchdog.Findings()
        watchdog.check_agents(ctx, f, NOON_UTC)
        self.assertIn("agent_missed:scanner", dict(f.alerts))
        conn.close()


class Budget(IsolatedCase):
    def test_the_sort_pass_stops_at_its_time_budget_and_says_so(self):
        conn = db.connect()
        reader = DriveReader("tok", conn=conn, transport=library())
        scan.full_inventory(conn, reader)
        classify.folder_pass(conn)
        self.assertGreaterEqual(len(classify.queue(conn, 500)), 3)
        ticks = iter(range(0, 10_000, 25))                               # 25 s a photo
        st = classify.sort_pass(conn, reader.thumbnail_for, sorter=classify.OllamaSorter("m", post=_ollama_ok),
                                budget_seconds=60, clock=lambda: next(ticks))
        self.assertEqual(st.done, 2)
        self.assertIn("1 minute budget", st.stopped)
        rest = classify.sort_pass(conn, reader.thumbnail_for, sorter=classify.OllamaSorter("m", post=_ollama_ok))
        self.assertGreater(rest.done, 0, "the rest is sorted on the next run")
        self.assertEqual(rest.stopped, "")
        conn.close()


class Wiring(IsolatedCase):
    """The fixes are only fixes where they are called."""

    def test_the_dashboard_and_every_agent_raise_the_limit_at_start(self):
        import os
        from unittest import mock
        from convention_social import cli
        with mock.patch("uvicorn.run") as serve, mock.patch.object(limits, "raise_open_files") as raised:
            cli.main(["dashboard"])
        self.assertEqual((serve.call_count, raised.call_count), (1, 1))
        with mock.patch("convention_social.core.limits.raise_open_files") as raised:
            runner.run("scanner", lambda ctx: "ok")
        self.assertEqual(raised.call_count, 1)

    def test_the_scanner_gives_the_sort_pass_its_budget(self):
        import os
        from unittest import mock
        from convention_social.agents import scanner
        conn = db.connect()
        seen = {}

        def fake_pass(conn_, fetch, **kw):
            seen.update(kw)
            return classify.PassStats()
        sorter = classify.OllamaSorter("m", post=_ollama_ok)
        for env, want in ((None, 45 * 60), ("10", 600)):
            if env:
                os.environ["SCAN_BUDGET_MINUTES"] = env
                config.reset()
            ctx = runner.Context("scanner", conn, logging.getLogger("t"), config.get_config(), True, 0)
            with mock.patch.object(classify, "pick_sorter", return_value=sorter), mock.patch.object(classify, "sort_pass", fake_pass):
                scanner.run(ctx, reader=DriveReader("tok", conn=conn, transport=library()))
            self.assertEqual(seen["budget_seconds"], want)
        conn.close()
