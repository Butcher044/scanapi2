"""All PostgreSQL queries — uses asyncpg directly (no ORM)."""
from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg


# ── Snapshots ─────────────────────────────────────────────────────────────────

async def create_snapshot(conn: asyncpg.Connection, bank: str) -> int:
    return await conn.fetchval(
        "INSERT INTO snapshots (bank) VALUES ($1) RETURNING id", bank
    )


async def get_latest_snapshot(conn: asyncpg.Connection, bank: str) -> Optional[dict]:
    row = await conn.fetchrow(
        "SELECT id, bank, created_at FROM snapshots WHERE bank=$1 ORDER BY created_at DESC LIMIT 1",
        bank,
    )
    return dict(row) if row else None


async def get_snapshots_for_cleanup(conn: asyncpg.Connection, bank: str, keep: int) -> list[int]:
    if keep < 1:
        return []
    rows = await conn.fetch(
        "SELECT id FROM snapshots WHERE bank=$1 ORDER BY created_at DESC OFFSET $2",
        bank, keep,
    )
    return [r["id"] for r in rows]


async def delete_snapshots(conn: asyncpg.Connection, ids: list[int]) -> None:
    if ids:
        await conn.execute("DELETE FROM snapshots WHERE id = ANY($1::int[])", ids)


# ── Services ──────────────────────────────────────────────────────────────────

async def create_service(conn: asyncpg.Connection, snapshot_id: int, name: str, url: str) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO services (snapshot_id, name, url)
        VALUES ($1, $2, $3)
        ON CONFLICT (snapshot_id, name) DO NOTHING
        RETURNING id
        """,
        snapshot_id, name, url,
    )
    if row:
        return row["id"]
    # Already existed (conflict)
    return await conn.fetchval(
        "SELECT id FROM services WHERE snapshot_id=$1 AND name=$2", snapshot_id, name
    )


async def get_services(conn: asyncpg.Connection, snapshot_id: int) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id, snapshot_id, name, url FROM services WHERE snapshot_id=$1", snapshot_id
    )
    return [dict(r) for r in rows]


async def get_bank_services(conn: asyncpg.Connection, bank: str) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT s.id, s.snapshot_id, s.name, s.url
        FROM services s
        JOIN snapshots sn ON sn.id = s.snapshot_id
        WHERE sn.bank = $1
          AND sn.id = (SELECT MAX(id) FROM snapshots WHERE bank = $1)
        ORDER BY s.name
        """,
        bank,
    )
    return [dict(r) for r in rows]


# ── Methods ───────────────────────────────────────────────────────────────────

async def create_method(
    conn: asyncpg.Connection,
    service_id: int,
    name: str,
    http_method: str,
    url: str,
    description: str,
    path: str,
    request_example: dict = None,
    response_example: dict = None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO methods
            (service_id, name, http_method, url, description, path,
             request_example, response_example)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        service_id, name, http_method, url, description, path,
        json.dumps(request_example or {}),
        json.dumps(response_example or {}),
    )


async def get_methods(conn: asyncpg.Connection, service_id: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, service_id, name, http_method, COALESCE(path,'') AS path, url, description,
               COALESCE(request_example,  '{}')::text AS request_example,
               COALESCE(response_example, '{}')::text AS response_example
        FROM methods WHERE service_id=$1
        """,
        service_id,
    )
    result = []
    for r in rows:
        d = dict(r)
        d["request_example"]  = json.loads(d["request_example"]  or "{}")
        d["response_example"] = json.loads(d["response_example"] or "{}")
        result.append(d)
    return result


async def get_service_methods(conn: asyncpg.Connection, service_id: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT id, service_id, name, http_method, COALESCE(path,'') AS path, url, description,
               COALESCE(request_example,  '{}')::text AS request_example,
               COALESCE(response_example, '{}')::text AS response_example
        FROM methods WHERE service_id=$1 ORDER BY http_method, COALESCE(path, name)
        """,
        service_id,
    )
    result = []
    for r in rows:
        d = dict(r)
        d["request_example"]  = json.loads(d["request_example"]  or "{}")
        d["response_example"] = json.loads(d["response_example"] or "{}")
        result.append(d)
    return result


async def get_all_methods_for_snapshot(conn: asyncpg.Connection, snapshot_id: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT m.id, m.service_id, s.name AS service_name, m.name,
               m.http_method, COALESCE(m.path,'') AS path, m.url
        FROM methods m
        JOIN services s ON s.id = m.service_id
        WHERE s.snapshot_id = $1
        """,
        snapshot_id,
    )
    return [dict(r) for r in rows]


# ── Fields ────────────────────────────────────────────────────────────────────

async def create_field(
    conn: asyncpg.Connection,
    method_id: int,
    name: str,
    field_type: str,
    required: bool,
    description: str,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO fields (method_id, name, field_type, required, description)
        VALUES ($1, $2, $3, $4, $5) RETURNING id
        """,
        method_id, name, field_type, required, description,
    )


