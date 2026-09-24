"""Queries for the benchmark: latest snapshot of each bank and admin overrides."""
from __future__ import annotations

from typing import Optional

import asyncpg


async def latest_services(conn: asyncpg.Connection) -> list[dict]:
    """(bank, created_at, service, path) for the latest snapshot of every bank.

    One row per method; a service without methods gives one row with path NULL.
    Hidden services/methods are excluded: the benchmark capability matrix must
    only ever match against what a human can actually see on the dev portal.
    """
    rows = await conn.fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (bank) id, bank, created_at
            FROM snapshots
            ORDER BY bank, id DESC
        )
        SELECT l.bank, l.created_at, s.name AS service, m.path
        FROM latest l
        JOIN services s ON s.snapshot_id = l.id AND s.hidden = FALSE
        LEFT JOIN methods m ON m.service_id = s.id AND m.hidden = FALSE
        ORDER BY l.bank, s.id, m.id
        """
    )
    return [dict(r) for r in rows]


async def get_overrides(conn: asyncpg.Connection) -> dict[tuple[str, str], bool]:
    rows = await conn.fetch("SELECT capability, bank, present FROM benchmark_overrides")
    return {(r["capability"], r["bank"]): r["present"] for r in rows}


async def set_override(conn: asyncpg.Connection, capability: str, bank: str, present: Optional[bool]) -> None:
    """Store an override; None removes it (the cell goes back to automatic)."""
    if present is None:
        await conn.execute(
            "DELETE FROM benchmark_overrides WHERE capability = $1 AND bank = $2", capability, bank
        )
        return
    await conn.execute(
        """
        INSERT INTO benchmark_overrides (capability, bank, present) VALUES ($1, $2, $3)
        ON CONFLICT (capability, bank) DO UPDATE SET present = EXCLUDED.present, updated_at = NOW()
        """,
        capability, bank, present,
    )
