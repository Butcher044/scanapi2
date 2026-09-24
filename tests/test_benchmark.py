"""Benchmark matching: capabilities vs. services by service name and method paths."""
import re

import pytest

from app import benchmark as bm
from app.benchmark_catalog import CATALOG, Capability

STATEMENT = Capability(
    key="statement", group="Счета", title="Выписка",
    paths=r"statement", names=r"выписк", exclude=r"digital-ruble",
)
PAYROLL = Capability(key="payroll", group="Персонал", title="Зарплатный проект", paths=r"salary|payroll")
CATALOG_2 = (STATEMENT, PAYROLL)
BANKS = ("tbank", "alfabank")


def svc(name, *paths):
    return bm.ServiceInfo(name=name, paths=tuple(paths))


def test_name_match_counts_every_method_of_the_service():
    ev = bm.match(STATEMENT, svc("Счета и выписки", "/api/v1/bank-accounts", "/api/v1/statement"))
    assert ev == bm.Evidence(service="Счета и выписки", matched=2, total=2, by_name=True)


def test_path_match_counts_only_matching_methods():
    ev = bm.match(PAYROLL, svc("Сотрудники", "/api/v1/salary/list", "/api/v1/employees", "/v1/payrolls/{id}"))
    assert ev == bm.Evidence(service="Сотрудники", matched=2, total=3, by_name=False)


def test_matching_ignores_case():
    assert bm.match(STATEMENT, svc("ВЫПИСКИ")) is not None
    assert bm.match(STATEMENT, svc("X", "/V2/Statement/Summary")) is not None


def test_no_match_gives_none():
    assert bm.match(PAYROLL, svc("Выписки", "/v1/statement")) is None


def test_excluded_paths_do_not_count():
    assert bm.match(STATEMENT, svc("Цифровой рубль", "/jp/v1/digital-ruble/statement/transactions")) is None


def test_excluded_name_does_not_match_by_name_but_paths_still_count():
    cap = Capability(key="k", group="g", title="t", paths=r"/payments", names=r"плат", exclude=r"валют")
    assert bm.match(cap, svc("Валютное платежное поручение", "/v1/pay-doc-cur")) is None
    assert bm.match(cap, svc("Валютные платежи", "/v1/payments")) == bm.Evidence("Валютные платежи", 1, 1, False)


def test_build_marks_presence_and_lists_evidence():
    result = bm.build(
        {
            "tbank": [svc("Счета и выписки", "/api/v1/statement"), svc("Зарплатный проект", "/api/v1/salary")],
            "alfabank": [svc("Выписки по счетам ЮЛ", "/jp/v1/statement/summary")],
        },
        overrides={}, banks=BANKS, catalog=CATALOG_2,
    )
    statement, payroll = result.rows
    assert statement.capability is STATEMENT
    assert statement.cells["tbank"].present and statement.cells["alfabank"].present
    assert [e.service for e in statement.cells["alfabank"].evidence] == ["Выписки по счетам ЮЛ"]
    assert payroll.cells["tbank"].present and not payroll.cells["alfabank"].present
    assert payroll.cells["alfabank"].evidence == ()


def test_evidence_is_sorted_by_matched_methods_then_name():
    result = bm.build(
        {"tbank": [svc("Б", "/statement"), svc("А", "/statement"), svc("В", "/statement", "/statement/x")]},
        overrides={}, banks=("tbank",), catalog=(STATEMENT,),
    )
    assert [e.service for e in result.rows[0].cells["tbank"].evidence] == ["В", "А", "Б"]


def test_override_wins_but_keeps_auto_value_and_evidence():
    result = bm.build(
        {"tbank": [svc("Счета и выписки", "/api/v1/statement")], "alfabank": []},
        overrides={("statement", "tbank"): False, ("payroll", "alfabank"): True},
        banks=BANKS, catalog=CATALOG_2,
    )
    statement, payroll = result.rows
    tb = statement.cells["tbank"]
    assert (tb.present, tb.auto, tb.override, len(tb.evidence)) == (False, True, False, 1)
    alfa = payroll.cells["alfabank"]
    assert (alfa.present, alfa.auto, alfa.override) == (True, False, True)


def test_overrides_for_unknown_capabilities_or_banks_are_ignored():
    result = bm.build({}, overrides={("gone", "tbank"): True, ("statement", "vtb"): True},
                      banks=BANKS, catalog=CATALOG_2)
    assert all(not c.present and c.override is None for r in result.rows for c in r.cells.values())


def test_bank_without_data_has_all_minus():
    result = bm.build({"tbank": [svc("Выписки")]}, overrides={}, banks=BANKS, catalog=CATALOG_2)
    assert all(not r.cells["alfabank"].present for r in result.rows)
    assert result.unmatched["alfabank"] == ()


def test_unmatched_services_are_listed_per_bank_sorted():
    result = bm.build(
        {"tbank": [svc("Отели", "/api/v1/hotel"), svc("Выписки"), svc("Автокредиты", "/api/v1/application")]},
        overrides={}, banks=BANKS, catalog=CATALOG_2,
    )
    assert result.unmatched == {"tbank": ("Автокредиты", "Отели"), "alfabank": ()}


def test_services_from_rows_groups_paths_and_keeps_services_without_methods():
    rows = [
        {"bank": "tbank", "service": "A", "path": "/a"},
        {"bank": "tbank", "service": "A", "path": "/b"},
        {"bank": "tbank", "service": "Empty", "path": None},
        {"bank": "sber", "service": "S", "path": ""},
    ]
    assert bm.services_from_rows(rows) == {
        "tbank": [svc("A", "/a", "/b"), svc("Empty")],
        "sber": [svc("S")],
    }


# ── Catalog sanity ────────────────────────────────────────────────────────────

def test_catalog_keys_and_titles_are_unique():
    assert len({c.key for c in CATALOG}) == len(CATALOG)
    assert len({c.title for c in CATALOG}) == len(CATALOG)


@pytest.mark.parametrize("cap", CATALOG, ids=lambda c: c.key)
def test_catalog_entries_are_valid(cap):
    assert re.fullmatch(r"[a-z][a-z0-9_]{1,40}", cap.key)
    assert cap.group and cap.title
    assert cap.paths or cap.names, "a capability must match by paths or by names"
    for pattern in (cap.paths, cap.names, cap.exclude):
        if pattern:
            re.compile(pattern)


def test_catalog_groups_are_contiguous():
    """The UI renders one header per group, so a group must not be split."""
    seen, last = [], None
    for cap in CATALOG:
        if cap.group != last:
            assert cap.group not in seen, f"group {cap.group!r} is split"
            seen.append(cap.group)
            last = cap.group
