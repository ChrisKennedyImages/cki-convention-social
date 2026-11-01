"""The one-tap Approve on a phone ping (Chris, 2026-10-13: the morning ping carries the card and an Approve button).

A signed, single-use token rides the ping's Approve action. It is HMAC-SHA256 over `qid|updated_at|exp|nonce`
with the dashboard's own session secret; the nonce lives in the settings table (`queue.<qid>.ping_nonce`), written
when the draft is pinged and blanked when the post is approved, so a token works once. Any save, rewrite or mend
changes `updated_at` and kills it. It lasts TOKEN_HOURS. An approval happens only on a POST (a GET with the token
is a page with a button and approves nothing).

The card the ping shows is fetched by the phone from the dashboard without a login, so its address needs a key of
its own: `card_key`, signed over `card|qid|updated_at|exp|nonce`, opens the card and nothing else. The address, and
the dashboard's access log that keeps every address, never carry the approve token (2026-10-24 audit: 59 tokens in
the log). The card key lives and dies with the token: the nonce blanked, the row changed, the hours up.

The same token serves other rows Chris decides from a ping (2026-11-01: the SEO agent's changes, seo/changes.py), each
under its own Scope: the nonce lives at `<scope>.<id>.ping_nonce` and the scope's name is signed first, so a token for
one kind of row never opens another. A post's token signs exactly as it always has, so the pings already on his phone
keep working.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets as pysecrets
import time
from dataclasses import dataclass
from typing import Optional

from . import config, settings

TOKEN_HOURS = 36
SECRET_FILE = "dashboard.secret"


@dataclass(frozen=True)
class Scope:
    name: str           # the nonce's settings prefix, and (for all but posts) the first thing signed
    where: str          # where he goes to decide instead, in the refusals
    changed: str        # what the refusal says when the row changed since the ping


POSTS = Scope("queue", "the draft", "The post changed since that ping (a save or a rewrite).")


def secret() -> bytes:
    """The dashboard's own secret (the same file that signs its session cookie), made on first use."""
    cfg = config.get_config()
    cfg.locks_dir.mkdir(parents=True, exist_ok=True)
    path = cfg.locks_dir / SECRET_FILE
    if not path.exists():
        path.write_text(pysecrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


def nonce_key(rid: int, scope: Scope = POSTS) -> str:
    return f"{scope.name}.{rid}.ping_nonce"


def _sign(*parts) -> str:
    return hmac.new(secret(), "|".join(str(p) for p in parts).encode(), hashlib.sha256).hexdigest()


def _subject(row, scope: Scope) -> tuple:
    """What a token signs about its row: its id and updated_at, after the scope's name for anything but a post."""
    return (row["id"], row["updated_at"]) if scope is POSTS else (scope.name, row["id"], row["updated_at"])


def issue(conn, row, now: Optional[float] = None, scope: Scope = POSTS) -> str:
    """A fresh token for this row (a new nonce replaces any older one, so only the latest ping's button works)."""
    nonce = pysecrets.token_hex(16)
    settings.set(conn, nonce_key(row["id"], scope), nonce)
    exp = int((now or time.time()) + TOKEN_HOURS * 3600)
    return f"{exp}.{nonce}.{_sign(*_subject(row, scope), exp, nonce)}"


def check(conn, row, token: str, now: Optional[float] = None, scope: Scope = POSTS) -> tuple[bool, str]:
    """(True, "") when the token is this row's, unspent, unexpired and the row is as it was; else (False, why)."""
    parts = (token or "").strip().split(".")
    if len(parts) != 3:
        return False, "That link is not a valid approve link."
    exp_s, nonce, sig = parts
    try:
        exp = int(exp_s)
    except ValueError:
        return False, "That link is not a valid approve link."
    if not nonce or settings.get(conn, nonce_key(row["id"], scope)) != nonce:
        return False, f"That approve button was already used, or belongs to an older ping. Open {scope.where} to approve it."
    if exp < (now or time.time()):
        return False, f"That approve button has expired. Open {scope.where} to approve it."
    if not hmac.compare_digest(_sign(*_subject(row, scope), exp, nonce), sig):
        return False, f"{scope.changed} Open {scope.where} to see it and approve it."
    return True, ""


def card_key(row, token: str) -> str:
    """The card's key for this token: `exp.signature`, nothing a POST could approve with."""
    exp, nonce, _ = token.split(".")
    return f"{exp}.{_sign('card', row['id'], row['updated_at'], exp, nonce)}"


def check_card(conn, row, key: str, now: Optional[float] = None) -> bool:
    """True when `key` is this draft's card key from a token that is unspent, unexpired and the draft's as it was."""
    parts = (key or "").split(".")
    if len(parts) != 2 or not parts[0].isdigit():
        return False
    exp, sig = parts
    nonce = settings.get(conn, nonce_key(row["id"]))
    if not nonce or int(exp) < (now or time.time()):
        return False
    return hmac.compare_digest(_sign("card", row["id"], row["updated_at"], exp, nonce), sig)


def spend(conn, rid: int, scope: Scope = POSTS) -> None:
    """The token is used: no second approval from the same ping."""
    settings.set(conn, nonce_key(rid, scope), "")
