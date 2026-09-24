"""import_snapshot transaction flow with a fake connection and repository (offline)."""
import asyncio
from contextlib import asynccontextmanager

import pytest

from app import snapshot_import as si
from app.diff import MethodRecord
from bank_api_parser.parsers.base_parser import APIMethod, HIDDEN_REASON_PRIVATE, ParseSnapshot


def _api(service, path, fields=("id",), hidden=False, hidden_reason=None):
    return APIMethod(
        bank="tbank", service_name=service, http_method="GET", path=path,
        summary="Op", description="", response_200_fields=list(fields),
        parsed_at="", url_on_portal=f"https://p/{service}",
        hidden=hidden, hidden_reason=hidden_reason,
    )


def _snap(services):
    return ParseSnapshot(
        bank="tbank", parsed_at="", services=services,
        total_services=len(services),
        total_methods=sum(len(v) for v in services.values()),
    )


class FakeConn:
    def __init__(self):
        self.tx_entered = self.tx_exited_with_error = False

    @asynccontextmanager
    async def transaction(self):
        self.tx_entered = True
        try:
            yield
        except BaseException:
            self.tx_exited_with_error = True
            raise


class FakeRepo:
    """Records every write; the previous snapshot state is configurable."""

    def __init__(self, prev_state=None, cleanup=()):
        self.prev_state, self.cleanup = prev_state, list(cleanup)
        self.calls = []

    async def get_latest_snapshot(self, conn, bank):
        return {"id": 1} if self.prev_state else None

    async def get_snapshot_state(self, conn, snap_id):
        return self.prev_state

    async def create_snapshot(self, conn, bank):
        self.calls.append(("snapshot", bank))
        return 2

    async def create_service(self, conn, snap_id, name, url, hidden=False):
        self.calls.append(("service", name, hidden))
        return 10

    async def create_method(self, conn, svc_id, **kw):
        self.calls.append(("method", kw["path"], kw.get("hidden", False), kw.get("hidden_reason")))
        return 100

    async def create_fields(self, conn, method_id, fields):
        self.calls.append(("fields", tuple(fields)))

    async def create_changes(self, conn, snap_id, bank, changes):
        self.calls.append(("changes", len(changes)))

    async def get_snapshots_for_cleanup(self, conn, bank, keep):
        self.calls.append(("cleanup_query", keep))
        return self.cleanup

    async def delete_snapshots(self, conn, ids):
        self.calls.append(("delete", tuple(ids)))


@pytest.fixture
def fake_repo(monkeypatch):
    def install(**kw):
        repo = FakeRepo(**kw)
        monkeypatch.setattr(si, "repo", repo)
        return repo
    return install


def _run(conn, snap, **kw):
    return asyncio.run(si.import_snapshot(conn, "tbank", snap, min_ratio=0.5, keep=7, **kw))


def test_first_snapshot_is_stored_without_changes(fake_repo):
    repo = fake_repo(cleanup=[])
    conn = FakeConn()
    changes = _run(conn, _snap({"Acc": [_api("Acc", "/a", ("b", "a"))]}))
    assert changes == []
    assert conn.tx_entered
    assert repo.calls == [
        ("snapshot", "tbank"), ("service", "Acc", False), ("method", "/a", False, None),
        ("fields", ("a", "b")), ("changes", 0), ("cleanup_query", 7), ("delete", ()),
    ]


def test_second_snapshot_records_diff_and_prunes(fake_repo):
    prev = ({"Acc": "https://p/Acc"},
            [MethodRecord("Acc", "GET", "/a", "Op", "https://p/Acc", frozenset({"id"}))])
    repo = fake_repo(prev_state=prev, cleanup=[1])
    changes = _run(FakeConn(), _snap({"Acc": [_api("Acc", "/a"), _api("Acc", "/b")]}))
    assert [(c.change_type, c.action, c.entity_path) for c in changes] == [("method", "added", "Acc / GET /b")]
    assert ("changes", 1) in repo.calls
    assert repo.calls[-1] == ("delete", (1,))


def test_sharp_drop_is_rejected_before_any_write(fake_repo):
    prev = ({"Acc": ""}, [MethodRecord("Acc", "GET", f"/{i}", "Op", "", frozenset()) for i in range(10)])
    repo = fake_repo(prev_state=prev)
    conn = FakeConn()
    with pytest.raises(si.SnapshotRejected):
        _run(conn, _snap({"Acc": [_api("Acc", "/0")]}))
    assert repo.calls == []
    assert conn.tx_exited_with_error


# ── Hidden services/methods ──────────────────────────────────────────────────

def test_hidden_changes_are_stored_but_not_returned(fake_repo):
    prev = ({"Acc": "https://p/Acc"},
            [MethodRecord("Acc", "GET", "/a", "Op", "https://p/Acc", frozenset({"id"}))])
    repo = fake_repo(prev_state=prev, cleanup=[])
    changes = _run(FakeConn(), _snap({
        "Acc": [_api("Acc", "/a"), _api("Acc", "/hidden", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
    }))
    # The caller only ever sees the visible change; the hidden add is still persisted.
    assert [(c.action, c.entity_path) for c in changes] == []
    stored = next(c for c in repo.calls if c[0] == "changes")
    assert stored == ("changes", 1)


def test_fully_hidden_service_is_stored_with_hidden_flag(fake_repo):
    # A visible service keeps the snapshot from being rejected as entirely hidden.
    repo = fake_repo(cleanup=[])
    _run(FakeConn(), _snap({
        "Acc": [_api("Acc", "/a")],
        "Priv": [_api("Priv", "/p", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
    }))
    assert ("service", "Priv", True) in repo.calls
    assert ("method", "/p", True, HIDDEN_REASON_PRIVATE) in repo.calls


def test_partially_hidden_service_is_not_marked_hidden(fake_repo):
    repo = fake_repo(cleanup=[])
    _run(FakeConn(), _snap({
        "Mix": [_api("Mix", "/a"), _api("Mix", "/b", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
    }))
    assert ("service", "Mix", False) in repo.calls


def test_sanity_check_uses_visible_counts_only(fake_repo):
    """10 previously-visible methods now all hidden -> 0 visible -> rejected,
    even though the raw (hidden-included) count looks unchanged."""
    prev = ({"Acc": ""}, [MethodRecord("Acc", "GET", f"/{i}", "Op", "", frozenset()) for i in range(10)])
    repo = fake_repo(prev_state=prev)
    conn = FakeConn()
    with pytest.raises(si.SnapshotRejected):
        _run(conn, _snap({
            "Acc": [_api("Acc", f"/{i}", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE) for i in range(10)],
        }))
    assert repo.calls == []
    assert conn.tx_exited_with_error


def test_entirely_hidden_snapshot_is_rejected_as_the_first_snapshot(fake_repo):
    repo = fake_repo()
    conn = FakeConn()
    with pytest.raises(si.SnapshotRejected, match="0 methods"):
        _run(conn, _snap({"Priv": [_api("Priv", "/p", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)]}))
    assert repo.calls == []
