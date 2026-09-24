"""Application configuration — reads config.yaml, then environment variables override it.

Secrets (DB password, Telegram token, site passwords) come only from the environment / .env.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, get_type_hints
from urllib.parse import quote, urlsplit

import yaml

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def _bool(value: object) -> bool:
    return str(value).strip().lower() in _TRUE


def _chat_id(value: object) -> Optional[int]:
    """Numeric Telegram chat id (groups/channels are negative); empty = not set."""
    text = str(value).strip()
    if not text:
        return None
    if not re.fullmatch(r"-?\d+", text):
        raise ValueError(f"chat id must be numeric, got {text!r}")
    return int(text)


def _base_url(value: object) -> str:
    text = str(value).strip().rstrip("/")
    if text and (urlsplit(text).scheme not in ("http", "https") or not urlsplit(text).netloc):
        raise ValueError(f"dashboard url must be http(s)://host..., got {text!r}")
    return text


@dataclass(frozen=True)
class Settings:
    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "bankmon"
    db_password: str = ""
    db_name: str = "system_monitoring"

    # Telegram: bot runs when a token is set; change notifications need telegram_notify
    telegram_bot_token: str = ""
    telegram_notify: bool = False
    telegram_chat_id: Optional[int] = None     # fixed chat/group that also gets the digest
    telegram_admin_chat: Optional[int] = None  # parse failures go only here
    dashboard_url: str = ""                    # public dashboard address for links in messages

    # Scheduler: HH:MM in Europe/Moscow
    scheduler_time: str = "10:00"

    # Snapshot import
    min_snapshot_ratio: float = 0.5
    snapshots_keep: int = 7

    # HTTP server
    host: str = "0.0.0.0"
    port: int = 8080

    # Site login: admin can parse and change settings, team only views. Empty = role disabled.
    admin_password: str = ""
    team_password: str = ""
    session_secret: str = ""   # signs session cookies; empty = random per start (everyone re-logs in)

    # Paths
    migrations_dir: str = "migrations"

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{quote(self.db_user, safe='')}:{quote(self.db_password, safe='')}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


# YAML section -> {yaml key: settings attribute}
_YAML_MAP: dict[str, dict[str, str]] = {
    "database":  {"host": "db_host", "port": "db_port", "user": "db_user", "dbname": "db_name"},
    "scheduler": {"time": "scheduler_time"},
    "dashboard": {"host": "host", "port": "port"},
    "parser":    {"min_snapshot_ratio": "min_snapshot_ratio", "snapshots_keep": "snapshots_keep"},
    "telegram":  {"notify": "telegram_notify"},
}

_ENV_MAP: dict[str, str] = {
    "DATABASE_HOST": "db_host",
    "DATABASE_PORT": "db_port",
    "DATABASE_USER": "db_user",
    "DATABASE_PASSWORD": "db_password",
    "DATABASE_DB": "db_name",
    "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
    "TELEGRAM_NOTIFY": "telegram_notify",
    "TELEGRAM_CHAT_ID": "telegram_chat_id",
    "TELEGRAM_ADMIN_CHAT": "telegram_admin_chat",
    "DASHBOARD_URL": "dashboard_url",
    "SCHEDULER_TIME": "scheduler_time",
    "MIN_SNAPSHOT_RATIO": "min_snapshot_ratio",
    "SNAPSHOTS_KEEP": "snapshots_keep",
    "DASHBOARD_HOST": "host",
    "DASHBOARD_PORT": "port",
    "ADMIN_PASSWORD": "admin_password",
    "TEAM_PASSWORD": "team_password",
    "SESSION_SECRET": "session_secret",
    "MIGRATIONS_DIR": "migrations_dir",
}

_TYPES = get_type_hints(Settings)
_CASTS = {int: int, float: float, bool: _bool, str: lambda v: str(v).strip(),
          Optional[int]: _chat_id}
_ATTR_CASTS = {"dashboard_url": _base_url}


def _cast(attr: str, value: object) -> object:
    return _ATTR_CASTS.get(attr, _CASTS[_TYPES[attr]])(value)


def _from_yaml(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {
        attr: _cast(attr, section[key])
        for name, mapping in _YAML_MAP.items()
        if isinstance(section := data.get(name), dict)
        for key, attr in mapping.items()
        if section.get(key) is not None
    }


def _from_env() -> dict[str, object]:
    return {
        attr: _cast(attr, os.environ[env])
        for env, attr in _ENV_MAP.items()
        if os.environ.get(env, "") != ""
    }


def load(config_path: str | None = None) -> Settings:
    """Build settings from YAML (path from arg, CONFIG_PATH env, or ./config.yaml) and env."""
    path = Path(config_path or os.environ.get("CONFIG_PATH") or "config.yaml")
    try:
        yaml_values = _from_yaml(path)
    except (yaml.YAMLError, ValueError, OSError) as exc:
        raise ValueError(f"Invalid config file {path}: {exc}") from exc
    try:
        env_values = _from_env()
    except ValueError as exc:
        raise ValueError(f"Invalid environment variable: {exc}") from exc
    settings = replace(Settings(), **{**yaml_values, **env_values})
    if not 0 <= settings.min_snapshot_ratio <= 1:
        raise ValueError("min_snapshot_ratio must be between 0 and 1")
    if settings.snapshots_keep < 2:
        raise ValueError("snapshots_keep must be >= 2 (the diff needs the previous snapshot)")
    if settings.admin_password and settings.admin_password == settings.team_password:
        raise ValueError("ADMIN_PASSWORD and TEAM_PASSWORD must differ")
    return settings
