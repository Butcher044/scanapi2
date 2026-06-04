"""
FastAPI application.

Startup order:
  1. Connect to PostgreSQL (asyncpg pool)
  2. Run SQL migrations
  3. Init Telegram bot (if token configured)
  4. Init parser runner
  5. Start APScheduler
  6. Serve API + React SPA

All /api/* routes are handled inline here.
Everything else is served from frontend/dist/ (React SPA).
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config as cfg_module
from app import database, repository as repo
from app.parser_runner import ParserRunner, BANK_KEYS
from app.scheduler import Scheduler
from app.telegram_bot import TelegramBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Loaded once at import time
settings = cfg_module.load()

# Global singletons (set during lifespan)
_bot: Optional[TelegramBot] = None
_runner: Optional[ParserRunner] = None
_scheduler: Optional[Scheduler] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bot, _runner, _scheduler

    # ── Startup ───────────────────────────────────────────────────────────────
    pool = await database.create_pool(settings.db_dsn)
    await database.run_migrations(pool, settings.migrations_dir)
    logger.info("DB migrations OK")

    if settings.telegram_bot_token:
        _bot = TelegramBot(settings.telegram_bot_token, pool)
        asyncio.create_task(_bot.start())
        logger.info("Telegram bot started")
    else:
        logger.info("Telegram bot disabled (no token)")

    _runner = ParserRunner(pool, _bot)

    _scheduler = Scheduler(_runner, settings.scheduler_time)
    _scheduler.start()

    # Immediate parse if env var set
    if os.environ.get("RUN_NOW", "").lower() in ("1", "true", "yes"):
        logger.info("RUN_NOW=true — running parse immediately")
        asyncio.create_task(_runner.run_all())

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    if _scheduler:
        _scheduler.stop()
    if _bot:
        await _bot.stop()
    await database.close_pool()


app = FastAPI(
    title="Bank API Monitor",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

BANK_LABELS = {
    "tbank":    "Т-Банк",
    "alfabank": "Альфа-Банк",
    "sber":     "Сбер",
    "tochka":   "Точка",
}


def _bank_label(bank: str) -> str:
    return BANK_LABELS.get(bank, bank)


def _pool():
    return database.get_pool()


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/api/summary")
async def api_summary():
    async with _pool().acquire() as conn:
        data = await repo.get_summary(conn)

    banks = [
        {
            "name":     b["bank"],
            "label":    _bank_label(b["bank"]),
            "services": b["service_count"],
            "methods":  b["method_count"],
        }
        for b in data["banks"]
    ]
    return {
        "banks":           banks,
        "total_services":  data["total_services"],
        "total_methods":   data["total_methods"],
        "changes_today":   data["changes_today"],
        "changes_week":    data["changes_week"],
        "changes_total":   data["changes_total"],
    }


@app.get("/api/stats")
async def api_stats():
    async with _pool().acquire() as conn:
        stats = await repo.get_stats(conn)
    banks = [
        {"name": s["bank"], "label": _bank_label(s["bank"]),
         "services": s["service_count"], "methods": s["method_count"]}
        for s in stats
    ]
    return {"banks": banks}


@app.get("/api/changes")
async def api_changes(
    bank:   str = Query(""),
    type:   str = Query(""),
    action: str = Query(""),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    async with _pool().acquire() as conn:
        rows, total = await repo.get_changes_filtered(
            conn, bank=bank, change_type=type, change_action=action,
            limit=limit, offset=offset,
        )

    changes = []
    for c in rows:
        detected_at = c["detected_at"]
        if detected_at:
            detected_at = detected_at.strftime("%Y-%m-%d %H:%M")
        changes.append({
            "id":          c["id"],
            "bank":        c["bank"],
            "bank_label":  _bank_label(c["bank"]),
            "type":        c["change_type"],
            "action":      c["change_action"],
            "entity":      c["entity_name"],
            "path":        c["entity_path"],
            "old_value":   c["old_value"],
            "new_value":   c["new_value"],
            "url":         c["url"],
            "detected_at": detected_at or "—",
        })

    return {"changes": changes, "total": total, "limit": limit, "offset": offset}


@app.get("/api/dynamics")
async def api_dynamics(weeks: int = Query(12, ge=1, le=52)):
    async with _pool().acquire() as conn:
        rows = await repo.get_weekly_changes(conn, weeks)
    dynamics = [
        {"week": r["week"], "count": r["count"],
         "bank": r["bank"], "label": _bank_label(r["bank"])}
        for r in rows
    ]
    return {"dynamics": dynamics}


@app.get("/api/services")
async def api_services(bank: str = Query(..., description="Bank key")):
    async with _pool().acquire() as conn:
        services = await repo.get_bank_services(conn, bank)
    return {
        "services": [
            {"id": s["id"], "name": s["name"], "url": s["url"]}
            for s in services
        ]
    }


@app.get("/api/methods")
async def api_methods(service_id: int = Query(...)):
    async with _pool().acquire() as conn:
        methods = await repo.get_service_methods(conn, service_id)
    return {
        "methods": [
            {
                "id":               m["id"],
                "name":             m["name"],
                "http_method":      m["http_method"],
                "path":             m["path"],
                "url":              m["url"],
                "request_example":  m.get("request_example", {}),
                "response_example": m.get("response_example", {}),
            }
            for m in methods
        ]
    }


@app.get("/api/fields")
async def api_fields(method_id: int = Query(...)):
    async with _pool().acquire() as conn:
        fields = await repo.get_fields(conn, method_id)
    return {
        "fields": [
            {"id": f["id"], "name": f["name"],
             "type": f["field_type"], "required": f["required"]}
            for f in fields
        ]
    }


@app.post("/api/parse")
async def api_parse_now():
    """Trigger immediate parse of all banks in the background."""
    if _runner is None:
        raise HTTPException(status_code=503, detail="Runner not ready")
    if _runner.status.running:
        return {"status": "already_running", "banks": list(BANK_KEYS)}
    asyncio.create_task(_runner.run_all())
    return {"status": "started", "banks": list(BANK_KEYS)}


@app.get("/api/parse/status")
async def api_parse_status():
    """Return current parse status (per-bank progress)."""
    if _runner is None:
        return {"running": False, "banks": {}}
    return _runner.status.to_dict()


# ── React SPA static serving ──────────────────────────────────────────────────

_DIST = Path("frontend/dist")

if (_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    """Serve exact static files or fall back to index.html for SPA routing."""
    # Try exact file match
    candidate = _DIST / full_path
    if candidate.exists() and candidate.is_file():
        return FileResponse(str(candidate))
    # SPA fallback
    index = _DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse(
        {"detail": "Frontend not built — run: cd frontend && npm install && npm run build"},
        status_code=404,
    )
