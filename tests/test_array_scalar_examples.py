"""
Defect 2: a top-level JSON array or scalar body must not be dropped.

Evidence: T-Bank "Получить счета v1-v4" (array example), Alfa (array/scalar
responses+requests), Sber partner-info (schema with `items:` but no
`type: array`).
"""
from bank_api_parser.parsers.base_parser import APIMethod, BaseParser


class _TestParser(BaseParser):
    def __init__(self):
        self.bank_name = "test"
        import logging
        self.logger = logging.getLogger("test")

    def parse(self):
        return None


def _p():
    return _TestParser()


# ── response/request examples ──────────────────────────────────────────────

def test_array_response_example_is_kept():
    op = {"responses": {"200": {"content": {"application/json": {"schema": {
        "type": "array",
        "items": {"type": "object", "properties": {"id": {"type": "string", "example": "1"}}},
    }}}}}}
    ex = _p()._extract_response_example(op, {})
    assert isinstance(ex, list)
    assert ex == [{"id": "1"}]


def test_array_request_example_is_kept():
    op = {"requestBody": {"content": {"application/json": {"schema": {
        "type": "array",
        "items": {"type": "string"},
        "example": ["a", "b"],
    }}}}}
    ex = _p()._extract_request_example(op, {})
    assert ex == ["a", "b"]


def test_scalar_response_example_is_kept():
    op = {"responses": {"200": {"content": {"application/json": {
        "schema": {"type": "string"}, "example": "PLAIN-VALUE"
    }}}}}
    ex = _p()._extract_response_example(op, {})
    assert ex == "PLAIN-VALUE"


def test_scalar_generated_from_schema_is_kept():
    """No explicit example — generated from a bare scalar schema."""
    op = {"responses": {"200": {"content": {"application/json": {
        "schema": {"type": "integer"}
    }}}}}
    ex = _p()._extract_response_example(op, {})
    assert ex == 0


def test_false_boolean_example_is_kept():
    """False is falsy but a meaningful example — must not be treated as 'empty'."""
    op = {"responses": {"200": {"content": {"application/json": {
        "schema": {"type": "boolean"}, "example": False
    }}}}}
    ex = _p()._extract_response_example(op, {})
    assert ex is False


# ── items-without-type inference ───────────────────────────────────────────

def test_items_without_explicit_array_type_is_treated_as_array_for_example():
    schema = {"items": {"type": "object", "properties": {"name": {"type": "string", "example": "x"}}}}
    result = _p()._schema_to_example(schema, {})
    assert result == [{"name": "x"}]


def test_items_without_explicit_array_type_is_treated_as_array_for_fields():
    schema = {"items": {"type": "object", "properties": {"name": {"type": "string"}, "id": {"type": "string"}}}}
    fields = _p()._extract_fields(schema, {})
    assert "name" in fields
    assert "id" in fields


# ── field extraction describes the fields of array items ───────────────────

def test_array_response_fields_describe_item_fields():
    op = {"responses": {"200": {"content": {"application/json": {"schema": {
        "type": "array",
        "items": {"type": "object", "properties": {"accountId": {"type": "string"}}},
    }}}}}}
    fields = _p()._extract_response_200_fields(op, {})
    assert "accountId" in fields


# ── APIMethod must be able to store non-dict examples ──────────────────────

def test_apimethod_roundtrips_list_example():
    method = APIMethod(
        bank="test", service_name="svc", http_method="GET", path="/x",
        summary="", description="", response_200_fields=[], parsed_at="",
        url_on_portal="", request_example={}, response_example=[{"id": "1"}],
    )
    restored = APIMethod.from_dict(method.to_dict())
    assert restored.response_example == [{"id": "1"}]


def test_apimethod_roundtrips_scalar_example():
    method = APIMethod(
        bank="test", service_name="svc", http_method="GET", path="/x",
        summary="", description="", response_200_fields=[], parsed_at="",
        url_on_portal="", request_example={}, response_example="plain",
    )
    restored = APIMethod.from_dict(method.to_dict())
    assert restored.response_example == "plain"
