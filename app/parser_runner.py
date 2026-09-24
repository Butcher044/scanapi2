"""Runs the bank parsers and imports results into PostgreSQL."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol, Sequence

import asyncpg

from app import notify_format
from app.banks import BANK_KEYS, parser_class
from app.diff import Change
from app.snapshot_import import SnapshotRejected, import_snapshot, visible_counts
from bank_api_parser import proxy
from bank_api_parser.parsers.base_parser import ParserError

logger = logging.getLogger(__name__)


# ── Status tracking (immutable, replaced on every transition) ────────────────

@dataclass(frozen=True)
class BankStatus:
    status: str = "pending"   # pending | running | done | error
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    services: int = 0
    methods: int = 0
    changes: int = 0
    error: Optional[str] = None


@dataclass(frozen=True)
class ParseStatus:
    running: bool = False
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    banks: dict[str, BankStatus] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "running":     self.running,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "banks": {k: asdict(v) for k, v in self.banks.items()},
        }


# Messages of these errors are ours and safe to show on the public status endpoint
_PUBLIC_ERRORS = (ParserError, SnapshotRejected)


def _public_error(exc: Exception) -> str:
    if isinstance(exc, _PUBLIC_ERRORS):
        return str(exc)
    return f"internal error ({type(exc).__name__}), see server logs"


class Notifier(Protocol):
    async def broadcast(self, texts: Sequence[str]) -> None: ...
    async def send_admin(self, text: str) -> None: ...


@dataclass(frozen=True)
class BankOutcome:
    changes: tuple[Change, ...] = ()
    error: Optional[str] = None     # None = success
    rejected: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ── Runner ────────────────────────────────────────────────────────────────────

class ParserRunner:
    def __init__(
        self,
        pool: asyncpg.Pool,
        notifier: Optional[Notifier] = None,
        *,
        min_snapshot_ratio: float = 0.5,
        snapshots_keep: int = 7,
        dashboard_url: str = "",
        proxy_source: Optional[Callable[[], Awaitable[Optional[proxy.ProxyRotator]]]] = None,
    ):
        self.pool = pool
        self.notifier = notifier
        self.min_snapshot_ratio = min_snapshot_ratio
        self.snapshots_keep = snapshots_keep
        self.dashboard_url = dashboard_url
        self.proxy_source = proxy_source
        self.status = ParseStatus(banks={b: BankStatus() for b in BANK_KEYS})
        self._lock = asyncio.Lock()
        # Banks whose last run failed — alerts fire only on transitions (in-memory:
        # after a restart a still-broken bank is reported once more).
        self._failing: frozenset[str] = frozenset()

    def _set_bank(self, bank: str, **changes) -> None:
        banks = {**self.status.banks, bank: replace(self.status.banks[bank], **changes)}
        self.status = replace(self.status, banks=banks)

    async def run_all(self, banks: tuple[str, ...] = BANK_KEYS) -> None:
        if self._lock.locked():
            logger.warning("Parse already running, skipping")
            return
        async with self._lock:
            self.status = ParseStatus(
                running=True, started_at=_now(),
                banks={b: BankStatus() for b in BANK_KEYS},
            )
            logger.info("Parse started: %s", list(banks))
            outcomes: dict[str, BankOutcome] = {}
            proxy.set_active(await self._load_proxies())
            try:
                for bank in banks:
                    outcomes = {**outcomes, bank: await self._run_bank_safe(bank)}
            finally:
                proxy.set_active(None)
                self.status = replace(self.status, running=False, finished_at=_now())
                states = [b.status for b in self.status.banks.values()]
                logger.info("Parse finished: %d done, %d errors",
                            states.count("done"), states.count("error"))
            await self._notify(outcomes)

    async def _load_proxies(self) -> Optional[proxy.ProxyRotator]:
        if self.proxy_source is None:
            return None
        try:
            return await self.proxy_source()
        except Exception:   # proxies are an optimisation: never block the parse
            logger.exception("Could not load proxies, parsing directly")
            return None

    async def _run_bank_safe(self, bank: str) -> BankOutcome:
        try:
            return BankOutcome(changes=tuple(await self.run_bank(bank)))
        except Exception as exc:
            logger.error("[%s] failed: %s", bank, exc, exc_info=True)
            error = _public_error(exc)
            self._set_bank(bank, status="error", error=error, finished_at=_now())
            return BankOutcome(error=error, rejected=isinstance(exc, SnapshotRejected))

    async def run_bank(self, bank: str) -> list[Change]:
        self._set_bank(bank, status="running", started_at=_now())
        logger.info("[%s] Starting parse", bank)

        # The constructor builds the CA bundle (disk I/O) — keep it off the event loop too.
        snapshot = await asyncio.to_thread(lambda: parser_class(bank)().parse())
        if snapshot is None:
            raise ParserError("parser returned no data")

        # Report only the visible surface — never trust the parser's own totals,
        # which may include hidden methods/services (see app.snapshot_import).
        visible_services, visible_methods = visible_counts(snapshot)
        logger.info("[%s] Parsed: %d services, %d methods (visible)",
                    bank, visible_services, visible_methods)
        async with self.pool.acquire() as conn:
            changes = await import_snapshot(
                conn, bank, snapshot,
                min_ratio=self.min_snapshot_ratio, keep=self.snapshots_keep,
            )

        self._set_bank(
            bank, status="done", finished_at=_now(),
            services=visible_services, methods=visible_methods,
            changes=len(changes),
        )
        return changes

    # ── Notifications (after every snapshot of the run is committed) ──────────

    async def _notify(self, outcomes: dict[str, BankOutcome]) -> None:
        failed = frozenset(b for b, o in outcomes.items() if o.error)
        recovered = frozenset(b for b, o in outcomes.items() if not o.error) & self._failing
        newly_failed = failed - self._failing
        self._failing = (self._failing - recovered) | failed
        if not self.notifier:
            return

        try:
            digest = notify_format.build_digest(
                {b: o.changes for b, o in outcomes.items() if not o.error},
                when=datetime.now(timezone.utc), dashboard_url=self.dashboard_url,
            )
        except Exception:   # a formatting bug must not also swallow the admin alerts
            logger.exception("Failed to build the change digest")
            digest = []
        alerts = [
            *(notify_format.format_failure(b, outcomes[b].error or "", rejected=outcomes[b].rejected)
              for b in outcomes if b in newly_failed),
            *(notify_format.format_recovery(b) for b in outcomes if b in recovered),
        ]
        if digest:
            await self._safely(self.notifier.broadcast, digest)
        for alert in alerts:
            await self._safely(self.notifier.send_admin, alert)

    @staticmethod
    async def _safely(send: Callable[[Any], Awaitable[None]], payload: object) -> None:
        try:
            await send(payload)
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)
