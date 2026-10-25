"""Chris's photographers (2026-10-15). His question: "What if I have several photographers that I want to be able to share
photos instantly?" His choices: a team member's photo comes to him as a ping with one tap to approve; every instant
photo goes out as an Instagram Story, and he can also post the best to the feed; at most 10 Stories and 2 feed posts a
day from instant photos, everyone together. A photographer is never named in public, and never in a ping (ntfy topics
are not private): only the dashboard says who sent what."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from PIL import Image

from convention_social.agents import content, phone, publisher, team
from convention_social.booking.remote import SiteAPI
from convention_social.buffer.client import BufferClient
from convention_social.core import approve_token, auth, config, db, runner, settings
from convention_social.dashboard import app as dash
from convention_social.dashboard.app import COOKIE, create_app, make_token
from tests._base import IsolatedCase
from tests._fakes import FakeBuffer, add_channels, make_ctx
from tests._photos import jpeg_bytes
from tests.test_content import ArtClientAny, say
from tests.test_hero_upload import LookClient
from tests.test_share_send import FakeSite

ID1, ID2, ID3 = "1760550000000-0123456789abcdef", "1760550060000-fedcba9876543210", "1760550120000-00112233445566ff"


class TeamSite(FakeSite):
    """FakeSite with the team list the Mini writes (worker/index.js PUT /api/team) and each send's sender, as the
    Worker's list gives it ("chris" or "m<number>")."""

    def __init__(self, sends=None, senders=None, **kw):
        super().__init__(sends, **kw)
        self.team = None
        self.senders = dict(senders or {})

    def __call__(self, method, url, headers, payload):
        if url.endswith("/api/team"):
            self.calls.append((method, url, dict(headers), payload))
            self.team = payload
            return type("R", (), {"json": lambda self_: {"ok": True}, "content": b""})()
        r = super().__call__(method, url, headers, payload)
        if method == "GET" and url.endswith("/api/sends"):
            data = r.json()
            for one in data["sends"]:
                one["sender"] = self.senders.get(one["id"], "chris")
            return type("R", (), {"json": lambda self_: data, "content": b""})()
        return r


class TeamCase(IsolatedCase):
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
        for target in (runner, dash):                  # app.py binds runner.start_agent as its own name: both, or a real run starts
            s = mock.patch.object(target, "start_agent", side_effect=lambda *a, **k: self.started.append((a, k)))
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

    def site(self, *pairs):
        """pairs: (send id, sender)."""
        return TeamSite({sid: (jpeg_bytes(size=(2000, 1500), seed=n), "the green room") for n, (sid, _) in enumerate(pairs)},
                        senders=dict(pairs))

    def api(self, site):
        return SiteAPI("tok", base="https://eventcaliber.com", transport=site)

    def run_sends(self, site, **kw):
        return phone.run(self.live(), api=self.api(site), check_client=LookClient(), art_client=ArtClientAny([say("pass")] * 4), **kw)

    def post(self, qid=None):
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,)) if qid else \
            db.one(self.conn, "SELECT * FROM content_queue ORDER BY id DESC LIMIT 1")
        return row, json.loads(row["rule_report"] or "{}")

    def ping_texts(self):
        return [a[0] + " " + a[1] + " " + (k.get("actions") or "") for a, k in self.pings]


