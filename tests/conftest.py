"""Shared API fixtures: fake DB pool, a known Auth, and a logged-in TestClient factory."""
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import Auth, LoginLimiter
from app.web_auth import COOKIE

PASSWORDS = {"admin": "admin-pass", "team": "team-pass"}


class _Acquire:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


class FakePool:
    def acquire(self):
        return _Acquire()


@pytest.fixture
def make_client(monkeypatch):
    """make_client(role) -> TestClient with a session cookie for that role (None = anonymous)."""
    auth = Auth(PASSWORDS, b"t" * 32)
    monkeypatch.setattr(main.app.state, "auth", auth, raising=False)
    monkeypatch.setattr(main.app.state, "limiter", LoginLimiter(), raising=False)
    monkeypatch.setattr(main.database, "get_pool", lambda: FakePool())

    def factory(role=None):
        client = TestClient(main.app)   # no `with` → lifespan (DB, scheduler) is not started
        if role:
            client.cookies.set(COOKIE, auth.issue(role))
        return client
    return factory
