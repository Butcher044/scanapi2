"""Tests for Tochka's 4-product parser (bank / pay-gateway / medusa / cyclops).

All specs and JS chunks are served from an in-memory fake session — no live network calls.
"""
import base64
import json
import logging
import zlib

import pytest
import requests

from bank_api_parser.parsers import tochka_parser
from bank_api_parser.parsers.base_parser import ParserError
from bank_api_parser.parsers.tochka_parser import (
    BANK_PORTAL_BASE,
    BANK_SPEC_URL,
    CYCLOPS_MAIN_JS,
    CYCLOPS_PORTAL_BASE,
    CYCLOPS_RUNTIME_JS,
    CYCLOPS_SITE_ROOT,
    MEDUSA_SPEC_URL,
    PAY_GATEWAY_SPEC_URL,
    TochkaParser,
)


def _op(operation_id, tag, summary=""):
    return {
        "tags": [tag],
        "summary": summary,
        "operationId": operation_id,
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "properties": {"id": {"type": "string"}}}
                    }
                }
            }
        },
    }


BANK_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/accounts": {"get": _op("listAccounts", "Счета")},
        "/webhooks": {"get": _op("getWebhooks", "Работа с вебхуками")},
    },
}

PAY_GATEWAY_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/links": {"get": _op("getPaymentLinks", "Платёжные ссылки")},
        "/webhooks": {"get": _op("getPayWebhooks", "Вебхуки")},
    },
}

MEDUSA_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/orders": {"get": _op("getOrders", "Заказы")},
    },
}


class _Resp:
    def __init__(
        self, body, status=200, is_json=True, location=None,
        headers=None, encoding="utf-8", body_encoding=None,
    ):
        self.text = json.dumps(body) if is_json else body
        self.status_code = status
        self.headers = headers if headers is not None else ({"Location": location} if location else {})
        # What requests.Response.encoding would report -- may differ from the
        # actual bytes on the wire (see _charset_of's docstring: `requests`
        # defaults this to ISO-8859-1 for text/* with no charset param).
        self.encoding = encoding
        # The actual bytes sent over the wire -- independent of what
        # `resp.encoding` claims; defaults to utf-8 like every real portal here.
        self._body_encoding = body_encoding or "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        """Тело по кускам — так его читает _get_text, чтобы оборваться на потолке."""
        data = self.text.encode(self._body_encoding)
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]


class _RoutedSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected URL requested: {url}")
        result = self.routes[url]
        if isinstance(result, Exception):
            raise result
        return result


def _parser_with_routes(routes):
    parser = TochkaParser()
    parser.session = _RoutedSession(routes)
    return parser


# ─── The 3 spec-backed products ────────────────────────────────────────────


def _spec_routes():
    return {
        BANK_SPEC_URL: _Resp(BANK_SPEC),
        PAY_GATEWAY_SPEC_URL: _Resp(PAY_GATEWAY_SPEC),
        MEDUSA_SPEC_URL: _Resp(MEDUSA_SPEC),
    }


def test_parse_product_prefixes_tags_with_product_name():
    parser = _parser_with_routes(_spec_routes())
    services = parser._parse_product(BANK_SPEC_URL, BANK_PORTAL_BASE, "Точка Банк")
    assert set(services) == {"Точка Банк. Счета", "Точка Банк. Работа с вебхуками"}


def test_webhooks_are_not_excluded_for_bank_or_pay_gateway_products():
    parser = _parser_with_routes(_spec_routes())
    bank = parser._parse_product(BANK_SPEC_URL, BANK_PORTAL_BASE, "Точка Банк")
    assert "Точка Банк. Работа с вебхуками" in bank


def test_different_products_do_not_collide_on_the_same_tag_name():
    """Medusa's own future "Заказы"-style tag must never merge with another
    product's tag of the same name once prefixed."""
    parser = _parser_with_routes(_spec_routes())
    medusa = parser._parse_product(MEDUSA_SPEC_URL, "https://m", "Безопасные сделки")
    bank = parser._parse_product(BANK_SPEC_URL, BANK_PORTAL_BASE, "Точка Банк")
    assert set(medusa) & set(bank) == set()


def test_portal_url_uses_kebab_slug_of_operation_id():
    parser = _parser_with_routes(_spec_routes())
    services = parser._parse_product(BANK_SPEC_URL, BANK_PORTAL_BASE, "Точка Банк")
    (method,) = services["Точка Банк. Счета"]
    assert method.url_on_portal == f"{BANK_PORTAL_BASE}/list-accounts"


def test_portal_url_falls_back_to_base_when_no_operation_id():
    parser = TochkaParser()
    assert parser._portal_url("https://p", "Tag", "") == "https://p"


def test_kebab_matches_lodash_style_slug_for_snake_case_with_digits():
    assert TochkaParser._kebab("get_payment_operation_list_acquiring_v1_0_payments_get") == (
        "get-payment-operation-list-acquiring-v-1-0-payments-get"
    )


