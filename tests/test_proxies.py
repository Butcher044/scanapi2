"""Proxy URL validation, expiry maths and the health check (network faked)."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

from app import proxies as pc

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("url", [
    "http://user:pass@1.2.3.4:8000", "socks5://u:p@proxy.example.ru:1080",
    "socks5h://h.example:1080", "https://h.example:443", "  http://h.example:3128  ",
])
def test_valid_proxy_urls(url):
    assert pc.validate_url(url) == url.strip()


@pytest.mark.parametrize("url", [
    "", "1.2.3.4:8000", "ftp://h:21", "http://h", "http://:8000", "socks4://h:1080",
    "http://h:99999", "http://h:80/path", "http://h:80?x=1", "http://h:80\nx", "x" * 600,
    # the app itself / cloud metadata / "any address" are never a real proxy (SSRF guard)
    "http://127.0.0.1:8080", "http://localhost:8080", "socks5://169.254.169.254:1080",
    "http://0.0.0.0:1", "http://[::1]:8080", "http://[::ffff:127.0.0.1]:8080",
    "socks5://[::ffff:169.254.169.254]:1080",
])
def test_invalid_proxy_urls(url):
    with pytest.raises(ValueError):
        pc.validate_url(url)


def test_private_network_proxy_is_allowed():
    assert pc.validate_url("http://10.0.0.5:3128") == "http://10.0.0.5:3128"


def test_check_never_raises(monkeypatch):
    def boom(session):
        raise RuntimeError("socks lib exploded with http://user:secret@h:1")
    monkeypatch.setattr(pc, "_geo", boom)
    result = pc.check("http://h:1")
    assert (result.ok, result.error) == (False, "ошибка проверки")


def test_days_left():
    assert pc.days_left(NOW + timedelta(days=30), NOW) == 30
    assert pc.days_left(NOW + timedelta(hours=5), NOW) == 0
    assert pc.days_left(NOW - timedelta(hours=1), NOW) == -1
    assert pc.days_left(None, NOW) is None


def test_days_left_counts_moscow_calendar_days():
    # Added "for 30 days" a moment ago: still 30, not 29
    assert pc.days_left(NOW + timedelta(days=30) - timedelta(seconds=5), NOW) == 30
    # 23:00 MSK today -> 01:00 MSK tomorrow is "1 day left", though only 2 hours
    late = datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)
    assert pc.days_left(late + timedelta(hours=2), late) == 1


def test_expiring_selects_soon_and_expired_not_yet_notified():
    rows = [
        {"id": 1, "expires_at": NOW + timedelta(days=2), "expiry_notified_at": None},
        {"id": 2, "expires_at": NOW + timedelta(days=10), "expiry_notified_at": None},
        {"id": 3, "expires_at": NOW - timedelta(days=1), "expiry_notified_at": None},
        {"id": 4, "expires_at": NOW + timedelta(days=1), "expiry_notified_at": NOW},
        {"id": 5, "expires_at": None, "expiry_notified_at": None},
    ]
    assert [r["id"] for r in pc.expiring(rows, NOW, warn_days=3)] == [1, 3]


def test_usable_skips_expired():
    rows = [
        {"url": "http://a:1", "expires_at": NOW + timedelta(days=1)},
        {"url": "http://b:1", "expires_at": NOW - timedelta(seconds=1)},
        {"url": "http://c:1", "expires_at": None},
    ]
    assert pc.usable_urls(rows, NOW) == ["http://a:1", "http://c:1"]


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = responses, []
        self.proxies, self.verify, self.trust_env = {}, True, True

    def get(self, url, timeout):
        self.calls.append((url, dict(self.proxies)))
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        pass


def _resp(status=200, payload=None):
    r = requests.Response()
    r.status_code = status
    r._content = (b"{}" if payload is None else __import__("json").dumps(payload).encode())
    return r


GEO_OK = _resp(payload={"status": "success", "countryCode": "RU", "query": "5.6.7.8"})


def test_check_ok_reports_ip_country_and_latency(monkeypatch):
    fake = FakeSession({pc.GEO_URL: GEO_OK, pc.PROBE_URL: _resp(200)})
    monkeypatch.setattr(pc.requests, "Session", lambda: fake)
    result = pc.check("socks5://u:p@h:1080")
    assert (result.ok, result.ip, result.country, result.error) == (True, "5.6.7.8", "RU", None)
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert all(p == {"http": "socks5://u:p@h:1080", "https": "socks5://u:p@h:1080"} for _, p in fake.calls)
    assert fake.trust_env is False


def test_check_proxy_down_gives_safe_error(monkeypatch):
    err = requests.exceptions.ProxyError("Cannot connect to proxy socks5://u:SECRET@h:1080")
    fake = FakeSession({pc.GEO_URL: err, pc.PROBE_URL: err})
    monkeypatch.setattr(pc.requests, "Session", lambda: fake)
    result = pc.check("socks5://u:SECRET@h:1080")
    assert result.ok is False and "SECRET" not in result.error
    assert result.error == "прокси недоступен"


def test_check_bank_unreachable_through_working_proxy(monkeypatch):
    fake = FakeSession({pc.GEO_URL: GEO_OK, pc.PROBE_URL: requests.exceptions.ReadTimeout("x")})
    monkeypatch.setattr(pc.requests, "Session", lambda: fake)
    result = pc.check("http://h:1")
    assert result.ok is False and result.country == "RU" and result.error == "банк не ответил: таймаут"


def test_non_russian_exit_is_flagged_but_ok(monkeypatch):
    geo = _resp(payload={"status": "success", "countryCode": "NL", "query": "9.9.9.9"})
    fake = FakeSession({pc.GEO_URL: geo, pc.PROBE_URL: _resp(200)})
    monkeypatch.setattr(pc.requests, "Session", lambda: fake)
    result = pc.check("http://h:1")
    assert result.ok is True and result.country == "NL"
