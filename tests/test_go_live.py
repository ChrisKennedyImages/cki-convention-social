"""Going live: the site builds before any photo is cleared, `ccs site check` says LIVE only when every
page and the booking API pass, the dashboard password can be saved straight to .env, and the go-live
script keeps its promises (never as root, never a secret on screen, the pinned wrangler)."""
from __future__ import annotations

import io
import os
import re
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from convention_social import cli
from convention_social.core import auth, config, secrets
from convention_social.drive import oauth
from convention_social.seo import site_check
from convention_social.site import build
from tests._base import IsolatedCase

REPO = Path(__file__).resolve().parents[1]


def run(argv) -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(argv)
    return code, out.getvalue()


def page(ok=True, path="/"):
    return {"path": path, "url": "https://eventcaliber.com" + path, "status": 200 if ok else 0, "ok": ok,
            "problems": [] if ok else ["could not be reached (ConnectionError)"]}


class FakeAPI:
    def __init__(self, fail=False):
        self.fail = fail

    def pull(self):
        if self.fail:
            raise RuntimeError("401 Unauthorized")
        return [{"id": "r1"}]


class SiteCheck(IsolatedCase):
    def check(self, pages, api, wait=0, sleeps=None):
        with mock.patch.object(site_check, "check_all", side_effect=pages), \
             mock.patch("convention_social.booking.remote.SiteAPI.from_config", return_value=api), \
             mock.patch("time.sleep", side_effect=lambda s: (sleeps if sleeps is not None else []).append(s)):
            return run(["site", "check", "--wait", str(wait)])

    def test_live_only_when_everything_passes(self):
        code, out = self.check([[page(), page(path="/book/")]], FakeAPI())
        self.assertEqual(code, 0)
        self.assertIn("PASS  https://eventcaliber.com/book/", out)
        self.assertIn("token is accepted (1 quote request(s) waiting)", out)
        self.assertIn("LIVE: every check passed", out)

    def test_a_failing_page_is_not_live(self):
        code, out = self.check([[page(), page(ok=False, path="/book/")]], FakeAPI())
        self.assertEqual(code, 1)
        self.assertIn("FAIL  https://eventcaliber.com/book/  (could not be reached (ConnectionError))", out)
        self.assertIn("NOT LIVE YET", out)
        self.assertNotIn("LIVE: every", out)

    def test_a_refused_token_or_no_token_is_not_live(self):
        code, out = self.check([[page()]], FakeAPI(fail=True))
        self.assertEqual(code, 1)
        self.assertIn("FAIL  booking API: the Mini could not read quote requests (RuntimeError: 401 Unauthorized)", out)
        code, out = self.check([[page()]], None)
        self.assertEqual(code, 1)
        self.assertIn("FAIL  booking API: no MEDIA_UPLOAD_TOKEN on this machine", out)

    def test_wait_retries_until_the_new_domain_answers(self):
        sleeps = []
        code, out = self.check([[page(ok=False)], [page(ok=False)], [page()]], FakeAPI(), wait=600, sleeps=sleeps)
        self.assertEqual(code, 0)
        self.assertEqual(sleeps, [20, 20])
        self.assertEqual(out.count("trying again"), 2)

    def test_check_all_writes_nothing(self):
        from convention_social.core import db
        conn = db.connect()
        before = db.one(conn, "SELECT (SELECT COUNT(*) FROM site_checks) + (SELECT COUNT(*) FROM errors) n")["n"]
        results = site_check.check_all(transport=lambda url: (0, ""))
        self.assertEqual(len(results), len(site_check.PATHS))
        self.assertTrue(all(not r["ok"] for r in results))
        after = db.one(conn, "SELECT (SELECT COUNT(*) FROM site_checks) + (SELECT COUNT(*) FROM errors) n")["n"]
        self.assertEqual(before, after)
        conn.close()


