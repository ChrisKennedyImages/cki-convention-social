"""THE LIBRARY IS READ ONLY. These pins fail if any code could write to Drive."""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from convention_social.drive import api, oauth

PKG = Path(__file__).resolve().parents[1] / "convention_social"
WRITE_CALLS = re.compile(r"requests\.(post|put|patch|delete)|\.(post|put|patch|delete)\(|method\s*=\s*['\"](POST|PUT|PATCH|DELETE)", re.I)
WRITE_ENDPOINTS = re.compile(r"/copy\b|/trash|emptyTrash|/permissions|/watch\b|batchUpdate|uploadType|/upload/drive|modifyLabels|generateIds", re.I)


def py_files(root: Path):
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


class DriveIsReadOnly(unittest.TestCase):
    def test_scope_is_exactly_drive_readonly(self):
        self.assertEqual(oauth.SCOPES, ("https://www.googleapis.com/auth/drive.readonly",))

    def test_drive_package_has_no_write_call_or_endpoint(self):
        files = py_files(PKG / "drive")
        self.assertGreaterEqual(len(files), 3)
        for f in files:
            text = f.read_text()
            self.assertIsNone(WRITE_CALLS.search(text), f"{f.name} has a write call")
            self.assertIsNone(WRITE_ENDPOINTS.search(text), f"{f.name} names a write endpoint")

    def test_only_api_py_talks_to_the_drive_api(self):
        hits = [p for p in py_files(PKG) if "googleapis.com/drive" in p.read_text()]
        self.assertEqual([p.name for p in hits], ["api.py"])

    def test_the_only_network_function_is_a_get(self):
        tree = ast.parse((PKG / "drive" / "api.py").read_text())
        calls = {f"{n.func.value.id}.{n.func.attr}" for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)}
        self.assertIn("requests.get", calls)
        self.assertFalse({c for c in calls if c.startswith("requests.") and c != "requests.get"})

    def test_reader_exposes_no_write_methods(self):
        names = {n for n in dir(api.DriveReader) if not n.startswith("_")}
        self.assertTrue(names)
        words = {w for n in names for w in n.lower().split("_")}
        for bad in ("create", "update", "delete", "trash", "move", "rename", "share", "copy", "upload", "patch", "put", "post"):
            self.assertNotIn(bad, words, f"DriveReader has a {bad} method")

    def test_whole_package_never_writes_to_drive(self):
        """No module anywhere builds a Drive write request by hand."""
        for f in py_files(PKG):
            text = f.read_text()
            if "googleapis" in text:
                self.assertIsNone(WRITE_ENDPOINTS.search(text), f"{f} names a Drive write endpoint")

    def test_the_pin_catches_a_planted_write(self):
        self.assertIsNotNone(WRITE_CALLS.search("requests.patch(API + '/files/x')"))
        self.assertIsNotNone(WRITE_ENDPOINTS.search("'/files/x/copy'"))
