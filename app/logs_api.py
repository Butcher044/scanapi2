"""Admin-only feed of the event journal behind the "Логи" tab."""
from __future__ import annotations

from typing import Literal, Mapping, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query

from app import database
from app.event_log import list_events
from app.web_auth import require_admin

MSK = ZoneInfo("Europe/Moscow")
PAGE_MAX = 500

Level = Literal["info", "success", "warning", "error"]
Category = Literal["parser", "schedule", "telegram", "proxy", "settings", "system"]

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[Depends(require_admin)])


def _event_view(row: Mapping) -> dict:
    local = row["created_at"].astimezone(MSK)
    return {
        "id":       row["id"],
        "time":     local.strftime("%d.%m.%Y %H:%M:%S"),
        "date":     local.strftime("%Y-%m-%d"),   # for grouping by day on the client
        "level":    row["level"],
        "category": row["category"],
        "message":  row["message"],
        "details":  row["details"],
    }


@router.get("/logs")
async def get_logs(
    level: Optional[Level] = None,
    category: Optional[Category] = None,
    before: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=PAGE_MAX),
) -> dict:
    """Newest first; `before` is the smallest id already shown (for "Показать ещё")."""
    async with database.get_pool().acquire() as conn:
        rows = await list_events(conn, level=level, category=category, before_id=before, limit=limit + 1)
    return {"events": [_event_view(r) for r in rows[:limit]], "has_more": len(rows) > limit}
