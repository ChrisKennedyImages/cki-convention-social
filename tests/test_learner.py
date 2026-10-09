"""The learner: times move only on real evidence, an hour a week at most, between 07:00 and 22:00;
photo weights stay between 0.5 and 1.5; dry run suggests and applies nothing; nothing outside its own
settings keys and history table ever changes. No network."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from convention_social.agents import learner
from convention_social.buffer.client import BufferClient
from convention_social.core import auth, config, db, runner, settings
from tests._fakes import AgentCase, FakeBuffer, add_channels, make_ctx

NY = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 10, 3, 0, tzinfo=timezone.utc)        # 23:00 New York, Friday Oct 9
MONDAY, SATURDAY = date(2026, 10, 12), date(2026, 10, 17)
FIRST_DAY = date(2026, 9, 1)


class LearnerCase(AgentCase):
    def setUp(self):
        super().setUp()
        self.conn = self.connect()
        self.n = 0

    def ctx(self, dry_run=False):
        return make_ctx(self.conn, agent="learner", dry_run=dry_run)

    def post(self, network, hh, mm, engagement, *, ours=False, shot=None, kind=None, subject="event", day=None):
        """One sent post with numbers; `ours` also makes the photo, the queue row and the post_history row."""
        self.n += 1
        pid = f"bp-{self.n}"
        local = datetime.combine(day or FIRST_DAY + timedelta(days=self.n), time(hh, mm), NY)
        sent = local.astimezone(timezone.utc).isoformat()
        now = db.utcnow()
        if ours:
            photo = db.insert(self.conn, "photos", drive_id=f"d-{self.n}", name=f"{self.n}.jpg", first_seen_at=now, last_seen_at=now)
            db.insert(self.conn, "classifications", photo_id=photo, method="vision", subject=subject, shot_type=shot,
                      event_kind=kind, classified_at=now)
            qid = db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps([photo]), targets=json.dumps([network]),
                            caption=json.dumps({network: "x"}), status="published", created_at=now, updated_at=now)
            db.insert(self.conn, "post_history", buffer_post_id=pid, queue_id=qid, service=network, sent_at=sent)
        db.insert(self.conn, "post_metrics", buffer_post_id=pid, service=network, ours=int(ours), sent_at=sent,
                  captured_on="2026-10-09", metrics=json.dumps({"likes": engagement}))

    def posts(self, network, hh, mm, count, engagement, **kw):
        for _ in range(count):
            self.post(network, hh, mm, engagement, **kw)

    def ig(self, kind_day=MONDAY, default=time(11, 30)):
        return learner.post_time_for(self.conn, "instagram", default, kind_day)


class Times(LearnerCase):
    def test_nothing_to_learn_changes_nothing(self):
        summary = learner.run(self.ctx(), now=NOW)
        self.assertIn("0 time move(s)", summary)
        self.assertEqual(self.ig(), time(11, 30))
        self.assertEqual(learner.weight_for(self.conn, "cosplay_portrait", "fan"), 1.0)
        note = settings.get(self.conn, learner.NOTE_KEY)
        self.assertTrue(note)
        self.assertIn("0 of the 8 posts", note)

    def test_a_better_hour_moves_the_time_an_hour_a_week_at_most(self):
        self.posts("instagram", 11, 30, 6, 10)
        self.posts("instagram", 14, 0, 6, 40)
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(self.ig(MONDAY), time(12, 30))
        self.assertEqual(self.ig(SATURDAY, time(10, 0)), time(11, 0))
        note = settings.get(self.conn, learner.NOTE_KEY)
        self.assertIn("Instagram moves from 11:30 am to 12:30 pm on weekdays and from 10:00 am to 11:00 am on weekends", note)
        # facebook and pinterest have no numbers: their times stand
        self.assertEqual(learner.post_time_for(self.conn, "facebook", time(9, 30), MONDAY), time(9, 30))
        # the next night: no second move inside the week
        learner.run(self.ctx(), now=NOW + timedelta(days=1))
        self.assertEqual(self.ig(MONDAY), time(12, 30))
        self.assertIn("at most once a week", settings.get(self.conn, learner.NOTE_KEY))
        learner.run(self.ctx(), now=NOW + timedelta(days=7))
        self.assertEqual(self.ig(MONDAY), time(13, 30))
        self.assertEqual(self.ig(SATURDAY, time(10, 0)), time(12, 0))
        learner.run(self.ctx(), now=NOW + timedelta(days=14))
        self.assertEqual(self.ig(MONDAY), time(14, 0), "the last step is shorter than an hour: it lands on the target")
        learner.run(self.ctx(), now=NOW + timedelta(days=28))
        self.assertEqual(self.ig(SATURDAY, time(10, 0)), time(14, 0))
        learner.run(self.ctx(), now=NOW + timedelta(days=35))
        self.assertEqual(self.ig(MONDAY), time(14, 0))
        self.assertIn("already does best", settings.get(self.conn, learner.NOTE_KEY))

    def test_seven_posts_are_not_enough_eight_are(self):
        self.posts("instagram", 11, 30, 2, 10)
        self.posts("instagram", 14, 0, 5, 40)
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(self.ig(), time(11, 30))
        self.assertIn("7 of the 8 posts", settings.get(self.conn, learner.NOTE_KEY))
        self.post("instagram", 11, 30, 10)
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(self.ig(), time(12, 30))

    def test_an_hour_with_four_posts_does_not_count(self):
        self.posts("instagram", 11, 30, 8, 10)
        self.posts("instagram", 14, 0, 4, 400)
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(self.ig(), time(11, 30))
        self.assertEqual(self.ig(SATURDAY, time(10, 0)), time(10, 0))
        times = json.loads(settings.get(self.conn, learner.SUGGESTION_KEY))["times"]
        self.assertEqual(times["instagram"]["best_hour"], 11, "four posts at 2 pm, however good, do not make it the best hour")

    def test_no_hour_with_five_posts_moves_nothing(self):
        for hh in (9, 12, 14, 16):
            self.posts("instagram", hh, 0, 2, 40 if hh == 14 else 10)
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(self.ig(), time(11, 30))
        self.assertIn("no posting hour has 5 posts", settings.get(self.conn, learner.NOTE_KEY))

    def test_a_small_edge_is_noise(self):
        self.posts("instagram", 11, 30, 6, 10)
        self.posts("instagram", 14, 0, 6, 10.5)
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(self.ig(), time(11, 30))
        self.assertEqual(self.ig(SATURDAY, time(10, 0)), time(10, 0))
        self.assertIn("no other hour did clearly better", settings.get(self.conn, learner.NOTE_KEY))

    def test_one_lucky_post_is_shrunk_toward_the_average(self):
        self.assertAlmostEqual(learner.bayes(100, 1, 10), 25.0)
        self.assertAlmostEqual(learner.bayes(1000, 100, 10), (1000 + 50) / 105)

    def test_young_and_old_posts_are_left_out(self):
        self.posts("instagram", 14, 0, 6, 40, day=(NOW - timedelta(days=1)).astimezone(NY).date())
        self.posts("instagram", 14, 0, 6, 40, day=(NOW - timedelta(days=120)).astimezone(NY).date())
        s = learner.learn(self.conn, config.get_config(), NOW)
        self.assertEqual(s.posts, 0)

    def test_never_later_than_ten_pm(self):
        self.posts("pinterest", 20, 30, 6, 5)
        self.posts("pinterest", 23, 30, 6, 50)
        seen = []
        for week in range(5):
            learner.run(self.ctx(), now=NOW + timedelta(days=7 * week))
            seen.append(learner.post_time_for(self.conn, "pinterest", time(20, 30), MONDAY))
        self.assertEqual(seen[:2], [time(21, 30), time(22, 0)])
        self.assertTrue(all(t <= time(22, 0) for t in seen), seen)

    def test_never_earlier_than_seven_am(self):
        self.posts("facebook", 9, 30, 6, 5)
        self.posts("facebook", 5, 0, 6, 50)
        seen = []
        for week in range(5):
            learner.run(self.ctx(), now=NOW + timedelta(days=7 * week))
            seen.append(learner.post_time_for(self.conn, "facebook", time(9, 30), MONDAY))
        self.assertEqual(seen[:3], [time(8, 30), time(7, 30), time(7, 0)])
        self.assertTrue(all(t >= time(7, 0) for t in seen), seen)


class Weights(LearnerCase):
    def test_kinds_that_do_better_weigh_more_inside_the_bounds(self):
        for net, hi, lo, mid in (("instagram", 30, 10, 20), ("pinterest", 3, 1, 2)):
            self.posts(net, 11, 30, 3, hi, ours=True, shot="cosplay_portrait", kind="fan")
            self.posts(net, 11, 30, 3, lo, ours=True, shot="candid", kind="business")
            self.post(net, 11, 30, mid, ours=True, shot="stage_panel", kind="fan")
        learner.run(self.ctx(), now=NOW)
        w = json.loads(settings.get(self.conn, learner.WEIGHTS_KEY))
        self.assertTrue(w["shot_type"])
        # per network first: pinterest's small numbers count as much as instagram's big ones
        self.assertEqual(sorted(w["shot_type"]), ["candid", "cosplay_portrait"])
        self.assertEqual(w["shot_type"]["cosplay_portrait"], 1.27)       # (6 x 1.5 + 5) / 11
        self.assertEqual(w["shot_type"]["candid"], 0.73)                 # (6 x 0.5 + 5) / 11
        self.assertNotIn("stage_panel", w["shot_type"], "2 posts are not enough to weigh")
        self.assertEqual(w["event_kind"], {"fan": 1.23, "business": 0.73})  # fan: (6 x 1.5 + 2 x 1.0 + 5) / 13
        self.assertEqual(learner.weight_for(self.conn, "stage_panel", "fan"), 1.23)
        self.assertEqual(learner.weight_for(self.conn, "cosplay_portrait", "fan"), 1.5, "the product is held to 1.5")
        self.assertEqual(learner.weight_for(self.conn, "candid", "business"), 0.5329)
        self.assertEqual(learner.weight_for(self.conn, None, None), 1.0)
        detail = json.loads(db.one(self.conn, "SELECT detail FROM learner_history ORDER BY id DESC")["detail"])
        self.assertEqual(sorted(detail["photos"]["per_network"]), ["instagram", "pinterest"])
        self.assertIn("Cosplay portrait photos now weigh 1.27, was 1.00", settings.get(self.conn, learner.NOTE_KEY))

    def test_every_weight_is_held_between_half_and_one_and_a_half(self):
        self.posts("instagram", 11, 30, 10, 100, ours=True, shot="cosplay_portrait", kind="fan")
        self.posts("instagram", 11, 30, 10, 0, ours=True, shot="candid", kind="business")
        learner.run(self.ctx(), now=NOW)
        w = json.loads(settings.get(self.conn, learner.WEIGHTS_KEY))
        values = [v for table in w.values() for v in table.values()]
        self.assertEqual(len(values), 4)
        self.assertEqual(w["shot_type"], {"cosplay_portrait": 1.5, "candid": 0.5})
        self.assertTrue(all(0.5 <= v <= 1.5 for v in values), values)

    def test_buildings_are_reported_never_weighted(self):
        self.posts("instagram", 11, 30, 5, 30, ours=True, shot="building_exterior", kind="unknown", subject="architecture")
        self.posts("instagram", 11, 30, 5, 10, ours=True, shot="candid", kind="fan")
        learner.run(self.ctx(), now=NOW)
        w = json.loads(settings.get(self.conn, learner.WEIGHTS_KEY))
        self.assertTrue(w)
        self.assertEqual(sorted(w), ["event_kind", "shot_type"])
        self.assertIn("Building posts did", settings.get(self.conn, learner.NOTE_KEY))
        self.assertIn("The building day stays once a week.", settings.get(self.conn, learner.NOTE_KEY))


class Safety(LearnerCase):
    def snapshot(self):
        tables = ("content_queue", "photos", "classifications", "drive_folders", "do_not_use", "credits", "channels",
                  "conventions", "post_history", "post_metrics", "final_checks", "api_usage", "errors")
        out = {t: [tuple(r) for r in db.rows(self.conn, f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
        out["settings"] = {k: v for k, v in settings.all_settings(self.conn).items()
                           if not k.startswith("learner.") or k == "learner.dry_run"}
        return out

    def test_live_run_touches_only_its_own_keys_and_table(self):
        self.posts("instagram", 11, 30, 6, 10, ours=True, shot="candid", kind="fan")
        self.posts("instagram", 14, 0, 6, 40, ours=True, shot="cosplay_portrait", kind="fan")
        for agent in ("publisher", "content", "learner"):
            settings.set_dry_run(self.conn, agent, True)
        settings.set(self.conn, "watchdog.digest_sent_on", "2026-10-09")
        before = self.snapshot()
        self.assertTrue(before["content_queue"])
        self.assertIn("learner.dry_run", before["settings"])
        learner.run(self.ctx(dry_run=False), now=NOW)
        self.assertEqual(self.snapshot(), before)
        changed = set(settings.all_settings(self.conn)) - set(before["settings"])
        self.assertEqual(changed, set(learner.OWNED_KEYS))
        self.assertTrue(settings.dry_run(self.conn, "learner"), "the learner never flips its own switch")
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM learner_history")["n"], 1)

    def test_dry_run_suggests_and_applies_nothing(self):
        self.posts("instagram", 11, 30, 6, 10, ours=True, shot="candid", kind="fan")
        self.posts("instagram", 14, 0, 6, 40, ours=True, shot="cosplay_portrait", kind="fan")
        summary = learner.run(self.ctx(dry_run=True), now=NOW)
        self.assertIn("DRY RUN suggested: 1 time move(s)", summary)
        s = json.loads(settings.get(self.conn, learner.SUGGESTION_KEY))
        self.assertEqual((s["status"], s["applied"]), ("suggested", False))
        self.assertEqual(s["times"]["instagram"]["weekday"], "12:30")
        self.assertTrue(s["weights"]["shot_type"])
        self.assertIsNone(settings.get(self.conn, learner.TIMES_KEY))
        self.assertIsNone(settings.get(self.conn, learner.WEIGHTS_KEY))
        self.assertEqual(self.ig(), time(11, 30))
        self.assertEqual(learner.weight_for(self.conn, "cosplay_portrait", "fan"), 1.0)
        h = db.one(self.conn, "SELECT status, applied, note FROM learner_history")
        self.assertEqual((h["status"], h["applied"]), ("suggested", 0))
        self.assertTrue(h["note"].startswith("Suggested, not applied"))
        learner.run(self.ctx(dry_run=False), now=NOW)
        self.assertEqual(json.loads(settings.get(self.conn, learner.SUGGESTION_KEY))["status"], "applied")
        self.assertEqual(self.ig(), time(12, 30))

    def test_post_time_for_falls_back_to_the_default(self):
        settings.set(self.conn, learner.TIMES_KEY, "{not json")
        self.assertEqual(self.ig(), time(11, 30))
        entry = {"weekday": "23:30", "weekend": "10:00", "base_weekday": "11:30", "base_weekend": "10:00"}
        settings.set(self.conn, learner.TIMES_KEY, json.dumps({"instagram": entry}))
        self.assertEqual(self.ig(), time(11, 30), "a stored time outside 07:00 to 22:00 is never used")
        entry["weekday"] = "12:30"
        settings.set(self.conn, learner.TIMES_KEY, json.dumps({"instagram": entry}))
        self.assertEqual(self.ig(), time(12, 30))
        self.assertEqual(self.ig(MONDAY, time(12, 0)), time(12, 0), "Chris moved the time himself: his time wins")
        self.assertEqual(learner.post_time_for(self.conn, "instagram", time(11, 30)), time(12, 30), "no day: matched by its base")
        self.assertEqual(learner.post_time_for(self.conn, "tiktok", time(9, 0), MONDAY), time(9, 0))
        settings.set(self.conn, learner.WEIGHTS_KEY, json.dumps({"shot_type": {"candid": "lots", "crowd": 9}}))
        self.assertEqual(learner.weight_for(self.conn, "candid", "fan"), 1.0)
        self.assertEqual(learner.weight_for(self.conn, "crowd", "fan"), 1.5)

    def test_a_new_post_times_setting_starts_learning_again(self):
        self.posts("instagram", 11, 30, 6, 10)
        self.posts("instagram", 14, 0, 6, 40)
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(self.ig(), time(12, 30))
        os.environ["POST_TIMES"] = "instagram=09:00"
        config.reset()
        self.assertEqual(self.ig(MONDAY, time(9, 0)), time(9, 0))
        learner.run(self.ctx(), now=NOW + timedelta(days=1))
        self.assertIn("starts again from your time", settings.get(self.conn, learner.NOTE_KEY))
        self.assertEqual(self.ig(MONDAY, time(9, 0)), time(10, 0), "and moves from his time, an hour at most")


class Running(LearnerCase):
    def test_numbers_are_pulled_only_with_a_key_and_once_a_day(self):
        learner.run(self.ctx(), now=NOW)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM post_metrics")["n"], 0)
        add_channels(self.conn, "instagram")
        fake = FakeBuffer()
        client = BufferClient("test-key", conn=self.conn, agent="learner", transport=fake)
        summary = learner.run(self.ctx(), client=client, now=NOW)
        self.assertIn("pulled numbers for 1 posts", summary)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM post_metrics")["n"], 1)
        learner.run(self.ctx(), client=client, now=NOW + timedelta(minutes=5))
        self.assertEqual(len([c for c in fake.calls if c[0].startswith("query Posts")]), 1)

    def test_runner_end_to_end_starts_in_dry_run(self):
        self.assertEqual(runner.run("learner", learner.run), runner.EXIT_OK)
        row = db.one(self.conn, "SELECT ok, dry_run, summary FROM agent_runs WHERE agent='learner'")
        self.assertIsNotNone(row)
        self.assertEqual((row["ok"], row["dry_run"]), (1, 1))
        self.assertTrue(row["summary"].startswith("DRY RUN suggested"))

    def test_dashboard_page(self):
        from convention_social.dashboard import learner_seo_routes
        from convention_social.dashboard.app import COOKIE, conn_dep, create_app, make_token, render, require_user
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        app = create_app()
        learner_seo_routes.register(app, require_user, conn_dep, render)
        client = TestClient(app)
        self.assertEqual(client.get("/learner", follow_redirects=False).status_code, 307)
        self.posts("instagram", 11, 30, 6, 10, ours=True, shot="candid", kind="fan")
        self.posts("instagram", 14, 0, 6, 40, ours=True, shot="cosplay_portrait", kind="fan")
        learner.run(self.ctx(dry_run=False), now=NOW)
        client.cookies.set(COOKIE, make_token("chris"))
        r = client.get("/learner")
        self.assertEqual(r.status_code, 200)
        self.assertIn("<main>", r.text)
        self.assertIn("12:30 pm weekdays, 11:00 am weekends", r.text)
        self.assertIn("cosplay portrait", r.text)
        self.assertIn("Instagram moves from 11:30 am", r.text)
