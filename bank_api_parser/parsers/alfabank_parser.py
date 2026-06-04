"""
Alfa-Bank parser.

Data sources (in combination):
  1. Article scan via _next/data: fetches EVERY article page → parses YAML
     frontmatter (mdString) → extracts method + production URL → 100% coverage
  2. Release Notes JSON (supplement for very recent adds not yet in articles)

Strategy:
  S0: requests → extract build hash from page HTML
  S1: Playwright → capture _next/data XHR (gets build hash + index.json data)
  After build hash obtained: run full article scan + release-notes supplement
  S2: DOM fallback (text scan) if build hash is unavailable
"""
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import yaml

from .base_parser import APIMethod, BaseParser, ParseSnapshot

logger = logging.getLogger("parser.alfabank")

PORTAL_BASE = "https://developers.alfabank.ru"
DOC_START = (
    f"{PORTAL_BASE}/products/alfa-api/documentation"
    "/articles/specification/articles/intro/intro"
)
RELEASE_NOTES_URL = f"{PORTAL_BASE}/release-notes"

IGNORED_ARTICLES = {
    "как выбрать выписку",
    "как получить файл выписки",
    "получение файла выписки",
    "как это работает",
    "введение",
    "introduction",
    "overview",
    "обзор",
}

PLAYWRIGHT_TIMEOUT = 40_000
CONTENT_WAIT_MS = 6_000

# Pattern for Release Notes method lines: "* POST /path - Description"
RN_METHOD_RE = re.compile(
    r"^\*\s+(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_/\-\{\}\.\*]+)"
    r"(?:\s*[-–—]\s*(.+))?",
    re.MULTILINE | re.I,
)


