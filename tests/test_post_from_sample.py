"""Post this on a design sample (Chris, 2026-10-15: "Put a "Post this" on every design sample so I can turn a sample I
like into a real draft post"). The sample becomes a draft on the daily draft's road and gates, never a shortcut."""
from __future__ import annotations

import html
import json
import logging
import os
import re
from unittest import mock

from fastapi.testclient import TestClient

from convention_social.agents import content, sample
from convention_social.core import auth, config, db, runner, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render import design_samples, motion
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say
from tests.test_hero_upload import LookClient
from tests.test_wedding import event_photo

ROOMS = ("stage_panel", "crowd", "backstage", "vendor_hall", "dinner_reception", "portrait")
EVERY_SAMPLE = {"fan-post.jpg": "fan", "spotlight-post.jpg": "spotlight", "slide-01.jpg": "carousel", "rooms-reel.mp4": "reel"}


class Case(IsolatedCase):
    """Six approved, sorted photos and one set of samples made on them (the reel too, silent: no music yet)."""

    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        config.get_config().ensure_dirs()
        self.ids = []
        for i, room in enumerate(ROOMS):
            pid = event_photo(self.conn, f"s{i}", kind="business", quality=5)
            self.conn.execute("UPDATE photos SET thumbnail_link='t' WHERE id=?", (pid,))
            self.conn.execute("UPDATE classifications SET shot_type=?, convention_name=? WHERE photo_id=?", (room, f"Event {i}", pid))
            self.ids.append(pid)
        def reel(shots, copy, *, out, audio=None):        # the reel's frames are pinned in test_reels; here only that it was made
            out.write_bytes(b"mp4")
            return out
        with mock.patch.object(design_samples.motion, "rooms_reel", reel):
            self.out = design_samples.make(self.conn, lambda fid: jpeg_bytes(size=(1600, 1000), seed=len(fid)), n=6,
                                           log=lambda m: None)
        self.folder = self.out.name
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def page(self) -> str:
        r = self.client.get(f"/library/design/{self.folder}/index.html")
        self.assertEqual(r.status_code, 200)
        return r.text

    def press(self, design: str, photos=None):
        rec = design_samples.sample_of(self.folder, design)
        ids = photos if photos is not None else (rec or {}).get("photos") or []
        with mock.patch("convention_social.dashboard.app.start_agent") as start:
            r = self.client.post(f"/library/design/{self.folder}/post", data={"design": design, "photos": ",".join(map(str, ids))},
                                 follow_redirects=False)
        return r, start

    def said(self, r) -> str:
        """What the samples page says after the press: the redirect followed, as Chris sees it."""
        self.assertEqual(r.status_code, 303)
        page = self.client.get(r.headers["location"])
        self.assertEqual(page.status_code, 200)
        return html.unescape(page.text)

    def live(self):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        settings.set_dry_run(self.conn, "content", False)

    def ctx(self):
        return runner.Context("sample", self.conn, logging.getLogger("t"), config.get_config(), True, 0)

    def fetch(self, row):
        return jpeg_bytes(size=(2400, 1600), seed=row["id"])

    def queued(self):
        return db.rows(self.conn, "SELECT * FROM content_queue WHERE kind='photo' ORDER BY id")


class TheButton(Case):
    def test_every_sample_has_post_this_with_its_design_and_the_photos_it_was_made_from(self):
        about = json.loads((self.out / "about.json").read_text())
        made = [s["design"] for s in about["samples"]]
        self.assertEqual(sorted(made), sorted(EVERY_SAMPLE.values()), "every post design and the reel are on record")
        track = self.root / "track.mp3"
        track.write_bytes(b"ID3")
        with mock.patch("convention_social.music.current", return_value=track):     # with music the reel can be posted too
            page = self.page()
        forms = re.findall(r'<form method="post" action="/library/design/([^/]+)/post" class="post">'
                           r'<input type="hidden" name="design" value="([a-z]+)"><input type="hidden" name="photos" value="([0-9,]+)">'
                           r'<button type="submit">Post this</button></form>', page)
        self.assertTrue(forms, "the page has Post this buttons")
        self.assertEqual(sorted(d for _, d, _ in forms), sorted(EVERY_SAMPLE.values()), "one per sample")
        for folder, design, ids in forms:
            self.assertEqual(folder, self.folder)
            photos = [int(x) for x in ids.split(",")]
            self.assertEqual(sorted(photos), sorted(self.ids), f"{design}: the six photos it was made from")
            self.assertEqual(photos, design_samples.sample_of(self.folder, design)["photos"])
        fan = design_samples.sample_of(self.folder, "fan")
        self.assertEqual(fan["hero"], fan["photos"][0], "the hero first, as the daily draft's renderer takes it")
        self.assertIn("Post this", (self.out / "index.html").read_text(), "the page written at make time has it too")


