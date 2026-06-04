from dataclasses import dataclass, field
from typing import Optional

from parsers.base_parser import APIMethod, ParseSnapshot


@dataclass
class MethodKey:
    http_method: str
    path: str

    def __hash__(self):
        return hash((self.http_method.upper(), self.path))

    def __eq__(self, other):
        return self.http_method.upper() == other.http_method.upper() and self.path == other.path


@dataclass
class MethodDiff:
    service: str
    http_method: str
    path: str
    summary: str
    changed_fields: list = field(default_factory=list)


@dataclass
class DiffResult:
    bank: str
    date_old: str
    date_new: str

    added_services: list = field(default_factory=list)
    removed_services: list = field(default_factory=list)

    added_methods: list = field(default_factory=list)
    removed_methods: list = field(default_factory=list)
    changed_methods: list = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.added_services
            or self.removed_services
            or self.added_methods
            or self.removed_methods
            or self.changed_methods
        )

    def summary_text(self) -> str:
        if not self.has_changes:
            return f"[{self.bank}] No changes between {self.date_old} and {self.date_new}"

        lines = [f"[{self.bank}] Changes from {self.date_old} → {self.date_new}:"]
        if self.added_services:
            lines.append(f"  + Added services ({len(self.added_services)}): {', '.join(self.added_services)}")
        if self.removed_services:
            lines.append(f"  - Removed services ({len(self.removed_services)}): {', '.join(self.removed_services)}")
        if self.added_methods:
            lines.append(f"  + Added methods ({len(self.added_methods)}):")
            for m in self.added_methods[:10]:
                lines.append(f"      {m.http_method:7} {m.path}  [{m.service}]")
            if len(self.added_methods) > 10:
                lines.append(f"      ... and {len(self.added_methods) - 10} more")
        if self.removed_methods:
            lines.append(f"  - Removed methods ({len(self.removed_methods)}):")
            for m in self.removed_methods[:10]:
                lines.append(f"      {m.http_method:7} {m.path}  [{m.service}]")
            if len(self.removed_methods) > 10:
                lines.append(f"      ... and {len(self.removed_methods) - 10} more")
        if self.changed_methods:
            lines.append(f"  ~ Changed response fields ({len(self.changed_methods)}):")
            for m in self.changed_methods[:10]:
                lines.append(f"      {m.http_method:7} {m.path}  fields: {m.changed_fields}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        def md(m: MethodDiff) -> dict:
            return {
                "service": m.service,
                "http_method": m.http_method,
                "path": m.path,
                "summary": m.summary,
                "changed_fields": m.changed_fields,
            }

        return {
            "bank": self.bank,
            "date_old": self.date_old,
            "date_new": self.date_new,
            "added_services": self.added_services,
            "removed_services": self.removed_services,
            "added_methods": [md(m) for m in self.added_methods],
            "removed_methods": [md(m) for m in self.removed_methods],
            "changed_methods": [md(m) for m in self.changed_methods],
        }


class DiffEngine:
    def compare(self, old: Optional[ParseSnapshot], new: Optional[ParseSnapshot]) -> Optional[DiffResult]:
        if old is None or new is None:
            return None

        result = DiffResult(
            bank=new.bank,
            date_old=old.parsed_at[:10],
            date_new=new.parsed_at[:10],
        )

        old_services = set(old.services.keys())
        new_services = set(new.services.keys())

        result.added_services = sorted(new_services - old_services)
        result.removed_services = sorted(old_services - new_services)

        # Build flat method maps: {MethodKey → APIMethod}
        old_methods = self._flatten_methods(old)
        new_methods = self._flatten_methods(new)

        old_keys = set(old_methods.keys())
        new_keys = set(new_methods.keys())

        for key in new_keys - old_keys:
            m = new_methods[key]
            result.added_methods.append(MethodDiff(
                service=m.service_name,
                http_method=m.http_method,
                path=m.path,
                summary=m.summary,
            ))

        for key in old_keys - new_keys:
            m = old_methods[key]
            result.removed_methods.append(MethodDiff(
                service=m.service_name,
                http_method=m.http_method,
                path=m.path,
                summary=m.summary,
            ))

        for key in old_keys & new_keys:
            old_m = old_methods[key]
            new_m = new_methods[key]
            field_diff = self._diff_fields(old_m.response_200_fields, new_m.response_200_fields)
            if field_diff:
                result.changed_methods.append(MethodDiff(
                    service=new_m.service_name,
                    http_method=new_m.http_method,
                    path=new_m.path,
                    summary=new_m.summary,
                    changed_fields=field_diff,
                ))

        return result

    def _flatten_methods(self, snapshot: ParseSnapshot) -> dict:
        flat = {}
        for methods in snapshot.services.values():
            for m in methods:
                if not isinstance(m, APIMethod):
                    from parsers.base_parser import APIMethod as AM
                    m = AM.from_dict(m) if isinstance(m, dict) else m
                if m.path:
                    key = MethodKey(m.http_method, m.path)
                    flat[key] = m
        return flat

    def _diff_fields(self, old_fields: list, new_fields: list) -> list:
        old_set = set(old_fields or [])
        new_set = set(new_fields or [])
        changes = []
        for f in sorted(new_set - old_set):
            changes.append(f"+{f}")
        for f in sorted(old_set - new_set):
            changes.append(f"-{f}")
        return changes
