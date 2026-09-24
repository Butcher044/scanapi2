"""Persist a parsed snapshot and record its diff — atomically."""
from __future__ import annotations

import logging
from typing import Optional

import asyncpg

from app import repository as repo
from app.diff import Change, MethodRecord, compute_changes, service_is_hidden

logger = logging.getLogger(__name__)


class SnapshotRejected(Exception):
    """The parsed snapshot looks broken and must not replace the previous one."""


def snapshot_to_records(snapshot) -> tuple[dict[str, str], list[MethodRecord]]:
    services = {
        name: (methods[0].url_on_portal if methods else "")
        for name, methods in snapshot.services.items()
    }
    methods = [
        MethodRecord(
            service=name,
            http_method=m.http_method,
            path=m.path or "",
            name=m.summary,
            url=m.url_on_portal,
            fields=frozenset(m.response_200_fields or ()),
            hidden=m.hidden,
            hidden_reason=m.hidden_reason,
        )
        for name, items in snapshot.services.items()
        for m in items
    ]
    return services, methods


def _visible_count(methods) -> int:
    return sum(1 for m in methods if not m.hidden)


def visible_counts(snapshot) -> tuple[int, int]:
    """Visible services and methods of a freshly parsed snapshot.

    Never trust the parser's own totals: a service is hidden iff every one of
    its methods is hidden (see diff.service_is_hidden), derived here instead.
    """
    visible_services = sum(
        1 for methods in snapshot.services.values()
        if not service_is_hidden(m.hidden for m in methods)
    )
    visible_methods = sum(
        1 for methods in snapshot.services.values() for m in methods if not m.hidden
    )
    return visible_services, visible_methods


def check_sanity(prev_methods: Optional[int], new_methods: int, min_ratio: float) -> None:
    """new_methods/prev_methods must both be VISIBLE-only counts — a snapshot that
    is entirely hidden looks like 0 visible methods and is rejected the same way
    as a genuinely empty one.
    """
    if new_methods == 0:
        raise SnapshotRejected("parser returned 0 methods")
    if prev_methods and min_ratio > 0 and new_methods < prev_methods * min_ratio:
        raise SnapshotRejected(
            f"methods dropped from {prev_methods} to {new_methods} "
            f"(< {min_ratio:.0%} of previous) — snapshot rejected"
        )


async def _write_snapshot(conn: asyncpg.Connection, bank: str, snapshot) -> int:
    snap_id = await repo.create_snapshot(conn, bank)
    for svc_name, methods in snapshot.services.items():
        svc_url = methods[0].url_on_portal if methods else ""
        # A service is hidden only if ALL of its methods are — derived here, not
        # trusted from the parser (see diff.service_is_hidden for the rule).
        svc_hidden = service_is_hidden(m.hidden for m in methods)
        svc_id = await repo.create_service(conn, snap_id, svc_name, svc_url, hidden=svc_hidden)
        for m in methods:
            method_id = await repo.create_method(
                conn, svc_id,
                name=m.summary,
                http_method=m.http_method,
                url=m.url_on_portal,
                description=m.description,
                path=m.path,
                request_example=m.request_example,
                response_example=m.response_example,
                hidden=m.hidden,
                hidden_reason=m.hidden_reason,
            )
            await repo.create_fields(conn, method_id, sorted(set(m.response_200_fields or ())))
    return snap_id


async def import_snapshot(
    conn: asyncpg.Connection,
    bank: str,
    snapshot,
    *,
    min_ratio: float,
    keep: int,
) -> list[Change]:
    """Store the snapshot, record changes vs. the previous one, prune old snapshots.

    Everything runs in one transaction: a failure leaves the DB untouched.
    Raises SnapshotRejected when the snapshot looks broken (based on VISIBLE
    method counts only — a bank whose visible surface collapses is rejected
    even if it still reports plenty of hidden methods).

    Hidden changes are stored (for the admin tab) but never returned to the
    caller, so they never reach the public history feed or Telegram.
    """
    services, methods = snapshot_to_records(snapshot)
    async with conn.transaction():
        prev = await repo.get_latest_snapshot(conn, bank)
        prev_state = await repo.get_snapshot_state(conn, prev["id"]) if prev else None
        prev_visible = _visible_count(prev_state[1]) if prev_state else None
        check_sanity(prev_visible, _visible_count(methods), min_ratio)

        changes = compute_changes(prev_state, services, methods)
        snap_id = await _write_snapshot(conn, bank, snapshot)
        await repo.create_changes(conn, snap_id, bank, changes)

        old_ids = await repo.get_snapshots_for_cleanup(conn, bank, keep=keep)
        await repo.delete_snapshots(conn, old_ids)

    visible_changes = [c for c in changes if not c.hidden]
    logger.info(
        "[%s] snapshot %d stored, %d changes (%d hidden)",
        bank, snap_id, len(visible_changes), len(changes) - len(visible_changes),
    )
    return visible_changes
