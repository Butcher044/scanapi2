"""APScheduler cron jobs (Moscow TZ): the daily parse and optional extra daily jobs."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from app.parser_runner import ParserRunner

logger = logging.getLogger(__name__)

TZ = "Europe/Moscow"
DEFAULT_TIME = "10:00"
_PARSE_JOB = "parse_all"
_TIME_RE = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def parse_time(text: str) -> tuple[int, int]:
    """"HH:MM" (24h) -> (hour, minute); ValueError otherwise."""
    match = _TIME_RE.fullmatch(text.strip())
    if not match:
        raise ValueError(f"время должно быть в формате ЧЧ:ММ, получено {text!r}")
    return int(match[1]), int(match[2])


def _trigger(hour: int, minute: int) -> CronTrigger:
    return CronTrigger(hour=hour, minute=minute, timezone=TZ)


class Scheduler:
    def __init__(self, runner: "ParserRunner", scheduler_time: str = DEFAULT_TIME):
        self._runner = runner
        self._scheduler = AsyncIOScheduler(timezone=TZ)
        try:
            hour, minute = parse_time(scheduler_time)
        except ValueError:
            logger.error("Bad scheduler_time %r — using %s", scheduler_time, DEFAULT_TIME)
            hour, minute = parse_time(DEFAULT_TIME)
        self._hour, self._minute = hour, minute
        self._scheduler.add_job(
            self._run, trigger=_trigger(hour, minute),
            id=_PARSE_JOB, name="Parse all banks", replace_existing=True,
        )
        logger.info("Scheduler configured: %s MSK", self.time)

    @property
    def time(self) -> str:
        return f"{self._hour:02d}:{self._minute:02d}"

    def reschedule(self, scheduler_time: str) -> None:
        """Move the daily parse; takes effect immediately (raises ValueError on bad input)."""
        hour, minute = parse_time(scheduler_time)
        self._scheduler.reschedule_job(_PARSE_JOB, trigger=_trigger(hour, minute))
        self._hour, self._minute = hour, minute
        logger.info("Daily parse rescheduled to %s MSK", self.time)

    def next_run(self) -> Optional[datetime]:
        job = self._scheduler.get_job(_PARSE_JOB)
        return job.trigger.get_next_fire_time(None, datetime.now(job.trigger.timezone)) if job else None

    def add_daily(self, job_id: str, func: Callable[[], Awaitable[None]], scheduler_time: str) -> None:
        hour, minute = parse_time(scheduler_time)
        self._scheduler.add_job(func, trigger=_trigger(hour, minute), id=job_id, replace_existing=True)

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
