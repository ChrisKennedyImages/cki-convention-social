"""Dashboard password: PBKDF2-SHA256 hash stored in DASHBOARD_PASSWORD_HASH. No plaintext anywhere."""
from __future__ import annotations

import hashlib
import secrets as pysecrets

ROUNDS = 200_000


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or pysecrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ROUNDS).hex()
    return f"pbkdf2${ROUNDS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, digest = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
        return pysecrets.compare_digest(calc, digest)
    except (ValueError, AttributeError):
        return False