class ThePress(Case):
    def test_the_press_records_the_sample_and_starts_the_agent_waiting_its_turn(self):
        self.live()
        r, start = self.press("fan")
        self.assertEqual(r.status_code, 303)
        self.assertIn("being checked and drafted now", self.said(r))
        rec = db.one(self.conn, "SELECT * FROM sample_posts")
        self.assertEqual((rec["folder"], rec["design"], rec["status"]), (self.folder, "fan", "pending"))
        self.assertEqual(json.loads(rec["photo_ids"]), design_samples.sample_of(self.folder, "fan")["photos"])
        self.assertEqual((start.call_args[0], start.call_args[1]), (("sample",), {"wait": True}))

    def test_the_draft_carries_the_samples_design_and_photos_and_pings_with_approve(self):
        self.live()
        self.press("spotlight")
        with mock.patch.object(content.notify, "push_result", return_value="sent") as push:
            line = sample.run(self.ctx(), fetch=self.fetch, check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 4))
        self.assertIn("drafted post #1", line)
        self.assertNotIn("DRY RUN", line)
        rows = self.queued()
        self.assertEqual(len(rows), 1)
        row, meta = rows[0], json.loads(rows[0]["rule_report"])
        want = design_samples.sample_of(self.folder, "spotlight")["photos"]
        self.assertEqual(json.loads(row["photo_ids"]), want, "the sample's photos, the hero first")
        self.assertEqual((row["status"], meta["design"], meta["source"], meta["asap"], meta["sample_folder"]),
                         ("draft", "spotlight", "sample", True, self.folder))
        self.assertEqual(meta["art"]["verdict"], "pass", "the art director looked")
        self.assertTrue(json.loads(row["caption"])["instagram"], "captions written")
        self.assertTrue(meta["rules"]["instagram"]["ok"], "through the copy rules")
        for pid in want:
            self.assertIsNotNone(db.one(self.conn, "SELECT 1 FROM final_checks WHERE photo_id=?", (pid,)), f"photo {pid} checked")
        self.assertEqual(push.call_count, 1)
        self.assertIn("Approve", push.call_args[1]["actions"])
        self.assertIn(f"/media/card/{row['id']}/", push.call_args[1]["attach"])
        rec = db.one(self.conn, "SELECT status, queue_id FROM sample_posts")
        self.assertEqual((rec["status"], rec["queue_id"]), ("drafted", row["id"]))
        self.assertIn(f"Drafted as post #{row['id']}", self.page())

    def test_the_reel_takes_the_current_music_track_and_never_goes_out_silent(self):
        heard = []
        self.live()
        self.assertIn("Cannot be posted: a reel never goes out silent", self.page())
        r, start = self.press("reel")
        self.assertIn("Not drafted: a reel never goes out silent", self.said(r))
        self.assertEqual(start.call_count, 0)
        sample.ask(self.conn, self.folder, "reel", design_samples.sample_of(self.folder, "reel")["photos"])
        line = sample.run(self.ctx(), fetch=self.fetch, check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 4))
        self.assertIn("never goes out silent", line)
        self.assertEqual(self.queued(), [])
        track = self.root / "track.mp3"
        track.write_bytes(b"ID3")
        real = motion.rooms_reel

        def reel(shots, copy, *, out, audio=None, **kw):    # the reel's frames are pinned in test_reels; here the track it gets
            if kw.get("encoder"):
                return real(shots, copy, out=out, audio=audio, **kw)     # the cover and stills, drawn by the reel's own code
            heard.append(audio)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"mp4")
            return out
        with mock.patch("convention_social.music.current", return_value=track), \
             mock.patch.dict(motion.REELS, {"rooms": reel}):
            self.assertIn('value="reel"', self.page(), "with music the reel has its Post this")
            sample.ask(self.conn, self.folder, "reel", design_samples.sample_of(self.folder, "reel")["photos"])
            line = sample.run(self.ctx(), fetch=self.fetch, check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 6))
        self.assertIn("drafted post", line)
        self.assertEqual(heard, [track], "the reel was made with the current track")
        meta = json.loads(self.queued()[-1]["rule_report"])
        self.assertEqual((meta.get("design"), meta.get("reel_failed"), meta.get("music")), ("reel", None, track.name), meta)

    def test_the_publisher_takes_it_as_soon_as_he_approves(self):
        from convention_social.agents import publisher
        from datetime import datetime, timezone
        self.live()
        self.press("carousel")
        sample.run(self.ctx(), fetch=self.fetch, check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 4))
        row = self.queued()[0]
        ctx = runner.Context("publisher", self.conn, logging.getLogger("t"), config.get_config(), True, 0)
        self.assertIsNotNone(publisher.asap_slot(ctx, row, datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc)))


