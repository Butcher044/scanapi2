"""Hidden services/methods admin API: only the admin can see the "hidden" tab."""
import pytest

from app import hidden_api


@pytest.fixture
def db(monkeypatch):
    state = {
        "summary": [],
        "services": {},   # bank -> list of service dicts
        "methods": {},    # service_id -> list of method dicts
    }
    repo = hidden_api.repo

    async def get_hidden_summary(conn):
        return list(state["summary"])

    async def get_hidden_services(conn, bank):
        return list(state["services"].get(bank, []))

    async def get_hidden_methods(conn, service_id):
        return list(state["methods"].get(service_id, []))

    for name, fn in locals().copy().items():
        if callable(fn) and hasattr(repo, name):
            monkeypatch.setattr(repo, name, fn)
    return state


def test_anonymous_gets_401(make_client, db):
    assert make_client().get("/api/hidden/summary").status_code == 401


def test_team_is_forbidden(make_client, db):
    assert make_client("team").get("/api/hidden/summary").status_code == 403


def test_summary_maps_bank_labels_and_reasons(make_client, db):
    db["summary"] = [
        {"bank": "tbank", "hidden_services": 1, "hidden_methods": 4,
         "by_reason": {"private": 3, "ghost": 1}},
    ]
    body = make_client("admin").get("/api/hidden/summary").json()
    assert body["banks"] == [{
        "name": "tbank", "label": "Т-Банк",
        "hidden_services": 1, "hidden_methods": 4,
        "by_reason": {"private": 3, "ghost": 1},
    }]


def test_services_lists_hidden_services_of_a_bank(make_client, db):
    db["services"]["tbank"] = [{"id": 7, "name": "Партнёрский API", "url": "u"}]
    body = make_client("admin").get("/api/hidden/services?bank=tbank").json()
    assert body["services"] == [{"id": 7, "name": "Партнёрский API", "url": "u"}]


def test_services_requires_bank_query_param(make_client, db):
    assert make_client("admin").get("/api/hidden/services").status_code == 422


def test_methods_lists_hidden_methods_of_a_service(make_client, db):
    db["methods"][7] = [{
        "id": 1, "name": "List", "http_method": "GET", "path": "/a", "url": "u",
        "hidden_reason": "private", "request_example": {}, "response_example": {"id": "x"},
    }]
    body = make_client("admin").get("/api/hidden/methods?service_id=7").json()
    assert body["methods"] == [{
        "id": 1, "name": "List", "http_method": "GET", "path": "/a", "url": "u",
        "hidden_reason": "private", "request_example": {}, "response_example": {"id": "x"},
    }]


def test_methods_requires_service_id_query_param(make_client, db):
    assert make_client("admin").get("/api/hidden/methods").status_code == 422
