"""Tests for T-Bank's 3-space (T-API / partner API / private) parser.

All specs are served from an in-memory fake session — no live network calls.
"""
import requests

from bank_api_parser.parsers.base_parser import HIDDEN_REASON_PRIVATE
from bank_api_parser.parsers.tbank_parser import (
    PORTAL_PARTNER,
    PORTAL_PRIVATE,
    PORTAL_TAPI,
    SPEC_URL_PARTNER,
    SPEC_URL_PRIVATE,
    SPEC_URL_TAPI,
    TBankParser,
)


def _op(operation_id, tag, summary="", schema=None):
    return {
        "tags": [tag],
        "summary": summary,
        "operationId": operation_id,
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": schema or {"type": "object", "properties": {"id": {"type": "string"}}}
                    }
                }
            }
        },
    }


TAPI_SPEC = {
    "openapi": "3.0.0",
    "tags": [
        {"name": "Заявки", "x-parent-tag": "Эквайринг"},
    ],
    "paths": {
        "/acq/applications": {"get": _op("getApplications", "Заявки")},
        "/acq/status": {"get": _op("getStatus", "Статус")},
    },
}

PARTNER_SPEC = {
    "openapi": "3.0.0",
    "tags": [],
    "paths": {
        "/partner/orders": {"get": _op("getOrders", "Заказы")},
    },
}

PRIVATE_SPEC = {
    "openapi": "3.0.0",
    "tags": [
        {"name": "Внутренние заявки", "x-parent-tag": "Эквайринг"},
    ],
    "paths": {
        "/private/internal": {"get": _op("getInternal", "Внутренние заявки")},
    },
}


class _Resp:
    def __init__(self, json_body, status=200):
        import json as _json

        self.text = _json.dumps(json_body)
        self.status_code = status
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        data = self.text.encode("utf-8")
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]


class _RoutedSession:
    """Maps exact URLs (as used by the parser) to canned responses."""

    def __init__(self, routes):
        self.routes = routes

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        if url not in self.routes:
            raise AssertionError(f"unexpected URL requested: {url}")
        result = self.routes[url]
        if isinstance(result, Exception):
            raise result
        return result


def _parser_with_routes(routes):
    parser = TBankParser()
    parser.session = _RoutedSession(routes)
    return parser


def _default_routes():
    return {
        SPEC_URL_TAPI: _Resp(TAPI_SPEC),
        SPEC_URL_PARTNER: _Resp(PARTNER_SPEC),
        SPEC_URL_PRIVATE: _Resp(PRIVATE_SPEC),
    }


def test_parse_merges_tapi_and_partner_into_visible_set():
    parser = _parser_with_routes(_default_routes())
    snapshot = parser.parse()

    visible = {
        svc: methods for svc, methods in snapshot.services.items()
        if not any(m.hidden for m in methods)
    }
    assert "Эквайринг. Заявки" in visible
    assert "Статус" in visible
    assert "Заказы" in visible


def test_x_parent_tag_renames_service_to_parent_dot_child():
    parser = _parser_with_routes(_default_routes())
    snapshot = parser.parse()

    assert "Заявки" not in snapshot.services
    (method,) = snapshot.services["Эквайринг. Заявки"]
    assert method.service_name == "Эквайринг. Заявки"
    assert method.hidden is False


def test_tag_without_x_parent_tag_is_left_unprefixed():
    parser = _parser_with_routes(_default_routes())
    snapshot = parser.parse()

    (method,) = snapshot.services["Статус"]
    assert method.service_name == "Статус"


def test_private_space_methods_are_marked_hidden_not_dropped():
    parser = _parser_with_routes(_default_routes())
    snapshot = parser.parse()

    assert "Эквайринг. Внутренние заявки" in snapshot.services
    (method,) = snapshot.services["Эквайринг. Внутренние заявки"]
    assert method.hidden is True
    assert method.hidden_reason == HIDDEN_REASON_PRIVATE


def test_private_methods_still_carry_full_field_and_example_data():
    parser = _parser_with_routes(_default_routes())
    snapshot = parser.parse()

    (method,) = snapshot.services["Эквайринг. Внутренние заявки"]
    assert "id" in method.response_200_fields
    assert method.http_method == "GET"
    assert method.path == "/private/internal"


def test_snapshot_totals_count_visible_and_hidden_methods_together():
    parser = _parser_with_routes(_default_routes())
    snapshot = parser.parse()

    assert snapshot.total_services == 4
    assert snapshot.total_methods == 4
    hidden_count = sum(1 for methods in snapshot.services.values() for m in methods if m.hidden)
    assert hidden_count == 1


def test_portal_url_uses_kebab_slug_of_operation_id_per_space():
    parser = _parser_with_routes(_default_routes())
    snapshot = parser.parse()

    (tapi_method,) = snapshot.services["Эквайринг. Заявки"]
    assert tapi_method.url_on_portal == f"{PORTAL_TAPI}/get-applications"

    (partner_method,) = snapshot.services["Заказы"]
    assert partner_method.url_on_portal == f"{PORTAL_PARTNER}/get-orders"

    (private_method,) = snapshot.services["Эквайринг. Внутренние заявки"]
    assert private_method.url_on_portal == f"{PORTAL_PRIVATE}/get-internal"


def test_same_tag_in_two_spaces_accumulates_methods_instead_of_overwriting():
    """Т-Банк отдаёт три спеки, и один и тот же тег встречается в нескольких.
    Слияние должно складывать методы: раньше словарь перезаписывался и методы
    из второй спеки теряли методы из первой.
    """
    partner_with_shared_tag = {
        "openapi": "3.0.0",
        "tags": [],
        "paths": {
            "/partner/orders": {"get": _op("getOrders", "Заказы")},
            "/partner/status": {"get": _op("getPartnerStatus", "Статус")},
        },
    }
    routes = _default_routes()
    routes[SPEC_URL_PARTNER] = _Resp(partner_with_shared_tag)
    snapshot = _parser_with_routes(routes).parse()

    paths = {m.path for m in snapshot.services["Статус"]}
    assert paths == {"/acq/status", "/partner/status"}


def test_portal_url_falls_back_to_base_when_no_operation_id():
    parser = TBankParser()
    assert parser._portal_url("https://p", "Tag", "") == "https://p"


def test_kebab_splits_camel_case_and_digit_boundaries():
    assert TBankParser._kebab("listAccounts") == "list-accounts"
    assert TBankParser._kebab("getPaymentOperationListAcquiringV1_0") == (
        "get-payment-operation-list-acquiring-v-1-0"
    )
    assert TBankParser._kebab("") == ""


def test_apply_parent_tags_is_noop_when_spec_has_no_x_parent_tag():
    spec = {"tags": [{"name": "Только тег"}], "paths": {}}
    result = TBankParser._apply_parent_tags(spec)
    assert result is spec
