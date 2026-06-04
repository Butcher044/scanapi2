"""Telegram bot — subscribe/unsubscribe + change notifications."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import asyncpg
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app import repository as repo

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

BANK_LABELS = {
    "tbank":    "Т-Банк",
    "alfabank": "Альфа-Банк",
    "sber":     "Сбер",
    "tochka":   "Точка",
}

TYPE_LABELS = {
    "service": "Сервис",
    "method":  "Метод",
    "field":   "Поле",
}

ACTION_LABELS = {
    "added":    ("🟢", "Добавлен"),
    "removed":  ("🔴", "Удалён"),
    "modified": ("🟡", "Изменён"),
}


def _format_change(change: dict) -> str:
    bank  = BANK_LABELS.get(change["bank"], change["bank"])
    cat   = TYPE_LABELS.get(change.get("change_type", ""), "")
    emoji, action = ACTION_LABELS.get(change.get("change_action", ""), ("⚪", change.get("change_action", "")))

    text = f"{emoji} *{action}* — {bank}\n"
    text += f"_Категория:_ {cat}\n"
    text += f"_Название:_ `{change.get('entity_name', '')}`\n"

    if change.get("old_value") or change.get("new_value"):
        text += "_Изменение:_\n"
        if change.get("old_value"):
            text += f"Было: {change['old_value']}\n"
        if change.get("new_value"):
            text += f"Стало: {change['new_value']}\n"

    if url := change.get("url"):
        text += f"\n[Ссылка на документацию]({url})"

    return text


class TelegramBot:
    def __init__(self, token: str, pool: asyncpg.Pool):
        self._token = token
        self._pool = pool
        self._app: Application | None = None

    async def start(self) -> None:
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("stop",  self._cmd_stop))
        self._app.add_handler(CommandHandler("help",  self._cmd_help))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram bot started polling")

    async def stop(self) -> None:
        if self._app:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            logger.info("Telegram bot stopped")

    async def notify_change(self, change: dict) -> None:
        if not self._app:
            return
        text = _format_change(change)
        async with self._pool.acquire() as conn:
            subscribers = await repo.get_subscribers(conn)
        for sub in subscribers:
            try:
                await self._app.bot.send_message(
                    chat_id=sub["chat_id"],
                    text=text,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                )
            except Exception as exc:
                logger.warning("Notify failed for %s: %s", sub["chat_id"], exc)

    # ── Command handlers ──────────────────────────────────────────────────────

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        chat_id = update.effective_chat.id
        username = user.username if user else ""
        async with self._pool.acquire() as conn:
            await repo.add_subscriber(conn, chat_id, username or "")
        await update.message.reply_text(
            "✅ Вы подписались на уведомления об изменениях API банков!\n"
            "Используйте /stop чтобы отписаться."
        )

    async def _cmd_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        async with self._pool.acquire() as conn:
            await repo.remove_subscriber(conn, update.effective_chat.id)
        await update.message.reply_text("❎ Вы отписались от уведомлений.")

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(
            "📋 *Команды:*\n"
            "/start — Подписаться на уведомления\n"
            "/stop — Отписаться от уведомлений\n"
            "/help — Показать справку",
            parse_mode="Markdown",
        )
