import logging
from typing import Optional

import requests
import yaml

from .base_parser import BaseParser, ParseSnapshot

logger = logging.getLogger("parser.tbank")

SPEC_URL = "https://business.tbank.ru/openapi/docs/openapi.yaml"
PORTAL_BASE = "https://developer.tbank.ru/docs/api/t-api"

# Tags/product names to exclude (case-insensitive substring match)
EXCLUDED_TAGS = {
    "долями",
    "voicekit",
    "voice kit",
}


class TBankParser(BaseParser):
    def __init__(self):
        super().__init__("tbank")

    def parse(self) -> Optional[ParseSnapshot]:
        self.logger.info("Starting T-Bank parser (OpenAPI YAML)")
        try:
            spec = self._download_spec()
            if spec is None:
                return None
            services = self._parse_openapi_spec(spec, PORTAL_BASE, EXCLUDED_TAGS)
            snapshot = self._make_snapshot(services)
            self.logger.info(
                "T-Bank: %d services, %d methods",
                snapshot.total_services,
                snapshot.total_methods,
            )
            return snapshot
        except Exception as exc:
            self.logger.error("T-Bank parser failed: %s", exc, exc_info=True)
            return None

    def _download_spec(self) -> Optional[dict]:
        self.logger.info("Downloading T-Bank spec from %s", SPEC_URL)
        try:
            resp = self.session.get(SPEC_URL, timeout=60)
            resp.raise_for_status()
            spec = yaml.safe_load(resp.text)
            self.logger.debug("Spec downloaded, %d paths", len(spec.get("paths", {})))
            return spec
        except requests.RequestException as exc:
            self.logger.error("Failed to download T-Bank spec: %s", exc)
            return None
        except yaml.YAMLError as exc:
            self.logger.error("Failed to parse T-Bank YAML: %s", exc)
            return None

    def _is_excluded(self, tag: str) -> bool:
        tag_lower = tag.lower()
        return any(excl in tag_lower for excl in EXCLUDED_TAGS)

    def _parse_openapi_spec(self, spec: dict, portal_base_url: str, excluded_tags: set = None) -> dict:
        """Override to apply T-Bank specific tag filtering."""
        from datetime import datetime

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

                # JSON examples for UI display
                if http_verb.lower() in ("post", "put", "patch"):
                    req_ex  = self._extract_request_example(operation, spec)
                    resp_ex = self._extract_response_example(operation, spec)
                else:
                    req_ex  = {}
                    resp_ex = self._extract_response_example(operation, spec)

                for tag in tags:
                    if self._is_excluded(tag):
                        self.logger.debug("Excluding tag: %s", tag)
                        continue

                    from .base_parser import APIMethod
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