# ─── Cyclops (nominal account): scraped from JS chunks, no spec ───────────


def _cyclops_operation():
    return {
        "tags": ["Документы"],
        "method": "get",
        "path": "/cyclops/documents",
        "operationId": "getDocuments",
        "description": "Список документов",
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"type": "object", "properties": {"id": {"type": "string"}}}
                    }
                }
            }
        },
    }


def _compressed_api_payload(operation: dict) -> str:
    return base64.b64encode(zlib.compress(json.dumps(operation).encode())).decode()


def _runtime_js(name_map: dict, hash_map: dict) -> str:
    name_obj = ",".join(f'{k}:"{v}"' for k, v in name_map.items())
    hash_obj = ",".join(f'{k}:"{v}"' for k, v in hash_map.items())
    return f'n.u=e=>"assets/js/"+(({{{name_obj}}})[e]||e)+"."+(({{{hash_obj}}})[e]+".js")'


def _main_js(routes: list) -> str:
    """`routes` is [(slug, content_hash)]."""
    entries = ",".join(
        f'"/docs/cyclops/api/{slug}-26f":{{"__comp":"4c5e977b","content":"{content_hash}"}}'
        for slug, content_hash in routes
    )
    return f"var routes = {{{entries}}};"


def _cyclops_happy_routes(extra=None):
    routes = {
        CYCLOPS_RUNTIME_JS: _Resp(_runtime_js({"1": "aaa111"}, {"1": "bbb222"}), is_json=False),
        CYCLOPS_MAIN_JS: _Resp(
            _main_js([("get-documents", "aaa111"), ("category-page", "ccc333")]), is_json=False
        ),
        f"{CYCLOPS_SITE_ROOT}/assets/js/aaa111.bbb222.js": _Resp(
            '{"api":"' + _compressed_api_payload(_cyclops_operation()) + '"}', is_json=False
        ),
    }
    if extra:
        routes.update(extra)
    return routes


def test_cyclops_decodes_operation_from_compressed_chunk_payload():
    parser = _parser_with_routes({**_spec_routes(), **_cyclops_happy_routes()})
    services = parser._parse_cyclops()

    assert "Номинальный счёт. Документы" in services
    (method,) = services["Номинальный счёт. Документы"]
    assert method.http_method == "GET"
    assert method.path == "/cyclops/documents"
    assert method.url_on_portal == f"{CYCLOPS_PORTAL_BASE}/get-documents"
    assert "id" in method.response_200_fields


def test_cyclops_skips_pages_with_no_matching_chunk_as_category_pages():
    parser = _parser_with_routes({**_spec_routes(), **_cyclops_happy_routes()})
    services = parser._parse_cyclops()

    total_methods = sum(len(v) for v in services.values())
    assert total_methods == 1  # only get-documents; category-page (unresolved chunk) skipped


def test_cyclops_skips_pages_whose_chunk_has_no_api_field():
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_MAIN_JS] = _Resp(
        _main_js([("get-documents", "aaa111"), ("landing", "ddd444")]), is_json=False
    )
    routes[CYCLOPS_RUNTIME_JS] = _Resp(
        _runtime_js({"1": "aaa111", "2": "ddd444"}, {"1": "bbb222", "2": "eee555"}), is_json=False
    )
    routes[f"{CYCLOPS_SITE_ROOT}/assets/js/ddd444.eee555.js"] = _Resp("{}", is_json=False)
    parser = _parser_with_routes({**_spec_routes(), **routes})

    services = parser._parse_cyclops()
    total_methods = sum(len(v) for v in services.values())
    assert total_methods == 1


def test_cyclops_raises_when_no_routes_found_in_main_js():
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_MAIN_JS] = _Resp("var routes = {};", is_json=False)
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="no method pages found"):
        parser._parse_cyclops()


def test_cyclops_raises_when_all_routes_are_category_pages():
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_MAIN_JS] = _Resp(_main_js([("category-page", "ccc333")]), is_json=False)
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="0 methods decoded"):
        parser._parse_cyclops()


def test_cyclops_raises_when_runtime_chunk_loader_not_found():
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_RUNTIME_JS] = _Resp("no chunk loader here", is_json=False)
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="n.u.*not found"):
        parser._parse_cyclops()


def test_cyclops_raises_when_runtime_chunk_loader_shape_is_unexpected():
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_RUNTIME_JS] = _Resp('n.u=e=>"assets/js/"+(something unexpected)', is_json=False)
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="unexpected shape"):
        parser._parse_cyclops()


def test_cyclops_raises_when_api_payload_is_not_valid_compressed_json():
    routes = _cyclops_happy_routes()
    routes[f"{CYCLOPS_SITE_ROOT}/assets/js/aaa111.bbb222.js"] = _Resp(
        '{"api":"not-valid-base64-zlib!!"}', is_json=False
    )
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="not valid compressed JSON"):
        parser._parse_cyclops()


