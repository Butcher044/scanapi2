"""Admin-editable settings (stored in app_settings) and what the parse run derives from them."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional, Protocol

import asyncpg

from app import notify_format, settings_repo
from app.proxies import expiring, usable_urls
from app.scheduler import parse_time
from bank_api_parser.proxy import ProxyRotator

logger = logging.getLogger(__name__)

KEY_TIME = "scheduler_time"
KEY_PROXY = "proxy_enabled"


@dataclass(frozen=True)
class RuntimeSettings:
    scheduler_time: str
    proxy_enabled: bool


def from_rows(rows: Mapping[str, str], default_time: str) -> RuntimeSettings:
    stored_time = rows.get(KEY_TIME, default_time)
    try:
        hour, minute = parse_time(stored_time)
        scheduler_time = f"{hour:02d}:{minute:02d}"
    except ValueError:
        logger.error("Stored scheduler_time %r is invalid, using %s", stored_time, default_time)
        scheduler_time = default_time
    return RuntimeSettings(scheduler_time=scheduler_time, proxy_enabled=rows.get(KEY_PROXY) == "true")


def to_rows(settings: RuntimeSettings) -> dict[str, str]:
    return {KEY_TIME: settings.scheduler_time, KEY_PROXY: "true" if settings.proxy_enabled else "false"}


async def load(pool: asyncpg.Pool, default_time: str) -> RuntimeSettings:
    async with pool.acquire() as conn:
        return from_rows(await settings_repo.get_settings(conn), default_time)


async def proxy_rotator(pool: asyncpg.Pool, default_time: str, now: datetime) -> Optional[ProxyRotator]:
    """Rotator over the unexpired proxies, or None for a direct connection."""
    async with pool.acquire() as conn:
        settings = from_rows(await settings_repo.get_settings(conn), default_time)
        if not settings.proxy_enabled:
            return None
        urls = usable_urls(await settings_repo.list_proxies(conn), now)
    if not urls:
        logger.warning("Proxies are enabled but none is usable: parsing directly")
        return None
    logger.info("Parsing through %d proxies", len(urls))
    return ProxyRotator(urls)


class AdminNotifier(Protocol):
    async def send_admin(self, text: str) -> None: ...


async def notify_expiring(pool: asyncpg.Pool, notifier: Optional[AdminNotifier], now: datetime) -> None:
    """One admin message about proxies that expire soon; each proxy is reported once."""
    if notifier is None:
        return
    async with pool.acquire() as conn:
        due = expiring(await settings_repo.list_proxies(conn), now)
        if not due:
            return
        await notifier.send_admin(notify_format.format_proxy_expiry(due, now))
        await settings_repo.mark_expiry_notified(conn, [r["id"] for r in due])
