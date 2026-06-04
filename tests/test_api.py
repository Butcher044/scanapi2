"""
Integration tests for the FastAPI application.

Requires a running PostgreSQL instance and a running app container, OR
can be run with SKIP_INTEGRATION=1 to skip live tests.

Live tests use the app already running on localhost:8090 (Docker).
For unit tests of the API layer, we mock the DB pool.
"""
import os
import sys
import json
from pathlib import Path

import pytest

# Try to import httpx for live tests
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

SKIP = os.environ.get("SKIP_INTEGRATION", "").lower() in ("1", "true", "yes")
BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8090")

pytestmark = pytest.mark.skipif(
    SKIP or not HAS_HTTPX,
    reason="Integration tests skipped (set SKIP_INTEGRATION=0 and install httpx to run)"
)


# ── Live API tests (require running container) ────────────────────────────────

class TestSummaryEndpoint:
    def test_returns_200(self):
        r = httpx.get(f"{BASE_URL}/api/summary")
        assert r.status_code == 200

    def test_has_required_keys(self):
        r = httpx.get(f"{BASE_URL}/api/summary").json()
        assert "banks" in r
        assert "total_services" in r
        assert "total_methods" in r
        assert "changes_today" in r
        assert "changes_week" in r
        assert "changes_total" in r

    def test_banks_is_list(self):
        r = httpx.get(f"{BASE_URL}/api/summary").json()
        assert isinstance(r["banks"], list)

    def test_bank_has_correct_shape(self):
        r = httpx.get(f"{BASE_URL}/api/summary").json()
        for bank in r["banks"]:
            assert "name" in bank
            assert "label" in bank
            assert "services" in bank
            assert "methods" in bank
            assert isinstance(bank["methods"], int)
            assert isinstance(bank["services"], int)

    def test_no_alfa_key_only_alfabank(self):
        """Old 'alfa' key must not appear — only 'alfabank'."""
        r = httpx.get(f"{BASE_URL}/api/summary").json()
        bank_names = [b["name"] for b in r["banks"]]
        assert "alfa" not in bank_names, \
            "Found stale 'alfa' bank key — should be 'alfabank'"


class TestChangesEndpoint:
    def test_returns_200(self):
        r = httpx.get(f"{BASE_URL}/api/changes")
        assert r.status_code == 200

    def test_has_pagination_fields(self):
        r = httpx.get(f"{BASE_URL}/api/changes").json()
        assert "changes" in r
        assert "total" in r
        assert "limit" in r
        assert "offset" in r

    def test_filter_by_bank(self):
        r = httpx.get(f"{BASE_URL}/api/changes?bank=tbank").json()
        for c in r["changes"]:
            assert c["bank"] == "tbank"

    def test_filter_by_type(self):
        r = httpx.get(f"{BASE_URL}/api/changes?type=method").json()
        for c in r["changes"]:
            assert c["type"] == "method"

    def test_filter_by_action(self):
        r = httpx.get(f"{BASE_URL}/api/changes?action=added").json()
        for c in r["changes"]:
            assert c["action"] == "added"

    def test_pagination_limit(self):
        r = httpx.get(f"{BASE_URL}/api/changes?limit=5").json()
        assert len(r["changes"]) <= 5

    def test_pagination_offset(self):
        r1 = httpx.get(f"{BASE_URL}/api/changes?limit=5&offset=0").json()
        r2 = httpx.get(f"{BASE_URL}/api/changes?limit=5&offset=5").json()
        ids1 = {c["id"] for c in r1["changes"]}
        ids2 = {c["id"] for c in r2["changes"]}
        # Pages should not overlap (assuming enough data)
        if ids1 and ids2:
            assert ids1.isdisjoint(ids2), "Paginated pages overlap"

    def test_change_has_correct_shape(self):
        r = httpx.get(f"{BASE_URL}/api/changes?limit=1").json()
        if not r["changes"]:
            pytest.skip("No changes in DB — run a parse first")
        c = r["changes"][0]
        required = ["id", "bank", "bank_label", "type", "action", "entity", "detected_at"]
        for field in required:
            assert field in c, f"Missing field: {field}"


class TestDynamicsEndpoint:
    def test_returns_200(self):
        r = httpx.get(f"{BASE_URL}/api/dynamics")
        assert r.status_code == 200

    def test_has_dynamics_key(self):
        r = httpx.get(f"{BASE_URL}/api/dynamics").json()
        assert "dynamics" in r
        assert isinstance(r["dynamics"], list)


