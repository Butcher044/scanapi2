"""Admin settings API: parse time (live reschedule), proxy toggle, proxy CRUD and checks."""
from datetime import datetime, timedelta, timezone

import pytest

import app.main as main
from app import admin_api
from app.proxies import CheckResult
from app.scheduler import Scheduler

URL = "socks5://user:SECRET@1.2.3.4:1080"


class _Runner:
    async def run_all(self):
        pass


@pytest.fixture
def db(monkeypatch):
    state = {"settings": {}, "proxies": {}, "next_id": 1}
    repo = admin_api.settings_repo

    async def get_settings(conn):
        return dict(state["settings"])

    async def put_settings(conn, values):
        state["settings"] = {**state["settings"], **values}

    async def list_proxies(conn):
        return list(state["proxies"].values())

    async def get_proxy(conn, pid):
        return state["proxies"].get(pid)

    async def add_proxy(conn, url, label, expires_at, limit):
        if len(state["proxies"]) >= limit:
            raise repo.ProxyLimitError(limit)
        if any(p["url"] == url for p in state["proxies"].values()):
            return None
        pid = state["next_id"]
        state["next_id"] += 1
        row = {"id": pid, "url": url, "label": label, "expires_at": expires_at,
               "created_at": datetime.now(timezone.utc), "last_checked_at": None, "last_ok": None,
               "last_ip": None, "last_country": None, "last_latency_ms": None, "last_error": None,
               "expiry_notified_at": None}
        state["proxies"] = {**state["proxies"], pid: row}
        return row

    async def delete_proxy(conn, pid):
        existed = pid in state["proxies"]
        state["proxies"] = {k: v for k, v in state["proxies"].items() if k != pid}
        return existed

    async def save_check(conn, pid, result):
        row = {**state["proxies"][pid], "last_checked_at": datetime.now(timezone.utc),
               "last_ok": result.ok, "last_ip": result.ip, "last_country": result.country,
               "last_latency_ms": result.latency_ms, "last_error": result.error}
        state["proxies"] = {**state["proxies"], pid: row}
        return row

    for name, fn in locals().copy().items():
        if callable(fn) and hasattr(repo, name):
            monkeypatch.setattr(repo, name, fn)
    return state


@pytest.fixture
def admin(make_client, db, monkeypatch):
    sched = Scheduler(_Runner(), "10:00")
    monkeypatch.setattr(main.app.state, "scheduler", sched, raising=False)
    monkeypatch.setattr(main.app.state, "default_time", "10:00", raising=False)
    return make_client("admin")


def test_get_settings_defaults(admin):
    body = admin.get("/api/settings").json()
    assert body["scheduler_time"] == "10:00" and body["proxy_enabled"] is False
    assert body["next_run"].endswith("10:00")


def test_put_settings_saves_and_reschedules(admin, db):
    r = admin.put("/api/settings", json={"scheduler_time": "18:45", "proxy_enabled": True})
    assert r.status_code == 200
    assert r.json()["scheduler_time"] == "18:45" and r.json()["proxy_enabled"] is True
    assert db["settings"] == {"scheduler_time": "18:45", "proxy_enabled": "true"}
    assert main.app.state.scheduler.time == "18:45"


def test_partial_update_keeps_other_value(admin, db):
    admin.put("/api/settings", json={"proxy_enabled": True})
    admin.put("/api/settings", json={"scheduler_time": "07:00"})
    assert db["settings"] == {"scheduler_time": "07:00", "proxy_enabled": "true"}


@pytest.mark.parametrize("value", ["25:00", "7", "", "ab:cd"])
def test_bad_time_is_422_and_nothing_changes(admin, db, value):
    assert admin.put("/api/settings", json={"scheduler_time": value}).status_code == 422
    assert db["settings"] == {} and main.app.state.scheduler.time == "10:00"


