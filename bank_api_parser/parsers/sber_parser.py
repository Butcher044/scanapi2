"""
Sber parser.

Products: Sber API, GigaChat API, SaluteSpeech API. Exclude: SaluteBot.

Strategy per product:
- Sber API: Download YAML specs from /docs/files/openapi/sbapi/{slug}.yaml
  (each section has a separate spec, ~29 sections total).
  This gives complete method coverage + full JSON examples from schemas.
- GigaChat API: Playwright text-scan (flat page, works well).
- SaluteSpeech API: Playwright link-scan (hierarchical but small).

Key insight: Sber portal YAML files contain control characters (x9c etc.)
that strict YAML parsers reject → must strip before parsing.
"""
import json
import logging
import re
import time
import yaml
from datetime import datetime
from typing import Optional

import requests

from .base_parser import APIMethod, BaseParser, ParseSnapshot

logger = logging.getLogger("parser.sber")

PORTAL_BASE = "https://developers.sber.ru"
SBER_SPEC_BASE = f"{PORTAL_BASE}/docs/files/openapi/sbapi"

# All known Sber API section slugs with downloadable YAML specs.
# (card-issues, corporate-cards, generic-letters have no spec file → 404)
SBER_API_SECTIONS = [
    "acceptance-advances",
    "bank-control-statements",
    "claims",
    "client-info",
    "confirmatory-documents-inquiry",
    "conv-currency",
    "correspondents",
    "credit-offers",
    "credit-requests",
    "crypto",
    "curr-control-messages",
    "currency-operation-details",
    "dicts",
    "encashment",
    "files",
    "nominal-accounts",
    "oauth",
    "partner-info",
    "pay-doc-cur",
    "payment-link",
    "payment-requests",
    "payments",
    "payrolls",
    "placement",
    "salary-agreements",
    "self-employed",
    "statement",
    "tax-deduction",
    "transfer",
]

PLAYWRIGHT_PRODUCTS = [
    {
        "name": "GigaChat API",
        "entry_urls": [
            f"{PORTAL_BASE}/docs/ru/gigachat/api/reference/rest/gigachat-api",
        ],
        "path_prefix": "/docs/ru/gigachat",
        "link_filter": "/gigachat/",
        "flat": True,
    },
    {
        "name": "SaluteSpeech API",
        "entry_urls": [
            f"{PORTAL_BASE}/docs/ru/salutespeech/recognition/rest-api/start",
            f"{PORTAL_BASE}/docs/ru/salutespeech/synthesis/rest-api/start",
            f"{PORTAL_BASE}/docs/ru/salutespeech/rest-api/reference/",
            f"{PORTAL_BASE}/docs/ru/salutespeech/",
        ],
        "path_prefix": "/docs/ru/salutespeech",
        "link_filter": "/salutespeech/",
    },
]

EXCLUDED_PRODUCTS = {"salutebot", "salute bot"}

# HTTP verb prefixes in URL slugs: post-token, get-models, put-something
SLUG_VERB_RE = re.compile(r"^(?:.*/)?(get|post|put|patch|delete)-(.+)$", re.I)

# HTTP method in text like "GET\nDescription" or "POST Description"
TEXT_VERB_RE = re.compile(
    r"^(GET|POST|PUT|PATCH|DELETE)[\s\n:]+(.{0,120})?", re.I | re.DOTALL
)

# Broad path pattern in text
HTTP_PATH_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+(/[A-Za-z0-9_/\-\{\}\.]{4,80})",
    re.I,
)

GOTO_TIMEOUT = 60_000
CONTENT_WAIT_MS = 8_000
PAGE_VISIT_TIMEOUT = 20_000


