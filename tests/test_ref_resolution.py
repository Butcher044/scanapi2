"""
Defect 4: $ref responses and external-file $refs must resolve.

  (a) a response can itself be `$ref: '#/components/responses/...'`.
  (b) a schema $ref can point into a sibling file, e.g.
      `./common/fintech-models.yml#/components/schemas/Account`, resolved
      relative to the spec's own URL and fetched through the parser's HTTP
      session (offline in tests via a fake session), cached per parse so one
      file is downloaded once. A ref that cannot be resolved must log a
      warning and yield an empty example -- never crash.
"""
import logging

import requests

from bank_api_parser.parsers.base_parser import BaseParser


class _TestParser(BaseParser):
    def __init__(self):
        self.bank_name = "test"
        self.logger = logging.getLogger("test")
        self._external_spec_cache = {}

    def parse(self):
        return None


def _p():
    return _TestParser()


class _FakeSession:
    def __init__(self, responses: dict):
        self.responses = responses  # url -> text or Exception
        self.calls = []

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        self.calls.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return _FakeResp(result)


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200
        self.encoding = "utf-8"

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        data = self.text.encode("utf-8")
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]


# ── local #/components/responses ref ───────────────────────────────────────

def test_local_response_ref_is_resolved_for_fields():
    spec = {
        "components": {
            "responses": {
                "AccountResponse": {
                    "content": {"application/json": {"schema": {
                        "type": "object", "properties": {"id": {"type": "string"}}
                    }}}
                }
            }
        }
    }
    op = {"responses": {"200": {"$ref": "#/components/responses/AccountResponse"}}}
    fields = _p()._extract_response_200_fields(op, spec)
    assert "id" in fields


def test_local_response_ref_is_resolved_for_example():
    spec = {
        "components": {
            "responses": {
                "AccountResponse": {
                    "content": {"application/json": {"schema": {
                        "type": "object",
                        "properties": {"id": {"type": "string", "example": "abc"}},
                    }}}
                }
            }
        }
    }
    op = {"responses": {"200": {"$ref": "#/components/responses/AccountResponse"}}}
    ex = _p()._extract_response_example(op, spec)
    assert ex == {"id": "abc"}


# ── external file ref ───────────────────────────────────────────────────────

EXTERNAL_YAML = """
components:
  schemas:
    Account:
      type: object
      properties:
        accountId:
          type: string
          example: "40817..."
        balance:
          type: number
          example: 100.5
"""


def test_external_file_ref_is_fetched_and_resolved():
    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    external_url = "https://developers.sber.ru/docs/files/openapi/sbapi/common/fintech-models.yml"
    schema = {"$ref": "common/fintech-models.yml#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({external_url: EXTERNAL_YAML})

    example = parser._schema_to_example(schema, {}, spec_url=spec_url)
    assert example == {"accountId": "40817...", "balance": 100.5}

    fields = parser._extract_fields(schema, {}, spec_url=spec_url)
    assert "accountId" in fields
    assert "balance" in fields


def test_external_file_is_fetched_only_once_per_parser():
    """Two refs into the same external file must trigger exactly one HTTP GET."""
    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    external_url = "https://developers.sber.ru/docs/files/openapi/sbapi/common/fintech-models.yml"
    schema = {
        "type": "object",
        "properties": {
            "a": {"$ref": "common/fintech-models.yml#/components/schemas/Account"},
            "b": {"$ref": "common/fintech-models.yml#/components/schemas/Account"},
        },
    }
    parser = _p()
    parser.session = _FakeSession({external_url: EXTERNAL_YAML})

    result = parser._schema_to_example(schema, {}, spec_url=spec_url)
    assert result["a"]["accountId"] == "40817..."
    assert result["b"]["accountId"] == "40817..."
    assert parser.session.calls.count(external_url) == 1


def test_external_ref_without_spec_url_is_empty_and_logs_warning(caplog):
    schema = {"$ref": "common/fintech-models.yml#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({})
    with caplog.at_level(logging.WARNING, logger="test"):
        result = parser._schema_to_example(schema, {})
    assert result is None
    assert any("$ref" in rec.message for rec in caplog.records)


def test_external_ref_fetch_failure_does_not_crash(caplog):
    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    external_url = "https://developers.sber.ru/docs/files/openapi/sbapi/common/fintech-models.yml"
    schema = {"$ref": "common/fintech-models.yml#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({external_url: requests.ConnectionError("boom")})

    with caplog.at_level(logging.WARNING, logger="test"):
        result = parser._schema_to_example(schema, {}, spec_url=spec_url)
    assert result is None


# ── the external ref is attacker-controlled input ──────────────────────────

def test_external_ref_to_another_host_is_refused_without_any_request(caplog):
    """`$ref` содержимое приходит из файла банка. urljoin с абсолютным URL
    подменяет базу целиком, поэтому подменённая спека увела бы парсер на
    произвольный хост (метаданные облака, внутренний сервис) нашими же
    TLS/прокси-настройками. Запрос не должен уходить вообще."""
    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    schema = {"$ref": "http://169.254.169.254/latest/meta-data/#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({})

    with caplog.at_level(logging.WARNING, logger="test"):
        result = parser._schema_to_example(schema, {}, spec_url=spec_url)

    assert result is None
    assert parser.session.calls == []
    assert any("169.254.169.254" in rec.getMessage() for rec in caplog.records)


def test_external_ref_with_a_non_http_scheme_is_refused():
    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    schema = {"$ref": "file:///etc/passwd#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({})

    assert parser._schema_to_example(schema, {}, spec_url=spec_url) is None
    assert parser.session.calls == []


def test_external_ref_on_the_same_host_is_still_allowed():
    """Соседние файлы спеки — штатный случай, их запрещать нельзя."""
    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    external_url = "https://developers.sber.ru/docs/other/fintech-models.yml"
    schema = {"$ref": "/docs/other/fintech-models.yml#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({external_url: EXTERNAL_YAML})

    result = parser._schema_to_example(schema, {}, spec_url=spec_url)
    assert result == {"accountId": "40817...", "balance": 100.5}


def test_external_ref_larger_than_the_cap_is_refused():
    """Бомба сжатия: requests распаковывает gzip сам и без ограничения объёма."""
    from bank_api_parser.parsers.base_parser import MAX_RESPONSE_BYTES

    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    external_url = "https://developers.sber.ru/docs/files/openapi/sbapi/common/huge.yml"
    schema = {"$ref": "common/huge.yml#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({external_url: "a" * (MAX_RESPONSE_BYTES + 1)})

    assert parser._schema_to_example(schema, {}, spec_url=spec_url) is None


def test_external_ref_invalid_yaml_does_not_crash():
    spec_url = "https://developers.sber.ru/docs/files/openapi/sbapi/section.yaml"
    external_url = "https://developers.sber.ru/docs/files/openapi/sbapi/common/broken.yml"
    schema = {"$ref": "common/broken.yml#/components/schemas/Account"}
    parser = _p()
    parser.session = _FakeSession({external_url: "key: [1, 2"})

    result = parser._schema_to_example(schema, {}, spec_url=spec_url)
    assert result is None
