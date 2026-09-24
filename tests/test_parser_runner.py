"""ParserRunner status transitions, error isolation and notifications (offline)."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from app import parser_runner as pr
from app.diff import Change
from app.snapshot_import import SnapshotRejected
from bank_api_parser.parsers.base_parser import APIMethod, HIDDEN_REASON_PRIVATE, ParserError, ParseSnapshot


def _api(path, hidden=False, hidden_reason=None):
    return APIMethod(
        bank="x", service_name="S", http_method="GET", path=path, summary="Op",
        description="", response_200_fields=[], parsed_at="", url_on_portal="",
        hidden=hidden, hidden_reason=hidden_reason,
    )


# 1 service, 3 visible methods — used to check the runner reports real (visible)
# counts rather than blindly trusting total_services/total_methods below.
SNAP = ParseSnapshot(
    bank="x", parsed_at="", services={"S": [_api("/a"), _api("/b"), _api("/c")]},
    total_services=1, total_methods=3,
)
CHANGE = Change("method", "added", "GET /a", "S / GET /a")


class FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


class FakeNotifier:
    def __init__(self, fail=False):
        self.digests, self.admin, self.fail = [], [], fail

    async def broadcast(self, texts):
        if self.fail:
            raise RuntimeError("telegram down")
        self.digests.append(list(texts))

    async def send_admin(self, text):
        if self.fail:
            raise RuntimeError("telegram down")
        self.admin.append(text)


def _parser_returning(result):
    class P:
        def parse(self):
            if isinstance(result, Exception):
                raise result
            return result
    return P


@pytest.fixture
def wire(monkeypatch):
    """Map bank -> parse result; import_snapshot returns imports[bank] (default [CHANGE])."""
    def install(results, imports=None):
        monkeypatch.setattr(pr, "parser_class", lambda bank: _parser_returning(results[bank]))

        async def fake_import(conn, bank, snapshot, *, min_ratio, keep):
            outcome = (imports or {}).get(bank, [CHANGE])
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        monkeypatch.setattr(pr, "import_snapshot", fake_import)
    return install


def test_reported_counts_exclude_hidden_methods_and_services(wire):
    snap = ParseSnapshot(
        bank="x", parsed_at="",
        services={
            "S": [_api("/a"), _api("/b", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
            "Priv": [_api("/p", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
        },
        total_services=2, total_methods=3,
    )
    wire({"sber": snap})
    runner = pr.ParserRunner(FakePool())
    asyncio.run(runner.run_all(("sber",)))
    assert runner.status.banks["sber"].services == 1
    assert runner.status.banks["sber"].methods == 1


def test_one_failing_bank_does_not_stop_others(wire):
    wire({"tbank": ParserError("boom"), "sber": SNAP})
    runner = pr.ParserRunner(FakePool())
    asyncio.run(runner.run_all(("tbank", "sber")))

    status = runner.status.to_dict()
    assert status["running"] is False and status["finished_at"]
    assert status["banks"]["tbank"]["status"] == "error"
    assert status["banks"]["tbank"]["error"] == "boom"
    assert status["banks"]["sber"] == {**status["banks"]["sber"],
                                       "status": "done", "services": 1, "methods": 3, "changes": 1}
    assert status["banks"]["tochka"]["status"] == "pending"


def test_none_snapshot_is_an_error(wire):
    wire({"tochka": None})
    runner = pr.ParserRunner(FakePool())
    asyncio.run(runner.run_all(("tochka",)))
    assert runner.status.banks["tochka"].error == "parser returned no data"


def test_one_digest_per_run_covering_all_banks(wire):
    wire({"tbank": SNAP, "sber": SNAP})
    notifier = FakeNotifier()
    asyncio.run(pr.ParserRunner(FakePool(), notifier).run_all(("tbank", "sber")))
    [digest] = notifier.digests
    text = "\n".join(digest)
    assert "Т-Банк" in text and "Сбер" in text and "GET /a" in text
    assert notifier.admin == []


def test_no_changes_means_silence(wire):
    wire({"sber": SNAP}, imports={"sber": []})
    notifier = FakeNotifier()
    asyncio.run(pr.ParserRunner(FakePool(), notifier).run_all(("sber",)))
    assert notifier.digests == [] and notifier.admin == []


def test_failure_alerts_only_on_transition(wire):
    notifier = FakeNotifier()
    runner = pr.ParserRunner(FakePool(), notifier)

    wire({"sber": ParserError("spec 500")})
    asyncio.run(runner.run_all(("sber",)))
    asyncio.run(runner.run_all(("sber",)))          # still failing: no second alert
    assert len(notifier.admin) == 1
    assert "Сбер" in notifier.admin[0] and "spec 500" in notifier.admin[0]

    wire({"sber": SNAP}, imports={"sber": []})
    asyncio.run(runner.run_all(("sber",)))          # recovered
    assert notifier.admin[-1] == "✅ <b>Сбер</b>: разбор снова проходит"
    asyncio.run(runner.run_all(("sber",)))          # healthy: nothing new
    assert len(notifier.admin) == 2


def test_rejected_snapshot_alert(wire):
    wire({"tochka": SNAP}, imports={"tochka": SnapshotRejected("1 methods vs 66")})
    notifier = FakeNotifier()
    asyncio.run(pr.ParserRunner(FakePool(), notifier).run_all(("tochka",)))
    [alert] = notifier.admin
    assert "снимок отклонён" in alert and "1 methods vs 66" in alert
    assert notifier.digests == []


def test_digest_uses_dashboard_url(wire):
    many = [Change("method", "added", f"GET /m{i}", f"S / GET /m{i}") for i in range(12)]
    wire({"sber": SNAP}, imports={"sber": many})
    notifier = FakeNotifier()
    runner = pr.ParserRunner(FakePool(), notifier, dashboard_url="https://mon.example/")
    asyncio.run(runner.run_all(("sber",)))
    assert 'href="https://mon.example/changes"' in notifier.digests[0][-1]


def test_notifier_failures_do_not_break_the_run(wire):
    wire({"sber": SNAP, "tbank": ParserError("x")})
    runner = pr.ParserRunner(FakePool(), FakeNotifier(fail=True))
    asyncio.run(runner.run_all(("tbank", "sber")))
    assert runner.status.banks["sber"].status == "done"
    assert runner.status.running is False


def test_concurrent_run_is_skipped(wire):
    wire({"sber": SNAP})
    runner = pr.ParserRunner(FakePool())

    async def scenario():
        await runner._lock.acquire()
        try:
            await runner.run_all(("sber",))  # returns immediately
        finally:
            runner._lock.release()

    asyncio.run(scenario())
    assert runner.status.banks["sber"].status == "pending"


def test_unexpected_error_text_is_not_exposed(wire):
    wire({"sber": KeyError("postgres://secret-host")})
    runner = pr.ParserRunner(FakePool())
    asyncio.run(runner.run_all(("sber",)))
    assert runner.status.banks["sber"].error == "internal error (KeyError), see server logs"


def test_digest_formatting_bug_still_sends_admin_alerts(wire, monkeypatch):
    def boom(*a, **kw):
        raise ValueError("formatter bug")
    monkeypatch.setattr(pr.notify_format, "build_digest", boom)
    wire({"tbank": SNAP, "sber": ParserError("down")})
    notifier = FakeNotifier()
    asyncio.run(pr.ParserRunner(FakePool(), notifier).run_all(("tbank", "sber")))
    assert notifier.digests == [] and len(notifier.admin) == 1


def test_proxy_rotator_is_active_only_during_the_run(wire, monkeypatch):
    from bank_api_parser import proxy
    seen = []

    class P:
        def parse(self):
            seen.append(proxy.active())
            return SNAP
    monkeypatch.setattr(pr, "parser_class", lambda bank: P)
    wire_imports = {}
    rot = proxy.ProxyRotator(["http://a:1"])

    async def source():
        return rot
    runner = pr.ParserRunner(FakePool(), proxy_source=source)

    async def fake_import(conn, bank, snapshot, *, min_ratio, keep):
        return wire_imports.get(bank, [])
    monkeypatch.setattr(pr, "import_snapshot", fake_import)
    asyncio.run(runner.run_all(("sber",)))
    assert seen == [rot] and proxy.active() is None


def test_proxy_source_failure_falls_back_to_direct(wire):
    from bank_api_parser import proxy
    wire({"sber": SNAP})

    async def broken():
        raise RuntimeError("db down")
    runner = pr.ParserRunner(FakePool(), proxy_source=broken)
    asyncio.run(runner.run_all(("sber",)))
    assert runner.status.banks["sber"].status == "done" and proxy.active() is None
