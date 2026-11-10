"""One render at a time, nothing left running and nothing left on disk (the 2026-11-09 audit)."""
from __future__ import annotations

import os
import subprocess
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from convention_social.render import reels3d


def alive(pid: int) -> bool:
    return subprocess.run(["ps", "-p", str(pid)], capture_output=True).returncode == 0


class OneRenderAtATime(unittest.TestCase):
    def test_a_render_works_in_a_temp_folder_of_its_own_that_goes_when_it_ends(self):
        r = reels3d.run_remotion(["/bin/sh", "-c", "echo $TMPDIR; touch $TMPDIR/left-behind"], cwd="/tmp", timeout=10)
        scratch = Path(r.stdout.strip())
        self.assertIn("ccs-remotion-", scratch.name)
        self.assertFalse(scratch.exists(), "Remotion's build folder went with the render")

    def test_two_renders_take_turns(self):
        spans = []

        def one():
            began = time.time()
            with reels3d.a_turn():
                took_turn = time.time()
                time.sleep(0.6)
                spans.append((took_turn, time.time()))
            del began
        threads = [threading.Thread(target=one) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        first, second = sorted(spans)
        self.assertGreaterEqual(second[0], first[1], "the second began only when the first had ended")

    def test_a_render_that_waited_its_whole_wait_goes_anyway(self):
        with reels3d.a_turn() as first:
            self.assertTrue(first)
            got = []

            def later():
                with reels3d.a_turn(wait=0, sleep=lambda s: None) as held:
                    got.append(held)
            t = threading.Thread(target=later)
            t.start()
            t.join()
        self.assertEqual(got, [False], "never a reason to make no reel")

    def test_an_error_on_the_way_out_stops_the_render_and_what_it_started(self):
        """An interrupt, or launchd stopping the agent, had left npx, node and Chrome running for weeks."""
        pid_file = Path(os.environ.get("TMPDIR", "/tmp")) / f"ccs-test-child-{os.getpid()}.pid"
        real = subprocess.Popen.communicate

        def interrupted(proc, *a, **kw):
            if kw.get("timeout") is not None:
                for _ in range(100):
                    if pid_file.exists() and pid_file.read_text().strip():
                        break
                    time.sleep(0.05)
                raise KeyboardInterrupt
            return real(proc, *a, **kw)
        try:
            with mock.patch.object(subprocess.Popen, "communicate", interrupted):
                with self.assertRaises(KeyboardInterrupt):
                    reels3d.run_remotion(["/bin/sh", "-c", f"sleep 60 & echo $! > {pid_file}; wait"], cwd="/tmp", timeout=30)
            child = int(pid_file.read_text().strip())
            for _ in range(40):
                if not alive(child):
                    break
                time.sleep(0.05)
            self.assertFalse(alive(child), "the process the render started was stopped with it")
        finally:
            pid_file.unlink(missing_ok=True)
