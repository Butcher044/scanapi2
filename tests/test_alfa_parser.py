"""Alfa-Bank parser: frontmatter extraction and the no-partial-snapshot policy (offline)."""
import json
from unittest import mock

import pytest
import requests

from bank_api_parser.parsers import alfabank_parser as alfa
from bank_api_parser.parsers.base_parser import (
    HIDDEN_REASON_GHOST,
    HIDDEN_REASON_PRIVATE,
    HIDDEN_REASON_SUPERSEDED,
    ParserError,
)

FRONTMATTER = """---
title: Создать заявку
endpoint:
  - method: POST
    production: 'https://baas.alfabank.ru/api/pp/v1/forms'
openApi:
  openapi: 3.0.0
  paths:
    /pp/v1/forms:
      post:
        responses:
          '200':
            content:
              application/json:
                schema:
                  type: object
                  properties:
                    formId: {type: string}
---
# body
"""

INDEX = {"pageProps": {"productInfoData": {"articles": [
    {"title": "Карты", "articles": [
        {"title": "Создать", "path": "a/create.md"},
        {"title": "Получить", "path": "a/get.md"},
        {"title": "Введение", "path": "a/intro.md"},
    ]},
]}}}


def _page(method, url):
    return {"mdString": f"---\nendpoint:\n  - method: {method}\n    production: '{url}'\n---\n"}


@pytest.fixture
def parser():
    p = alfa.AlfaBankParser()
    p._build_hash = "build123456"
    p._index_data = INDEX
    return p


def test_session_uses_short_user_agent(parser):
    assert parser.session.headers["User-Agent"] == alfa.ALFA_USER_AGENT
    assert parser._thread_session().headers["User-Agent"] == alfa.ALFA_USER_AGENT


def test_endpoint_and_fields_from_frontmatter(parser):
    (ep,) = parser._endpoints_from_page_props({"mdString": FRONTMATTER})
    assert (ep["method"], ep["path"]) == ("POST", "/api/pp/v1/forms")
    assert "formId" in ep["fields"]


def test_regex_fallback_for_invalid_yaml(parser):
    md = "---\nendpoint: [\n  method: GET\n  production: https://x.ru/api/v1/a\n---\n"
    assert parser._endpoints_from_page_props({"mdString": md}) == [
        {"method": "GET", "path": "/api/v1/a", "fields": []},
    ]


def test_no_frontmatter_means_no_endpoints(parser):
    assert parser._endpoints_from_page_props({"mdString": "# just text"}) == []
    assert parser._endpoints_from_page_props({}) == []


def test_frontmatter_without_endpoint_key_is_legitimately_empty(parser):
    """Frontmatter parses fine and simply declares no `endpoint:` -- a purely
    descriptive article (e.g. "Введение") is not a parse failure."""
    md = "---\ntitle: Просто статья без методов\n---\n"
    assert parser._endpoints_from_page_props({"mdString": md}) == []


def test_frontmatter_with_empty_endpoint_list_is_legitimately_empty(parser):
    md = "---\ntitle: X\nendpoint: []\n---\n"
    assert parser._endpoints_from_page_props({"mdString": md}) == []


def test_unparsable_frontmatter_is_a_parser_error_not_a_silent_empty_page(parser):
    """Frontmatter block IS present but neither YAML nor the regex fallback can
    make sense of it -- this must not look like "no endpoints" (module
    docstring: "a partial scan is an error"), so it must fail loudly instead
    of silently returning []."""
    md = "---\nthis is not: [valid yaml at all\n---\n"
    with pytest.raises(ParserError, match="frontmatter"):
        parser._endpoints_from_page_props({"mdString": md})


def test_scan_article_treats_unparsable_frontmatter_like_a_failed_fetch(parser, monkeypatch):
    """_scan_article must convert the ParserError above into None (same as a
    network failure) so it goes through the existing retry-then-abort path."""
    bad_page = {"mdString": "---\nthis is not: [valid yaml at all\n---\n"}
    monkeypatch.setattr(parser, "_fetch_article_page", lambda path, depth=0: bad_page)
    assert parser._scan_article({"path": "a/create", "service": "Карты", "title": "Создать"}) is None


def test_build_id_from_html():
    assert alfa.AlfaBankParser._build_id_from_html('{"buildId":"abcdef123456"}') == "abcdef123456"
    assert alfa.AlfaBankParser._build_id_from_html('<script src="/_next/static/XyZ0123456789/_x.js">') == "XyZ0123456789"
    assert alfa.AlfaBankParser._build_id_from_html("<html></html>") is None


