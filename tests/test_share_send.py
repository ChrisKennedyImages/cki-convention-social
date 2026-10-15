"""Post to Event Caliber (Chris, 2026-10-15: "i want to be able to text an image from a current event im doing to the
dashboard to auto post immediately. right now you have to be on the dashboard to do that and thats a pain").

A share sheet button on his iPhone sends one photo and a line to eventcaliber.com (worker/index.js /api/send, pinned
in tests/worker_test.mjs). The Mini pulls it every minute, keeps it like a photo from the Send page, deletes it at
the site, drafts it through the daily draft's gates, and because his send is his approval, approves it at once on
the asap rule: a readable plate, a wedding, a caption that still breaks a rule after one rewrite or the art
director's no stop it and ping him why. Dry run says what it would have posted. The posted ping carries the
Instagram link and the dashboard."""
from __future__ import annotations

import json
import logging
import os
import plistlib
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from convention_social.agents import content, inbox, phone, publisher
from convention_social.booking.remote import SiteAPI
from convention_social.buffer.client import BufferClient
from convention_social.core import auth, config, db, notify, runner, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.site import deploy
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_channels, make_ctx
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say
from tests.test_hero_upload import LookClient

ID1, ID2 = "1760550000000-0123456789abcdef", "1760550060000-fedcba9876543210"


class FakeSite:
    """eventcaliber.com's /api/sends as the Worker answers them (the Worker itself is pinned in worker_test.mjs)."""

    def __init__(self, sends=None, broken=()):
        self.sends = dict(sends or {})             # id -> (bytes, note)
        self.broken = set(broken)                  # ids whose download fails
        self.calls = []

    def __call__(self, method, url, headers, payload):
        self.calls.append((method, url, dict(headers), payload))
        path = urlsplit(url).path
        if method == "GET" and path == "/api/sends":
            data = {"sends": [{"id": i, "note": n, "type": "image/jpeg", "size": len(b), "received_at": "2026-10-15T18:00:00.000Z"}
                              for i, (b, n) in sorted(self.sends.items())]}
        elif method == "POST" and path == "/api/sends/ack":
            gone = [i for i in payload["ids"] if self.sends.pop(i, None) is not None]
            data = {"ok": True, "deleted": len(gone)}
        elif method == "GET" and path.startswith("/api/sends/"):
            sid = path.rsplit("/", 1)[1]
            if sid in self.broken:
                raise ConnectionError("the network dropped")
            return types.SimpleNamespace(content=self.sends[sid][0], json=lambda: {})
        else:
            raise AssertionError(f"{method} {path}")
        return types.SimpleNamespace(json=lambda: data, content=b"")


class ShareCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        config.get_config().ensure_dirs()
        self.pings = []
        p = mock.patch.object(phone.notify, "push", side_effect=lambda *a, **k: self.pings.append((a, k)) or True)
        p.start()
        self.addCleanup(p.stop)
        self.started = []
        s = mock.patch.object(phone.runner, "start_agent", side_effect=lambda *a, **k: self.started.append((a, k)))
        s.start()
        self.addCleanup(s.stop)

    def ctx(self, dry=True):
        return runner.Context("phone", self.conn, logging.getLogger("t"), config.get_config(), dry, 0)

    def live(self, publisher_live=True):
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        settings.set_dry_run(self.conn, "content", False)
        settings.set_dry_run(self.conn, "publisher", not publisher_live)
        return self.ctx(dry=False)

    def site(self, *ids, note="the keynote room, just before the doors", **kw):
        return FakeSite({i: (jpeg_bytes(size=(2000, 1500), seed=n), note) for n, i in enumerate(ids or (ID1,))}, **kw)

    def api(self, site):
        return SiteAPI("tok", base="https://eventcaliber.com", transport=site)

    def post(self):
        row = db.one(self.conn, "SELECT * FROM content_queue ORDER BY id DESC LIMIT 1")
        return row, (json.loads(row["rule_report"]) if row else {})

    def send_row(self):
        return db.one(self.conn, "SELECT * FROM phone_sends ORDER BY id DESC LIMIT 1")


