"""Unit tests for DiffEngine."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.base_parser import APIMethod, ParseSnapshot
from storage.diff_engine import DiffEngine


def _method(bank, service, verb, path, summary="", fields=None):
    return APIMethod(
        bank=bank,
        service_name=service,
        http_method=verb,
        path=path,
        summary=summary,
        description="",
        response_200_fields=fields or [],
        parsed_at="2026-05-27T10:00:00",
        url_on_portal="https://example.com",
    )


def _snapshot(bank, services_dict, date="2026-05-27T10:00:00"):
    total_methods = sum(len(v) for v in services_dict.values())
    return ParseSnapshot(
        bank=bank,
        parsed_at=date,
        services=services_dict,
        total_services=len(services_dict),
        total_methods=total_methods,
    )


def test_no_changes():
    m = _method("tbank", "Платежи", "POST", "/payments")
    old = _snapshot("tbank", {"Платежи": [m]})
    new = _snapshot("tbank", {"Платежи": [m]}, date="2026-05-28T10:00:00")

    engine = DiffEngine()
    result = engine.compare(old, new)

    assert result is not None
    assert not result.has_changes
    assert result.added_methods == []
    assert result.removed_methods == []


def test_added_service():
    m1 = _method("tbank", "Платежи", "POST", "/payments")
    m2 = _method("tbank", "Счета", "GET", "/accounts")

    old = _snapshot("tbank", {"Платежи": [m1]})
    new = _snapshot("tbank", {"Платежи": [m1], "Счета": [m2]}, date="2026-05-28T10:00:00")

    engine = DiffEngine()
    result = engine.compare(old, new)

    assert "Счета" in result.added_services
    assert result.removed_services == []
    assert len(result.added_methods) == 1
    assert result.added_methods[0].path == "/accounts"


def test_removed_service():
    m1 = _method("tbank", "Платежи", "POST", "/payments")
    m2 = _method("tbank", "Счета", "GET", "/accounts")

    old = _snapshot("tbank", {"Платежи": [m1], "Счета": [m2]})
    new = _snapshot("tbank", {"Платежи": [m1]}, date="2026-05-28T10:00:00")

    engine = DiffEngine()
    result = engine.compare(old, new)

    assert "Счета" in result.removed_services
    assert result.added_services == []
    assert len(result.removed_methods) == 1
    assert result.removed_methods[0].path == "/accounts"


def test_added_method():
    m1 = _method("tochka", "Платежи", "POST", "/payments")
    m2 = _method("tochka", "Платежи", "GET", "/payments/{id}")

    old = _snapshot("tochka", {"Платежи": [m1]})
    new = _snapshot("tochka", {"Платежи": [m1, m2]}, date="2026-05-28T10:00:00")

    engine = DiffEngine()
    result = engine.compare(old, new)

    assert len(result.added_methods) == 1
    assert result.added_methods[0].path == "/payments/{id}"
    assert result.added_methods[0].http_method == "GET"


def test_removed_method():
    m1 = _method("tochka", "Платежи", "POST", "/payments")
    m2 = _method("tochka", "Платежи", "GET", "/payments/{id}")

    old = _snapshot("tochka", {"Платежи": [m1, m2]})
    new = _snapshot("tochka", {"Платежи": [m1]}, date="2026-05-28T10:00:00")

    engine = DiffEngine()
    result = engine.compare(old, new)

    assert len(result.removed_methods) == 1
    assert result.removed_methods[0].path == "/payments/{id}"


def test_changed_response_fields():
    m_old = _method("sber", "Счета", "GET", "/accounts", fields=["id", "balance", "currency"])
    m_new = _method("sber", "Счета", "GET", "/accounts", fields=["id", "balance", "currency", "iban"])

    old = _snapshot("sber", {"Счета": [m_old]})
    new = _snapshot("sber", {"Счета": [m_new]}, date="2026-05-28T10:00:00")

    engine = DiffEngine()
    result = engine.compare(old, new)

    assert len(result.changed_methods) == 1
    changed = result.changed_methods[0]
    assert "+iban" in changed.changed_fields
    assert result.added_methods == []


def test_removed_field():
    m_old = _method("sber", "Счета", "GET", "/accounts", fields=["id", "balance", "old_field"])
    m_new = _method("sber", "Счета", "GET", "/accounts", fields=["id", "balance"])

    old = _snapshot("sber", {"Счета": [m_old]})
    new = _snapshot("sber", {"Счета": [m_new]}, date="2026-05-28T10:00:00")

    engine = DiffEngine()
    result = engine.compare(old, new)

    assert len(result.changed_methods) == 1
    assert "-old_field" in result.changed_methods[0].changed_fields


def test_none_snapshots():
    engine = DiffEngine()
    assert engine.compare(None, None) is None
    assert engine.compare(None, _snapshot("tbank", {})) is None


def test_summary_text_no_changes():
    m = _method("tbank", "Платежи", "POST", "/payments")
    old = _snapshot("tbank", {"Платежи": [m]})
    new = _snapshot("tbank", {"Платежи": [m]}, date="2026-05-28T10:00:00")

    result = DiffEngine().compare(old, new)
    assert "No changes" in result.summary_text()


def test_summary_text_with_changes():
    m1 = _method("tbank", "Платежи", "POST", "/payments")
    m2 = _method("tbank", "Счета", "GET", "/accounts")

    old = _snapshot("tbank", {"Платежи": [m1]})
    new = _snapshot("tbank", {"Платежи": [m1], "Счета": [m2]}, date="2026-05-28T10:00:00")

    result = DiffEngine().compare(old, new)
    text = result.summary_text()
    assert "Added services" in text or "добавлен" in text.lower() or "Счета" in text


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
