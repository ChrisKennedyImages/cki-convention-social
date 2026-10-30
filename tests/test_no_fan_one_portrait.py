"""Chris, 2026-10-12, late: "We are going to get rid of 'fan conventions'" and "Portraits and headshots
are the same". Off every public surface and out of the scout's search; one shot type."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from convention_social import offer
from convention_social.agents import learner
from convention_social.ai import claude, seo_plan
from convention_social.core import auth, config, db
from convention_social.dashboard import app as dashboard
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import classify
from convention_social.outreach import draft, research
from convention_social.render import meta
from convention_social.seo import photo_text
from tests._base import IsolatedCase

REPO = Path(__file__).resolve().parents[1]


class NoFanConventions(IsolatedCase):
    def test_the_offer_file_and_the_quote_form_never_say_it(self):
        text = (REPO / "offer.json").read_text().lower()
        self.assertNotIn("fan", text.split('"coverage"')[0].replace("fantastic", ""))
        kinds = offer.load()["event_kinds"]
        self.assertEqual(kinds[0], "Business, corporate and association conferences")
        self.assertFalse(any("fan" in k.lower() for k in kinds), kinds)

    def test_every_public_wording_for_the_sorters_fan_tag_says_convention(self):
        self.assertEqual(claude.KIND_WORDS["fan"], "a convention")
        self.assertEqual(seo_plan.KIND_WORDS["fan"], "convention")
        self.assertEqual(photo_text.KIND_WORDS["fan"], "convention")
        self.assertEqual(photo_text.KIND_KEYWORDS["fan"], "convention photography")
        self.assertEqual(learner.kind_words("event_kind", "fan"), "convention photos")
        for table in (seo_plan.PRIMARY["fan"], seo_plan.RELATED["fan"], seo_plan.HASHTAGS["fan"]):
            for phrase in table.values() if isinstance(table, dict) else table:
                self.assertNotIn("fan", phrase.lower(), phrase)
        conn = db.connect()
        self.addCleanup(conn.close)
        row = {"id": 1, "shot_type": "portrait", "event_kind": "fan", "subject": "event"}
        m = meta.for_photo(conn, row)
        self.assertEqual(m.title, "Portrait at a convention")
        self.assertNotIn("fan convention photography", m.keywords)
        self.assertIn("convention photography", m.keywords)

    def test_the_scout_is_told_to_leave_fan_conventions_out(self):
        self.assertIn("Fan conventions (comic, anime, gaming, pop culture) do not: leave them out.", research.SYSTEM)
        self.assertIn("kind is business or other.", research.SYSTEM)
        self.assertIn("fan", research.KINDS, "rows found before 2026-10-12 still validate")

    def test_the_dashboard_menus_do_not_offer_it(self):
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        client = TestClient(create_app())
        client.cookies.set(COOKIE, make_token("chris"))
        for path in ("/calendar", "/outreach"):
            page = client.get(path).text
            self.assertNotIn('value="fan"', page, path)
            self.assertNotIn("Fan convention", page, path)
            self.assertIn("Conference or convention", page, path)

    def test_the_sorter_still_tells_a_fan_convention_apart_and_the_photos_are_plain_conventions(self):
        # Chris, 2026-10-12: "The fan photos go to plain conventions": used like any convention photo, never set aside
        self.assertIn("fan", classify.KINDS)
        self.assertNotIn("fan", classify.NOT_OFFERED_KINDS)
        from convention_social.library import eligibility
        self.assertNotIn("fan", eligibility.NOT_OFFERED_KINDS)
        from tests.test_wedding import event_photo
        conn = db.connect()
        self.addCleanup(conn.close)
        pid = event_photo(conn, "fan1", kind="fan", final="fan")
        self.assertTrue(eligibility.is_eligible(conn, pid)[0], eligibility.is_eligible(conn, pid))

    def test_no_public_python_wording_says_fan_convention(self):
        allowed = {"convention_social/library/classify.py", "convention_social/library/heuristics.py",
                   "convention_social/outreach/research.py"}          # the sorter's tag and the scout's exclusion
        hits = []
        for path in sorted((REPO / "convention_social").rglob("*.py")):
            rel = str(path.relative_to(REPO))
            if rel in allowed:
                continue
            for n, line in enumerate(path.read_text().splitlines(), start=1):
                code = line.split("#")[0]                       # comments may name the rule; code and strings may not
                if re.search(r"fan conventions?", code, re.IGNORECASE):
                    hits.append(f"{rel}:{n}: {line.strip()}")
        self.assertEqual(hits, [])


class OnePortrait(IsolatedCase):
    def test_one_coverage_row_and_one_shot_type(self):
        keys = offer.coverage_keys()
        self.assertIn("portraits", keys)
        self.assertNotIn("headshots", keys)
        self.assertNotIn("headshots", (REPO / "worker" / "index.js").read_text().split("const COVERAGE")[1].split("]")[0])
        self.assertNotIn("headshot", classify.SHOT_TYPES)
        self.assertIn("a headshot or a posed group", classify.FINAL_SYSTEM)
        self.assertNotIn("headshot", json.dumps(classify.FINAL_SCHEMA))
        self.assertNotIn("headshots", draft.COVERAGE_BY_KIND["business"])
        self.assertIn("portraits", draft.COVERAGE_BY_KIND["business"])
        self.assertEqual(dict(dashboard.SHOT_CHOICES).get("headshot"), None)
        self.assertEqual(dict(dashboard.SHOT_CHOICES)["portrait"], "Portrait")

    def test_the_migration_turns_stored_headshots_into_portraits(self):
        from tests.test_wedding import event_photo
        conn = db.connect()
        self.addCleanup(conn.close)
        versions = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        mine = [v for v in versions if "0063" in v]
        self.assertEqual(len(mine), 1, versions)
        conn.execute("DELETE FROM schema_migrations WHERE version=?", (mine[0],))
        pid = event_photo(conn, "h1", kind="business", final="business")
        conn.execute("UPDATE classifications SET shot_type='headshot' WHERE photo_id=?", (pid,))
        conn.execute("UPDATE final_checks SET shot_type='headshot' WHERE photo_id=?", (pid,))
        conn.commit()
        db.migrate(conn)
        self.assertEqual(db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (pid,))["shot_type"], "portrait")
        self.assertEqual(db.one(conn, "SELECT shot_type FROM final_checks WHERE photo_id=?", (pid,))["shot_type"], "portrait")


class OneHall(IsolatedCase):
    """Chris, 2026-10-12: "Exhibition Halls, vendors and booths are all the same thing"."""

    def test_one_coverage_row_and_one_shot_type(self):
        keys = offer.coverage_keys()
        self.assertIn("exhibition_hall", keys)
        self.assertNotIn("vendors", keys)
        worker = (REPO / "worker" / "index.js").read_text().split("const COVERAGE")[1].split("]")[0]
        self.assertNotIn("vendors", worker)
        self.assertIn("exhibition_hall", worker)
        # 2026-10-29: the hall is a coverage row of the site, not a shot type: the eight titles have no expo word
        for word in ("booth", "vendor_hall"):
            self.assertNotIn(word, classify.SHOT_TYPES)
            self.assertNotIn(word, dict(dashboard.SHOT_CHOICES))
            self.assertNotIn(word, photo_text.SHOT_WORDS)
            self.assertNotIn(word, meta.SHOT_WORDS)
            self.assertNotIn(word, seo_plan.ROOM)
        self.assertNotIn("vendors", draft.COVERAGE_BY_KIND["fan"])

    def test_the_migration_turns_stored_booths_into_the_hall(self):
        from tests.test_wedding import event_photo
        conn = db.connect()
        self.addCleanup(conn.close)
        mine = [v for v in {r[0] for r in conn.execute("SELECT version FROM schema_migrations")} if "0064" in v]
        self.assertEqual(len(mine), 1)
        conn.execute("DELETE FROM schema_migrations WHERE version=?", (mine[0],))
        pid = event_photo(conn, "b1", kind="business", final="business")
        conn.execute("UPDATE classifications SET shot_type='booth' WHERE photo_id=?", (pid,))
        conn.execute("UPDATE final_checks SET shot_type='booth' WHERE photo_id=?", (pid,))
        conn.commit()
        db.migrate(conn)
        self.assertEqual(db.one(conn, "SELECT shot_type FROM classifications WHERE photo_id=?", (pid,))["shot_type"], "vendor_hall")
        self.assertEqual(db.one(conn, "SELECT shot_type FROM final_checks WHERE photo_id=?", (pid,))["shot_type"], "vendor_hall")
