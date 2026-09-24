"""Sber parser: section discovery, hidden-method marking, and failure policy (offline)."""
import pytest
import requests

from bank_api_parser.parsers import sber_parser as sber
from bank_api_parser.parsers.base_parser import HIDDEN_REASON_NOT_IN_MENU, ParserError

OVERVIEW = """
<a href="/docs/ru/sber-api/specifications/overview">Обзор</a>
<a class="menu__link menu__link--not-first-level" href="/docs/ru/sber-api/specifications/payments/payments-overview"><div class="x">Рублевое платежное поручение</div><svg></svg></a>
<a class="menu__link" href="/docs/ru/sber-api/specifications/qr"><div class="y">Универсальный QR-код &amp; СБП</div></a>
<a href="/docs/ru/sber-api/specifications/payments#x">dup</a>
<a href="/docs/ru/sber-api/specifications/conv-currency">no menu title</a>
<a href="/docs/ru/sber-api/specifications/brand-new">no title anywhere</a>
"""

PAYMENTS = """openapi: 3.0.0
info: {title: Платежи\x9c}
paths:
  /v1/payments:
    get:
      tags: [Платежи]
      operationId: listPayments
      responses: {}
  /v1/payments/{id}:
    get:
      tags: [Sber API / Платежи]
      operationId: getPayment
      responses: {}
"""


class _Resp:
    def __init__(self, status=200, text=""):
        self.status_code, self.content = status, text.encode("utf-8")
        self.encoding = "utf-8"

    @property
    def text(self):
        return self.content.decode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            # Real requests.Response.raise_for_status() attaches itself as
            # `.response` -- _download_spec relies on that to special-case 404.
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)

    def iter_content(self, chunk_size=65536):
        data = self.text.encode("utf-8")
        for start in range(0, len(data), chunk_size):
            yield data[start:start + chunk_size]


class _Session:
    def __init__(self, routes):
        self.routes = routes
        self.urls = []

    def get(self, url, timeout=None, stream=False, allow_redirects=True):
        self.urls.append(url)
        r = self.routes.get(url, _Resp(404))
        if isinstance(r, Exception):
            raise r
        return r


def _parser(routes):
    p = sber.SberParser()
    p.session = _Session(routes)
    return p


# Minimal overview with exactly one, plain section — most tests build on this
# so a 404 on an unrelated section never leaks in as a spurious failure.
ONE_SECTION_OVERVIEW = (
    '<a class="menu__link" href="/docs/ru/sber-api/specifications/demo">'
    '<div>Рублевое платежное поручение</div></a>'
)

NOMINAL_ACCOUNTS_BE = """openapi: 3.0.0
paths:
  /v1/nominal-accounts-be/deal:
    post:
      operationId: nominalAccountsBeDeal
      responses: {}
"""

BASE_ROUTES = {
    sber.SECTIONS_URL: _Resp(text=ONE_SECTION_OVERVIEW),
    f"{sber.SPEC_BASE}/demo.yaml": _Resp(text=PAYMENTS),
    # EXTRA_SECTIONS always adds nominal-accounts-be regardless of the menu fixture.
    f"{sber.SPEC_BASE}/nominal-accounts-be.yaml": _Resp(text=NOMINAL_ACCOUNTS_BE),
}


def test_sections_are_discovered_with_portal_menu_titles():
    assert sber.SberParser._sections(OVERVIEW) == {
        "brand-new": "brand-new",                          # last resort: the slug itself
        "conv-currency": "Конвертация валюты",             # not in the menu: built-in title
        "payments": "Рублевое платежное поручение",
        "qr": "Универсальный QR-код & СБП",                # HTML entities decoded
    }


def test_discover_sections_adds_extra_sections_not_in_the_live_menu():
    """nominal-accounts-be is never linked from the top-level nav (only reachable
    by expanding "Безопасные сделки"); it must still be discovered."""
    sections = _parser(BASE_ROUTES)._discover_sections()
    assert sections["nominal-accounts-be"] == "Бенефициар-исполнитель"
    assert sections["demo"] == "Рублевое платежное поручение"


