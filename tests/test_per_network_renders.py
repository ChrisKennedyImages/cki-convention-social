"""Chris, 2026-11-02, on draft #61's page (photo 921, LinkedIn only): "The LinkedIn photo is a completely fully branded photo."
The page had led with the Instagram card. Nothing is drawn for a network a draft is not going to, and the draft page shows each
ticked network what it will receive, by the publisher's own map (payloads.ASPECT_FOR), labeled by network."""
from __future__ import annotations

import json
import os
from unittest import mock
from pathlib import Path

from fastapi.testclient import TestClient

from convention_social.agents import art_director, content, publisher
from convention_social.ai.claude import NETWORKS
from convention_social.buffer import payloads
from convention_social.core import auth, config
from convention_social.core import previews
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.render.photo import LINKEDIN_PHOTO
from tests.test_linkedin_logo import DraftCase
from tests.test_repeat_per_network import MONDAY_6AM, aired


class Renders(DraftCase):
    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def page(self, qid) -> str:
        return self.client.get(f"/queue/{qid}").text

    def drawn(self) -> list[str]:
        return sorted(p.name for p in (config.get_config().data_root / "renders" / "posts").rglob("*.jpg"))

    def test_a_linkedin_only_draft_renders_the_photo_as_shot_alone_and_its_page_shows_only_that(self):
        aired(self.conn, self.pid, ["instagram"])                       # the window holds Instagram: LinkedIn alone goes
        content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        self.assertIn("linkedin", json.loads(row["targets"]))
        self.assertNotIn("instagram", json.loads(row["targets"]))
        self.assertEqual(list(json.loads(row["render_paths"])), [LINKEDIN_PHOTO], "no 4:5 card, no 2:3 card")
        self.assertTrue(self.drawn())
        self.assertTrue(all(name.endswith("-linkedin.jpg") for name in self.drawn()), self.drawn())
        page = self.page(row["id"])
        self.assertIn("LinkedIn:</strong> the photo as shot", page)
        self.assertIn(f"/media/render/{row['id']}/linkedin/1", page)
        self.assertNotIn("Instagram:</strong>", page)
        self.assertNotIn("/4x5/", page)
        self.assertNotIn("/2x3/", page)

    def test_with_no_card_to_judge_the_art_director_spends_no_look(self):
        class NeverAsked:
            def __getattr__(self, name):
                raise AssertionError("a look was spent on a draft with no card")
        paths, verdict = art_director.direct(self.conn, lambda focus: {LINKEDIN_PHOTO: [str(self.root / "hero.jpg")]},
                                             brief=lambda p: "a card", dry_run=False, client=NeverAsked())
        self.assertEqual(list(paths), [LINKEDIN_PHOTO])
        self.assertEqual(verdict["verdict"], "not reviewed")
        self.assertIn("No card to look at", verdict["notes"])

    def test_a_draft_for_instagram_and_linkedin_shows_the_card_and_the_photo_each_labeled(self):
        content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        self.assertEqual(sorted(json.loads(row["render_paths"])), ["4:5", LINKEDIN_PHOTO], "no 2:3: Pinterest is off")
        page = self.page(row["id"])
        self.assertIn("Instagram:</strong> the card", page)
        self.assertIn(f"/media/render/{row['id']}/4x5/1", page)
        self.assertIn("LinkedIn:</strong> the photo as shot", page)
        self.assertIn(f"/media/render/{row['id']}/linkedin/1", page)
        self.assertLess(page.index("Instagram:</strong> the card"), page.index("LinkedIn:</strong> the photo as shot"))
        self.assertNotIn("Pinterest:</strong>", page)
        self.assertNotIn("Facebook:</strong>", page)
        self.assertNotIn("/2x3/", page)

    def test_the_page_shows_each_network_by_the_key_the_publisher_sends(self):
        self.assertIs(publisher.ASPECT_FOR, payloads.ASPECT_FOR)
        for n in NETWORKS:
            self.assertEqual(previews.key_for({}, n), publisher.ASPECT_FOR[n], n)
        self.assertEqual(previews.key_for({"9:16": ["r.mp4"], "cover": ["c.jpg"]}, "instagram"), "cover", "a reel row: the video, by its cover")
        self.assertEqual(previews.key_for({"9:16": ["r.mp4"], "cover": ["c.jpg"]}, "pinterest"), "2:3")

    def test_the_preview_follows_the_ticks_and_a_network_ticked_now_gets_its_file(self):
        content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        qid, caps = row["id"], json.loads(row["caption"])
        form = {f"caption_{n}": caps.get(n, "") for n in NETWORKS}
        page = self.client.post(f"/queue/{qid}/save", data={**form, "target_linkedin": "on", "do": "save"}).text
        self.assertNotIn("Instagram:</strong>", page, "unticked: no image")
        self.assertIn("LinkedIn:</strong> the photo as shot", page)
        os.environ["POST_NETWORKS"] = "instagram,linkedin,pinterest"
        config.reset()
        page = self.client.post(f"/queue/{qid}/save", data={**form, "target_instagram": "on", "target_linkedin": "on",
                                                              "target_pinterest": "on", "do": "save"}).text
        self.assertIn("Instagram:</strong> the card", page)
        self.assertIn("Pinterest:</strong> the pin card", page)
        self.assertIn(f"/media/render/{qid}/2x3/1", page)
        renders = json.loads(self.row()["render_paths"])
        self.assertEqual(sorted(renders), ["2:3", "4:5", LINKEDIN_PHOTO])
        self.assertTrue(Path(renders["2:3"][0]).is_file(), "the pin card was drawn when Pinterest was ticked")
        self.assertEqual(self.client.get(f"/media/render/{qid}/2x3/1").status_code, 200)


