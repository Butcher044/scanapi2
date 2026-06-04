import logging
from typing import Optional

import requests

from .base_parser import BaseParser, ParseSnapshot

logger = logging.getLogger("parser.tochka")

SPEC_URL = "https://enter.tochka.com/doc/openapi/swagger.json"
PORTAL_BASE = "https://developers.tochka.com/docs/tochka-api"

# Tags to exclude (case-insensitive substring match)
EXCLUDED_TAGS = {
    "introduction",
    "введение",
    "работа с вебхуками",
    "webhook",
    "webhooks",
}


class TochkaParser(BaseParser):
    def __init__(self):
        super().__init__("tochka")

    def parse(self) -> Optional[ParseSnapshot]:
        self.logger.info("Starting Tochka parser (OpenAPI JSON)")
        try:
            spec = self._download_spec()
            if spec is None:
                return None
            services = self._parse_openapi_spec(spec, PORTAL_BASE, EXCLUDED_TAGS)
            snapshot = self._make_snapshot(services)
            self.logger.info(
                "Tochka: %d services, %d methods",
                snapshot.total_services,
                snapshot.total_methods,
            )
            return snapshot
        except Exception as exc:
            self.logger.error("Tochka parser failed: %s", exc, exc_info=True)
            return None

    def _download_spec(self) -> Optional[dict]:
        self.logger.info("Downloading Tochka spec from %s", SPEC_URL)
        try:
            resp = self.session.get(SPEC_URL, timeout=60)
            resp.raise_for_status()
            spec = resp.json()
            self.logger.debug("Spec downloaded, %d paths", len(spec.get("paths", {})))
            return spec
        except requests.RequestException as exc:
            self.logger.error("Failed to download Tochka spec: %s", exc)
            return None
        except ValueError as exc:
            self.logger.error("Failed to parse Tochka JSON: %s", exc)
            return None

    def _parse_openapi_spec(self, spec: dict, portal_base_url: str, excluded_tags: set = None) -> dict:
        """Override to use Swagger 2.0 definitions for $ref resolution and apply tag filtering."""
        from datetime import datetime
        from .base_parser import APIMethod

        excluded_lower = {t.lower() for t in (excluded_tags or set())}
        now = datetime.utcnow().isoformat()
        services: dict = {}

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

                if http_verb.lower() in ("post", "put", "patch"):
                    req_ex  = self._extract_request_example(operation, spec)
                    resp_ex = self._extract_response_example(operation, spec)
                else:
                    req_ex  = {}
                    resp_ex = self._extract_response_example(operation, spec)

                for tag in tags:
                    if any(excl in tag.lower() for excl in excluded_lower):
                        self.logger.debug("Excluding tag: %s", tag)
                        continue

                    portal_url = f"{portal_base_url}/#{tag.lower().replace(' ', '-')}"
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
