"""bin/test with no arguments runs every test file once, in a few processes (bin/test-parallel.py)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def runner():
    spec = importlib.util.spec_from_file_location("test_parallel", REPO / "bin" / "test-parallel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EveryFileOnce(unittest.TestCase):
    def test_the_shares_hold_every_test_file_exactly_once(self):
        files = sorted((REPO / "tests").glob("test_*.py"))
        for n in (1, 2, 8):
            dealt = [f for share in runner().shares(files, n) for f in share]
            self.assertEqual(sorted(dealt), files, n)
            self.assertEqual(len(dealt), len(set(dealt)), n)

    def test_bin_test_hands_the_whole_suite_to_it_and_keeps_one_process_for_a_named_test(self):
        script = (REPO / "bin" / "test").read_text()
        self.assertIn("bin/test-parallel.py", script)
        self.assertIn("if [ $# -eq 0 ]; then", script, "with -k NAME it is one process, as before")

    def test_a_share_that_fails_or_a_file_that_ran_nothing_fails_the_run(self):
        source = (REPO / "bin" / "test-parallel.py").read_text()
        self.assertIn("ok = not bad and not skips and not not_run and not empty and total > 0", source)
