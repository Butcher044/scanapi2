"""
Runs the bank parsers and imports results into PostgreSQL.
Imports parsers directly (no subprocess) — cleaner and faster.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import asyncpg

from app import repository as repo

if TYPE_CHECKING:
    from app.telegram_bot import TelegramBot

logger = logging.getLogger(__name__)

_PARSER_DIR = Path(__file__).parent.parent / "bank_api_parser"
if str(_PARSER_DIR) not in sys.path:
    sys.path.insert(0, str(_PARSER_DIR))

BANK_KEYS = ("tbank", "tochka", "alfabank", "sber")

BANK_LABELS = {
    "tbank":    "Т-Банк",
    "tochka":   "Точка",
    "alfabank": "Альфа-Банк",
    "sber":     "Сбер",
}


# ── Status tracking ───────────────────────────────────────────────────────────

@dataclass
class BankStatus:
    status: str = "pending"   # pending | running | done | error
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    services: int = 0
    methods: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "status":      self.status,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "services":    self.services,
            "methods":     self.methods,
            "error":       self.error,
        }


@dataclass
class ParseStatus:
    running: bool = False
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    banks: dict = field(default_factory=lambda: {b: BankStatus() for b in BANK_KEYS})

    def to_dict(self) -> dict:
        return {
            "running":     self.running,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "banks": {k: v.to_dict() for k, v in self.banks.items()},
        }

    def reset(self) -> None:
        now = _now()
        self.running = True
        self.started_at = now
        self.finished_at = None
        self.banks = {b: BankStatus() for b in BANK_KEYS}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _get_parser_class(bank: str):
    if bank == "tbank":
        from parsers.tbank_parser import TBankParser
        return TBankParser
    elif bank == "tochka":
        from parsers.tochka_parser import TochkaParser
        return TochkaParser
    elif bank == "alfabank":
        from parsers.alfabank_parser import AlfaBankParser
        return AlfaBankParser
    elif bank == "sber":
        from parsers.sber_parser import SberParser
        return SberParser
    raise ValueError(f"Unknown bank: {bank}")


# ── Runner ────────────────────────────────────────────────────────────────────

class ParserRunner:
    def __init__(self, pool: asyncpg.Pool, telegram: "TelegramBot | None" = None):
        self.pool = pool
        self.telegram = telegram
        self.status = ParseStatus()

    async def run_all(self, banks: tuple[str, ...] = BANK_KEYS) -> None:
        if self.status.running:
            logger.warning("Parse already running, skipping")
            return

        self.status.reset()
        logger.info("Parse started: %s", list(banks))

        try:
            for bank in banks:
                try:
                    await self.run_bank(bank)
                except Exception as exc:
                    logger.error("Bank %s failed: %s", bank, exc, exc_info=True)
                    self.status.banks[bank].status = "error"
                    self.status.banks[bank].error = str(exc)
                    self.status.banks[bank].finished_at = _now()
        finally:
            self.status.running = False
            self.status.finished_at = _now()
            done = sum(1 for b in self.status.banks.values() if b.status == "done")
            errors = sum(1 for b in self.status.banks.values() if b.status == "error")
            logger.info("Parse finished: %d done, %d errors", done, errors)

    async def run_bank(self, bank: str) -> None:
        bs = self.status.banks[bank]
        bs.status = "running"
        bs.started_at = _now()
        logger.info("[%s] Starting parse", bank)

        ParserClass = _get_parser_class(bank)
        parser = ParserClass()

        loop = asyncio.get_event_loop()
        snapshot = await loop.run_in_executor(None, parser.parse)

        if snapshot is None:
            bs.status = "error"
            bs.error = "Parser returned None"
            bs.finished_at = _now()
            logger.error("[%s] Parser returned None", bank)
            return

        logger.info("[%s] Parsed: %d services, %d methods", bank, snapshot.total_services, snapshot.total_methods)
        await self._import_snapshot(bank, snapshot)

        bs.status = "done"
        bs.services = snapshot.total_services
        bs.methods = snapshot.total_methods
        bs.finished_at = _now()
        logger.info("[%s] Done: %d services, %d methods", bank, bs.services, bs.methods)

    # ── DB import ─────────────────────────────────────────────────────────────

    async def _import_snapshot(self, bank: str, snapshot) -> None:
        async with self.pool.acquire() as conn:
            prev = await repo.get_latest_snapshot(conn, bank)
            snap_id = await repo.create_snapshot(conn, bank)

            prev_services: dict[str, dict] = {}
            if prev:
                for svc in await repo.get_services(conn, prev["id"]):
                    prev_services[svc["name"]] = svc

            for svc_name, methods in snapshot.services.items():
                svc_url = methods[0].url_on_portal if methods else ""
                svc_id = await repo.create_service(conn, snap_id, svc_name, svc_url)

                if prev and svc_name not in prev_services:
                    await self._save_change(conn, snap_id, bank, "service", "added",
                                            svc_name, svc_name, svc_url)

                for method in methods:
                    method_id = await repo.create_method(
                        conn, svc_id,
                        name=method.summary,
                        http_method=method.http_method,
                        url=method.url_on_portal,
                        description=method.description,
                        path=method.path,
                        request_example=getattr(method, "request_example", {}),
                        response_example=getattr(method, "response_example", {}),
                    )
                    for field_name in (method.response_200_fields or []):
                        try:
                            await repo.create_field(conn, method_id, field_name, "string", False, "")
                        except Exception:
                            pass

            if prev:
                for svc_name, svc in prev_services.items():
                    if svc_name not in snapshot.services:
                        await self._save_change(conn, snap_id, bank, "service", "removed",
                                                svc_name, svc_name, svc["url"])

            if prev:
                await self._diff_methods(conn, snap_id, bank, prev["id"])

            old_ids = await repo.get_snapshots_for_cleanup(conn, bank, keep=7)
            if old_ids:
                await repo.delete_snapshots(conn, old_ids)

    async def _diff_methods(self, conn, new_snap_id, bank, prev_snap_id):
        prev_methods = await repo.get_all_methods_for_snapshot(conn, prev_snap_id)
        new_methods  = await repo.get_all_methods_for_snapshot(conn, new_snap_id)

        prev_map = {f"{m['http_method']}:{m['path']}": m for m in prev_methods if m["path"]}
        new_map  = {f"{m['http_method']}:{m['path']}": m for m in new_methods  if m["path"]}

        for key, m in new_map.items():
            if key not in prev_map:
                await self._save_change(conn, new_snap_id, bank, "method", "added",
                                        f"{m['http_method']} {m['path']}",
                                        f"{m['service_name']} / {m['http_method']} {m['path']}", m["url"])

        for key, m in prev_map.items():
            if key not in new_map:
                await self._save_change(conn, new_snap_id, bank, "method", "removed",
                                        f"{m['http_method']} {m['path']}",
                                        f"{m['service_name']} / {m['http_method']} {m['path']}", m["url"])

        for key in set(new_map) & set(prev_map):
            old_m, new_m = prev_map[key], new_map[key]
            old_fields = [f["name"] for f in await repo.get_fields(conn, old_m["id"])]
            new_fields = [f["name"] for f in await repo.get_fields(conn, new_m["id"])]
            added   = sorted(set(new_fields) - set(old_fields))
            removed = sorted(set(old_fields) - set(new_fields))
            if added or removed:
                await self._save_change(conn, new_snap_id, bank, "field", "modified",
                                        f"{new_m['http_method']} {new_m['path']}",
                                        f"{new_m['service_name']} / {new_m['http_method']} {new_m['path']}",
                                        new_m["url"],
                                        old_value=", ".join(f"-{f}" for f in removed),
                                        new_value=", ".join(f"+{f}" for f in added))

    async def _field_names(self, conn, method_id):
        return [f["name"] for f in await repo.get_fields(conn, method_id)]

    async def _save_change(self, conn, snap_id, bank, change_type, action,
                           entity_name, entity_path, url="", old_value="", new_value=""):
        await repo.create_change(conn,
            snapshot_id=snap_id, bank=bank,
            change_type=change_type, change_action=action,
            entity_name=entity_name, entity_path=entity_path,
            url=url, old_value=old_value, new_value=new_value)

        if self.telegram:
            await self.telegram.notify_change({
                "bank": bank, "change_type": change_type, "change_action": action,
                "entity_name": entity_name, "entity_path": entity_path,
                "url": url, "old_value": old_value, "new_value": new_value,
            })