class SberParser(BaseParser):
    def __init__(self):
        super().__init__("sber")

    def parse(self) -> Optional[ParseSnapshot]:
        self.logger.info("Starting Sber parser")
        all_services: dict = {}

        # ── Sber API: download YAML specs (fast, complete, accurate) ──────
        sber_api_services = self._parse_sber_api_via_yaml()
        if sber_api_services:
            all_services.update(sber_api_services)
            count = sum(len(v) for v in sber_api_services.values())
            self.logger.info("Sber API (YAML): %d services, %d methods", len(sber_api_services), count)
        else:
            self.logger.warning("Sber API YAML strategy returned nothing")

        # ── GigaChat + SaluteSpeech: Playwright ───────────────────────────
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error("playwright not installed — skipping GigaChat/SaluteSpeech")
            if not all_services:
                return None
        else:
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    ctx = browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Safari/537.36"
                        ),
                        locale="ru-RU",
                        viewport={"width": 1440, "height": 900},
                    )
                    page = ctx.new_page()
                    for product in PLAYWRIGHT_PRODUCTS:
                        if any(excl in product["name"].lower() for excl in EXCLUDED_PRODUCTS):
                            continue
                        self.logger.info("Parsing (Playwright): %s", product["name"])
                        services = self._parse_product(page, product)
                        if services:
                            count_m = sum(len(v) for v in services.values())
                            self.logger.info("%s: %d services, %d methods", product["name"], len(services), count_m)
                            all_services.update(services)
                        else:
                            self.logger.warning("No data for %s", product["name"])
                        time.sleep(3)
                    browser.close()
            except Exception as exc:
                self.logger.error("Playwright portion failed: %s", exc, exc_info=True)

        if not all_services:
            self.logger.error("Sber: no data extracted")
            return None

        snapshot = self._make_snapshot(all_services)
        self.logger.info("Sber total: %d services, %d methods", snapshot.total_services, snapshot.total_methods)
        return snapshot

    # ─── Sber API: YAML spec download strategy ────────────────────────────

    @staticmethod
    def _fix_yaml_control_chars(text: str) -> str:
        """Strip control characters that yaml.safe_load rejects (e.g. x9c from Sber docs)."""
        # Keep \t (x09), \n (x0a), \r (x0d)
        return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)

    def _download_sber_yaml(self, slug: str) -> Optional[dict]:
        url = f"{SBER_SPEC_BASE}/{slug}.yaml"
        try:
            r = self.session.get(url, timeout=30)
            if r.status_code != 200:
                self.logger.debug("[Sber] YAML %s → HTTP %d", slug, r.status_code)
                return None
            # Decode as UTF-8 explicitly (requests defaults to ISO-8859-1 for text/*
            # when charset is absent, which garbles Russian Cyrillic)
            text = r.content.decode("utf-8", errors="replace")
            text = self._fix_yaml_control_chars(text)
            return yaml.safe_load(text)
        except Exception as exc:
            self.logger.debug("[Sber] YAML %s failed: %s", slug, exc)
            return None

    def _parse_sber_api_via_yaml(self) -> dict:
        """Download and parse all Sber API section YAML specs."""
        all_services: dict = {}
        for slug in SBER_API_SECTIONS:
            spec = self._download_sber_yaml(slug)
            if not spec:
                continue
            # Use section overview page as portal URL
            portal_url = f"{PORTAL_BASE}/docs/ru/sber-api/specifications/{slug}"
            section_services = self._parse_openapi_spec(spec, portal_url)
            if not section_services:
                self.logger.debug("[Sber] No methods in %s", slug)
                continue
            count = sum(len(v) for v in section_services.values())
            self.logger.debug("[Sber] %s: %d services, %d methods", slug, len(section_services), count)
            for svc_name, methods in section_services.items():
                # Prefix with "Sber API / " if service name doesn't already have it
                if not svc_name.startswith("Sber API"):
                    final_svc = f"Sber API / {svc_name}"
                else:
                    final_svc = svc_name
                for m in methods:
                    m.service_name = final_svc
                all_services.setdefault(final_svc, []).extend(methods)
        return all_services

    # ─── Per-product entry ────────────────────────────────────────────────

    def _parse_product(self, page, product: dict) -> dict:
        for url in product["entry_urls"]:
            loaded = self._load_page(page, url)
            if not loaded:
                continue

            # Step 1: text scan on current page (works great for GigaChat overview)
            services = self._extract_methods_from_current_page(page, product)
            if services:
                total = sum(len(v) for v in services.values())
                if total >= 5:
                    return services

            # Step 2: collect nav/content links, then visit service pages
            services = self._extract_via_links(page, product)
            if services:
                return services

        return {}

    def _load_page(self, page, url: str) -> bool:
        try:
            page.goto(url, timeout=GOTO_TIMEOUT, wait_until="domcontentloaded")
            page.wait_for_timeout(CONTENT_WAIT_MS)
            return True
        except Exception as exc:
            self.logger.warning("Load failed for %s: %s", url, exc)
            return False

    # ─── Strategy A: text + link scan on current page ─────────────────────

    def _extract_methods_from_current_page(self, page, product: dict) -> dict:
        """Extract methods visible on a single page (text scan + link analysis).

        Full-body text scan is restricted to flat APIs (GigaChat) where the
        format is clean and reliable.  For Sber API / SaluteSpeech the full-page
        scan generates false positives — prose mentions, cross-references, and
        navigation links all match HTTP_PATH_RE and create ghost methods.
        Those products rely on the link-based extraction below instead.
        """
        services: dict = {}
        now = datetime.utcnow().isoformat()
        seen: set = set()

        flat = product.get("flat", False)

        # Full-body text scan: GigaChat only (flat=True, clean tabular format)
        if flat:
            try:
                text = page.inner_text("body") or ""
                for verb, path in HTTP_PATH_RE.findall(text):
                    key = f"{verb.upper()}:{path}"
                    if key in seen:
                        continue
                    seen.add(key)
                    svc = self._service_from_path(path, product["name"], flat)
                    services.setdefault(svc, []).append(APIMethod(
                        bank=self.bank_name,
                        service_name=svc,
                        http_method=verb.upper(),
                        path=path,
                        summary=f"{verb.upper()} {path}",
                        description="",
                        response_200_fields=[],
                        parsed_at=now,
                        url_on_portal=page.url,
                    ))
            except Exception:
                pass

        # Analyze links — extract verb from text or slug
        try:
            links = page.query_selector_all("a[href]")
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    if not self._is_relevant_link(href, product):
                        continue
                    link_text = (link.inner_text() or "").strip()

                    verb, summary = self._verb_and_summary_from_link(href, link_text)
                    if not verb:
                        continue

                    # Derive service from URL path
                    svc = product["name"] if flat else self._service_from_url_path(href, product["name"])
                    portal_url = f"{PORTAL_BASE}{href}" if href.startswith("/") else href
                    path = self._path_from_slug(href) or href

                    key = f"{verb}:{path}"
                    if key in seen:
                        continue
                    seen.add(key)

                    services.setdefault(svc, []).append(APIMethod(
                        bank=self.bank_name,
                        service_name=svc,
                        http_method=verb,
                        path=path,
                        summary=summary or f"{verb} {path}",
                        description="",
                        response_200_fields=[],
                        parsed_at=now,
                        url_on_portal=portal_url,
                    ))
                except Exception:
                    pass
        except Exception:
            pass

        return services

    # ─── Strategy B: visit service pages ─────────────────────────────────

    def _extract_via_links(self, page, product: dict) -> dict:
        """
        Collect service-level links from current page, visit each service page,
        extract methods via text scan + link analysis.
        """
        services: dict = {}
        now = datetime.utcnow().isoformat()

        # Collect service links (1 level deep) from current page
        service_links = self._collect_service_links(page, product)
        self.logger.info(
            "[Sber %s] Found %d service pages to visit",
            product["name"], len(service_links)
        )

        # Limit visits: max 40 pages to keep runtime under 5 min for Sber API
        for href, service_name in list(service_links.items())[:40]:
            url = f"{PORTAL_BASE}{href}" if href.startswith("/") else href
            self.logger.debug("[Sber] Visiting service page: %s", url)
            try:
                page.goto(url, timeout=PAGE_VISIT_TIMEOUT, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                # Try to extract JSON examples from this page's code blocks
                req_ex, resp_ex = self._extract_json_examples_from_page(page)

                page_services = self._extract_methods_from_current_page(page, product)
                for svc, methods in page_services.items():
                    final_svc = service_name or svc
                    for m in methods:
                        m.service_name = final_svc
                        # Assign examples to all methods found on this page
                        if not m.request_example and req_ex:
                            m.request_example = req_ex
                        if not m.response_example and resp_ex:
                            m.response_example = resp_ex
                    services.setdefault(final_svc, []).extend(methods)

                time.sleep(1)
            except Exception as exc:
                self.logger.debug("[Sber] Failed to visit %s: %s", url, exc)

        return services

    def _collect_service_links(self, page, product: dict) -> dict:
        """
        Collect {href: service_name} for service/section pages.
        Includes overview pages — they list individual method sub-links.
        Method pages (verb-prefix slug) are skipped here; they're found
        when we visit the overview pages in _extract_via_links.
        """
        result = {}
        try:
            links = page.query_selector_all("a[href]")
            for link in links:
                try:
                    href = link.get_attribute("href") or ""
                    if not href or not self._is_relevant_link(href, product):
                        continue

                    slug = href.rstrip("/").split("/")[-1]

                    # Skip the top-level "overview" (the page we're already on)
                    if href == product.get("entry_urls", [""])[0].replace(
                        "https://developers.sber.ru", ""
                    ):
                        continue

                    # Skip pure HTTP method pages if we already have enough to group by
                    # (we'll find method links BY VISITING service pages)

                    text = (link.inner_text() or "").strip()
                    if not text or len(text) < 2:
                        continue
                    if href not in result:
                        result[href] = text[:60]
                except Exception:
                    pass
        except Exception:
            pass
        return result

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _is_relevant_link(self, href: str, product: dict) -> bool:
        """Check if this link belongs to the current product's docs."""
        if not href:
            return False
        filter_kw = product.get("link_filter", "")
        return filter_kw in href

    def _verb_and_summary_from_link(self, href: str, text: str) -> tuple:
        """
        Try to extract HTTP verb + summary from link text or URL slug.
        GigaChat links look like: text="GET\nСписок моделей", href="/docs/.../get-models"
        Sber links look like: href="/docs/.../post-statement"
        """
        # Try link text first: "GET\nDescription" format
        m = TEXT_VERB_RE.match(text)
        if m:
            verb = m.group(1).upper()
            summary = (m.group(2) or "").strip().split("\n")[0][:100]
            return verb, summary

        # Try URL slug: "post-token", "get-models"
        slug = href.rstrip("/").split("/")[-1]
        sm = re.match(r"^(get|post|put|patch|delete)-(.+)$", slug, re.I)
        if sm:
            verb = sm.group(1).upper()
            summary = sm.group(2).replace("-", " ").title()
            return verb, summary

        return "", text[:80]

    def _extract_json_examples_from_page(self, page) -> tuple:
        """Scrape request/response JSON examples from a Playwright page.

        Sber portal renders JSON in:
          <div class='openapi-demo__code-block-container ... language-json ...'>
          <pre class='prism-code language-json ...'>

        We target those specific classes first, then fall back to generic pre/code.
        """
        req_ex: dict = {}
        resp_ex: dict = {}
        try:
            raw_texts = page.evaluate("""() => {
                // Priority 1: Sber-specific JSON code block containers
                const sberSel = [
                    'pre[class*="language-json"]',
                    'div[class*="language-json"]',
                    'div[class*="code-block"][class*="json"]',
                    'div[class*="openapi-demo__code-block"]',
                    '[class*="prism-code"][class*="language-json"]',
                ];
                const found = [];
                for (const sel of sberSel) {
                    const els = document.querySelectorAll(sel);
                    for (const el of els) {
                        const text = (el.innerText || el.textContent || '').trim();
                        if (text.startsWith('{') || text.startsWith('[')) {
                            found.push(text);
                            if (found.length >= 10) break;
                        }
                    }
                    if (found.length >= 2) break;
                }
                // Fallback: generic pre/code
                if (found.length === 0) {
                    const els = document.querySelectorAll('pre, code');
                    for (const el of Array.from(els).slice(0, 40)) {
                        const text = (el.innerText || el.textContent || '').trim();
                        if (text.startsWith('{') || text.startsWith('[')) {
                            found.push(text);
                        }
                    }
                }
                return found.slice(0, 10);
            }""")

            json_blocks = []
            for text in (raw_texts or []):
                text = (text or "").strip()
                if not text:
                    continue
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and data:
                        json_blocks.append(data)
                    elif isinstance(data, list) and data and isinstance(data[0], dict):
                        json_blocks.append({"items": data})
                except (json.JSONDecodeError, ValueError):
                    pass

            if len(json_blocks) >= 2:
                req_ex  = json_blocks[0]
                resp_ex = json_blocks[-1]
            elif len(json_blocks) == 1:
                resp_ex = json_blocks[0]
        except Exception as exc:
            self.logger.debug("[Sber] JSON example extraction error: %s", exc)
        return req_ex, resp_ex

    def _path_from_slug(self, href: str) -> str:
        """
        Try to reconstruct API path from URL slug.
        e.g. get-models → /models, post-chat-completions → /chat/completions
        But for Sber, the slug is just a doc page name, not the API path.
        Returns empty string if not determinable.
        """
        return ""

    def _service_from_url_path(self, href: str, product_name: str) -> str:
        """Derive service name from URL path, grouping by penultimate path segment."""
        parts = [p for p in href.split("/") if p]
        # Remove common prefixes
        meaningful = [p for p in parts if p.lower() not in (
            "docs", "ru", "en", "api", "reference", "rest", "rest-api",
            "sber-api", "gigachat", "salutespeech", "specifications",
        )]
        if len(meaningful) >= 2:
            # Use second meaningful segment as service group
            svc = meaningful[1].replace("-", " ").title()
            return f"{product_name} / {svc}"
        if meaningful:
            svc = meaningful[0].replace("-", " ").title()
            return f"{product_name} / {svc}"
        return product_name

    def _service_from_path(self, api_path: str, product_name: str, flat: bool = False) -> str:
        """Derive service name from an API endpoint path like /api/v1/chat/completions."""
        if flat:
            return product_name
        parts = [p for p in api_path.split("/") if p and not re.match(r"^v\d+$", p)]
        # Paths with only 1 meaningful segment (like /models, /files) → use product name
        if len(parts) <= 1:
            return product_name
        if len(parts) >= 2:
            # Skip generic prefixes
            if parts[0].lower() in ("api",):
                svc = parts[1] if len(parts) > 2 else parts[0]
            else:
                svc = parts[1] if len(parts) > 1 else parts[0]
            return f"{product_name} / {svc.replace('-', ' ').title()}"
        return product_name
