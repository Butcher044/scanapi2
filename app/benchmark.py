"""
Benchmark: which bank offers which capability (app.benchmark_catalog).

Pure functions over the latest snapshot of each bank. A cell is "+" when some
service matches the capability (see Capability) — unless an admin override
says otherwise. The evidence (which services, how many methods) is kept for
the UI, so every "+" can be checked by a human. Services that match nothing
are returned as `unmatched`, so nothing silently falls out of the comparison.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Mapping, Optional, Sequence

from app.benchmark_catalog import CATALOG, Capability


@dataclass(frozen=True)
class ServiceInfo:
    name: str
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evidence:
    service: str
    matched: int       # methods that count for the capability
    total: int         # all methods of the service
    by_name: bool      # the service name itself matched: every method counts


@dataclass(frozen=True)
class Cell:
    auto: bool
    override: Optional[bool]
    evidence: tuple[Evidence, ...]

    @property
    def present(self) -> bool:
        return self.auto if self.override is None else self.override


@dataclass(frozen=True)
class Row:
    capability: Capability
    cells: Mapping[str, Cell]


@dataclass(frozen=True)
class Benchmark:
    rows: tuple[Row, ...]
    unmatched: Mapping[str, tuple[str, ...]]


@lru_cache(maxsize=None)
def _regex(pattern: str) -> Optional[re.Pattern]:
    return re.compile(pattern) if pattern else None


def _hits(pattern: str, exclude: str, text: str) -> bool:
    rx, ex = _regex(pattern), _regex(exclude)
    text = text.lower()
    return rx is not None and rx.search(text) is not None and not (ex and ex.search(text))


def match(cap: Capability, service: ServiceInfo) -> Optional[Evidence]:
    total = len(service.paths)
    if _hits(cap.names, cap.exclude, service.name):
        return Evidence(service.name, total, total, by_name=True)
    matched = sum(1 for p in service.paths if _hits(cap.paths, cap.exclude, p))
    return Evidence(service.name, matched, total, by_name=False) if matched else None


def _cell(cap: Capability, services: Sequence[ServiceInfo], override: Optional[bool]) -> Cell:
    found = (match(cap, s) for s in services)
    evidence = sorted((e for e in found if e), key=lambda e: (-e.matched, e.service))
    return Cell(auto=bool(evidence), override=override, evidence=tuple(evidence))


def build(
    services: Mapping[str, Sequence[ServiceInfo]],
    overrides: Mapping[tuple[str, str], bool],
    banks: Sequence[str],
    catalog: Sequence[Capability] = CATALOG,
) -> Benchmark:
    rows = tuple(
        Row(cap, {bank: _cell(cap, services.get(bank, ()), overrides.get((cap.key, bank))) for bank in banks})
        for cap in catalog
    )
    matched_names = {
        bank: {e.service for row in rows for e in row.cells[bank].evidence} for bank in banks
    }
    unmatched = {
        bank: tuple(sorted(s.name for s in services.get(bank, ()) if s.name not in matched_names[bank]))
        for bank in banks
    }
    return Benchmark(rows=rows, unmatched=unmatched)


def services_from_rows(rows: Iterable[Mapping]) -> dict[str, list[ServiceInfo]]:
    """Group flat (bank, service, path) rows — path is NULL for a service without methods."""
    grouped: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        paths = grouped.setdefault(r["bank"], {}).setdefault(r["service"], [])
        if r["path"]:
            paths.append(r["path"])
    return {
        bank: [ServiceInfo(name, tuple(paths)) for name, paths in by_name.items()]
        for bank, by_name in grouped.items()
    }