def test_article_scan_skips_ignored_and_dedupes(parser, monkeypatch):
    pages = {
        "/products/alfa-api/documentation/a/create": _page("POST", "https://h/api/v1/x"),
        "/products/alfa-api/documentation/a/get": _page("POST", "https://h/v1/x"),  # same after /api strip
    }
    requested = []

    def fetch(path, depth=0):
        requested.append(path)
        return pages[path]

    monkeypatch.setattr(parser, "_fetch_article_page", fetch)
    services = parser._strategy_article_scan()
    assert sorted(requested) == sorted(pages)
    assert [(m.http_method, m.path) for m in services["Карты"]] == [("POST", "/v1/x")]


FRONTMATTER_WITH_EXTERNAL_REF = """---
endpoint:
  - method: POST
    production: 'https://h/v1/x'
openApi:
  openapi: 3.0.0
  paths:
    /v1/x:
      post:
        requestBody:
          content:
            application/json:
              schema:
                $ref: 'other.yml#/components/schemas/X'
        responses: {}
---
"""


def test_article_scan_never_fetches_external_refs(parser, monkeypatch):
    """spec_url is deliberately not passed into field/example extraction from
    the article scan (see the comment in _endpoints_from_frontmatter):
    resolving an external $ref there would fetch over the network from
    ARTICLE_WORKERS worker threads, through the shared, non-thread-safe
    `self.session` and the unlocked `self._external_spec_cache`."""
    monkeypatch.setattr(
        parser, "_fetch_article_page",
        lambda path, depth=0: {"mdString": FRONTMATTER_WITH_EXTERNAL_REF},
    )
    spy = mock.Mock(return_value={})
    monkeypatch.setattr(parser, "_fetch_external_spec", spy)
    parser._strategy_article_scan()
    spy.assert_not_called()


def test_retry_keys_by_leaf_index_not_by_possibly_duplicate_path(parser, monkeypatch):
    """Two leaves that happen to share the same `path` (e.g. the same article
    reachable from two places in the tree) must each be retried and resolved
    independently -- keying the retry map by `leaf["path"]` would collapse
    the two distinct results into one (last-write-wins)."""
    leaves = [
        {"path": "shared/x.md", "service": "Карты", "title": "A"},
        {"path": "shared/x.md", "service": "Карты", "title": "B"},
    ]
    call_count = {id(leaves[0]): 0, id(leaves[1]): 0}

    def scan_article(leaf):
        call_count[id(leaf)] += 1
        if call_count[id(leaf)] == 1:
            return None  # fails on the first pass for both leaves
        marker = "A" if leaf is leaves[0] else "B"
        return [{"method": "GET", "path": f"/{marker}", "fields": []}]

    monkeypatch.setattr(parser, "_scan_article", scan_article)
    results = parser._scan_all_articles(leaves)
    assert results[0] == [{"method": "GET", "path": "/A", "fields": []}]
    assert results[1] == [{"method": "GET", "path": "/B", "fields": []}]


PRIVATE_INDEX = {"pageProps": {"productInfoData": {"articles": [
    {"title": "Партнёрская программа малого и микробизнеса", "tags": ["private"], "articles": [
        {"title": "Короткая анкета для регистрации бизнеса", "tags": ["service"], "articles": [
            {"title": "Отправить анкету", "path": "partner/send.md"},
        ]},
    ]},
]}}}

SUPERSEDED_INDEX = {"pageProps": {"productInfoData": {"articles": [
    {"title": "Вебхуки", "tags": ["service"], "articles": [
        {"title": "Получение вебхука", "path": "webhooks/get.md", "visible": False},
        {"title": "Создание вебхука", "path": "webhooks/create.md"},
    ]},
]}}}


def test_private_subtree_methods_are_hidden_not_dropped(parser, monkeypatch):
    """A whole closed space (findings.md: 11 services / 89 methods, e.g.
    "Короткая анкета для регистрации бизнеса") is kept in the snapshot,
    just flagged — not silently removed."""
    parser._index_data = PRIVATE_INDEX
    monkeypatch.setattr(parser, "_fetch_article_page", lambda path, depth=0: _page("POST", "https://h/v1/send"))
    services = parser._strategy_article_scan()
    (method,) = services["Короткая анкета для регистрации бизнеса"]
    assert method.hidden is True
    assert method.hidden_reason == HIDDEN_REASON_PRIVATE


