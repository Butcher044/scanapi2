"""Event log helpers: human wording, secret scrubbing, resilient writes, queries."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from app import event_log as el


@pytest.mark.parametrize("seconds,expected", [
    (0.2, "меньше секунды"), (1, "1 с"), (42.4, "42 с"), (60, "1 мин"),
    (190, "3 мин 10 с"), (3600, "1 ч"), (3900, "1 ч 5 мин"),
])
def test_fmt_duration(seconds, expected):
    assert el.fmt_duration(seconds) == expected


@pytest.mark.parametrize("n,expected", [
    (0, "0 методов"), (1, "1 метод"), (3, "3 метода"), (5, "5 методов"),
    (11, "11 методов"), (21, "21 метод"), (104, "104 метода"),
])
def test_count(n, expected):
    assert el.count(n, "метод", "метода", "методов") == expected


def test_strip_html_keeps_text_and_unescapes():
    html = '📊 <b>Т-Банк</b> &amp; <a href="https://x">ссылка</a>'
    assert el.strip_html(html) == "📊 Т-Банк & ссылка"


def test_scrub_hides_proxy_credentials():
    text = "ProxyError: socks5://user:S3cret@1.2.3.4:1080 refused; http://a:b@h:1"
    scrubbed = el.scrub(text)
    assert "S3cret" not in scrubbed and "a:b@" not in scrubbed
    assert "socks5://***@1.2.3.4:1080" in scrubbed


class _Conn:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def execute(self, query, *args):
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((query, args))

    async def fetch(self, query, *args):
        self.calls.append((query, args))
        return []


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


def test_record_writes_scrubbed_and_clipped_row():
    conn = _Conn()
    log = el.EventLog(_Pool(conn))
    asyncio.run(log.record("error", "proxy", "Прокси http://u:pw@h:1 не отвечает", "x" * 50_000))
    [(query, args)] = conn.calls
    assert "INSERT INTO event_log" in query
    level, category, message, details = args
    assert (level, category) == ("error", "proxy")
    assert "pw" not in message
    assert len(details) <= el.MAX_DETAILS + 1


def test_record_never_raises_when_the_db_is_down():
    log = el.EventLog(_Pool(_Conn(fail=True)))
    asyncio.run(log.record("info", "system", "hello"))   # no exception


def test_null_log_is_a_noop():
    asyncio.run(el.NULL_EVENTS.record("info", "system", "hello"))


def test_list_events_filters_become_parameters():
    conn = _Conn()
    asyncio.run(el.list_events(conn, level="error", category="telegram", before_id=50, limit=10))
    [(query, args)] = conn.calls
    assert "level = $1" in query and "category = $2" in query and "id < $3" in query
    assert args == ("error", "telegram", 50, 10)


def test_list_events_without_filters():
    conn = _Conn()
    asyncio.run(el.list_events(conn, limit=5))
    [(query, args)] = conn.calls
    assert "WHERE" not in query and args == (5,)


def test_describe_error_survives_broken_str():
    class Broken(Exception):
        def __str__(self):
            raise ValueError("boom")

    assert el.describe_error(Broken()) == "Broken"
