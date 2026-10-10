"""Core engine: config isolation, migrations, fail-closed dry run, runner, mail, secrets, spend."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from convention_social.ai import spend
from convention_social.core import auth, config, db, mail, notify, runner, secrets, settings, state_io
from tests._base import IsolatedCase


class Config(IsolatedCase):
    def test_defaults_are_this_suite(self):
        cfg = config.get_config()
        self.assertEqual(cfg.brand_name, "Event Caliber")
        self.assertEqual(cfg.dashboard_port, 4610)
        self.assertEqual(cfg.data_root, self.root / "data")
        self.assertTrue(str(config.DEFAULT_DATA_ROOT).endswith("cki-convention-social-data"))

    def test_port_is_free_of_the_mini_list(self):
        self.assertNotIn(config.DEFAULT_PORT, (4000, 8090, 8443, 8710, 8765, 11434))

    def test_brand_name_comes_from_env(self):
        os.environ["BRAND_NAME"] = "Another Name"
        config.reset()
        self.assertEqual(config.get_config().brand_name, "Another Name")

    def test_write_env_keeps_other_lines_and_is_private(self):
        path = config.env_file_path()
        path.write_text("# keep me\nA=1\n")
        config.write_env({"A": "2", "B": "has space"})
        text = path.read_text()
        self.assertIn("# keep me", text)
        self.assertIn("A=2", text)
        self.assertEqual(config.getenv("B"), "has space")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_process_env_wins_over_file(self):
        config.env_file_path().write_text("X_TEST=file\n")
        os.environ["X_TEST"] = "env"
        config.reset()
        self.assertEqual(config.getenv("X_TEST"), "env")


class Database(IsolatedCase):
    def test_migrations_apply_once(self):
        conn = db.connect()
        self.assertIn("0001_init", db.applied_versions(conn))
        self.assertEqual(db.migrate(conn), [])
        for t in ("photos", "drive_folders", "classifications", "do_not_use", "credits", "conventions",
                  "content_queue", "channels", "post_history", "api_usage", "agent_runs", "errors", "settings"):
            self.assertIn(t, db.table_names(conn))

    def test_nothing_is_cleared_by_default(self):
        conn = db.connect()
        now = db.utcnow()
        conn.execute("INSERT INTO drive_folders (drive_id, name, first_seen_at, last_seen_at) VALUES ('f1','x',?,?)", (now, now))
        conn.execute("INSERT INTO photos (drive_id, name, folder_id, first_seen_at, last_seen_at) VALUES ('p1','a.jpg','f1',?,?)", (now, now))
        self.assertEqual(db.one(conn, "SELECT clearance FROM drive_folders")["clearance"], "not_cleared")
        self.assertEqual(db.one(conn, "SELECT clearance FROM photos")["clearance"], "inherit")


class DryRun(IsolatedCase):
    def test_defaults_to_dry(self):
        conn = db.connect()
        for agent in settings.AGENTS_WITH_DRY_RUN:
            self.assertTrue(settings.dry_run(conn, agent))

    def test_garbage_value_stays_dry(self):
        conn = db.connect()
        settings.set(conn, "publisher.dry_run", "maybe")
        self.assertTrue(settings.dry_run(conn, "publisher"))
        settings.set_dry_run(conn, "publisher", False)
        self.assertFalse(settings.dry_run(conn, "publisher"))


class Runner(IsolatedCase):
    def test_records_success_and_failure(self):
        self.assertEqual(runner.run("t", lambda ctx: "fine"), runner.EXIT_OK)

        def boom(ctx):
            raise ValueError("nope")
        self.assertEqual(runner.run("t", boom), runner.EXIT_FAILED)
        conn = db.connect()
        runs = db.rows(conn, "SELECT ok, dry_run FROM agent_runs ORDER BY id")
        self.assertEqual([r["ok"] for r in runs], [1, 0])
        self.assertTrue(all(r["dry_run"] == 1 for r in runs))
        self.assertEqual(db.one(conn, "SELECT kind FROM errors")["kind"], "ValueError")

    def test_lock_blocks_a_second_copy(self):
        lock = runner.Lock("t")
        self.assertTrue(lock.acquire())
        try:
            self.assertEqual(runner.run("t", lambda ctx: "x"), runner.EXIT_LOCKED)
        finally:
            lock.release()


class Mail(IsolatedCase):
    def test_tests_never_send(self):
        os.environ["BRAND_FROM_EMAIL"] = "hello@example.org"
        config.reset()
        res = mail.send("Hi there", "<p>x</p>", to="a@example.org", dry_run=False)
        self.assertFalse(res.sent)
        self.assertTrue(res.dry_run)
        self.assertTrue(res.path.exists())
        self.assertIn(mail.SELF_HEADER, res.path.read_text())

    def test_notify_silent_in_tests(self):
        os.environ["NTFY_TOPIC"] = "x"
        config.reset()
        self.assertFalse(notify.push("t", "m", dry_run=False))


class Secrets(IsolatedCase):
    def test_whitespace_stripped_and_never_shown(self):
        os.environ["SMTP_PASSWORD"] = "abcd efgh"
        self.assertEqual(secrets.get_secret("SMTP_PASSWORD"), "abcdefgh")
        self.assertTrue(secrets.present()["SMTP_PASSWORD"])
        self.assertEqual(secrets.KEYCHAIN_SERVICE, "com.chriskennedyimages.conventionsocial")


class Auth(IsolatedCase):
    def test_round_trip(self):
        h = auth.hash_password("correct horse")
        self.assertTrue(auth.verify_password("correct horse", h))
        self.assertFalse(auth.verify_password("wrong", h))
        self.assertFalse(auth.verify_password("x", "garbage"))


class Spend(IsolatedCase):
    def test_rates_and_cap(self):
        self.assertEqual(spend.rate_for("claude-opus-5"), (5.00, 25.00))
        self.assertEqual(spend.rate_for("claude-sonnet-5"), (2.00, 10.00))
        # a dated member is priced by its family prefix, not by a guess
        self.assertEqual(spend.rate_for("claude-haiku-4-5"), (1.00, 5.00))
        self.assertEqual(spend.rate_for("claude-opus-4-8"), (5.00, 25.00))
        self.assertEqual(spend.rate_for("claude-sonnet-4-6"), (3.00, 15.00))
        # an unknown family is never silently priced; cost 0 is what the watchdog flags
        self.assertIsNone(spend.rate_for("claude-mirage-7"))
        self.assertEqual(spend.cost_usd("claude-mirage-7", 1_000_000, 1_000_000), 0.0)
        conn = db.connect()
        self.assertFalse(spend.cap_reached(conn))
        spend.record(conn, "t", "claude-opus-5", 1_000_000, 1_000_000)
        self.assertAlmostEqual(spend.month_to_date(conn, datetime.now(timezone.utc)), 30.0)
        self.assertTrue(spend.cap_reached(conn))

    def test_zero_cap_fails_closed(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        self.assertTrue(spend.cap_reached(db.connect()))


class StateIO(IsolatedCase):
    def test_atomic_save_and_private(self):
        p = self.root / "s.json"
        state_io.save_json(p, {"a": 1}, private=True)
        state_io.save_json(p, {"a": 2}, private=True)
        self.assertEqual(state_io.load_json(p, {}), {"a": 2})
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        p.write_text("{broken")
        self.assertEqual(state_io.load_json(p, {}), {"a": 1})