class TheSiteAPI(ShareCase):
    def test_list_fetch_and_delete_with_the_minis_token_in_a_header_never_the_address(self):
        site = self.site(ID1)
        api = self.api(site)
        self.assertEqual([s["id"] for s in api.sends()], [ID1])
        self.assertEqual(api.send_bytes(ID1), site.sends[ID1][0])
        self.assertEqual(api.ack_sends([ID1]), 1)
        self.assertEqual(api.ack_sends([]), 0)
        self.assertEqual(site.sends, {}, "deleted at the site")
        for method, url, headers, _ in site.calls:
            self.assertEqual(headers["Authorization"], "Bearer tok")
            self.assertNotIn("tok", urlsplit(url).query)
        self.assertEqual([(m, urlsplit(u).path) for m, u, _, _ in site.calls],
                         [("GET", "/api/sends"), ("GET", f"/api/sends/{ID1}"), ("POST", "/api/sends/ack")])


class Pull(ShareCase):
    def test_each_send_is_kept_like_one_from_the_send_page_then_deleted_at_the_site(self):
        site = self.site(ID1, ID2)
        line = phone.pull(self.ctx(), self.api(site))
        self.assertIn("kept 2", line)
        self.assertEqual(site.sends, {}, "R2 cleanup: each one deleted at the site once kept")
        rows = db.rows(self.conn, "SELECT s.*, p.folder_id, p.clearance, p.source FROM phone_sends s JOIN photos p ON p.id = s.photo_id ORDER BY s.id")
        self.assertEqual([(r["via"], r["remote_id"], r["status"], r["note"]) for r in rows],
                         [("share", ID1, "pending", "the keynote room, just before the doors"),
                          ("share", ID2, "pending", "the keynote room, just before the doors")])
        self.assertEqual({(r["folder_id"], r["clearance"], r["source"]) for r in rows}, {("phone", "cleared", "phone")})
        self.assertTrue(all(s["line"].startswith("from the share sheet, waiting its turn") for s in phone.recent(self.conn)))

    def test_a_large_photo_from_the_share_sheet_is_kept_at_3000_pixels(self):
        from convention_social import storage
        site = FakeSite({ID1: (jpeg_bytes(size=(4000, 3000)), "")})
        phone.pull(self.ctx(), self.api(site))
        p = db.one(self.conn, "SELECT width, height FROM photos ORDER BY id DESC LIMIT 1")
        self.assertEqual((p["width"], p["height"]), (storage.MAX_EDGE, 2250), "kept small, like every photo on the Mini (#74)")

    def test_a_send_kept_before_the_delete_went_is_not_kept_twice(self):
        site = self.site(ID1)
        with mock.patch.object(SiteAPI, "ack_sends", side_effect=ConnectionError("the network dropped")):
            phone.pull(self.ctx(), self.api(site))
        self.assertIn(ID1, site.sends, "the delete did not go: still at the site")
        phone.pull(self.ctx(), self.api(site))
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM phone_sends")["n"], 1, "kept once")
        self.assertEqual(site.sends, {}, "and deleted at the site on the next pull")

    def test_a_download_that_fails_is_left_at_the_site_for_the_next_pull(self):
        site = self.site(ID1, broken={ID1})
        phone.pull(self.ctx(), self.api(site))
        self.assertIn(ID1, site.sends)
        self.assertIsNone(self.send_row())
        site.broken.clear()
        phone.pull(self.ctx(), self.api(site))
        self.assertEqual(self.send_row()["remote_id"], ID1)
        self.assertEqual(site.sends, {})

    def test_a_refused_photo_is_deleted_there_and_he_is_told_why(self):
        site = FakeSite({ID1: (jpeg_bytes(size=(800, 500)), ""), ID2: (b"not a photo", "")})
        phone.pull(self.ctx(), self.api(site))
        self.assertIsNone(self.send_row(), "nothing kept")
        self.assertEqual(site.sends, {}, "it never becomes a photo: deleted there too")
        texts = [a[0] + " " + a[1] for a, _ in self.pings]
        self.assertEqual(len(texts), 2)
        self.assertTrue(any("too small for a post" in t for t in texts), texts)
        self.assertTrue(any("not a photo file" in t for t in texts), texts)
        self.assertTrue(all("not posted" in t for t in texts))
        self.assertTrue(all(k["dry_run"] is False for _, k in self.pings), "he sent it: he hears back, dry run or not")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE agent='phone' AND kind='send'")["n"], 2)

    def test_a_site_that_cannot_be_reached_is_said_once_after_a_few_minutes_never_per_minute(self):
        class Down:
            def __call__(self, *a):
                raise ConnectionError("no route")
        for _ in range(phone.PULL_QUIET_FAILURES - 1):
            phone.pull(self.ctx(), self.api(Down()))
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM errors WHERE kind='send_pull'"), "a blip is not news")
        for _ in range(3):
            phone.pull(self.ctx(), self.api(Down()))
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM errors WHERE kind='send_pull'")["n"], 1, "said once while it stands")
        phone.pull(self.ctx(), self.api(self.site()))
        self.assertEqual(settings.get(self.conn, phone.PULL_FAILURES_KEY), "0", "a good pull starts the count again")