def test_superseded_article_version_is_hidden_not_dropped(parser, monkeypatch):
    """visible:false = an older version of a still-published article
    (findings.md: 34 methods, e.g. Вебхуки v1 alongside a live v2)."""
    parser._index_data = SUPERSEDED_INDEX
    pages = {
        "/products/alfa-api/documentation/webhooks/get": _page("GET", "https://h/v1/webhooks/get"),
        "/products/alfa-api/documentation/webhooks/create": _page("POST", "https://h/v1/webhooks/create"),
    }
    monkeypatch.setattr(parser, "_fetch_article_page", lambda path, depth=0: pages[path])
    services = parser._strategy_article_scan()
    by_path = {m.path: m for m in services["Вебхуки"]}
    assert by_path["/v1/webhooks/get"].hidden is True
    assert by_path["/v1/webhooks/get"].hidden_reason == HIDDEN_REASON_SUPERSEDED
    assert by_path["/v1/webhooks/create"].hidden is False
    assert by_path["/v1/webhooks/create"].hidden_reason is None


def test_transient_failure_is_retried(parser, monkeypatch):
    calls = {}

    def fetch(path, depth=0):
        calls[path] = calls.get(path, 0) + 1
        if path.endswith("get") and calls[path] == 1:
            return None
        return _page("GET", f"https://h{path}")

    monkeypatch.setattr(parser, "_fetch_article_page", fetch)
    services = parser._strategy_article_scan()
    assert len(services["Карты"]) == 2


def test_persistent_failure_rejects_snapshot(parser, monkeypatch):
    monkeypatch.setattr(
        parser, "_fetch_article_page",
        lambda path, depth=0: None if path.endswith("get") else _page("GET", "https://h/a"),
    )
    with pytest.raises(ParserError, match="1 of 2 articles"):
        parser._strategy_article_scan()


class _Resp:
    def __init__(
        self, status=200, payload=None, location=None, body=None,
        headers=None, encoding="utf-8", body_encoding=None,
    ):
        self.status_code = status
        # What requests.Response.encoding would report -- may differ from the
        # actual bytes on the wire (see _charset_of's docstring: `requests`
        # defaults this to ISO-8859-1 for text/* with no charset param).
        self.encoding = encoding
        text = body if body is not None else json.dumps(payload or {})
        # The actual bytes sent over the wire -- independent of what
        # `resp.encoding` claims; defaults to utf-8 like every real portal here.
        self.content = text.encode(body_encoding or "utf-8")
        self.headers = headers if headers is not None else ({"Location": location} if location else {})

    def raise_for_status(self):
        if self.status_code >= 400:
            # Real requests.Response.raise_for_status() attaches itself as
            # `.response` -- _fetch_article_page relies on that for the 404 case.
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size=65536):
        for start in range(0, len(self.content), chunk_size):
            yield self.content[start:start + chunk_size]


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.mark.parametrize("responses,expected", [
    ([_Resp(404)], {}),
    ([_Resp(503)], None),
    ([requests.ConnectionError("x")], None),
    ([_Resp(payload={"pageProps": {"__N_REDIRECT": "/products/alfa-api/documentation/b/c"}}),
      _Resp(payload={"pageProps": {"mdString": "m"}})], {"mdString": "m"}),
])
def test_fetch_article_page_outcomes(parser, responses, expected):
    parser._local.session = _Session(responses)
    assert parser._fetch_article_page("/products/alfa-api/documentation/a/b") == expected


def test_fetch_article_page_builds_next_data_url(parser):
    parser._local.session = _Session([_Resp(payload={"pageProps": {}})])
    parser._fetch_article_page("/products/alfa-api/documentation/a/b")
    assert parser._local.session.urls == [
        "https://developers.alfabank.ru/_next/data/build123456/products/alfa-api/documentation/a/b.json"
        "?productName=alfa-api&documentName=a&documentName=b"
    ]


def test_parse_fails_without_build_id(parser, monkeypatch):
    monkeypatch.setattr(parser, "_get_build_hash_via_requests", lambda: None)
    with pytest.raises(ParserError, match="buildId"):
        parser.parse()


