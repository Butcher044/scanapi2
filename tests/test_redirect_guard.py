"""
SSRF via HTTP redirect: `_is_same_origin` only ever checked a URL computed
from spec content, never the address an HTTP redirect chain actually lands
on. `requests` follows redirects transparently by default (up to 30 hops)
and nobody compared the final `resp.url` against the originally requested
host -- a compromised/malicious spec server could answer with e.g.
`302 Location: http://169.254.169.254/...` (cloud metadata) or any internal
address, and the response body would be parsed and end up in
`response_example`/`request_example`, visible on the dashboard.

Redirects must therefore be followed by hand (`allow_redirects=False`), one
hop at a time, checking `_is_same_origin` against the ORIGINAL url before any
further request is made -- and giving up after a small number of hops.
"""
import logging

import pytest
import requests

from bank_api_parser.parsers.base_parser import BaseParser, ParserError


class _TestParser(BaseParser):
    def __init__(self):
        self.bank_name = "test"
        self.logger = logging.getLogger("test")
        self._external_spec_cache = {}

    def parse(self):
        return None


class _RedirectResp:
    def __init__(self, status_code=200, text="", location=None):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"
        self.headers = {"Location": location} if location else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        data = self.text.encode("utf-8")
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]


class _RoutedSession:
    """Maps exact URLs to canned responses; records every URL actually requested
    so a test can prove a rejected redirect target was never fetched."""

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


def _parser_with(routes):
    p = _TestParser()
    p.session = _RoutedSession(routes)
    return p


def test_cross_host_redirect_is_rejected_and_target_is_never_requested():
    routes = {
        "http://a.example/spec.json": _RedirectResp(
            302, location="http://169.254.169.254/latest/meta-data/"
        ),
    }
    parser = _parser_with(routes)

    with pytest.raises(ParserError, match="169.254.169.254"):
        parser._get_capped_text("http://a.example/spec.json")

    assert parser.session.calls == ["http://a.example/spec.json"]


def test_redirect_to_non_http_scheme_is_rejected():
    routes = {
        "http://a.example/spec.json": _RedirectResp(302, location="file:///etc/passwd"),
    }
    parser = _parser_with(routes)

    with pytest.raises(ParserError):
        parser._get_capped_text("http://a.example/spec.json")

    assert parser.session.calls == ["http://a.example/spec.json"]


def test_same_host_redirect_is_followed_and_body_is_read():
    routes = {
        "http://a.example/old.json": _RedirectResp(302, location="http://a.example/new.json"),
        "http://a.example/new.json": _RedirectResp(200, text='{"paths": {}}'),
    }
    parser = _parser_with(routes)

    text = parser._get_capped_text("http://a.example/old.json")

    assert text == '{"paths": {}}'
    assert parser.session.calls == ["http://a.example/old.json", "http://a.example/new.json"]


def test_scheme_upgrade_on_same_host_redirect_is_followed():
    routes = {
        "http://a.example/old.json": _RedirectResp(302, location="https://a.example/new.json"),
        "https://a.example/new.json": _RedirectResp(200, text="ok"),
    }
    parser = _parser_with(routes)

    text = parser._get_capped_text("http://a.example/old.json")

    assert text == "ok"


def test_redirect_chain_longer_than_hop_limit_raises_without_finishing_it():
    # 7 same-host hops in a row -- exceeds BaseParser._MAX_REDIRECT_HOPS (5).
    routes = {
        f"http://a.example/{i}": _RedirectResp(302, location=f"http://a.example/{i + 1}")
        for i in range(7)
    }
    routes["http://a.example/7"] = _RedirectResp(200, text="ok")
    parser = _parser_with(routes)

    with pytest.raises(ParserError, match="redirect"):
        parser._get_capped_text("http://a.example/0")

    assert "http://a.example/6" not in parser.session.calls
    assert "http://a.example/7" not in parser.session.calls
