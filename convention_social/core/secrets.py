"""Secrets: process env -> <repo>/.env -> macOS Keychain. Nothing else.

Keychain entries live under service KEYCHAIN_SERVICE with the account set to
the variable name, e.g.
  security add-generic-password -s com.chriskennedyimages.conventionsocial -a BUFFER_API_KEY -w
(no value on the command line: `security` then asks for it, so it never lands
in shell history). Values are never logged. `present()` reports which names
resolve, for the dashboard and `bin/ccs env-check`, without exposing them.
"""
from __future__ import annotations

import subprocess
from typing import Optional

from . import config

KEYCHAIN_SERVICE = "com.chriskennedyimages.conventionsocial"

SECRET_NAMES = (
    "SMTP_PASSWORD",
    "ANTHROPIC_API_KEY",
    "BUFFER_API_KEY",
    "R2_KEY",
    "R2_SECRET",
    "MEDIA_UPLOAD_TOKEN",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "DASHBOARD_PASSWORD_HASH",
)


def _keychain(name: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    value = out.stdout.strip()
    return value or None


def get_secret(name: str) -> Optional[str]:
    """No secret this suite uses may contain whitespace, so it is stripped: Google
    shows app passwords as four spaced groups and people paste them that way."""
    value = config.getenv(name) or _keychain(name)
    if not value:
        return None
    return "".join(value.split()) or None


def present() -> dict[str, bool]:
    return {name: bool(get_secret(name)) for name in SECRET_NAMES}
