"""The dashboard away from home (Chris, 2026-10-15: "can i reach this dashboard without running tailscale when
im out of town?"): a Cloudflare Tunnel from the Mini to a private address, Cloudflare Access in front (a code
sent to his email, only his email), the dashboard password behind it. Never public without Access: the tunnel
starts only when Access answers for the address from outside and stops when Cloudflare routes it anywhere but
127.0.0.1:4610, and the dashboard refuses every request that came through Cloudflare without a valid Access
token. The Tailscale address keeps working as it is."""
from __future__ import annotations

import base64
import io
import json
import os
import plistlib
import re
import sys
import textwrap
import time
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from convention_social import cli
from convention_social.core import access, auth, config, notify, tunnel
from convention_social.dashboard.app import COOKIE, create_app
from tests._base import IsolatedCase

REPO = Path(__file__).resolve().parents[1]
LABEL = "com.chriskennedyimages.conventionsocial.tunnel"
HOST = "dash.eventcaliber.com"
TEAM = "eventcaliber.cloudflareaccess.com"
AUD = "4714c1358e65fe4b408ad6d432a5f878f08194bdb4752441fd56faefa9b2b6f2"
EMAIL = "chriskimages@gmail.com"
ACCESS_KEYS = ("TUNNEL_HOSTNAME", "ACCESS_TEAM_DOMAIN", "ACCESS_AUD", "ACCESS_EMAIL", "CLOUDFLARE_TUNNEL_TOKEN",
               "DASHBOARD_PUBLIC_URL")
