"""Telegram bot: /start, /stop, /status, /help + delivery of digests and admin alerts.

Recipients of the change digest: every /start subscriber plus an optional fixed
chat/group (TELEGRAM_CHAT_ID). Parse failures go only to TELEGRAM_ADMIN_CHAT.
Messages are pre-formatted HTML from app.notify_format.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Callable, Optional, Sequence

import asyncpg
from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter
from telegram.ext import Application, CommandHandler, ContextTypes

from app import repository as repo
from app.notify_format import format_status

if TYPE_CHECKING:
    from app.parser_runner import ParseStatus

logger = logging.getLogger(__name__)

SEND_ATTEMPTS = 3
PART_PAUSE = 1.0       # seconds between parts of one digest to the same chat
BACKOFF_BASE = 2.0     # network error backoff: 2s, 4s
_sleep = asyncio.sleep  # patched in tests

_HELP = (
    "📋 <b>Команды</b>\n"
    "/start — подписаться на изменения API банков\n"
    "/stop — отписаться\n"
    "/status — состояние последнего разбора\n"
    "/help — эта справка"
)


def _seconds(delay: object) -> float:
    return delay.total_seconds() if isinstance(delay, timedelta) else float(delay)


class TelegramBot:
    def __init__(
        self,
        token: str,
        pool: asyncpg.Pool,
        *,
        fixed_chat_id: Optional[int] = None,
        admin_chat_id: Optional[int] = None,
        status_provider: Callable[[], Optional["ParseStatus"]] = lambda: None,
    ):
        self._token = token
        self._pool = pool
        self._fixed_chat_id = fixed_chat_id
        self._admin_chat_id = admin_chat_id
        self._status = status_provider
        self._app: Application | None = None

    async def start(self) -> None:
        self._app = Application.builder().token(self._token).build()
        for name, handler in (("start", self._cmd_start), ("stop", self._cmd_stop),
                              ("status", self._cmd_status), ("help", self._cmd_help)):
            self._app.add_handler(CommandHandler(name, handler))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram bot started polling")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None
            logger.info("Telegram bot stopped")

    # ── Delivery ──────────────────────────────────────────────────────────────

    async def broadcast(self, texts: Sequence[str]) -> None:
        """Send every part of the digest to each subscriber and the fixed chat."""
        if not self._app or not texts:
            return
        async with self._pool.acquire() as conn:
            subscribers = await repo.get_subscribers(conn)
        fixed = [self._fixed_chat_id] if self._fixed_chat_id is not None else []
        chats = list(dict.fromkeys([*(s["chat_id"] for s in subscribers), *fixed]))

        for chat_id in chats:
            for i, text in enumerate(texts):
                if i:
                    await _sleep(PART_PAUSE)
                if not await self._send(chat_id, text):
                    break   # the rest of the digest would fail the same way
        logger.info("Digest (%d parts) sent to %d chats", len(texts), len(chats))

    async def send_admin(self, text: str) -> None:
        if not self._app:
            return
        if self._admin_chat_id is None:
            logger.warning("TELEGRAM_ADMIN_CHAT is not set, admin alert not sent: %s", text)
            return
        await self._send(self._admin_chat_id, text)

    async def _send(self, chat_id: int, text: str) -> bool:
        for attempt in range(SEND_ATTEMPTS):
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id, text=text,
                    parse_mode="HTML", disable_web_page_preview=True,
                )
                return True
            except RetryAfter as exc:
                if attempt + 1 < SEND_ATTEMPTS:
                    await _sleep(_seconds(exc.retry_after))
            except Forbidden as exc:
                await self._drop_chat(chat_id, exc)
                return False
            except BadRequest as exc:   # malformed message / chat not found: retrying won't help
                logger.warning("Telegram rejected message to %s: %s", chat_id, exc)
                return False
            except NetworkError as exc:  # includes TimedOut
                logger.warning("Telegram network error for %s (attempt %d): %s", chat_id, attempt + 1, exc)
                if attempt + 1 < SEND_ATTEMPTS:
                    await _sleep(BACKOFF_BASE * 2 ** attempt)
            except Exception:
                logger.exception("Unexpected error sending to %s", chat_id)
                return False
        logger.warning("Giving up on chat %s after %d attempts", chat_id, SEND_ATTEMPTS)
        return False

    async def _drop_chat(self, chat_id: int, exc: Exception) -> None:
        if chat_id in (self._fixed_chat_id, self._admin_chat_id):
            logger.error("Bot has no access to configured chat %s: %s", chat_id, exc)
            return
        logger.info("Chat %s blocked the bot, unsubscribing: %s", chat_id, exc)
        async with self._pool.acquire() as conn:
            await repo.remove_subscriber(conn, chat_id)

    # ── Command handlers ──────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        async with self._pool.acquire() as conn:
            await repo.add_subscriber(conn, update.effective_chat.id, (user.username if user else "") or "")
        await update.message.reply_text(
            "✅ Вы подписались на изменения API банков.\n"
            "Раз в день после разбора пришлю сводку — только если что-то изменилось.\n"
            "/status — состояние разбора, /stop — отписаться."
        )

    async def _cmd_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        async with self._pool.acquire() as conn:
            await repo.remove_subscriber(conn, update.effective_chat.id)
        await update.message.reply_text("❎ Вы отписались от уведомлений.")

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(format_status(self._status()), parse_mode="HTML")

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(_HELP, parse_mode="HTML")
