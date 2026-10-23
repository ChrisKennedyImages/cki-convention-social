"""One Today page and designed drafts that come to the phone (Chris, 2026-10-15).

"we really need to fix this dashboard. its very difficult to understand the UX and UI. design samples is completely in
a different place then todays posts and today has no sign of design examples. why are they examples? cant they just
create them and send them to ntfy for me to approve and watch? everything is just very confusing". Then: "we keep
reusing the same photos too." His choices: all four parts; up to 3 designed drafts a day; on Approve "an option to post
immediately or to follow the pace"; Skip puts the photos back in rotation.

1. Designed drafts on the daily draft's road, each pinged with Post now, Follow the pace and Skip; the variety rules.
2. One Today page: Needs you, This week, Went out; the old pages redirect.
3. Plain words, and the practice-run banner on every page.
4. Four tabs, Settings, every alert with its fix; alerts about networks that are off never show.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from convention_social.agents import content, publisher, sample
try:
    from convention_social.agents import designed
except ImportError:          # the code before 2026-10-15 has no designed lane: each pin that needs it then fails on its own
    designed = None
from convention_social.ai import claude
from convention_social.core import approve_token, auth, config, db, notify, runner, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import report
from convention_social.render import motion
from tests._base import IsolatedCase
from tests._fakes import write_render
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say
from tests.test_hero_upload import LookClient

CLEAN = "Green room before the keynote. Request a quote for your event."
ROOMS = ("stage_panel", "crowd", "backstage", "vendor_hall", "dinner_reception", "portrait")


class Case(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        os.environ["AI_MODEL"] = "template"
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        config.get_config().ensure_dirs()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))
        self.tz = ZoneInfo(config.get_config().timezone)
        starts = mock.patch("convention_social.dashboard.app.start_agent")     # Post now starts the publisher: never a real one here
        starts.start()
        self.addCleanup(starts.stop)

    # ---- photos and drafts
    def photo(self, n: int, room: str = "stage_panel", event: str = "Event A", quality: int = 5) -> int:
        now = db.utcnow()
        if db.one(self.conn, "SELECT 1 FROM drive_folders WHERE drive_id='fe'") is None:
            db.insert(self.conn, "drive_folders", drive_id="fe", name="Con", clearance="cleared", first_seen_at=now, last_seen_at=now)
        pid = db.insert(self.conn, "photos", drive_id=f"d{n}", name=f"d{n}.jpg", folder_id="fe", width=3000, height=2000,
                        thumbnail_link="t", taken_at="2025:02:14 10:00:00", first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name=event, event_kind="business",
                  is_convention=1, quality=quality, possible_minor=0, personal_details="[]", space="interior", residential=0,
                  empty_room=0, sharp=1, light=4, moment=4, shot_type=room, classified_at=now)
        return pid

    def library(self, specs) -> list[int]:
        return [self.photo(i, room, event, q) for i, (room, event, q) in enumerate(specs)]

    def checked(self, pid):
        db.insert(self.conn, "final_checks", photo_id=pid, possible_minor=0, personal_details="[]", model="m", checked_at=db.utcnow(),
                  shot_type="stage_panel", event_kind="business")

    def row(self, ids, *, status="draft", design="fan", source=None, video=False, art="pass", for_day=None, created=None,
            scheduled_for=None, payload=None, asap=None) -> int:
        folder = config.get_config().data_root / "renders" / "posts"
        renders = {"4:5": [write_render(folder, f"c{len(ids)}-{design}-{status}.jpg")], "2:3": [write_render(folder, f"p-{design}.jpg")]}
        if video:
            v = folder / f"r-{status}.mp4"
            v.write_bytes(b"mp4")
            renders = {"9:16": [str(v)], "cover": [write_render(folder, f"cover-{status}.jpg")], "2:3": [write_render(folder, "pin.jpg")]}
        meta = {"for_day": for_day or datetime.now(self.tz).date().isoformat(), "design": design, "art": {"verdict": art}}
        if source:
            meta["source"] = source
        if asap is not None:
            meta["asap"] = asap
        now = created or db.utcnow()
        return db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps(list(ids)), targets=json.dumps(["instagram"]),
                         caption=json.dumps({"instagram": CLEAN, "facebook": CLEAN, "pinterest": CLEAN}), render_paths=json.dumps(renders),
                         rule_report=json.dumps(meta), status=status, scheduled_for=scheduled_for, payload=json.dumps(payload) if payload else None,
                         created_at=now, updated_at=now)

    def meta(self, qid) -> dict:
        return json.loads(db.one(self.conn, "SELECT rule_report FROM content_queue WHERE id=?", (qid,))["rule_report"])

    def status(self, qid) -> str:
        return db.one(self.conn, "SELECT status FROM content_queue WHERE id=?", (qid,))["status"]

    # ---- the designed lane
    def live(self):
        settings.set_dry_run(self.conn, "content", False)

    def ten(self, day_offset=0, hour=10):
        return (datetime.now(self.tz) + timedelta(days=day_offset)).replace(hour=hour, minute=0, second=0, microsecond=0)

    def ctx(self):
        return runner.Context("designed", self.conn, logging.getLogger("t"), config.get_config(), False, 0)

    def fetch(self, row):
        return jpeg_bytes(size=(2400, 1600), seed=row["id"])

    def designed_draft(self, now=None, **kw):
        kw.setdefault("check_client", LookClient(shot_type=None))
        kw.setdefault("art_client", ArtClientAny([say("pass")] * 8))
        kw.setdefault("drafter", claude.TemplateDrafter())
        with mock.patch.object(content.notify, "push_result", return_value="sent") as push:
            line = designed.draft(self.ctx(), self.fetch, now=now or self.ten(), **kw)
        return line, push

    def designed_rows(self):
        return [r for r in db.rows(self.conn, "SELECT * FROM content_queue ORDER BY id")
                if json.loads(r["rule_report"] or "{}").get("source") == "designed"]


def a_library(case: Case) -> list[int]:
    """Eighteen approved photos: six rooms, four events, the vendor hall a single photo from one event."""
    specs = []
    for i in range(18):
        room = ROOMS[i % 6] if i % 6 != 3 else ("vendor_hall" if i == 3 else "crowd")
        specs.append((room, f"Event {'ABCD'[i % 4]}", 5 - (i % 3)))
    return case.library(specs)


# ============================================================ 1. designed drafts
class DesignedDrafts(Case):
    def test_a_designed_draft_is_a_real_draft_on_the_daily_road_and_pings_with_the_three_choices(self):
        self.live()
        ids = a_library(self)
        line, push = self.designed_draft()
        self.assertIn("drafted post #1", line)
        rows = self.designed_rows()
        self.assertEqual(len(rows), 1)
        row, meta = rows[0], json.loads(rows[0]["rule_report"])
        self.assertEqual((row["status"], meta["source"], meta["for_day"], meta["designed_day"]),
                         ("draft", "designed", self.ten().date().isoformat(), self.ten().date().isoformat()))
        self.assertIn(meta["design"], content.NEEDS, "a design the daily draft's renderer makes")
        self.assertEqual(meta["art"]["verdict"], "pass", "the art director looked")
        self.assertTrue(meta["rules"]["instagram"]["ok"], "through the copy rules")
        for pid in json.loads(row["photo_ids"]):
            self.assertIn(pid, ids)
            self.assertIsNotNone(db.one(self.conn, "SELECT 1 FROM final_checks WHERE photo_id=?", (pid,)), "Claude's final check")
        self.assertEqual(report.use_of(self.conn, json.loads(row["photo_ids"]))[json.loads(row["photo_ids"])[0]]["surfaces"], ["post"],
                         "the photos' use is recorded for the rotation")
        kw, qid = push.call_args[1], row["id"]
        self.assertEqual(kw["click"], notify.link(f"/queue/{qid}"), "a tap opens the draft")
        self.assertIn(f"/media/card/{qid}/", kw["attach"], "the card rides the ping")
        for how, label in (("now", "Post now"), ("pace", "Follow the pace"), ("skip", "Skip")):
            self.assertIn(f"http, {label}, {notify.link(f'/queue/{qid}/choose-by-token/{how}')}, method=POST", kw["actions"])
        self.assertEqual(kw["actions"].count("http,"), 3, "three choices, the most ntfy shows")

    def test_up_to_the_days_count_and_no_more_while_that_many_wait(self):
        self.live()
        a_library(self)
        self.assertEqual(designed.per_day(), 3, "three a day unless the Keys page says otherwise")
        for h in range(3):
            self.assertIn("drafted post", self.designed_draft(self.ten(hour=9 + h))[0])
        self.assertIn("the most a day is 3", self.designed_draft(self.ten(hour=13))[0])
        self.assertEqual(len(self.designed_rows()), 3)
        tomorrow = self.ten(day_offset=1)
        self.assertIn("still wait for you", self.designed_draft(tomorrow)[0], "three unanswered: no more pile up")
        self.client.post(f"/queue/{self.designed_rows()[0]['id']}/skip")
        self.assertIn("drafted post", self.designed_draft(tomorrow)[0], "answered one: the next one comes")
        self.assertIn("from 8:00 to 20:00", self.designed_draft(self.ten(day_offset=1, hour=22))[0])

    def test_zero_stops_the_lane_and_a_practice_run_drafts_nothing(self):
        a_library(self)
        self.assertIn("practice run", self.designed_draft()[0])
        self.live()
        os.environ["DESIGNED_PER_DAY"] = "0"
        config.reset()
        self.assertIn("designed drafts are off", self.designed_draft()[0])
        self.assertEqual(self.designed_rows(), [])

    def test_the_designs_come_from_the_renderers_own_list(self):
        """Another session adds new designs to the renderer's list (content.NEEDS, TAKES, make_renderer): they join the
        designed drafts by themselves, and the reel only with music."""
        self.assertEqual(designed.designs(has_music=False), [d for d in content.NEEDS if d not in ("single", "reel")])
        self.assertIn("reel", designed.designs(has_music=True))
        with mock.patch.dict(content.NEEDS, {"mosaic": 4}), mock.patch.dict(content.TAKES, {"mosaic": 4}):
            self.assertIn("mosaic", designed.designs(has_music=False))

    def test_each_design_takes_its_turn(self):
        self.live()
        a_library(self)
        os.environ["DESIGNED_PER_DAY"] = "6"
        config.reset()
        made = []
        for h in range(3):
            self.designed_draft(self.ten(hour=9 + h))
            made.append(json.loads(self.designed_rows()[-1]["rule_report"])["design_wanted"])
        self.assertEqual(made, designed.designs(has_music=False)[:3], "never the same design twice before the others")

    def test_mostly_reels_two_of_every_three_designed_drafts_are_reels(self):
        """Chris, 2026-10-23: "Mostly reels". With music, two of every three designed drafts are reels; the third is the
        still design used least lately. Without music, never a reel."""
        made = []
        for i in range(9):
            d = designed.next_design(self.conn, has_music=True)
            made.append(d)
            self.row([self.photo(200 + i)], design=d, source=designed.SOURCE)
        for k in range(0, 9, 3):
            self.assertEqual(made[k:k + 3].count("reel"), 2, made)
        stills = [d for d in made if d != "reel"]
        self.assertEqual(len(set(stills)), len(stills), "the stills still take turns")
        self.assertNotEqual(designed.next_design(self.conn, has_music=False), "reel")

    def test_a_reels_ping_says_reel_and_opens_it_playing(self):
        title, message = content.ping_words("Event Caliber", "reel", 6, "Saturday", designed=False)
        self.assertTrue(title.startswith("Reel:"), title)
        self.assertIn("sound", message)
        self.assertFalse(content.ping_words("Event Caliber", "poster", 1, "Saturday", designed=False)[0].startswith("Reel"))
        self.assertTrue(content.ping_words("Event Caliber", "reel", 6, "today", designed=True)[0].startswith("Reel:"))
        self.assertTrue(content.ping_click(7, "reel").endswith("/queue/7?play=1"))
        pid = self.photo(1)
        qid = self.row([pid], design="reel", video=True)
        page = self.client.get(f"/queue/{qid}?play=1").text
        self.assertRegex(page, r'<video class="reel"[^>]* autoplay muted', "it opens playing (phones only allow it silent)")
        self.assertNotIn("autoplay", self.client.get(f"/queue/{qid}").text)

    def test_a_reels_ping_carries_its_own_cover(self):
        pid = self.photo(1)
        qid = self.row([pid], design="reel", video=True)
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        token = approve_token.issue(self.conn, row)
        anon = TestClient(create_app())
        r = anon.get(f"/media/card/{qid}/{token}.jpg")
        self.assertEqual(r.status_code, 200)
        cover = json.loads(row["render_paths"])["cover"][0]
        self.assertEqual(r.content, open(cover, "rb").read(), "the reel's cover, not its Pinterest card")

    def test_the_scanner_starts_the_designed_drafts_instead_of_the_samples(self):
        from convention_social.agents import scanner
        self.live()
        with mock.patch.object(designed, "due", return_value=(True, "")), \
             mock.patch("convention_social.core.runner.start_agent") as start, \
             mock.patch("convention_social.render.design_samples.auto") as samples, \
             mock.patch("convention_social.drive.oauth.access_token", side_effect=__import__("convention_social.drive.oauth", fromlist=["x"]).DriveAuthError("signed out")):
            scanner.run(runner.Context("scanner", self.conn, logging.getLogger("t"), config.get_config(), False, 0))
        self.assertIn(mock.call("designed"), start.call_args_list)
        self.assertEqual(samples.call_count, 0, "the samples page is not made any more")


# ============================================================ 1. the three choices
class Choices(Case):
    def test_post_now_posts_immediately_and_follow_the_pace_keeps_its_slot(self):
        """Chris: "an option to post immediately or to follow the pace". Post now is Buffer's shareNow with no time, and the
        publisher is started at once rather than at its next ten-minute run; Follow the pace keeps its slot. No page or
        ping says "35 minutes" for it any more."""
        from convention_social.buffer.client import BufferClient
        from tests._fakes import FakeBuffer, add_channels
        add_channels(self.conn, "instagram")
        pid, other = self.photo(1), self.photo(2, room="crowd")
        self.checked(pid)
        self.checked(other)
        now_q = self.row([pid], scheduled_for="2026-12-01T11:30")
        pace_q = self.row([other], design="single")
        for qid in (now_q, pace_q):
            for text in (self.client.get("/").text, self.client.get(f"/queue/{qid}").text):
                self.assertNotIn("35 minutes", text)
                self.assertIn("Post now: it goes out now.", html.unescape(text))
        with mock.patch("convention_social.dashboard.app.start_agent") as start:
            r = self.client.post(f"/queue/{now_q}/approve", data={"how": "now", "back": "/"}, follow_redirects=False)
            self.client.post(f"/queue/{pace_q}/approve", data={"how": "pace", "back": "/"})
        self.assertEqual([c for c in start.call_args_list if c.args == ("publisher",)], [mock.call("publisher")],
                         "Post now starts the publisher at once; Follow the pace waits for it")
        self.assertIsNone(db.one(self.conn, "SELECT scheduled_for FROM content_queue WHERE id=?", (now_q,))["scheduled_for"],
                          "now, not the time once set")
        said = html.unescape(self.client.get(r.headers["location"]).text)
        self.assertIn(f"Approved post {now_q}. It goes out now.", said)
        self.assertNotIn("35 minutes", said)
        fake = FakeBuffer()
        ctx = runner.Context("publisher", self.conn, logging.getLogger("t"), config.get_config(), False, 0)
        with mock.patch.object(publisher.notify, "push"):
            publisher.publish_ready(ctx, client=BufferClient("test-key", conn=self.conn, transport=fake),
                                    uploader=lambda path, key: f"https://media.example/{key}")
        sent = {row["id"]: json.loads(row["payload"])["instagram"]
                for row in db.rows(self.conn, "SELECT id, payload FROM content_queue WHERE id IN (?, ?)", (now_q, pace_q))}
        self.assertEqual(sent[now_q]["mode"], "shareNow", "Post now: Buffer posts it immediately")
        self.assertNotIn("dueAt", sent[now_q])
        self.assertEqual(sent[pace_q]["mode"], "customScheduled", "Follow the pace: the next open slot")
        self.assertIn("dueAt", sent[pace_q])

    def test_follow_the_pace_takes_the_next_open_slot_even_for_a_photo_from_the_phone(self):
        pid = self.photo(1)
        self.checked(pid)
        qid = self.row([pid], source="phone", asap=True)
        self.client.post(f"/queue/{qid}/approve", data={"how": "pace"})
        self.assertEqual(self.status(qid), "approved")
        self.assertFalse(self.meta(qid)["asap"])
        ctx = runner.Context("publisher", self.conn, logging.getLogger("t"), config.get_config(), True, 0)
        self.assertIsNone(publisher.asap_slot(ctx, db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))),
                          "the planner finds its slot, one post a slot")

    def test_skip_sets_it_aside_and_its_photos_go_back_into_the_rotation(self):
        ids = [self.photo(i) for i in range(3)]
        daily = self.row(ids[:1], for_day=(datetime.now(self.tz).date() + timedelta(days=1)).isoformat())
        idea = self.row(ids[1:], source="designed")
        report.record_use(self.conn, "post", ids, ref="post:x")
        with mock.patch("convention_social.dashboard.app.start_agent") as start:
            self.client.post(f"/queue/{idea}/skip")
            self.assertEqual(start.call_count, 0, "a skipped designed draft is not replaced")
            page = html.unescape(self.client.post(f"/queue/{daily}/skip").text)
            self.assertEqual(start.call_args[0], ("content",), "a skipped daily post is drafted again at once")
        self.assertIn("Its photos go back into the rotation", page)
        for qid in (daily, idea):
            self.assertEqual(self.status(qid), "rejected")
            self.assertEqual(self.meta(qid)["rejected_by"], content.SKIPPED)
        used, _, _ = content.recent_use(self.conn, 400)
        self.assertFalse(used & set(ids), "back in the rotation: no photo of a skipped post sits out")
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM do_not_use"), "never Don't use")
        self.assertEqual(db.one(self.conn, "SELECT clearance FROM photos WHERE id=?", (ids[0],))["clearance"], "inherit")
        self.assertTrue(report.use_of(self.conn, ids), "their use stays on record: they come round after the others")

    def test_the_choices_from_the_ping_are_single_use(self):
        pid = self.photo(1)
        self.checked(pid)
        qid = self.row([pid])
        extras = content.ping_extras(self.conn, db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,)), {"verdict": "pass"})
        token = extras["actions"].split("body='token=", 1)[1].split("'", 1)[0]
        anon = TestClient(create_app())
        self.assertEqual(anon.get(f"/queue/{qid}/choose-by-token/now?token={token}").status_code, 200)
        self.assertEqual(self.status(qid), "draft", "a GET decides nothing")
        r = anon.post(f"/queue/{qid}/choose-by-token/now", data={"token": token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn(f"Approved post {qid}", r.text)
        self.assertTrue(self.meta(qid)["asap"])
        self.assertEqual(anon.post(f"/queue/{qid}/choose-by-token/skip", data={"token": token}).status_code, 409, "one choice per ping")
        self.assertEqual(self.status(qid), "approved")
        other = self.row([pid])
        extras = content.ping_extras(self.conn, db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (other,)), {"verdict": "pass"})
        token = extras["actions"].split("body='token=", 1)[1].split("'", 1)[0]
        r = anon.post(f"/queue/{other}/choose-by-token/skip", data={"token": token})
        self.assertIn("Its photos go back into the rotation", r.text)
        self.assertEqual(self.status(other), "rejected")

    def test_a_draft_the_art_director_did_not_pass_pings_with_open_and_skip_only(self):
        pid = self.photo(1)
        qid = self.row([pid], art="redo")
        actions = content.ping_extras(self.conn, db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,)), {"verdict": "redo"})["actions"]
        self.assertIn(f"view, Open, {notify.link(f'/queue/{qid}')}", actions)
        self.assertNotIn("Post now", actions)
        self.assertIn("http, Skip,", actions)


# ============================================================ 1. variety
class Variety(Case):
    def test_no_photo_goes_out_twice_inside_variety_days_by_any_road(self):
        os.environ["PHOTO_REPEAT_DAYS"] = "7"
        os.environ["VARIETY_DAYS"] = "30"
        config.reset()
        pid = self.photo(1)
        self.checked(pid)
        when = (datetime.now(timezone.utc) - timedelta(days=20)).replace(microsecond=0).isoformat()
        old = self.row([pid], status="published", created=when)
        self.conn.execute("UPDATE content_queue SET published_at=?, updated_at=? WHERE id=?", (when, when, old))
        for source in (None, "designed", "sample", "phone"):
            qid = self.row([pid], status="approved", source=source)
            ctx = runner.Context("publisher", self.conn, logging.getLogger("t"), config.get_config(), True, 0)
            stop = publisher.door(ctx, db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,)))
            self.assertIsNotNone(stop, f"{source or 'daily'}: twenty days ago is inside the thirty")
            self.assertIn(f"already went out as post #{old} in the last 30 days", stop[1])
        self.assertEqual(config.repeat_window(config.get_config()), 30)

    def test_designed_drafts_never_take_a_photo_already_on_a_post(self):
        self.live()
        ids = a_library(self)
        daily = self.row(ids[:4], for_day=(datetime.now(self.tz).date() + timedelta(days=1)).isoformat())
        self.assertTrue(daily)
        for h in range(3):
            self.designed_draft(self.ten(hour=9 + h))
        seen = []
        for r in self.designed_rows():
            photos = json.loads(r["photo_ids"])
            self.assertFalse(set(photos) & set(ids[:4]), "the daily draft's photos sit out")
            self.assertFalse(set(photos) & set(seen), "no photo on two designed drafts")
            seen += photos

    def test_designed_drafts_spread_across_rooms_and_events_least_recently_used_first(self):
        self.live()
        ids = a_library(self)
        report.record_use(self.conn, "site", [ids[0]], ref="site:x")       # the strongest photo was on the site just now
        for h in range(3):
            self.designed_draft(self.ten(hour=9 + h))
        rows = self.designed_rows()
        first = json.loads(rows[0]["photo_ids"])
        self.assertNotEqual(first[0], ids[0], "the least recently used leads; quality only breaks ties")
        rooms = {pid: r["shot_type"] for pid, r in ((p, db.one(self.conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (p,)))
                                                       for p in ids)}
        events = {p: db.one(self.conn, "SELECT convention_name FROM classifications WHERE photo_id=?", (p,))["convention_name"] for p in ids}
        heroes, taken = [], set()
        for r in rows:
            photos = json.loads(r["photo_ids"])
            left = [p for p in ids if p not in taken]                          # the pool this draft drew from
            n_rooms = len({rooms[p] for p in photos})
            n_events = len({events[p] for p in photos})
            self.assertGreaterEqual(n_rooms, min(len(photos), 4, len({rooms[p] for p in left})), f"one room before any repeats: {photos}")
            self.assertEqual(n_events, min(len(photos), 4, len({events[p] for p in left})), f"one event before any repeats: {photos}")
            heroes.append(photos[0])
            taken |= set(photos)
        self.assertEqual(len({events[h] for h in heroes}), 3, "each designed draft of the day leads with a different event")
        vendor = ids[3]
        self.assertLessEqual(sum(vendor in json.loads(r["photo_ids"]) for r in rows), 1,
                             "the only photo of its room is not pinned into every draft")

    def test_post_this_refuses_a_photo_already_on_a_post(self):
        from tests.test_post_from_sample import Case as SampleCase
        case = SampleCase("run")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.live()
        fan = case.press("fan")
        self.assertEqual(fan[0].status_code, 303)
        photos = __import__("convention_social.render.design_samples", fromlist=["x"]).sample_of(case.folder, "fan")["photos"]
        now = db.utcnow()
        db.insert(case.conn, "content_queue", kind="photo", photo_ids=json.dumps(photos[:1]), targets=json.dumps(["instagram"]),
                  caption="{}", status="draft", rule_report="{}", created_at=now, updated_at=now)
        line = sample.run(case.ctx(), fetch=case.fetch, check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 4))
        self.assertIn(f"photo {photos[0]} is already on a post", line)
        self.assertEqual(db.one(case.conn, "SELECT COUNT(*) n FROM content_queue")["n"], 1, "nothing drafted")


# ============================================================ 2. one Today page
class TodayPage(Case):
    def test_needs_you_shows_every_waiting_draft_newest_first_with_its_three_choices(self):
        pid = self.photo(1)
        self.checked(pid)
        older = self.row([pid], design="single")
        newer = self.row([pid], design="fan", source="designed")
        page = self.client.get("/").text
        self.assertIn("Needs you", page)
        self.assertLess(page.index(f'id="d{newer}"'), page.index(f'id="d{older}"'), "newest first")
        for qid in (older, newer):
            self.assertRegex(page, rf'action="/queue/{qid}/approve"><input type="hidden" name="how" value="now">.*?>Post now</button>')
            self.assertRegex(page, rf'action="/queue/{qid}/approve"><input type="hidden" name="how" value="pace">.*?>Follow the pace</button>')
            self.assertRegex(page, rf'action="/queue/{qid}/skip".*?>Skip</button>')
        self.assertIn("Designed for today", page)
        self.assertIn("The daily post for", page)

    def test_a_reel_plays_inline_with_its_sound(self):
        pid = self.photo(1)
        self.checked(pid)
        qid = self.row([pid], design="reel", video=True, source="designed")
        page = self.client.get("/").text
        tag = re.search(rf'<video class="reel" src="/media/render/{qid}/9x16/1"[^>]*>', page)
        self.assertIsNotNone(tag, "the reel plays on Today, not on another page")
        self.assertIn("controls", tag.group(0))
        self.assertIn(f'poster="/media/render/{qid}/cover/1"', tag.group(0))
        self.assertNotIn("muted", tag.group(0), "with its sound")
        self.assertNotIn("autoplay", tag.group(0), "a browser plays an autoplaying video only muted")

    def test_this_week_shows_what_is_scheduled_by_day_as_thumbnails(self):
        pid = self.photo(1)
        tomorrow = datetime.now(self.tz).date() + timedelta(days=1)
        approved = self.row([pid], status="approved", scheduled_for=f"{tomorrow.isoformat()}T11:30")
        day3 = datetime.combine(datetime.now(self.tz).date() + timedelta(days=3), datetime.min.time(), self.tz).replace(hour=10)
        held = self.row([pid], status="scheduled", payload={"instagram": {"dueAt": day3.astimezone(timezone.utc).isoformat()}})
        page = self.client.get("/").text
        week = page[page.index('id="week"'):page.index('id="went-out"')]
        self.assertIn("Tomorrow", week)
        self.assertRegex(week, rf'href="/queue/{approved}"><img src="/media/render/{approved}/4x5/1"[^>]*><span class="t">11:30 am')
        self.assertIn(f"{day3:%A}", week)
        self.assertRegex(week, rf'href="/queue/{held}"><img src="/media/render/{held}/4x5/1"[^>]*><span class="t">10:00 am')

    def test_went_out_links_each_post_on_instagram(self):
        pid = self.photo(1)
        qid = self.row([pid], status="published")
        db.insert(self.conn, "post_history", buffer_post_id="b1", queue_id=qid, service="instagram", sent_at=db.utcnow(), caption="",
                  external_link="https://www.instagram.com/p/ABC123/")
        page = self.client.get("/").text
        went = page[page.index('id="went-out"'):]
        self.assertIn('href="https://www.instagram.com/p/ABC123/"', went)
        self.assertIn("Open on Instagram", went)
        self.assertIn(f'/media/render/{qid}/4x5/1', went)

    def test_the_old_pages_answer_with_a_redirect(self):
        for old, new in (("/posts", "/#went-out"), ("/queue", "/"), ("/library?view=design", "/"), ("/library/design", "/"),
                         ("/library/design/design-20261015-0942/index.html", "/"), ("/more", "/settings"),
                         ("/?show=published", "/history?show=published")):
            r = self.client.get(old, follow_redirects=False)
            self.assertEqual((r.status_code, r.headers.get("location")), (303, new), old)


# ============================================================ 3. plain words
class Words(Case):
    def test_plain_words_everywhere_a_post_shows(self):
        pid = self.photo(1)
        for status in ("would_publish", "rejected", "draft"):
            self.row([pid], status=status)
        page = self.client.get("/history").text
        self.assertIn("Practice run (posting is off)", page)
        self.assertIn("Skipped", page)
        self.assertIn("To approve", page)
        for word in (">would publish<", ">rejected<", ">Queue<", "Review queue"):
            self.assertNotIn(word, page)
            self.assertNotIn(word, self.client.get("/").text)
        self.assertNotIn("samples", report.use_line({"n": 2, "last": "2026-10-15", "surfaces": ["post", "sample"]}))
        self.assertIn("ideas", report.use_line({"n": 2, "last": "2026-10-15", "surfaces": ["post", "sample"]}))

    def test_the_banner_shows_on_every_page_while_posting_or_drafting_is_a_practice_run(self):
        pages = ("/", "/library", "/inquiries", "/settings", "/keys", "/history", "/send")
        for path in pages:
            page = self.client.get(path).text
            self.assertIn("Practice run: Posts are not going out.", page, path)
            self.assertIn('<a href="/agents">Switch it on: Settings, Agents</a>', page, path)
        settings.set_dry_run(self.conn, "publisher", False)
        self.assertIn("Practice run: New drafts cannot go out.", self.client.get("/").text, "the content lane alone")
        settings.set_dry_run(self.conn, "content", False)
        for path in pages:
            self.assertNotIn("Practice run:", self.client.get(path).text, path)


# ============================================================ 4. four tabs, Settings, alerts with their fixes
class Tabs(Case):
    def tabs(self, page):
        bar = re.search(r"<nav>(.*?)</nav>", page, re.S).group(1)
        return re.findall(r">([A-Za-z ]+)</a>", bar)

    def test_four_tabs_and_settings_holds_the_system_pages_grouped(self):
        for path in ("/", "/library", "/inquiries", "/settings", "/agents", "/keys", "/errors", "/outreach"):
            self.assertEqual(self.tabs(self.client.get(path).text), ["Today", "Photos", "Bookings", "Settings"], path)
        page = self.client.get("/settings").text
        system, work = page.index(">System<"), page.index(">Finding work<")
        for href in ("/agents", "/errors", "/keys", "/team", "/buffer"):      # Team (2026-10-15, his photographers): a system page
            self.assertTrue(system < page.index(f'href="{href}"', system) < work, href)
        for href in ("/outreach", "/scout", "/seo", "/learner"):
            self.assertGreater(page.index(f'href="{href}"', work), work, href)
        chips = re.search(r'<div class="chips">(.*?)</div>', self.client.get("/agents").text, re.S).group(1)
        # deliberate change, 2026-10-15: the Team page (his photographers) sits under Settings, after Keys
        self.assertEqual(re.findall(r">([A-Za-z ]+)</a>", chips),
                         ["Agents", "Errors", "Keys", "Team", "Buffer", "Outreach", "Scout", "Search", "Learner"])

    def test_every_alert_has_its_fix_where_one_exists(self):
        pid = self.photo(1)
        self.checked(pid)
        failed = self.row([pid], status="failed")
        runner.record_error(self.conn, "scanner", "drive_auth", "Google Drive sign-in expired")
        runner.record_error(self.conn, "publisher", "post_error", f"post {failed}: Buffer could not send it: instagram: no image")
        runner.record_error(self.conn, "seo", "seo_text", "photo 3: the search text could not be written")
        runner.record_error(self.conn, "publisher", "buffer_budget", "Buffer 24h window at 200/250")
        page = html.unescape(self.client.get("/errors").text)
        self.assertIn('<a class="btn primary" href="/drive/login">Sign in to Drive</a>', page)
        self.assertIn(f"Approve post {failed} again", page)
        self.assertIn("Run the search agent again", page)
        budget = next(c for c in page.split('<div class="card alert">') if "Buffer's request limit" in c)
        self.assertNotIn("/errors/fix", budget, "nothing to press but Dismiss")
        self.assertIn("Dismiss", budget)
        self.assertIn(f"Approve post {failed} again", html.unescape(self.client.get("/").text), "in Needs you too")
        r = self.client.post("/errors/fix", data={"kind": "post_error", "back": "/errors"})
        self.assertEqual(self.status(failed), "approved", "the failed post is approved again")
        self.assertIn(f"Approved post {failed} again", html.unescape(r.text))
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM errors WHERE kind='post_error' AND alerted=0"), "and its alert dismissed")
        with mock.patch("convention_social.dashboard.app.start_agent") as start:
            self.client.post("/errors/fix", data={"kind": "seo_text", "back": "/errors"})
        self.assertEqual(start.call_args[0], ("seo",))

    def test_alerts_about_networks_that_are_off_never_show(self):
        from convention_social.buffer import payloads
        runner.record_error(self.conn, "publisher", "no_channel", "post 5: Not sent to facebook (no connected Buffer channel); "
                                                                  "pinterest (no connected Buffer channel).")
        runner.record_error(self.conn, "publisher", "BufferError", "post 4: Instagram does not support the 'carousel' post type.")
        with mock.patch.object(payloads, "posting_networks", lambda: ("instagram",)):
            for path in ("/errors", "/"):
                page = html.unescape(self.client.get(path).text)
                self.assertNotIn("Not sent to facebook", page, path)
                self.assertIn("does not support the 'carousel' post type", page, path)
        with mock.patch.object(payloads, "posting_networks", lambda: ("instagram", "facebook", "pinterest")):
            self.assertIn("Not sent to facebook", html.unescape(self.client.get("/errors").text), "a network switched back on is said again")
