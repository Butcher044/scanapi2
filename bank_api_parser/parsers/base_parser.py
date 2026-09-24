from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse
import codecs
import json
import logging
import requests
import yaml
from urllib3.util.retry import Retry

from bank_api_parser import proxy
from bank_api_parser.tls import ca_bundle

# Every response is read in chunks and cut off here. requests transparently
# inflates `Content-Encoding: gzip`, so a few kilobytes on the wire can become
# gigabytes in memory; Alfa alone downloads pages in 8 threads at once.
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_CHUNK_BYTES = 64 * 1024

# HTTP redirect hops followed by hand for a single request before giving up
# (see BaseParser._guarded_get). Kept small: a legitimate spec host needs at
# most one or two hops (e.g. http -> https, or a trailing-slash canonicalize).
_MAX_REDIRECT_HOPS = 5
_REDIRECT_STATUS_CODES = (301, 302, 303, 307, 308)

# Body types that are legitimately bodiless in the UI even when they have a schema.
BINARY_MEDIA_TYPE_PREFIXES = (
    "application/octet-stream",
    "application/pdf",
    "application/zip",
    "image/",
)

# Why a method exists in the bank's source data but not on the public dev portal.
# Such methods are kept and marked, not dropped: the dashboard shows only visible
# ones, an admin sees the rest in the "Скрытые сервисы" tab.
HIDDEN_REASON_PRIVATE = "private"          # closed space of the portal (partner/internal)
HIDDEN_REASON_SUPERSEDED = "superseded"    # older version of an article that has a newer one
HIDDEN_REASON_NOT_IN_MENU = "not_in_menu"  # spec exists, no page in the portal navigation
HIDDEN_REASON_GHOST = "ghost"              # only mentioned in release notes, path is dead

HIDDEN_REASONS = (
    HIDDEN_REASON_PRIVATE,
    HIDDEN_REASON_SUPERSEDED,
    HIDDEN_REASON_NOT_IN_MENU,
    HIDDEN_REASON_GHOST,
)


@dataclass
class APIMethod:
    bank: str
    service_name: str
    http_method: str
    path: str
    summary: str
    description: str
    response_200_fields: list
    parsed_at: str
    url_on_portal: str
    # Actual JSON examples (displayed in UI, monitored for changes).
    # A body can be an object, an array, or (rarely) a bare scalar.
    request_example: dict | list | str | int | float | bool = field(default_factory=dict)
    response_example: dict | list | str | int | float | bool = field(default_factory=dict)
    # Not visible on the dev portal — kept for the admin tab, never on the dashboard.
    hidden: bool = False
    hidden_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "bank": self.bank,
            "service_name": self.service_name,
            "http_method": self.http_method,
            "path": self.path,
            "summary": self.summary,
            "description": self.description,
            "response_200_fields": self.response_200_fields,
            "parsed_at": self.parsed_at,
            "url_on_portal": self.url_on_portal,
            "request_example": self.request_example,
            "response_example": self.response_example,
            "hidden": self.hidden,
            "hidden_reason": self.hidden_reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "APIMethod":
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})


