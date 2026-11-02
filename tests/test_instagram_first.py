"""2026-11-02, 14:26 UTC: the designed agent drafted post #62 as a reel "held off Instagram and Facebook and Pinterest":
photos already on Instagram but free on LinkedIn sat in one pool with fresh ones (content.candidates dropped a photo only
when it was held on every network that is on) and the rotation picked them, with about 1,800 photos free on Instagram
ready. Now the candidates free on every network that is on come first, a photo free only on some comes after them, and
no automatic post is held off Instagram (the first network in the posting order) while any candidate free on Instagram
remains; the fallback is said in the run line. A LinkedIn-only post happens when Chris chooses it (#61) or when
Instagram truly has nothing left."""
from __future__ import annotations

import json
import os

from convention_social.agents import content, designed
from convention_social.core import config, db
from tests.test_linkedin_logo import DraftCase
from tests.test_repeat_per_network import MONDAY_6AM, aired


class Case(DraftCase):
    def setUp(self):
        super().setUp()
        os.environ["POST_NETWORKS"] = "instagram,linkedin"
        config.reset()

    def fresh_photo(self, quality: int = 3) -> int:
        """Another approved event photo, weaker than DraftCase's, so only its freedom can put it first."""
        now = db.utcnow()
        n = db.one(self.conn, "SELECT COUNT(*) AS n FROM photos")["n"] + 1
        pid = db.insert(self.conn, "photos", drive_id=f"d{n}", name=f"d{n}.jpg", folder_id="fe", width=3000, height=2000,
                        taken_at=f"2025:02:14 1{n}:00:00", first_seen_at=now, last_seen_at=now)
        db.insert(self.conn, "classifications", photo_id=pid, method="ollama", subject="event", convention_name="Katsucon", is_convention=1,
                  quality=quality, possible_minor=0, personal_details="[]", space="exterior", residential=0, empty_room=0, sharp=1,
                  light=4, moment=4, classified_at=now)
        return pid

    def ids(self, rows) -> list[int]:
        return [r["id"] for r in rows]


class TheDailyDraft(Case):
    def test_a_fresh_photo_leads_an_instagram_used_one_and_the_draft_targets_instagram(self):
        fresh = self.fresh_photo()
        aired(self.conn, self.pid, ["instagram"])                 # free on LinkedIn only
        pool = content.candidates(self.conn, "event")
        self.assertEqual(self.ids(pool), [fresh, self.pid], "the fresh photo first, however strong the used one")
        self.assertEqual([r["held_on"] for r in pool], [[], ["instagram"]])
        line = content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        self.assertEqual(json.loads(row["photo_ids"]), [fresh])
        self.assertIn("instagram", json.loads(row["targets"]))
        self.assertNotIn("held off", line)
        self.assertNotIn("no photo free on", line)

    def test_only_when_instagram_has_nothing_left_does_a_post_go_without_it_and_the_line_says_so(self):
        aired(self.conn, self.pid, ["instagram"])
        line = content.draft_one(self.ctx(dry=True), self.fetch, now=MONDAY_6AM)
        row = self.row()
        self.assertEqual(json.loads(row["photo_ids"]), [self.pid])
        self.assertNotIn("instagram", json.loads(row["targets"]))
        self.assertIn("linkedin", json.loads(row["targets"]))
        self.assertIn("no photo free on Instagram is left, so this post is held off it", line)
        self.assertIn("held off Instagram", line)

    def test_a_photo_held_only_on_linkedin_comes_after_the_free_and_before_one_held_on_instagram(self):
        on_linkedin = self.fresh_photo(quality=5)
        on_instagram = self.fresh_photo(quality=5)
        aired(self.conn, on_linkedin, ["linkedin"])
        aired(self.conn, on_instagram, ["instagram"])
        pool = content.candidates(self.conn, "event")
        self.assertEqual(self.ids(pool), [self.pid, on_linkedin, on_instagram])
        free, fell_back = content.free_on_first(pool, ("instagram", "linkedin"))
        self.assertEqual((self.ids(free), fell_back), ([self.pid, on_linkedin], False), "a post may take both of these and still go to Instagram")

    def test_a_credited_person_on_instagram_lately_holds_the_photo_there_only(self):
        fresh = self.fresh_photo()
        self.conn.execute("UPDATE photos SET credit='@ally' WHERE id=?", (self.pid,)) if "credit" in [c[1] for c in self.conn.execute("PRAGMA table_info(photos)")] else None
        when = db.utcnow()
        db.insert(self.conn, "content_queue", kind="photo", photo_ids="[999]", targets='["instagram"]', caption="{}", status="published",
                  published_at=when, created_at=when, updated_at=when, rule_report=json.dumps({"event": "Other", "people": ["@ally"]}))
        held = content.held_on_networks(self.conn, ("instagram", "linkedin"))
        self.assertEqual(held(self.pid, "@ally"), ["instagram"])
        self.assertEqual(held(fresh, ""), [])


class TheDesignedDraft(Case):
    def test_the_pool_leads_with_photos_free_on_instagram(self):
        fresh = self.fresh_photo()
        aired(self.conn, self.pid, ["instagram"])
        pool = designed.pool(self.conn)
        self.assertEqual(self.ids(pool), [fresh, self.pid])
        self.assertEqual([r["held_on"] for r in pool], [[], ["instagram"]])
        rows, fell_back = content.free_on_first(pool, ("instagram", "linkedin"))
        self.assertEqual((self.ids(rows), fell_back), ([fresh], False), "the designed draft takes only what Instagram can have")

    def test_with_nothing_free_on_instagram_the_pool_still_offers_the_rest(self):
        aired(self.conn, self.pid, ["instagram"])
        rows, fell_back = content.free_on_first(designed.pool(self.conn), ("instagram", "linkedin"))
        self.assertEqual((self.ids(rows), fell_back), ([self.pid], True))
