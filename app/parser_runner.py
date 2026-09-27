"""Runs the bank parsers and imports results into PostgreSQL."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional, Protocol, Sequence

import asyncpg

from app import notify_format
from app.banks import BANK_KEYS, bank_label, parser_class
from app.diff import Change
from app.event_log import NULL_EVENTS, EventSink, count, describe_error, fmt_duration
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


# How a run was started, as the admin reads it in the "Логи" tab
TRIGGERS = {
    "manual":   "вручную из админки",
    "schedule": "по расписанию",
    "startup":  "при запуске приложения",
}


def _labels(banks: Sequence[str]) -> str:
    return ", ".join(bank_label(b) for b in banks)


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
        events: EventSink = NULL_EVENTS,
    ):
        self.pool = pool
        self.notifier = notifier
        self.min_snapshot_ratio = min_snapshot_ratio
        self.snapshots_keep = snapshots_keep
        self.dashboard_url = dashboard_url
        self.proxy_source = proxy_source
        self.events = events
        self.status = ParseStatus(banks={b: BankStatus() for b in BANK_KEYS})
        self._lock = asyncio.Lock()
        # Banks whose last run failed — alerts fire only on transitions (in-memory:
        # after a restart a still-broken bank is reported once more).
        self._failing: frozenset[str] = frozenset()

    def _set_bank(self, bank: str, **changes) -> None:
        banks = {**self.status.banks, bank: replace(self.status.banks[bank], **changes)}
        self.status = replace(self.status, banks=banks)

    async def run_all(self, banks: tuple[str, ...] = BANK_KEYS, *, trigger: str = "manual") -> None:
        how = TRIGGERS.get(trigger, trigger)
        if self._lock.locked():
            logger.warning("Parse already running, skipping")
            await self.events.record(
                "warning", "parser",
                f"Парсинг уже идёт — повторный запуск ({how}) пропущен",
            )
            return
        async with self._lock:
            started = time.monotonic()
            await self.events.record("info", "parser", f"Парсинг запущен {how}: {_labels(banks)}")
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
            await self._record_summary(outcomes, time.monotonic() - started)
            await self._notify(outcomes)

    async def _record_summary(self, outcomes: dict[str, BankOutcome], seconds: float) -> None:
        failed = [b for b, o in outcomes.items() if o.error]
        ok = len(outcomes) - len(failed)
        message = (f"Парсинг завершён за {fmt_duration(seconds)}: "
                   f"успешно {ok} из {len(outcomes)}")
        if not failed:
            await self.events.record("success", "parser", message)
            return
        level = "error" if ok == 0 else "warning"
        await self.events.record(level, "parser", f"{message}; с ошибкой: {_labels(failed)}")

    async def _load_proxies(self) -> Optional[proxy.ProxyRotator]:
        if self.proxy_source is None:
            return None
        try:
            rotator = await self.proxy_source()
        except Exception as exc:   # proxies are an optimisation: never block the parse
            logger.exception("Could not load proxies, parsing directly")
            await self.events.record(
                "warning", "proxy",
                "Не удалось загрузить список прокси — банки опрашиваются напрямую",
                describe_error(exc),
            )
            return None
        if rotator:
            await self.events.record(
                "info", "proxy", f"Запросы к банкам идут через {len(rotator)} прокси")
        else:
            await self.events.record(
                "info", "proxy", "Запросы к банкам идут напрямую, без прокси")
        return rotator

    async def _run_bank_safe(self, bank: str) -> BankOutcome:
        label = bank_label(bank)
        started = time.monotonic()
        await self.events.record("info", "parser", f"{label}: начинаю сбор документации")
        try:
            changes = tuple(await self.run_bank(bank))
        except Exception as exc:
            logger.error("[%s] failed: %s", bank, exc, exc_info=True)
            error = _public_error(exc)
            self._set_bank(bank, status="error", error=error, finished_at=_now())
            rejected = isinstance(exc, SnapshotRejected)
            await self._record_bank_error(label, exc, rejected, time.monotonic() - started)
            return BankOutcome(error=error, rejected=rejected)
        st = self.status.banks[bank]
        await self.events.record(
            "success", "parser",
            f"{label}: готово за {fmt_duration(time.monotonic() - started)} — "
            f"{count(st.services, 'сервис', 'сервиса', 'сервисов')}, "
            f"{count(st.methods, 'метод', 'метода', 'методов')}, изменений: {len(changes)}",
        )
        return BankOutcome(changes=changes)

    async def _record_bank_error(self, label: str, exc: Exception, rejected: bool, seconds: float) -> None:
        if rejected:
            await self.events.record(
                "error", "parser",
                f"{label}: результат отклонён, старые данные сохранены",
                "Парсер вернул подозрительно мало данных по сравнению с прошлым разом — "
                "скорее всего, портал банка отдал неполную страницу. Новый снимок не записан.\n"
                + describe_error(exc),
            )
            return
        await self.events.record(
            "error", "parser",
            f"{label}: ошибка через {fmt_duration(seconds)}, данные банка не обновлены",
            describe_error(exc),
        )

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
            await self.events.record(
                "info", "telegram",
                "Telegram не настроен — сводки и уведомления не отправляются",
            )
            return

        try:
            digest = notify_format.build_digest(
                {b: o.changes for b, o in outcomes.items() if not o.error},
                when=datetime.now(timezone.utc), dashboard_url=self.dashboard_url,
            )
        except Exception as exc:   # a formatting bug must not also swallow the admin alerts
            logger.exception("Failed to build the change digest")
            await self.events.record(
                "error", "telegram", "Не удалось собрать сводку изменений для Telegram",
                describe_error(exc),
            )
            digest = None
        alerts = [
            *(notify_format.format_failure(b, outcomes[b].error or "", rejected=outcomes[b].rejected)
              for b in outcomes if b in newly_failed),
            *(notify_format.format_recovery(b) for b in outcomes if b in recovered),
        ]
        if digest:
            await self._safely(self.notifier.broadcast, digest, "сводку изменений")
        elif digest is not None:
            await self._record_no_digest(outcomes, failed)
        for alert in alerts:
            await self._safely(self.notifier.send_admin, alert, "уведомление администратору")

    async def _record_no_digest(self, outcomes: dict[str, BankOutcome], failed: frozenset[str]) -> None:
        if outcomes and failed == frozenset(outcomes):
            text = "Ни один банк не обработан — сводка в Telegram не отправляется"
        else:
            text = "Изменений нет — сводка в Telegram не отправляется"
        await self.events.record("info", "telegram", text)

    async def _safely(self, send: Callable[[Any], Awaitable[None]], payload: object, what: str) -> None:
        try:
            await send(payload)
        except Exception as exc:
            logger.warning("Telegram notification failed: %s", exc)
            await self.events.record(
                "error", "telegram", f"Не удалось отправить {what} в Telegram", describe_error(exc),
            )