class TheTeam(TeamCase):
    def test_a_photographer_is_added_by_first_name_with_a_token_of_their_own_and_the_site_gets_only_its_hash(self):
        site = TeamSite()
        mid, token = team.add(self.conn, "  Anna ", api=self.api(site))
        self.assertGreaterEqual(len(token), 40)
        row = db.one(self.conn, "SELECT * FROM team_members WHERE id=?", (mid,))
        self.assertEqual((row["name"], row["active"]), ("Anna", 1))
        self.assertEqual(row["token_sha256"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, json.dumps(dict(row)), "the token itself is never kept")
        self.assertEqual(site.team["members"], [{"id": mid, "token_sha256": row["token_sha256"], "active": True}])
        self.assertNotIn("Anna", json.dumps(site.team), "no name ever leaves the Mini")
        for bad in ("", "Anna Smith-Jones the third", "anna@example.org", "<b>"):
            with self.assertRaises(team.Refused):
                team.add(self.conn, bad, api=self.api(site))

    def test_switched_off_a_new_token_and_a_one_time_phone_link(self):
        site = TeamSite()
        mid, token = team.add(self.conn, "Ben", api=self.api(site))
        team.set_active(self.conn, mid, False, api=self.api(site))
        self.assertEqual(site.team["members"][0]["active"], False)
        new = team.new_token(self.conn, mid, api=self.api(site))
        self.assertNotEqual(new, token)
        self.assertEqual(site.team["members"][0]["token_sha256"], hashlib.sha256(new.encode()).hexdigest())
        link = team.phone_link(self.conn, mid, api=self.api(site))
        code = link.rsplit("/", 1)[1]
        self.assertTrue(link.startswith("https://eventcaliber.com/join/"))
        j = site.team["joins"][0]
        self.assertEqual((j["code_sha256"], j["member_id"]), (hashlib.sha256(code.encode()).hexdigest(), mid))
        self.assertGreater(datetime.fromisoformat(j["expires_at"].replace("Z", "+00:00")), datetime.now(timezone.utc) + timedelta(days=6))

    def test_a_site_that_does_not_take_the_list_is_said(self):
        class Down:
            def __call__(self, *a):
                raise ConnectionError("no route")
        mid, token = team.add(self.conn, "Cara", api=self.api(Down()))
        self.assertTrue(token)
        ok, why = team.push(self.conn, api=self.api(Down()))
        self.assertFalse(ok)
        self.assertIn("not on the site yet", why)


class TeamSends(TeamCase):
    def setUp(self):
        super().setUp()
        self.mid, _ = team.add(self.conn, "Anna", api=self.api(TeamSite()))

    def test_a_team_photo_is_checked_and_comes_to_chris_with_approve_and_skip_never_naming_them(self):
        site = self.site((ID1, f"m{self.mid}"))
        self.run_sends(site)
        s = db.one(self.conn, "SELECT * FROM phone_sends ORDER BY id DESC LIMIT 1")
        self.assertEqual((s["sender_id"], s["status"]), (self.mid, "drafted"))
        row, meta = self.post()
        self.assertEqual((row["status"], meta["source"], meta["instant"], meta["format"]), ("draft", "team", True, "story"))
        self.assertNotIn("approved_by", meta, "a team photo waits for his tap")
        self.assertEqual(len(self.pings), 1)
        (title, message), kw = self.pings[0]
        self.assertIn("a photo from your team", title)
        self.assertIn(f"http, Approve, ", kw["actions"])
        self.assertIn(f"/queue/{row['id']}/choose-by-token/now", kw["actions"], "Approve is his Post now (#80's choices)")
        self.assertIn(f"http, Skip, ", kw["actions"])
        self.assertIn(f"/queue/{row['id']}/choose-by-token/skip", kw["actions"])
        self.assertIn(f"/media/card/{row['id']}/", kw["attach"])
        self.assertNotIn("Anna", " ".join(self.ping_texts()), "never a name in a ping")
        self.assertEqual(self.started, [], "nothing goes to Buffer before his tap")

    def test_his_tap_approves_it_and_it_goes_out_as_a_story_right_away(self):
        add_channels(self.conn, "instagram")
        self.run_sends(self.site((ID1, f"m{self.mid}")))
        row, _ = self.post()
        token = approve_token.issue(self.conn, row)
        client = TestClient(create_app())
        r = client.post(f"/queue/{row['id']}/choose-by-token/now", data={"token": token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.post(row["id"])[0]["status"], "approved")
        self.assertIn((("publisher",), {}), self.started, "his tap hands it to Buffer at once")
        self.assertEqual(client.post(f"/queue/{row['id']}/choose-by-token/skip", data={"token": token}).status_code, 409, "one tap")
        publisher.publish_ready(make_ctx(self.conn, dry_run=True), client=BufferClient("test-key", conn=self.conn, transport=FakeBuffer()))
        ig = json.loads(self.post(row["id"])[0]["payload"])["instagram"]
        self.assertEqual((ig["mode"], ig["metadata"]["instagram"]["type"]), ("shareNow", "story"))
        self.assertTrue(ig["assets"][0]["image"]["url"].endswith(f"/cards/{row['id']}-story-1.jpg"))

    def test_skip_sets_it_aside(self):
        self.run_sends(self.site((ID1, f"m{self.mid}")))
        row, _ = self.post()
        token = approve_token.issue(self.conn, row)
        client = TestClient(create_app())
        r = client.post(f"/queue/{row['id']}/choose-by-token/skip", data={"token": token})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.post(row["id"])[0]["status"], "rejected")
        self.assertEqual(self.started, [], "a skipped team photo is not drafted again")
        self.assertEqual(client.post(f"/queue/{row['id']}/choose-by-token/skip", data={"token": token}).status_code, 409, "once")

    def test_his_tap_past_the_cap_is_refused_with_the_plain_line(self):
        self.run_sends(self.site((ID1, f"m{self.mid}")))
        row, _ = self.post()
        Cap.stories_today(self, 10)
        r = TestClient(create_app()).post(f"/queue/{row['id']}/choose-by-token/now", data={"token": approve_token.issue(self.conn, row)})
        self.assertEqual(r.status_code, 409)
        self.assertIn("10 Stories", r.text)
        self.assertEqual(self.post(row["id"])[0]["status"], "draft")

    def test_a_sender_not_on_the_team_or_switched_off_is_refused_and_deleted_there(self):
        team.set_active(self.conn, self.mid, False, api=self.api(TeamSite()))
        site = self.site((ID1, f"m{self.mid}"), (ID2, "m99"))
        phone.pull(self.ctx(), self.api(site))
        self.assertIsNone(db.one(self.conn, "SELECT 1 FROM phone_sends"))
        self.assertEqual(site.sends, {})
        self.assertEqual(len(self.pings), 2)
        self.assertTrue(all("not on your team" in t for t in self.ping_texts()))
        self.assertNotIn("Anna", " ".join(self.ping_texts()))

    def test_the_team_page_says_when_in_new_york_time(self):
        self.run_sends(self.site((ID1, f"m{self.mid}")))
        self.conn.execute("UPDATE phone_sends SET created_at='2026-10-15T19:02:00+00:00'")
        anna = [m for m in team.members(self.conn) if m["name"] == "Anna"][0]
        self.assertEqual(anna["last_send_at"], "Oct 15, 15:02", "his own time zone (New York), like the rest of the dashboard")

    def test_the_send_page_says_who_sent_it_for_chris_only(self):
        self.run_sends(self.site((ID1, f"m{self.mid}")))
        self.assertIn("from Anna", phone.recent(self.conn)[0]["line"])


class Stories(TeamCase):
    def test_chris_s_own_send_goes_out_as_a_story_with_a_9_16_card_and_no_caption(self):
        add_channels(self.conn, "instagram")
        self.run_sends(self.site((ID1, "chris")))
        row, meta = self.post()
        self.assertEqual((row["status"], meta["format"], meta["approved_by"]), ("approved", "story", "share"))
        story = json.loads(row["render_paths"])["story"][0]
        with Image.open(story) as im:
            self.assertEqual(im.size, (1080, 1920))
        publisher.publish_ready(make_ctx(self.conn, dry_run=True), client=BufferClient("test-key", conn=self.conn, transport=FakeBuffer()))
        ig = json.loads(self.post(row["id"])[0]["payload"])["instagram"]
        self.assertEqual((ig["mode"], ig["metadata"]["instagram"]["type"], ig["text"]), ("shareNow", "story", ""))
        (title, message), _ = self.pings[0]
        self.assertIn("Story", title + message)

    def test_the_story_card_is_a_slit_scan_with_the_photo_whole(self):
        """Chris, 2026-10-15, on the Story look: "Slit Scan streaks": the photo whole, its own colour drawn out into streaks
        above and below (#79's technique, render/bold.py), the mark and the address clear of Instagram's own bars."""
        from convention_social.render import motion
        out = self.root / "story.jpg"
        motion.story_card(motion.Shot(Image.new("RGB", (2000, 1500), (200, 120, 40)), "", ""), out=out)
        with Image.open(out) as im:
            near, edge = im.getpixel((100, 520)), im.getpixel((100, 5))
            self.assertEqual(im.size, (1080, 1920))
        self.assertGreater(near[0], 120, "the streak next to the photo is the photo's own colour")
        self.assertGreater(sum(near), sum(edge) + 150, "and it fades toward the frame's edge")

    def test_the_ping_shows_the_story_that_goes_out(self):
        import io
        self.run_sends(self.site((ID1, "chris")))
        row, _ = self.post()
        token = approve_token.issue(self.conn, row)
        r = TestClient(create_app()).get(f"/media/card/{row['id']}/{approve_token.card_key(row, token)}.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(r.content)).size, (1080, 1920))

    def test_also_post_to_the_feed_makes_a_feed_post_on_the_same_road(self):
        add_channels(self.conn, "instagram")
        self.run_sends(self.site((ID1, "chris")))
        story_row, _ = self.post()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        self.assertIn(f'action="/queue/{story_row["id"]}/feed"', client.get(f"/queue/{story_row['id']}").text)
        r = client.post(f"/queue/{story_row['id']}/feed", follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        feed, meta = self.post()
        self.assertNotEqual(feed["id"], story_row["id"])
        self.assertEqual((feed["status"], meta["format"], meta["feed_of"], meta["instant"]), ("approved", "feed", story_row["id"], True))
        self.assertIn((("publisher",), {"wait": True}), self.started)
        publisher.publish_ready(make_ctx(self.conn, dry_run=True), client=BufferClient("test-key", conn=self.conn, transport=FakeBuffer()))
        ig = json.loads(self.post(feed["id"])[0]["payload"])["instagram"]
        self.assertEqual((ig["mode"], ig["metadata"]["instagram"]["type"]), ("shareNow", "post"))
        self.assertTrue(ig["text"], "the feed post carries its caption")
        self.assertEqual(team.also_feed(self.conn, story_row["id"])[0], None, "once per photo")

    def test_the_story_s_up_ping_offers_also_post_to_the_feed_with_one_tap(self):
        add_channels(self.conn, "instagram")
        self.run_sends(self.site((ID1, "chris")))
        row, _ = self.post()
        self.conn.execute("UPDATE content_queue SET status='scheduled', buffer_post_ids=? WHERE id=?",
                          (json.dumps({"instagram": "post-1"}), row["id"]))
        client = BufferClient("test-key", conn=self.conn, transport=FakeBuffer(status_sequence=["sent"]))
        with mock.patch.object(publisher.notify, "push") as push:
            publisher.verify_scheduled(make_ctx(self.conn, dry_run=False), client=client)
        title, message = push.call_args[0][:2]
        actions = push.call_args[1]["actions"]
        self.assertIn("Story", title + message)
        self.assertIn("http, Also post to the feed, ", actions)
        self.assertIn(f"/queue/{row['id']}/feed-by-token", actions)
        token = actions.split("body='token=")[1].split("'")[0]
        web = TestClient(create_app())
        r = web.post(f"/queue/{row['id']}/feed-by-token", data={"token": token})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.post()[1]["format"], "feed")


class Cap(TeamCase):
    def stories_today(self, n, fmt="story"):
        now = db.utcnow()
        day = datetime.now(ZoneInfo(config.get_config().timezone)).date().isoformat()
        for _ in range(n):
            db.insert(self.conn, "content_queue", kind="photo", photo_ids="[]", targets='["instagram"]', caption="{}", status="published",
                      rule_report=json.dumps({"instant": True, "format": fmt, "sent_on": day}), created_at=now, updated_at=now)

    def test_past_ten_stories_a_send_waits_with_a_plain_line_and_the_ping_says_so(self):
        self.stories_today(10)
        self.run_sends(self.site((ID1, "chris")))
        row, meta = self.post()
        self.assertEqual(row["status"], "draft", "not approved past the cap")
        self.assertIn("10 Stories", row["last_error"])
        (title, message), _ = self.pings[-1]
        self.assertIn("10 Stories", message)
        self.assertIn("waits", message)
        self.assertEqual(self.started, [])
        self.assertIn(f"waits as post #{row['id']}: today's 10 Stories", phone.recent(self.conn)[0]["line"], "the Send page says why too")

    def test_past_two_feed_posts_also_post_to_the_feed_says_why(self):
        self.stories_today(2, fmt="feed")
        self.run_sends(self.site((ID1, "chris")))
        story_row, _ = self.post()
        qid, why = team.also_feed(self.conn, story_row["id"])
        self.assertIsNone(qid)
        self.assertIn("2 feed posts", why)

    def test_the_publisher_holds_the_cap_too(self):
        add_channels(self.conn, "instagram")
        self.run_sends(self.site((ID1, "chris")))
        row, _ = self.post()
        self.stories_today(10)
        publisher.publish_ready(make_ctx(self.conn, dry_run=True), client=BufferClient("test-key", conn=self.conn, transport=FakeBuffer()))
        after = self.post(row["id"])[0]
        self.assertEqual(after["status"], "draft")
        self.assertIn("10 Stories", after["last_error"])


class ThePage(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_the_team_page_adds_shows_the_token_once_and_switches_off(self):
        settings_page = self.client.get("/settings").text
        self.assertIn('href="/team"', settings_page, "Team sits under Settings (#80's menu)")
        page = self.client.get("/team").text
        self.assertIn('name="name"', page)
        with mock.patch.object(team, "push", return_value=(True, "")):
            r = self.client.post("/team/add", data={"name": "Anna"}, follow_redirects=False)
        self.assertEqual(r.status_code, 200, "the token is on this answer, never in an address")
        token = r.text.split('id="token" type="text" readonly value="')[1].split('"')[0]
        self.assertEqual(db.one(self.conn, "SELECT token_sha256 FROM team_members")["token_sha256"], hashlib.sha256(token.encode()).hexdigest())
        self.assertIn("send them the link, then paste this when it asks", r.text)
        page = self.client.get("/team").text
        self.assertIn("Anna", page)
        self.assertNotIn(token, page, "never shown again")
        mid = db.one(self.conn, "SELECT id FROM team_members")["id"]
        with mock.patch.object(team, "push", return_value=(True, "")):
            self.client.post(f"/team/{mid}/active", data={"active": "0"})
        self.assertEqual(db.one(self.conn, "SELECT active FROM team_members")["active"], 0)
        with mock.patch.object(team, "push", return_value=(True, "")):
            r = self.client.post(f"/team/{mid}/link", follow_redirects=False)
        self.assertEqual(r.status_code, 200)
        self.assertIn("https://eventcaliber.com/join/", r.text)


class TheIcon(IsolatedCase):
    def test_the_site_s_mark_file_draws_as_a_file(self):
        """The upload page's mark and its home-screen icon are the site's /assets/mark.svg. Written without the SVG
        namespace, a browser draws nothing for it as a file (an inline <svg> does not need it; a file does)."""
        from convention_social.site import build
        svg = build.mark_file("aperture", "Event Caliber")
        self.assertTrue(svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" '), svg[:80])
