"""Chris, 2026-11-02: "LinkedIn and insta are two totally different platforms. That rule only applies to each platform
Individually not all together". The repeat window (PHOTO_REPEAT_DAYS) and the variety rule (VARIETY_DAYS) count per network:
a photo that aired on Instagram stays off Instagram for the window and may go to LinkedIn; a draft drops only the networks
where its photo is inside that network's window, with the reason on the draft page; a photo inside the window everywhere
that is on is refused, as before. The publisher's door holds the same way."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest import mock

from convention_social.agents import content, publisher
from convention_social.core import config, db
from convention_social.render.photo import LINKEDIN_PHOTO
from tests._fakes import add_channels, add_photo, add_post, all_eligible, make_ctx, write_render
from tests.test_linkedin_logo import DraftCase

MONDAY_6AM = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
FRIDAY_8AM = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


def aired(conn, photo_id, targets, days_ago=4, status="published"):
    """A post of this photo that went to `targets` `days_ago` days ago."""
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(microsecond=0).isoformat()
    return db.insert(conn, "content_queue", kind="photo", photo_ids=json.dumps([photo_id]), targets=json.dumps(list(targets)),
                     caption=json.dumps({t: "x" for t in targets}), status=status, published_at=when, created_at=when, updated_at=when,
                     rule_report=json.dumps({"event": "Katsucon", "people": []}))


class AtTheDraft(DraftCase):
    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()

    def test_a_photo_on_instagram_four_days_ago_goes_to_linkedin_and_not_instagram(self):
        old = aired(self.conn, self.pid, ["instagram"])
        self.assertEqual([r["id"] for r in content.candidates(self.conn, "event")], [self.pid], "a candidate: free on LinkedIn")
        line = content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        self.assertIn("drafted post", line)
        self.assertIn("held off Instagram", line)
        row = self.row()
        targets = json.loads(row["targets"])
        self.assertNotIn("instagram", targets)
        self.assertIn("linkedin", targets)
        meta = json.loads(row["rule_report"])
        self.assertIn(f"photo {self.pid} was on post #{old} inside the last", meta["skipped"]["instagram"])
        self.assertNotIn("instagram", json.loads(row["caption"]))
        self.assertNotIn("instagram", meta["rules"])
        self.assertIn(LINKEDIN_PHOTO, json.loads(row["render_paths"]))

    def test_a_photo_on_linkedin_four_days_ago_stays_off_linkedin(self):
        aired(self.conn, self.pid, ["linkedin"])
        self.assertEqual([r["id"] for r in content.candidates(self.conn, "event")], [self.pid])
        content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        targets = json.loads(row["targets"])
        self.assertNotIn("linkedin", targets)
        self.assertIn("instagram", targets)
        self.assertIn("linkedin", json.loads(row["rule_report"])["skipped"])

    def test_a_photo_inside_the_window_everywhere_is_refused_as_before(self):
        aired(self.conn, self.pid, list(content.TARGETS))
        self.assertEqual(content.candidates(self.conn, "event"), [])
        self.assertIn("no photo ready", content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM))
        held = content.held_on(self.conn, [self.pid], 30, [], 14)
        self.assertEqual(set(held), set(content.TARGETS))

    def test_a_credited_person_counts_per_network_too(self):
        when = (datetime.now(timezone.utc) - timedelta(days=4)).replace(microsecond=0).isoformat()
        db.insert(self.conn, "content_queue", kind="photo", photo_ids=json.dumps([999]), targets=json.dumps(["instagram"]),
                  caption="{}", status="published", published_at=when, created_at=when, updated_at=when,
                  rule_report=json.dumps({"event": "Other Con", "people": ["@ally"]}))
        held = content.held_on(self.conn, [self.pid], 30, ["@ally"], 14)
        self.assertEqual(list(held), ["instagram"])
        self.assertIn("@ally was on a post here inside the last 14 days", held["instagram"]["why"])


class AtTheDoor(DraftCase):
    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()
        p = mock.patch.object(publisher, "_eligibility_module", return_value=all_eligible())
        p.start()
        self.addCleanup(p.stop)
        add_channels(self.conn, "instagram", "linkedin")
        self.conn.execute("UPDATE photos SET prominent_logo=0, local_path=? WHERE id=?",
                          (write_render(self.root / "photos", "e1.jpg"), self.pid))
        self.renders = {"4:5": [write_render(self.root / "renders", "r-45.jpg")], "2:3": [write_render(self.root / "renders", "r-23.jpg")],
                        LINKEDIN_PHOTO: [write_render(self.root / "renders", "r-li.jpg")]}

    def test_a_photo_that_went_out_on_instagram_still_goes_to_linkedin(self):
        aired(self.conn, self.pid, ["instagram"])
        qid = add_post(self.conn, [self.pid], ("linkedin",), render_paths=self.renders)
        publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "would_publish")
        self.assertEqual(set(json.loads(row["payload"])), {"linkedin"})

    def test_the_same_photo_for_instagram_again_goes_back(self):
        old = aired(self.conn, self.pid, ["instagram"])
        qid = add_post(self.conn, [self.pid], ("instagram",), render_paths=self.renders)
        publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "draft")
        self.assertIn(f"already went out as post #{old}", row["last_error"])

    def test_a_post_for_both_keeps_linkedin_and_drops_instagram(self):
        old = aired(self.conn, self.pid, ["instagram"])
        qid = add_post(self.conn, [self.pid], ("instagram", "linkedin"), render_paths=self.renders)
        publisher.publish_ready(make_ctx(self.conn), now=FRIDAY_8AM)
        row = db.one(self.conn, "SELECT * FROM content_queue WHERE id=?", (qid,))
        self.assertEqual(row["status"], "would_publish")
        self.assertEqual(set(json.loads(row["payload"])), {"linkedin"})
        self.assertIn(f"already went out as post #{old}", json.loads(row["rule_report"])["skipped"]["instagram"])
        self.assertIn("once a network", json.loads(row["rule_report"])["skipped"]["instagram"])