class Approved(ShareCase):
    def test_his_send_is_his_approval_and_it_goes_out_now(self):
        ctx = self.live()
        site = self.site(ID1)
        line = phone.run(ctx, api=self.api(site), check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        self.assertIn("approved by your send", line)
        row, meta = self.post()
        self.assertEqual(row["status"], "approved")
        self.assertTrue(row["approved_at"])
        self.assertEqual((meta["source"], meta["asap"], meta["approved_by"], meta["art"]["verdict"]), ("share", True, "share", "pass"))
        s = self.send_row()
        self.assertEqual((s["status"], s["queue_id"], s["via"]), ("drafted", row["id"], "share"))
        self.assertEqual(len(self.pings), 1, "one ping: it is going, with no Approve to press")
        (title, message), kw = self.pings[0]
        self.assertIn("going out now", title)
        self.assertIn("going to Instagram now", message)
        self.assertNotIn("take back", message, "Right away (2026-10-15): there is no window to stop it in")
        self.assertNotIn("Approve", kw.get("actions") or "")
        self.assertTrue(kw["click"].endswith(f"/queue/{row['id']}"))
        self.assertIn(f"/media/card/{row['id']}/", kw["attach"], "the card he is sending out")
        self.assertIn((("publisher",), {"wait": True}), self.started, "the publisher hands it to Buffer now, not in ten minutes")
        self.assertEqual(site.sends, {})

    def buffer_input(self, now=None):
        """The publisher's dry run of what is approved: the Instagram CreatePostInput it would send."""
        publisher.publish_ready(make_ctx(self.conn, dry_run=True), client=BufferClient("test-key", conn=self.conn, transport=FakeBuffer()),
                                now=now)
        return json.loads(self.post()[0]["payload"])["instagram"]

    def test_buffer_is_told_to_post_it_now_with_no_window(self):
        """Chris, 2026-10-15, asked whether to keep the 35 minutes to pull it back or post at once: "Right away"."""
        add_channels(self.conn, "instagram")
        phone.run(self.live(), api=self.api(self.site()), check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        ig = self.buffer_input(now=datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc))
        self.assertEqual(ig["mode"], "shareNow")
        self.assertNotIn("dueAt", ig)

    def test_a_photo_from_the_send_page_keeps_its_window(self):
        add_channels(self.conn, "instagram")
        ctx = self.live()
        phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)), "the main hall")
        with mock.patch.object(content.notify, "push"):
            phone.run(ctx, check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        self.conn.execute("UPDATE content_queue SET status='approved', approved_at=? WHERE id=?", (db.utcnow(), self.post()[0]["id"]))
        ig = self.buffer_input(now=datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc))      # 15:00 in New York
        self.assertEqual((ig["mode"], ig["dueAt"]), ("customScheduled", "2026-10-15T19:35:00Z"), "the asap slot, 35 minutes on")

    def test_a_time_he_sets_on_a_share_post_still_wins(self):
        add_channels(self.conn, "instagram")
        phone.run(self.live(), api=self.api(self.site()), check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        self.conn.execute("UPDATE content_queue SET scheduled_for='2026-10-16T09:00' WHERE id=?", (self.post()[0]["id"],))
        ig = self.buffer_input(now=datetime(2026, 10, 15, 19, 0, tzinfo=timezone.utc))
        self.assertEqual((ig["mode"], ig["dueAt"]), ("customScheduled", "2026-10-16T13:00:00Z"))

    def test_the_card_never_says_photography_twice_when_no_room_is_confirmed(self):
        """2026-10-15 (#79): a post prints the confirmed room's words or EVENT PHOTOGRAPHY, with EVENT CALIBER as the small
        line so it never repeats; a conference photo had "CONFERENCE PHOTOGRAPHY" over "EVENT PHOTOGRAPHY"."""
        from convention_social.render import motion
        seen, real = [], motion.single_post

        def spy(shot, copy, **kw):
            seen.append((shot.room, kw.get("kicker")))
            return real(shot, copy, **kw)
        with mock.patch.object(motion, "single_post", spy):
            phone.run(self.live(), api=self.api(self.site()), check_client=LookClient(event_kind="business"),
                      art_client=ArtClientAny([say("pass")]))
        self.assertEqual(seen[0], ("EVENT PHOTOGRAPHY", "EVENT CALIBER"))
        with mock.patch.object(motion, "single_post", spy):
            phone.run(self.live(), api=self.api(self.site(ID2)), check_client=LookClient(event_kind="business", room="main_stage"),
                      art_client=ArtClientAny([say("pass")]))
        self.assertEqual(seen[-1], ("MAIN STAGE", "CONFERENCE PHOTOGRAPHY"), "a confirmed room keeps the kind of work above it")

    def test_a_readable_plate_or_a_wedding_stops_it_and_he_hears_why(self):
        ctx = self.live()
        for i, (look, word) in enumerate(((LookClient(personal_details=["vehicle_plate"]), "it shows a readable car plate"),
                                          (LookClient(event_kind="wedding"), "a wedding"))):
            self.pings.clear()
            phone.run(ctx, api=self.api(self.site(ID1 if i == 0 else ID2)), check_client=look, art_client=ArtClientAny([say("pass")]))
            self.assertIsNone(db.one(self.conn, "SELECT 1 FROM content_queue WHERE status IN ('approved', 'scheduled')"), "nothing posts")
            self.assertEqual(self.send_row()["status"], "failed")
            self.assertEqual(len(self.pings), 1)
            (title, message), kw = self.pings[0]
            self.assertIn("not posted", title + message)
            self.assertIn(word, message)
            self.assertNotIn("vehicle_plate", message, "plain words on the phone, never the check's code")
            self.assertNotIn("..", message)
            self.assertFalse(kw["dry_run"])
            self.assertIn(f"from the share sheet, not posted: {word}", phone.recent(self.conn)[0]["line"], "the Send page, in the same words")
        self.assertEqual(self.started, [], "the publisher is not started for a photo that stopped")

    def test_a_caption_that_still_breaks_a_rule_after_one_rewrite_stops_it(self):
        ctx = self.live()
        broken = ("back", f"The instagram {publisher.CAPTION_BACK}: it names a known event.")
        with mock.patch.object(publisher, "door", return_value=broken) as door, \
                mock.patch.object(content, "mend_captions", return_value={"instagram": "rewritten"}) as mend:
            phone.run(ctx, api=self.api(self.site()), check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        self.assertEqual(mend.call_count, 1, "rewritten once")
        self.assertEqual(door.call_count, 2, "checked again after the rewrite")
        row, _ = self.post()
        self.assertEqual(row["status"], "draft", "it waits for him; nothing posts")
        self.assertIn("still breaks a rule", row["last_error"])
        self.assertEqual(self.send_row()["status"], "failed")
        (title, message), kw = self.pings[0]
        self.assertIn("not posted", title + message)
        self.assertIn("not posted: the suite rewrote the captions and one still breaks a rule. The Instagram caption", message)
        self.assertNotIn("..", message)
        self.assertTrue(kw["click"].endswith(f"/queue/{row['id']}"))

    def test_the_art_directors_no_stops_it(self):
        ctx = self.live()
        phone.run(ctx, api=self.api(self.site()), check_client=LookClient(), art_client=ArtClientAny([say("reject", notes="Flat light.")]))
        row, _ = self.post()
        self.assertEqual(row["status"], "rejected")
        (title, message), _ = self.pings[0]
        self.assertIn("not posted", title + message)
        self.assertIn("the art director turned it back: Flat light. Tap to see it.", message)

    def test_an_art_director_who_could_not_look_leaves_it_for_his_approve(self):
        ctx = self.live()

        class Broken:
            beta = messages = property(lambda self: self)

            def create(self, **kw):
                raise RuntimeError("overloaded")
        phone.run(ctx, api=self.api(self.site()), check_client=LookClient(), art_client=Broken())
        row, meta = self.post()
        self.assertEqual((row["status"], meta["art"]["verdict"]), ("draft", "not reviewed"))
        (title, message), kw = self.pings[0]
        self.assertIn("not posted", title + message)
        self.assertIn("the art director could not look at it this time. It waits for your Approve.", message)
        self.assertTrue(kw["click"].endswith(f"/queue/{row['id']}"))

    def test_a_photo_from_the_send_page_still_waits_for_his_approve(self):
        ctx = self.live()
        phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)), "the main hall")
        with mock.patch.object(content.notify, "push") as push:
            phone.run(ctx, check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        row, meta = self.post()
        self.assertEqual(row["status"], "draft")
        self.assertNotIn("approved_by", meta)
        self.assertIn("Approve", push.call_args[1]["actions"])


class DryRun(ShareCase):
    def test_the_content_lane_in_dry_run_drafts_it_and_says_it_was_not_posted(self):
        from tests.test_phone import FreeSorter
        site = self.site()
        line = phone.run(self.ctx(), api=self.api(site), sorter=FreeSorter())
        self.assertIn("DRY RUN", line)
        row, _ = self.post()
        self.assertEqual(row["status"], "draft", "never approved without Claude's final check")
        (title, message), kw = self.pings[0]
        self.assertIn("Dry run", title + message)
        self.assertIn("not posted", message)
        self.assertIn(f"post {row['id']}", message)
        self.assertFalse(kw["dry_run"], "he sent it: the answer reaches his phone")
        self.assertEqual(self.started, [])
        self.assertEqual(site.sends, {}, "kept on the Mini and deleted at the site in dry run too")

    def test_the_publisher_in_dry_run_says_what_would_have_gone_out(self):
        ctx = self.live(publisher_live=False)
        phone.run(ctx, api=self.api(self.site()), check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        row, _ = self.post()
        self.assertEqual(row["status"], "approved", "approved by his send; the publisher's dry run takes it no further")
        (title, message), _ = self.pings[0]
        self.assertIn("Dry run", title + message)
        self.assertIn("would have gone out on Instagram right away", message)


class PostedPing(ShareCase):
    def test_the_posted_ping_opens_instagram_and_carries_the_dashboard(self):
        add_channels(self.conn, "instagram")
        ctx = self.live()
        phone.run(ctx, api=self.api(self.site()), check_client=LookClient(), art_client=ArtClientAny([say("pass")]))
        row, _ = self.post()
        self.conn.execute("UPDATE content_queue SET status='scheduled', buffer_post_ids=? WHERE id=?",
                          (json.dumps({"instagram": "post-1"}), row["id"]))
        pctx = make_ctx(self.conn, dry_run=False)
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(status_sequence=["sent"]))
        with mock.patch.object(publisher.notify, "push") as push:
            publisher.verify_scheduled(pctx, client=client)
        title, message = push.call_args[0][:2]
        kw = push.call_args[1]
        self.assertEqual(kw["click"], "https://www.instagram.com/p/abc123/")
        self.assertIn("view, Instagram, https://www.instagram.com/p/abc123/", kw["actions"])
        self.assertIn(f"/queue/{row['id']}", kw["actions"])
        self.assertIn("is on Instagram", title + message)
        self.assertIn("Delete", message)

    def test_an_ordinary_posted_ping_is_as_it_was(self):
        add_channels(self.conn, "instagram")
        from tests._fakes import add_post
        qid = add_post(self.conn, [], ("instagram",), status="scheduled")
        self.conn.execute("UPDATE content_queue SET buffer_post_ids=? WHERE id=?", (json.dumps({"instagram": "post-1"}), qid))
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(status_sequence=["sent"]))
        with mock.patch.object(publisher.notify, "push") as push:
            publisher.verify_scheduled(make_ctx(self.conn, dry_run=False), client=client)
        self.assertEqual(push.call_args[0][0], f"{config.get_config().brand_name}: posted")
        self.assertIsNone(push.call_args[1].get("actions"))