# the shape of a remotely-managed tunnel's token (base64 JSON: account, tunnel, secret); a stand-in, never a real one
TOKEN = base64.b64encode(json.dumps({"a": "0" * 32, "t": "1" * 8 + "-" + "2" * 4 + "-" + "3" * 4 + "-" + "4" * 4 + "-" + "5" * 12,
                                     "s": base64.b64encode(b"x" * 32).decode()}).encode()).decode()


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def int_b64u(n: int) -> str:
    return b64u(n.to_bytes((n.bit_length() + 7) // 8, "big"))


KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk(key, kid="k1") -> dict:
    pub = key.public_key().public_numbers()
    return {"kid": kid, "kty": "RSA", "alg": "RS256", "use": "sig", "e": int_b64u(pub.e), "n": int_b64u(pub.n)}


def jwt(claims: dict, key=KEY, kid="k1", alg="RS256") -> str:
    head = b64u(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    body = b64u(json.dumps(claims).encode())
    sig = key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64u(sig)}"


def claims(**over) -> dict:
    now = int(time.time())
    base = {"aud": [AUD], "email": EMAIL, "exp": now + 3600, "iat": now - 10, "nbf": now - 10,
            "iss": f"https://{TEAM}", "type": "app", "sub": "abc"}
    base.update(over)
    return base


def config_line(ingress: list, warp: bool = False, json_log: bool = False) -> str:
    """One `cloudflared` log line as it reports the routes Cloudflare sent (console form, or --output json)."""
    cfg = json.dumps({"ingress": ingress, "warp-routing": {"enabled": warp}})
    if json_log:
        return json.dumps({"level": "info", "version": 3, "config": cfg, "time": "2026-10-15T18:00:00Z",
                           "message": "Updated to new configuration"})
    return f"2026-10-15T18:00:00Z INF Updated to new configuration config={json.dumps(cfg)} version=3"


GOOD_ROUTES = [{"hostname": HOST, "originRequest": {}, "service": "http://127.0.0.1:4610"}, {"service": "http_status:404"}]


class AccessCase(IsolatedCase):
    def setUp(self):
        super().setUp()
        for key in ACCESS_KEYS:
            os.environ.pop(key, None)
        access.forget_keys()

    def configure(self, **over):
        values = {"TUNNEL_HOSTNAME": HOST, "ACCESS_TEAM_DOMAIN": TEAM, "ACCESS_AUD": AUD, "ACCESS_EMAIL": EMAIL}
        values.update(over)
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        config.reset()


# ---------------------------------------------------------------------------------------------- the service
class Template(AccessCase):
    def setUp(self):
        super().setUp()
        self.path = REPO / "launchd" / f"{LABEL}.plist.template"
        self.text = self.path.read_text()
        self.plist = plistlib.loads(self.text.encode())

    def test_the_tunnel_service_is_ours_and_runs_the_suites_own_gate(self):
        self.assertEqual(self.plist["Label"], LABEL)
        self.assertEqual(self.plist["ProgramArguments"], ["__PYTHON__", "-m", "convention_social.cli", "tunnel", "run"])
        self.assertEqual(self.plist["UserName"], "__USER__")
        self.assertIs(self.plist["KeepAlive"], True, "restarted when it stops")
        self.assertGreaterEqual(self.plist["ThrottleInterval"], 30, "a refused start is tried again at most once a minute")
        self.assertEqual(set(self.plist["EnvironmentVariables"]), {"HOME", "PATH", "CCS_DATA_ROOT", "PYTHONUNBUFFERED"})
        self.assertEqual(self.plist["StandardErrorPath"], "__DATA__/logs/tunnel.launchd.log")

    def test_no_secret_no_address_and_no_other_port_in_the_file(self):
        body = self.text.split("<plist version=\"1.0\">", 1)[1]        # below Apple's own DOCTYPE address
        for word in ("TOKEN", "eyJ", "token", "--url", "http://", "https://", "443", "8443", "tailscale"):
            self.assertNotIn(word, body, word)

    def test_cloudflared_gets_the_token_only_in_its_environment(self):
        cmd = tunnel.command("/opt/homebrew/bin/cloudflared")
        self.assertEqual(cmd, ["/opt/homebrew/bin/cloudflared", "tunnel", "--no-autoupdate", "run"])
        env = tunnel.child_env(TOKEN)
        self.assertEqual(set(env), {"HOME", "PATH", "TUNNEL_TOKEN"})
        self.assertEqual(env["TUNNEL_TOKEN"], TOKEN)
        self.assertTrue(env["HOME"].startswith(str(config.get_config().data_root)),
                        "cloudflared never reads a ~/.cloudflared another program on the Mini may keep")
        self.assertNotIn(TOKEN, " ".join(cmd))

    def test_the_address_cannot_collide_with_the_sites_own(self):
        """The Worker serves eventcaliber.com and www (wrangler.jsonc routes); the dashboard's address is another name."""
        text = "\n".join(ln for ln in (REPO / "wrangler.jsonc").read_text().splitlines() if not ln.strip().startswith("//"))
        patterns = {r["pattern"] for r in json.loads(text)["routes"]}
        self.assertEqual(patterns, {"eventcaliber.com", "www.eventcaliber.com"})
        self.assertNotIn(tunnel.default_hostname(), patterns)
        self.assertEqual(tunnel.default_hostname(), HOST)
        for bad in ("eventcaliber.com", "www.eventcaliber.com", "dash.example.org", "dash..eventcaliber.com", "a b.eventcaliber.com"):
            self.assertEqual(tunnel.norm_hostname(bad), "", bad)
        self.assertEqual(tunnel.norm_hostname(" https://Dash.EventCaliber.com/ "), HOST)


class Routes(AccessCase):
    """Cloudflare keeps the tunnel's routes; cloudflared says which it was given. Anything but our dashboard is refused."""

    def problems(self, line):
        return tunnel.route_problems(line, HOST, 4610)

    def test_our_dashboard_and_the_closing_404_pass(self):
        self.assertEqual(self.problems(config_line(GOOD_ROUTES)), [])
        self.assertEqual(self.problems(config_line(GOOD_ROUTES, json_log=True)), [])
        localhost = [{"hostname": HOST, "service": "http://localhost:4610/"}, {"service": "http_status:404"}]
        self.assertEqual(self.problems(config_line(localhost)), [])

    def test_any_other_port_service_host_or_private_network_is_refused(self):
        for routes, word in (
                ([{"hostname": HOST, "service": "http://127.0.0.1:4611"}, {"service": "http_status:404"}], "4611"),
                ([{"hostname": HOST, "service": "http://127.0.0.1:443"}, {"service": "http_status:404"}], "443"),
                ([{"hostname": HOST, "service": "ssh://127.0.0.1:22"}, {"service": "http_status:404"}], "ssh"),
                ([{"hostname": HOST, "service": "http://192.168.1.20:4610"}, {"service": "http_status:404"}], "192.168"),
                ([{"hostname": "other.eventcaliber.com", "service": "http://127.0.0.1:4610"}, {"service": "http_status:404"}], "other"),
                ([{"hostname": HOST, "service": "http://127.0.0.1:4610"}, {"service": "http://127.0.0.1:8080"}], "8080"),
                ([{"hostname": HOST, "service": "http://127.0.0.1:4610"}], "404")):
            got = self.problems(config_line(routes))
            self.assertTrue(got, routes)
            self.assertIn(word, " ".join(got))
        self.assertIn("private network", " ".join(self.problems(config_line(GOOD_ROUTES, warp=True))))

    def test_a_line_that_is_not_the_routes_is_none_and_a_garbled_one_is_refused(self):
        self.assertIsNone(self.problems("2026-10-15T18:00:00Z INF Registered tunnel connection connIndex=0"))
        self.assertTrue(self.problems('2026-10-15T18:00:00Z INF Updated to new configuration config="{not json" version=3'))


class Supervisor(AccessCase):
    def fake(self, body: str) -> list[str]:
        script = self.root / "fake_cloudflared.py"
        script.write_text("import sys, time\n" + textwrap.dedent(body))
        return [sys.executable, str(script)]

    def supervise(self, cmd, within=5.0):
        out = io.StringIO()
        code = tunnel.supervise(cmd, {"PATH": os.environ.get("PATH", "")}, HOST, 4610, confirm_within=within, out=out)
        return code, out.getvalue()

    def test_runs_while_cloudflare_routes_only_to_our_dashboard(self):
        cmd = self.fake(f"""
            print({config_line(GOOD_ROUTES)!r}, file=sys.stderr, flush=True)
            print("INF Registered tunnel connection connIndex=0", file=sys.stderr, flush=True)
            time.sleep(0.3)
            sys.exit(0)
        """)
        code, out = self.supervise(cmd)
        self.assertEqual(code, 0)
        self.assertIn("Registered tunnel connection", out, "cloudflared's own lines reach the log")
        self.assertIn("running, routed only to http://127.0.0.1:4610", out)
        self.assertEqual(tunnel.read_status()["state"], "stopped")

    def test_a_route_to_anything_else_stops_cloudflared_at_once(self):
        bad = [{"hostname": HOST, "service": "http://127.0.0.1:4611"}, {"service": "http_status:404"}]
        cmd = self.fake(f"""
            print({config_line(GOOD_ROUTES)!r}, file=sys.stderr, flush=True)
            time.sleep(0.2)
            print({config_line(bad)!r}, file=sys.stderr, flush=True)
            time.sleep(30)
        """)
        started = time.time()
        code, out = self.supervise(cmd)
        self.assertLess(time.time() - started, 10, "stopped, not left to run")
        self.assertNotEqual(code, 0)
        self.assertIn("4611", out)
        status = tunnel.read_status()
        self.assertEqual(status["state"], "refused")
        self.assertIn("4611", status["why"])

    def test_no_routes_said_in_time_is_a_stop(self):
        cmd = self.fake("""
            print("INF Starting tunnel", file=sys.stderr, flush=True)
            time.sleep(30)
        """)
        code, out = self.supervise(cmd, within=1.0)
        self.assertNotEqual(code, 0)
        self.assertIn("did not say which routes", out)
        self.assertEqual(tunnel.read_status()["state"], "refused")


class RunGate(AccessCase):
    """`ccs tunnel run` (the launchd service): nothing starts until every piece is in place and Access answers."""

    def run_cli(self, argv):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stderr", out):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_missing_pieces_start_nothing_and_never_show_the_token(self):
        os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = TOKEN
        self.configure(ACCESS_AUD=None)
        with mock.patch.object(tunnel.subprocess, "Popen", side_effect=AssertionError("started")) as popen:
            code, out = self.run_cli(["tunnel", "run"])
        self.assertNotEqual(code, 0)
        self.assertIn("ACCESS_AUD", out)
        self.assertNotIn(TOKEN, out)
        popen.assert_not_called()

    def test_no_access_from_outside_starts_nothing(self):
        os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = TOKEN
        self.configure()
        with mock.patch.object(tunnel.shutil, "which", return_value="/opt/homebrew/bin/cloudflared"), \
             mock.patch.object(access, "check_outside", return_value=(False, "https://dash.eventcaliber.com/ answered 200 itself")), \
             mock.patch.object(tunnel.subprocess, "Popen", side_effect=AssertionError("started")) as popen:
            code, out = self.run_cli(["tunnel", "run"])
        self.assertNotEqual(code, 0)
        self.assertIn("answered 200 itself", out)
        popen.assert_not_called()
        self.assertEqual(tunnel.read_status()["state"], "refused")

    def test_everything_in_place_starts_cloudflared_with_the_token_in_its_environment(self):
        os.environ["CLOUDFLARE_TUNNEL_TOKEN"] = TOKEN
        self.configure()
        seen = {}

        def supervise(cmd, env, hostname, port, **kw):
            seen.update(cmd=cmd, env=env, hostname=hostname, port=port)
            return 0
        with mock.patch.object(tunnel.shutil, "which", return_value="/opt/homebrew/bin/cloudflared"), \
             mock.patch.object(access, "check_outside", return_value=(True, "Access answers")), \
             mock.patch.object(tunnel, "supervise", supervise):
            code, out = self.run_cli(["tunnel", "run"])
        self.assertEqual(code, 0)
        self.assertEqual(seen["cmd"], ["/opt/homebrew/bin/cloudflared", "tunnel", "--no-autoupdate", "run"])
        self.assertEqual(seen["env"]["TUNNEL_TOKEN"], TOKEN)
        self.assertEqual((seen["hostname"], seen["port"]), (HOST, 4610))
        self.assertNotIn(TOKEN, out)


class OutsideCheck(AccessCase):
    """From outside, the address must answer Cloudflare's sign-in on every path, never the dashboard."""

    def check(self, answer):
        calls = []

        def get(url, **kw):
            calls.append(url)
            self.assertFalse(kw.get("allow_redirects", True), "the first answer is the one that counts")
            return answer if isinstance(answer, mock.Mock) else answer(url)
        self.configure()
        ok, why = access.check_outside(access.settings(), get=get)
        return ok, why, calls

    def test_the_access_sign_in_passes_on_every_path(self):
        signin = mock.Mock(status_code=302, headers={"Location": f"https://{TEAM}/cdn-cgi/access/login/{HOST}?kid={AUD}"})
        ok, why, calls = self.check(signin)
        self.assertTrue(ok, why)
        self.assertEqual(calls, [f"https://{HOST}{p}" for p in access.OUTSIDE_PATHS])
        self.assertIn("/queue/0/approve-by-token", access.OUTSIDE_PATHS, "the token paths are behind Access too")
        self.assertIn("/queue/0/choose-by-token/now", access.OUTSIDE_PATHS, "his three choices' path too (2026-10-15)")

    def test_anything_else_fails(self):
        for answer, word in ((mock.Mock(status_code=200, headers={}), "200"),
                             (mock.Mock(status_code=307, headers={"Location": "/login?next=/"}), "/login"),
                             (mock.Mock(status_code=302, headers={"Location": "https://elsewhere.example/x"}), "elsewhere"),
                             (mock.Mock(status_code=403, headers={}), "403")):
            ok, why, _ = self.check(answer)
            self.assertFalse(ok, answer)
            self.assertIn(word, why)

    def test_one_open_path_fails_the_whole_check(self):
        def answer(url):
            if url.endswith("/approve-by-token"):
                return mock.Mock(status_code=409, headers={})
            return mock.Mock(status_code=302, headers={"Location": f"https://{TEAM}/cdn-cgi/access/login/{HOST}"})
        ok, why, _ = self.check(answer)
        self.assertFalse(ok)
        self.assertIn("approve-by-token", why)

    def test_no_answer_and_no_settings_fail_closed(self):
        def down(url, **kw):
            raise ConnectionError("no route")
        self.configure()
        ok, why = access.check_outside(access.settings(), get=down)
        self.assertFalse(ok)
        self.assertIn("ConnectionError", why)

        def no_name(url, **kw):
            raise ConnectionError("HTTPSConnectionPool(host='dash.eventcaliber.com'): (Caused by NameResolutionError)")
        ok, why = access.check_outside(access.settings(), get=no_name)
        self.assertFalse(ok)
        self.assertIn("does not exist yet", why, "said in words, not Python's")
        self.configure(ACCESS_TEAM_DOMAIN=None)
        ok, why = access.check_outside(access.settings(), get=lambda *a, **k: self.fail("asked with no team"))
        self.assertFalse(ok)


class Setup(AccessCase):
    def run_setup(self, answers, secret):
        os.environ["CCS_ENV_FILE"] = str(self.root / "test.env")
        config.reset()
        out = io.StringIO()
        it = iter(answers)
        with redirect_stdout(out):
            code = tunnel.setup(ask=lambda prompt: next(it), ask_secret=lambda prompt: secret)
        return code, out.getvalue(), (self.root / "test.env")

    def test_saves_the_details_and_takes_the_token_out_of_the_pasted_command(self):
        code, out, env = self.run_setup(["", f"https://{TEAM}/", AUD, EMAIL],
                                        f"sudo cloudflared service install {TOKEN}")
        self.assertEqual(code, 0, out)
        text = env.read_text()
        for line in (f"TUNNEL_HOSTNAME={HOST}", f"ACCESS_TEAM_DOMAIN={TEAM}", f"ACCESS_AUD={AUD}", f"ACCESS_EMAIL={EMAIL}"):
            self.assertIn(line, text)
        self.assertIn("CLOUDFLARE_TUNNEL_TOKEN=", text)
        self.assertIn(TOKEN, text)
        self.assertNotIn(TOKEN, out, "the token is never shown")
        self.assertIn("do not run", out.lower(), "Cloudflare's own install command would run the tunnel without the gate")

    def test_refuses_the_sites_own_names_another_sign_in_domain_and_a_non_token(self):
        for answers, secret, word in (
                (["www.eventcaliber.com", TEAM, AUD, EMAIL], TOKEN, "www.eventcaliber.com"),
                (["", "eventcaliber.example.com", AUD, EMAIL], TOKEN, "cloudflareaccess.com"),
                (["", TEAM, "short", EMAIL], TOKEN, "tag"),
                (["", TEAM, AUD, "not-an-email"], TOKEN, "email"),
                (["", TEAM, AUD, EMAIL], "eyJnot-a-token", "token")):
            code, out, env = self.run_setup(answers, secret)
            self.assertNotEqual(code, 0, answers)
            self.assertIn(word, out)
            self.assertFalse(env.exists() and "CLOUDFLARE_TUNNEL_TOKEN" in env.read_text(), "nothing saved")


# ---------------------------------------------------------------------------------------------- the dashboard
class BehindAccess(AccessCase):
    """The real dashboard with a stand-in for the team's signing keys."""

    def setUp(self):
        super().setUp()
        os.environ["DASHBOARD_PASSWORD_HASH"] = auth.hash_password("correct horse")
        self.configure()
        self.fetches = []

        def certs(team):
            self.fetches.append(team)
            return {"keys": [jwk(KEY)], "public_cert": {}, "public_certs": []}
        p = mock.patch.object(access, "_fetch_certs", certs)
        p.start()
        self.addCleanup(p.stop)
        self.client = TestClient(create_app())

    def outside(self, token=None, **extra):
        headers = {"Host": HOST, "Cf-Ray": "8f00000000000000-IAD", "Cf-Connecting-Ip": "203.0.113.9",
                   "X-Forwarded-Proto": "https"}
        if token is not None:
            headers["Cf-Access-Jwt-Assertion"] = token
        headers.update(extra)
        return headers


class DashboardBehindAccess(BehindAccess):
    def test_through_the_tunnel_without_access_nothing_answers_but_the_refusal(self):
        for path in ("/login", "/", "/healthz", "/queue/1/approve-by-token", "/media/card/1/x.jpg"):
            r = self.client.get(path, headers=self.outside(), follow_redirects=False)
            self.assertEqual(r.status_code, 403, path)
            self.assertIn("Cloudflare Access", r.text)
            self.assertIn('name="viewport"', r.text, "a page a phone can read, not tiny plain text")
            self.assertNotIn("password", r.text.lower())
        r = self.client.post("/login", data={"password": "correct horse"}, headers=self.outside(), follow_redirects=False)
        self.assertEqual(r.status_code, 403, "the password is never even checked")
        self.assertNotIn("set-cookie", r.headers)

    def test_either_mark_of_cloudflare_is_enough(self):
        r = self.client.get("/login", headers={"Host": HOST})
        self.assertEqual(r.status_code, 403, "the tunnel's address alone")
        r = self.client.get("/login", headers={"Cf-Ray": "8f00000000000000-IAD"})
        self.assertEqual(r.status_code, 403, "Cloudflare's headers on any address")

    def test_a_valid_access_token_reaches_the_login_and_the_password_is_still_asked(self):
        token = jwt(claims())
        self.assertEqual(self.client.get("/login", headers=self.outside(token)).status_code, 200)
        r = self.client.get("/", headers=self.outside(token), follow_redirects=False)
        self.assertEqual(r.status_code, 307)
        self.assertTrue(r.headers["location"].startswith("/login"), "Access is the door; the password is still the key")
        cookie = jwt(claims())
        r = self.client.get("/login", headers={**self.outside(), "Cookie": f"CF_Authorization={cookie}"})
        self.assertEqual(r.status_code, 200, "a browser carries the same token as the CF_Authorization cookie")

    def test_every_wrong_token_is_refused(self):
        now = int(time.time())
        for name, token in (("another application", jwt(claims(aud=["0" * 64]))),
                            ("another sign-in domain", jwt(claims(iss="https://other.cloudflareaccess.com"))),
                            ("expired", jwt(claims(exp=now - 120))),
                            ("not yet valid", jwt(claims(nbf=now + 600))),
                            ("another email", jwt(claims(email="someone@example.com"))),
                            ("no email", jwt({k: v for k, v in claims().items() if k != "email"}))
                            , ("signed by another key", jwt(claims(), key=OTHER_KEY))
                            , ("an unknown key id", jwt(claims(), kid="k9"))
                            , ("alg none", f"{b64u(json.dumps({'alg': 'none', 'kid': 'k1'}).encode())}."
                                           f"{b64u(json.dumps(claims()).encode())}.")
                            , ("HS256", jwt(claims(), alg="HS256"))
                            , ("garbage", "not.a.token")):
            r = self.client.get("/login", headers=self.outside(token))
            self.assertEqual(r.status_code, 403, name)

    def test_the_same_email_in_capitals_is_his(self):
        self.assertEqual(self.client.get("/login", headers=self.outside(jwt(claims(email="ChrisKImages@Gmail.com")))).status_code, 200)

    def test_unset_access_details_refuse_everything_from_outside(self):
        self.configure(ACCESS_AUD=None)
        self.assertEqual(self.client.get("/login", headers=self.outside(jwt(claims()))).status_code, 403)
        self.configure(ACCESS_EMAIL=None)
        self.assertEqual(self.client.get("/login", headers=self.outside(jwt(claims()))).status_code, 403)

    def test_cloudflares_keys_out_of_reach_refuse(self):
        def down(team):
            raise ConnectionError("no route")
        access.forget_keys()
        with mock.patch.object(access, "_fetch_certs", down):
            r = self.client.get("/login", headers=self.outside(jwt(claims())))
        self.assertEqual(r.status_code, 403)
        self.assertIn("signing keys", r.text)

    def test_the_keys_are_fetched_once_not_per_request(self):
        token = jwt(claims())
        for _ in range(3):
            self.client.get("/login", headers=self.outside(token))
        self.assertEqual(self.fetches, [TEAM])

    def test_tailscale_and_the_mini_itself_are_untouched(self):
        self.assertEqual(self.client.get("/login", headers={"Host": "mac-mini.tail915d2c.ts.net:8443"}).status_code, 200)
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_the_session_cookie_is_secure_over_https_only(self):
        r = self.client.post("/login", data={"password": "correct horse"}, headers=self.outside(jwt(claims())),
                             follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        cookie = r.headers["set-cookie"]
        self.assertIn(f"{COOKIE}=", cookie)
        for part in ("Secure", "HttpOnly", "SameSite=lax"):
            self.assertIn(part, cookie)
        r = TestClient(create_app(), base_url="https://mac-mini.tail915d2c.ts.net:8443").post(
            "/login", data={"password": "correct horse"}, follow_redirects=False)
        self.assertIn("Secure", r.headers["set-cookie"], "the Tailscale address is https too")
        r = self.client.post("/login", data={"password": "correct horse"}, follow_redirects=False)
        self.assertNotIn("Secure", r.headers["set-cookie"], "plain http on the Mini itself keeps working")


# ---------------------------------------------------------------------------------------------- the links
class Links(AccessCase):
    """Behind Access only a browser gets in, so a ping's buttons open the browser: the ntfy app's own POST and
    its picture fetch would land on Cloudflare's sign-in, and the Approve would look done when nothing was."""

    def test_through_access_approve_opens_the_page_and_no_picture_is_fetched(self):
        """Since 2026-10-15 the one Approve is his three choices (Post now, Follow the pace, Skip): behind Access each opens
        the choice page in the browser."""
        self.configure(DASHBOARD_PUBLIC_URL=f"https://{HOST}")
        self.assertTrue(access.through_access(notify.link("/")))
        actions = notify.choice_actions(7, "1.2.3")
        self.assertEqual(actions, "; ".join(f"view, {label}, https://{HOST}/queue/7/choose-by-token/{how}?token=1.2.3, clear=true"
                                            for how, label in (("now", "Post now"), ("pace", "Follow the pace"), ("skip", "Skip"))))
        self.assertNotIn("http, ", actions)
        self.assertIsNone(notify.card_link(7, "1.2.3"))

    def test_any_address_on_the_sites_domain_counts_as_behind_access(self):
        self.configure(TUNNEL_HOSTNAME=None, DASHBOARD_PUBLIC_URL="https://dashboard.eventcaliber.com")
        self.assertTrue(access.through_access(notify.link("/")))
        self.assertTrue(notify.choice_actions(7, "1.2.3").startswith("view, Post now, "))

    def test_the_tailscale_address_keeps_the_one_tap_approve_and_the_picture(self):
        self.configure(DASHBOARD_PUBLIC_URL="https://mac-mini.tail915d2c.ts.net:8443")
        self.assertFalse(access.through_access(notify.link("/")))
        self.assertTrue(notify.choice_actions(7, "1.2.3").startswith(
            "http, Post now, https://mac-mini.tail915d2c.ts.net:8443/queue/7/choose-by-token/now, method=POST"))
        self.assertEqual(notify.card_link(7, "1.2.3"), "https://mac-mini.tail915d2c.ts.net:8443/media/card/7/1.2.3.jpg")

    def test_no_picture_means_no_filename_either(self):
        """ntfy treats a message with a Filename and no Attach as a file upload: the words would arrive as a file."""
        os.environ["NTFY_TOPIC"] = "event-caliber-abc"
        config.reset()
        seen = {}

        def ok(url, **kw):
            seen.update(kw)
            return mock.Mock(status_code=200)
        self.assertEqual(notify.push_result("t", "m", dry_run=False, transport=ok, attach=None, filename="post-7.jpg"), "sent")
        self.assertNotIn("Filename", seen["headers"])
        self.assertNotIn("Attach", seen["headers"])
        notify.push_result("t", "m", dry_run=False, transport=ok, attach="https://x.example/c.jpg", filename="post-7.jpg")
        self.assertEqual(seen["headers"]["Filename"], "post-7.jpg")


# ---------------------------------------------------------------------------------------------- go-live
class Scripts(AccessCase):
    def setUp(self):
        super().setUp()
        self.go = (REPO / "scripts/go-live.sh").read_text()
        self.install = (REPO / "scripts/install-daemons.sh").read_text()

    def test_the_installer_puts_the_tunnel_in_only_when_its_check_passes(self):
        gate = self.install.index("tunnel check --quiet")
        loop = self.install.index('for t in "${templates[@]}"; do')
        self.assertLess(gate, loop)
        block = self.install[gate - 400:loop]
        self.assertIn('templates=(${templates:#*/${TUNNEL_LABEL}.plist.template})', block)
        self.assertIn('TUNNEL_LABEL="${PREFIX}tunnel"', self.install)
        self.assertIn('sudo -u "$USER_NAME"', block, "the check runs as Chris, with his .env, never as root")
        # with no tunnel, only our own tunnel service is stopped and removed, never anything else
        self.assertIn('launchctl bootout "system/$TUNNEL_LABEL"', block)
        self.assertIn('rm -f "$DST/$TUNNEL_LABEL.plist"', block)
        self.assertNotRegex(self.install, r"bootout\s+\S*cloudflare", "another cloudflared on the Mini is never stopped")

    def test_go_live_reads_what_is_there_and_points_the_links_only_at_a_working_tunnel(self):
        check = self.go.index("bin/ccs tunnel check")
        install = self.go.index('sudo "$REPO/scripts/install-daemons.sh" || stop ')
        self.assertLess(check, install)
        self.assertIn("have CLOUDFLARE_TUNNEL_TOKEN", self.go[check - 300:check])
        use = self.go.index("bin/ccs tunnel status --wait")
        self.assertLess(install, use)
        self.assertIn("--use", self.go[use:use + 80], "DASHBOARD_PUBLIC_URL moves only once the tunnel runs")
        self.assertLess(use, self.go.index("bin/ccs site deploy --no-check"), "the site's own pings get the address too")
        self.assertIn('"--tunnel"', self.go)
        self.assertIn("bin/ccs tunnel setup", self.go)

    def test_nothing_runs_cloudflares_own_installer_or_changes_tailscale(self):
        for path in (REPO / "scripts").glob("*.sh"):
            text = path.read_text()
            self.assertNotIn("cloudflared service install", text, path.name)
            for line in text.splitlines():
                if "tailscale" in line and not line.lstrip().startswith(("print", "#", "echo")):
                    self.fail(f"{path.name} runs tailscale: {line.strip()}")


class MediaThroughTheTunnel(BehindAccess):
    """Chris, 2026-10-15: "does this have a place for the sample posts reels that get created". Every page and file the
    dashboard serves goes through the tunnel, the design samples and their reels included; a phone plays and seeks a
    reel with byte ranges; and nothing private stays in Cloudflare's cache, which by default keeps .jpg and .mp4 for
    two hours when the origin says nothing (developers.cloudflare.com/cache/concepts/default-cache-behavior/)."""

    def setUp(self):
        super().setUp()
        from convention_social.dashboard.app import make_token
        folder = config.get_config().data_root / "renders" / "design-20261015-1200"
        folder.mkdir(parents=True)
        self.reel = bytes(range(256)) * 40                     # 10240 bytes standing in for rooms-reel.mp4
        (folder / "rooms-reel.mp4").write_bytes(self.reel)
        (folder / "fan-post.jpg").write_bytes(b"\xff\xd8" + b"x" * 500)
        self.client.cookies.set(COOKIE, make_token("chris"))

    def test_a_reel_plays_and_seeks_through_the_tunnel_and_stays_out_of_cloudflares_cache(self):
        token = jwt(claims())
        r = self.client.get("/library/design/design-20261015-1200/rooms-reel.mp4", headers={**self.outside(token), "Range": "bytes=1000-1999"})
        self.assertEqual(r.status_code, 206, "a phone seeks a video with byte ranges")
        self.assertEqual(r.headers["content-range"], f"bytes 1000-1999/{len(self.reel)}")
        self.assertEqual(r.content, self.reel[1000:2000])
        self.assertEqual(r.headers["content-type"], "video/mp4")
        self.assertEqual(r.headers["cache-control"], "private, no-store")
        r = self.client.get("/library/design/design-20261015-1200/rooms-reel.mp4", headers=self.outside(token))
        self.assertEqual((r.status_code, r.content), (200, self.reel))
        self.assertEqual(r.headers["cache-control"], "private, no-store")
        self.assertEqual(r.headers.get("accept-ranges"), "bytes")

    def test_every_answer_through_the_tunnel_is_private(self):
        token = jwt(claims())
        for path in ("/library/design/design-20261015-1200/fan-post.jpg", "/login", "/", "/healthz"):
            r = self.client.get(path, headers=self.outside(token), follow_redirects=False)
            self.assertEqual(r.headers.get("cache-control"), "private, no-store", path)

    def test_without_access_the_samples_are_refused_too(self):
        r = self.client.get("/library/design/design-20261015-1200/rooms-reel.mp4", headers=self.outside())
        self.assertEqual(r.status_code, 403)
        self.assertNotEqual(r.content[:4], self.reel[:4])

    def test_the_tailscale_address_keeps_its_own_headers(self):
        r = self.client.get("/library/design/design-20261015-1200/rooms-reel.mp4", headers={"Range": "bytes=0-99"})
        self.assertEqual((r.status_code, r.content), (206, self.reel[:100]))
        self.assertNotIn("private", r.headers.get("cache-control", ""))
