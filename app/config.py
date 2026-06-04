"""Application configuration — reads from config.yaml then overrides with env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Settings:
    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "user"
    db_password: str = "1111"
    db_name: str = "system_monitoring"
    db_ssl: str = "disable"

    # Telegram
    telegram_bot_token: str = ""

    # Scheduler: HH:MM in Europe/Moscow
    scheduler_time: str = "10:00"

    # HTTP server
    host: str = "0.0.0.0"
    port: int = 8080

    # Paths
    migrations_dir: str = "migrations"
    parser_dir: str = "bank_api_parser"
    frontend_dir: str = "frontend/dist"

    @property
    def db_dsn(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


def load(config_path: str = "config.yaml") -> Settings:
    s = Settings()

    # 1. Read YAML (optional)
    path = Path(config_path)
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text()) or {}
            if db := data.get("database", {}):
                s.db_host = db.get("host", s.db_host)
                s.db_port = int(db.get("port", s.db_port))
                s.db_user = db.get("user", s.db_user)
                s.db_password = str(db.get("password", s.db_password))
                s.db_name = db.get("dbname", s.db_name)
                s.db_ssl = db.get("sslmode", s.db_ssl)
            # Telegram token is intentionally NOT read from YAML.
            # Set TELEGRAM_BOT_TOKEN in .env or as an environment variable.
            if sched := data.get("scheduler", {}):
                s.scheduler_time = sched.get("time", s.scheduler_time)
            if dash := data.get("dashboard", {}):
                s.host = dash.get("host", s.host)
                s.port = int(dash.get("port", s.port))
        except Exception as exc:
            print(f"[config] YAML parse error: {exc}")

    # 2. Environment variables override YAML
    _env = {
        "DATABASE_HOST": ("db_host", str),
        "DATABASE_PORT": ("db_port", int),
        "DATABASE_USER": ("db_user", str),
        "DATABASE_PASSWORD": ("db_password", str),
        "DATABASE_DB": ("db_name", str),
        "TELEGRAM_BOT_TOKEN": ("telegram_bot_token", str),
        "SCHEDULER_TIME": ("scheduler_time", str),
        "DASHBOARD_HOST": ("host", str),
        "DASHBOARD_PORT": ("port", int),
        "MIGRATIONS_DIR": ("migrations_dir", str),
    }
    for env_key, (attr, typ) in _env.items():
        if val := os.environ.get(env_key):
            setattr(s, attr, typ(val))

    return s
