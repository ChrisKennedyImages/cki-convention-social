"""Nothing from another company's suite may live in this repo.

Every file in the tree (code, templates, docs, tests, config) and every file
name is scanned, case-insensitively, for the names, ids, domains, buckets and
topics of the other suites this one was built beside. The list is stored
base64-encoded so this file does not trip its own scan. Add to it; never
remove from it.

One allowance (Chris, 2026-10-31, asked twice and told nothing outside this
repo is touched): the two schema.org field names Google's image metadata
asks for, "license" and "acquireLicensePage", pass as whole words. Every
other form of that word, and every other word on the list, still trips.

And the OFL texts the reel looks ship beside their fonts
(reel-looks/public/fonts/*-OFL.txt, 2026-11-08): the SIL Open Font terms must
travel with the fonts word for word, so in those files, and only those, that
one word passes in every form. Every other word on the list still trips there
too.
"""
from __future__ import annotations

import base64
import os
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".wrangler"}
SKIP_FILES = {"package-lock.json"}        # npm's own text, never ours
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".woff", ".woff2", ".ttf", ".otf", ".sqlite3"}
MEDIA_SUFFIXES = {".mp4", ".mov", ".m4a", ".mp3", ".wav"}   # compressed sound and video: any four letters occur by chance

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
            if name not in SKIP_FILES and Path(name).suffix.lower() not in MEDIA_SUFFIXES:
                yield Path(dirpath) / name


ALLOWED = re.compile(r"\b(license|acquirelicensepage)\b")     # the two schema.org names, whole words only
OFL_TEXTS = re.compile(r"(^|/)reel-looks/public/fonts/[A-Za-z]+-OFL\.txt$")
OFL_WORD = BANNED[3]                                           # the one word the fonts' OFL texts must carry


def hits_in(text: str, *, ofl_text: bool = False) -> list[str]:
    low = ALLOWED.sub("", text.lower())
    return [w for w in BANNED if w in low and not (ofl_text and w == OFL_WORD)]


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

    def test_the_two_schema_org_names_pass_and_nothing_near_them_does(self):
        self.assertEqual(hits_in('"license": "https://x/contact/", "acquireLicensePage": "https://x/contact/"'), [])
        # the near forms are stored encoded, like the list, so this file does not trip its own scan
        for near in ("bGljZW5zZWQ=", "bGljZW5zaW5n", "bGljZW5jZQ==", "YWNxdWlyZUxpY2Vuc2VQYWdlcw=="):
            word = base64.b64decode(near).decode()
            self.assertTrue(hits_in(word), word)

    def test_an_ofl_text_passes_its_one_word_and_nothing_else(self):
        """reel-looks/public/fonts/*-OFL.txt carry the SIL Open Font terms word for word; any other banned word still trips
        there, and that word still trips in every other file."""
        word = base64.b64decode("bGljZW5zZWQ=").decode()
        self.assertEqual(hits_in(f"This Font Software is {word} under the SIL Open Font License", ofl_text=True), [])
        self.assertTrue(hits_in(word))
        self.assertTrue(hits_in(BANNED[0], ofl_text=True))
        self.assertTrue(OFL_TEXTS.search("reel-looks/public/fonts/Anton-OFL.txt"))
        for elsewhere in ("reel-looks/src/fonts.ts", "reel-looks/public/fonts/notes.txt", "docs/Anton-OFL.txt"):
            self.assertFalse(OFL_TEXTS.search(elsewhere), elsewhere)

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
            for w in hits_in(data, ofl_text=bool(OFL_TEXTS.search(rel.as_posix()))):
                found.append(f"{rel}: {w}")
        self.assertEqual(found, [], "words from another suite found:\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