class EveryMinute(ShareCase):
    def test_a_quiet_minute_leaves_no_run_behind(self):
        site = FakeSite()
        with mock.patch.object(SiteAPI, "from_config", return_value=self.api(site)), \
                mock.patch.object(runner, "main_for") as main_for, mock.patch.object(sys, "argv", ["phone", "--when-waiting"]):
            with self.assertRaises(SystemExit) as cm:
                phone.main()
            self.assertEqual(cm.exception.code, 0)
            self.assertEqual(main_for.call_count, 0)
            self.assertIsNone(db.one(self.conn, "SELECT 1 FROM agent_runs WHERE agent='phone'"))
            site.sends[ID1] = (jpeg_bytes(size=(2000, 1500)), "")
            phone.main()
            self.assertEqual(main_for.call_args[0][0], "phone", "a send waiting: the full run")

    def test_a_send_left_on_the_mini_runs_without_the_site(self):
        phone.keep(self.conn, jpeg_bytes(size=(2000, 1500)))
        with mock.patch.object(SiteAPI, "from_config", return_value=None), mock.patch.object(runner, "main_for") as main_for, \
                mock.patch.object(sys, "argv", ["phone", "--when-waiting"]):
            phone.main()
        self.assertEqual(main_for.call_count, 1)

    def test_the_launchd_job_runs_every_minute_on_our_prefix(self):
        path = Path(config.REPO_ROOT) / "launchd" / "com.chriskennedyimages.conventionsocial.phone.plist.template"
        text = path.read_text()
        for k, v in {"__USER__": "u", "__PYTHON__": "/p", "__REPO__": "/r", "__HOME__": "/h", "__DATA__": "/d"}.items():
            text = text.replace(k, v)
        plist = plistlib.loads(text.encode())
        self.assertEqual(plist["Label"], "com.chriskennedyimages.conventionsocial.phone")
        self.assertEqual(plist["ProgramArguments"][1:], ["-m", "convention_social.agents.phone", "--when-waiting"])
        self.assertEqual(plist["StartInterval"], 60)

    def test_the_inbox_starts_the_phone_agent_when_sends_wait_at_the_site(self):
        """Before go-live installs the one-minute job, the ten-minute inbox run is the pickup."""
        from tests.test_booking import FakeSite as BookingSite
        booking = BookingSite([])
        sends = self.site()

        def transport(method, url, headers, payload):
            return (sends if "/api/sends" in url else booking)(method, url, headers, payload)
        ictx = runner.Context("inbox", self.conn, logging.getLogger("t"), config.get_config(), True, 0)
        with mock.patch.object(inbox.runner, "start_agent") as start:
            inbox.run(ictx, api=self.api(transport))
        self.assertEqual((start.call_args[0], start.call_args[1]), (("phone",), {"wait": True}))
        sends.sends.clear()
        with mock.patch.object(inbox.runner, "start_agent") as start:
            inbox.run(ictx, api=self.api(transport))
        self.assertEqual(start.call_count, 0)


