"""T-Bank parser.

The Docusaurus portal (developer.tbank.ru) does not serve one spec — it builds
three separate spaces from type-filtered copies of the same underlying YAML:

  - "T-API"           /docs/api      <- front/openapi.yaml?type=sme
  - "API" (partner)   /t_api/api     <- front/openapi.yaml?type=public&type=acq&...
  - "private"         /private/api   <- front/openapi.yaml?type=private (no selector
                                        entry, no sitemap page, noindex — closed space)

The combined "everything" spec (business.tbank.ru/openapi/docs/openapi.yaml) mixes
all three, which both invents non-existent services and hides the closed ones behind
ordinary-looking tags. We fetch each space separately so the visible set matches the
portal 1:1, and keep the private methods — marked hidden — instead of dropping them.
"""
import copy
import re
from dataclasses import replace

from .base_parser import BaseParser, HIDDEN_REASON_PRIVATE, ParseSnapshot

SPEC_BASE = "https://business.tbank.ru/openapi/docs/front/openapi.yaml"
SPEC_URL_TAPI = f"{SPEC_BASE}?type=sme"
SPEC_URL_PARTNER = (
    f"{SPEC_BASE}?type=public&type=acq&type=credit&type=pos&type=dolyame"
    "&type=tochka&type=rosbank&type=ecobundle&type=unset&type=shopping"
)
SPEC_URL_PRIVATE = f"{SPEC_BASE}?type=private"

PORTAL_TAPI = "https://developer.tbank.ru/docs/api"
PORTAL_PARTNER = "https://developer.tbank.ru/t_api/api"
# Real path of the closed space (no selector entry, no sitemap, noindex) — kept so
# an admin looking at the hidden tab can still find the source page.
PORTAL_PRIVATE = "https://developer.tbank.ru/private/api"

_OPENAPI_VERBS = {"get", "post", "put", "patch", "delete"}


class TBankParser(BaseParser):
    def __init__(self):
        super().__init__("tbank")

    def parse(self) -> ParseSnapshot:
        self.logger.info("Starting T-Bank parser (T-API + partner API + private, OpenAPI YAML)")

        services: dict = {}
        for spec_url, portal_base in (
            (SPEC_URL_TAPI, PORTAL_TAPI),
            (SPEC_URL_PARTNER, PORTAL_PARTNER),
        ):
            self._merge(services, self._parse_space(spec_url, portal_base))

        private_services = self._parse_space(SPEC_URL_PRIVATE, PORTAL_PRIVATE)
        self._merge(services, self._mark_hidden(private_services))

        snapshot = self._make_snapshot(services)
        self.logger.info(
            "T-Bank: %d services, %d methods (visible + hidden)",
            snapshot.total_services, snapshot.total_methods,
        )
        return snapshot

    def _parse_space(self, spec_url: str, portal_base: str) -> dict:
        spec = self._fetch_spec(spec_url)
        spec = self._apply_parent_tags(spec)
        return self._parse_openapi_spec(spec, portal_base, spec_url=spec_url)

    @staticmethod
    def _apply_parent_tags(spec: dict) -> dict:
        """The portal groups leaf tags under a parent (`x-parent-tag`) and shows
        "Parent. Child" as the service name. A bare leaf tag is ambiguous on its
        own (e.g. "Заявки" means different things under different parents), so
        operations are rewritten to the display name before grouping.
        """
        parent_of = {
            t["name"]: t["x-parent-tag"]
            for t in spec.get("tags", [])
            if isinstance(t, dict) and t.get("name") and t.get("x-parent-tag")
        }
        if not parent_of:
            return spec

        spec = copy.deepcopy(spec)
        for path_item in spec.get("paths", {}).values():
            if not isinstance(path_item, dict):
                continue
            for verb, operation in path_item.items():
                if verb not in _OPENAPI_VERBS or not isinstance(operation, dict):
                    continue
                operation["tags"] = [
                    f"{parent_of[tag]}. {tag}" if tag in parent_of else tag
                    for tag in (operation.get("tags") or [])
                ]
        return spec

    @staticmethod
    def _merge(into: dict, extra: dict) -> None:
        for svc, methods in extra.items():
            into.setdefault(svc, []).extend(methods)

    @staticmethod
    def _mark_hidden(services: dict) -> dict:
        """Everything from the `private` space is real (used by internal/partner
        integrations) but must never reach the public dashboard — keep it, tagged
        for the admin-only hidden tab."""
        return {
            svc: [replace(m, hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE) for m in methods]
            for svc, methods in services.items()
        }

    def _portal_url(self, portal_base_url: str, tag: str, op_id: str) -> str:
        if not op_id:
            return portal_base_url
        return f"{portal_base_url}/{self._kebab(op_id)}"

    @staticmethod
    def _kebab(op_id: str) -> str:
        """operationId -> the slug Docusaurus derives for the page anchor.

        Splits camelCase/PascalCase boundaries and letter<->digit transitions
        (e.g. "getPaymentOperationListAcquiringV1_0" -> "get-payment-operation-
        list-acquiring-v-1-0"), matching the lodash `kebabCase` the portal itself
        uses — verified against Tochka's sitemap, which exposes the same scheme.
        """
        words = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+", op_id)
        return "-".join(w.lower() for w in words) if words else op_id.lower()
