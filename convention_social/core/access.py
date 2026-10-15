"""Cloudflare Access in front of the dashboard away from home (Chris, 2026-10-15: "can i reach this dashboard
without running tailscale when im out of town?").

The Mini runs a Cloudflare Tunnel (core/tunnel.py) to a private address, `TUNNEL_HOSTNAME` (dash.eventcaliber.com).
Cloudflare Access stands in front of it: a one-time code sent to `ACCESS_EMAIL`, nobody else. The dashboard's own
password stays behind it. The rule: **never public without Access.** Three gates, each failing closed:

- `check_outside`: from outside, every path of the address answers Cloudflare's sign-in (a redirect to the team's
  `*.cloudflareaccess.com`), never the dashboard. The tunnel does not start until it passes.
- `refusal`: a request that came through Cloudflare (its `Cf-Ray` or `Cf-Connecting-Ip` header, or the tunnel's
  address as its Host) is refused unless it carries a valid Access token: RS256, signed by one of the team's keys
  (`https://<team>/cdn-cgi/access/certs`), for this application (`ACCESS_AUD`), from the team (`iss`), unexpired,
  for `ACCESS_EMAIL`. Missing settings, unreachable keys or any doubt: refused. Tailscale and the Mini itself carry
  no Cloudflare header and are untouched.
- `through_access`: a link on the tunnel's address (or anywhere on the site's domain) opens only in a browser, so a
  ping's Approve opens the approve page instead of posting from the ntfy app (whose POST would meet the sign-in).

Cloudflare's docs, read 2026-10-15: developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/
authorization-cookie/validating-json/ (the header, the CF_Authorization cookie, the certs, RS256, iss, aud) and
developers.cloudflare.com/fundamentals/reference/http-headers/ (Cf-Ray and CF-Connecting-IP on every proxied request).
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit

from . import config

HOST_KEY, TEAM_KEY, AUD_KEY, EMAIL_KEY = "TUNNEL_HOSTNAME", "ACCESS_TEAM_DOMAIN", "ACCESS_AUD", "ACCESS_EMAIL"
JWT_HEADER = "cf-access-jwt-assertion"
JWT_COOKIE = "CF_Authorization"
CLOUDFLARE_MARKS = ("cf-ray", "cf-connecting-ip", JWT_HEADER)      # set by Cloudflare's edge on every proxied request
TEAM_SUFFIX = ".cloudflareaccess.com"
AUD_RE = re.compile(r"^[A-Za-z0-9]{32,128}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
KEYS_FOR = 3600          # seconds Cloudflare's signing keys are kept before they are read again
REFETCH_AFTER = 60       # an unknown key id reads them again, at most this often
LEEWAY = 60              # seconds of clock difference allowed on exp and nbf
# the paths the outside check asks for: the start, the login, the token paths a ping opens, the updater's check
OUTSIDE_PATHS = ("/", "/login", "/queue/0/approve-by-token", "/media/card/0/x.jpg", "/healthz")
REFUSED = ("This address opens only through Cloudflare Access sign-in, and this request did not come with a valid "
           "one. Open the address again in your browser to get the email code. ({why})")


@dataclass(frozen=True)
class Settings:
    hostname: str
    team: str
    aud: str
    email: str

    def missing(self) -> list[str]:
        return [key for key, value in ((HOST_KEY, self.hostname), (TEAM_KEY, self.team), (AUD_KEY, self.aud),
                                       (EMAIL_KEY, self.email)) if not value]


def norm_team(raw: Optional[str]) -> str:
    """`eventcaliber.cloudflareaccess.com`, from that or its https address; anything not on cloudflareaccess.com is ""."""
    text = (raw or "").strip()
    host = (urlsplit(text if "//" in text else "//" + text).hostname or "").lower()
    if not host.endswith(TEAM_SUFFIX):
        return ""
    return host if re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host[:-len(TEAM_SUFFIX)]) else ""


def norm_aud(raw: Optional[str]) -> str:
    value = (raw or "").strip()
    return value if AUD_RE.match(value) else ""


def norm_email(raw: Optional[str]) -> str:
    value = (raw or "").strip().lower()
    return value if EMAIL_RE.match(value) else ""


def settings() -> Settings:
    from .tunnel import norm_hostname
    return Settings(hostname=norm_hostname(config.getenv(HOST_KEY)), team=norm_team(config.getenv(TEAM_KEY)),
                    aud=norm_aud(config.getenv(AUD_KEY)), email=norm_email(config.getenv(EMAIL_KEY)))


def _host_only(host_header: str) -> str:
    return (urlsplit(f"//{host_header.strip()}").hostname or "").lower() if host_header else ""


def from_outside(headers: Mapping[str, str], s: Optional[Settings] = None) -> bool:
    """Came through Cloudflare: any of the headers its edge adds, or the tunnel's address as the Host."""
    if any(headers.get(mark) for mark in CLOUDFLARE_MARKS):
        return True
    s = s or settings()
    return bool(s.hostname) and _host_only(headers.get("host", "")) == s.hostname


def token_from(headers: Mapping[str, str], cookies: Mapping[str, str]) -> str:
    return (headers.get(JWT_HEADER) or cookies.get(JWT_COOKIE) or "").strip()


def refusal(headers: Mapping[str, str], cookies: Mapping[str, str], now: Optional[float] = None) -> Optional[str]:
    """None: let the request through (it did not come through Cloudflare, or it carries a valid Access token for
    Chris). Else the sentence the 403 says. Every doubt is a refusal."""
    s = settings()
    if not from_outside(headers, s):
        return None
    if s.missing():
        return REFUSED.format(why="this Mini has no Access settings: " + ", ".join(s.missing()))
    ok, why = verify(token_from(headers, cookies), s, now=now)
    return None if ok else REFUSED.format(why=why)


