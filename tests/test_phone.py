"""A photo from Chris's phone while he shoots becomes a draft post within minutes (2026-10-14: "if I'm in the middle
of shooting conventions and want to share a photo I took from my phone can we set up a way to send the photos to the
suite for social upload?"; his answers: a draft post right away, from a page on the dashboard)."""
from __future__ import annotations

import io
import json
import logging
import os
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from PIL import Image

from convention_social import cli, storage
from convention_social.agents import content, phone, publisher
from convention_social.ai import claude
from convention_social.core import auth, config, db, runner, settings
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.drive import scan
from convention_social.drive.api import DriveReader
from convention_social.render import meta
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say
from tests.test_hero_upload import LookClient
from tests.test_library import library


def heic_bytes(size=(2000, 1500)) -> bytes:
    """An HEIC file written without registering the opener in this process (so the pins below prove keep() does)."""
    import pillow_heif
    buf = io.BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", size, (90, 60, 30))).save(buf, quality=80)
    return buf.getvalue()


class FreeSorter:
    """A local sorter (Ollama's stand-in): free, so it runs in dry run too."""
    method, model = "ollama", "fake-vision"

    def __init__(self, **answer):
        self.answer = {"subject": "event", "event_kind": "business", "shot_type": "stage_panel", "quality": 4, "sharp": True,
                       "light": 4, "moment": 4, "people_count": 3, "possible_minor": False, "personal_details": [],
                       "summary": "A speaker on stage.", **answer}
        self.calls = 0

    def paid(self):
        return False

    def classify(self, thumb, hint):
        self.calls += 1
        assert "phone" in hint
        return dict(self.answer)


class Keep(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)

    def photo(self):
        return db.one(self.conn, "SELECT * FROM photos ORDER BY id DESC LIMIT 1")

    def test_a_jpeg_and_a_heic_are_kept_as_a_cleared_photo_of_their_own_never_in_drive(self):
        sid = phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)), "  the main hall  before the doors ")
        p = self.photo()
        self.assertTrue(p["drive_id"].startswith("phone-"))
        self.assertEqual((p["folder_id"], p["clearance"], p["source"], p["width"], p["height"]), ("phone", "cleared", "phone", 2000, 1500))
        own = Path(p["local_path"])
        self.assertEqual(own.parent, config.get_config().data_root / "phone")
        self.assertTrue(own.is_file())
        self.assertEqual(meta.is_clean(own), [], "re-encoded from the pixels: no GPS, no camera data")
        self.assertEqual(p["taken_at"], "2026:09:20 14:31:00", "when the phone took it")
        self.assertTrue((config.get_config().data_root / "thumbs" / f"{p['drive_id']}.jpg").is_file())
        f = db.one(self.conn, "SELECT * FROM drive_folders WHERE drive_id='phone'")
        self.assertEqual((f["name"], f["clearance"], f["image_count"]), ("From the phone", "cleared", 1))
        c = db.one(self.conn, "SELECT * FROM classifications WHERE photo_id=?", (p["id"],))
        self.assertEqual((c["method"], c["subject"], c["orientation"]), ("folder", "event", "landscape"))
        s = db.one(self.conn, "SELECT * FROM phone_sends WHERE id=?", (sid,))
        self.assertEqual((s["photo_id"], s["status"], s["note"]), (p["id"], "pending", "the main hall before the doors"))
        phone.keep(self.conn, heic_bytes())
        self.assertEqual(self.photo()["width"], 2000, "HEIC, the iPhone's own format")
        self.assertEqual(db.one(self.conn, "SELECT image_count FROM drive_folders WHERE drive_id='phone'")["image_count"], 2)
        self.assertEqual(len(phone.pending(self.conn)), 2)

    def test_heic_opens_in_a_fresh_process(self):
        """The dashboard is a fresh process with nothing registered: keep() itself must register the HEIC opener."""
        import subprocess
        import sys
        heic = self.root / "one.heic"
        heic.write_bytes(heic_bytes())
        code = ("from pathlib import Path; from convention_social.core import db; from convention_social.agents import phone; "
                f"conn = db.connect(); sid = phone.keep(conn, Path({str(heic)!r}).read_bytes()); "
                "print('kept', db.one(conn, 'SELECT width FROM photos')['width'])")
        r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, env=dict(os.environ), timeout=120,
                           cwd=str(Path(__file__).resolve().parents[1]))
        self.assertIn("kept 2000", r.stdout, r.stderr[-600:])

    def test_refusals(self):
        for data, why in ((b"", "empty"), (b"not a photo", "not a photo"), (jpeg_bytes(size=(800, 500)), "too small")):
            with self.assertRaises(phone.Refused) as cm:
                phone.keep(self.conn, data)
            self.assertIn(why, str(cm.exception))
        now = db.utcnow()
        db.insert(self.conn, "conventions", name="Katsucon", start_date="2026-02-13", created_at=now, updated_at=now)
        with self.assertRaises(phone.Refused) as cm:
            phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)), "backstage at Katsucon")
        self.assertIn("names Katsucon", str(cm.exception))
        self.assertIsNone(self.photo(), "nothing kept")
        self.assertEqual(len(phone.clean_note(self.conn, "x" * 300)), phone.NOTE_MAX)

    def test_the_weekly_drive_pass_never_sweeps_it(self):
        drive = library()
        reader = DriveReader("tok", conn=self.conn, transport=drive)
        scan.full_inventory(self.conn, reader)
        phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)))
        del drive.files["p3"]                                                   # gone from Drive
        time.sleep(1.1)                                                         # the pass's "now" is a new second
        st = scan.full_inventory(self.conn, reader)
        self.assertEqual(st.trashed, 1, "only the Drive photo")
        rows = {r["drive_id"]: r["trashed"] for r in db.rows(self.conn, "SELECT drive_id, trashed FROM photos")}
        self.assertEqual(rows["p3"], 1)
        self.assertEqual([t for d, t in rows.items() if d.startswith("phone-")], [0])

    def test_the_nightly_sweep_leaves_its_file(self):
        phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)))
        p = self.photo()
        storage.sweep(self.conn, now=time.time() + 100 * 86400, keep_days=0)
        self.assertTrue(Path(p["local_path"]).is_file())
        self.assertEqual(self.photo()["local_path"], p["local_path"])

    def test_a_send_left_drafting_by_a_run_that_died_is_tried_again(self):
        sid = phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)))
        old = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(microsecond=0).isoformat()
        self.conn.execute("UPDATE phone_sends SET status='drafting', updated_at=? WHERE id=?", (old, sid))
        self.assertEqual([r["id"] for r in phone.pending(self.conn)], [sid])
        self.conn.execute("UPDATE phone_sends SET updated_at=? WHERE id=?", (db.utcnow(), sid))
        self.assertEqual(phone.pending(self.conn), [], "one being drafted now is left to its run")


