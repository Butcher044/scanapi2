"""
`_get_capped_text` must not corrupt Cyrillic bodies. `requests` defaults
`resp.encoding` to ISO-8859-1 for any `text/*` response whose server did not
declare a charset (RFC 2616 default) -- confirmed live against
developers.sber.ru, whose pages and specs are `text/html` with no charset
param. The old code trusted `resp.encoding` blindly and mangled every
Cyrillic body it read; `_charset_of` must use the server-declared charset
only when `Content-Type` actually names one, and fall back to utf-8
otherwise -- including when the declared name is not a real encoding.
"""
import logging

from bank_api_parser.parsers.base_parser import BaseParser


class _TestParser(BaseParser):
    def __init__(self):
        self.bank_name = "test"
        self.logger = logging.getLogger("test")
        self._external_spec_cache = {}

    def parse(self):
        return None


class _FakeSession:
    def __init__(self, resp):
        self.resp = resp

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        return self.resp


class _FakeResp:
    """Mimics requests.Response: body served in chunks, decoding driven by headers.

    `encoding` mimics what `requests` itself would already have set by the
    time a caller sees the response -- including its RFC-2616 default of
    'ISO-8859-1' for `text/*` bodies with no declared charset -- so a test can
    prove the new code no longer trusts that attribute.
    """

    def __init__(self, body: bytes, headers: dict | None = None, encoding: str | None = None):
        self.body = body
        self.headers = headers if headers is not None else {}
        self.status_code = 200
        self.encoding = encoding

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]


def _parser_with(resp) -> BaseParser:
    p = _TestParser()
    p.session = _FakeSession(resp)
    return p


CYRILLIC_TEXT = "Оплата по QR-коду"


# ── _get_capped_text: end-to-end decoding behaviour ─────────────────────────

def test_text_html_without_charset_is_read_as_utf8_not_iso_8859_1():
    """Regression: requests sets resp.encoding == 'ISO-8859-1' here (its RFC
    2616 default for text/* with no declared charset); the old
    `getattr(resp, "encoding", None) or "utf-8"` trusted that and mangled
    every Cyrillic body. developers.sber.ru serves exactly this shape."""
    body = CYRILLIC_TEXT.encode("utf-8")
    resp = _FakeResp(body, headers={"Content-Type": "text/html"}, encoding="ISO-8859-1")
    parser = _parser_with(resp)
    assert parser._get_capped_text("https://example.test/page") == CYRILLIC_TEXT


def test_declared_charset_is_honoured():
    body = CYRILLIC_TEXT.encode("windows-1251")
    resp = _FakeResp(
        body, headers={"Content-Type": "text/html; charset=windows-1251"}, encoding="windows-1251"
    )
    parser = _parser_with(resp)
    assert parser._get_capped_text("https://example.test/page") == CYRILLIC_TEXT


def test_missing_headers_attribute_falls_back_to_utf8_without_raising():
    body = CYRILLIC_TEXT.encode("utf-8")
    resp = _FakeResp(body)
    del resp.headers  # simulate a fake response with no `headers` attribute at all
    parser = _parser_with(resp)
    assert parser._get_capped_text("https://example.test/page") == CYRILLIC_TEXT


def test_unknown_charset_name_falls_back_to_utf8_without_raising():
    body = CYRILLIC_TEXT.encode("utf-8")
    resp = _FakeResp(body, headers={"Content-Type": "text/html; charset=not-a-real-charset"})
    parser = _parser_with(resp)
    assert parser._get_capped_text("https://example.test/page") == CYRILLIC_TEXT


# ── _charset_of: the pure helper, tested directly ───────────────────────────

def test_charset_of_returns_declared_charset():
    resp = _FakeResp(b"", headers={"Content-Type": "text/html; charset=windows-1251"})
    assert BaseParser._charset_of(resp) == "windows-1251"


def test_charset_of_defaults_to_utf8_when_not_declared():
    resp = _FakeResp(b"", headers={"Content-Type": "text/html"})
    assert BaseParser._charset_of(resp) == "utf-8"


def test_charset_of_defaults_to_utf8_without_headers_attribute():
    class _NoHeaders:
        pass

    assert BaseParser._charset_of(_NoHeaders()) == "utf-8"


def test_charset_of_defaults_to_utf8_for_unknown_charset_name():
    resp = _FakeResp(b"", headers={"Content-Type": "text/html; charset=bogus-xyz"})
    assert BaseParser._charset_of(resp) == "utf-8"
