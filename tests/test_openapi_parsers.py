"""Tests for the shared OpenAPI parsing used by T-Bank and Tochka."""
import pytest
import requests

from bank_api_parser.parsers.base_parser import ParserError
from bank_api_parser.parsers.tbank_parser import TBankParser
from bank_api_parser.parsers.tochka_parser import TochkaParser

SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/accounts": {
            "get": {"tags": ["Счета"], "summary": "Список", "operationId": "listAccounts",
                    "responses": {"200": {"content": {"application/json": {"schema": {
                        "type": "object", "properties": {"id": {"type": "string"}}}}}}}},
        },
        "/voice": {"post": {"tags": ["VoiceKit API"], "summary": "Voice", "responses": {}}},
        "/webhooks": {"get": {"tags": ["Работа с вебхуками"], "summary": "Hooks", "responses": {}}},
        "/notag": {"delete": {"summary": "No tag", "responses": {}}},
        "/x": {"parameters": [], "options": {"tags": ["Счета"]}},
    },
}


class _Resp:
    def __init__(self, text="", status=200):
        self.text, self.status_code = text, status
        self.encoding = "utf-8"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        data = self.text.encode("utf-8")
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]


class _Session:
    def __init__(self, result):
        self.result = result

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_tbank_excludes_tags_by_substring_and_uses_kebab_operation_slug():
    services = TBankParser()._parse_openapi_spec(SPEC, "https://p", {"voicekit"})
    assert set(services) == {"Счета", "Работа с вебхуками", "Без тега"}
    (m,) = services["Счета"]
    assert (m.http_method, m.path, m.url_on_portal) == ("GET", "/accounts", "https://p/list-accounts")
    assert "id" in m.response_200_fields


def test_tochka_uses_kebab_operation_slug():
    services = TochkaParser()._parse_openapi_spec(SPEC, "https://t", {"вебхук"})
    assert "Работа с вебхуками" not in services
    assert services["Счета"][0].url_on_portal == "https://t/list-accounts"


@pytest.mark.parametrize("text", ['{"openapi": "3.0.0", "paths": {"/a": {}}}',
                                  "openapi: 3.0.0\npaths:\n  /a: {}\n"])
def test_fetch_spec_accepts_json_and_yaml(text):
    parser = TBankParser()
    parser.session = _Session(_Resp(text))
    assert "/a" in parser._fetch_spec("https://x")["paths"]


@pytest.mark.parametrize("result,match", [
    (requests.ConnectionError("boom"), "failed to download"),
    (_Resp("", 503), "failed to download"),
    (_Resp("{not json"), "invalid spec"),
    (_Resp('{"openapi": "3.0.0"}'), "no paths"),
])
def test_fetch_spec_raises_parser_error(result, match):
    parser = TochkaParser()
    parser.session = _Session(result)
    with pytest.raises(ParserError, match=match):
        parser._fetch_spec("https://x")
