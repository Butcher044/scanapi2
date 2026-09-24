"""
Alfa-Bank parser.

  1. requests → Next.js buildId from page HTML
  2. _next/data/{buildId}/index.json → article tree
  3. every leaf article (fetched in parallel) → YAML frontmatter: endpoint + embedded openApi
  4. release-notes.json → methods announced but not (yet) described in articles

A partial scan is an error: a snapshot with missing articles would produce
false "removed" changes on this run and false "added" changes on the next one.
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
import yaml

from .base_parser import (
    HIDDEN_REASON_GHOST,
    HIDDEN_REASON_PRIVATE,
    HIDDEN_REASON_SUPERSEDED,
    MAX_RESPONSE_BYTES,
    APIMethod,
    BaseParser,
    ParserError,
    ParseSnapshot,
)

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

HTTP_VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

ARTICLE_WORKERS = 8
RETRY_WORKERS = 2
ARTICLE_TIMEOUT = 30  # article payloads reach ~1 MB (embedded OpenAPI spec)
MAX_REDIRECTS = 3
_CHUNK_BYTES = 64 * 1024  # matches BaseParser._get_capped_text's chunk size

# Alfa-Bank WAF blocks a full Chrome UA (returns a 6 KB JS challenge);
# a short UA without the "Chrome/x Safari/x" suffix gets the real SSR HTML.
ALFA_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

# Pattern for Release Notes method lines: "* POST /path - Description"
RN_METHOD_RE = re.compile(
    r"^\*\s+(GET|POST|PUT|PATCH|DELETE)\s+(/[A-Za-z0-9_/\-\{\}\.\*]+)"
    r"(?:\s*[-–—]\s*(.+))?",
    re.MULTILINE | re.I,
)
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


class AlfaBankParser(BaseParser):
    def __init__(self):
        super().__init__("alfabank")
        self._build_hash: Optional[str] = None
        self._index_data: Optional[dict] = None
        self._local = threading.local()

    def _create_session(self) -> requests.Session:
        session = super()._create_session()
        session.headers["User-Agent"] = ALFA_USER_AGENT
        return session

    def _thread_session(self) -> requests.Session:
        """requests.Session is not thread-safe — one per worker thread."""
        if not hasattr(self._local, "session"):
            self._local.session = self._create_session()
        return self._local.session

    def parse(self) -> ParseSnapshot:
        self.logger.info("Starting Alfa-Bank parser (article scan + release notes)")

        self._build_hash = self._get_build_hash_via_requests()
        if not self._build_hash:
            raise ParserError("Next.js buildId not found on developers.alfabank.ru")
        self.logger.info("[Alfa] buildId: %s", self._build_hash)

        self._index_data = self._fetch_json(
            f"{PORTAL_BASE}/_next/data/{self._build_hash}/index.json?productName=alfa-api"
        )
        if not self._index_data:
            raise ParserError("article index (index.json) is unavailable")

        services = self._strategy_article_scan()
        if not services:
            raise ParserError("article scan returned no methods")

        merged = self._merge_release_notes(services, self._strategy_release_notes_supplement())
        snap = self._make_snapshot(merged)
        self.logger.info("Alfa-Bank: %d services, %d methods", snap.total_services, snap.total_methods)
        return snap

    def _merge_release_notes(self, services: dict, rn_services: dict) -> dict:
        """Add release-notes methods that the article scan did not find."""
        seen = {
            self._method_key(m.http_method, m.path)
            for methods in services.values() for m in methods
        }
        merged = dict(services)
        added = 0
        for svc, methods in rn_services.items():
            new_methods = [
                m for m in methods
                if self._method_key(m.http_method, m.path) not in seen
            ]
            if new_methods:
                merged[svc] = [*merged.get(svc, []), *new_methods]
                added += len(new_methods)
        self.logger.info("[Alfa RN] %d methods added from release notes", added)
        return merged

    # ─── Build hash extraction ────────────────────────────────────────────

    def _get_build_hash_via_requests(self) -> Optional[str]:
        """
        Extract Next.js buildId from page HTML.
        The release-notes page is large (1MB) so try cheaper URLs first.
        The buildId appears in:
          - "buildId":"..." in __NEXT_DATA__ JSON or anywhere in HTML
          - /_next/static/{buildId}/ in script src attributes
        """
        for url, timeout in [(DOC_START, 20), (PORTAL_BASE, 15), (RELEASE_NOTES_URL, 40)]:
            try:
                html_text = self._get_capped_text(url, timeout=timeout)
            except (requests.RequestException, ParserError) as exc:
                self.logger.warning("buildId lookup failed for %s: %s", url, exc)
                continue
            build_id = self._build_id_from_html(html_text)
            if build_id:
                return build_id
        return None

    @staticmethod
    def _build_id_from_html(html: str) -> Optional[str]:
        m = re.search(r'"buildId"\s*:\s*"([^"]{10,})"', html)
        if m:
            return m.group(1)

        for candidate in re.findall(r'/_next/static/([^/"]{10,}?)/', html):
            if candidate not in ("chunks", "css", "media", "images"):
                return candidate

        m = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>\s*(\{.+?\})\s*</script>',
            html, re.DOTALL,
        )
        if m:
            try:
                return json.loads(m.group(1)).get("buildId") or None
            except ValueError:
                return None
        return None

    # ─── Article scan ─────────────────────────────────────────────────────

    def _strategy_article_scan(self) -> dict:
        articles = (
            self._index_data.get("pageProps", {})
                            .get("productInfoData", {})
                            .get("articles", [])
        )
        leaves = [
            leaf for leaf in self._collect_leaf_articles(articles)
            if leaf["path"] and not any(ign in leaf["title"].lower() for ign in IGNORED_ARTICLES)
        ]
        self.logger.info("[Alfa article] %d leaf articles to scan", len(leaves))

        endpoints = self._scan_all_articles(leaves)
        services = self._methods_from_endpoints(leaves, endpoints)
        self.logger.info(
            "[Alfa article] Done: %d services, %d methods",
            len(services), sum(len(v) for v in services.values()),
        )
        return services

    def _scan_all_articles(self, leaves: list) -> list:
        """Endpoints of every leaf; one retry pass, then any failure aborts the parse.

        The retry pass is keyed by the leaf's position in `leaves`, not by
        `leaf["path"]`: two different leaves can legitimately share the same
        path (the same article reachable from two places in the tree), and a
        path-keyed map would silently collapse their two results into one.
        """
        results = self._scan_articles(leaves, ARTICLE_WORKERS)
        failed_indices = [i for i, eps in enumerate(results) if eps is None]
        if not failed_indices:
            return results

        self.logger.warning("[Alfa article] retrying %d failed articles", len(failed_indices))
        retried = dict(zip(
            failed_indices,
            self._scan_articles([leaves[i] for i in failed_indices], RETRY_WORKERS),
        ))
        merged = [retried[i] if i in retried else eps for i, eps in enumerate(results)]

        still_failed = [leaves[i]["path"] for i, eps in enumerate(merged) if eps is None]
        if still_failed:
            raise ParserError(
                f"{len(still_failed)} of {len(leaves)} articles could not be fetched "
                f"(e.g. {still_failed[0]}) — partial snapshot rejected"
            )
        return merged

    def _scan_articles(self, leaves: list, workers: int) -> list:
        """Per leaf: its endpoints, or None when the fetch failed.

        Pages (~1 MB each) are reduced to endpoints inside the worker so they
        are not all held in memory at once.
        """
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(self._scan_article, leaves))

    def _scan_article(self, leaf: dict) -> Optional[list]:
        pp = self._fetch_article_page(self._portal_path(leaf))
        if pp is None:
            return None
        try:
            return self._endpoints_from_page_props(pp)
        except ParserError as exc:
            # Frontmatter present but unparsable is treated like a failed
            # fetch: it goes through the same retry-then-abort path as a
            # network failure (see module docstring: "a partial scan is an
            # error"), rather than silently looking like "no endpoints".
            self.logger.warning("Article endpoints unparsable for %s: %s", leaf["path"], exc)
            return None

    def _methods_from_endpoints(self, leaves: list, endpoints: list) -> dict:
        services: dict = {}
        seen: set = set()
        now = datetime.now(timezone.utc).isoformat()
        for leaf, eps in zip(leaves, endpoints):
            portal_url = f"{PORTAL_BASE}{self._portal_path(leaf)}"
            hidden, hidden_reason = self._hidden_status(leaf)
            for ep in eps:
                # Normalise path so /api/... and /... are treated as the same key
                key = self._method_key(ep["method"], ep["path"])
                if key in seen:
                    continue
                seen.add(key)
                svc = leaf["service"]
                services.setdefault(svc, []).append(APIMethod(
                    bank=self.bank_name,
                    service_name=svc,
                    http_method=ep["method"],
                    path=self._norm_path(ep["path"]),
                    summary=leaf["title"],
                    description="",
                    response_200_fields=ep.get("fields", []),
                    parsed_at=now,
                    url_on_portal=portal_url,
                    request_example=ep.get("request_example", {}),
                    response_example=ep.get("response_example", {}),
                    hidden=hidden,
                    hidden_reason=hidden_reason,
                ))
        return services

    @staticmethod
    def _portal_path(leaf: dict) -> str:
        return f"/products/alfa-api/documentation/{leaf['path']}"

    def _collect_leaf_articles(
        self, items: list, service_name: Optional[str] = None,
        parent_title: str = "", private: bool = False,
    ) -> list:
        """Recursively collect leaf articles.

        Service name = the nearest ANCESTOR (not necessarily the immediate
        parent) whose own `tags` include "service" — the portal's own
        catalog-card rule (findings.md Phase 11: "карточка каталога =
        tags.includes('service')"), so names read like the portal
        ("Выписки по счетам ЮЛ") instead of a subheading fragment. Falls back
        to the immediate parent folder's title when no ancestor is tagged at
        all (older/untagged trees), so behaviour degrades gracefully rather
        than collapsing every leaf under one name.

        "private" (closed space of the portal) is inherited down the whole
        subtree from ANY ancestor's own tag, mirroring the portal's own nav
        filter `visible && !tags.includes("private")` — a service-tagged
        folder nested inside a private one (e.g. "Короткая анкета для
        регистрации бизнеса" under "Партнёрская программа...") is still
        private.
        """
        leaves = []
        for item in items:
            title = item.get("title", "")
            children = item.get("articles", [])
            path = item.get("path", "").replace(".md", "")
            tags = item.get("tags") or []
            is_private = private or "private" in tags
            svc = title if "service" in tags else service_name

            if children:
                leaves.extend(self._collect_leaf_articles(children, svc, title, is_private))
            elif path:
                leaves.append({
                    "service": svc or parent_title or title,
                    "title": title,
                    "path": path,
                    "private": is_private,
                    "visible": item.get("visible", True),
                })
        return leaves

    @staticmethod
    def _hidden_status(leaf: dict) -> tuple[bool, Optional[str]]:
        """Why a leaf article's methods are not shown on the public dashboard.

        Checked in this order because the buckets can overlap in the raw
        data (a superseded article can also sit in a private subtree) and
        findings.md's audit attributes each of the 144 extra methods to
        exactly one reason — private space wins first, since it is the
        stronger (portal-wide, not per-article) closure.
        """
        if leaf.get("private"):
            return True, HIDDEN_REASON_PRIVATE
        if leaf.get("visible") is False:
            return True, HIDDEN_REASON_SUPERSEDED
        return False, None

    def _fetch_article_page(self, portal_path: str, depth: int = 0) -> Optional[dict]:
        """Article pageProps via _next/data, following redirects.

        Returns {} for an article listed in the index but not published (404),
        None when the fetch failed and should be retried.
        """
        if depth > MAX_REDIRECTS:
            self.logger.warning("Too many redirects for %s", portal_path)
            return None

        doc_segments = portal_path.strip("/").split("/")[3:]  # after products/alfa-api/documentation
        params = "productName=alfa-api&" + "&".join(f"documentName={s}" for s in doc_segments)
        url = f"{PORTAL_BASE}/_next/data/{self._build_hash}{portal_path}.json?{params}"

        try:
            text = self._capped_text_via(self._thread_session(), url, ARTICLE_TIMEOUT)
            pp = json.loads(text).get("pageProps", {})
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                self.logger.warning("Article not found (404): %s", portal_path)
                return {}
            self.logger.warning("Article fetch failed for %s: %s", portal_path, exc)
            return None
        except (requests.RequestException, ParserError, ValueError) as exc:
            self.logger.warning("Article fetch failed for %s: %s", portal_path, exc)
            return None

        if "__N_REDIRECT" in pp:
            return self._fetch_article_page(pp["__N_REDIRECT"], depth + 1)
        return pp

    # ─── Path helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _norm_path(path: str) -> str:
        """Canonical method path: deduplication key AND the stored path.

        The article scan gives '/api/pp/v1/...' (full production URL path).
        The release-notes supplement extracts '/pp/v1/...' (no /api prefix).
        Stripping /api everywhere keeps the diff key stable when a method moves
        from release notes to a published article.
        """
        return re.sub(r"^/api(?=/)", "", path)

    @staticmethod
    def _method_key(method: str, path: str) -> str:
        """Dedup / lookup key shared by article-scan merging, endpoint
        deduplication, and the release-notes merge -- one canonical form of
        "this HTTP method + path" instead of the same f-string in three places."""
        return f"{method}:{AlfaBankParser._norm_path(path)}"

    # ─── Endpoint + field extraction ──────────────────────────────────────

    def _operation_from_embedded_spec(self, spec: dict, path: str, method: str) -> dict:
        """Find the operation object in the embedded OpenAPI spec.
        Handles path mismatch: production URL may start with /api/ while spec uses /.
        """
        paths = spec.get("paths", {})
        path_item = paths.get(path) or paths.get(self._norm_path(path))
        if not path_item:
            for sp, item in paths.items():
                if path.endswith(sp) or sp.endswith(path.lstrip("/")):
                    path_item = item
                    break
        if not path_item or not isinstance(path_item, dict):
            self.logger.debug("embedded spec has no path entry for %s %s", method, path)
            return {}
        operation = path_item.get(method.lower())
        if operation is None:
            self.logger.debug("embedded spec path %s has no %s operation", path, method)
            return {}
        return operation

    def _endpoints_from_page_props(self, pp: dict) -> list:
        """Extract {method, path, fields, request_example, response_example}.

        Each Alfa-Bank article's YAML frontmatter contains:
          endpoint:
            - method: POST
              production: 'https://baas.alfabank.ru/api/pp/v1/debit-cards/forms'
          openApi:            ← full OpenAPI 3.x spec with schemas and examples

        A page can legitimately have no endpoints (no frontmatter block at
        all, or a frontmatter block whose `endpoint:` is absent/empty — a
        purely descriptive article). That is different from a frontmatter
        block that IS present but that neither the YAML parser nor the regex
        fallback can make sense of: silently returning [] there would turn a
        real, still-published method into a phantom "removed" on this run and
        a phantom "added" on the next (module docstring: "a partial scan is
        an error"), so that case raises instead.
        """
        fm_match = FRONTMATTER_RE.match(pp.get("mdString", "") or "")
        if not fm_match:
            return []  # no frontmatter block at all -- legitimately no endpoints
        fm_text = fm_match.group(1)

        fm = None
        try:
            fm = yaml.safe_load(fm_text)
        except yaml.YAMLError as exc:
            self.logger.warning("Frontmatter YAML is invalid, using regex fallback: %s", exc)

        if isinstance(fm, dict):
            if not fm.get("endpoint"):
                return []  # frontmatter understood fine, article declares no endpoint
            results = self._endpoints_from_frontmatter(fm)
            if results:
                return results

        results = self._endpoints_from_frontmatter_text(fm_text)
        if results:
            return results

        if isinstance(fm, dict):
            # YAML parsed fine; `endpoint:` was present but yielded nothing
            # usable (e.g. entries missing a method/production) -- understood,
            # not a parse failure.
            return []

        raise ParserError(
            "frontmatter present but could not be parsed "
            "(neither YAML nor the regex fallback found any endpoints)"
        )

    def _endpoints_from_frontmatter(self, fm: dict) -> list:
        spec = fm.get("openApi") or {}
        results = []
        for ep in fm.get("endpoint") or []:
            if not isinstance(ep, dict):
                continue
            method = str(ep.get("method", "")).upper()
            path = urlparse(str(ep.get("production", ""))).path
            if method not in HTTP_VERBS or not path:
                continue
            op = self._operation_from_embedded_spec(spec, path, method) if isinstance(spec, dict) else {}
            # spec_url is deliberately NOT passed to the three extractors below.
            # Passing it would let a $ref inside an article's embedded spec
            # resolve into an *external* sibling file (BaseParser._fetch_external_spec)
            # from one of ARTICLE_WORKERS worker threads, through the shared,
            # non-thread-safe `self.session` and the unlocked
            # `self._external_spec_cache` -- a data race. Embedded specs are
            # expected to be self-contained (local "#/..." refs only); see
            # test_article_scan_never_fetches_external_refs.
            results.append({
                "method": method,
                "path": path,
                "fields": self._extract_fields_for_method(method, op, spec) if op else [],
                "request_example": (
                    self._extract_request_example(op, spec)
                    if op and method in ("POST", "PUT", "PATCH") else {}
                ),
                "response_example": self._extract_response_example(op, spec) if op else {},
            })
        return results

    @staticmethod
    def _endpoints_from_frontmatter_text(fm_text: str) -> list:
        """Regex fallback for frontmatter that is not valid YAML."""
        methods = re.findall(r"method:\s*([A-Z]+)", fm_text, re.I)
        prods = re.findall(r"production:\s*['\"]?(https://[^\s'\"]+)['\"]?", fm_text, re.I)
        return [
            {"method": method.upper(), "path": urlparse(prod).path, "fields": []}
            for method, prod in zip(methods, prods)
            if method.upper() in HTTP_VERBS and urlparse(prod).path
        ]

    # ─── Release notes supplement ─────────────────────────────────────────

    def _strategy_release_notes_supplement(self) -> dict:
        """Methods listed in release-notes.json (recent additions)."""
        self.logger.info("[Alfa RN] Fetching release-notes supplement")
        data = self._fetch_json(f"{PORTAL_BASE}/_next/data/{self._build_hash}/release-notes.json")
        if not data:
            # Skipping would make the RN-only methods flap as removed/added between runs
            raise ParserError("release notes (release-notes.json) are unavailable")

        services: dict = {}
        seen: set = set()
        now = datetime.now(timezone.utc).isoformat()

        changes = data.get("pageProps", {}).get("content", {}).get("changes", [])
        for change in changes:
            for update in change.get("updates", []):
                self._collect_rn_update_methods(update, services, seen, now)

        self.logger.info("[Alfa RN] %d services, %d methods", len(services), len(seen))
        return services

    def _collect_rn_update_methods(self, update: dict, services: dict, seen: set, now: str) -> None:
        """Parse one release-notes update block and append any new methods it
        describes to `services`, recording their keys in `seen`. Both are
        shared accumulators across every update in the release-notes feed
        (mirrors the `seen`-set dedup pattern used by `_methods_from_endpoints`),
        so dedup works across, not just within, a single update.
        """
        tags = update.get("tags") or []
        content = update.get("content", "")
        if not content:
            return
        svc = ", ".join(tags) if tags else "API"
        if any(ign in svc.lower() for ign in IGNORED_ARTICLES):
            return

        for match in RN_METHOD_RE.finditer(content):
            verb = match.group(1).upper()
            path = self._norm_path(match.group(2))
            desc = (match.group(3) or "").strip()
            key = self._method_key(verb, path)
            if key in seen:
                continue
            seen.add(key)
            services.setdefault(svc, []).append(APIMethod(
                bank=self.bank_name,
                service_name=svc,
                http_method=verb,
                path=path,
                summary=desc or f"{verb} {path}",
                description=desc,
                response_200_fields=[],
                parsed_at=now,
                url_on_portal=self._portal_url_from_content(content),
                # Release notes announce changes, not necessarily live
                # endpoints — some list dead pre-launch paths (e.g.
                # ESOP's /jp/v1/esop/... vs the real /esop/jp/v1/...).
                # A method only ever seen here (never in a published
                # article) is hidden unconditionally: safer than
                # trying to tell a real early-access method apart
                # from a ghost (findings.md Phase 11).
                hidden=True,
                hidden_reason=HIDDEN_REASON_GHOST,
            ))

    @staticmethod
    def _portal_url_from_content(content: str) -> str:
        m = re.search(r"\[([^\]]+)\]\((/products/[^)]+)\)", content)
        return f"{PORTAL_BASE}{m.group(2)}" if m else RELEASE_NOTES_URL

    # ─── Utilities ────────────────────────────────────────────────────────

    def _fetch_json(self, url: str) -> Optional[dict]:
        """GET and parse a JSON document, size-capped like every other
        download (see BaseParser._get_capped_text)."""
        try:
            text = self._get_capped_text(url, timeout=ARTICLE_TIMEOUT)
            return json.loads(text)
        except (requests.RequestException, ParserError, ValueError) as exc:
            self.logger.warning("fetch_json failed for %s: %s", url, exc)
            return None

    def _capped_text_via(self, session: requests.Session, url: str, timeout: int) -> str:
        """Same size-capped, chunked download as BaseParser._get_capped_text,
        but against an explicitly given session.

        Needed (only) for calls made from worker threads: requests.Session is
        not thread-safe, so a threaded fetch must use `self._thread_session()`,
        not the shared `self.session` that `_get_capped_text` is hard-wired
        to. Kept as one private method so the cap logic is not duplicated at
        each threaded call site. Redirects are followed via
        `BaseParser._guarded_get`, which refuses to leave the original host
        (see its docstring) -- not duplicated here either.
        """
        resp = self._guarded_get(session, url, timeout)
        resp.raise_for_status()
        chunks: list = []
        size = 0
        for chunk in resp.iter_content(_CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ParserError(f"{url}: response is larger than {MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks).decode(self._charset_of(resp), errors="replace")
