"""GET /api/logs: admin only, validated filters, Moscow time, pagination."""
from datetime import datetime, timezone

import pytest

from app import logs_api


def _row(i, level="info", category="parser", message="m", details=None):
    return {"id": i, "created_at": datetime(2026, 9, 27, 7, 5, 9, tzinfo=timezone.utc),
            "level": level, "category": category, "message": message, "details": details}


@pytest.fixture
def rows(monkeypatch):
    state = {"rows": [], "calls": []}

    async def list_events(conn, *, level=None, category=None, before_id=None, limit=100):
        state["calls"].append({"level": level, "category": category, "before_id": before_id, "limit": limit})
        return state["rows"][:limit]
    monkeypatch.setattr(logs_api, "list_events", list_events)
    return state


def test_only_admin_sees_logs(make_client, rows):
    assert make_client(None).get("/api/logs").status_code == 401
    assert make_client("team").get("/api/logs").status_code == 403


def test_events_are_shaped_in_moscow_time(make_client, rows):
    rows["rows"] = [_row(2, "error", "telegram", "Не доставлено", "детали")]
    body = make_client("admin").get("/api/logs").json()
    assert body == {"has_more": False, "events": [{
        "id": 2, "time": "27.09.2026 10:05:09", "date": "2026-09-27", "level": "error",
        "category": "telegram", "message": "Не доставлено", "details": "детали"}]}


def test_has_more_uses_one_extra_row(make_client, rows):
    rows["rows"] = [_row(i) for i in (5, 4, 3)]
    body = make_client("admin").get("/api/logs?limit=2&before=6&level=info&category=parser").json()
    assert [e["id"] for e in body["events"]] == [5, 4] and body["has_more"] is True
    assert rows["calls"] == [{"level": "info", "category": "parser", "before_id": 6, "limit": 3}]


@pytest.mark.parametrize("query", ["level=debug", "category=nope", "limit=0", "limit=1000", "before=-1"])
def test_bad_filters_are_422(make_client, rows, query):
    assert make_client("admin").get(f"/api/logs?{query}").status_code == 422
