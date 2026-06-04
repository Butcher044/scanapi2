"""APScheduler cron job — runs parser at configured time (Moscow TZ)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from app.parser_runner import ParserRunner

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, runner: "ParserRunner", scheduler_time: str = "10:00"):
        self._runner = runner
        self._scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

        try:
            hour, minute = scheduler_time.strip().split(":")
        except ValueError:
            logger.error("Bad scheduler_time format: %r — using 10:00", scheduler_time)
            hour, minute = "10", "00"

        self._scheduler.add_job(
            self._run,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="Europe/Moscow"),
            id="parse_all",
            name="Parse all banks",
            replace_existing=True,
        )
        logger.info("Scheduler configured: %s:%s MSK", hour, minute)

    async def _run(self) -> None:
        logger.info("Scheduled parse starting")
        try:
            await self._runner.run_all()
        except Exception as exc:
            logger.error("Scheduled parse error: %s", exc, exc_info=True)

    def start(self) -> None:
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
