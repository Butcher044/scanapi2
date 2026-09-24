"""All PostgreSQL queries — uses asyncpg directly (no ORM)."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional, Sequence

import asyncpg

from app.diff import MethodRecord

if TYPE_CHECKING:
    from app.diff import Change, SnapshotState


# ── Snapshots ─────────────────────────────────────────────────────────────────

async def create_snapshot(conn: asyncpg.Connection, bank: str) -> int:
    return await conn.fetchval(
        "INSERT INTO snapshots (bank) VALUES ($1) RETURNING id", bank
    )


async def get_latest_snapshot(conn: asyncpg.Connection, bank: str) -> Optional[dict]:
    """Базовый снимок для diff. Порядок по id, а не по created_at: created_at —
    это NOW() на начало транзакции, у двух пересекающихся импортов одного банка
    он инвертируется относительно порядка вставки. Везде, где выбирается
    «последний снимок», критерий один и тот же — максимальный id."""
    row = await conn.fetchrow(
        "SELECT id, bank, created_at FROM snapshots WHERE bank=$1 ORDER BY id DESC LIMIT 1",
        bank,
    )
    return dict(row) if row else None


async def get_snapshots_for_cleanup(conn: asyncpg.Connection, bank: str, keep: int) -> list[int]:
    """Лишние снимки банка. Порядок тот же, что в get_latest_snapshot, иначе чистка
    способна удалить как раз тот снимок, который дашборд считает текущим."""
    if keep < 1:
        return []
    rows = await conn.fetch(
        "SELECT id FROM snapshots WHERE bank=$1 ORDER BY id DESC OFFSET $2",
        bank, keep,
    )
    return [r["id"] for r in rows]


async def delete_snapshots(conn: asyncpg.Connection, ids: list[int]) -> None:
    if ids:
        await conn.execute("DELETE FROM snapshots WHERE id = ANY($1::int[])", ids)


async def get_snapshot_state(conn: asyncpg.Connection, snapshot_id: int) -> "SnapshotState":
    """Services and methods (with response field names) of a stored snapshot."""
    svc_rows = await conn.fetch(
        "SELECT name, COALESCE(url,'') AS url FROM services WHERE snapshot_id=$1", snapshot_id
    )
    method_rows = await conn.fetch(
        """
        SELECT s.name AS service, m.http_method, COALESCE(m.path,'') AS path, m.name,
               COALESCE(m.url,'') AS url, m.hidden, m.hidden_reason,
               COALESCE(array_agg(f.name) FILTER (WHERE f.name IS NOT NULL), '{}') AS fields
        FROM methods m
        JOIN services s ON s.id = m.service_id
        LEFT JOIN fields f ON f.method_id = m.id
        WHERE s.snapshot_id = $1
        GROUP BY m.id, s.name
        """,
        snapshot_id,
    )
    services = {r["name"]: r["url"] for r in svc_rows}
    methods = [
        MethodRecord(r["service"], r["http_method"], r["path"], r["name"], r["url"],
                     frozenset(r["fields"]), hidden=r["hidden"], hidden_reason=r["hidden_reason"])
        for r in method_rows
    ]
    return services, methods


# ── Services ──────────────────────────────────────────────────────────────────

async def create_service(
    conn: asyncpg.Connection, snapshot_id: int, name: str, url: str, hidden: bool = False
) -> int:
    row = await conn.fetchrow(
        """
        INSERT INTO services (snapshot_id, name, url, hidden)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (snapshot_id, name) DO UPDATE
            SET url = EXCLUDED.url, hidden = EXCLUDED.hidden
        RETURNING id
        """,
        snapshot_id, name, url, hidden,
    )
    if row:
        return row["id"]
    # Already existed (conflict)
    return await conn.fetchval(
        "SELECT id FROM services WHERE snapshot_id=$1 AND name=$2", snapshot_id, name
    )


async def get_bank_services(
    conn: asyncpg.Connection, bank: str, include_hidden: bool = False
) -> list[dict]:
    """Services of a bank's latest snapshot. Hidden ones are excluded by default —
    the public dashboard must never show them; the admin tab opts in explicitly."""
    query = """
        SELECT s.id, s.snapshot_id, s.name, s.url, s.hidden
        FROM services s
        JOIN snapshots sn ON sn.id = s.snapshot_id
        WHERE sn.bank = $1
          AND sn.id = (SELECT MAX(id) FROM snapshots WHERE bank = $1)
    """
    if not include_hidden:
        query += " AND s.hidden = FALSE"
    query += " ORDER BY s.name"
    rows = await conn.fetch(query, bank)
    return [dict(r) for r in rows]


async def get_hidden_services(conn: asyncpg.Connection, bank: str) -> list[dict]:
    """Hidden services of a bank's latest snapshot — for the admin tab."""
    rows = await conn.fetch(
        """
        SELECT s.id, s.snapshot_id, s.name, s.url
        FROM services s
        JOIN snapshots sn ON sn.id = s.snapshot_id
        WHERE sn.bank = $1
          AND sn.id = (SELECT MAX(id) FROM snapshots WHERE bank = $1)
          AND s.hidden = TRUE
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
    request_example: Optional[dict] = None,
    response_example: Optional[dict] = None,
    hidden: bool = False,
    hidden_reason: Optional[str] = None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO methods
            (service_id, name, http_method, url, description, path,
             request_example, response_example, hidden, hidden_reason)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING id
        """,
        service_id, name, http_method, url, description, path,
        json.dumps(request_example or {}),
        json.dumps(response_example or {}),
        hidden, hidden_reason,
    )


