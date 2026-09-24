"""Admin settings stored in the DB, proxy rotator assembly and expiry alerts (DB faked)."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app import runtime_settings as rs

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


class FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


def test_defaults_when_nothing_stored():
    s = rs.from_rows({}, default_time="09:15")
    assert s == rs.RuntimeSettings(scheduler_time="09:15", proxy_enabled=False)


def test_stored_values_win_and_bad_time_is_ignored():
    assert rs.from_rows({"scheduler_time": "18:30", "proxy_enabled": "true"}, "10:00") == \
        rs.RuntimeSettings("18:30", True)
    assert rs.from_rows({"scheduler_time": "99:99"}, "10:00").scheduler_time == "10:00"


def test_to_rows_roundtrip():
    s = rs.RuntimeSettings("07:05", True)
    assert rs.from_rows(rs.to_rows(s), "10:00") == s


@pytest.fixture
def db(monkeypatch):
    state = {"settings": {}, "proxies": [], "notified": []}

    async def get_settings(conn):
        return state["settings"]

    async def list_proxies(conn):
        return state["proxies"]

    async def mark(conn, ids):
        state["notified"].extend(ids)

    monkeypatch.setattr(rs.settings_repo, "get_settings", get_settings)
    monkeypatch.setattr(rs.settings_repo, "list_proxies", list_proxies)
    monkeypatch.setattr(rs.settings_repo, "mark_expiry_notified", mark)
    return state


def _proxy(i, url, days, notified=None, label=""):
    return {"id": i, "url": url, "label": label, "expires_at": NOW + timedelta(days=days),
            "expiry_notified_at": notified}


def test_rotator_is_none_when_proxies_disabled(db):
    db["proxies"] = [_proxy(1, "http://a:1", 5)]
    assert asyncio.run(rs.proxy_rotator(FakePool(), "10:00", NOW)) is None


def test_rotator_uses_only_unexpired_proxies(db):
    db["settings"] = {"proxy_enabled": "true"}
    db["proxies"] = [_proxy(1, "http://a:1", 5), _proxy(2, "http://b:1", -1)]
    rot = asyncio.run(rs.proxy_rotator(FakePool(), "10:00", NOW))
    assert rot.candidates() == ["http://a:1"]


def test_rotator_is_none_when_enabled_but_all_expired(db):
    db["settings"] = {"proxy_enabled": "true"}
    db["proxies"] = [_proxy(1, "http://a:1", -2)]
    assert asyncio.run(rs.proxy_rotator(FakePool(), "10:00", NOW)) is None


class Notifier:
    def __init__(self):
        self.admin = []

    async def send_admin(self, text):
        self.admin.append(text)


def test_expiry_alert_lists_masked_proxies_once(db):
    db["proxies"] = [_proxy(1, "socks5://u:SECRET@h1:1080", 2, label="Москва-1"),
                     _proxy(2, "http://h2:3128", 20), _proxy(3, "http://h3:1", -1)]
    notifier = Notifier()
    asyncio.run(rs.notify_expiring(FakePool(), notifier, NOW))
    [text] = notifier.admin
    assert "SECRET" not in text and "socks5://u:***@h1:1080" in text and "Москва-1" in text
    assert "h3" in text and "h2" not in text
    assert db["notified"] == [1, 3]


def test_expiry_alert_silent_when_nothing_expires(db):
    db["proxies"] = [_proxy(1, "http://a:1", 20)]
    notifier = Notifier()
    asyncio.run(rs.notify_expiring(FakePool(), notifier, NOW))
    assert notifier.admin == [] and db["notified"] == []


def test_expiry_not_marked_when_there_is_no_notifier(db):
    db["proxies"] = [_proxy(1, "http://a:1", 1)]
    asyncio.run(rs.notify_expiring(FakePool(), None, NOW))
    assert db["notified"] == []