class Draft(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        config.get_config().ensure_dirs()

    def ctx(self, dry=True):
        return runner.Context("phone", self.conn, logging.getLogger("t"), config.get_config(), dry, 0)

    def live(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        settings.set_dry_run(self.conn, "content", False)
        return self.ctx(dry=False)

    def send(self, note="the keynote room, just before the doors"):
        return phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)), note)

    def last_post(self):
        row = db.one(self.conn, "SELECT * FROM content_queue ORDER BY id DESC LIMIT 1")
        return row, (json.loads(row["rule_report"]) if row else {})

    def test_dry_run_with_the_free_sorter_drafts_a_single_post_for_today(self):
        sid = self.send()
        pid = db.one(self.conn, "SELECT photo_id FROM phone_sends WHERE id=?", (sid,))["photo_id"]
        own = db.one(self.conn, "SELECT local_path FROM photos WHERE id=?", (pid,))["local_path"]
        sorter = FreeSorter()
        line = phone.run(self.ctx(dry=False), sorter=sorter)                  # the content lane is in dry run: so is this
        self.assertIn("DRY RUN drafted post #1", line)
        self.assertIn("sent from your phone", line)
        self.assertEqual(sorter.calls, 1, "the free sorter runs in dry run")
        row, meta_ = self.last_post()
        today = datetime.now(ZoneInfo(config.get_config().timezone)).date().isoformat()
        self.assertEqual((meta_["for_day"], meta_["design"], meta_["source"], meta_["asap"], meta_["note"], meta_["send_id"]),
                         (today, "single", "phone", True, "the keynote room, just before the doors", sid))
        self.assertEqual((json.loads(row["photo_ids"]), row["status"]), ([pid], "draft"))
        self.assertTrue(json.loads(row["caption"])["instagram"])
        self.assertEqual(json.loads(row["render_paths"]).keys() & {"4:5", "2:3"}, {"4:5", "2:3"})
        s = db.one(self.conn, "SELECT status, queue_id FROM phone_sends WHERE id=?", (sid,))
        self.assertEqual((s["status"], s["queue_id"]), ("drafted", row["id"]))
        self.assertEqual(db.one(self.conn, "SELECT local_path FROM photos WHERE id=?", (pid,))["local_path"], own,
                         "its own file stays its copy; never the cache the sweep takes")
        self.assertEqual(list((config.get_config().data_root / "photos").glob("phone-*")), [])
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM photo_use WHERE photo_id=? AND surface='post'", (pid,))["n"], 1)
        c = db.one(self.conn, "SELECT method, quality, shot_type FROM classifications WHERE photo_id=?", (pid,))
        self.assertEqual(tuple(c), ("ollama", 4, "stage_panel"))         # no age is written since 2026-10-15
        self.assertEqual(phone.run(self.ctx(), sorter=sorter), "nothing sent from the phone is waiting")

    def test_dry_run_without_a_sorter_says_why_on_the_page_and_the_agents_page(self):
        sid = self.send()
        line = phone.run(self.ctx())
        self.assertIn("not drafted: dry run, so Claude did not look at it, and it is not sorted yet", line)   # 2026-10-15: no age gate
        s = db.one(self.conn, "SELECT status, error FROM phone_sends WHERE id=?", (sid,))
        self.assertEqual(s["status"], "failed")
        self.assertIn("switch the content lane live", s["error"])
        self.assertIn("not drafted", phone.recent(self.conn)[0]["line"])
        self.assertEqual(db.one(self.conn, "SELECT agent, kind FROM errors")["agent"], "phone")
        self.assertIsNone(self.last_post()[0])

    def test_live_claude_looks_and_the_draft_fails_closed(self):
        """Deliberate change, 2026-10-15: "someone may be under 18" no longer stops a draft (Chris: "If I approve
        something, it means I checked it"); a plate and a wedding still do, and an old-style age answer drafts."""
        ctx = self.live()
        sid = self.send()
        line = phone.run(ctx, check_client=LookClient(personal_details=["vehicle_plate"]), art_client=ArtClientAny([say("pass")]))
        self.assertIn("vehicle_plate", line)
        self.assertEqual(db.one(self.conn, "SELECT status FROM phone_sends WHERE id=?", (sid,))["status"], "failed")
        sid = self.send()
        line = phone.run(ctx, check_client=LookClient(event_kind="wedding"), art_client=ArtClientAny([say("pass")]))
        self.assertIn("wedding", line)
        self.assertIsNone(self.last_post()[0])
        sid = self.send()
        line = phone.run(ctx, check_client=LookClient(possible_minor=True), art_client=ArtClientAny([say("pass")]))
        self.assertIn("drafted post", line)
        self.assertNotIn("under 18", line)

    def test_live_the_check_passes_and_the_post_is_drafted_with_the_card_and_the_ping(self):
        ctx = self.live()
        sid = self.send()
        pid = db.one(self.conn, "SELECT photo_id FROM phone_sends WHERE id=?", (sid,))["photo_id"]
        with mock.patch.object(content.notify, "push_result", return_value="sent") as push:
            line = phone.run(ctx, check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        self.assertIn("drafted post #1", line)
        self.assertNotIn("DRY RUN", line)
        row, meta_ = self.last_post()
        self.assertEqual((row["status"], meta_["art"]["verdict"], meta_["asap"]), ("draft", "pass", True))
        fc = db.one(self.conn, "SELECT possible_minor, event_kind FROM final_checks WHERE photo_id=?", (pid,))
        self.assertEqual(tuple(fc), (0, "business"))
        c = db.one(self.conn, "SELECT method, shot_type FROM classifications WHERE photo_id=?", (pid,))
        self.assertEqual(tuple(c), ("vision", "stage_panel"), "no sorter ran: Claude's look is the sort")
        from convention_social.library import eligibility
        self.assertEqual(eligibility.is_eligible(self.conn, pid), (True, "ok"))
        self.assertEqual(push.call_count, 1)
        title, message = push.call_args[0][:2]
        self.assertIn("your photo from the floor", title)
        self.assertIn("as soon as Buffer takes it", message)
        self.assertIn("Approve", push.call_args[1]["actions"])
        self.assertIn(f"/media/card/{row['id']}/", push.call_args[1]["attach"])
        self.assertEqual(db.one(self.conn, "SELECT status, queue_id FROM phone_sends WHERE id=?", (sid,))["queue_id"], row["id"])

    def test_the_art_directors_reject_fails_the_send_and_says_why(self):
        ctx = self.live()
        sid = self.send()
        line = phone.run(ctx, check_client=LookClient(), art_client=ArtClientAny([say("reject", notes="Flat light, no moment.")]))
        self.assertIn("the art director turned it back: Flat light, no moment.", line)
        row, _ = self.last_post()
        self.assertEqual(row["status"], "rejected")
        s = db.one(self.conn, "SELECT status, queue_id, error FROM phone_sends WHERE id=?", (sid,))
        self.assertEqual((s["status"], s["queue_id"]), ("failed", row["id"]))
        self.assertIn("Flat light", s["error"])

    def test_the_caption_writer_hears_his_line(self):
        seen = []

        class Drafter:
            model = "fake"

            def draft(self, facts, photo, notes=()):
                seen.append(facts)
                return claude.TemplateDrafter().draft(facts, photo, notes)
        self.send("the keynote room, just before the doors")
        phone.run(self.ctx(), sorter=FreeSorter(), drafter=Drafter())
        self.assertEqual(seen[0].note, "the keynote room, just before the doors")
        self.assertIn("The photographer, who took it minutes ago, says of this moment: the keynote room, just before the doors.",
                      claude.user_text(seen[0]))
        self.assertNotIn("photographer, who took it", claude.user_text(claude.PostFacts(brand_name="x")), "only when there is a line")

    def test_the_daily_draft_reads_a_phone_photos_own_file(self):
        sid = self.send()
        row = dict(db.one(self.conn, "SELECT * FROM photos WHERE id=(SELECT photo_id FROM phone_sends WHERE id=?)", (sid,)))
        data = content.read_photo(config.get_config(), row, lambda drive_id: (_ for _ in ()).throw(AssertionError("Drive asked")))
        self.assertEqual(data, Path(row["local_path"]).read_bytes())
        drive_row = {"drive_id": "d1", "source": "drive", "local_path": None}
        self.assertEqual(content.read_photo(config.get_config(), drive_row, lambda drive_id: b"from drive " + drive_id.encode()), b"from drive d1")

    def test_a_second_send_waits_its_turn(self):
        codes = [runner.EXIT_LOCKED, runner.EXIT_LOCKED, 0]
        args = types.SimpleNamespace(agent="phone", dry_run=False, live=False, wait=True)
        with mock.patch.object(runner, "run", side_effect=lambda *a, **k: codes.pop(0)) as run, mock.patch.object(cli.time, "sleep") as sleep:
            self.assertEqual(cli.cmd_run(args), 0)
        self.assertEqual((run.call_count, sleep.call_count), (3, 2))
        codes[:] = [runner.EXIT_LOCKED]
        args.wait = False
        with mock.patch.object(runner, "run", side_effect=lambda *a, **k: codes.pop(0)) as run, mock.patch.object(cli.time, "sleep") as sleep:
            self.assertEqual(cli.cmd_run(args), runner.EXIT_LOCKED)
        self.assertEqual((run.call_count, sleep.call_count), (1, 0))
        with mock.patch.object(runner.subprocess, "Popen") as popen:
            runner.start_agent("phone", wait=True)
            runner.start_agent("content")
        self.assertEqual(popen.call_args_list[0][0][0][-3:], ["run", "phone", "--wait"])
        self.assertEqual(popen.call_args_list[1][0][0][-2:], ["run", "content"])


class LeftBehind(IsolatedCase):
    def test_the_hourly_scanner_restarts_a_send_left_behind(self):
        from convention_social.agents import scanner
        conn = db.connect()
        self.addCleanup(conn.close)
        ctx = runner.Context("scanner", conn, logging.getLogger("t"), config.get_config(), True, 0)
        with mock.patch.object(scanner.runner, "start_agent") as start:
            scanner.run(ctx)                                                    # Drive is not signed in here: the scan stops early
        self.assertEqual(start.call_count, 0, "nothing waiting")
        sid = phone.keep(conn, jpeg_bytes(size=(2000, 1500)))
        old = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(microsecond=0).isoformat()
        conn.execute("UPDATE phone_sends SET status='drafting', updated_at=? WHERE id=?", (old, sid))
        with mock.patch.object(scanner.runner, "start_agent") as start:
            scanner.run(ctx)
        self.assertEqual((start.call_args[0], start.call_args[1]), (("phone",), {"wait": True}))


class OutAsSoonAsApproved(IsolatedCase):
    def test_a_phone_post_takes_the_next_time_buffer_takes_never_the_days_slot(self):
        conn = db.connect()
        self.addCleanup(conn.close)
        ctx = runner.Context("publisher", conn, logging.getLogger("t"), config.get_config(), True, 0)
        now = datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)                 # 15:00 in New York
        row = {"rule_report": json.dumps({"asap": True, "source": "phone"})}
        self.assertEqual(publisher.asap_slot(ctx, row, now), "2026-10-14T15:35")
        self.assertIsNone(publisher.asap_slot(ctx, {"rule_report": json.dumps({"for_day": "2026-10-15"})}, now))
        self.assertIsNone(publisher.asap_slot(ctx, {"rule_report": None}, now))


