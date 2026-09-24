"""Unit test for the pure merge logic of app.repository.get_hidden_summary.

The SQL itself needs a live PostgreSQL to verify (not available here — see the
report). This test only exercises how the two fetched row sets are combined,
using a fake asyncpg.Connection that returns canned rows per call.
"""
import asyncio

from app import repository as repo


class FakeConn:
    """Returns queued row sets in call order; args are ignored (no bind params here)."""

    def __init__(self, results):
        self._results = list(results)

    async def fetch(self, query, *args):
        return self._results.pop(0)


def _run(results):
    return asyncio.run(repo.get_hidden_summary(FakeConn(results)))


def test_merges_totals_with_per_reason_breakdown():
    totals = [
        {"bank": "sber", "hidden_services": 1, "hidden_methods": 3},
        {"bank": "tbank", "hidden_services": 0, "hidden_methods": 0},
    ]
    by_reason = [
        {"bank": "sber", "hidden_reason": "private", "cnt": 2},
        {"bank": "sber", "hidden_reason": "ghost", "cnt": 1},
    ]
    result = _run([totals, by_reason])
    assert result == [
        {"bank": "sber", "hidden_services": 1, "hidden_methods": 3,
         "by_reason": {"private": 2, "ghost": 1}},
        {"bank": "tbank", "hidden_services": 0, "hidden_methods": 0, "by_reason": {}},
    ]


def test_bank_with_no_hidden_methods_gets_empty_reason_breakdown():
    totals = [{"bank": "alfabank", "hidden_services": 0, "hidden_methods": 0}]
    result = _run([totals, []])
    assert result == [
        {"bank": "alfabank", "hidden_services": 0, "hidden_methods": 0, "by_reason": {}}
    ]