class FinalCheck(Case):
    def test_a_photo_that_fails_the_final_check_drops_the_draft_and_says_why(self):
        self.live()
        for answer, said in (({"possible_minor": True}, "may be under 18"), ({"personal_details": ["vehicle_plate"]}, "vehicle_plate"),
                             ({"event_kind": "wedding"}, "wedding")):
            self.conn.execute("DELETE FROM final_checks")
            self.press("fan")
            line = sample.run(self.ctx(), fetch=self.fetch, check_client=LookClient(**answer), art_client=ArtClientAny([say("pass")] * 4))
            self.assertIn("did not pass the final check", line)
            self.assertIn(said, line)
            rec = db.one(self.conn, "SELECT status, error FROM sample_posts ORDER BY id DESC LIMIT 1")
            self.assertEqual(rec["status"], "failed")
            self.assertIn(said, rec["error"])
            self.assertEqual(self.queued(), [], "no draft")
            self.assertIn("Not drafted:", self.page())
            self.assertIn(said, self.page())
        self.assertEqual(db.one(self.conn, "SELECT agent FROM errors ORDER BY id DESC LIMIT 1")["agent"], "sample", "on the Agents page")


class Stale(Case):
    def test_a_sample_made_again_since_is_refused_and_says_so(self):
        self.live()
        newer = self.out.parent / "design-29991231-2359"
        newer.mkdir()
        (newer / "index.html").write_text("<p>x</p>")
        (newer / "about.json").write_text(json.dumps({"samples": []}))
        page = self.page()
        self.assertNotIn("<button type=\"submit\">Post this</button>", page)
        self.assertIn("Cannot be posted: these samples were made again since", page)
        r, start = self.press("fan")
        self.assertIn("Not drafted: these samples were made again since", self.said(r))
        self.assertEqual((start.call_count, db.one(self.conn, "SELECT COUNT(*) n FROM sample_posts")["n"]), (0, 0))

    def test_a_sample_with_a_photo_no_longer_approved_is_refused_and_says_so(self):
        self.live()
        gone = design_samples.sample_of(self.folder, "carousel")["photos"][2]
        self.conn.execute("UPDATE photos SET clearance='blocked' WHERE id=?", (gone,))
        self.assertIn(f"Cannot be posted: photo {gone} in it is no longer approved", self.page())
        r, start = self.press("carousel")
        self.assertIn(f"Not drafted: photo {gone} in it is no longer approved", self.said(r))
        self.assertEqual(start.call_count, 0)
        # one pressed before the photo was taken away is refused by the agent too
        sample.ask(self.conn, self.folder, "carousel", design_samples.sample_of(self.folder, "carousel")["photos"])
        line = sample.run(self.ctx(), fetch=self.fetch, check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 4))
        self.assertIn("no longer approved", line)
        self.assertEqual(self.queued(), [])

    def test_photos_other_than_the_samples_are_refused(self):
        self.live()
        r, start = self.press("fan", photos=self.ids[:5])
        self.assertIn("not the photos this sample was made from", self.said(r))
        self.assertEqual(start.call_count, 0)


class DryRun(Case):
    def test_dry_run_makes_no_draft(self):
        self.assertTrue(settings.dry_run(self.conn, "content"))
        r, start = self.press("fan")
        self.assertIn("Not drafted: the content lane is in dry run", self.said(r))
        self.assertEqual(start.call_count, 0)
        sample.ask(self.conn, self.folder, "fan", design_samples.sample_of(self.folder, "fan")["photos"])  # pressed while live
        look = LookClient()
        line = sample.run(self.ctx(), fetch=self.fetch, check_client=look, art_client=ArtClientAny([say("pass")] * 4))
        self.assertIn("dry run", line)
        self.assertEqual((self.queued(), look.calls), ([], 0), "no draft and nothing spent")


class Rotation(Case):
    def test_the_drafts_photos_are_recorded_as_used(self):
        self.live()
        self.press("fan")
        sample.run(self.ctx(), fetch=self.fetch, check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 4))
        qid = self.queued()[0]["id"]
        used = {r["photo_id"] for r in db.rows(self.conn, "SELECT photo_id FROM photo_use WHERE surface='post' AND ref=?", (f"post:{qid}",))}
        self.assertTrue(used, "the use is recorded")
        self.assertEqual(used, set(design_samples.sample_of(self.folder, "fan")["photos"]))


class LeftBehind(IsolatedCase):
    def test_the_hourly_scanner_restarts_a_press_left_behind(self):
        from convention_social.agents import scanner
        conn = db.connect()
        self.addCleanup(conn.close)
        ctx = runner.Context("scanner", conn, logging.getLogger("t"), config.get_config(), True, 0)
        sample.ask(conn, "design-20261015-0900", "fan", [1, 2, 3])
        with mock.patch.object(scanner.runner, "start_agent") as start:
            scanner.run(ctx)
        self.assertIn(mock.call("sample", wait=True), start.call_args_list)
