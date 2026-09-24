"""Queries for admin-editable settings and the proxy list."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import asyncpg

from app.proxies import CheckResult

_PROXY_COLUMNS = (
    "id, url, label, expires_at, created_at, last_checked_at, last_ok, last_ip, "
    "last_country, last_latency_ms, last_error, expiry_notified_at"
)


async def get_settings(conn: asyncpg.Connection) -> dict[str, str]:
    rows = await conn.fetch("SELECT key, value FROM app_settings")
    return {r["key"]: r["value"] for r in rows}


async def put_settings(conn: asyncpg.Connection, values: dict[str, str]) -> None:
    if not values:
        return
    await conn.executemany(
        """
        INSERT INTO app_settings (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        list(values.items()),
    )


async def list_proxies(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(f"SELECT {_PROXY_COLUMNS} FROM proxies ORDER BY id")
    return [dict(r) for r in rows]


async def get_proxy(conn: asyncpg.Connection, proxy_id: int) -> Optional[dict]:
    row = await conn.fetchrow(f"SELECT {_PROXY_COLUMNS} FROM proxies WHERE id = $1", proxy_id)
    return dict(row) if row else None


class ProxyLimitError(Exception):
    def __init__(self, limit: int):
        super().__init__(f"proxy limit {limit} reached")
        self.limit = limit


async def add_proxy(
    conn: asyncpg.Connection, url: str, label: str, expires_at: Optional[datetime], limit: int
) -> Optional[dict]:
    """Insert a proxy; None when the same URL is already in the list.

    The count and the insert run under one advisory lock, so concurrent adds cannot overshoot `limit`.
    """
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('proxies_insert'))")
        if await conn.fetchval("SELECT count(*) FROM proxies") >= limit:
            raise ProxyLimitError(limit)
        row = await conn.fetchrow(
            f"""
            INSERT INTO proxies (url, label, expires_at) VALUES ($1, $2, $3)
            ON CONFLICT (url) DO NOTHING
            RETURNING {_PROXY_COLUMNS}
            """,
            url, label, expires_at,
        )
    return dict(row) if row else None


async def delete_proxy(conn: asyncpg.Connection, proxy_id: int) -> bool:
    return await conn.fetchval("DELETE FROM proxies WHERE id = $1 RETURNING id", proxy_id) is not None


async def save_check(conn: asyncpg.Connection, proxy_id: int, result: CheckResult) -> Optional[dict]:
    row = await conn.fetchrow(
        f"""
        UPDATE proxies
        SET last_checked_at = NOW(), last_ok = $2, last_ip = $3, last_country = $4,
            last_latency_ms = $5, last_error = $6
        WHERE id = $1
        RETURNING {_PROXY_COLUMNS}
        """,
        proxy_id, result.ok, result.ip, result.country, result.latency_ms, result.error,
    )
    return dict(row) if row else None


async def mark_expiry_notified(conn: asyncpg.Connection, ids: list[int]) -> None:
    if ids:
        await conn.execute(
            "UPDATE proxies SET expiry_notified_at = NOW() WHERE id = ANY($1::int[])", ids
        )
