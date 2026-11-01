"""Core engine: config isolation, migrations, fail-closed dry run, runner, mail, secrets, spend."""
from __future__ import annotations

import os
import ssl
from datetime import datetime, timedelta, timezone
from unittest import mock

from convention_social.ai import spend
from convention_social.core import auth, config, db, mail, notify, runner, secrets, settings, state_io
from tests._base import IsolatedCase


class FakeSMTP:
    """smtplib.SMTP's part that send() uses, recording each step; `refuse` is raised by starttls, as a bad certificate is."""
    def __init__(self, refuse=None):
        self.steps, self.refuse = [], refuse

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        self.steps.append(("ehlo", None))

    def starttls(self, context=None):
        self.steps.append(("starttls", context))
        if self.refuse:
            raise self.refuse

    def login(self, user, password):
        self.steps.append(("login", user))

    def send_message(self, msg):
        self.steps.append(("send_message", msg["To"]))


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

    def test_write_env_refuses_a_line_break_or_a_bad_key_and_writes_nothing(self):
        """2026-10-24 audit: a value with a line break was written raw, so one Keys field could add any line to .env."""
        path = config.env_file_path()
        path.write_text("A=1\n")
        for bad in ({"A": "x\nINJECTED=1"}, {"A": "x\r\nB=2"}, {"not a key": "x"}, {"A": "x\0"}):
            with self.assertRaises(ValueError):
                config.write_env(bad)
        self.assertEqual(path.read_text(), "A=1\n")

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
    def test_defaults_to_dry_except_the_scout_he_armed(self):
        """Every agent that sends or publishes starts in dry run. The scout only searches (inside the monthly
        cap) and is armed by Chris's choice, 2026-10-13 (migration 0070_scout_armed)."""
        conn = db.connect()
        for agent in settings.AGENTS_WITH_DRY_RUN:
            self.assertEqual(settings.dry_run(conn, agent), agent != "scout", agent)

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

    def live(self, server):
        """send() with live mail allowed and smtplib.SMTP replaced by `server`: nothing leaves the machine."""
        env = {"CCS_ALLOW_LIVE_MAIL_IN_TESTS": "1", "SMTP_HOST": "smtp.gmail.com", "SMTP_USER": "chris@example.org",
               "SMTP_PASSWORD": "not-a-real-password", "BRAND_FROM_EMAIL": "chris@example.org"}
        with mock.patch.dict(os.environ, env), mock.patch.object(mail.smtplib, "SMTP", lambda *a, **kw: server):
            config.reset()
            return mail.send("Hi there", "<p>x</p>", to="a@example.org", dry_run=False)

    def test_the_mail_servers_certificate_and_name_are_checked_before_the_login(self):
        server = FakeSMTP()
        res = self.live(server)
        self.assertTrue(res.sent)
        self.assertEqual([s for s, _ in server.steps], ["ehlo", "starttls", "ehlo", "login", "send_message"])
        context = server.steps[1][1]
        self.assertIsInstance(context, ssl.SSLContext, "starttls is given a context; without one smtplib checks nothing")
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_a_certificate_that_does_not_check_stops_before_the_password_is_sent(self):
        server = FakeSMTP(refuse=ssl.SSLCertVerificationError("certificate verify failed: unable to get local issuer"))
        res = self.live(server)
        self.assertFalse(res.sent)
        self.assertIn("SSLCertVerificationError", res.error)
        self.assertNotIn("login", [s for s, _ in server.steps], "the app password never goes to a server that did not check out")

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
        self.assertAlmostEqual(spend.cycle_to_date(conn, datetime.now(timezone.utc)), 30.0)
        self.assertTrue(spend.cap_reached(conn))

    def test_a_reservation_holds_the_cap_until_the_call_settles(self):
        """8.2 (2026-10-13): cap_reached checked but never reserved, so two agents could each overshoot by one call.
        An in-flight row counts until the call records over it (or is released); a stale one is swept."""
        os.environ["AI_MONTHLY_CAP_USD"] = "1"
        # the cycle starts two days ago at the latest, so a reservation half an hour old is inside it whatever the date
        # (it was backdated to 2026-10-13 and fell out of the cycle when November began, 2026-11-01)
        now = datetime.now(timezone.utc)
        os.environ["AI_CAP_RESETS_ON"] = str((now - timedelta(days=2)).day)
        config.reset()
        conn = db.connect()
        rid = spend.reserve(conn, "content", "claude-opus-5", estimate_usd=0.6)
        self.assertIsNotNone(rid)
        self.assertAlmostEqual(spend.cycle_to_date(conn), 0.6)
        self.assertTrue(spend.cap_reached(conn, about_to_spend=0.6), "a second call of the same size would overshoot: refused while the first is in flight")
        self.assertFalse(spend.cap_reached(conn), "the plain check still reads the ledger as it stands")
        self.assertIsNone(spend.reserve(conn, "scout", "claude-opus-5", estimate_usd=0.6), "the second agent cannot reserve past the cap")
        cost = spend.record(conn, "content", "claude-opus-5", 10_000, 1_000, "caption", reservation=rid)
        self.assertAlmostEqual(cost, 0.075)
        rows = db.rows(conn, "SELECT agent, cost_usd, detail FROM api_usage")
        self.assertEqual(len(rows), 1, "the reservation row became the real one, not a second row")
        self.assertAlmostEqual(rows[0]["cost_usd"], 0.075)
        self.assertIn("caption", rows[0]["detail"])
        self.assertNotIn("reserved", rows[0]["detail"])
        rid2 = spend.reserve(conn, "scout", "claude-opus-5", estimate_usd=0.5)
        self.assertIsNotNone(rid2)
        spend.release(conn, rid2)
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM api_usage")["n"], 1, "a call that failed leaves nothing")
        stale = spend.reserve(conn, "chief", "claude-opus-5", estimate_usd=0.5)
        old = (now - spend.RESERVE_SWEEP - timedelta(minutes=1)).replace(microsecond=0).isoformat()
        conn.execute("UPDATE api_usage SET ts=? WHERE id=?", (old, stale))
        self.assertAlmostEqual(spend.cycle_to_date(conn), 0.575, msg="held until swept")
        self.assertIsNotNone(spend.reserve(conn, "content", "claude-opus-5", estimate_usd=0.1))
        self.assertIsNone(db.one(conn, "SELECT id FROM api_usage WHERE cost_usd=0.5 AND detail LIKE 'reserved %'"),
                          "a reservation older than the sweep window is a crashed call: swept by the next reserve")
        self.assertAlmostEqual(spend.cycle_to_date(conn), 0.175)
        spend.record(conn, "content", "claude-opus-5", 1, 1, "x", reservation=999999)
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM api_usage WHERE detail LIKE '%x'")["n"], 1, "an unknown reservation still records the call")
        conn.close()

    def test_the_cap_counts_from_the_day_the_credit_arrives(self):
        """2026-10-25: Chris's Max plan pays $200 of API credit on the 17th and Anthropic stops every call when it is
        gone. A cap counted from the 1st could spend its whole amount twice inside one credit (late this month, early
        next); counted from the 17th it cannot. Unset, the cap counts from the 1st as it always did."""
        conn = db.connect()
        spend.record(conn, "t", "claude-opus-5", 1_000_000, 0)                                  # $5
        conn.execute("UPDATE api_usage SET ts='2026-10-10T12:00:00+00:00'")
        spend.record(conn, "t", "claude-opus-5", 400_000, 0)                                    # $2
        conn.execute("UPDATE api_usage SET ts='2026-10-18T12:00:00+00:00' WHERE ts > '2026-10-11'")
        oct20, nov10 = datetime(2026, 10, 20, tzinfo=timezone.utc), datetime(2026, 11, 10, tzinfo=timezone.utc)
        self.assertAlmostEqual(spend.cycle_to_date(conn, oct20), 7.0, msg="from the 1st: both October rows")
        self.assertAlmostEqual(spend.cycle_to_date(conn, nov10), 0.0, msg="from the 1st: November starts clean")
        os.environ["AI_CAP_RESETS_ON"] = "17"
        config.reset()
        self.assertAlmostEqual(spend.cycle_to_date(conn, oct20), 2.0, msg="from the 17th: the 10th was last cycle")
        self.assertAlmostEqual(spend.cycle_to_date(conn, nov10), 2.0, msg="from the 17th: the 18th is still this cycle")
        self.assertEqual(spend.cycle_start(datetime(2026, 11, 17, 0, 0, 1, tzinfo=timezone.utc), 17).day, 17)
        self.assertEqual(spend.cycle_start(datetime(2026, 11, 16, 23, 59, tzinfo=timezone.utc), 17).month, 10)
        self.assertEqual(spend.cycle_start(datetime(2026, 3, 1, tzinfo=timezone.utc), 31), datetime(2026, 2, 28, tzinfo=timezone.utc), "past the 28th reads as the 28th")
        self.assertEqual(spend.cycle_start(datetime(2026, 3, 5, tzinfo=timezone.utc), 0).day, 1, "below 1 reads as the 1st")
        conn.close()

    def test_zero_cap_fails_closed(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        self.assertTrue(spend.cap_reached(db.connect()))


class Logs(IsolatedCase):
    def test_lines_go_to_the_rotating_file_and_to_stderr_only_when_someone_is_watching(self):
        """2026-10-24 audit: every agent's log was written twice, its own rotating file and launchd's capture of stderr,
        which never rotates (6.8 MB in two weeks). Under launchd stderr is no terminal, so the lines go to the file alone."""
        from logging import StreamHandler
        from logging.handlers import RotatingFileHandler
        from convention_social.core import logs
        with mock.patch.object(logs, "watched", return_value=False):
            quiet = logs.get_logger("quiet-agent")
        self.assertEqual([type(h) for h in quiet.handlers], [RotatingFileHandler])
        self.assertEqual(quiet.handlers[0].baseFilename, str(config.get_config().logs_dir / "quiet-agent.log"))
        with mock.patch.object(logs, "watched", return_value=True):
            typed = logs.get_logger("typed-agent")
        self.assertEqual([type(h) for h in typed.handlers], [RotatingFileHandler, StreamHandler])
        self.assertEqual([type(h) for h in logs.get_logger("typed-agent", to_stderr=False).handlers], [RotatingFileHandler, StreamHandler],
                         "the same logger again: not configured twice")

    def test_the_dashboard_gives_uvicorn_the_same_rotating_log(self):
        """The access log went to stderr and so to dashboard.launchd.log, 1.4 MB in two weeks, unrotated."""
        import logging
        from logging.handlers import RotatingFileHandler
        from convention_social import cli
        from convention_social.core import logs
        served = logging.getLogger("uvicorn")
        for h in list(served.handlers):
            served.removeHandler(h)
        with mock.patch("uvicorn.run") as run, mock.patch.object(logs, "watched", return_value=False):
            cli.main(["dashboard"])
        self.assertIsNone(run.call_args.kwargs["log_config"], "uvicorn's own stderr logging is off")
        self.assertEqual([type(h) for h in served.handlers], [RotatingFileHandler])
        self.assertEqual(served.handlers[0].baseFilename, str(config.get_config().logs_dir / "dashboard.log"))
        for h in list(served.handlers):
            served.removeHandler(h)
            h.close()


class StateIO(IsolatedCase):
    def test_atomic_save_and_private(self):
        p = self.root / "s.json"
        state_io.save_json(p, {"a": 1}, private=True)
        state_io.save_json(p, {"a": 2}, private=True)
        self.assertEqual(state_io.load_json(p, {}), {"a": 2})
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        p.write_text("{broken")
        self.assertEqual(state_io.load_json(p, {}), {"a": 1})

    def test_a_corrupt_copy_is_readable_by_this_user_alone(self):
        """2026-10-24 audit: two corrupt copies of the Drive token sat in cache/ world-readable, the refresh token in
        them. A sidecar is 600 whatever it copies, and so are a private file's .bak and .tmp, from their first byte."""
        old_umask = os.umask(0o022)                # the Mini's own default: a plain write would be 644
        self.addCleanup(os.umask, old_umask)
        p = self.root / "google_token.json"
        state_io.save_json(p, {"refresh_token": "r1"}, private=True)
        state_io.save_json(p, {"refresh_token": "r2"}, private=True)
        p.write_text("{broken")
        self.assertEqual(state_io.load_json(p, {}), {"refresh_token": "r1"})
        sidecars = list(self.root.glob("google_token.json.corrupt-*"))
        self.assertEqual(len(sidecars), 1)
        self.assertEqual(oct(sidecars[0].stat().st_mode & 0o777), "0o600", "the sidecar")
        self.assertEqual(oct(p.with_name("google_token.json.bak").stat().st_mode & 0o777), "0o600", "the .bak")
        state_io.save_json(self.root / "plain.json", {"a": 1})
        (self.root / "plain.json").write_text("{broken")
        state_io.load_json(self.root / "plain.json", {})
        self.assertEqual([oct(s.stat().st_mode & 0o777) for s in self.root.glob("plain.json.corrupt-*")], ["0o600"],
                         "a sidecar of a plain file too: nothing but the suite reads it")
