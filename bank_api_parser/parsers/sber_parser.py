"""
Sber parser (Sber API only).

Section list is discovered from the specifications overview page; each section
publishes its own OpenAPI YAML at /docs/files/openapi/sbapi/{slug}.yaml — except
where the portal's real file name (or URL) differs from that guess. Those
exceptions (and a handful of methods whose spec exists but has no page in the
portal navigation) were found by a one-time manual audit against the live
portal (findings.md, "Phase 11 — аудит Сбера") and are hardcoded below: the
live menu remains the primary discovery mechanism for the ~30 regular
sections, the explicit maps only correct the known drift.

A spec that 404s is now a hard failure (ParserError), not a silent skip: every
section the menu currently links to has a real spec, so a 404 means our map is
stale, not that the section legitimately has no API.

Sber portal YAML files contain control characters (x9c etc.) that strict
YAML parsers reject, so they are stripped before parsing.
"""
import html
import re
from dataclasses import replace
from typing import Optional

import requests
import yaml

from .base_parser import (
    HIDDEN_REASON_NOT_IN_MENU,
    APIMethod,
    BaseParser,
    ParserError,
    ParseSnapshot,
)

PORTAL_BASE = "https://developers.sber.ru"
SPEC_BASE = f"{PORTAL_BASE}/docs/files/openapi/sbapi"
SECTIONS_URL = f"{PORTAL_BASE}/docs/ru/sber-api/specifications/overview"
SECTION_LINK_RE = re.compile(r"/docs/ru/sber-api/specifications/([a-z0-9][a-z0-9\-]*)")
# Side-menu entry: <a class="menu__link ..." href=".../{slug}[/page]"><div ...>Title</div>
MENU_TITLE_RE = re.compile(
    r'<a class="menu__link[^"]*" href="/docs/ru/sber-api/specifications/([a-z0-9][a-z0-9\-]*)(?:[/#][^"]*)?"[^>]*>'
    r'\s*<div[^>]*>([^<]+)</div>'
)
NON_SECTION_SLUGS = {"overview"}
# Sections the menu links to (findable via SECTION_LINK_RE) but never labels with a menu__link
FALLBACK_TITLES = {"conv-currency": "Конвертация валюты"}
TIMEOUT = 30

# Sections the top-level navigation never links to at all — only reachable by
# expanding a *different* section in the sidebar (here: "Безопасные сделки" /
# nominal-accounts). Kept as its own service, not merged into "Безопасные
# сделки": the two specs share 9 identical METHOD+path pairs, which would
# silently double-count if they landed under the same title.
EXTRA_SECTIONS = {"nominal-accounts-be": "Бенефициар-исполнитель"}

# slug (as discovered from the portal's own navigation) -> explicit
# [(spec filename, URL path segment for that spec's operations), ...].
# Overrides the "{slug}.yaml" / url==slug guess where the portal's real file
# name or per-operation URL differs from it. Sections not listed here keep
# the guess: a single spec at "{slug}.yaml", URL path segment == slug.
SECTION_SPECS: dict[str, list[tuple[str, str]]] = {
    # nav slug is "corporate-cards" (title "Бизнес-карты"); the spec file and
    # every operation's URL live under "business-cards" instead.
    "corporate-cards": [("business-cards.yaml", "business-cards")],
    # spec file extension is .yml, not the guessed .yaml.
    "card-issues": [("card-issues.yml", "card-issues")],
    # "Универсальный QR-код": main spec is plati-qr.yml (.yml, under qr/plati-qr/),
    # plus a second, separately published callback spec for its notification page.
    "qr": [
        ("plati-qr.yml", "qr/plati-qr"),
        ("qr-order-notify.yml", "qr/platy-qr-notify"),
    ],
    # "Рублевое платежное поручение" ships a second spec (qr-confirm) whose one
    # operation has its own portal page (payments/qr-confirm) alongside payments.yaml.
    "payments": [
        ("payments.yaml", "payments"),
        ("qr-confirm.yaml", "payments"),
    ],
    "nominal-accounts-be": [("nominal-accounts-be.yaml", "nominal-accounts-be")],
}