class BuildWithoutPhotos(IsolatedCase):
    def test_no_drive_sign_in_still_builds_the_site(self):
        made = {}

        def fake_build(conn, photos, *, preview=False, **kw):
            made["photos"], made["preview"] = photos, preview
            return Path("site/dist")

        with mock.patch.object(oauth, "access_token", side_effect=oauth.DriveAuthError("Google Drive is not signed in yet.")), \
             mock.patch.object(build, "build", side_effect=fake_build), \
             mock.patch.object(build, "pick_photos", side_effect=AssertionError("no Drive, so no photo pick")):
            code, out = run(["site", "build"])
        self.assertEqual(code, 0)
        self.assertTrue(made)
        self.assertFalse(made["preview"])
        self.assertEqual((made["photos"].hero, made["photos"].coverage, made["photos"].venues), ([], [], []))
        self.assertIn("Building without photos", out)
        self.assertIn("built without photos", out)

    def test_the_menu_links_only_to_sections_that_exist(self):
        out = build.build(None, build.SitePhotos(), out=self.root / "dist")
        for rel in ("index.html", "book/index.html"):
            nav = re.search(r'<nav class="mono">(.*?)</nav>', (out / rel).read_text()).group(1)
            self.assertIn('href="/#coverage"', nav)
            self.assertIn('href="/availability/"', nav)
            self.assertNotIn("#work", nav)
            self.assertNotIn("#venues", nav)
        from PIL import Image
        im = Image.new("RGB", (2400, 1600), (90, 90, 90))
        out = build.build(None, build.SitePhotos(hero=[(im, "a")], coverage=[(im, "c")], venues=[(im, "v")]),
                          out=self.root / "dist2")
        nav = re.search(r'<nav class="mono">(.*?)</nav>', (out / "index.html").read_text()).group(1)
        self.assertIn('href="/#work"', nav)
        self.assertIn('href="/#venues"', nav)


class SavePassword(IsolatedCase):
    def test_save_writes_only_a_hash_that_verifies(self):
        env = self.root / "save.env"
        os.environ["CCS_ENV_FILE"] = str(env)
        config.reset()
        with mock.patch("getpass.getpass", side_effect=["correct horse", "correct horse"]):
            code, out = run(["hash-password", "--save"])
        self.assertEqual(code, 0)
        text = env.read_text()
        self.assertNotIn("correct horse", text + out)
        stored = secrets.get_secret("DASHBOARD_PASSWORD_HASH")
        self.assertTrue(stored)
        self.assertTrue(auth.verify_password("correct horse", stored))
        self.assertEqual(oct(env.stat().st_mode & 0o777), "0o600")

    def test_mismatch_saves_nothing(self):
        env = self.root / "save.env"
        os.environ["CCS_ENV_FILE"] = str(env)
        config.reset()
        with mock.patch("getpass.getpass", side_effect=["correct horse", "correct horsf"]):
            code, out = run(["hash-password", "--save"])
        self.assertEqual(code, 2)
        self.assertFalse(env.exists())
        self.assertIn("did not match", out)


class GoLiveScript(IsolatedCase):
    """Static promises of scripts/go-live.sh; its full run was proven against stand-ins for
    Cloudflare, sudo and the installers (first run, re-run, R2 off, failed deploy, failed check,
    two accounts)."""

    def setUp(self):
        super().setUp()
        self.text = (REPO / "scripts/go-live.sh").read_text()

    def test_refuses_root_and_pins_wrangler(self):
        self.assertTrue(os.access(REPO / "scripts/go-live.sh", os.X_OK))
        self.assertIn('[[ $EUID -ne 0 ]] || stop', self.text)
        self.assertIn("WR=(npx --yes wrangler@4.149.0)", self.text)
        self.assertEqual(re.findall(r"\bnpx\b(?! --yes wrangler@4\.149\.0)", self.text), ["npx"])  # only `command -v npx`

    def test_secrets_only_travel_through_pipes(self):
        self.assertIn('value MEDIA_UPLOAD_TOKEN | "${WR[@]}" secret put UPLOAD_TOKEN', self.text)
        for line in self.text.splitlines():
            if re.search(r"\b(print|echo|say|warn)\b.*\$\(value ", line):
                self.fail(f"a secret could reach the screen: {line}")

    def test_deploys_the_untracked_live_config_and_ends_on_the_live_check(self):
        self.assertIn('LIVE=(-c wrangler.live.jsonc)', self.text)
        self.assertIn('"${WR[@]}" deploy "${LIVE[@]}"', self.text)
        self.assertIn("wrangler.live.jsonc", (REPO / ".gitignore").read_text())
        self.assertIn("bin/ccs site check --wait 600", self.text)
        self.assertIn("SET_AFTER_d1_create", (REPO / "wrangler.jsonc").read_text())