class OnThePage(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_button_and_the_page(self):
        home = self.client.get("/").text
        self.assertIn('href="/send"', home)
        self.assertIn("Send a photo", home)
        page = self.client.get("/send").text
        self.assertIn('accept="image/*"', page)
        self.assertIn('name="note"', page)
        self.assertIn("dry run", page, "the content lane starts in dry run: the page says Claude does not look")
        self.assertNotIn("setTimeout", page, "nothing waiting: no reload")

    def test_a_send_is_kept_and_the_agent_started_waiting_its_turn(self):
        with mock.patch.object(dash, "start_agent") as start:
            r = self.client.post("/send", files={"file": ("IMG_1.jpg", jpeg_bytes(size=(2000, 1500)), "image/jpeg")},
                                 data={"note": "the main hall"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertTrue(r.headers["location"].startswith("/send?msg=Sent."), r.headers["location"])
        self.assertEqual((start.call_args[0], start.call_args[1]), (("phone",), {"wait": True}))
        s = db.one(self.conn, "SELECT * FROM phone_sends")
        self.assertEqual((s["status"], s["note"]), ("pending", "the main hall"))
        page = self.client.get("/send").text
        self.assertIn(f'src="/media/thumb/{s["photo_id"]}"', page)
        self.assertIn("waiting its turn", page)
        self.assertIn("setTimeout", page, "the page follows the send by itself")
        r = self.client.get(f"/media/thumb/{s['photo_id']}")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/jpeg"))
        thumb = config.get_config().data_root / "thumbs" / f"{db.one(self.conn, 'SELECT drive_id FROM photos')['drive_id']}.jpg"
        thumb.unlink()                                                          # the nightly sweep took the preview
        self.assertEqual(self.client.get(f"/media/thumb/{s['photo_id']}").status_code, 200, "made again from its own file")
        self.assertTrue(thumb.is_file())
        self.conn.execute("UPDATE phone_sends SET status='drafted', queue_id=7 WHERE id=?", (s["id"],))
        page = self.client.get("/send").text
        self.assertIn('href="/queue/7"', page)
        self.assertNotIn("setTimeout", page)

    def test_a_bad_file_or_a_named_note_is_refused_and_nothing_starts(self):
        with mock.patch.object(dash, "start_agent") as start:
            r = self.client.post("/send", files={"file": ("x.jpg", b"not a photo", "image/jpeg")}, follow_redirects=False)
            self.assertIn("Not+kept%3A+not+a+photo", r.headers["location"])
            anon = TestClient(create_app())
            self.assertNotEqual(anon.post("/send", files={"file": ("x.jpg", jpeg_bytes(), "image/jpeg")}, follow_redirects=False).status_code, 303)
        self.assertEqual(start.call_count, 0)
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM phone_sends"))
        self.assertIn("Not kept", self.client.get("/send?msg=Not+kept%3A+x").text)
