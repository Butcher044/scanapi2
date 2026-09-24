"""Admin-only API for the "скрытые сервисы" tab.

Some methods exist in a bank's source data but are not visible to a human on
the public dev portal (closed/partner space, superseded article, spec missing
from the menu, release-notes ghost with a dead path). They are kept and
marked (see migrations/007_hidden_methods.sql), never shown on the normal
dashboard, and surfaced here for the admin instead.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app import database, repository as repo
from app.banks import bank_label
from app.web_auth import require_admin

router = APIRouter(prefix="/api/hidden", tags=["hidden"], dependencies=[Depends(require_admin)])


def _pool():
    return database.get_pool()


@router.get("/summary")
async def hidden_summary() -> dict:
    """Per bank: how many services/methods are hidden, broken down by reason."""
    async with _pool().acquire() as conn:
        rows = await repo.get_hidden_summary(conn)
    return {
        "banks": [
            {
                "name":            r["bank"],
                "label":           bank_label(r["bank"]),
                "hidden_services": r["hidden_services"],
                "hidden_methods":  r["hidden_methods"],
                "by_reason":       r["by_reason"],
            }
            for r in rows
        ]
    }


@router.get("/services")
async def hidden_services(bank: str = Query(..., description="Bank key")) -> dict:
    """Hidden services of a bank's latest snapshot."""
    async with _pool().acquire() as conn:
        services = await repo.get_hidden_services(conn, bank)
    return {
        "services": [
            {"id": s["id"], "name": s["name"], "url": s["url"]}
            for s in services
        ]
    }


@router.get("/methods")
async def hidden_methods(service_id: int = Query(...)) -> dict:
    """Hidden methods of a service (the service itself may be visible or hidden)."""
    async with _pool().acquire() as conn:
        methods = await repo.get_hidden_methods(conn, service_id)
    return {
        "methods": [
            {
                "id":               m["id"],
                "name":             m["name"],
                "http_method":      m["http_method"],
                "path":             m["path"],
                "url":              m["url"],
                "hidden_reason":    m["hidden_reason"],
                "request_example":  m.get("request_example", {}),
                "response_example": m.get("response_example", {}),
            }
            for m in methods
        ]
    }