async def get_fields(conn: asyncpg.Connection, method_id: int) -> list[dict]:
    rows = await conn.fetch(
        "SELECT id, method_id, name, field_type, required, description FROM fields WHERE method_id=$1",
        method_id,
    )
    return [dict(r) for r in rows]


# ── Changes ───────────────────────────────────────────────────────────────────

async def create_change(conn: asyncpg.Connection, **kw: Any) -> int:
    return await conn.fetchval(
        """
        INSERT INTO changes
            (snapshot_id, bank, change_type, change_action,
             entity_name, entity_path, old_value, new_value, url)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id
        """,
        kw["snapshot_id"], kw["bank"], kw["change_type"], kw["change_action"],
        kw["entity_name"], kw["entity_path"],
        kw.get("old_value", ""), kw.get("new_value", ""), kw.get("url", ""),
    )


async def get_changes_filtered(
    conn: asyncpg.Connection,
    bank: str = "",
    change_type: str = "",
    change_action: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    conditions: list[str] = []
    args: list[Any] = []
    i = 1

    if bank:
        conditions.append(f"bank = ${i}"); args.append(bank); i += 1
    if change_type:
        conditions.append(f"change_type = ${i}"); args.append(change_type); i += 1
    if change_action:
        conditions.append(f"change_action = ${i}"); args.append(change_action); i += 1

    where = " AND ".join(conditions) if conditions else "TRUE"

    total = await conn.fetchval(f"SELECT COUNT(*) FROM changes WHERE {where}", *args)

    rows = await conn.fetch(
        f"""
        SELECT id, snapshot_id, bank, change_type, change_action,
               entity_name, entity_path,
               COALESCE(old_value,'') AS old_value,
               COALESCE(new_value,'') AS new_value,
               COALESCE(url,'') AS url, detected_at
        FROM changes WHERE {where}
        ORDER BY detected_at DESC
        LIMIT ${i} OFFSET ${i+1}
        """,
        *args, limit, offset,
    )
    return [dict(r) for r in rows], total


# ── Subscribers ───────────────────────────────────────────────────────────────

async def add_subscriber(conn: asyncpg.Connection, chat_id: int, username: str) -> None:
    await conn.execute(
        "INSERT INTO telegram_subscribers (chat_id, username) VALUES ($1,$2) ON CONFLICT (chat_id) DO NOTHING",
        chat_id, username,
    )


async def remove_subscriber(conn: asyncpg.Connection, chat_id: int) -> None:
    await conn.execute("DELETE FROM telegram_subscribers WHERE chat_id=$1", chat_id)


async def get_subscribers(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch("SELECT id, chat_id, username FROM telegram_subscribers")
    return [dict(r) for r in rows]


# ── Statistics ────────────────────────────────────────────────────────────────

async def get_stats(conn: asyncpg.Connection) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT s.bank,
               COUNT(DISTINCT sv.id) AS service_count,
               COUNT(DISTINCT m.id)  AS method_count
        FROM snapshots s
        LEFT JOIN services sv ON sv.snapshot_id = s.id
        LEFT JOIN methods m   ON m.service_id = sv.id
        WHERE s.id IN (SELECT MAX(id) FROM snapshots GROUP BY bank)
        GROUP BY s.bank
        ORDER BY s.bank
        """
    )
    return [dict(r) for r in rows]


async def get_summary(conn: asyncpg.Connection) -> dict:
    stats = await get_stats(conn)
    total_services = sum(r["service_count"] for r in stats)
    total_methods  = sum(r["method_count"] for r in stats)

    today = await conn.fetchval(
        "SELECT COUNT(*) FROM changes WHERE detected_at::date = CURRENT_DATE"
    ) or 0
    week = await conn.fetchval(
        "SELECT COUNT(*) FROM changes WHERE detected_at >= NOW() - INTERVAL '7 days'"
    ) or 0
    total_changes = await conn.fetchval("SELECT COUNT(*) FROM changes") or 0

    return {
        "banks": stats,
        "total_services": total_services,
        "total_methods": total_methods,
        "changes_today": today,
        "changes_week": week,
        "changes_total": total_changes,
    }


async def get_weekly_changes(conn: asyncpg.Connection, weeks: int = 12) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT TO_CHAR(DATE_TRUNC('week', detected_at), 'YYYY-MM-DD') AS week,
               COUNT(*) AS count, bank
        FROM changes
        WHERE detected_at >= NOW() - ($1::int * INTERVAL '1 week')
        GROUP BY week, bank
        ORDER BY week
        """,
        weeks,
    )
    return [dict(r) for r in rows]
