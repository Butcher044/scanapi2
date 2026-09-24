"""Benchmark API: everyone reads the matrix, only the admin overrides cells."""
from datetime import datetime, timezone

import pytest

from app import benchmark_api
from app.banks import BANK_KEYS

SNAP = datetime(2026, 9, 20, 7, 30, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    state = {
        "rows": [
            {"bank": "tbank", "created_at": SNAP, "service": "Счета и выписки", "path": "/api/v1/statement"},
            {"bank": "tbank", "created_at": SNAP, "service": "Отели", "path": "/api/v1/hotel"},
            {"bank": "sber", "created_at": SNAP, "service": "Выписки", "path": "/v2/statement/summary"},
            {"bank": "sber", "created_at": SNAP, "service": "Справочники", "path": None},
        ],
        "overrides": {},
    }
    repo = benchmark_api.benchmark_repo

    async def latest_services(conn):
        return list(state["rows"])

    async def get_overrides(conn):
        return dict(state["overrides"])

    async def set_override(conn, capability, bank, present):
        rest = {k: v for k, v in state["overrides"].items() if k != (capability, bank)}
        state["overrides"] = rest if present is None else {**rest, (capability, bank): present}

    for name, fn in locals().copy().items():
        if callable(fn) and hasattr(repo, name):
            monkeypatch.setattr(repo, name, fn)
    return state


def _row(body, key):
    return next(r for g in body["groups"] for r in g["rows"] if r["key"] == key)


def test_anonymous_gets_401(make_client, db):
    assert make_client().get("/api/benchmark").status_code == 401


def test_team_sees_the_matrix(make_client, db):
    body = make_client("team").get("/api/benchmark").json()
    assert [b["key"] for b in body["banks"]] == list(BANK_KEYS)
    tbank = next(b for b in body["banks"] if b["key"] == "tbank")
    assert tbank["label"] and tbank["snapshot_at"] == "20.09.2026 10:30"
    assert next(b for b in body["banks"] if b["key"] == "tochka")["snapshot_at"] is None

    cell = _row(body, "statement")["cells"]["tbank"]
    assert cell == {
        "present": True, "auto": True, "override": None,
        "evidence": [{"service": "Счета и выписки", "matched": 1, "total": 1, "by_name": True}],
    }
    assert _row(body, "statement")["cells"]["tochka"]["present"] is False
    assert body["unmatched"]["tbank"] == ["Отели"]
    assert body["unmatched"]["sber"] == ["Справочники"]
    assert body["unmatched"]["tochka"] == []


def test_groups_keep_catalog_order_and_titles(make_client, db):
    body = make_client("team").get("/api/benchmark").json()
    assert body["groups"][0]["title"] == "Счета и выписки"
    assert body["groups"][0]["rows"][0] == {**body["groups"][0]["rows"][0], "key": "accounts", "title": "Счета и остатки"}


def test_team_cannot_override(make_client, db):
    resp = make_client("team").put("/api/benchmark/overrides",
                                   json={"capability": "statement", "bank": "tbank", "present": False})
    assert resp.status_code == 403
    assert db["overrides"] == {}


def test_admin_sets_and_resets_an_override(make_client, db):
    admin = make_client("admin")
    body = admin.put("/api/benchmark/overrides",
                     json={"capability": "statement", "bank": "tbank", "present": False}).json()
    assert _row(body, "statement")["cells"]["tbank"] | {"evidence": None} == {
        "present": False, "auto": True, "override": False, "evidence": None}
    assert db["overrides"] == {("statement", "tbank"): False}

    body = admin.put("/api/benchmark/overrides",
                     json={"capability": "statement", "bank": "tbank", "present": None}).json()
    assert _row(body, "statement")["cells"]["tbank"]["override"] is None
    assert db["overrides"] == {}


@pytest.mark.parametrize("payload", [
    {"capability": "no_such_thing", "bank": "tbank", "present": True},
    {"capability": "statement", "bank": "vtb", "present": True},
    {"capability": "statement", "bank": "tbank", "present": "yes"},
    {"capability": "statement", "bank": "tbank"},
    {"capability": "x" * 1000, "bank": "tbank", "present": True},
])
def test_invalid_override_is_422(make_client, db, payload):
    assert make_client("admin").put("/api/benchmark/overrides", json=payload).status_code == 422
    assert db["overrides"] == {}
