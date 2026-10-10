"""Scanner, eligibility (fail closed), classification, credits sheet and the report, against a fake Drive."""
from __future__ import annotations

import json
import os
import types

from convention_social.core import config, db, runner, settings
from convention_social.drive import oauth, scan
from convention_social.drive.api import DriveReader
from convention_social.library import classify, credits, eligibility, heuristics, report
from convention_social.library.classify import ollama_model as real_ollama_model
from tests._base import IsolatedCase
from tests.fake_drive import FakeDrive


def library():
    d = FakeDrive()
    d.folder("fcon", "Katsucon 2025")
    d.folder("fcos", "Cosplay", "fcon")
    d.folder("fcpac", "CPAC Texas 2022 Selects")
    d.folder("fwed", "Smith Wedding 2021")
    d.image("p1", "DSC_1.jpg", "fcos")
    d.image("p2", "DSC_2.jpg", "fcos", w=4000, h=6000)
    d.image("p3", "IMG_3.jpg", "fcpac")
    d.image("p4", "w.jpg", "fwed")
    d.image("raw1", "DSC_9.CR2", "fcos", mime="image/x-canon-cr2")
    d.image("nothumb", "odd.jpg", "fcos", thumb=False)
    return d


class Scan(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.drive = library()
        self.reader = DriveReader("tok", conn=self.conn, transport=self.drive)

    def test_full_inventory(self):
        st = scan.full_inventory(self.conn, self.reader)
        self.assertEqual((st.folders, st.images, st.skipped_raw, st.skipped_unrenderable), (4, 4, 1, 1))
        paths = {r["drive_id"]: r["path"] for r in db.rows(self.conn, "SELECT * FROM drive_folders")}
        self.assertEqual(paths["fcos"], "My Drive/Katsucon 2025/Cosplay")
        p2 = db.one(self.conn, "SELECT * FROM photos WHERE drive_id='p2'")
        self.assertEqual((p2["width"], p2["height"], p2["camera"]), (4000, 6000, "Canon R5"))
        self.assertEqual(settings.get(self.conn, scan.CHANGES_TOKEN_KEY), "100")
        # the start token was asked for before anything was listed
        self.assertTrue(self.drive.calls[0][0].endswith("/changes/startPageToken"))
        self.assertEqual(db.one(self.conn, "SELECT image_count FROM drive_folders WHERE drive_id='fcos'")["image_count"], 2)

    def test_changes_apply(self):
        scan.full_inventory(self.conn, self.reader)
        new = self.drive.image("p5", "new.jpg", "fcpac")
        self.drive.changes = [{"fileId": "p5", "file": self.drive.files[new]},
                              {"fileId": "p1", "removed": True},
                              {"fileId": "p3", "file": {**self.drive.files["p3"], "trashed": True}}]
        st = scan.incremental(self.conn, self.reader)
        self.assertEqual((st.changes, st.images, st.trashed), (3, 1, 2))
        self.assertEqual(settings.get(self.conn, scan.CHANGES_TOKEN_KEY), "200")
        trashed = {r["drive_id"] for r in db.rows(self.conn, "SELECT drive_id FROM photos WHERE trashed=1")}
        self.assertEqual(trashed, {"p1", "p3"})

    def test_rescan_keeps_clearance(self):
        scan.full_inventory(self.conn, self.reader)
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='fcon'")
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE drive_id='p2'")
        scan.full_inventory(self.conn, self.reader)
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM drive_folders WHERE drive_id='fcon'")["clearance"], "cleared")
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM photos WHERE drive_id='p2'")["clearance"], "blocked")

    def test_only_gets_were_made(self):
        scan.full_inventory(self.conn, self.reader)
        self.assertGreater(len(self.drive.calls), 4)
        n = db.one(self.conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='drive'")["n"]
        self.assertEqual(n, len(self.drive.calls))


class FakeClaude:
    """messages.create returning a fixed JSON answer."""
    def __init__(self, answer, stop="end_turn"):
        self.answer, self.stop, self.calls = answer, stop, 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        assert kw["model"] == "claude-haiku-5-5"
        assert kw["output_config"]["format"]["type"] == "json_schema"
        block = types.SimpleNamespace(type="text", text=json.dumps(self.answer))
        return types.SimpleNamespace(content=[block], stop_reason=self.stop, model=kw["model"],
                                     usage=types.SimpleNamespace(input_tokens=900, output_tokens=120))


ADULTS = {"subject": "event", "event_kind": "fan", "event_name_seen": "Katsucon", "shot_type": "cosplay_portrait",
          "view": "interior", "quality": 5, "people_count": 1, "possible_minor": False, "personal_details": [],
          "summary": "A cosplayer."}


class Eligibility(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.drive = library()
        self.reader = DriveReader("tok", conn=self.conn, transport=self.drive)
        scan.full_inventory(self.conn, self.reader)
        classify.folder_pass(self.conn)

    def pid(self, drive_id):
        return db.one(self.conn, "SELECT id FROM photos WHERE drive_id=?", (drive_id,))["id"]

    def vision(self, answer=ADULTS):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        c = classify.VisionClassifier(self.conn, client=FakeClaude(answer))
        return classify.vision_pass(self.conn, self.reader.thumbnail, classifier=c)

    def final(self, drive_id, minor=0, details="[]"):
        db.insert(self.conn, "final_checks", photo_id=self.pid(drive_id), possible_minor=minor, personal_details=details,
                  model="claude-opus-5-5", checked_at=db.utcnow())

    def test_nothing_eligible_by_default(self):
        self.vision()
        ids = [r["id"] for r in db.rows(self.conn, "SELECT id FROM photos")]
        self.assertEqual(len(ids), 4)
        self.assertEqual(eligibility.eligible_photo_ids(self.conn, ids), [])
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1")), (False, "not cleared yet"))

    def test_cleared_parent_folder_minor_check_and_final_check(self):
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='fcon'")
        # cleared, but not checked for minors yet: still no
        self.assertEqual(eligibility.is_candidate(self.conn, self.pid("p1")), (False, "not checked for minors yet"))
        self.vision()
        self.assertEqual(eligibility.is_candidate(self.conn, self.pid("p1")), (True, "ok"))
        # a candidate is not postable until Claude's final check passes
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1")), (False, "not given the final check yet"))
        self.final("p1")
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1")), (True, "ok"))
        # a nearer excluded folder wins over a cleared parent
        self.conn.execute("UPDATE drive_folders SET clearance='excluded' WHERE drive_id='fcos'")
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1"))[0], False)

    def test_final_check_minor_or_details_blocks(self):
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='fcon'")
        self.vision()
        self.final("p1", minor=1)
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1")), (False, "the final check says someone may be under 18"))
        self.final("p2", details='["house_number"]')
        self.assertIn("house_number", eligibility.is_eligible(self.conn, self.pid("p2"))[1])

    def test_possible_minor_never_eligible(self):
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='fcon'")
        self.vision({**ADULTS, "possible_minor": True})
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1")), (False, "someone in it may be under 18"))
        self.conn.execute("UPDATE photos SET clearance='cleared' WHERE drive_id='p1'")
        self.assertFalse(eligibility.is_eligible(self.conn, self.pid("p1"))[0])

    def test_personal_details_block(self):
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='fcon'")
        self.vision({**ADULTS, "personal_details": ["badge_name"]})
        self.assertIn("badge_name", eligibility.is_eligible(self.conn, self.pid("p1"))[1])

    def test_do_not_use_list_and_consent(self):
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='fcon'")
        self.vision()
        pid = self.pid("p1")
        self.final("p1")
        self.assertTrue(eligibility.is_eligible(self.conn, pid)[0])
        self.drive.sheet_csv = ("Photo or folder,Name,Handle,Consent,Notes\n"
                                "https://drive.google.com/file/d/p1/view?usp=sharing,Ann,@ann_cos,yes,met at the con\n"
                                "https://drive.google.com/drive/folders/nosuchfolder,,,no,\n")
        res = credits.sync(self.conn, self.drive.sheet_csv)
        self.assertEqual((res.rows, res.matched), (2, 1))
        self.assertEqual(eligibility.credit_line(self.conn, pid), "@ann_cos")
        db.insert(self.conn, "do_not_use", kind="handle", value="@ann_cos", reason="takedown", added_at=db.utcnow())
        self.assertEqual(eligibility.is_eligible(self.conn, pid),
                         (False, "a person in it (@ann_cos) is on the do-not-use list"))

    def test_consent_no_blocks(self):
        self.conn.execute("UPDATE drive_folders SET clearance='cleared' WHERE drive_id='fcon'")
        self.vision()
        credits.sync(self.conn, "Folder,Consent\nfcos,no\n")
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1")), (False, "the credits sheet says no consent"))

    def test_trashed_photo_not_eligible(self):
        self.conn.execute("UPDATE photos SET clearance='cleared', trashed=1 WHERE drive_id='p1'")
        self.assertEqual(eligibility.is_eligible(self.conn, self.pid("p1")), (False, "photo is no longer in Drive"))


class Classification(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.drive = library()
        self.reader = DriveReader("tok", conn=self.conn, transport=self.drive)
        scan.full_inventory(self.conn, self.reader)

    def test_folder_pass_marks_candidates_only(self):
        self.assertEqual(classify.folder_pass(self.conn), 4)
        self.assertEqual(classify.folder_pass(self.conn), 0)
        rows = {r["drive_id"]: r for r in db.rows(self.conn, "SELECT p.drive_id, c.* FROM classifications c JOIN photos p ON p.id=c.photo_id")}
        self.assertEqual(rows["p1"]["is_convention"], 1)
        self.assertEqual(rows["p1"]["event_kind"], "fan")
        self.assertEqual(rows["p3"]["event_kind"], "business")
        self.assertEqual(rows["p4"]["is_convention"], 0)
        self.assertEqual(rows["p4"]["subject"], "other")
        self.assertEqual(rows["p1"]["subject"], "event")
        self.assertIsNone(rows["p1"]["possible_minor"])
        self.assertEqual(rows["p2"]["orientation"], "portrait")

    def test_vision_pass_respects_cap_and_skips_non_events(self):
        classify.folder_pass(self.conn)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        fake = FakeClaude(ADULTS)
        st = classify.vision_pass(self.conn, self.reader.thumbnail, classifier=classify.VisionClassifier(self.conn, client=fake))
        self.assertEqual(st.done, 3)       # the wedding folder is never sent
        self.assertEqual(fake.calls, 3)
        self.assertGreater(db.one(self.conn, "SELECT SUM(cost_usd) c FROM api_usage WHERE provider='anthropic'")["c"], 0)
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        self.conn.execute("UPDATE classifications SET method='folder'")
        st = classify.vision_pass(self.conn, self.reader.thumbnail, classifier=classify.VisionClassifier(self.conn, client=fake))
        self.assertEqual((st.done, st.stopped), (0, "monthly AI spend cap reached"))

    def test_refusal_leaves_photo_unchecked(self):
        classify.folder_pass(self.conn)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        st = classify.vision_pass(self.conn, self.reader.thumbnail,
                                  classifier=classify.VisionClassifier(self.conn, client=FakeClaude(ADULTS, stop="refusal")))
        self.assertEqual((st.done, st.failed), (0, 3))
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM classifications WHERE possible_minor IS NOT NULL")["n"], 0)

    def test_no_ollama_and_no_key_means_no_sort(self):
        classify.folder_pass(self.conn)
        st = classify.sort_pass(self.conn, self.reader.thumbnail)
        self.assertIn("no sorter", st.stopped)
        self.assertEqual(st.done, 0)


class Heuristics(IsolatedCase):
    def test_guesses(self):
        g = heuristics.guess("My Drive/CPAC Texas 2022 Premium Finals")
        self.assertEqual((g.is_event, g.event_kind, g.year), (True, "business", 2022))
        self.assertIn("CPAC", g.event_name)
        self.assertFalse(heuristics.guess("My Drive/Smith Wedding 2021").is_event)
        self.assertEqual(heuristics.guess("My Drive/Katsucon 2025/Cosplay").event_kind, "fan")
        self.assertIsNone(heuristics.guess("My Drive/Misc").is_event)


class Report(IsolatedCase):
    def test_report_and_contact_sheet(self):
        conn = db.connect()
        drive = library()
        reader = DriveReader("tok", conn=conn, transport=drive)
        scan.full_inventory(conn, reader)
        classify.folder_pass(conn)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        classify.vision_pass(conn, reader.thumbnail, classifier=classify.VisionClassifier(conn, client=FakeClaude(ADULTS)))
        s = report.summary(conn)
        self.assertEqual(s["convention_photos"], 3)
        self.assertEqual(s["by_event"]["Katsucon"], {"2024": 3})
        picks = report.best(conn, 30)
        self.assertEqual(len(picks), 3)
        sheet = report.write_contact_sheet(conn, reader.thumbnail, n=30)
        out = report.write_report(conn, sheet=sheet)
        self.assertTrue(sheet.exists() and sheet.stat().st_size > 1000)
        text = out.read_text()
        self.assertIn("3 convention photos found", text)
        self.assertIn(sheet.name, text)


class ScannerAgent(IsolatedCase):
    def test_not_signed_in_is_recorded_not_raised(self):
        from convention_social.agents import scanner
        code = runner.run("scanner", scanner.run)
        self.assertEqual(code, runner.EXIT_OK)
        conn = db.connect()
        self.assertEqual(settings.get(conn, oauth.STATE_KEY), "missing")
        self.assertEqual(db.one(conn, "SELECT kind FROM errors")["kind"], "drive_auth")

    def test_not_signed_in_is_one_open_error_however_many_runs(self):
        """The Mini, 2026-10-10: 22 identical "not signed in yet" rows from the hourly scanner and one
        from the daily draft. One open row per agent, its time moved forward; a dismissed one
        (Dashboard, alerted=1) lets the next run record afresh."""
        from convention_social.agents import content, scanner
        conn = db.connect()
        for _ in range(3):
            self.assertEqual(runner.run("scanner", scanner.run), runner.EXIT_OK)
            self.assertEqual(runner.run("content", content.run), runner.EXIT_OK)
        rows = [dict(r) for r in db.rows(conn, "SELECT id, agent, kind, ts, alerted FROM errors ORDER BY id")]
        self.assertTrue(rows)
        self.assertEqual(sorted((r["agent"], r["kind"]) for r in rows), [("content", "drive_auth"), ("scanner", "drive_auth")])
        first = rows[0]
        conn.execute("UPDATE errors SET ts='2000-01-01T00:00:00+00:00' WHERE id=?", (first["id"],))
        runner.run(first["agent"], {"scanner": scanner.run, "content": content.run}[first["agent"]])
        self.assertNotEqual(db.one(conn, "SELECT ts FROM errors WHERE id=?", (first["id"],))["ts"], "2000-01-01T00:00:00+00:00")
        conn.execute("UPDATE errors SET alerted=1 WHERE agent='scanner'")
        runner.run("scanner", scanner.run)
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM errors WHERE agent='scanner'")["n"], 2)
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM errors WHERE agent='scanner' AND alerted=0")["n"], 1)

    def test_dry_run_scans_but_never_pays(self):
        from convention_social.agents import scanner
        drive = library()
        conn = db.connect()
        ctx = runner.Context("scanner", conn, None, config.get_config(), True, 0)
        line = scanner.run(ctx, reader=DriveReader("tok", conn=conn, transport=drive))
        self.assertIn("full:", line)
        self.assertIn("(dry run)", line)
        self.assertEqual(db.one(conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='anthropic'")["n"], 0)
        line2 = scanner.run(ctx, reader=DriveReader("tok", conn=conn, transport=drive))
        self.assertIn("changes:", line2)


class OAuthState(IsolatedCase):
    def test_expired_token_sets_state(self):
        from convention_social.core import state_io
        conn = db.connect()
        state_io.save_json(oauth.token_path(), {"token": "a", "refresh_token": "r", "client_id": "c", "client_secret": "s",
                                                "token_uri": oauth.TOKEN_URI, "scopes": list(oauth.SCOPES),
                                                "expiry": "2020-01-01T00:00:00Z"}, private=True)

        class RefreshError(Exception):
            pass

        def boom(creds):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")
        with self.assertRaises(oauth.DriveAuthError):
            oauth.access_token(conn, refresh_fn=boom)
        self.assertEqual(settings.get(conn, oauth.STATE_KEY), "expired")

    def test_token_with_extra_scope_refused(self):
        from convention_social.core import state_io
        state_io.save_json(oauth.token_path(), {"token": "a", "refresh_token": "r", "client_id": "c", "client_secret": "s",
                                                "token_uri": oauth.TOKEN_URI,
                                                "scopes": ["https://www.googleapis.com/auth/drive"]}, private=True)
        with self.assertRaises(oauth.DriveAuthError):
            oauth.access_token(db.connect())


class Ollama(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        d = library()
        d.folder("farch", "Hilton Lobby Interiors 2017")
        d.image("a1", "lobby.jpg", "farch")
        self.reader = DriveReader("tok", conn=self.conn, transport=d)
        scan.full_inventory(self.conn, self.reader)
        classify.folder_pass(self.conn)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_model_detection(self):
        class R:
            def __init__(self, data):
                self.data = data

            def json(self):
                return self.data
        tags = {"models": [{"name": "llama3.1:8b"}, {"name": "qwen2.5vl:7b"}, {"name": "llava:13b"}]}
        self.assertEqual(real_ollama_model(lambda url, **kw: R(tags)), "qwen2.5vl:7b")
        self.assertIsNone(real_ollama_model(lambda url, **kw: R({"models": [{"name": "llama3.1:8b"}]})))

        def down(url, **kw):
            raise ConnectionError("refused")
        self.assertIsNone(real_ollama_model(down))
        os.environ["OLLAMA_MODEL"] = "llava:13b"
        config.reset()
        self.assertEqual(real_ollama_model(down), "llava:13b")

    def test_ollama_sorts_for_free_including_buildings(self):
        seen = []

        def post(url, json=None, **kw):
            seen.append((url, json))
            assert json["format"]["required"]
            assert json["messages"][1]["images"]
            answer = dict(ADULTS)
            if "architecture" in json["messages"][1]["content"]:
                answer.update(subject="architecture", shot_type="building_interior", people_count=0, view="interior")
            return types.SimpleNamespace(status_code=200, json=lambda: {"message": {"content": __import__("json").dumps(answer)}})
        st = classify.sort_pass(self.conn, self.reader.thumbnail, sorter=classify.OllamaSorter("qwen2.5vl:7b", post=post))
        self.assertEqual(st.done, 4)                  # three event photos and the lobby; the wedding is never sent
        self.assertTrue(seen[0][0].endswith("/api/chat"))
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage WHERE provider='anthropic'")["n"], 0)
        row = db.one(self.conn, "SELECT c.* FROM classifications c JOIN photos p ON p.id=c.photo_id WHERE p.drive_id='a1'")
        self.assertEqual((row["method"], row["subject"], row["view"], row["is_convention"]), ("ollama", "architecture", "interior", 0))

    def test_bad_local_answer_leaves_photo_unchecked(self):
        post = lambda url, **kw: types.SimpleNamespace(status_code=200, json=lambda: {"message": {"content": '{"subject": "event"}'}})
        st = classify.sort_pass(self.conn, self.reader.thumbnail, sorter=classify.OllamaSorter("m", post=post))
        self.assertEqual(st.done, 0)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM classifications WHERE possible_minor IS NOT NULL")["n"], 0)


class FinalCheck(IsolatedCase):
    def test_final_check_writes_and_bills(self):
        conn = db.connect()
        now = db.utcnow()
        conn.execute("INSERT INTO photos (drive_id, name, first_seen_at, last_seen_at) VALUES ('x','x.jpg',?,?)", (now, now))
        pid = db.one(conn, "SELECT id FROM photos")["id"]
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        calls = []

        class Beta:
            def __init__(self, answer, stop="end_turn"):
                self.answer, self.stop = answer, stop
                self.beta = self
                self.messages = self

            def create(self, **kw):
                calls.append(kw)
                block = types.SimpleNamespace(type="text", text=__import__("json").dumps(self.answer))
                return types.SimpleNamespace(content=[block], stop_reason=self.stop, model=kw["model"],
                                             usage=types.SimpleNamespace(input_tokens=1500, output_tokens=200))
        from tests.fake_drive import thumb_bytes
        data = classify.final_check(conn, pid, thumb_bytes(), client=Beta({"possible_minor": False, "personal_details": [], "summary": "ok"}))
        self.assertEqual(data["possible_minor"], False)
        self.assertEqual(calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(calls[0]["fallbacks"], "default")
        fc = db.one(conn, "SELECT * FROM final_checks WHERE photo_id=?", (pid,))
        self.assertEqual((fc["possible_minor"], fc["personal_details"]), (0, "[]"))
        self.assertGreater(db.one(conn, "SELECT SUM(cost_usd) c FROM api_usage")["c"], 0)
        # a refusal writes nothing new and returns None
        self.assertIsNone(classify.final_check(conn, pid, thumb_bytes(), client=Beta({}, stop="refusal")))
        # at the cap, no call at all
        os.environ["AI_MONTHLY_CAP_USD"] = "0"
        config.reset()
        n = len(calls)
        self.assertIsNone(classify.final_check(conn, pid, thumb_bytes(), client=Beta({})))
        self.assertEqual(len(calls), n)
        conn.close()