@dataclass
class ParseSnapshot:
    bank: str
    parsed_at: str
    services: dict
    total_services: int
    total_methods: int

    def to_dict(self) -> dict:
        serialized_services = {}
        for svc, methods in self.services.items():
            serialized_services[svc] = [
                m.to_dict() if isinstance(m, APIMethod) else m for m in methods
            ]
        return {
            "bank": self.bank,
            "parsed_at": self.parsed_at,
            "services": serialized_services,
            "total_services": self.total_services,
            "total_methods": self.total_methods,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ParseSnapshot":
        services = {}
        for svc, methods in data.get("services", {}).items():
            services[svc] = [
                APIMethod.from_dict(m) if isinstance(m, dict) else m for m in methods
            ]
        return cls(
            bank=data["bank"],
            parsed_at=data["parsed_at"],
            services=services,
            total_services=data["total_services"],
            total_methods=data["total_methods"],
        )


class ParserError(RuntimeError):
    """The portal could not be parsed; the message explains why."""


class BaseParser(ABC):
    # generated examples stop recursing past this many nested levels (validated against Tochka)
    _MAX_EXAMPLE_DEPTH = 12

    def __init__(self, bank_name: str):
        self.bank_name = bank_name
        self.logger = logging.getLogger(f"parser.{bank_name}")
        self.session = self._create_session()
        # url -> parsed spec (or {} on failure), one fetch per external file per parse
        self._external_spec_cache: dict = {}

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.verify = ca_bundle()
        retry = Retry(
            total=3,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = proxy.make_adapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        return session

    @abstractmethod
    def parse(self) -> ParseSnapshot:
        """Return a snapshot or raise ParserError with the reason."""

    # ── OpenAPI / Swagger helpers ──────────────────────────────────────────

    @staticmethod
    def _charset_of(resp) -> str:
        """Encoding to decode `resp`'s body with.

        `requests` defaults `resp.encoding` to ISO-8859-1 for any `text/*`
        response whose server did not declare a charset (RFC 2616 default) --
        confirmed live against developers.sber.ru, whose pages and specs are
        `text/html` with no charset param. Trusting `resp.encoding` blindly
        therefore mangles every UTF-8 (e.g. Cyrillic) body such a server sends.

        The server-declared charset is used only when `Content-Type` actually
        names one; every other case (no header, no charset param, an unknown
        or garbled charset name, a fake response with no `headers` attribute
        at all) falls back to utf-8. Never raises, never mutates `resp`.
        """
        headers = getattr(resp, "headers", None) or {}
        content_type = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
        for param in content_type.split(";")[1:]:
            key, _, value = param.strip().partition("=")
            if key.lower() != "charset":
                continue
            charset = value.strip().strip('"').strip("'")
            if not charset:
                continue
            try:
                codecs.lookup(charset)
            except LookupError:
                continue
            return charset
        return "utf-8"

    def _guarded_get(
        self, session: requests.Session, url: str, timeout: int, stream: bool = True,
    ) -> requests.Response:
        """GET `url` on `session`, following only same-origin http(s) redirects.

        `requests` follows redirects transparently by default (up to 30 hops)
        and never checks where the chain actually lands. A portal server
        (third-party, possibly compromised) could answer with e.g.
        `302 Location: http://169.254.169.254/...` (cloud metadata) or any
        other internal address, and the response would be parsed and end up
        in `response_example`/`request_example` -- visible on the dashboard
        (SSRF via redirect).

        Redirects are therefore followed by hand: each hop's `Location` is
        resolved (via `urljoin`) against the current URL and checked with
        `_is_same_origin` against the ORIGINAL `url` before the next request
        is made. A cross-origin or non-http(s) target raises ParserError
        naming the rejected address -- before a request to it is ever sent.
        A chain longer than `_MAX_REDIRECT_HOPS` also raises ParserError.
        Takes `session` explicitly (not `self.session`): worker threads use
        their own session, since `requests.Session` is not thread-safe.
        """
        current_url = url
        hops = 0
        while True:
            resp = session.get(current_url, timeout=timeout, stream=stream, allow_redirects=False)
            if resp.status_code not in _REDIRECT_STATUS_CODES:
                return resp
            if hops >= _MAX_REDIRECT_HOPS:
                raise ParserError(f"{url}: more than {_MAX_REDIRECT_HOPS} redirects, giving up")
            location = (getattr(resp, "headers", None) or {}).get("Location")
            if not location:
                return resp
            next_url = urljoin(current_url, location)
            if not self._is_same_origin(next_url, url):
                raise ParserError(
                    f"{url}: refusing to follow redirect to {next_url} (different origin)"
                )
            current_url = next_url
            hops += 1

    def _get_capped_text(
        self, url: str, timeout: int = 30, max_bytes: int = MAX_RESPONSE_BYTES
    ) -> str:
        """GET a text response, reading it in chunks and giving up past `max_bytes`.

        Portals are third-party servers: a broken one (or a compromised CDN)
        can answer with an endlessly inflating body, and `resp.text` would hold
        all of it in memory before anyone could object.
        """
        resp = self._guarded_get(self.session, url, timeout)
        resp.raise_for_status()
        chunks: list = []
        size = 0
        for chunk in resp.iter_content(_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise ParserError(f"{url}: response is larger than {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks).decode(self._charset_of(resp), errors="replace")

    def _fetch_spec(self, url: str, timeout: int = 60) -> dict:
        """Download an OpenAPI spec (JSON or YAML); raise ParserError on any problem."""
        self.logger.info("Downloading spec %s", url)
        try:
            text = self._get_capped_text(url, timeout=timeout)
        except requests.RequestException as exc:
            raise ParserError(f"failed to download {url}: {exc}") from exc
        try:
            spec = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
        except (ValueError, yaml.YAMLError) as exc:
            raise ParserError(f"{url}: invalid spec: {exc}") from exc
        if not isinstance(spec, dict) or not spec.get("paths"):
            raise ParserError(f"{url}: not an OpenAPI spec (no paths)")
        return spec

    def _fetch_external_spec(self, url: str) -> dict:
        """Fetch and parse a sibling spec file referenced by an external $ref.

        Cached per parser instance so one file is downloaded once per parse.
        Never raises: a failure is logged and yields {}, so a bad ref cannot
        crash the whole snapshot.
        """
        if url in self._external_spec_cache:
            return self._external_spec_cache[url]
        spec: dict = {}
        try:
            text = self._get_capped_text(url)
            loaded = json.loads(text) if text.lstrip().startswith("{") else yaml.safe_load(text)
            if isinstance(loaded, dict):
                spec = loaded
            else:
                self.logger.warning("external $ref file %s is not a JSON/YAML object", url)
        except (requests.RequestException, ParserError) as exc:
            self.logger.warning("failed to fetch external $ref file %s: %s", url, exc)
        except (ValueError, yaml.YAMLError) as exc:
            self.logger.warning("external $ref file %s is not valid JSON/YAML: %s", url, exc)
        self._external_spec_cache[url] = spec
        return spec

    @staticmethod
    def _is_same_origin(url: str, spec_url: str) -> bool:
        """A `$ref` is content of a file served by the bank, not something we chose.
        `urljoin` lets an absolute ref replace the base entirely, so a tampered
        spec could point the parser at any host it likes — only a sibling file on
        the same http(s) host may be fetched.
        """
        target, base = urlparse(url), urlparse(spec_url)
        return target.scheme in ("http", "https") and target.netloc == base.netloc

    def _resolve_pointer(self, ref: str, spec: dict) -> dict:
        """Walk a local '#/a/b/c' JSON pointer inside `spec`."""
        parts = ref[2:].split("/")
        node = spec
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                node = node.get(part, {})
            else:
                return {}
        return node if isinstance(node, dict) else {}

    def _resolve_ref(
        self,
        ref: str,
        spec: dict,
        spec_url: Optional[str] = None,
        _seen: frozenset = frozenset(),
    ) -> tuple:
        """Resolve a $ref — local ('#/...') or into a sibling file ('common/x.yml#/...').

        Returns (node, spec_for_node, spec_url_for_node, seen) so callers can keep
        resolving further $refs found inside `node` against the right document.
        `seen` accumulates per recursion branch (not globally) so a cycle is
        caught without blocking legitimate reuse of the same ref in sibling branches.
        A ref that cannot be resolved logs a warning and yields ({}, spec, spec_url, seen).
        """
        if not ref or ref in _seen:
            return {}, spec, spec_url, _seen
        seen = _seen | {ref}

        if ref.startswith("#/"):
            return self._resolve_pointer(ref, spec), spec, spec_url, seen

        file_part, _, fragment = ref.partition("#")
        if not file_part:
            return {}, spec, spec_url, seen
        if not spec_url:
            self.logger.warning("cannot resolve external $ref '%s': spec has no known URL", ref)
            return {}, spec, spec_url, seen

        external_url = urljoin(spec_url, file_part)
        if not self._is_same_origin(external_url, spec_url):
            self.logger.warning(
                "refusing external $ref '%s': %s is not on the host of the spec (%s)",
                ref, external_url, spec_url,
            )
            return {}, spec, spec_url, seen
        external_spec = self._fetch_external_spec(external_url)
        if not external_spec:
            return {}, spec, spec_url, seen
        if not fragment:
            return external_spec, external_spec, external_url, seen
        node = self._resolve_pointer("#" + fragment, external_spec)
        return node, external_spec, external_url, seen

    @staticmethod
    def _is_array_schema(schema: dict) -> bool:
        """A schema is an array if declared as such, or (Sber partner-info) has
        `items:` without an explicit `type: array`."""
        return schema.get("type") == "array" or "items" in schema

    def _extract_fields(
        self,
        schema: dict,
        spec: dict,
        prefix: str = "",
        depth: int = 0,
        spec_url: Optional[str] = None,
        _seen: frozenset = frozenset(),
    ) -> list:
        if depth > 4 or not schema:
            return []

        if "$ref" in schema:
            schema, spec, spec_url, _seen = self._resolve_ref(schema["$ref"], spec, spec_url, _seen)
            if not schema:
                return []

        fields = []

        for combinator in ("allOf", "oneOf", "anyOf"):
            if combinator in schema:
                for sub in schema[combinator]:
                    fields.extend(self._extract_fields(sub, spec, prefix, depth + 1, spec_url, _seen))
                return fields

        if schema.get("type") == "object" or "properties" in schema:
            for prop_name, prop_schema in schema.get("properties", {}).items():
                full = f"{prefix}.{prop_name}" if prefix else prop_name
                fields.append(full)
                if depth < 2:
                    fields.extend(self._extract_fields(prop_schema, spec, full, depth + 1, spec_url, _seen))
        elif self._is_array_schema(schema):
            fields.extend(self._extract_fields(schema.get("items", {}), spec, prefix, depth + 1, spec_url, _seen))

        return fields

    def _pick_media_type(self, content: dict) -> tuple:
        """Pick the media type to read a body from: JSON first, else the first
        non-binary type that actually has a schema or example. (None, None) when
        nothing usable is present."""
        if not content:
            return None, None
        for media_type, data in content.items():
            if "json" in media_type.lower():
                return media_type, data
        for media_type, data in content.items():
            if any(media_type.lower().startswith(p) for p in BINARY_MEDIA_TYPE_PREFIXES):
                continue
            if isinstance(data, dict) and (data.get("schema") or "example" in data or data.get("examples")):
                return media_type, data
        return None, None

    def _select_response(self, responses: dict, spec: dict, spec_url: Optional[str] = None) -> tuple:
        """Pick the best 2xx response: prefers 200/201, else the first 2xx that
        actually has a body. Response keys are normalized to str first, since an
        unquoted `200:` in YAML parses as the int key 200. A $ref on the response
        object itself is resolved before its content is inspected. A 2xx with no
        content (e.g. 204) legitimately yields nothing.

        Returns (response_entry, its_spec, its_spec_url); ({}, spec, spec_url) when
        nothing qualifies.
        """
        normalized = {str(status): entry for status, entry in (responses or {}).items()}
        candidates = []
        for status, entry in normalized.items():
            if len(status) != 3 or not status.isdigit() or status[0] != "2":
                continue
            resolved, resolved_spec, resolved_spec_url = entry, spec, spec_url
            if isinstance(entry, dict) and "$ref" in entry:
                resolved, resolved_spec, resolved_spec_url, _ = self._resolve_ref(entry["$ref"], spec, spec_url)
            if isinstance(resolved, dict) and (resolved.get("content") or resolved.get("schema")):
                candidates.append((status, resolved, resolved_spec, resolved_spec_url))

        if not candidates:
            return {}, spec, spec_url
        for status, resolved, resolved_spec, resolved_spec_url in candidates:
            if status in ("200", "201"):
                return resolved, resolved_spec, resolved_spec_url
        _, resolved, resolved_spec, resolved_spec_url = candidates[0]
        return resolved, resolved_spec, resolved_spec_url

    def _extract_response_200_fields(self, operation: dict, spec: dict, spec_url: Optional[str] = None) -> list:
        """Extract field names from the best 2xx response body (used for GET/DELETE)."""
        responses = operation.get("responses", {})
        ok, ok_spec, ok_spec_url = self._select_response(responses, spec, spec_url)
        if not ok:
            return []

        # OpenAPI 3.x
        content = ok.get("content", {})
        if content:
            _, data = self._pick_media_type(content)
            if data is not None:
                fields = self._extract_fields(data.get("schema", {}), ok_spec, spec_url=ok_spec_url)
                if fields:
                    return fields
            return []

        # Swagger 2.0
        schema = ok.get("schema", {})
        if schema:
            return self._extract_fields(schema, ok_spec, spec_url=ok_spec_url)

        return []

    def _extract_request_body_fields(self, operation: dict, spec: dict, spec_url: Optional[str] = None) -> list:
        """Extract field names from the request body (used for POST/PUT/PATCH).

        Checks requestBody (OpenAPI 3.x) and body parameters (Swagger 2.0).
        Monitors which fields a method ACCEPTS — important for change tracking.
        """
        # OpenAPI 3.x — requestBody
        request_body = operation.get("requestBody", {})
        if request_body:
            content = request_body.get("content", {})
            _, data = self._pick_media_type(content)
            if data is not None:
                fields = self._extract_fields(data.get("schema", {}), spec, spec_url=spec_url)
                if fields:
                    return fields

        # Swagger 2.0 — body parameter
        for param in operation.get("parameters", []):
            if param.get("in") == "body":
                schema = param.get("schema", {})
                if schema:
                    return self._extract_fields(schema, spec, spec_url=spec_url)

        return []

    def _extract_fields_for_method(
        self, http_verb: str, operation: dict, spec: dict, spec_url: Optional[str] = None
    ) -> list:
        """Choose the right extractor based on HTTP method:
        - GET / DELETE  → response 200 fields (what the API returns)
        - POST / PUT / PATCH → request body fields (what the API accepts)
        Falls back to response fields if request body is empty.
        """
        verb = http_verb.lower()
        if verb in ("post", "put", "patch"):
            fields = self._extract_request_body_fields(operation, spec, spec_url)
            if fields:
                return fields
            # Some endpoints have no request body but a response
            return self._extract_response_200_fields(operation, spec, spec_url)
        return self._extract_response_200_fields(operation, spec, spec_url)

    # ── JSON example generation ────────────────────────────────────────────

    @staticmethod
    def _json_safe(val: object) -> object:
        """Convert Python types that json.dumps can't handle into JSON-safe equivalents."""
        if isinstance(val, date):  # also covers datetime
            return val.isoformat()
        if isinstance(val, dict):
            return {k: BaseParser._json_safe(v) for k, v in val.items()}
        if isinstance(val, list):
            return [BaseParser._json_safe(v) for v in val]
        return val

    @staticmethod
    def _is_meaningful_example(value: object) -> bool:
        """True for a usable example. An empty dict/list carries no information,
        but a falsy scalar (False, 0, "") is still a meaningful example."""
        if value is None:
            return False
        if isinstance(value, (dict, list)) and not value:
            return False
        return True

    def _schema_to_example(
        self,
        schema: dict,
        spec: dict,
        depth: int = 0,
        spec_url: Optional[str] = None,
        _seen: frozenset = frozenset(),
    ) -> object:
        """Recursively build a JSON example (object, array, or scalar) from an OpenAPI schema.

        Priority:
        1. schema.example (explicit example)
        2. Recurse into properties / allOf / oneOf / anyOf
        3. Type-based defaults as last resort

        Only the child that is too deep is skipped — its siblings keep being
        processed. A $ref that would revisit itself on the same branch (e.g. a
        self-referencing schema) is short-circuited by `_seen`, independently of
        the depth limit.
        """
        if depth > self._MAX_EXAMPLE_DEPTH or not schema:
            return None

        if "$ref" in schema:
            schema, spec, spec_url, _seen = self._resolve_ref(schema["$ref"], spec, spec_url, _seen)
            if not schema:
                return None

        # Explicit example always wins — but must be JSON-serializable
        if "example" in schema:
            return self._json_safe(schema["example"])

        # Combiners — merge object results, return first non-null for scalars
        for combiner in ("allOf", "oneOf", "anyOf"):
            if combiner in schema:
                merged: dict = {}
                for sub in schema[combiner]:
                    sub_schema, sub_spec, sub_spec_url, sub_seen = sub, spec, spec_url, _seen
                    if isinstance(sub, dict) and "$ref" in sub:
                        sub_schema, sub_spec, sub_spec_url, sub_seen = self._resolve_ref(
                            sub["$ref"], spec, spec_url, _seen
                        )
                        if not sub_schema:
                            continue
                    result = self._schema_to_example(sub_schema, sub_spec, depth + 1, sub_spec_url, sub_seen)
                    if isinstance(result, dict):
                        merged.update(result)
                    elif result is not None and not merged:
                        return result
                # Also merge any properties defined at the combiner level
                for prop_name, prop_schema in schema.get("properties", {}).items():
                    if prop_name not in merged:
                        val = self._schema_to_example(prop_schema, spec, depth + 1, spec_url, _seen)
                        if val is not None:
                            merged[prop_name] = val
                return merged if merged else None

        if schema.get("type") == "object" or "properties" in schema:
            obj: dict = {}
            for prop_name, prop_schema in schema.get("properties", {}).items():
                val = self._schema_to_example(prop_schema, spec, depth + 1, spec_url, _seen)
                if val is not None:
                    obj[prop_name] = val
                else:
                    # too deep, unresolvable $ref, or genuinely no default — keep the
                    # key with a type-based placeholder instead of dropping it
                    t = prop_schema.get("type", "string") if isinstance(prop_schema, dict) else "string"
                    obj[prop_name] = {"string": "string", "integer": 0,
                                      "number": 0.0, "boolean": False,
                                      "array": [], "object": {}}.get(t, "string")
            # return empty dict instead of None so callers can distinguish "has schema" from "no schema"
            return obj

        if self._is_array_schema(schema):
            item_ex = self._schema_to_example(schema.get("items", {}), spec, depth + 1, spec_url, _seen)
            return [item_ex] if item_ex is not None else []

        schema_type = schema.get("type", "")
        defaults = {"string": "string", "integer": 0, "number": 0.0,
                    "boolean": False, "null": None}
        return defaults.get(schema_type, None)

    def _extract_request_example(
        self, operation: dict, spec: dict, spec_url: Optional[str] = None
    ) -> dict | list | str | int | float | bool:
        """Return a JSON-serializable example (object, array, or scalar) for the request body."""
        # OpenAPI 3.x
        rb = operation.get("requestBody", {})
        if rb:
            content = rb.get("content", {})
            _, data = self._pick_media_type(content)
            if data is not None:
                if "example" in data and self._is_meaningful_example(data["example"]):
                    return self._json_safe(data["example"])
                for ex in data.get("examples", {}).values():
                    v = ex.get("value")
                    if self._is_meaningful_example(v):
                        return self._json_safe(v)
                result = self._schema_to_example(data.get("schema", {}), spec, spec_url=spec_url)
                if self._is_meaningful_example(result):
                    return self._json_safe(result)

        # Swagger 2.0 — body parameter
        for param in operation.get("parameters", []):
            if param.get("in") == "body":
                result = self._schema_to_example(param.get("schema", {}), spec, spec_url=spec_url)
                if self._is_meaningful_example(result):
                    return self._json_safe(result)
        return {}

    def _extract_response_example(
        self, operation: dict, spec: dict, spec_url: Optional[str] = None
    ) -> dict | list | str | int | float | bool:
        """Return a JSON-serializable example (object, array, or scalar) for the best 2xx response."""
        responses = operation.get("responses", {})
        ok, ok_spec, ok_spec_url = self._select_response(responses, spec, spec_url)
        if not ok:
            return {}

        # OpenAPI 3.x
        content = ok.get("content", {})
        if content:
            _, data = self._pick_media_type(content)
            if data is not None:
                if "example" in data and self._is_meaningful_example(data["example"]):
                    return self._json_safe(data["example"])
                for ex in data.get("examples", {}).values():
                    v = ex.get("value")
                    if self._is_meaningful_example(v):
                        return self._json_safe(v)
                result = self._schema_to_example(data.get("schema", {}), ok_spec, spec_url=ok_spec_url)
                if self._is_meaningful_example(result):
                    return self._json_safe(result)
            return {}

        # Swagger 2.0
        for mt, ex in ok.get("examples", {}).items():
            if "json" in mt and self._is_meaningful_example(ex):
                return self._json_safe(ex)
        schema = ok.get("schema", {})
        if schema:
            result = self._schema_to_example(schema, ok_spec, spec_url=ok_spec_url)
            if self._is_meaningful_example(result):
                return self._json_safe(result)
        return {}

    def _portal_url(self, portal_base_url: str, tag: str, op_id: str) -> str:
        return f"{portal_base_url}#{op_id}" if op_id else portal_base_url

    def _parse_openapi_spec(
        self,
        spec: dict,
        portal_base_url: str,
        excluded_tags: set = None,
        spec_url: Optional[str] = None,
    ) -> dict:
        """Convert an OpenAPI/Swagger spec into {service_name: [APIMethod]}.

        A tag is skipped when any excluded_tags entry is a substring of it (case-insensitive).
        `spec_url` is the URL the spec itself was downloaded from; it is needed to resolve
        $refs that point into sibling files (e.g. Sber's `common/*.yml`). Without it, such
        refs cannot be resolved and yield an empty example (a warning is logged).
        """
        excluded_tags = {t.lower() for t in (excluded_tags or set())}
        now = datetime.now(timezone.utc).isoformat()
        services: dict[str, list[APIMethod]] = {}

        for path, path_item in spec.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            for http_verb, operation in path_item.items():
                if http_verb not in {"get", "post", "put", "patch", "delete"}:
                    continue
                if not isinstance(operation, dict):
                    continue

                tags = operation.get("tags") or ["Без тега"]
                summary = operation.get("summary", "")
                description = operation.get("description", "")
                op_id = operation.get("operationId", "")
                fields = self._extract_fields_for_method(http_verb, operation, spec, spec_url)

                # Actual JSON examples for display
                if http_verb.lower() in ("post", "put", "patch"):
                    req_ex = self._extract_request_example(operation, spec, spec_url)
                    resp_ex = self._extract_response_example(operation, spec, spec_url)
                else:
                    req_ex = {}
                    resp_ex = self._extract_response_example(operation, spec, spec_url)

                for tag in tags:
                    if any(excl in tag.lower() for excl in excluded_tags):
                        continue
                    portal_url = self._portal_url(portal_base_url, tag, op_id)

                    method = APIMethod(
                        bank=self.bank_name,
                        service_name=tag,
                        http_method=http_verb.upper(),
                        path=path,
                        summary=summary,
                        description=description,
                        response_200_fields=fields,
                        parsed_at=now,
                        url_on_portal=portal_url,
                        request_example=req_ex,
                        response_example=resp_ex,
                    )
                    services.setdefault(tag, []).append(method)

        return services

    def _make_snapshot(self, services: dict) -> ParseSnapshot:
        total_methods = sum(len(v) for v in services.values())
        return ParseSnapshot(
            bank=self.bank_name,
            parsed_at=datetime.now(timezone.utc).isoformat(),
            services=services,
            total_services=len(services),
            total_methods=total_methods,
        )
