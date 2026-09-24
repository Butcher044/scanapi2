"""In-process API tests: FastAPI TestClient with the repository layer faked (no DB)."""
from datetime import datetime, timezone

import pytest

import app.main as main
from app.banks import BANK_KEYS
from app.parser_runner import ParseStatus


class _Runner:
    def __init__(self, running=False):
        self.status = ParseStatus(running=running)
        self.calls = 0

    async def run_all(self):
        self.calls += 1


@pytest.fixture
def client(monkeypatch, make_client):
    monkeypatch.setattr(main, "_runner", _Runner())
    return make_client("admin")


def _fake(monkeypatch, name, value):
    async def fn(*args, **kwargs):
        return value
    monkeypatch.setattr(main.repo, name, fn)


def test_summary_maps_bank_labels(client, monkeypatch):
    _fake(monkeypatch, "get_summary", {
        "banks": [{"bank": "alfabank", "service_count": 2, "method_count": 5}],
        "total_services": 2, "total_methods": 5,
        "changes_today": 1, "changes_week": 3, "changes_total": 9,
    })
    body = client.get("/api/summary").json()
    assert body["banks"] == [{"name": "alfabank", "label": "Альфа-Банк", "services": 2, "methods": 5}]
    assert body["changes_total"] == 9


def test_changes_are_formatted_in_moscow_time(client, monkeypatch):
    row = {
        "id": 1, "bank": "tbank", "change_type": "method", "change_action": "added",
        "entity_name": "GET /a", "entity_path": "S / GET /a", "old_value": "", "new_value": "",
        "url": "u", "detected_at": datetime(2026, 1, 1, 21, 30, tzinfo=timezone.utc),
    }
    _fake(monkeypatch, "get_changes_filtered", ([row], 1))
    body = client.get("/api/changes?limit=10").json()
    assert body["total"] == 1
    assert body["changes"][0]["detected_at"] == "2026-01-02 00:30"
    assert body["changes"][0]["bank_label"] == "Т-Банк"


def test_changes_rejects_bad_limit(client):
    assert client.get("/api/changes?limit=0").status_code == 422


def test_services_and_methods(client, monkeypatch):
    _fake(monkeypatch, "get_bank_services", [{"id": 7, "name": "Счета", "url": "u"}])
    _fake(monkeypatch, "get_service_methods", [{
        "id": 1, "name": "List", "http_method": "GET", "path": "/a", "url": "u",
        "request_example": {}, "response_example": {"id": "x"},
    }])
    assert client.get("/api/services?bank=tbank").json()["services"][0]["id"] == 7
    assert client.get("/api/methods?service_id=7").json()["methods"][0]["response_example"] == {"id": "x"}
    assert client.get("/api/services").status_code == 422


@pytest.mark.parametrize("path", ["/api/stats", "/api/dynamics", "/api/fields?method_id=1", "/api/nope"])
def test_removed_and_unknown_api_routes_are_404(client, path):
    assert client.get(path).status_code == 404


def test_parse_starts_for_admin(client):
    r = client.post("/api/parse")
    assert r.status_code == 200
    assert r.json() == {"status": "started", "banks": list(BANK_KEYS)}


def test_parse_status(client):
    body = client.get("/api/parse/status").json()
    assert body["running"] is False


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("INDEX", encoding="utf-8")
    (root / "robots.txt").write_text("ROBOTS", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("SECRET", encoding="utf-8")
    monkeypatch.setattr(main, "_DIST", root.resolve())
    return root


def test_spa_serves_static_file_and_index_fallback(client, dist):
    assert client.get("/robots.txt").text == "ROBOTS"
    assert client.get("/banks/tbank").text == "INDEX"


@pytest.mark.parametrize("path", ["/..%2fsecret.txt", "/%2e%2e/secret.txt", r"/..\secret.txt"])
def test_spa_fallback_blocks_path_traversal(client, dist, path):
    assert "SECRET" not in client.get(path).text


def test_security_headers(client):
    r = client.get("/api/parse/status")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    # default-src does not cover <base>, so a dangling base tag would otherwise
    # be free to re-point every relative URL on the page.
    assert "base-uri 'self'" in csp
    assert "object-src 'none'" in csp


def test_changes_rejects_huge_offset(client):
    assert client.get("/api/changes?offset=1000001").status_code == 422