def secure_request(scheme: str, headers: Mapping[str, str]) -> bool:
    """The session cookie is Secure whenever the browser is on https: the tunnel, the Tailscale address
    (uvicorn takes X-Forwarded-Proto from a proxy on 127.0.0.1), or anything Cloudflare passed on."""
    return scheme == "https" or headers.get("x-forwarded-proto", "").lower() == "https" or from_outside(headers)


# ---------------------------------------------------------------------------------------------- the token
def _b64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


_KEYS: dict[str, tuple[float, dict]] = {}
_KEYS_LOCK = threading.Lock()


def forget_keys() -> None:
    with _KEYS_LOCK:
        _KEYS.clear()


def _fetch_certs(team: str) -> dict:
    import requests
    r = requests.get(f"https://{team}/cdn-cgi/access/certs", timeout=5)
    r.raise_for_status()
    return r.json()


def _public_keys(doc: dict) -> dict:
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
    keys = {}
    for k in doc.get("keys") or []:
        if k.get("kty") == "RSA" and k.get("kid") and k.get("n") and k.get("e"):
            n, e = (int.from_bytes(_b64(k[f]), "big") for f in ("n", "e"))
            keys[k["kid"]] = RSAPublicNumbers(e, n).public_key()
    return keys


def signing_key(team: str, kid: str, now: float):
    """The team's public key for `kid`, read from Cloudflare at most hourly (and again, at most once a minute,
    for a key id it has not seen: Cloudflare rotates them). Raises when they cannot be read."""
    with _KEYS_LOCK:
        fetched, keys = _KEYS.get(team, (0.0, {}))
        if now - fetched > KEYS_FOR or (kid not in keys and now - fetched > REFETCH_AFTER):
            keys = _public_keys(_fetch_certs(team))
            _KEYS[team] = (now, keys)
        return keys.get(kid)


def verify(token: str, s: Settings, now: Optional[float] = None) -> tuple[bool, str]:
    """(True, "") only for an Access application token this application issued for Chris; else (False, why)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    now = time.time() if now is None else now
    if not token:
        return False, "no Access token"
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return False, "not an Access token"
    try:
        head, body, sig = json.loads(_b64(parts[0])), json.loads(_b64(parts[1])), _b64(parts[2])
    except (ValueError, TypeError):
        return False, "not an Access token"
    if not isinstance(head, dict) or not isinstance(body, dict) or head.get("alg") != "RS256":
        return False, "not an RS256 Access token"
    try:
        key = signing_key(s.team, str(head.get("kid") or ""), now)
    except Exception as e:  # noqa: BLE001  no keys, no entry
        return False, f"Cloudflare's signing keys could not be read ({type(e).__name__})"
    if key is None:
        return False, "signed by a key Cloudflare does not list for this team"
    try:
        key.verify(sig, f"{parts[0]}.{parts[1]}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        return False, "the signature does not check"
    aud = body.get("aud")
    if s.aud not in (aud if isinstance(aud, list) else [aud]):
        return False, "issued for another application"
    if body.get("iss") != f"https://{s.team}":
        return False, "issued by another sign-in domain"
    try:
        if float(body["exp"]) < now - LEEWAY:
            return False, "expired"
        if float(body.get("nbf", 0)) > now + LEEWAY:
            return False, "not valid yet"
    except (KeyError, TypeError, ValueError):
        return False, "no expiry"
    if str(body.get("email") or "").strip().lower() != s.email:
        return False, "not the email this dashboard allows"
    return True, ""


# ---------------------------------------------------------------------------------------------- links
def through_access(url: str) -> bool:
    """The address only a browser can open: the tunnel's, or any name on the site's own domain (the dashboard is
    never served there except through the tunnel). The Tailscale address and 127.0.0.1 are not."""
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return False
    s_host = settings().hostname
    domain = (config.get_config().brand_domain or "").lower().strip(".")
    return host == s_host or bool(domain) and (host == domain or host.endswith("." + domain))


# ---------------------------------------------------------------------------------------------- from outside
def check_outside(s: Settings, get: Optional[Callable] = None) -> tuple[bool, str]:
    """From outside, does every path of the address answer Cloudflare's sign-in, never the dashboard? (True, what
    was seen) or (False, why). Settings missing, no answer, or any other answer: False."""
    if s.missing():
        return False, "missing on this Mini: " + ", ".join(s.missing())
    if get is None:
        import requests
        get = requests.get
    for path in OUTSIDE_PATHS:
        url = f"https://{s.hostname}{path}"
        try:
            r = get(url, allow_redirects=False, timeout=10,
                    headers={"Accept": "text/html", "User-Agent": "event-caliber-suite outside check"})
        except Exception as e:  # noqa: BLE001  no answer is not a pass
            return False, f"{url} did not answer ({type(e).__name__}: {str(e)[:120]})"
        code = getattr(r, "status_code", 0)
        where = (getattr(r, "headers", {}) or {}).get("Location") or (getattr(r, "headers", {}) or {}).get("location") or ""
        to = (urlsplit(where).hostname or "").lower()
        if not (300 <= code < 400 and to == s.team):
            seen = f"answered {code}" + (f" to {where[:120]}" if where else "")
            return False, (f"{url} {seen}, not Cloudflare's sign-in at {s.team}: Access is not in front of every path. "
                           "Nothing is started until it is.")
    return True, f"every path of https://{s.hostname} answers Cloudflare's sign-in at {s.team}"
