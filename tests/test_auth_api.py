"""Login/logout, closed API for anonymous users, admin-only endpoints for the team role."""
import pytest

import app.main as main
from app.web_auth import COOKIE
from tests.conftest import PASSWORDS


class _Runner:
    from app.parser_runner import ParseStatus
    status = ParseStatus()

    async def run_all(self):
        pass


@pytest.fixture(autouse=True)
def runner(monkeypatch):
    monkeypatch.setattr(main, "_runner", _Runner())


@pytest.mark.parametrize("method,path", [
    ("get", "/api/summary"), ("get", "/api/changes"), ("get", "/api/parse/status"),
    ("post", "/api/parse"), ("get", "/api/settings"), ("get", "/api/proxies"),
    ("get", "/api/auth/me"), ("get", "/api/docs"), ("get", "/api/openapi.json"),
])
def test_anonymous_gets_401_everywhere(make_client, method, path):
    assert getattr(make_client(), method)(path).status_code == 401


@pytest.mark.parametrize("method,path", [
    ("post", "/api/parse"), ("get", "/api/settings"), ("put", "/api/settings"),
    ("get", "/api/proxies"), ("post", "/api/proxies"), ("delete", "/api/proxies/1"),
    ("post", "/api/proxies/1/check"), ("post", "/api/proxies/check"),
])
def test_team_gets_403_on_admin_endpoints(make_client, method, path):
    assert getattr(make_client("team"), method)(path).status_code == 403


def test_team_can_read_data(make_client):
    assert make_client("team").get("/api/parse/status").status_code == 200


@pytest.mark.parametrize("role", ["admin", "team"])
def test_login_sets_httponly_cookie_and_me_returns_role(make_client, role):
    client = make_client()
    r = client.post("/api/auth/login", json={"password": PASSWORDS[role]})
    assert r.status_code == 200 and r.json() == {"role": role}
    cookie = r.headers["set-cookie"]
    assert f"{COOKIE}=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Max-Age=2592000" in cookie
    assert client.get("/api/auth/me").json() == {"role": role}


def test_wrong_password_is_401_and_sets_no_cookie(make_client):
    r = make_client().post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 401 and "set-cookie" not in r.headers


def test_login_rate_limited_after_five_failures(make_client):
    client = make_client()
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "x"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": PASSWORDS["admin"]})
    assert r.status_code == 429 and "retry-after" in r.headers


def test_logout_clears_cookie(make_client):
    client = make_client("admin")
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    assert f'{COOKIE}=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]


def test_forged_cookie_is_rejected(make_client):
    client = make_client()
    client.cookies.set(COOKIE, "admin.9999999999.forged")
    assert client.get("/api/summary").status_code == 401


def test_cross_origin_write_is_rejected(make_client):
    client = make_client("admin")
    r = client.post("/api/parse", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_write_is_allowed(make_client):
    client = make_client("admin")
    assert client.post("/api/parse", headers={"Origin": "http://testserver"}).status_code == 200


def test_login_validates_body(make_client):
    client = make_client()
    assert client.post("/api/auth/login", json={}).status_code == 422
    assert client.post("/api/auth/login", json={"password": "x" * 1000}).status_code == 422


def test_spa_shell_is_public(make_client, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("INDEX", encoding="utf-8")
    monkeypatch.setattr(main, "_DIST", tmp_path.resolve())
    assert make_client().get("/login").text == "INDEX"


def test_health_is_public_and_reveals_nothing(make_client):
    resp = make_client().get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_spoofed_forwarded_proto_does_not_mark_cookie_secure(make_client):
    # Only uvicorn (for FORWARDED_ALLOW_IPS peers) may turn the scheme into https
    r = make_client().post("/api/auth/login", json={"password": PASSWORDS["admin"]},
                           headers={"X-Forwarded-Proto": "https"})
    assert r.status_code == 200 and "Secure" not in r.headers["set-cookie"]