def test_one_section_is_one_service_named_after_the_menu_title():
    snap = _parser(BASE_ROUTES).parse()
    methods = snap.services["Рублевое платежное поручение"]
    assert {m.path for m in methods} == {"/v1/payments", "/v1/payments/{id}"}
    assert all(m.service_name == "Рублевое платежное поручение" for m in methods)
    assert all(not m.hidden and m.hidden_reason is None for m in methods)


def test_sections_sharing_a_title_are_merged():
    routes = {
        sber.SECTIONS_URL: _Resp(text='''
<a class="menu__link" href="/docs/ru/sber-api/specifications/svc-a"><div>Платежи</div></a>
<a class="menu__link" href="/docs/ru/sber-api/specifications/svc-b"><div>Платежи</div></a>'''),
        f"{sber.SPEC_BASE}/svc-a.yaml": _Resp(text=PAYMENTS),
        f"{sber.SPEC_BASE}/svc-b.yaml": _Resp(text=PAYMENTS.replace("/v1/payments", "/v1/qr")),
        f"{sber.SPEC_BASE}/nominal-accounts-be.yaml": _Resp(text=NOMINAL_ACCOUNTS_BE),
    }
    snap = _parser(routes).parse()
    assert "Платежи" in snap.services
    assert len(snap.services["Платежи"]) == 4


@pytest.mark.parametrize("override,match", [
    ({sber.SECTIONS_URL: _Resp(503)}, "section list unavailable"),
    ({sber.SECTIONS_URL: _Resp(text="<html></html>")}, "no API sections"),
    ({f"{sber.SPEC_BASE}/demo.yaml": _Resp(404)}, "spec not found"),
    ({f"{sber.SPEC_BASE}/demo.yaml": _Resp(500)}, "failed to download"),
    ({f"{sber.SPEC_BASE}/demo.yaml": requests.ConnectionError("x")}, "failed to download"),
    ({f"{sber.SPEC_BASE}/demo.yaml": _Resp(text="a: [b")}, "invalid spec"),
    ({f"{sber.SPEC_BASE}/demo.yaml": _Resp(text="<html>maintenance</html>")}, "not an OpenAPI"),
])
def test_any_failure_rejects_the_whole_parse(override, match):
    with pytest.raises(ParserError, match=match):
        _parser({**BASE_ROUTES, **override}).parse()


def test_a_404_on_any_discovered_section_is_now_loud_not_silently_skipped():
    """Every section the menu links to is known to have a real spec — a 404
    means the map has drifted, so it must abort the parse, not vanish quietly."""
    routes = {
        sber.SECTIONS_URL: _Resp(text=OVERVIEW),  # discovers payments, qr, conv-currency, brand-new
        f"{sber.SPEC_BASE}/payments.yaml": _Resp(text=PAYMENTS),
        # qr, conv-currency, brand-new specs are not routed -> 404 by default
    }
    with pytest.raises(ParserError, match="spec not found"):
        _parser(routes).parse()


def test_discover_sections_rejects_an_oversized_overview_page():
    """The overview page is downloaded through `_get_capped_text` just like
    every spec — a runaway/compromised portal answering with an endlessly
    inflating body must abort with ParserError, not be read into memory whole."""
    from bank_api_parser.parsers.base_parser import MAX_RESPONSE_BYTES

    oversized = "x" * (MAX_RESPONSE_BYTES + 1)
    routes = {sber.SECTIONS_URL: _Resp(text=oversized)}
    with pytest.raises(ParserError, match="larger than"):
        _parser(routes)._discover_sections()


def test_no_sections_at_all_is_an_error():
    with pytest.raises(ParserError, match="no API sections found"):
        _parser({sber.SECTIONS_URL: _Resp(text="")}).parse()


def test_yaml_cleanup_removes_control_chars_and_tab_only_lines():
    raw = "a:\n  b: 1\x9c\n\t\t  \n  c: 2\n"
    assert sber.SberParser._fix_yaml_control_chars(raw) == "a:\n  b: 1\n\n  c: 2\n"


# ── Explicit spec map (SECTION_SPECS) ───────────────────────────────────────