class EverySurface(Renders):
    """Chris's phone showed the same branded 4:5 card for post 61 on Today's "To approve" card. Every place that shows a
    draft's image follows the one rule (core/previews): Today, the draft page, All posts, the ping's card and the
    approve-by-token page each show what the first ticked network receives, labeled."""

    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PUBLIC_URL"] = "https://mac-mini.example:8443"
        config.reset()

    def linkedin_only(self):
        """A LinkedIn-only draft (the window holds Instagram), with the art director passing so the ping carries its token."""
        aired(self.conn, self.pid, ["instagram"])
        passed = lambda conn, render, **kw: (render((0.5, 0.42)), {"verdict": "pass", "notes": "Fine.", "rounds": 1})  # noqa: E731
        with mock.patch.object(content.notify, "push") as push, mock.patch.object(content.art_director, "direct", passed):
            content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        self.assertEqual(list(json.loads(row["render_paths"])), [LINKEDIN_PHOTO])
        return row, push.call_args[1]

    def test_today_shows_the_photo_as_shot_labeled_linkedin_never_a_card(self):
        row, _ = self.linkedin_only()
        page = self.client.get("/").text
        self.assertIn(f"/media/render/{row['id']}/linkedin/1", page)
        self.assertIn("LinkedIn: the photo as shot", page)
        self.assertNotIn("/4x5/", page)
        self.assertNotIn("/2x3/", page)

    def test_all_posts_shows_the_photo_as_shot_labeled_linkedin(self):
        row, _ = self.linkedin_only()
        page = self.client.get("/history").text
        self.assertIn(f"/media/render/{row['id']}/linkedin/1", page)
        self.assertIn("LinkedIn: the photo as shot", page)
        self.assertNotIn("/4x5/", page)

    def test_the_pings_card_is_the_photo_as_shot(self):
        row, kw = self.linkedin_only()
        attach = kw["attach"]
        self.assertTrue(attach.startswith(f"https://mac-mini.example:8443/media/card/{row['id']}/"), attach)
        served = TestClient(create_app()).get(attach.split("mac-mini.example:8443", 1)[1])
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.content, Path(json.loads(row["render_paths"])[LINKEDIN_PHOTO][0]).read_bytes(), "the LinkedIn file itself")

    def test_the_token_page_shows_the_photo_as_shot_labeled_linkedin(self):
        row, kw = self.linkedin_only()
        token = kw["actions"].split("body='token=", 1)[1].split("'", 1)[0]
        page = TestClient(create_app()).get(f"/queue/{row['id']}/approve-by-token?token={token}").text
        self.assertIn("LinkedIn: the photo as shot", page)
        self.assertIn(f"/media/card/{row['id']}/", page)
        self.assertNotIn("/4x5/", page)

    def test_a_draft_for_instagram_and_linkedin_leads_with_the_instagram_card_everywhere(self):
        passed = lambda conn, render, **kw: (render((0.5, 0.42)), {"verdict": "pass", "notes": "Fine.", "rounds": 1})  # noqa: E731
        with mock.patch.object(content.notify, "push") as push, mock.patch.object(content.art_director, "direct", passed):
            content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        for path in ("/", "/history"):
            page = self.client.get(path).text
            self.assertIn(f"/media/render/{row['id']}/4x5/1", page, path)
            self.assertIn("Instagram: the card", page, path)
        served = TestClient(create_app()).get(push.call_args[1]["attach"].split("mac-mini.example:8443", 1)[1])
        self.assertEqual(served.content, Path(json.loads(row["render_paths"])["4:5"][0]).read_bytes(), "the ping shows the card Instagram gets")

    def test_one_rule_for_every_surface(self):
        """The helper every surface reads is keyed off the publisher's own map."""
        for n in NETWORKS:
            self.assertEqual(previews.key_for({}, n), publisher.ASPECT_FOR[n], n)
        self.assertEqual(previews.key_for({"9:16": ["r.mp4"], "cover": ["c.jpg"]}, "facebook"), "cover")
        self.assertEqual(previews.key_for({"story": ["s.jpg"], "4:5": ["c.jpg"]}, "instagram", {"instant": True, "format": "story"}), "story")
        self.assertEqual(previews.key_for({"story": ["s.jpg"], "4:5": ["c.jpg"]}, "instagram", {}), "4:5")