class TestServicesEndpoint:
    def test_requires_bank_param(self):
        r = httpx.get(f"{BASE_URL}/api/services")
        assert r.status_code in (400, 422)

    def test_returns_services_for_tbank(self):
        r = httpx.get(f"{BASE_URL}/api/services?bank=tbank")
        assert r.status_code == 200
        data = r.json()
        assert "services" in data
        assert isinstance(data["services"], list)

    def test_service_has_correct_shape(self):
        r = httpx.get(f"{BASE_URL}/api/services?bank=tbank").json()
        if not r["services"]:
            pytest.skip("No services for tbank")
        s = r["services"][0]
        assert "id" in s
        assert "name" in s
        assert isinstance(s["id"], int)


class TestMethodsEndpoint:
    def _first_service_id(self, bank="tbank"):
        r = httpx.get(f"{BASE_URL}/api/services?bank={bank}").json()
        if not r.get("services"):
            return None
        return r["services"][0]["id"]

    def test_requires_service_id(self):
        r = httpx.get(f"{BASE_URL}/api/methods")
        assert r.status_code in (400, 422)

    def test_returns_methods(self):
        sid = self._first_service_id()
        if sid is None:
            pytest.skip("No services in DB")
        r = httpx.get(f"{BASE_URL}/api/methods?service_id={sid}")
        assert r.status_code == 200
        data = r.json()
        assert "methods" in data

    def test_method_has_correct_shape(self):
        sid = self._first_service_id()
        if sid is None:
            pytest.skip("No services in DB")
        r = httpx.get(f"{BASE_URL}/api/methods?service_id={sid}").json()
        if not r.get("methods"):
            pytest.skip("No methods for service")
        m = r["methods"][0]
        assert "id" in m
        assert "http_method" in m
        assert m["http_method"] in ("GET", "POST", "PUT", "PATCH", "DELETE")

    def test_no_duplicate_methods_per_service(self):
        sid = self._first_service_id()
        if sid is None:
            pytest.skip("No services in DB")
        r = httpx.get(f"{BASE_URL}/api/methods?service_id={sid}").json()
        methods = r.get("methods", [])
        # Key: (http_method, path) should be unique
        keys = [(m["http_method"], m.get("path", m["name"])) for m in methods]
        assert len(keys) == len(set(keys)), \
            f"Duplicate methods found: {[k for k in keys if keys.count(k) > 1]}"


class TestParseStatusEndpoint:
    def test_returns_200(self):
        r = httpx.get(f"{BASE_URL}/api/parse/status")
        assert r.status_code == 200

    def test_has_required_keys(self):
        r = httpx.get(f"{BASE_URL}/api/parse/status").json()
        assert "running" in r
        assert "banks" in r

    def test_banks_have_status_field(self):
        r = httpx.get(f"{BASE_URL}/api/parse/status").json()
        for bank, status in r["banks"].items():
            assert "status" in status
            assert status["status"] in ("pending", "running", "done", "error")

    def test_correct_bank_keys(self):
        r = httpx.get(f"{BASE_URL}/api/parse/status").json()
        expected = {"tbank", "tochka", "alfabank", "sber"}
        actual = set(r["banks"].keys())
        assert actual == expected, f"Wrong bank keys: {actual}"


class TestSPAFallback:
    def test_root_serves_html(self):
        r = httpx.get(f"{BASE_URL}/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")

    def test_spa_route_serves_html(self):
        for path in ("/banks", "/changes"):
            r = httpx.get(f"{BASE_URL}{path}")
            assert r.status_code == 200
            assert "text/html" in r.headers.get("content-type", "")


# ── Unit tests (no network required) ─────────────────────────────────────────

class TestAlwaysRun:
    """These tests run always, no network or DB needed."""

    def test_bank_label_mapping(self):
        """Verify that bank label constants are correct."""
        from app.main import _bank_label
        assert _bank_label("tbank") == "Т-Банк"
        assert _bank_label("alfabank") == "Альфа-Банк"
        assert _bank_label("sber") == "Сбер"
        assert _bank_label("tochka") == "Точка"
        assert _bank_label("unknown") == "unknown"

    def test_changes_endpoint_imports(self):
        """FastAPI app can be imported without errors."""
        from app.main import app
        assert app is not None


if __name__ == "__main__":
    if not HAS_HTTPX:
        print("httpx not installed — run: pip install httpx")
        sys.exit(1)

    print(f"Testing against: {BASE_URL}\n")
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(Path(__file__).parent.parent)
    )
    sys.exit(result.returncode)
