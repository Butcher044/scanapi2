"""Tochka parser.

The dev portal (developers.tochka.com) has 4 independent products, each with its
own OpenAPI spec, sidebar and URL prefix. `service_name` is prefixed with the
product name so the dashboard never shows two unrelated "Заказы" or "Платежи".

  - "Точка Банк"        enter.tochka.com/doc/openapi/swagger.json
  - "Приём платежей"    api.tochka.com/static/v1/pay-gateway/docs/tochka-pay-gateway.json
  - "Безопасные сделки" enter.tochka.com/doc/medusa/swagger.json
  - "Номинальный счёт"  no public spec — the 4th product (cyclops) never got an
                         OpenAPI file; each method's schema is compressed
                         (base64+zlib) inside that method's page bundle
                         (Docusaurus per-route JS chunk). See _parse_cyclops.

Portal links follow the sitemap scheme confirmed for all 3 spec-backed products:
<product base>/api/<kebab(operationId)>.
"""
import base64
import copy
import json
import re
import zlib
from datetime import datetime, timezone

import requests

from .base_parser import APIMethod, BaseParser, ParserError, ParseSnapshot

BANK_SPEC_URL = "https://enter.tochka.com/doc/openapi/swagger.json"
BANK_PORTAL_BASE = "https://developers.tochka.com/docs/tochka-api/api"
BANK_PREFIX = "Точка Банк"

PAY_GATEWAY_SPEC_URL = "https://api.tochka.com/static/v1/pay-gateway/docs/tochka-pay-gateway.json"
PAY_GATEWAY_PORTAL_BASE = "https://developers.tochka.com/docs/pay-gateway/api"
PAY_GATEWAY_PREFIX = "Приём платежей"

MEDUSA_SPEC_URL = "https://enter.tochka.com/doc/medusa/swagger.json"
MEDUSA_PORTAL_BASE = "https://developers.tochka.com/docs/medusa/api"
MEDUSA_PREFIX = "Безопасные сделки"

CYCLOPS_PREFIX = "Номинальный счёт"
CYCLOPS_PORTAL_BASE = "https://developers.tochka.com/docs/cyclops/api"
CYCLOPS_SITE_ROOT = "https://developers.tochka.com"
# Имена бандлов содержат хэш сборки и меняются при каждом деплое портала (старый
# файл после этого отдаёт 404), поэтому их берём из <script src=...> главной страницы.
CYCLOPS_ENTRY_URL = f"{CYCLOPS_SITE_ROOT}/"
# Только пути самого портала; атрибут в минифицированном HTML бывает и без кавычек.
_BUNDLE_SRC_RE = r'<script[^>]*\ssrc=["\']?(/assets/js/{name}\.[0-9a-f]+\.js)["\'\s>]'
_CYCLOPS_RUNTIME_SRC_RE = re.compile(_BUNDLE_SRC_RE.format(name=r"runtime~main"))
_CYCLOPS_MAIN_SRC_RE = re.compile(_BUNDLE_SRC_RE.format(name=r"main"))

# Потолки на чужой контент: бандлы портала — это сотни килобайт, а операция в чанке —
# единицы килобайт. Всё, что заметно больше, означает не «портал вырос», а что читать
# это до конца нельзя: иначе один ответ (или одна zip-бомба) съедает память процесса.
MAX_REMOTE_BYTES = 16 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 4 * 1024 * 1024

_OPENAPI_VERBS = {"get", "post", "put", "patch", "delete"}

# Matches the route registry entry Docusaurus's main bundle embeds for every
# doc page, e.g.:
#   "/docs/cyclops/api/echo-v-3-26f":{"__comp":"4c5e977b","content":"e57c48f7"}
_CYCLOPS_ROUTE_RE = re.compile(
    r'"(/docs/cyclops/api/([a-z0-9-]+))-[0-9a-f]{3}":'
    r'\{"__comp":"[0-9a-f]+","content":"([0-9a-f]+)"'
)