class AlfaBankParser(BaseParser):
    def __init__(self):
        super().__init__("alfabank")
        self._build_hash: Optional[str] = None
        self._index_data: Optional[dict] = None

        # Alfa-Bank WAF blocks full Chrome UA (returns 6KB JS challenge).
        # Short UA (no "Chrome/x Safari/x" suffix) gets full 750KB SSR HTML.
        self.session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

    def parse(self) -> Optional[ParseSnapshot]:
        self.logger.info("Starting Alfa-Bank parser (article scan + release notes)")

        # S0: get build hash via plain requests (fast path)
        self._build_hash = self._get_build_hash_via_requests()
        if self._build_hash:
            self.logger.info("[Alfa S0] Build hash: %s", self._build_hash)

        # S1: Playwright XHR to get index.json + optionally build hash
        if not self._build_hash:
            self._run_playwright_capture()

        if not self._build_hash:
            self.logger.warning("Build hash unavailable — falling back to DOM scan")
            return self._dom_fallback()

        # Fetch index.json (article tree) if not already captured
        if not self._index_data:
            self._index_data = self._fetch_json(
                f"{PORTAL_BASE}/_next/data/{self._build_hash}/index.json"
                "?productName=alfa-api"
            )

        # Primary: full article scan
        services = self._strategy_article_scan()

        # Supplement with release notes (adds recently-added methods not yet in articles)
        rn_services = self._strategy_release_notes_supplement()
        for svc, methods in rn_services.items():
            # Normalise paths before comparing so /api/pp/v1/... == /pp/v1/...
            existing_keys = {
                f"{m.http_method}:{self._norm_path(m.path)}"
                for v in services.values()
                for m in v
            }
            new_methods = [
                m for m in methods
                if f"{m.http_method}:{self._norm_path(m.path)}" not in existing_keys
            ]
            if new_methods:
                services.setdefault(svc, []).extend(new_methods)

        if not services:
            self.logger.error("Alfa-Bank: no data extracted")
            return None

        snap = self._make_snapshot(services)
        self.logger.info("Alfa-Bank: %d services, %d methods", snap.total_services, snap.total_methods)
        return snap

    # ─── Build hash extraction ────────────────────────────────────────────

    def _get_build_hash_via_requests(self) -> Optional[str]:
        """
        Extract Next.js buildId from page HTML.
        The release-notes page is large (1MB) so try cheaper URLs first.
        The buildId appears in:
          - "buildId":"..." in __NEXT_DATA__ JSON or anywhere in HTML
          - /_next/static/{buildId}/ in script src attributes
        """
        # Try cheap URLs first, then release-notes (large but reliable)
        for url, timeout in [(DOC_START, 20), (PORTAL_BASE, 15), (RELEASE_NOTES_URL, 40)]:
            try:
                resp = self.session.get(url, timeout=timeout)
                if resp.status_code != 200:
                    continue
                html = resp.text

                # Pattern 1: "buildId":"..." anywhere in HTML
                m = re.search(r'"buildId"\s*:\s*"([^"]{10,})"', html)
                if m:
                    return m.group(1)

                # Pattern 2: /_next/static/{buildId}/ in script sources
                for candidate in re.findall(r'/_next/static/([^/"]{10,}?)/', html):
                    if candidate not in ("chunks", "css", "media", "images"):
                        return candidate

                # Pattern 3: __NEXT_DATA__ script tag (Pages Router)
                m = re.search(
                    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>\s*(\{.+?\})\s*</script>',
                    html, re.DOTALL,
                )
                if m:
                    try:
                        nd = json.loads(m.group(1))
                        if nd.get("buildId"):
                            return nd["buildId"]
                    except Exception:
                        pass

            except Exception as exc:
                self.logger.debug("S0 attempt failed for %s: %s", url, exc)

        return None

    # ─── Playwright XHR capture ───────────────────────────────────────────

    def _run_playwright_capture(self):
        """
        Use Playwright to:
        1. Extract buildId from window.__NEXT_DATA__ (always present on SSG pages)
        2. Extract productInfoData.articles from pageProps for article tree
        3. Capture _next/data response URLs (as fallback for build hash)
        """
        self.logger.info("[Alfa S1] Playwright: extracting __NEXT_DATA__")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error("playwright not installed")
            return

        captured_urls: list = []

        def handle_response(response):
            try:
                url = response.url
                if "_next/data" in url and ".json" in url:
                    captured_urls.append(url)
            except Exception:
                pass

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    locale="ru-RU",
                )
                page = ctx.new_page()
                page.on("response", handle_response)

                try:
                    page.goto(DOC_START, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
                    page.wait_for_timeout(CONTENT_WAIT_MS)
                except Exception as exc:
                    self.logger.warning("[Alfa S1] Navigation error: %s", exc)

                # Primary: extract __NEXT_DATA__ (always present on SSG pages)
                try:
                    next_data_raw = page.evaluate("JSON.stringify(window.__NEXT_DATA__ || null)")
                    if next_data_raw and next_data_raw != "null":
                        next_data = json.loads(next_data_raw)
                        build_id = next_data.get("buildId")
                        if build_id:
                            self._build_hash = build_id
                            self.logger.info("[Alfa S1] buildId from __NEXT_DATA__: %s", build_id)

                        # Get article tree from pageProps if available
                        pp = next_data.get("props", {}).get("pageProps", {})
                        if "productInfoData" in pp:
                            # Wrap in the expected index.json structure
                            self._index_data = {"pageProps": pp}
                            self.logger.info("[Alfa S1] Got productInfoData from __NEXT_DATA__")
                except Exception as exc:
                    self.logger.warning("[Alfa S1] __NEXT_DATA__ extract error: %s", exc)

                browser.close()
        except Exception as exc:
            self.logger.error("[Alfa S1] Playwright error: %s", exc)
            return

        # Fallback: extract build hash from captured URL strings
        if not self._build_hash:
            for url in captured_urls:
                m = re.search(r"/_next/data/([^/]{10,})/", url)
                if m:
                    self._build_hash = m.group(1)
                    self.logger.info("[Alfa S1] Build hash from XHR URL: %s", self._build_hash)
                    break

        self.logger.debug("[Alfa S1] Captured %d _next/data URLs", len(captured_urls))

    # ─── Article scan (primary) ───────────────────────────────────────────

    def _strategy_article_scan(self) -> dict:
        if not self._index_data:
            self.logger.warning("[Alfa article] No index data — skipping article scan")
            return {}

        articles = (
            self._index_data.get("pageProps", {})
                            .get("productInfoData", {})
                            .get("articles", [])
        )
        if not articles:
            return {}

        leaves = self._collect_leaf_articles(articles)
        self.logger.info("[Alfa article] %d leaf articles to scan", len(leaves))

        services: dict = {}
        seen: set = set()
        now = datetime.utcnow().isoformat()
        errors = 0

        for leaf in leaves:
            if any(ign in leaf["title"].lower() for ign in IGNORED_ARTICLES):
                continue
            if not leaf["path"]:
                continue

            portal_path = f"/products/alfa-api/documentation/{leaf['path']}"
            pp = self._fetch_article_page(portal_path)

            if not pp:
                errors += 1
                continue

            endpoints = self._endpoints_from_page_props(pp)

            for ep in endpoints:
                # Normalise path so /api/... and /... are treated as the same key
                norm_key = f"{ep['method']}:{self._norm_path(ep['path'])}"
                if norm_key in seen:
                    continue
                seen.add(norm_key)

                svc = leaf["service"]
                services.setdefault(svc, []).append(APIMethod(
                    bank=self.bank_name,
                    service_name=svc,
                    http_method=ep["method"],
                    path=ep["path"],
                    summary=leaf["title"],
                    description="",
                    response_200_fields=ep.get("fields", []),
                    parsed_at=now,
                    url_on_portal=f"{PORTAL_BASE}{portal_path}",
                    request_example=ep.get("request_example", {}),
                    response_example=ep.get("response_example", {}),
                ))

            time.sleep(0.25)

        self.logger.info(
            "[Alfa article] Done: %d services, %d methods, %d errors",
            len(services), len(seen), errors,
        )
        return services

    def _collect_leaf_articles(self, items: list, service_name: str = "") -> list:
        """Recursively collect leaf articles.

        Service name = the IMMEDIATE parent folder of a leaf article.
        Parent categories (folders-of-folders like "Карты ФЛ") are skipped as
        service names — only the folder that directly holds method articles
        becomes a service (e.g. "Выпуск дебетовых карт", "Работа с картами").

        Fix: always pass the CURRENT node's title to children, so
        "Карты ФЛ" → "Выпуск дебетовых карт" → leaf, not
        "Карты ФЛ" → "Карты ФЛ" → leaf.
        """
        leaves = []
        for item in items:
            title = item.get("title", "")
            children = item.get("articles", [])
            path = item.get("path", "").replace(".md", "")

            if children:
                # Always reset service_name to the current node's title.
                # This ensures we use the DIRECT parent, not a grandparent.
                leaves.extend(self._collect_leaf_articles(children, title))
            elif path:
                leaves.append({
                    "service": service_name or title,
                    "title": title,
                    "path": path,
                })
        return leaves

    def _fetch_article_page(self, portal_path: str, depth: int = 0) -> dict:
        """Fetch article page props via _next/data, following redirects."""
        if depth > 3 or not self._build_hash:
            return {}

        segments = portal_path.strip("/").split("/")
        doc_segments = segments[3:]  # after products/alfa-api/documentation
        params = "productName=alfa-api&" + "&".join(f"documentName={s}" for s in doc_segments)
        url = f"{PORTAL_BASE}/_next/data/{self._build_hash}{portal_path}.json?{params}"

        try:
            resp = self.session.get(url, timeout=15)
            if resp.status_code != 200:
                return {}
            data = resp.json()
            pp = data.get("pageProps", {})

            if "__N_REDIRECT" in pp:
                return self._fetch_article_page(pp["__N_REDIRECT"], depth + 1)

            return pp
        except Exception as exc:
            self.logger.debug("Article fetch error for %s: %s", portal_path, exc)
            return {}

    # ─── Path helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _norm_path(path: str) -> str:
        """Normalise path for deduplication.

        The article scan gives '/api/pp/v1/...' (full production URL path).
        The release-notes supplement extracts '/pp/v1/...' (no /api prefix).
        Strip the /api prefix so both hash to the same key.
        """
        return re.sub(r"^/api(?=/)", "", path)

    # ─── Endpoint + field extraction ──────────────────────────────────────────

    def _operation_from_embedded_spec(self, spec: dict, path: str, method: str) -> dict:
        """Find the operation object in the embedded OpenAPI spec.
        Handles path mismatch: production URL may start with /api/ while spec uses /.
        """
        paths = spec.get("paths", {})
        path_item = paths.get(path)
        if not path_item:
            stripped = re.sub(r"^/api(?=/)", "", path)
            path_item = paths.get(stripped)
        if not path_item:
            for sp, item in paths.items():
                if path.endswith(sp) or sp.endswith(path.lstrip("/")):
                    path_item = item
                    break
        if not path_item or not isinstance(path_item, dict):
            return {}
        return path_item.get(method.lower(), {})

    def _endpoints_from_page_props(self, pp: dict) -> list:
        """Extract {method, path, fields, request_example, response_example}.

        Each Alfa-Bank article's YAML frontmatter contains:
          endpoint:
            - method: POST
              production: 'https://baas.alfabank.ru/api/pp/v1/debit-cards/forms'
          openApi:            ← full OpenAPI 3.x spec with schemas and examples
            paths:
              /pp/v1/debit-cards/forms:
                post:
                  requestBody: ...
                  responses:  ...
        """
        results = []

        md_string = pp.get("mdString", "")
        if md_string:
            fm_match = re.match(r'^---\s*\n(.*?)\n---', md_string, re.DOTALL)
            if fm_match:
                try:
                    fm = yaml.safe_load(fm_match.group(1))
                    if isinstance(fm, dict):
                        open_api_spec = fm.get("openApi", {}) or {}
                        for ep in fm.get("endpoint", []):
                            method = str(ep.get("method", "")).upper()
                            production = str(ep.get("production", ""))
                            if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and production:
                                path = urlparse(production).path
                                if path:
                                    fields: list = []
                                    req_ex: dict = {}
                                    resp_ex: dict = {}
                                    if open_api_spec:
                                        op = self._operation_from_embedded_spec(
                                            open_api_spec, path, method
                                        )
                                        if op:
                                            fields = self._extract_fields_for_method(
                                                method, op, open_api_spec
                                            )[:50]
                                            if method in ("POST", "PUT", "PATCH"):
                                                req_ex = self._extract_request_example(
                                                    op, open_api_spec
                                                )
                                            resp_ex = self._extract_response_example(
                                                op, open_api_spec
                                            )
                                    results.append({
                                        "method": method,
                                        "path": path,
                                        "fields": fields,
                                        "request_example": req_ex,
                                        "response_example": resp_ex,
                                    })
                except Exception:
                    pass

            if not results:
                # Fallback: regex scan of frontmatter text
                fm_re = re.search(r'^---\s*\n(.*?)\n---', md_string, re.DOTALL)
                if fm_re:
                    fm_text = fm_re.group(1)
                    methods = re.findall(r'method:\s*([A-Z]+)', fm_text, re.I)
                    prods = re.findall(
                        r"production:\s*['\"]?(https://[^\s'\"]+)['\"]?", fm_text, re.I
                    )
                    for i, method in enumerate(methods):
                        if i < len(prods) and method.upper() in {
                            "GET", "POST", "PUT", "PATCH", "DELETE"
                        }:
                            path = urlparse(prods[i]).path
                            if path:
                                results.append({
                                    "method": method.upper(),
                                    "path": path,
                                    "fields": [],
                                })

        return results

    # ─── Release notes supplement ─────────────────────────────────────────

    def _strategy_release_notes_supplement(self) -> dict:
        """Fetch release-notes.json to get recently-added methods."""
        if not self._build_hash:
            return {}

        self.logger.info("[Alfa RN] Fetching release-notes supplement")
        data = self._fetch_json(
            f"{PORTAL_BASE}/_next/data/{self._build_hash}/release-notes.json"
        )
        if not data:
            return {}

        services: dict = {}
        seen: set = set()
        now = datetime.utcnow().isoformat()

        changes = data.get("pageProps", {}).get("content", {}).get("changes", [])
        for change in changes:
            for update in change.get("updates", []):
                tags = update.get("tags") or []
                content = update.get("content", "")
                if not content:
                    continue
                svc = ", ".join(tags) if tags else "API"
                if any(ign in svc.lower() for ign in IGNORED_ARTICLES):
                    continue

                for match in RN_METHOD_RE.finditer(content):
                    verb = match.group(1).upper()
                    path = match.group(2)
                    desc = (match.group(3) or "").strip()
                    # Use normalised path as key to match article-scan dedup
                    key = f"{verb}:{self._norm_path(path)}"
                    if key in seen:
                        continue
                    seen.add(key)
                    portal_url = self._portal_url_from_content(content)
                    services.setdefault(svc, []).append(APIMethod(
                        bank=self.bank_name,
                        service_name=svc,
                        http_method=verb,
                        path=path,
                        summary=desc or f"{verb} {path}",
                        description=desc,
                        response_200_fields=[],
                        parsed_at=now,
                        url_on_portal=portal_url,
                    ))

        self.logger.info("[Alfa RN] %d services, %d methods", len(services), len(seen))
        return services

    def _portal_url_from_content(self, content: str) -> str:
        m = re.search(r'\[([^\]]+)\]\((/products/[^)]+)\)', content)
        if m:
            return f"{PORTAL_BASE}{m.group(2)}"
        return RELEASE_NOTES_URL

    # ─── DOM fallback ─────────────────────────────────────────────────────

    def _dom_fallback(self) -> Optional[ParseSnapshot]:
        self.logger.info("[Alfa DOM] Fallback: page text scan")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        services: dict = {}
        seen: set = set()
        now = datetime.utcnow().isoformat()
        text_pattern = re.compile(
            r"\b(GET|POST|PUT|PATCH|DELETE)\b\s+(/[A-Za-z0-9_/\-\{\}\.]{4,80})",
            re.I,
        )

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_context().new_page()
                for url in [RELEASE_NOTES_URL, DOC_START]:
                    try:
                        page.goto(url, timeout=PLAYWRIGHT_TIMEOUT, wait_until="domcontentloaded")
                        page.wait_for_timeout(5000)
                        text = page.inner_text("body") or ""
                        for verb, path in text_pattern.findall(text):
                            key = f"{verb.upper()}:{path}"
                            if key in seen:
                                continue
                            seen.add(key)
                            svc = path.strip("/").split("/")[1].title() if "/" in path else "API"
                            services.setdefault(svc, []).append(APIMethod(
                                bank=self.bank_name,
                                service_name=svc,
                                http_method=verb.upper(),
                                path=path,
                                summary=f"{verb.upper()} {path}",
                                description="",
                                response_200_fields=[],
                                parsed_at=now,
                                url_on_portal=url,
                            ))
                    except Exception:
                        pass
                browser.close()
        except Exception as exc:
            self.logger.error("DOM fallback error: %s", exc)

        if not services:
            return None
        snap = self._make_snapshot(services)
        self.logger.info("Alfa-Bank DOM fallback: %d services, %d methods", snap.total_services, snap.total_methods)
        return snap

    # ─── Utilities ────────────────────────────────────────────────────────

    def _fetch_json(self, url: str) -> Optional[dict]:
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            self.logger.debug("fetch_json failed for %s: %s", url, exc)
            return None