def test_parse_fails_without_index(parser, monkeypatch):
    monkeypatch.setattr(parser, "_get_build_hash_via_requests", lambda: "build123456")
    monkeypatch.setattr(parser, "_fetch_json", lambda url: None)
    with pytest.raises(ParserError, match="index"):
        parser.parse()


def test_release_notes_only_add_unknown_methods(parser, monkeypatch):
    monkeypatch.setattr(parser, "_get_build_hash_via_requests", lambda: "build123456")
    rn = {"pageProps": {"content": {"changes": [{"updates": [{
        "tags": ["Карты"],
        "content": "* POST /v1/x - дубль\n* GET /v1/new - новый [док](/products/alfa-api/documentation/n)",
    }]}]}}}
    monkeypatch.setattr(parser, "_fetch_json", lambda url: rn if "release-notes" in url else INDEX)
    monkeypatch.setattr(parser, "_fetch_article_page",
                        lambda path, depth=0: _page("POST", "https://h/api/v1/x"))
    snap = parser.parse()
    all_methods = {(m.http_method, m.path): m for ms in snap.services.values() for m in ms}
    # Путь хранится в одной форме (без /api), иначе метод «переезжает» при появлении статьи
    assert set(all_methods) == {("POST", "/v1/x"), ("GET", "/v1/new")}
    # Published in an article → visible.
    assert all_methods[("POST", "/v1/x")].hidden is False
    # Only ever seen in release notes → hidden ghost (findings.md: 21 dead-path
    # ghosts, but ALL RN-only methods are hidden unconditionally — safer).
    assert all_methods[("GET", "/v1/new")].hidden is True
    assert all_methods[("GET", "/v1/new")].hidden_reason == HIDDEN_REASON_GHOST


def test_release_notes_only_service_is_hidden_wholesale():
    """"Самозанятые" (findings.md): the entire service in our output is a
    single release-notes-only method with a dead path — since ALL RN-only
    methods are hidden, that whole service comes out fully hidden, not
    silently dropped."""
    p = alfa.AlfaBankParser()
    p._build_hash = "build123456"
    p._index_data = {"pageProps": {"productInfoData": {"articles": []}}}
    rn = {"pageProps": {"content": {"changes": [{"updates": [{
        "tags": ["Самозанятые"],
        "content": "* POST /jp/v1/esop/self-employed/register - Регистрация самозанятого",
    }]}]}}}
    with mock.patch.object(p, "_fetch_json", return_value=rn):
        services = p._strategy_release_notes_supplement()
    (method,) = services["Самозанятые"]
    assert method.hidden is True
    assert method.hidden_reason == HIDDEN_REASON_GHOST
    assert method.path == "/jp/v1/esop/self-employed/register"


def test_parse_fails_when_release_notes_are_unavailable(parser, monkeypatch):
    monkeypatch.setattr(parser, "_get_build_hash_via_requests", lambda: "build123456")
    monkeypatch.setattr(parser, "_fetch_json", lambda url: None if "release-notes" in url else INDEX)
    monkeypatch.setattr(parser, "_fetch_article_page",
                        lambda path, depth=0: _page("POST", "https://h/api/v1/x"))
    with pytest.raises(ParserError, match="release notes"):
        parser.parse()


def test_capped_text_via_rejects_cross_host_redirect_and_never_requests_target(parser):
    """SSRF via redirect: a threaded fetch (`_capped_text_via` runs on the
    worker-thread session, not `self.session`) must refuse a redirect that
    leaves the originally requested host, before making a request to it."""
    session = _Session([_Resp(status=302, location="http://169.254.169.254/latest/meta-data/")])

    with pytest.raises(ParserError):
        parser._capped_text_via(session, "https://developers.alfabank.ru/x", 5)

    assert session.urls == ["https://developers.alfabank.ru/x"]


def test_capped_text_via_decodes_utf8_body_despite_resp_encoding_defaulting_to_latin1(parser):
    """`requests` defaults `resp.encoding` to ISO-8859-1 for any text/* response
    whose server did not declare a charset (RFC 2616 default) -- confirmed live
    against Alfa's own portal HTML pages. `_capped_text_via` must decode via
    `BaseParser._charset_of`, not `resp.encoding`, or Cyrillic bodies come out
    mangled."""
    body = "Выписки по счёту"
    session = _Session([
        _Resp(body=body, headers={"Content-Type": "text/html"}, encoding="ISO-8859-1"),
    ])

    text = parser._capped_text_via(session, "https://developers.alfabank.ru/x", 5)

    assert text == body