async def get_service_methods(
    conn: asyncpg.Connection, service_id: int, include_hidden: bool = False
) -> list[dict]:
    """Methods of a service. Hidden ones are excluded by default — the public
    dashboard must never show them; the admin tab opts in explicitly."""
    query = """
        SELECT id, service_id, name, http_method, COALESCE(path,'') AS path, url, description,
               hidden, hidden_reason,
               COALESCE(request_example,  '{}')::text AS request_example,
               COALESCE(response_example, '{}')::text AS response_example
        FROM methods WHERE service_id=$1
    """
    if not include_hidden:
        query += " AND hidden = FALSE"
    query += " ORDER BY http_method, COALESCE(path, name)"
    rows = await conn.fetch(query, service_id)
    result = []
    for r in rows:
        d = dict(r)
        d["request_example"]  = json.loads(d["request_example"]  or "{}")
        d["response_example"] = json.loads(d["response_example"] or "{}")
        result.append(d)
    return result


async def get_hidden_methods(conn: asyncpg.Connection, service_id: int) -> list[dict]:
    """Hidden methods of a service — for the admin tab."""
    rows = await conn.fetch(
        """
        SELECT id, service_id, name, http_method, COALESCE(path,'') AS path, url, description,
               hidden, hidden_reason,
               COALESCE(request_example,  '{}')::text AS request_example,
               COALESCE(response_example, '{}')::text AS response_example
        FROM methods WHERE service_id=$1 AND hidden = TRUE
        ORDER BY http_method, COALESCE(path, name)
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


# ── Fields ────────────────────────────────────────────────────────────────────

async def create_fields(conn: asyncpg.Connection, method_id: int, names: list[str]) -> None:
    if names:
        await conn.executemany(
            "INSERT INTO fields (method_id, name, field_type, required, description) "
            "VALUES ($1, $2, 'string', FALSE, '')",
            [(method_id, n) for n in names],
        )


# ── Changes ───────────────────────────────────────────────────────────────────

async def create_changes(
    conn: asyncpg.Connection, snapshot_id: int, bank: str, changes: Sequence["Change"]
) -> None:
    if not changes:
        return
    await conn.executemany(
        """
        INSERT INTO changes
            (snapshot_id, bank, change_type, change_action,
             entity_name, entity_path, old_value, new_value, url, hidden)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        """,
        [
            (snapshot_id, bank, c.change_type, c.action, c.entity_name,
             c.entity_path, c.old_value, c.new_value, c.url, c.hidden)
            for c in changes
        ],
    )


async def get_changes_filtered(
    conn: asyncpg.Connection,
    bank: str = "",
    change_type: str = "",
    change_action: str = "",
    limit: int = 50,
    offset: int = 0,
    include_hidden: bool = False,
) -> tuple[list[dict], int]:
    """Changes history. Hidden ones (about hidden methods/services) are excluded by
    default — they must never reach the public dashboard, history or Telegram."""
    conditions: list[str] = []
    args: list[Any] = []
    i = 1

    if bank:
        conditions.append(f"bank = ${i}"); args.append(bank); i += 1
    if change_type:
        conditions.append(f"change_type = ${i}"); args.append(change_type); i += 1
    if change_action:
        conditions.append(f"change_action = ${i}"); args.append(change_action); i += 1
    if not include_hidden:
        conditions.append("hidden = FALSE")

    where = " AND ".join(conditions) if conditions else "TRUE"

    total = await conn.fetchval(f"SELECT COUNT(*) FROM changes WHERE {where}", *args)

    rows = await conn.fetch(
        f"""
        SELECT id, snapshot_id, bank, change_type, change_action,
               entity_name, entity_path,
               COALESCE(old_value,'') AS old_value,
               COALESCE(new_value,'') AS new_value,
               COALESCE(url,'') AS url, detected_at, hidden
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

async def get_stats(conn: asyncpg.Connection, include_hidden: bool = False) -> list[dict]:
    """Per-bank service/method counts of the latest snapshot. Hidden services and
    methods are excluded by default so the public dashboard never counts them."""
    svc_filter = "" if include_hidden else " AND sv.hidden = FALSE"
    method_filter = "" if include_hidden else " AND m.hidden = FALSE"
    rows = await conn.fetch(
        f"""
        SELECT s.bank,
               COUNT(DISTINCT sv.id) AS service_count,
               COUNT(DISTINCT m.id)  AS method_count
        FROM snapshots s
        LEFT JOIN services sv ON sv.snapshot_id = s.id{svc_filter}
        LEFT JOIN methods m   ON m.service_id = sv.id{method_filter}
        WHERE s.id IN (SELECT MAX(id) FROM snapshots GROUP BY bank)
        GROUP BY s.bank
        ORDER BY s.bank
        """
    )
    return [dict(r) for r in rows]


async def get_summary(conn: asyncpg.Connection, include_hidden: bool = False) -> dict:
    stats = await get_stats(conn, include_hidden=include_hidden)
    total_services = sum(r["service_count"] for r in stats)
    total_methods  = sum(r["method_count"] for r in stats)

    hidden_clause = "" if include_hidden else " AND hidden = FALSE"
    today = await conn.fetchval(
        # Range on the raw column (not a function of it) so idx_changes_detected is usable
        "SELECT COUNT(*) FROM changes "
        "WHERE detected_at >= date_trunc('day', NOW() AT TIME ZONE 'Europe/Moscow') "
        "AT TIME ZONE 'Europe/Moscow'" + hidden_clause
    ) or 0
    week = await conn.fetchval(
        "SELECT COUNT(*) FROM changes WHERE detected_at >= NOW() - INTERVAL '7 days'" + hidden_clause
    ) or 0
    total_changes = await conn.fetchval("SELECT COUNT(*) FROM changes" + (
        "" if include_hidden else " WHERE hidden = FALSE"
    )) or 0

    return {
        "banks": stats,
        "total_services": total_services,
        "total_methods": total_methods,
        "changes_today": today,
        "changes_week": week,
        "changes_total": total_changes,
    }


# ── Hidden summary (admin tab) ─────────────────────────────────────────────────

async def get_hidden_summary(conn: asyncpg.Connection) -> list[dict]:
    """Per bank: hidden service/method counts of the latest snapshot, plus a
    breakdown of hidden methods by hidden_reason — feeds the admin "hidden" tab."""
    totals = await conn.fetch(
        """
        WITH latest AS (
            SELECT id, bank FROM snapshots WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY bank)
        )
        SELECT l.bank,
               COUNT(DISTINCT s.id) FILTER (WHERE s.hidden) AS hidden_services,
               COUNT(DISTINCT m.id) FILTER (WHERE m.hidden) AS hidden_methods
        FROM latest l
        LEFT JOIN services s ON s.snapshot_id = l.id
        LEFT JOIN methods m  ON m.service_id = s.id
        GROUP BY l.bank
        ORDER BY l.bank
        """
    )
    by_reason = await conn.fetch(
        """
        WITH latest AS (
            SELECT id, bank FROM snapshots WHERE id IN (SELECT MAX(id) FROM snapshots GROUP BY bank)
        )
        SELECT l.bank, m.hidden_reason, COUNT(*) AS cnt
        FROM latest l
        JOIN services s ON s.snapshot_id = l.id
        JOIN methods m  ON m.service_id = s.id
        WHERE m.hidden
        GROUP BY l.bank, m.hidden_reason
        """
    )
    reasons: dict[str, dict[str, int]] = {}
    for r in by_reason:
        reasons.setdefault(r["bank"], {})[r["hidden_reason"]] = r["cnt"]

    return [
        {
            "bank": r["bank"],
            "hidden_services": r["hidden_services"],
            "hidden_methods": r["hidden_methods"],
            "by_reason": reasons.get(r["bank"], {}),
        }
        for r in totals
    ]