def test_cyclops_rejects_an_oversized_remote_file(monkeypatch):
    """Чанки портала читаются потоком с потолком: раздутый (или подменённый) ответ
    не должен целиком оседать в памяти процесса."""
    monkeypatch.setattr(tochka_parser, "MAX_REMOTE_BYTES", 1024)
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_MAIN_JS] = _Resp("x" * 5000, is_json=False)
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="too large"):
        parser._parse_cyclops()


def test_cyclops_rejects_a_decompression_bomb(monkeypatch):
    """Маленький base64-блоб может развернуться в гигабайты — распаковка с потолком."""
    monkeypatch.setattr(tochka_parser, "MAX_DECOMPRESSED_BYTES", 1024)
    bomb = base64.b64encode(zlib.compress(b" " * 200_000)).decode()
    routes = _cyclops_happy_routes()
    routes[f"{CYCLOPS_SITE_ROOT}/assets/js/aaa111.bbb222.js"] = _Resp(
        '{"api":"' + bomb + '"}', is_json=False
    )
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="unpacks to more than"):
        parser._parse_cyclops()


def test_cyclops_logs_a_page_whose_chunk_has_no_api_field(caplog):
    """Страница без поля api не отличима от страницы-раздела, поэтому она пропускается,
    но молчать об этом нельзя: так пропажа настоящего метода станет заметной."""
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_MAIN_JS] = _Resp(
        _main_js([("get-documents", "aaa111"), ("no-api-field", "ddd444")]), is_json=False
    )
    routes[CYCLOPS_RUNTIME_JS] = _Resp(
        _runtime_js({"1": "aaa111", "2": "ddd444"}, {"1": "bbb222", "2": "eee555"}), is_json=False
    )
    routes[f"{CYCLOPS_SITE_ROOT}/assets/js/ddd444.eee555.js"] = _Resp("{}", is_json=False)
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with caplog.at_level(logging.WARNING):
        parser._parse_cyclops()

    assert any("no-api-field" in r.getMessage() for r in caplog.records)


def test_cyclops_raises_parser_error_on_network_failure():
    routes = _cyclops_happy_routes()
    routes[CYCLOPS_RUNTIME_JS] = requests.ConnectionError("boom")
    parser = _parser_with_routes({**_spec_routes(), **routes})

    with pytest.raises(ParserError, match="failed to download"):
        parser._parse_cyclops()


def test_get_text_rejects_cross_host_redirect_and_never_requests_target():
    """SSRF via redirect: a portal server 302-ing `_get_text` to another host
    (e.g. cloud metadata, an internal service) must be refused before that
    second address is ever requested."""
    routes = {
        CYCLOPS_RUNTIME_JS: _Resp(
            "", status=302, is_json=False, location="http://169.254.169.254/latest/meta-data/"
        ),
    }
    parser = _parser_with_routes(routes)

    with pytest.raises(ParserError):
        parser._get_text(CYCLOPS_RUNTIME_JS)

    assert parser.session.calls == [CYCLOPS_RUNTIME_JS]


def test_get_text_decodes_utf8_body_despite_resp_encoding_defaulting_to_latin1():
    """`requests` defaults `resp.encoding` to ISO-8859-1 for any text/* response
    whose server did not declare a charset (RFC 2616 default), even though the
    actual bytes on the wire are UTF-8. `_get_text` must decode via
    `BaseParser._charset_of`, not `resp.encoding`, or Cyrillic bodies (e.g.
    developers.tochka.com's own HTML/JS bundles) come out mangled."""
    body = "Выписки по счёту"
    routes = {
        CYCLOPS_RUNTIME_JS: _Resp(
            body, is_json=False,
            headers={"Content-Type": "text/html"}, encoding="ISO-8859-1",
        ),
    }
    parser = _parser_with_routes(routes)

    assert parser._get_text(CYCLOPS_RUNTIME_JS) == body


def test_get_text_honors_server_declared_charset():
    """When the server DOES declare a charset, that charset must be used to
    decode -- the fix must not degenerate into always assuming utf-8."""
    body = "Выписки по счёту"
    routes = {
        CYCLOPS_RUNTIME_JS: _Resp(
            body, is_json=False,
            headers={"Content-Type": "text/html; charset=windows-1251"},
            encoding="windows-1251", body_encoding="windows-1251",
        ),
    }
    parser = _parser_with_routes(routes)

    assert parser._get_text(CYCLOPS_RUNTIME_JS) == body


# ─── Full parse() wiring ───────────────────────────────────────────────────


def test_parse_merges_all_four_products_with_correct_prefixes():
    parser = _parser_with_routes({**_spec_routes(), **_cyclops_happy_routes()})
    snapshot = parser.parse()

    assert "Точка Банк. Счета" in snapshot.services
    assert "Точка Банк. Работа с вебхуками" in snapshot.services
    assert "Приём платежей. Вебхуки" in snapshot.services
    assert "Безопасные сделки. Заказы" in snapshot.services
    assert "Номинальный счёт. Документы" in snapshot.services
    assert snapshot.total_methods == 6
