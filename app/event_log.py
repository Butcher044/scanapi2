"""Human-readable event journal behind the admin "Логи" tab.

Every component that does something the admin cares about (parser runs, the
schedule firing, Telegram deliveries, proxy and settings changes) writes a short
Russian sentence here. Writing must never break the caller: a failed insert is
only logged to the server log.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from typing import Optional, Protocol

import asyncpg

logger = logging.getLogger(__name__)

LEVELS = ("info", "success", "warning", "error")
CATEGORIES = ("parser", "schedule", "telegram", "proxy", "settings", "system")
KEEP_DAYS = 30
MAX_DETAILS = 20_000
MAX_MESSAGE = 1_000

# scheme://user:password@host -> scheme://***@host (proxy URLs end up in error texts)
_CREDENTIALS = re.compile(r"(\w+://)[^/\s:@]+:[^/\s@]+@")
_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Event:
    level: str
    category: str
    message: str
    details: Optional[str] = None


class EventSink(Protocol):
    async def record(self, level: str, category: str, message: str,
                     details: Optional[str] = None) -> None: ...


class NullEventLog:
    """Used before the DB is up and in tests that don't care about events."""

    async def record(self, level: str, category: str, message: str,
                     details: Optional[str] = None) -> None:
        return None


NULL_EVENTS = NullEventLog()


class EventLog:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def record(self, level: str, category: str, message: str,
                     details: Optional[str] = None) -> None:
        try:
            async with self._pool.acquire() as conn:
                await insert_event(conn, level, category, message, details)
        except Exception as exc:   # the journal is a side channel: never fail the caller
            logger.warning("Could not write event %r: %s", message, exc)


# ── Wording helpers ───────────────────────────────────────────────────────────

def scrub(text: str) -> str:
    return _CREDENTIALS.sub(r"\1***@", text)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def strip_html(text: str) -> str:
    """Telegram HTML -> the plain text the reader actually saw."""
    return html.unescape(_TAG.sub("", text)).strip()


def count(n: int, one: str, few: str, many: str) -> str:
    """count(3, "метод", "метода", "методов") -> "3 метода"."""
    tail = n % 100
    if 11 <= tail <= 14:
        form = many
    elif n % 10 == 1:
        form = one
    elif 2 <= n % 10 <= 4:
        form = few
    else:
        form = many
    return f"{n} {form}"


def fmt_duration(seconds: float) -> str:
    total = int(round(seconds))
    if seconds < 1:
        return "меньше секунды"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    if minutes:
        return f"{minutes} мин {secs} с" if secs else f"{minutes} мин"
    return f"{secs} с"


def describe_error(exc: BaseException) -> str:
    """Technical detail for the admin: exception type and (scrubbed) message."""
    try:
        text = str(exc).strip()
    except Exception:   # a broken __str__ must not break the caller's error path
        return type(exc).__name__
    return scrub(f"{type(exc).__name__}: {text}" if text else type(exc).__name__)


# ── Queries ───────────────────────────────────────────────────────────────────

async def insert_event(conn: asyncpg.Connection, level: str, category: str,
                       message: str, details: Optional[str] = None) -> None:
    if level not in LEVELS or category not in CATEGORIES:
        raise ValueError(f"unknown event level/category: {level}/{category}")
    await conn.execute(
        "INSERT INTO event_log (level, category, message, details) VALUES ($1, $2, $3, $4)",
        level, category,
        _clip(scrub(message), MAX_MESSAGE),
        _clip(scrub(details), MAX_DETAILS) if details else None,
    )


async def list_events(conn: asyncpg.Connection, *, level: Optional[str] = None,
                      category: Optional[str] = None, before_id: Optional[int] = None,
                      limit: int = 100) -> list[dict]:
    """Newest first; filters are optional and always passed as parameters."""
    conditions, args = [], []
    for column, value in (("level", level), ("category", category)):
        if value is not None:
            args.append(value)
            conditions.append(f"{column} = ${len(args)}")
    if before_id is not None:
        args.append(before_id)
        conditions.append(f"id < ${len(args)}")
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    args.append(limit)
    rows = await conn.fetch(
        "SELECT id, created_at, level, category, message, details FROM event_log"
        f"{where} ORDER BY id DESC LIMIT ${len(args)}",
        *args,
    )
    return [dict(r) for r in rows]


async def prune(conn: asyncpg.Connection, keep_days: int = KEEP_DAYS) -> int:
    status = await conn.execute(
        "DELETE FROM event_log WHERE created_at < NOW() - make_interval(days => $1)", keep_days,
    )
    return int(status.split()[-1]) if status else 0