def test_section_specs_override_the_guessed_filename_and_url_path():
    """"corporate-cards" (nav slug) really publishes business-cards.yaml, with
    every operation's URL under .../specifications/business-cards/…"""
    spec = """openapi: 3.0.0
paths:
  /v2/corporate-cards/list:
    post:
      operationId: corporateCardsListPost
      responses: {}
"""
    routes = {
        **BASE_ROUTES,
        sber.SECTIONS_URL: _Resp(text=(
            '<a class="menu__link" href="/docs/ru/sber-api/specifications/corporate-cards">'
            '<div>Бизнес-карты</div></a>'
        )),
        f"{sber.SPEC_BASE}/business-cards.yaml": _Resp(text=spec),
    }
    snap = _parser(routes).parse()
    (method,) = snap.services["Бизнес-карты"]
    assert method.url_on_portal == (
        f"{sber.PORTAL_BASE}/docs/ru/sber-api/specifications/business-cards/corporate-cards-list-post"
    )


def test_section_with_two_specs_merges_their_methods_under_one_title():
    """"Универсальный QR-код" (slug "qr") is backed by plati-qr.yml plus a
    second, separately published callback spec (qr-order-notify.yml)."""
    main_spec = """openapi: 3.0.0
paths:
  /v1/qr/create:
    post:
      operationId: qrCreate
      responses: {}
"""
    notify_spec = """openapi: 3.0.0
paths:
  /notify:
    post:
      operationId: qrNotifications
      responses: {}
"""
    routes = {
        sber.SECTIONS_URL: _Resp(text=(
            '<a class="menu__link" href="/docs/ru/sber-api/specifications/qr">'
            '<div>Универсальный QR-код</div></a>'
        )),
        f"{sber.SPEC_BASE}/plati-qr.yml": _Resp(text=main_spec),
        f"{sber.SPEC_BASE}/qr-order-notify.yml": _Resp(text=notify_spec),
        f"{sber.SPEC_BASE}/nominal-accounts-be.yaml": _Resp(text=NOMINAL_ACCOUNTS_BE),
    }
    snap = _parser(routes).parse()
    methods = snap.services["Универсальный QR-код"]
    assert {m.path for m in methods} == {"/v1/qr/create", "/notify"}
    urls = {m.path: m.url_on_portal for m in methods}
    assert urls["/v1/qr/create"].endswith("/qr/plati-qr/qr-create")
    assert urls["/notify"].endswith("/qr/platy-qr-notify/qr-notifications")


def test_multi_spec_section_dedupes_methods_declared_in_both_specs():
    """Two specs backing one section (SECTION_SPECS: qr, payments) can
    redundantly describe the same (method, path); it must be counted once,
    not double the section's visible method count."""
    main_spec = """openapi: 3.0.0
paths:
  /v1/qr/create:
    post:
      operationId: qrCreate
      responses: {}
"""
    notify_spec = """openapi: 3.0.0
paths:
  /v1/qr/create:
    post:
      operationId: qrCreateDuplicate
      responses: {}
  /notify:
    post:
      operationId: qrNotifications
      responses: {}
"""
    routes = {
        sber.SECTIONS_URL: _Resp(text=(
            '<a class="menu__link" href="/docs/ru/sber-api/specifications/qr">'
            '<div>Универсальный QR-код</div></a>'
        )),
        f"{sber.SPEC_BASE}/plati-qr.yml": _Resp(text=main_spec),
        f"{sber.SPEC_BASE}/qr-order-notify.yml": _Resp(text=notify_spec),
        f"{sber.SPEC_BASE}/nominal-accounts-be.yaml": _Resp(text=NOMINAL_ACCOUNTS_BE),
    }
    snap = _parser(routes).parse()
    methods = snap.services["Универсальный QR-код"]
    assert {m.path for m in methods} == {"/v1/qr/create", "/notify"}
    assert len(methods) == 2  # not 3: the duplicate /v1/qr/create is dropped


# ── Hidden methods (spec exists, no page in the portal navigation) ─────────

