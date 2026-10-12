"""The website's main photo from Chris's phone (2026-10-12: "That photo is just on my phone I think")."""
from __future__ import annotations

import io
import json
import os
import types

from fastapi.testclient import TestClient
from PIL import Image

from convention_social.core import auth, config, db, settings
from convention_social.dashboard.app import COOKIE, create_app, make_token
from convention_social.library import classify
from convention_social.render import meta
from convention_social.site import build, hero
from tests._base import IsolatedCase
from tests._photos import jpeg_bytes
from tests.test_wedding import event_photo


class LookClient:
    def __init__(self, **answer):
        self.answer = {"possible_minor": False, "personal_details": [], "shot_type": "stage_panel", "event_kind": "business",
                       "summary": "A full room.", **answer}
        self.calls = 0
        self.beta = self.messages = self

    def create(self, **kw):
        self.calls += 1
        assert kw["output_config"]["format"]["schema"] is classify.FINAL_SCHEMA
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=json.dumps(self.answer))], stop_reason="end_turn",
                                     model=kw["model"], usage=types.SimpleNamespace(input_tokens=1500, output_tokens=100))


def looker(conn, client):
    return lambda data: classify.look(conn, data, client=client, agent="site")


class Keep(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()

    def test_only_a_real_full_size_photo_is_kept_and_it_keeps_no_camera_data(self):
        for data, why in ((b"", "empty"), (b"not a jpeg", "not a photo"), (jpeg_bytes(size=(800, 500)), "too small")):
            with self.assertRaises(hero.Refused) as cm:
                hero.save(data)
            self.assertIn(why, str(cm.exception))
        self.assertFalse(hero.present())
        out = hero.save(jpeg_bytes(size=(1600, 1000)))
        self.assertTrue(hero.present())
        self.assertEqual(meta.is_clean(out), [])
        self.assertEqual(hero.status(self.conn)["width"], 1600)
        self.assertTrue(hero.remove(self.conn))
        self.assertFalse(hero.present())
        self.assertFalse(hero.remove(self.conn))

    def test_claude_looks_once_per_upload_and_the_verdict_decides(self):
        self.assertEqual(hero.checked(self.conn), (False, "no upload"))
        hero.save(jpeg_bytes(size=(1600, 1000)))
        self.assertEqual(hero.checked(self.conn)[0], False)
        self.assertIn("not checked yet", hero.checked(self.conn)[1])
        client = LookClient()
        self.assertEqual(hero.checked(self.conn, looker(self.conn, client)), (True, "checked by Claude"))
        self.assertEqual(hero.checked(self.conn, looker(self.conn, LookClient(possible_minor=True))), (True, "checked by Claude"), "kept with the file")
        self.assertEqual(client.calls, 1)
        self.assertEqual(db.one(self.conn, "SELECT COUNT(*) n FROM api_usage WHERE agent='site'")["n"], 1)
        hero.save(jpeg_bytes(seed=2, size=(1600, 1000)))                   # a new file: Claude looks again
        self.assertEqual(hero.checked(self.conn, looker(self.conn, LookClient(possible_minor=True))), (False, "someone in it may be under 18"))
        hero.save(jpeg_bytes(seed=3, size=(1600, 1000)))
        self.assertEqual(hero.checked(self.conn, looker(self.conn, LookClient(event_kind="wedding")))[0], False)
        hero.save(jpeg_bytes(seed=4, size=(1600, 1000)))
        self.assertEqual(hero.checked(self.conn, looker(self.conn, LookClient(personal_details=["badge_name"])))[1], "it shows badge_name")
        hero.save(jpeg_bytes(seed=5, size=(1600, 1000)))
        self.assertIn("could not look", hero.checked(self.conn, lambda data: None)[1])


class OnTheSite(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        os.environ["AI_MONTHLY_CAP_USD"] = "5"
        config.reset()
        for i in range(3):
            event_photo(self.conn, f"lib{i}", kind="business", final="business", quality=5 - i, light=5, moment=5)

    def fetch(self, row):
        return Image.new("RGB", (int(row["width"]), int(row["height"])), (90, 90, 90))

    def test_the_upload_is_the_hero_once_claude_has_looked(self):
        hero.save(jpeg_bytes(size=(1600, 1000)))
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertEqual(photos.hero[0][0].size, (3000, 2000), "unchecked: the build chooses from the library")
        self.assertTrue(photos.hero_note.startswith("your uploaded photo could not be used: not checked yet"), photos.hero_note)
        photos = build.pick_photos(self.conn, self.fetch, look=looker(self.conn, LookClient()))
        self.assertEqual(photos.hero[0][0].size, (1600, 1000))
        self.assertEqual(photos.hero[0][1], "Stage and panel")
        self.assertEqual(photos.hero_note, "your uploaded photo (checked by Claude)")
        self.assertEqual(len(photos.coverage), 3, "the library frames fill the grid")
        settings.set(self.conn, build.HERO_KEY, str(db.one(self.conn, "SELECT id FROM photos WHERE drive_id='lib2'")["id"]))
        self.assertEqual(build.pick_photos(self.conn, self.fetch).hero[0][0].size, (1600, 1000), "the upload wins over a pick")
        hero.remove(self.conn)
        photos = build.pick_photos(self.conn, self.fetch)
        self.assertTrue(photos.hero_note.startswith("your Site hero pick"), photos.hero_note)

    def test_a_refused_upload_is_never_the_hero(self):
        hero.save(jpeg_bytes(size=(1600, 1000)))
        photos = build.pick_photos(self.conn, self.fetch, look=looker(self.conn, LookClient(possible_minor=True)))
        self.assertEqual(photos.hero[0][0].size, (3000, 2000))
        self.assertIn("your uploaded photo could not be used: someone in it may be under 18; the build's choice", photos.hero_note)


class TheCard(IsolatedCase):
    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        config.reset()
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.client = TestClient(create_app())
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_send_replace_and_remove_from_the_approved_page(self):
        page = self.client.get("/library?view=approved").text
        self.assertIn("Site hero from your phone", page)
        self.assertIn(">Send</button>", page)
        r = self.client.post("/library/hero/upload", files={"file": ("tiny.jpg", jpeg_bytes(size=(600, 400)), "image/jpeg")}, follow_redirects=False)
        self.assertIn("Not+kept:+too+small", r.headers["location"])
        r = self.client.post("/library/hero/upload", files={"file": ("pano.jpg", jpeg_bytes(size=(2000, 900)), "image/jpeg")}, follow_redirects=False)
        self.assertIn("msg=Kept.", r.headers["location"])
        page = self.client.get("/library?view=approved").text
        self.assertIn("Uploaded: 2000 × 900", page)
        self.assertIn("not checked yet", page)
        self.assertIn(">Replace</button>", page)
        self.assertTrue(hero.present())
        r = self.client.post("/library/hero/remove", follow_redirects=False)
        self.assertIn("Removed", r.headers["location"])
        self.assertFalse(hero.present())
        anon = TestClient(create_app())
        self.assertNotEqual(anon.post("/library/hero/remove", follow_redirects=False).status_code, 303)