def test_add_proxy_defaults_to_30_days_and_masks_password(admin):
    r = admin.post("/api/proxies", json={"url": URL, "label": "МСК-1"})
    assert r.status_code == 201
    body = r.json()
    assert body["url"] == "socks5://user:***@1.2.3.4:1080" and "SECRET" not in r.text
    assert body["label"] == "МСК-1" and body["days_left"] in (29, 30)


def test_add_proxy_with_days_or_date(admin):
    assert admin.post("/api/proxies", json={"url": "http://h:1", "days": 7}).json()["days_left"] in (6, 7)
    date = (datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat()
    body = admin.post("/api/proxies", json={"url": "http://h:2", "expires_on": date}).json()
    assert body["days_left"] in (9, 10)


@pytest.mark.parametrize("payload", [
    {"url": "ftp://h:1"}, {"url": "h:1"}, {"url": "http://h:1", "days": 0},
    {"url": "http://h:1", "days": 5000}, {"url": "http://h:1", "label": "x" * 200},
    {"url": "http://h:1", "days": 5, "expires_on": "2030-01-01"},
])
def test_add_proxy_validation(admin, payload):
    assert admin.post("/api/proxies", json=payload).status_code == 422


def test_duplicate_proxy_is_409(admin):
    admin.post("/api/proxies", json={"url": URL})
    assert admin.post("/api/proxies", json={"url": URL}).status_code == 409


def test_list_and_delete(admin):
    pid = admin.post("/api/proxies", json={"url": URL}).json()["id"]
    listed = admin.get("/api/proxies").json()["proxies"]
    assert [p["id"] for p in listed] == [pid] and "SECRET" not in str(listed)
    assert admin.delete(f"/api/proxies/{pid}").status_code == 204
    assert admin.delete(f"/api/proxies/{pid}").status_code == 404


def test_check_one_stores_result(admin, monkeypatch):
    seen = []

    def fake_check(url):
        seen.append(url)
        return CheckResult(ok=True, ip="5.6.7.8", country="RU", latency_ms=120)
    monkeypatch.setattr(admin_api.proxies, "check", fake_check)
    pid = admin.post("/api/proxies", json={"url": URL}).json()["id"]
    body = admin.post(f"/api/proxies/{pid}/check").json()
    assert seen == [URL]        # the real URL (with password) goes to the checker only
    assert body["last_ok"] is True and body["last_country"] == "RU" and body["last_latency_ms"] == 120
    assert admin.post("/api/proxies/999/check").status_code == 404


def test_check_all(admin, monkeypatch):
    monkeypatch.setattr(admin_api.proxies, "check",
                        lambda url: CheckResult(ok=url.endswith(":1"), error=None if url.endswith(":1") else "таймаут"))
    admin.post("/api/proxies", json={"url": "http://a:1"})
    admin.post("/api/proxies", json={"url": "http://b:2"})
    body = admin.post("/api/proxies/check").json()["proxies"]
    assert [(p["last_ok"], p["last_error"]) for p in body] == [(True, None), (False, "таймаут")]


def test_check_all_survives_a_failing_check(admin, monkeypatch):
    def fake_check(url):
        if url.endswith(":2"):
            raise RuntimeError("boom")
        return CheckResult(ok=True)
    monkeypatch.setattr(admin_api.proxies, "check", fake_check)
    admin.post("/api/proxies", json={"url": "http://a:1"})
    admin.post("/api/proxies", json={"url": "http://b:2"})
    resp = admin.post("/api/proxies/check")
    assert resp.status_code == 200
    assert [(p["last_ok"], p["last_error"]) for p in resp.json()["proxies"]] == [
        (True, None), (False, "ошибка проверки")]


def test_add_proxy_respects_the_limit(admin, monkeypatch):
    monkeypatch.setattr(admin_api, "MAX_PROXIES", 1)
    assert admin.post("/api/proxies", json={"url": "http://a:1"}).status_code == 201
    resp = admin.post("/api/proxies", json={"url": "http://b:2"})
    assert resp.status_code == 422 and "1" in resp.json()["detail"]