# spec-file stem -> set of (HTTP method, path) that the spec describes but the
# portal navigation never links to (verified live; findings.md Phase 11).
NOT_IN_MENU_METHODS: dict[str, set[tuple[str, str]]] = {
    "business-cards": {("POST", "/v2/corporate-cards/transactions-for-period")},
    "files": {("GET", "/v1/files/tasks-for-download/{taskId}")},
    "placement": {
        ("POST", "/v1/placement/deposit/application"),
        ("POST", "/v1/placement/deposit/application/interest-rate"),
        ("POST", "/v1/placement/minimum-balance/application"),
        ("POST", "/v1/placement/minimum-balance/application/interest-rate"),
    },
    "transfer": {
        ("POST", "/v1/sbp/paymentB2C/batchExecute"),
        ("GET", "/v1/sbp/paymentB2C/getBatchStatus/batch/{batchUid}"),
    },
}
# spec-file stems whose entire spec has no page anywhere in the portal navigation.
NOT_IN_MENU_SECTIONS: set[str] = {"conv-currency"}

# Keep \t (x09), \n (x0a), \r (x0d)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# Whitespace-only lines containing tabs (seen in self-employed.yaml) are a YAML syntax error
BLANK_LINE_RE = re.compile(r"^[ \t]+$", re.MULTILINE)

_CAMEL_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")
_ALPHA_DIGIT_BOUNDARY_RE = re.compile(r"([A-Za-z])([0-9])")
_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]+")