def test_methods_absent_from_portal_navigation_are_marked_hidden_not_in_menu():
    spec = """openapi: 3.0.0
paths:
  /v1/files/list:
    get:
      operationId: filesList
      responses: {}
  /v1/files/tasks-for-download/{taskId}:
    get:
      operationId: taskForDownload
      responses: {}
"""
    routes = {
        sber.SECTIONS_URL: _Resp(text=(
            '<a class="menu__link" href="/docs/ru/sber-api/specifications/files">'
            '<div>Работа с файлами</div></a>'
        )),
        f"{sber.SPEC_BASE}/files.yaml": _Resp(text=spec),
        f"{sber.SPEC_BASE}/nominal-accounts-be.yaml": _Resp(text=NOMINAL_ACCOUNTS_BE),
    }
    snap = _parser(routes).parse()
    by_path = {m.path: m for m in snap.services["Работа с файлами"]}
    assert not by_path["/v1/files/list"].hidden
    assert by_path["/v1/files/tasks-for-download/{taskId}"].hidden
    assert by_path["/v1/files/tasks-for-download/{taskId}"].hidden_reason == HIDDEN_REASON_NOT_IN_MENU


def test_a_section_with_no_page_anywhere_is_hidden_wholesale():
    """conv-currency: the spec exists, but no page in the portal navigation
    links to it at all — every method is hidden, the section itself is kept
    (not dropped) so an admin can still see it."""
    spec = """openapi: 3.0.0
paths:
  /v1/conv-currency:
    post:
      operationId: create
      responses: {}
  /v1/conv-currency/{externalId}:
    get:
      operationId: get
      responses: {}
"""
    routes = {
        sber.SECTIONS_URL: _Resp(text=(
            '<a href="/docs/ru/sber-api/specifications/conv-currency">no menu title</a>'
        )),
        f"{sber.SPEC_BASE}/conv-currency.yaml": _Resp(text=spec),
        f"{sber.SPEC_BASE}/nominal-accounts-be.yaml": _Resp(text=NOMINAL_ACCOUNTS_BE),
    }
    snap = _parser(routes).parse()
    methods = snap.services["Конвертация валюты"]
    assert len(methods) == 2
    assert all(m.hidden and m.hidden_reason == HIDDEN_REASON_NOT_IN_MENU for m in methods)


# ── spec_url propagation (external $ref resolution) ─────────────────────────

def test_spec_url_is_passed_through_so_external_refs_resolve():
    """Sber specs $ref into sibling files (common/*.yml); without spec_url=
    those refs cannot be resolved and silently yield an empty example."""
    spec = """openapi: 3.0.0
paths:
  /v1/payments:
    post:
      operationId: createPayment
      requestBody:
        content:
          application/json:
            schema:
              $ref: './common/models.yml#/components/schemas/PaymentRequest'
      responses: {}
"""
    external = """components:
  schemas:
    PaymentRequest:
      type: object
      properties:
        amount:
          type: integer
          example: 100
"""
    routes = {
        **BASE_ROUTES,
        f"{sber.SPEC_BASE}/demo.yaml": _Resp(text=spec),
        f"{sber.SPEC_BASE}/common/models.yml": _Resp(text=external),
    }
    snap = _parser(routes).parse()
    (method,) = snap.services["Рублевое платежное поручение"]
    assert method.request_example == {"amount": 100}


# ── Portal URL / kebab-case ─────────────────────────────────────────────────

@pytest.mark.parametrize("op_id,expected", [
    ("listPayments", "list-payments"),
    ("createQRcreditRPP", "create-qrcredit-rpp"),
    ("getStatusV2", "get-status-v-2"),
    ("", ""),
])
def test_kebab_case_matches_lodash_word_boundaries(op_id, expected):
    assert sber.SberParser._kebab(op_id) == expected


def test_portal_url_falls_back_to_the_section_page_without_an_operation_id():
    spec = """openapi: 3.0.0
paths:
  /v1/payments:
    get:
      responses: {}
"""
    routes = {**BASE_ROUTES, f"{sber.SPEC_BASE}/demo.yaml": _Resp(text=spec)}
    snap = _parser(routes).parse()
    (method,) = snap.services["Рублевое платежное поручение"]
    assert method.url_on_portal == f"{sber.PORTAL_BASE}/docs/ru/sber-api/specifications/demo"
