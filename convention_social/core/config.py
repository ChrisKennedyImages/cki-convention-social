"""Configuration: the repo's own .env plus the process environment, nothing else.

No home-directory secrets file, no shell profile and no other checkout is
ever read. The only file consulted is <repo>/.env, and it never overrides
variables already in the environment. Everything runtime-writable lives under
DATA_ROOT, which defaults to ~/cki-convention-social-data and is created on
demand. The brand name is a setting, not code: changing BRAND_NAME in .env
renames the company everywhere the suite writes it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = Path.home() / "cki-convention-social-data"
DATA_SUBDIRS = ("db", "logs", "photos", "thumbs", "renders", "backups", "outbox-dry", "cache", ".locks")
DEFAULT_PORT = 4610          # taken on the Mini: 4000, 8090, 8443, 8710, 8765, 11434

_ENV_FILE_CACHE: dict[str, str] | None = None
_ENV_FILE_PATH: Path | None = None


def env_file_path() -> Path:
    """<repo>/.env unless a test points CCS_ENV_FILE elsewhere."""
    override = os.environ.get("CCS_ENV_FILE")
    return Path(override).expanduser() if override else REPO_ROOT / ".env"


def env_values() -> dict[str, str]:
    """Values from the .env file only (cached per path). Missing file -> {}."""
    global _ENV_FILE_CACHE, _ENV_FILE_PATH
    path = env_file_path()
    if _ENV_FILE_CACHE is None or _ENV_FILE_PATH != path:
        _ENV_FILE_PATH = path
        if path.exists():
            _ENV_FILE_CACHE = {k: v for k, v in dotenv_values(path).items() if v is not None}
        else:
            _ENV_FILE_CACHE = {}
    return _ENV_FILE_CACHE


def _quote(value: str) -> str:
    """A value the .env parser reads back exactly; quoted when it has to be."""
    if value == "" or any(ch in value for ch in ' \t#"\'\\'):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def write_env(updates: dict[str, str]) -> Path:
    """Set KEY=value lines in the .env file (create it if missing), keep every
    other line as it is, keep the file private, and forget the cached values so
    this process sees the change on its next read. Values are never logged."""
    path = env_file_path()
    lines = path.read_text().splitlines() if path.exists() else []
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else None
        if key in pending:
            out.append(f"{key}={_quote(pending.pop(key))}")
        else:
            out.append(line)
    for key, value in pending.items():
        out.append(f"{key}={_quote(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n")
    path.chmod(0o600)
    reset()
    return path


def getenv(key: str, default: Optional[str] = None) -> Optional[str]:
    """Process environment first, then the .env file, then default."""
    value = os.environ.get(key)
    if value is not None and value.strip() != "":
        return value.strip()
    value = env_values().get(key)
    if value is not None and value.strip() != "":
        return value.strip()
    return default


def _int(key: str, default: int) -> int:
    raw = getenv(key)
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def _float(key: str, default: float) -> float:
    raw = getenv(key)
    try:
        return float(raw) if raw is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    brand_name: str
    brand_domain: str
    brand_from_email: str
    brand_postal_address: str
    legal_name: str
    data_root: Path
    timezone: str
    dashboard_port: int
    dashboard_public_url: str
    dashboard_password_hash: str
    smtp_host: str
    smtp_user: str
    ai_monthly_cap_usd: float
    buffer_plan: str
    ntfy_topic: str
    alert_email: str
    digest_hour: int
    variety_days: int
    photo_repeat_days: int
    subdirs: tuple[str, ...] = field(default=DATA_SUBDIRS)

    @property
    def db_path(self) -> Path:
        return self.data_root / "db" / "convention_social.sqlite3"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def locks_dir(self) -> Path:
        return self.data_root / ".locks"

    def ensure_dirs(self) -> None:
        for sub in self.subdirs:
            (self.data_root / sub).mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    data_root = Path(getenv("CCS_DATA_ROOT", str(DEFAULT_DATA_ROOT))).expanduser()
    return Config(
        brand_name=getenv("BRAND_NAME", "Event Caliber"),
        brand_domain=getenv("BRAND_DOMAIN", ""),
        brand_from_email=getenv("BRAND_FROM_EMAIL", ""),
        brand_postal_address=getenv("BRAND_POSTAL_ADDRESS", ""),
        legal_name=getenv("LEGAL_NAME", "CKI, LLC"),
        data_root=data_root,
        timezone=getenv("TIMEZONE", "America/New_York"),
        dashboard_port=_int("DASHBOARD_PORT", DEFAULT_PORT),
        dashboard_public_url=(getenv("DASHBOARD_PUBLIC_URL", "") or "").rstrip("/"),
        dashboard_password_hash=getenv("DASHBOARD_PASSWORD_HASH", ""),
        smtp_host=getenv("SMTP_HOST", ""),
        smtp_user=getenv("SMTP_USER", ""),
        ai_monthly_cap_usd=_float("AI_MONTHLY_CAP_USD", 20.0),
        buffer_plan=getenv("BUFFER_PLAN", "essentials").lower(),
        ntfy_topic=getenv("NTFY_TOPIC", ""),
        alert_email=getenv("ALERT_EMAIL", ""),
        digest_hour=_int("DIGEST_HOUR", 7),
        variety_days=_int("VARIETY_DAYS", 14),
        photo_repeat_days=_int("PHOTO_REPEAT_DAYS", 180),
    )


_CONFIG: Config | None = None


def get_config() -> Config:
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG


def reset() -> None:
    """Forget cached config and .env values (tests change the environment)."""
    global _CONFIG, _ENV_FILE_CACHE, _ENV_FILE_PATH
    _CONFIG = None
    _ENV_FILE_CACHE = None
    _ENV_FILE_PATH = None
