"""Nothing from another company's suite may live in this repo.

Every file in the tree (code, templates, docs, tests, config) and every file
name is scanned, case-insensitively, for the names, ids, domains, buckets and
topics of the other suites this one was built beside. The list is stored
base64-encoded so this file does not trip its own scan. Add to it; never
remove from it.
"""
from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".wrangler"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".sqlite3"}

ENCODED = (
    "cG9zdG1hcmtldGVk", "Y29udHJhY3Rvcg==", "bWhpYw==", "bGljZW4=", "cHJlc2VudGNhcmU=",
    "YmlkZm9yZ2U=", "aW1hZ2UzNjU=", "YmF5Y291bnRyeWRlY2tz", "YWxsZWdoZW55Y2xpbmlj",
    "c29sb21vbnNyb29maW5n", "cG0tbWVkaWE=", "Y2tpLXNvY2lhbA==", "Y29udmVudGlvbnMtYWdlbnRz",
    "Y2tpLWFnZW50cw==", "Y2FyZWdpdg==", "LnBtMi1ja2k=",
    "NmE3Y2NhNTliZjFlYjRkM2QyOWZkYzUw", "NmE3Y2NhMjI2YTE5MjdlMmQxYTEwMDkz",
)
BANNED = tuple(base64.b64decode(e).decode() for e in ENCODED)


def repo_files():
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            yield Path(dirpath) / name


def hits_in(text: str) -> list[str]:
    low = text.lower()
    return [w for w in BANNED if w in low]


class BannedWords(unittest.TestCase):
    def test_the_list_decodes_and_is_not_empty(self):
        self.assertGreaterEqual(len(BANNED), 18)
        self.assertTrue(all(BANNED))

    def test_the_scan_reads_files(self):
        """A scan that reads nothing passes for the wrong reason."""
        files = [p for p in repo_files() if p.suffix == ".py"]
        self.assertGreater(len(files), 10)

    def test_the_scan_catches_a_planted_word(self):
        self.assertTrue(hits_in("xx" + BANNED[0].upper() + "yy"))

    def test_no_banned_word_anywhere(self):
        found = []
        for path in repo_files():
            rel = path.relative_to(REPO)
            for w in hits_in(str(rel)):
                found.append(f"{rel} (file name): {w}")
            if path.suffix.lower() in BINARY_SUFFIXES:
                data = path.read_bytes().decode("latin-1")
            else:
                try:
                    data = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    data = path.read_bytes().decode("latin-1")
            for w in hits_in(data):
                found.append(f"{rel}: {w}")
        self.assertEqual(found, [], "words from another suite found:\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
