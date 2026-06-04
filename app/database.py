"""asyncpg connection pool + database migrations."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def create_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=15,
        command_timeout=60,
    )
    logger.info("Database pool created")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized")
    return _pool


async def run_migrations(pool: asyncpg.Pool, migrations_dir: str = "migrations") -> None:
    """Apply pending SQL migrations (supports goose-style Up/Down markers)."""
    async with pool.acquire() as conn:
        # Ensure our migration tracking table exists with correct schema.
        # The old Go/goose setup may have left a schema_migrations table with
        # a different column layout — detect and recreate if needed.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    VARCHAR(255) PRIMARY KEY,
                applied_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Check if 'version' column exists (vs old 'version_id' from goose)
        col_ok = await conn.fetchval("""
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name   = 'schema_migrations'
              AND column_name  = 'version'
        """)
        if not col_ok:
            logger.warning("schema_migrations has wrong schema (old goose table?) — recreating")
            await conn.execute("DROP TABLE schema_migrations")
            await conn.execute("""
                CREATE TABLE schema_migrations (
                    version    VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

        applied: set[str] = {
            row["version"]
            for row in await conn.fetch("SELECT version FROM schema_migrations")
        }

        sql_files = sorted(Path(migrations_dir).glob("*.sql"))
        if not sql_files:
            logger.warning("No migration files found in %s", migrations_dir)
            return

        for sql_file in sql_files:
            version = sql_file.stem
            if version in applied:
                continue

            content = sql_file.read_text(encoding="utf-8")

            # Extract the "Up" section (goose format)
            if "-- +goose Up" in content:
                up_part = content.split("-- +goose Up", 1)[1]
                if "-- +goose Down" in up_part:
                    up_part = up_part.split("-- +goose Down", 1)[0]
                sql = up_part.strip()
            else:
                sql = content

            # Strip goose/comment-only lines
            sql = "\n".join(
                line for line in sql.splitlines()
                if not line.strip().startswith("--") or line.strip() == ""
            ).strip()

            if not sql:
                continue

            try:
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", version
                )
                logger.info("Migration applied: %s", version)
            except Exception as exc:
                logger.error("Migration failed: %s — %s", version, exc)
                raise
