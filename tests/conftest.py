"""Shared API fixtures: fake DB pool, a known Auth, and a logged-in TestClient factory."""
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.auth import Auth, LoginLimiter
from app.event_log import CATEGORIES, LEVELS, Event
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


class RecordingEvents:
    """In-memory event sink: what a component wrote to the admin's "Логи" tab."""

    def __init__(self):
        self.events: list[Event] = []

    async def record(self, level, category, message, details=None):
        assert level in LEVELS, level
        assert category in CATEGORIES, category
        self.events.append(Event(level, category, message, details))

    def find(self, text, level=None):
        """Events whose message contains `text` (and match `level` when given)."""
        return [e for e in self.events if text in e.message and (level is None or e.level == level)]


@pytest.fixture
def events():
    return RecordingEvents()
