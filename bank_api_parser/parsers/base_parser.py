from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging
import time
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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
    # Actual JSON examples (displayed in UI, monitored for changes)
    request_example: dict = field(default_factory=dict)
    response_example: dict = field(default_factory=dict)

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


class BaseParser(ABC):
    def __init__(self, bank_name: str):
        self.bank_name = bank_name
        self.logger = logging.getLogger(f"parser.{bank_name}")
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
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

    def _rate_limit(self):
        delay = random.uniform(2.0, 5.0)
        self.logger.debug("Rate limit pause %.1fs", delay)
        time.sleep(delay)

    @abstractmethod
    def parse(self) -> Optional[ParseSnapshot]:
        pass

    # ── OpenAPI / Swagger helpers ──────────────────────────────────────────

    def _resolve_ref(self, ref: str, spec: dict, _seen: set = None) -> dict:
        if _seen is None:
            _seen = set()
        if ref in _seen or not ref.startswith("#/"):
            return {}
        _seen.add(ref)
        parts = ref[2:].split("/")
        node = spec
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                node = node.get(part, {})
            else:
                return {}
        return node if isinstance(node, dict) else {}
        if not ref.startswith("#/"):
            return {}
        parts = ref[2:].split("/")
        node = spec
        for part in parts:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict):
                node = node.get(part, {})
            else:
                return {}
        return node if isinstance(node, dict) else {}

    def _extract_fields(self, schema: dict, spec: dict, prefix: str = "", depth: int = 0) -> list:
        if depth > 4 or not schema:
            return []

        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"], spec)
            if not schema:
                return []

        fields = []

        for combinator in ("allOf", "oneOf", "anyOf"):
            if combinator in schema:
                for sub in schema[combinator]:
                    fields.extend(self._extract_fields(sub, spec, prefix, depth + 1))
                return fields

        schema_type = schema.get("type", "")

        if schema_type == "object" or "properties" in schema:
            for prop_name, prop_schema in schema.get("properties", {}).items():
                full = f"{prefix}.{prop_name}" if prefix else prop_name
                fields.append(full)
                if depth < 2:
                    fields.extend(self._extract_fields(prop_schema, spec, full, depth + 1))
        elif schema_type == "array":
            fields.extend(self._extract_fields(schema.get("items", {}), spec, prefix, depth + 1))

        return fields

    def _extract_response_200_fields(self, operation: dict, spec: dict) -> list:
        """Extract field names from the 200/201 response body (used for GET/DELETE)."""
        responses = operation.get("responses", {})
        ok = responses.get("200") or responses.get("201") or {}

        # OpenAPI 3.x
        content = ok.get("content", {})
        for media_type, data in content.items():
            if "json" in media_type.lower():
                fields = self._extract_fields(data.get("schema", {}), spec)
                if fields:
                    return fields[:50]
        # fallback: any content type
        for data in content.values():
            fields = self._extract_fields(data.get("schema", {}), spec)
            if fields:
                return fields[:50]

        # Swagger 2.0
        schema = ok.get("schema", {})
        if schema:
            return self._extract_fields(schema, spec)[:50]

        return []

    def _extract_request_body_fields(self, operation: dict, spec: dict) -> list:
        """Extract field names from the request body (used for POST/PUT/PATCH).

        Checks requestBody (OpenAPI 3.x) and body parameters (Swagger 2.0).
        Monitors which fields a method ACCEPTS — important for change tracking.
        """
        # OpenAPI 3.x — requestBody
        request_body = operation.get("requestBody", {})
        if request_body:
            content = request_body.get("content", {})
            for media_type, data in content.items():
                if "json" in media_type.lower():
                    fields = self._extract_fields(data.get("schema", {}), spec)
                    if fields:
                        return fields[:50]
            # non-JSON (form-data, etc.)
            for data in content.values():
                fields = self._extract_fields(data.get("schema", {}), spec)
                if fields:
                    return fields[:50]

        # Swagger 2.0 — body parameter
        for param in operation.get("parameters", []):
            if param.get("in") == "body":
                schema = param.get("schema", {})
                if schema:
                    return self._extract_fields(schema, spec)[:50]

        return []

    def _extract_fields_for_method(self, http_verb: str, operation: dict, spec: dict) -> list:
        """Choose the right extractor based on HTTP method:
        - GET / DELETE  → response 200 fields (what the API returns)
        - POST / PUT / PATCH → request body fields (what the API accepts)
        Falls back to response fields if request body is empty.
        """
        verb = http_verb.lower()
        if verb in ("post", "put", "patch"):
            fields = self._extract_request_body_fields(operation, spec)
            if fields:
                return fields
            # Some endpoints have no request body but a response
            return self._extract_response_200_fields(operation, spec)
        return self._extract_response_200_fields(operation, spec)

    # ── JSON example generation ────────────────────────────────────────────

    @staticmethod
    def _json_safe(val: object) -> object:
        """Convert Python types that json.dumps can't handle into JSON-safe equivalents."""
        import datetime
        if isinstance(val, (datetime.date, datetime.datetime)):
            return val.isoformat()
        if isinstance(val, dict):
            return {k: BaseParser._json_safe(v) for k, v in val.items()}
        if isinstance(val, list):
            return [BaseParser._json_safe(v) for v in val]
        return val

    def _schema_to_example(self, schema: dict, spec: dict, depth: int = 0) -> object:
        """Recursively build a JSON example object from an OpenAPI schema.

        Priority:
        1. schema.example (explicit example)
        2. Recurse into properties / allOf / oneOf / anyOf
        3. Type-based defaults as last resort
        """
        if depth > 4 or not schema:
            return None

        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"], spec)
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
                    if isinstance(sub, dict) and "$ref" in sub:
                        sub = self._resolve_ref(sub["$ref"], spec)
                    result = self._schema_to_example(sub, spec, depth + 1)
                    if isinstance(result, dict):
                        merged.update(result)
                    elif result is not None and not merged:
                        return result
                # Also merge any properties defined at the combiner level
                for prop_name, prop_schema in schema.get("properties", {}).items():
                    if prop_name not in merged:
                        val = self._schema_to_example(prop_schema, spec, depth + 1)
                        if val is not None:
                            merged[prop_name] = val
                return merged if merged else None

        schema_type = schema.get("type", "")

        if schema_type == "object" or "properties" in schema:
            obj: dict = {}
            for prop_name, prop_schema in schema.get("properties", {}).items():
                if depth >= 3:  # limit depth to avoid huge payloads
                    break
                val = self._schema_to_example(prop_schema, spec, depth + 1)
                if val is not None:
                    obj[prop_name] = val
                else:
                    t = prop_schema.get("type", "string") if isinstance(prop_schema, dict) else "string"
                    obj[prop_name] = {"string": "string", "integer": 0,
                                      "number": 0.0, "boolean": False,
                                      "array": [], "object": {}}.get(t, "string")
            # return empty dict instead of None so callers can distinguish "has schema" from "no schema"
            return obj

        if schema_type == "array":
            item_ex = self._schema_to_example(schema.get("items", {}), spec, depth + 1)
            return [item_ex] if item_ex is not None else []

        defaults = {"string": "string", "integer": 0, "number": 0.0,
                    "boolean": False, "null": None}
        return defaults.get(schema_type, None)

    def _extract_request_example(self, operation: dict, spec: dict) -> dict:
        """Return a JSON-serializable example object for the request body."""
        # OpenAPI 3.x
        rb = operation.get("requestBody", {})
        if rb:
            content = rb.get("content", {})
            for mt, data in content.items():
                if "json" not in mt.lower():
                    continue
                if "example" in data and isinstance(data["example"], dict):
                    return self._json_safe(data["example"])
                for ex in data.get("examples", {}).values():
                    v = ex.get("value", {})
                    if isinstance(v, dict) and v:
                        return self._json_safe(v)
                result = self._schema_to_example(data.get("schema", {}), spec)
                if isinstance(result, dict):
                    return self._json_safe(result)

        # Swagger 2.0 — body parameter
        for param in operation.get("parameters", []):
            if param.get("in") == "body":
                result = self._schema_to_example(param.get("schema", {}), spec)
                if isinstance(result, dict):
                    return self._json_safe(result)
        return {}

    def _extract_response_example(self, operation: dict, spec: dict) -> dict:
        """Return a JSON-serializable example object for the 200/201 response."""
        responses = operation.get("responses", {})
        ok = responses.get("200") or responses.get("201") or {}

        # OpenAPI 3.x
        content = ok.get("content", {})
        for mt, data in content.items():
            if "json" not in mt.lower():
                continue
            if "example" in data and isinstance(data["example"], dict):
                return self._json_safe(data["example"])
            for ex in data.get("examples", {}).values():
                v = ex.get("value", {})
                if isinstance(v, dict) and v:
                    return self._json_safe(v)
            result = self._schema_to_example(data.get("schema", {}), spec)
            if isinstance(result, dict):
                return self._json_safe(result)

        # Swagger 2.0
        for mt, ex in ok.get("examples", {}).items():
            if "json" in mt and isinstance(ex, dict) and ex:
                return self._json_safe(ex)
        schema = ok.get("schema", {})
        if schema:
            result = self._schema_to_example(schema, spec)
            if isinstance(result, dict):
                return self._json_safe(result)
        return {}

    def _parse_openapi_spec(
        self,
        spec: dict,
        portal_base_url: str,
        excluded_tags: set = None,
    ) -> dict:
        """Convert an OpenAPI/Swagger spec into {service_name: [APIMethod]}."""
        excluded_tags = {t.lower() for t in (excluded_tags or set())}
        now = datetime.utcnow().isoformat()
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
                fields = self._extract_fields_for_method(http_verb, operation, spec)

                # Actual JSON examples for display
                if http_verb.lower() in ("post", "put", "patch"):
                    req_ex = self._extract_request_example(operation, spec)
                    resp_ex = self._extract_response_example(operation, spec)
                else:
                    req_ex = {}
                    resp_ex = self._extract_response_example(operation, spec)

                for tag in tags:
                    if tag.lower() in excluded_tags:
                        continue
                    if any(excl in tag.lower() for excl in excluded_tags):
                        continue

                    portal_url = f"{portal_base_url}#{op_id}" if op_id else portal_base_url

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
            parsed_at=datetime.utcnow().isoformat(),
            services=services,
            total_services=len(services),
            total_methods=total_methods,
        )
