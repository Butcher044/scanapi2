"""
Tests for JSON field extraction from OpenAPI specs.

Rules:
  - GET / DELETE  → response 200 fields (what the API RETURNS)
  - POST / PUT / PATCH → request body fields (what the API ACCEPTS)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.base_parser import BaseParser, APIMethod, ParseSnapshot


# ── Minimal concrete subclass for testing ─────────────────────────────────────
class _TestParser(BaseParser):
    def __init__(self):
        self.bank_name = "test"
        import logging
        self.logger = logging.getLogger("test")

    def parse(self):
        return None


def _p():
    return _TestParser()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _openapi3_spec_with_response(properties: dict) -> tuple:
    """Returns (operation, spec) with a 200 JSON response."""
    spec = {
        "components": {"schemas": {"Body": {"type": "object", "properties": properties}}}
    }
    operation = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Body"}
                    }
                }
            }
        }
    }
    return operation, spec


def _openapi3_spec_with_request(properties: dict) -> tuple:
    """Returns (operation, spec) with a requestBody."""
    spec = {
        "components": {"schemas": {"Req": {"type": "object", "properties": properties}}}
    }
    operation = {
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/Req"}
                }
            }
        }
    }
    return operation, spec


def _swagger2_spec_with_response(properties: dict) -> tuple:
    """Returns Swagger 2.0 (operation, spec) with a 200 response."""
    spec = {
        "definitions": {"Resp": {"type": "object", "properties": properties}}
    }
    operation = {
        "responses": {
            "200": {"schema": {"$ref": "#/definitions/Resp"}}
        }
    }
    return operation, spec


def _swagger2_spec_with_body(properties: dict) -> tuple:
    """Returns Swagger 2.0 (operation, spec) with a body parameter."""
    spec = {
        "definitions": {"Body": {"type": "object", "properties": properties}}
    }
    operation = {
        "parameters": [
            {"in": "body", "name": "body", "schema": {"$ref": "#/definitions/Body"}}
        ]
    }
    return operation, spec


# ── Response 200 field extraction ─────────────────────────────────────────────

def test_extract_response_200_openapi3():
    op, spec = _openapi3_spec_with_response({
        "id":      {"type": "string"},
        "balance": {"type": "number"},
        "status":  {"type": "string"},
    })
    fields = _p()._extract_response_200_fields(op, spec)
    assert "id" in fields
    assert "balance" in fields
    assert "status" in fields


def test_extract_response_200_swagger2():
    op, spec = _swagger2_spec_with_response({
        "accountId": {"type": "string"},
        "amount":    {"type": "number"},
    })
    fields = _p()._extract_response_200_fields(op, spec)
    assert "accountId" in fields
    assert "amount" in fields


def test_extract_response_empty_when_no_response():
    op = {"responses": {}}
    fields = _p()._extract_response_200_fields(op, {})
    assert fields == []


def test_extract_nested_response_fields():
    spec = {
        "components": {
            "schemas": {
                "Account": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "owner": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "phone": {"type": "string"},
                            },
                        },
                    },
                }
            }
        }
    }
    operation = {
        "responses": {
            "200": {
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/Account"}}
                }
            }
        }
    }
    fields = _p()._extract_response_200_fields(operation, spec)
    assert "id" in fields
    assert "owner" in fields
    assert "owner.name" in fields
    assert "owner.phone" in fields


# ── Request body field extraction ─────────────────────────────────────────────

def test_extract_request_body_openapi3():
    op, spec = _openapi3_spec_with_request({
        "amount":   {"type": "number"},
        "currency": {"type": "string"},
        "toAccount": {"type": "string"},
    })
    fields = _p()._extract_request_body_fields(op, spec)
    assert "amount" in fields
    assert "currency" in fields
    assert "toAccount" in fields


def test_extract_request_body_swagger2():
    op, spec = _swagger2_spec_with_body({
        "paymentId": {"type": "string"},
        "status":    {"type": "string"},
    })
    fields = _p()._extract_request_body_fields(op, spec)
    assert "paymentId" in fields
    assert "status" in fields


def test_extract_request_body_empty_when_no_body():
    op = {"parameters": [{"in": "query", "name": "limit"}]}
    fields = _p()._extract_request_body_fields(op, {})
    assert fields == []


# ── Method-aware extraction ───────────────────────────────────────────────────

def test_get_uses_response_fields():
    """GET should extract response fields, not request body."""
    resp_op, spec = _openapi3_spec_with_response({"id": {"type": "string"}, "balance": {"type": "number"}})
    # Add an irrelevant requestBody to confirm it's not used
    resp_op["requestBody"] = {
        "content": {"application/json": {"schema": {"type": "object", "properties": {"irrelevant": {"type": "string"}}}}}
    }
    fields = _p()._extract_fields_for_method("get", resp_op, spec)
    assert "id" in fields
    assert "balance" in fields
    assert "irrelevant" not in fields


def test_post_uses_request_body_fields():
    """POST should extract request body fields, not response."""
    req_op, spec = _openapi3_spec_with_request({"amount": {"type": "number"}, "to": {"type": "string"}})
    # Add an irrelevant response
    req_op["responses"] = {
        "200": {
            "content": {"application/json": {"schema": {"type": "object", "properties": {"irrelevant": {"type": "string"}}}}}
        }
    }
    fields = _p()._extract_fields_for_method("post", req_op, spec)
    assert "amount" in fields
    assert "to" in fields
    assert "irrelevant" not in fields


def test_put_uses_request_body_fields():
    op, spec = _openapi3_spec_with_request({"name": {"type": "string"}})
    fields = _p()._extract_fields_for_method("put", op, spec)
    assert "name" in fields


def test_patch_uses_request_body_fields():
    op, spec = _openapi3_spec_with_request({"status": {"type": "string"}})
    fields = _p()._extract_fields_for_method("patch", op, spec)
    assert "status" in fields


def test_delete_uses_response_fields():
    op, spec = _openapi3_spec_with_response({"deleted": {"type": "boolean"}})
    fields = _p()._extract_fields_for_method("delete", op, spec)
    assert "deleted" in fields


def test_post_falls_back_to_response_when_no_body():
    """If POST has no request body, fall back to response fields."""
    op, spec = _openapi3_spec_with_response({"result": {"type": "string"}})
    # No requestBody
    fields = _p()._extract_fields_for_method("post", op, spec)
    assert "result" in fields


# ── Field count limit ─────────────────────────────────────────────────────────

def test_fields_capped_at_50():
    props = {f"field_{i}": {"type": "string"} for i in range(100)}
    op, spec = _openapi3_spec_with_response(props)
    fields = _p()._extract_response_200_fields(op, spec)
    assert len(fields) <= 50


# ── JSON example extraction ───────────────────────────────────────────────────

def test_extract_request_example_openapi3():
    op, spec = _openapi3_spec_with_request({
        "amount":   {"type": "number", "example": 100.5},
        "currency": {"type": "string", "example": "RUB"},
    })
    ex = _p()._extract_request_example(op, spec)
    assert isinstance(ex, dict)
    assert ex.get("amount") == 100.5
    assert ex.get("currency") == "RUB"


def test_extract_response_example_openapi3():
    op, spec = _openapi3_spec_with_response({
        "id":     {"type": "string", "example": "abc-123"},
        "status": {"type": "string", "example": "SUCCESS"},
    })
    ex = _p()._extract_response_example(op, spec)
    assert isinstance(ex, dict)
    assert ex.get("id") == "abc-123"
    assert ex.get("status") == "SUCCESS"


def test_extract_example_from_schema_object():
    spec = {}
    schema = {
        "type": "object",
        "properties": {
            "name":  {"type": "string", "example": "Иван"},
            "score": {"type": "integer", "example": 42},
        }
    }
    ex = _p()._schema_to_example(schema, spec)
    assert isinstance(ex, dict)
    assert ex.get("name") == "Иван"
    assert ex.get("score") == 42


def test_extract_example_date_serializable():
    """Dates from YAML specs (e.g. 2023-01-01) must become strings, not datetime.date."""
    import datetime
    spec = {}
    schema = {"type": "string", "format": "date", "example": datetime.date(2023, 1, 1)}
    result = _p()._schema_to_example(schema, spec)
    assert isinstance(result, str), f"Expected str, got {type(result)}"
    assert result == "2023-01-01"


def test_extract_example_allof_merged():
    spec = {
        "components": {
            "schemas": {
                "Base":  {"type": "object", "properties": {"id":   {"type": "string", "example": "1"}}},
                "Extra": {"type": "object", "properties": {"name": {"type": "string", "example": "Alice"}}},
            }
        }
    }
    schema = {
        "allOf": [
            {"$ref": "#/components/schemas/Base"},
            {"$ref": "#/components/schemas/Extra"},
        ]
    }
    ex = _p()._schema_to_example(schema, spec)
    assert isinstance(ex, dict)
    assert ex.get("id") == "1"
    assert ex.get("name") == "Alice"


def test_extract_example_post_returns_request_not_response():
    """POST example must use request body, not response."""
    op, spec = _openapi3_spec_with_request({"amount": {"type": "number", "example": 50.0}})
    op["responses"] = {
        "200": {"content": {"application/json": {"schema": {
            "type": "object", "properties": {"result": {"type": "string", "example": "ok"}}
        }}}}
    }
    req_ex = _p()._extract_request_example(op, spec)
    resp_ex = _p()._extract_response_example(op, spec)
    assert req_ex.get("amount") == 50.0
    assert resp_ex.get("result") == "ok"
    assert "result" not in req_ex
    assert "amount" not in resp_ex


def test_sber_yaml_control_char_strip():
    """Sber YAML files contain x9c control characters that must be stripped."""
    from parsers.sber_parser import SberParser
    text_with_ctrl = "key: value\x9cmore"
    cleaned = SberParser._fix_yaml_control_chars(text_with_ctrl)
    assert "\x9c" not in cleaned
    assert "key: value" in cleaned


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"  ERROR {fn.__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    import sys as _sys; _sys.exit(0 if failed == 0 else 1)
