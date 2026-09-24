"""Pure snapshot comparison: previous DB state vs freshly parsed snapshot."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Optional


@dataclass(frozen=True)
class MethodRecord:
    service: str
    http_method: str
    path: str
    name: str
    url: str
    fields: frozenset[str]
    # Not visible on the dev portal — kept for the admin "hidden" tab, never on the
    # public dashboard. Deliberately NOT part of method_key(): a method flipping
    # hidden<->visible across snapshots must still be recognised as the same method.
    hidden: bool = False
    hidden_reason: Optional[str] = None


@dataclass(frozen=True)
class Change:
    change_type: str      # service | method | field
    action: str           # added | removed | modified
    entity_name: str
    entity_path: str
    url: str = ""
    old_value: str = ""
    new_value: str = ""
    # True when the change concerns something hidden: stored for the admin tab,
    # but must never reach the public dashboard, history feed or Telegram.
    hidden: bool = False


# services: {name: url}; methods: all methods of the snapshot (visible and hidden)
SnapshotState = tuple[dict[str, str], list[MethodRecord]]


def method_key(m: MethodRecord) -> str:
    """Stable identity of a method across snapshots (independent of service grouping)."""
    if m.path:
        return f"{m.http_method} {m.path}"
    return f"{m.service} / {m.http_method} {m.name}"


def service_is_hidden(hidden_flags: Iterable[bool]) -> bool:
    """A service is hidden iff it has at least one method and every one of them is hidden.

    An empty service (no methods at all) has nothing to hide and stays visible.
    Shared with app.snapshot_import so "hidden" is derived the same way everywhere
    instead of being trusted from the parser.
    """
    flags = list(hidden_flags)
    return bool(flags) and all(flags)


def _index(methods: Iterable[MethodRecord]) -> dict[str, MethodRecord]:
    # First occurrence wins so duplicates inside one snapshot are reported once
    index: dict[str, MethodRecord] = {}
    for m in methods:
        index.setdefault(method_key(m), m)
    return index


def _hidden_service_names(methods: Iterable[MethodRecord]) -> frozenset[str]:
    by_service: dict[str, list[bool]] = {}
    for m in methods:
        by_service.setdefault(m.service, []).append(m.hidden)
    return frozenset(name for name, flags in by_service.items() if service_is_hidden(flags))


def _method_change(action: str, m: MethodRecord, *, hidden: bool) -> Change:
    key = method_key(m)
    path = key if key.startswith(f"{m.service} / ") else f"{m.service} / {key}"
    return Change("method", action, key, path, m.url, hidden=hidden)


def _service_changes(
    prev: dict[str, str], new: dict[str, str],
    hidden_old: frozenset[str], hidden_new: frozenset[str],
) -> list[Change]:
    added = [
        Change("service", "added", n, n, new[n], hidden=n in hidden_new)
        for n in sorted(new.keys() - prev.keys())
    ]
    removed = [
        Change("service", "removed", n, n, prev[n], hidden=n in hidden_old)
        for n in sorted(prev.keys() - new.keys())
    ]
    return added + removed


def _field_change(old: MethodRecord, new: MethodRecord) -> Optional[Change]:
    added = sorted(new.fields - old.fields)
    removed = sorted(old.fields - new.fields)
    if not added and not removed:
        return None
    base = _method_change("modified", new, hidden=new.hidden)
    return replace(
        base,
        change_type="field",
        old_value=", ".join(f"-{f}" for f in removed),
        new_value=", ".join(f"+{f}" for f in added),
    )


def compute_changes(
    prev: Optional[SnapshotState],
    new_services: dict[str, str],
    new_methods: Iterable[MethodRecord],
) -> list[Change]:
    """Return changes between the previous snapshot and the new one.

    The very first snapshot of a bank (prev is None) is a baseline — no changes.

    Hidden methods are compared alongside visible ones (nothing is thrown away),
    but every resulting Change is marked hidden so callers can filter it out of
    the public dashboard/history/Telegram while still keeping it for the admin
    tab. A method flipping visible<->hidden keeps the same method_key(), so by
    itself it would look unchanged; we detect that flip and report it as a
    removed/added change instead — always visible, because the user really did
    lose/gain something they could see on the dashboard.
    """
    if prev is None:
        return []
    prev_services, prev_methods = prev
    old_idx = _index(prev_methods)
    new_idx = _index(new_methods)

    added_keys = sorted(new_idx.keys() - old_idx.keys())
    removed_keys = sorted(old_idx.keys() - new_idx.keys())
    common_keys = sorted(new_idx.keys() & old_idx.keys())

    method_changes = (
        [_method_change("added", new_idx[k], hidden=new_idx[k].hidden) for k in added_keys]
        + [_method_change("removed", old_idx[k], hidden=old_idx[k].hidden) for k in removed_keys]
    )

    flip_changes: list[Change] = []
    field_changes: list[Change] = []
    for k in common_keys:
        old_m, new_m = old_idx[k], new_idx[k]
        if old_m.hidden != new_m.hidden:
            # Visibility flip on an otherwise-identical method key: the dashboard
            # sees it appear/disappear, so it is reported as added/removed — always
            # visible — and normal field-level diffing is skipped for this key.
            if new_m.hidden:
                flip_changes.append(_method_change("removed", old_m, hidden=False))
            else:
                flip_changes.append(_method_change("added", new_m, hidden=False))
            continue
        fc = _field_change(old_m, new_m)
        if fc is not None:
            field_changes.append(fc)

    hidden_old = _hidden_service_names(prev_methods)
    hidden_new = _hidden_service_names(new_methods)
    service_changes = _service_changes(prev_services, new_services, hidden_old, hidden_new)

    return service_changes + method_changes + flip_changes + field_changes