class TheToken(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        self.env_file = self.root / "dot.env"
        self.env_file.write_text("")
        os.environ["CCS_ENV_FILE"] = str(self.env_file)
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_keys_page_holds_it_as_a_secret(self):
        page = self.client.get("/keys").text
        self.assertIn('name="SEND_TOKEN"', page)
        self.assertIn('type="password" name="SEND_TOKEN"', page)
        self.assertIn('action="/keys/send-token"', page)

    def test_the_send_page_says_share_sheet_photos_post_on_their_own(self):
        """Chris, 2026-10-15: "Add the line": the page's own photos wait for his Approve; the share sheet's do not."""
        page = self.client.get("/send").text
        self.assertIn("Photos from the Post to Event Caliber share sheet on your iPhone are approved by the send and post on "
                      "their own after the checks.", page)

    def test_make_one_saves_a_long_random_token_shows_it_once_and_the_site_follows(self):
        r = self.client.post("/keys/send-token", follow_redirects=False)
        self.assertEqual(r.status_code, 200, "the page itself: never a redirect with the token in its address")
        config.reset()
        token = config.getenv("SEND_TOKEN")
        self.assertGreaterEqual(len(token or ""), 40)
        self.assertIn(token, r.text, "shown once, to copy into the Shortcut")
        self.assertTrue(settings.get(self.conn, deploy.SEND_TOKEN_CHANGED_KEY), "the site takes it on its next publish")
        self.assertNotIn(token, self.client.get("/keys").text, "never shown again")
        r2 = self.client.post("/keys/send-token", follow_redirects=False)
        config.reset()
        self.assertNotEqual(config.getenv("SEND_TOKEN"), token, "a new one replaces the old")

    def test_every_deploy_puts_it_on_the_worker_and_a_change_publishes_the_site(self):
        self.assertIn(("SEND_TOKEN", "SEND_TOKEN"), deploy.WORKER_SECRETS)
        put = []
        os.environ["SEND_TOKEN"] = "t" * 43
        deploy.put_secrets(self.root, self.conn, put=lambda repo, name, value: put.append((name, value)) or True)
        self.assertIn(("SEND_TOKEN", "t" * 43), put)
        from datetime import datetime, timedelta, timezone
        settings.set(self.conn, deploy.SEND_TOKEN_CHANGED_KEY, (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat())
        go, why = deploy.photos_pending(self.conn)
        self.assertTrue(go)
        self.assertIn("send token", why)


class Migration(IsolatedCase):
    """core/db.py applies every migration file not yet recorded in schema_migrations, in file-name order, and records it by
    its name. Main has 0076_doctor and 0077_final_check_room; this change's file is 0078_share_sends."""

    def schema(self, conn):
        return {t: sorted(r[1] for r in conn.execute(f"PRAGMA table_info({t})")) for t in db.table_names(conn)}

    def test_a_fresh_database_and_the_minis_existing_one_end_with_every_table(self):
        files = db.migration_files()
        self.assertEqual([p.stem for p in files if p.stem.startswith("0078_")], ["0078_share_sends"], "its own number")
        stems = [p.stem for p in files]
        self.assertGreater(stems.index("0078_share_sends"), max(stems.index("0076_doctor"), stems.index("0077_final_check_room")))
        fresh = db.connect(self.root / "fresh.sqlite3")
        self.addCleanup(fresh.close)
        with mock.patch.object(db, "migration_files", return_value=[p for p in files if p.stem != "0078_share_sends"]):
            old = db.connect(self.root / "old.sqlite3")                 # the Mini's database as main leaves it
        self.addCleanup(old.close)
        self.assertNotIn("via", self.schema(old)["phone_sends"])
        self.assertEqual(db.migrate(old), ["0078_share_sends"], "only this change's file is applied to it")
        self.assertEqual(self.schema(old), self.schema(fresh), "the same tables and columns either way")
        self.assertTrue({"via", "remote_id"} <= set(self.schema(fresh)["phone_sends"]))
        self.assertEqual(db.migrate(old), [], "applied once")