class TochkaParser(BaseParser):
    def __init__(self):
        super().__init__("tochka")

    def parse(self) -> ParseSnapshot:
        self.logger.info("Starting Tochka parser (4 products: bank API, pay-gateway, medusa, cyclops)")

        services: dict = {}
        for spec_url, portal_base, prefix in (
            (BANK_SPEC_URL, BANK_PORTAL_BASE, BANK_PREFIX),
            (PAY_GATEWAY_SPEC_URL, PAY_GATEWAY_PORTAL_BASE, PAY_GATEWAY_PREFIX),
            (MEDUSA_SPEC_URL, MEDUSA_PORTAL_BASE, MEDUSA_PREFIX),
        ):
            self._merge(services, self._parse_product(spec_url, portal_base, prefix))

        self._merge(services, self._parse_cyclops())

        snapshot = self._make_snapshot(services)
        self.logger.info("Tochka: %d services, %d methods", snapshot.total_services, snapshot.total_methods)
        return snapshot

    # ─── The 3 products with a real OpenAPI spec ──────────────────────────

    def _parse_product(self, spec_url: str, portal_base: str, prefix: str) -> dict:
        spec = self._fetch_spec(spec_url)
        spec = self._prefix_tags(spec, prefix)
        return self._parse_openapi_spec(spec, portal_base, spec_url=spec_url)

    @staticmethod
    def _prefix_tags(spec: dict, prefix: str) -> dict:
        """Prefix every operation's tags with the product name, so e.g. Medusa's
        "Заказы" and any future product's own "Заказы" cannot collide into one
        service on the dashboard."""
        spec = copy.deepcopy(spec)
        for path_item in spec.get("paths", {}).values():
            if not isinstance(path_item, dict):
                continue
            for verb, operation in path_item.items():
                if verb not in _OPENAPI_VERBS or not isinstance(operation, dict):
                    continue
                tags = operation.get("tags") or ["Без тега"]
                operation["tags"] = [f"{prefix}. {tag}" for tag in tags]
        return spec

    def _portal_url(self, portal_base_url: str, tag: str, op_id: str) -> str:
        if not op_id:
            return portal_base_url
        return f"{portal_base_url}/{self._kebab(op_id)}"

    @staticmethod
    def _kebab(op_id: str) -> str:
        """operationId -> the slug the portal uses for the page, e.g.
        "get_payment_operation_list_acquiring_v1_0_payments_get" ->
        "get-payment-operation-list-acquiring-v-1-0-payments-get". Verified
        against developers.tochka.com/sitemap.xml for all 3 spec-backed products
        (snake_case with digits, camelCase, and PascalCase-acronym operationIds)."""
        words = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", op_id)
        return "-".join(w.lower() for w in words) if words else op_id.lower()

    @staticmethod
    def _merge(into: dict, extra: dict) -> None:
        for svc, methods in extra.items():
            into.setdefault(svc, []).extend(methods)

    # ─── Nominal account (cyclops): no spec, scraped from page bundles ────

    def _parse_cyclops(self) -> dict:
        """The nominal-account product has no OpenAPI file. Docusaurus still
        compiles a full operation object (operationId, tags, method, path,
        parameters, requestBody, responses — the same shape `_parse_openapi_spec`
        consumes) for each method page; it just ships it compressed inside that
        page's own JS chunk instead of a public spec.

        This walks the same webpack chunk-naming scheme the browser uses to load
        that chunk lazily on navigation: main.js lists, for every /docs/cyclops/
        api/<slug> route, a content hash; runtime.js maps chunk id -> filename.
        Any break in that chain (webpack internals are not a stable API) raises
        ParserError instead of silently producing a partial or wrong snapshot.
        """
        runtime_url, main_url = self._cyclops_bundle_urls()
        name_to_chunk_hash = self._cyclops_chunk_hash_map(runtime_url)
        pages = self._cyclops_pages(main_url, name_to_chunk_hash)

        if not pages:
            raise ParserError("cyclops (nominal account): no method pages found in main.js")

        services: dict = {}
        skipped_as_category_page = 0
        now = self._now()
        for slug, operation in pages:
            if operation is None:
                skipped_as_category_page += 1
                continue
            method = (operation.get("method") or "").upper()
            path = operation.get("path") or ""
            if not method or not path:
                self.logger.warning(
                    "[Tochka cyclops] %s decoded without method/path — dropped", slug
                )
                continue
            tags = operation.get("tags") or ["Без тега"]
            fields = self._extract_fields_for_method(method, operation, operation)
            req_ex = (
                self._extract_request_example(operation, operation)
                if method in ("POST", "PUT", "PATCH") else {}
            )
            resp_ex = self._extract_response_example(operation, operation)
            for tag in tags:
                services.setdefault(f"{CYCLOPS_PREFIX}. {tag}", []).append(APIMethod(
                    bank=self.bank_name,
                    service_name=f"{CYCLOPS_PREFIX}. {tag}",
                    http_method=method,
                    path=path,
                    summary=operation.get("description", ""),
                    description=operation.get("description", ""),
                    response_200_fields=fields,
                    parsed_at=now,
                    url_on_portal=f"{CYCLOPS_PORTAL_BASE}/{slug}",
                    request_example=req_ex,
                    response_example=resp_ex,
                ))

        total = sum(len(v) for v in services.values())
        self.logger.info(
            "[Tochka cyclops] %d services, %d methods (%d category pages skipped)",
            len(services), total, skipped_as_category_page,
        )
        if total == 0:
            raise ParserError("cyclops (nominal account): 0 methods decoded — scraping is unreliable")
        return services

    def _cyclops_bundle_urls(self) -> tuple[str, str]:
        """(runtime_url, main_url) текущей сборки портала — те же файлы, что
        грузит браузер с главной страницы."""
        html = self._get_text(CYCLOPS_ENTRY_URL)
        urls = []
        for label, pattern in (("runtime~main", _CYCLOPS_RUNTIME_SRC_RE), ("main", _CYCLOPS_MAIN_SRC_RE)):
            m = pattern.search(html)
            if not m:
                raise ParserError(f"cyclops: {label} bundle not found in {CYCLOPS_ENTRY_URL}")
            urls.append(f"{CYCLOPS_SITE_ROOT}{m.group(1)}")
        return urls[0], urls[1]

    def _cyclops_chunk_hash_map(self, runtime_url: str) -> dict:
        """content-hash -> filename, derived from webpack's runtime chunk loader
        (`__webpack_require__.u`): two lookup objects, "name" and "content hash",
        keyed by numeric chunk id. For per-page doc chunks the "name" the portal's
        build assigns is exactly the content hash already known from main.js, so
        the caller only needs this reverse map (content hash -> filename)."""
        runtime_js = self._get_text(runtime_url)
        start = runtime_js.find("n.u=e=>")
        if start == -1:
            raise ParserError("cyclops: webpack chunk loader (n.u) not found in runtime bundle")
        segment = runtime_js[start:start + 20000]

        name_prefix = 'n.u=e=>"assets/js/"+(('
        mid_marker = ')[e]||e)+"."+('
        end_marker = ')[e]+".js"'
        mid = segment.find(mid_marker)
        end = segment.find(end_marker, mid if mid != -1 else 0)
        if not segment.startswith(name_prefix) or mid == -1 or end == -1:
            raise ParserError("cyclops: webpack chunk loader has an unexpected shape")

        name_obj_text = segment[len(name_prefix):mid]
        hash_obj_text = segment[mid + len(mid_marker):end]
        name_map = dict(re.findall(r'(\d+):"([0-9a-zA-Z]+)"', name_obj_text))
        hash_map = dict(re.findall(r'(\d+):"([0-9a-zA-Z]+)"', hash_obj_text))
        if not name_map or not hash_map:
            raise ParserError("cyclops: webpack chunk id maps are empty")

        chunk_id_by_name = {name: chunk_id for chunk_id, name in name_map.items()}
        return {
            content_hash: f"assets/js/{content_hash}.{hash_map[chunk_id]}.js"
            for content_hash, chunk_id in chunk_id_by_name.items()
            if chunk_id in hash_map
        }

    def _cyclops_pages(self, main_url: str, chunk_filename_by_content_hash: dict) -> list:
        """[(slug, operation_dict_or_None)] for every /docs/cyclops/api/<slug>
        route found in main.js. `None` marks a page with no "api" field — a
        sidebar category landing page, not a method (kept out of the count, not
        treated as an error)."""
        main_js = self._get_text(main_url)
        matches = _CYCLOPS_ROUTE_RE.findall(main_js)
        results = []
        for _full_path, slug, content_hash in matches:
            filename = chunk_filename_by_content_hash.get(content_hash)
            if not filename:
                self.logger.warning("[Tochka cyclops] no chunk file for %s (content %s)", slug, content_hash)
                results.append((slug, None))
                continue
            chunk_js = self._get_text(f"{CYCLOPS_SITE_ROOT}/{filename}")
            m = re.search(r'"api":"([^"]+)"', chunk_js)
            if not m:
                # Не отличимо от страницы-раздела, поэтому не ошибка — но обязано быть
                # видно в логе: иначе пропавший метод исчезнет без единого следа.
                self.logger.warning("[Tochka cyclops] no 'api' field in the chunk of %s", slug)
                results.append((slug, None))
                continue
            results.append((slug, self._decode_api_payload(slug, m.group(1))))
        return results

    @staticmethod
    def _decode_api_payload(slug: str, payload: str) -> dict:
        """Распаковка с потолком: содержимое приходит с чужого сайта, а маленький
        base64-блоб разворачивается в сколько угодно гигабайт."""
        try:
            raw = base64.b64decode(payload)
            unpacker = zlib.decompressobj()
            data = unpacker.decompress(raw, MAX_DECOMPRESSED_BYTES)
            if not unpacker.eof:
                raise ParserError(
                    f"cyclops: {slug} 'api' payload unpacks to more than "
                    f"{MAX_DECOMPRESSED_BYTES} bytes — refusing to decompress it"
                )
            return json.loads(data)
        except (ValueError, zlib.error) as exc:
            raise ParserError(f"cyclops: {slug} 'api' payload is not valid compressed JSON: {exc}") from exc

    def _get_text(self, url: str) -> str:
        """Чтение потоком с потолком: ответ портала не должен целиком оседать
        в памяти процесса, каким бы большим его ни сделали."""
        try:
            resp = self._guarded_get(self.session, url, timeout=30)
            resp.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in resp.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_REMOTE_BYTES:
                    raise ParserError(
                        f"cyclops: {url} is too large (over {MAX_REMOTE_BYTES} bytes)"
                    )
                chunks.append(chunk)
        except requests.RequestException as exc:
            raise ParserError(f"cyclops: failed to download {url}: {exc}") from exc
        return b"".join(chunks).decode(self._charset_of(resp), errors="replace")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