class SberParser(BaseParser):
    def __init__(self):
        super().__init__("sber")

    def parse(self) -> ParseSnapshot:
        self.logger.info("Starting Sber parser")
        sections = self._discover_sections()
        self.logger.info("[Sber] %d sections discovered", len(sections))

        services: dict = {}
        for slug, title in sections.items():
            methods = self._section_methods(slug, title)
            services[title] = [*services.get(title, []), *methods]

        if not services:
            raise ParserError("no methods found in any Sber API spec")
        snapshot = self._make_snapshot(services)
        self.logger.info("Sber total: %d services, %d methods", snapshot.total_services, snapshot.total_methods)
        return snapshot

    def _discover_sections(self) -> dict[str, str]:
        """The overview page is fetched through `_get_capped_text` (chunked,
        size-capped): a compromised/broken portal answering with an endlessly
        inflating body must not be read into memory whole -- same risk class
        already closed for specs in `_download_spec`. A size overflow raises
        ParserError, which must reach the caller as-is, not be swallowed."""
        try:
            text = self._get_capped_text(SECTIONS_URL, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ParserError(f"section list unavailable ({SECTIONS_URL}): {exc}") from exc
        sections = self._sections(text)
        if not sections:
            raise ParserError(f"no API sections found on {SECTIONS_URL}")
        # The live menu is the primary source; EXTRA_SECTIONS only fills in the
        # one section the top-level nav never links to (see its docstring).
        for slug, title in EXTRA_SECTIONS.items():
            sections.setdefault(slug, title)
        return sections

    @staticmethod
    def _sections(page: str) -> dict[str, str]:
        """slug -> human title, sorted by slug. Title: side menu, then FALLBACK_TITLES, then the slug."""
        slugs = sorted(set(SECTION_LINK_RE.findall(page)) - NON_SECTION_SLUGS)
        menu: dict[str, str] = {}
        for slug, title in MENU_TITLE_RE.findall(page):
            menu.setdefault(slug, html.unescape(title).strip())
        return {slug: menu.get(slug) or FALLBACK_TITLES.get(slug, slug) for slug in slugs}

    @staticmethod
    def _fix_yaml_control_chars(text: str) -> str:
        """Strip what yaml.safe_load rejects: control chars (e.g. x9c) and tab-only lines."""
        return BLANK_LINE_RE.sub("", CONTROL_CHARS_RE.sub("", text))

    @staticmethod
    def _spec_list(slug: str) -> list[tuple[str, str]]:
        """[(spec filename, URL path segment), ...] for a section slug."""
        return SECTION_SPECS.get(slug, [(f"{slug}.yaml", slug)])

    def _download_spec(self, url: str) -> dict:
        """Parsed spec at `url`. Any failure — 404 included — aborts the whole
        parse: every section the map or the live menu points at is known to
        have a real spec, so a 404 means the map has drifted, not that the
        section legitimately publishes nothing.

        Downloaded through `_get_capped_text` (chunked, size-capped): a
        compromised/broken portal answering with an endlessly inflating body
        must not be read into memory whole."""
        try:
            text = self._get_capped_text(url, timeout=TIMEOUT)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                raise ParserError(f"spec not found: {url}") from exc
            raise ParserError(f"failed to download {url}: {exc}") from exc
        except requests.RequestException as exc:
            raise ParserError(f"failed to download {url}: {exc}") from exc

        text = self._fix_yaml_control_chars(text)
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ParserError(f"invalid spec {url}: {exc}") from exc
        if not isinstance(spec, dict) or "paths" not in spec:
            raise ParserError(f"spec {url} is not an OpenAPI document")
        return spec

    def _section_methods(self, slug: str, title: str) -> list[APIMethod]:
        """All methods of one section, across every spec that backs it (usually
        one), whatever their OpenAPI tags, under the section title.

        A few sections (qr, payments -- see SECTION_SPECS) are backed by more
        than one spec file, and those can redundantly describe the very same
        (http_method, path); such a repeat is dropped so it doesn't inflate
        the section's visible method count."""
        methods = []
        seen: set[tuple[str, str]] = set()
        for filename, section_path in self._spec_list(slug):
            spec_url = f"{SPEC_BASE}/{filename}"
            spec = self._download_spec(spec_url)
            portal_url = f"{PORTAL_BASE}/docs/ru/sber-api/specifications/{section_path}"
            spec_key = filename.rsplit(".", 1)[0]
            for section_methods in self._parse_openapi_spec(spec, portal_url, spec_url=spec_url).values():
                for m in section_methods:
                    key = (m.http_method, m.path)
                    if key in seen:
                        continue
                    seen.add(key)
                    hidden, reason = self._hidden_status(spec_key, m.http_method, m.path)
                    methods.append(replace(m, service_name=title, hidden=hidden, hidden_reason=reason))
        return methods

    @staticmethod
    def _hidden_status(spec_key: str, method: str, path: str) -> tuple[bool, Optional[str]]:
        if spec_key in NOT_IN_MENU_SECTIONS:
            return True, HIDDEN_REASON_NOT_IN_MENU
        if (method, path) in NOT_IN_MENU_METHODS.get(spec_key, ()):
            return True, HIDDEN_REASON_NOT_IN_MENU
        return False, None

    # ── Portal URLs ─────────────────────────────────────────────────────────

    def _portal_url(self, portal_base_url: str, tag: str, op_id: str) -> str:
        """.../specifications/{section}/{lodash-kebab(operationId)} — the plain
        "#{op_id}" anchor 404s almost everywhere on this portal (findings.md)."""
        return f"{portal_base_url}/{self._kebab(op_id)}" if op_id else portal_base_url

    @staticmethod
    def _kebab(op_id: str) -> str:
        """lodash-style kebab-case: word boundaries before an uppercase letter
        or a digit, everything else lower-cased and dash-joined."""
        s = _CAMEL_BOUNDARY_RE.sub(r"\1-\2", op_id)
        s = _ALPHA_DIGIT_BOUNDARY_RE.sub(r"\1-\2", s)
        return _NON_ALNUM_RE.sub("-", s).strip("-").lower()
