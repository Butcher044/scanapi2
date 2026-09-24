"""
Defect 1: response picking must not be hard-wired to the "200"/"201" string keys.

  (a) an unquoted `200:` in YAML parses as the integer key 200 — `.get("200")` misses it.
  (b) a real 2xx response other than 200/201 (e.g. 202) with content must not be ignored.
  204 (or any 2xx with no body) must still resolve to an empty example/field list.
"""
from bank_api_parser.parsers.base_parser import BaseParser


class _TestParser(BaseParser):
    def __init__(self):
        self.bank_name = "test"
        import logging
        self.logger = logging.getLogger("test")

    def parse(self):
        return None


def _p():
    return _TestParser()


def _json_response(status, properties):
    return {
        status: {
            "content": {
                "application/json": {
                    "schema": {"type": "object", "properties": properties}
                }
            }
        }
    }


def test_integer_200_key_is_picked_for_fields():
    """Unquoted `200:` in YAML parses to the int key 200."""
    op = {"responses": _json_response(200, {"id": {"type": "string"}})}
    fields = _p()._extract_response_200_fields(op, {})
    assert "id" in fields


def test_integer_200_key_is_picked_for_example():
    op = {"responses": {200: {"content": {"application/json": {
        "schema": {"type": "object", "properties": {"id": {"type": "string", "example": "abc"}}}
    }}}}}
    ex = _p()._extract_response_example(op, {})
    assert ex.get("id") == "abc"


def test_202_with_content_is_used_when_200_absent():
    op = {"responses": _json_response("202", {"accepted": {"type": "boolean"}})}
    fields = _p()._extract_response_200_fields(op, {})
    assert "accepted" in fields


def test_prefers_200_over_202_when_both_have_content():
    responses = {}
    responses.update(_json_response("202", {"wrong": {"type": "string"}}))
    responses.update(_json_response("200", {"right": {"type": "string"}}))
    op = {"responses": responses}
    fields = _p()._extract_response_200_fields(op, {})
    assert "right" in fields
    assert "wrong" not in fields


def test_204_with_no_content_stays_empty():
    op = {"responses": {"204": {"description": "no content"}}}
    assert _p()._extract_response_200_fields(op, {}) == []
    assert _p()._extract_response_example(op, {}) == {}


def test_non_2xx_responses_are_ignored():
    op = {"responses": {"404": {"content": {"application/json": {
        "schema": {"type": "object", "properties": {"error": {"type": "string"}}}
    }}}}}
    assert _p()._extract_response_200_fields(op, {}) == []
    assert _p()._extract_response_example(op, {}) == {}


def test_first_2xx_with_content_is_used_when_no_200_or_201():
    """Among several non-200/201 2xx responses, the first one with content wins."""
    op = {"responses": {
        "203": {"description": "no body"},
        "206": {"content": {"application/json": {
            "schema": {"type": "object", "properties": {"partial": {"type": "boolean"}}}
        }}},
    }}
    fields = _p()._extract_response_200_fields(op, {})
    assert "partial" in fields
