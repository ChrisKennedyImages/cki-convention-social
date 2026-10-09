"""Backup: a readable copy, 14 kept, a second place, and a gzipped copy off the machine under private/."""
from __future__ import annotations

import gzip
import os
import sqlite3
from datetime import datetime

from convention_social.agents import backup
from convention_social.core import config, db, runner, settings
from tests._fakes import AgentCase, make_ctx


class Ok:
    status_code = 200


class Backup(AgentCase):
    def test_readable_copy_pruned_to_fourteen_and_copied_out(self):
        conn = self.connect()
        settings.set(conn, "marker", "kept")
        os.environ["BACKUP_COPY_DIR"] = str(self.root / "second-place")
        config.reset()
        ctx = make_ctx(conn, agent="backup")
        for i in range(16):
            backup.backup_once(ctx, now=datetime(2026, 9, 1 + i, 2, 30))
        self.assertEqual(backup.prune(ctx.cfg.data_root / "backups"), 2)
        files = sorted((ctx.cfg.data_root / "backups").glob("*.sqlite3"))
        self.assertEqual(len(files), 14)
        self.assertEqual(files[0].name, "convention_social-20260903-0230.sqlite3")
        copy = sqlite3.connect(str(files[-1]))
        try:
            self.assertEqual(copy.execute("SELECT value FROM settings WHERE key='marker'").fetchone()[0], "kept")
        finally:
            copy.close()
        copied = backup.copy_out(files[-1])
        self.assertIsNotNone(copied)
        self.assertTrue(copied.exists())
        summary = backup.run(ctx, now=datetime(2026, 10, 9, 2, 30))
        self.assertTrue(summary)
        self.assertIn("backup convention_social-20261009-0230.sqlite3", summary)
        self.assertIn("second-place", summary)
        self.assertIn("off the machine: no", summary)

    def test_off_the_machine_copy_goes_under_private_with_the_token(self):
        conn = self.connect()
        os.environ.update({"MEDIA_BASE_URL": "https://media.example/m", "MEDIA_UPLOAD_TOKEN": "tok"})
        config.reset()
        ctx = make_ctx(conn, agent="backup")
        sent = []

        def put(url, data=None, timeout=None, headers=None):
            sent.append((url, data, headers))
            return Ok()
        friday = datetime(2026, 10, 9, 2, 30)
        summary = backup.run(ctx, now=friday, put=put)
        self.assertTrue(sent)
        url, data, headers = sent[0]
        self.assertEqual(url, "https://media.example/m/private/backups/convention_social-fri.sqlite3.gz")
        self.assertEqual(headers, {"Authorization": "Bearer tok", "Content-Type": "application/gzip"})
        self.assertTrue(gzip.decompress(data).startswith(b"SQLite format 3"))
        self.assertIn("off the machine: private/backups/convention_social-fri.sqlite3.gz", summary)

    def test_a_failed_off_machine_copy_is_an_error_not_a_crash(self):
        conn = self.connect()
        os.environ.update({"MEDIA_BASE_URL": "https://media.example/m", "MEDIA_UPLOAD_TOKEN": "tok"})
        config.reset()
        ctx = make_ctx(conn, agent="backup")

        def refused(url, **kw):
            raise ConnectionError("no route")
        self.assertIn("off the machine: no", backup.run(ctx, put=refused))
        self.assertEqual(db.one(conn, "SELECT kind FROM errors")["kind"], "backup_offsite")

    def test_runner(self):
        conn = self.connect()
        self.assertEqual(runner.run("backup", backup.run), runner.EXIT_OK)
        summary = db.one(conn, "SELECT summary FROM agent_runs ORDER BY id DESC LIMIT 1")["summary"]
        self.assertTrue(summary)
        self.assertIn("BACKUP_COPY_DIR unset", summary)
