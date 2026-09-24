"""Unit tests for the pure parts of app.snapshot_import."""
import pytest

from app.diff import MethodRecord
from app.snapshot_import import SnapshotRejected, check_sanity, snapshot_to_records, visible_counts
from bank_api_parser.parsers.base_parser import APIMethod, HIDDEN_REASON_PRIVATE, ParseSnapshot


def _api(service, http, path, fields=None, url="https://portal/x", summary="Op",
         hidden=False, hidden_reason=None):
    return APIMethod(
        bank="tbank", service_name=service, http_method=http, path=path,
        summary=summary, description="", response_200_fields=fields,
        parsed_at="", url_on_portal=url, hidden=hidden, hidden_reason=hidden_reason,
    )


def _snap(services):
    return ParseSnapshot(
        bank="tbank", parsed_at="", services=services,
        total_services=len(services),
        total_methods=sum(len(v) for v in services.values()),
    )


def test_snapshot_to_records_maps_services_and_methods():
    snap = _snap({"Acc": [_api("Acc", "GET", "/a", ["id", "name"], url="https://p/acc")]})
    services, methods = snapshot_to_records(snap)
    assert services == {"Acc": "https://p/acc"}
    assert methods == [MethodRecord("Acc", "GET", "/a", "Op", "https://p/acc", frozenset({"id", "name"}))]


def test_snapshot_to_records_handles_empty_service_and_none_fields():
    snap = _snap({"Empty": [], "S": [_api("S", "POST", "/b", None)]})
    services, methods = snapshot_to_records(snap)
    assert services == {"Empty": "", "S": "https://portal/x"}
    assert methods[0].fields == frozenset()


def test_check_sanity_rejects_empty_snapshot():
    with pytest.raises(SnapshotRejected):
        check_sanity(prev_methods=None, new_methods=0, min_ratio=0.5)


def test_check_sanity_accepts_first_non_empty_snapshot():
    check_sanity(prev_methods=None, new_methods=10, min_ratio=0.5)


def test_check_sanity_rejects_sharp_drop():
    with pytest.raises(SnapshotRejected, match="49"):
        check_sanity(prev_methods=100, new_methods=49, min_ratio=0.5)


def test_check_sanity_accepts_drop_within_ratio():
    check_sanity(prev_methods=100, new_methods=50, min_ratio=0.5)


def test_check_sanity_disabled_with_zero_ratio():
    check_sanity(prev_methods=100, new_methods=1, min_ratio=0)


# ── Hidden services/methods ──────────────────────────────────────────────────

def test_snapshot_to_records_carries_hidden_flags():
    snap = _snap({"Priv": [_api("Priv", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)]})
    _, methods = snapshot_to_records(snap)
    assert methods == [
        MethodRecord("Priv", "GET", "/a", "Op", "https://portal/x", frozenset(),
                      hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)
    ]


def test_visible_counts_excludes_hidden_methods():
    snap = _snap({
        "Acc": [_api("Acc", "GET", "/a"), _api("Acc", "GET", "/b", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
    })
    assert visible_counts(snap) == (1, 1)


def test_visible_counts_excludes_fully_hidden_service():
    snap = _snap({
        "Acc": [_api("Acc", "GET", "/a")],
        "Priv": [_api("Priv", "GET", "/p", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
    })
    assert visible_counts(snap) == (1, 1)


def test_visible_counts_keeps_empty_service_visible():
    snap = _snap({"Empty": [], "Acc": [_api("Acc", "GET", "/a")]})
    assert visible_counts(snap) == (2, 1)


def test_visible_counts_partially_hidden_service_still_visible():
    snap = _snap({
        "Mix": [_api("Mix", "GET", "/a"), _api("Mix", "GET", "/b", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)],
    })
    assert visible_counts(snap) == (1, 1)
