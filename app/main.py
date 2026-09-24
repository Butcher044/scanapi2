"""
FastAPI application.

Startup order:
  1. Connect to PostgreSQL (asyncpg pool)
  2. Run SQL migrations
  3. Init Telegram bot (if token configured)
  4. Init parser runner
  5. Start APScheduler (parse time from the DB, set by the admin)
  6. Serve API + React SPA

Every /api/* route except login/logout needs a session cookie (app.web_auth);
parsing and settings are admin-only (app.admin_api). Everything else is served
from frontend/dist/ (React SPA) — the SPA shows the login form itself.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config as cfg_module
from app import admin_api, benchmark_api, database, hidden_api, repository as repo, runtime_settings, web_auth
from app.auth import Auth, LoginLimiter
from app.banks import BANK_KEYS, bank_label
from app.parser_runner import ParserRunner
from app.scheduler import Scheduler
from app.telegram_bot import TelegramBot
from app.web_auth import require_admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
# httpx logs every request URL at INFO — Telegram URLs contain the bot token
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# Loaded once at import time
settings = cfg_module.load()

PROXY_EXPIRY_CHECK_TIME = "09:00"   # MSK, daily admin reminder about expiring proxies


def _build_auth() -> Auth:
    if not settings.admin_password:
        logger.warning("ADMIN_PASSWORD is not set: nobody can log in as admin")
    if not settings.team_password:
        logger.info("TEAM_PASSWORD is not set: the team (read-only) login is disabled")
    secret = settings.session_secret.encode()
    if not secret:
        logger.warning("SESSION_SECRET is not set: sessions end on every restart")
        secret = secrets.token_bytes(32)
    return Auth({"admin": settings.admin_password, "team": settings.team_password}, secret)

# Keep references to background tasks so they are not garbage-collected mid-run
_tasks: set[asyncio.Task] = set()


def _on_task_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("Background task %s failed", task.get_name(), exc_info=task.exception())


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_on_task_done)


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
        _bot = TelegramBot(
            settings.telegram_bot_token, pool,
            fixed_chat_id=settings.telegram_chat_id,
            admin_chat_id=settings.telegram_admin_chat,
            status_provider=lambda: _runner.status if _runner else None,
        )
        _spawn(_bot.start())
        logger.info("Telegram bot started")
    else:
        logger.info("Telegram bot disabled (no token)")

    _runner = ParserRunner(
        pool,
        _bot if settings.telegram_notify else None,
        min_snapshot_ratio=settings.min_snapshot_ratio,
        snapshots_keep=settings.snapshots_keep,
        dashboard_url=settings.dashboard_url,
        proxy_source=lambda: runtime_settings.proxy_rotator(
            pool, settings.scheduler_time, datetime.now(timezone.utc)),
    )
    if settings.telegram_notify and not _bot:
        logger.warning("TELEGRAM_NOTIFY=true but TELEGRAM_BOT_TOKEN is empty: nothing will be sent")
    if settings.telegram_notify and _bot and settings.telegram_admin_chat is None:
        logger.warning("TELEGRAM_ADMIN_CHAT is not set: parse failure alerts will only be logged")
    logger.info("Telegram notifications %s", "enabled" if settings.telegram_notify and _bot else "disabled")

    stored = await runtime_settings.load(pool, settings.scheduler_time)
    _scheduler = Scheduler(_runner, stored.scheduler_time)

    async def _proxy_expiry_job() -> None:   # APScheduler needs a real coroutine function
        try:
            await runtime_settings.notify_expiring(pool, _bot, datetime.now(timezone.utc))
        except Exception:
            logger.exception("Proxy expiry check failed")

    _scheduler.add_daily("proxy_expiry", _proxy_expiry_job, PROXY_EXPIRY_CHECK_TIME)
    _scheduler.start()
    app.state.scheduler = _scheduler

    # Immediate parse if env var set
    if os.environ.get("RUN_NOW", "").lower() in ("1", "true", "yes"):
        logger.info("RUN_NOW=true — running parse immediately")
        _spawn(_runner.run_all())

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
    openapi_url="/api/openapi.json",
    redoc_url=None,
)
app.state.auth = _build_auth()
app.state.limiter = LoginLimiter()
app.state.default_time = settings.scheduler_time
app.state.scheduler = None
app.include_router(web_auth.router)
app.include_router(admin_api.router)
app.include_router(benchmark_api.router)
app.include_router(hidden_api.router)
# Registered before _security_headers, so it runs inside it: 401s get the headers too.
app.middleware("http")(web_auth.auth_middleware)

# SPA assets are same-origin; fonts come from Google Fonts. Swagger UI (/api/docs)
# loads its bundle from a CDN, so it is left without CSP.
_CSP = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    # Not covered by default-src: without it a single injected <base> tag would
    # re-point every relative URL on the page at someone else's host.
    "base-uri 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if not request.url.path.startswith("/api/docs"):
        response.headers["Content-Security-Policy"] = _CSP
    return response


# ── Helpers ───────────────────────────────────────────────────────────────────

MSK = ZoneInfo("Europe/Moscow")


def _fmt_msk(dt: Optional[datetime]) -> str:
    return dt.astimezone(MSK).strftime("%Y-%m-%d %H:%M") if dt else "—"


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
            "label":    bank_label(b["bank"]),
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


@app.get("/api/changes")
async def api_changes(
    bank:   str = Query(""),
    type:   str = Query(""),
    action: str = Query(""),
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0, le=1_000_000),
):
    async with _pool().acquire() as conn:
        rows, total = await repo.get_changes_filtered(
            conn, bank=bank, change_type=type, change_action=action,
            limit=limit, offset=offset,
        )

    changes = []
    for c in rows:
        changes.append({
            "id":          c["id"],
            "bank":        c["bank"],
            "bank_label":  bank_label(c["bank"]),
            "type":        c["change_type"],
            "action":      c["change_action"],
            "entity":      c["entity_name"],
            "path":        c["entity_path"],
            "old_value":   c["old_value"],
            "new_value":   c["new_value"],
            "url":         c["url"],
            "detected_at": _fmt_msk(c["detected_at"]),
        })

    return {"changes": changes, "total": total, "limit": limit, "offset": offset}


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


@app.post("/api/parse", dependencies=[Depends(require_admin)])
async def api_parse_now():
    """Trigger immediate parse of all banks in the background."""
    if _runner is None:
        raise HTTPException(status_code=503, detail="Runner not ready")
    if _runner.status.running:
        return {"status": "already_running", "banks": list(BANK_KEYS)}
    _spawn(_runner.run_all())
    return {"status": "started", "banks": list(BANK_KEYS)}


@app.get("/api/health", include_in_schema=False)
async def api_health():
    """Liveness probe for the Docker healthcheck; public, reveals nothing."""
    return {"ok": True}


@app.get("/api/parse/status")
async def api_parse_status():
    """Return current parse status (per-bank progress)."""
    if _runner is None:
        return {"running": False, "banks": {}}
    return _runner.status.to_dict()


# ── React SPA static serving ──────────────────────────────────────────────────

_DIST = Path("frontend/dist").resolve()

if (_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    """Serve exact static files inside dist/ or fall back to index.html for SPA routing."""
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    candidate = (_DIST / full_path).resolve()
    if candidate.is_relative_to(_DIST) and candidate.is_file():
        return FileResponse(str(candidate))
    index = _DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse(
        {"detail": "Frontend not built — run: cd frontend && npm install && npm run build"},
        status_code=404,
    )
