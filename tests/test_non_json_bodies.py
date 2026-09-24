"""
Defect 5: bodies without a JSON media type must not be skipped entirely.

Evidence: Sber oauth /token and /revoke (application/x-www-form-urlencoded),
Sber claims upload (multipart), Alfa form-encoded requests and text/plain,
xml responses. Truly binary types (application/octet-stream, application/pdf,
image/*, application/zip) must stay empty.
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


def test_form_urlencoded_request_fields_are_extracted():
    op = {"requestBody": {"content": {"application/x-www-form-urlencoded": {"schema": {
        "type": "object",
        "properties": {"grant_type": {"type": "string"}, "refresh_token": {"type": "string"}},
    }}}}}
    fields = _p()._extract_request_body_fields(op, {})
    assert "grant_type" in fields
    assert "refresh_token" in fields


def test_form_urlencoded_request_example_is_generated():
    op = {"requestBody": {"content": {"application/x-www-form-urlencoded": {"schema": {
        "type": "object",
        "properties": {"grant_type": {"type": "string", "example": "refresh_token"}},
    }}}}}
    ex = _p()._extract_request_example(op, {})
    assert ex == {"grant_type": "refresh_token"}


def test_multipart_request_with_explicit_example_is_used():
    op = {"requestBody": {"content": {"multipart/form-data": {
        "schema": {"type": "object", "properties": {"file": {"type": "string", "format": "binary"}}},
        "example": {"file": "claim.pdf"},
    }}}}
    ex = _p()._extract_request_example(op, {})
    assert ex == {"file": "claim.pdf"}


def test_xml_response_fields_and_example_are_extracted():
    op = {"responses": {"200": {"content": {"application/xml": {"schema": {
        "type": "object", "properties": {"status": {"type": "string", "example": "OK"}}
    }}}}}}
    fields = _p()._extract_response_200_fields(op, {})
    assert "status" in fields
    ex = _p()._extract_response_example(op, {})
    assert ex == {"status": "OK"}


def test_text_plain_response_with_scalar_example_is_used():
    op = {"responses": {"200": {"content": {"text/plain": {"example": "plain text value"}}}}}
    ex = _p()._extract_response_example(op, {})
    assert ex == "plain text value"


def test_json_media_type_is_preferred_over_other_media_types():
    op = {"requestBody": {"content": {
        "application/x-www-form-urlencoded": {"schema": {
            "type": "object", "properties": {"wrong": {"type": "string"}}
        }},
        "application/json": {"schema": {
            "type": "object", "properties": {"right": {"type": "string"}}
        }},
    }}}
    fields = _p()._extract_request_body_fields(op, {})
    assert "right" in fields
    assert "wrong" not in fields


def test_octet_stream_request_stays_empty():
    op = {"requestBody": {"content": {"application/octet-stream": {
        "schema": {"type": "string", "format": "binary"}
    }}}}
    assert _p()._extract_request_body_fields(op, {}) == []
    assert _p()._extract_request_example(op, {}) == {}


def test_pdf_response_stays_empty():
    op = {"responses": {"200": {"content": {"application/pdf": {
        "schema": {"type": "string", "format": "binary"}
    }}}}}
    assert _p()._extract_response_200_fields(op, {}) == []
    assert _p()._extract_response_example(op, {}) == {}


def test_image_response_stays_empty():
    op = {"responses": {"200": {"content": {"image/png": {
        "schema": {"type": "string", "format": "binary"}
    }}}}}
    assert _p()._extract_response_example(op, {}) == {}


def test_zip_response_stays_empty():
    op = {"responses": {"200": {"content": {"application/zip": {
        "schema": {"type": "string", "format": "binary"}
    }}}}}
    assert _p()._extract_response_example(op, {}) == {}
