"""Admin-only API: daily parse time, proxy on/off, proxy list with expiry and health checks."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from app import database, proxies, runtime_settings, settings_repo
from app.runtime_settings import RuntimeSettings
from app.scheduler import Scheduler, parse_time
from app.web_auth import require_admin
from bank_api_parser.proxy import mask

logger = logging.getLogger(__name__)

MSK = ZoneInfo("Europe/Moscow")
DEFAULT_DAYS = 30
MAX_PROXIES = 100
CHECK_CONCURRENCY = 8

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[Depends(require_admin)])


def _scheduler(request: Request) -> Scheduler:
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not ready")
    return scheduler


def _msk(dt: Optional[datetime], fmt: str) -> Optional[str]:
    return dt.astimezone(MSK).strftime(fmt) if dt else None


# ── Settings ──────────────────────────────────────────────────────────────────

class SettingsPatch(BaseModel):
    scheduler_time: Optional[str] = Field(default=None, max_length=5)
    proxy_enabled: Optional[bool] = None

    @field_validator("scheduler_time")
    @classmethod
    def _valid_time(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        hour, minute = parse_time(value)
        return f"{hour:02d}:{minute:02d}"


def _settings_view(settings: RuntimeSettings, scheduler: Scheduler) -> dict:
    return {
        "scheduler_time": settings.scheduler_time,
        "proxy_enabled":  settings.proxy_enabled,
        "next_run":       _msk(scheduler.next_run(), "%d.%m, %H:%M"),
    }


@router.get("/settings")
async def get_settings(request: Request) -> dict:
    current = await runtime_settings.load(database.get_pool(), request.app.state.default_time)
    return _settings_view(current, _scheduler(request))


@router.put("/settings")
async def put_settings(patch: SettingsPatch, request: Request) -> dict:
    scheduler = _scheduler(request)
    pool = database.get_pool()
    current = await runtime_settings.load(pool, request.app.state.default_time)
    updated = RuntimeSettings(
        scheduler_time=patch.scheduler_time or current.scheduler_time,
        proxy_enabled=current.proxy_enabled if patch.proxy_enabled is None else patch.proxy_enabled,
    )
    async with pool.acquire() as conn:
        await settings_repo.put_settings(conn, runtime_settings.to_rows(updated))
    if updated.scheduler_time != scheduler.time:
        scheduler.reschedule(updated.scheduler_time)
    return _settings_view(updated, scheduler)


# ── Proxies ───────────────────────────────────────────────────────────────────

class ProxyIn(BaseModel):
    url: str = Field(max_length=proxies.MAX_URL_LENGTH)
    label: str = Field(default="", max_length=100)
    days: Optional[int] = Field(default=None, ge=1, le=3650)
    expires_on: Optional[date] = None

    @field_validator("url")
    @classmethod
    def _valid_url(cls, value: str) -> str:
        return proxies.validate_url(value)

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def _one_expiry(self) -> "ProxyIn":
        if self.days is not None and self.expires_on is not None:
            raise ValueError("укажите либо количество дней, либо дату")
        if self.expires_on is not None and self.expires_on < datetime.now(MSK).date():
            raise ValueError("дата окончания уже прошла")
        return self

    def expires_at(self, now: datetime) -> datetime:
        if self.expires_on is not None:   # valid through the whole day, Moscow time
            return datetime.combine(self.expires_on, time(23, 59, 59), MSK)
        return now + timedelta(days=self.days or DEFAULT_DAYS)


def _proxy_view(row: Mapping, now: datetime) -> dict:
    return {
        "id":              row["id"],
        "url":             mask(row["url"]),
        "label":           row["label"],
        "expires_at":      _msk(row["expires_at"], "%d.%m.%Y"),
        "days_left":       proxies.days_left(row["expires_at"], now),
        "last_checked_at": _msk(row["last_checked_at"], "%d.%m %H:%M"),
        "last_ok":         row["last_ok"],
        "last_ip":         row["last_ip"],
        "last_country":    row["last_country"],
        "last_latency_ms": row["last_latency_ms"],
        "last_error":      row["last_error"],
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/proxies")
async def list_proxies() -> dict:
    async with database.get_pool().acquire() as conn:
        rows = await settings_repo.list_proxies(conn)
    now = _now()
    return {"proxies": [_proxy_view(r, now) for r in rows]}


@router.post("/proxies", status_code=201)
async def add_proxy(body: ProxyIn) -> dict:
    now = _now()
    try:
        async with database.get_pool().acquire() as conn:
            row = await settings_repo.add_proxy(conn, body.url, body.label, body.expires_at(now), MAX_PROXIES)
    except settings_repo.ProxyLimitError as exc:
        raise HTTPException(status_code=422, detail=f"не больше {exc.limit} прокси") from exc
    if row is None:
        raise HTTPException(status_code=409, detail="такой прокси уже есть в списке")
    return _proxy_view(row, now)


@router.delete("/proxies/{proxy_id}", status_code=204)
async def delete_proxy(proxy_id: int) -> Response:
    async with database.get_pool().acquire() as conn:
        if not await settings_repo.delete_proxy(conn, proxy_id):
            raise HTTPException(status_code=404, detail="прокси не найден")
    return Response(status_code=204)


async def _check_and_save(row: Mapping, limit: asyncio.Semaphore) -> Optional[dict]:
    async with limit:
        try:
            result = await asyncio.to_thread(proxies.check, row["url"])
        except Exception as exc:  # a checker bug must not hide the other proxies' results
            # No traceback: its frames hold the proxy URL with credentials
            logger.error("Proxy check crashed for proxy id=%s: %s", row["id"], type(exc).__name__)
            result = proxies.CheckResult(ok=False, error="ошибка проверки")
    async with database.get_pool().acquire() as conn:
        return await settings_repo.save_check(conn, row["id"], result)


@router.post("/proxies/check")
async def check_all() -> dict:
    async with database.get_pool().acquire() as conn:
        rows = await settings_repo.list_proxies(conn)
    limit = asyncio.Semaphore(CHECK_CONCURRENCY)
    checked = await asyncio.gather(*(_check_and_save(r, limit) for r in rows), return_exceptions=True)
    for row, outcome in zip(rows, checked):
        if isinstance(outcome, BaseException):
            logger.error("Saving check result failed for proxy id=%s: %r", row["id"], outcome)
    now = _now()
    return {"proxies": [_proxy_view(r, now) for r in checked if isinstance(r, dict)]}


@router.post("/proxies/{proxy_id}/check")
async def check_one(proxy_id: int) -> dict:
    async with database.get_pool().acquire() as conn:
        row = await settings_repo.get_proxy(conn, proxy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="прокси не найден")
    checked = await _check_and_save(row, asyncio.Semaphore(1))
    if checked is None:
        raise HTTPException(status_code=404, detail="прокси не найден")
    return _proxy_view(checked, _now())
