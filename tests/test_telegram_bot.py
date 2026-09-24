"""TelegramBot delivery: fan-out, retries, auto-unsubscribe, admin alerts, /status (offline)."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut

from app import telegram_bot as tb
from app.parser_runner import BankStatus, ParseStatus


class FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield object()


class FakeBot:
    """Records sent messages; `errors[chat_id]` is a list of exceptions raised in order."""

    def __init__(self, errors=None):
        self.sent, self.errors = [], {k: list(v) for k, v in (errors or {}).items()}

    async def send_message(self, chat_id, text, **kwargs):
        pending = self.errors.get(chat_id)
        if pending:
            raise pending.pop(0)
        self.sent.append((chat_id, text, kwargs))


@pytest.fixture
def env(monkeypatch):
    state = {"subscribers": [], "removed": [], "sleeps": []}

    async def get_subscribers(conn):
        return [{"id": i, "chat_id": c, "username": ""} for i, c in enumerate(state["subscribers"])]

    async def remove_subscriber(conn, chat_id):
        state["removed"].append(chat_id)

    async def fake_sleep(seconds):
        state["sleeps"].append(seconds)

    monkeypatch.setattr(tb.repo, "get_subscribers", get_subscribers)
    monkeypatch.setattr(tb.repo, "remove_subscriber", remove_subscriber)
    monkeypatch.setattr(tb, "_sleep", fake_sleep)
    return state


def make_bot(fake, **kwargs):
    bot = tb.TelegramBot("token", FakePool(), **kwargs)
    bot._app = SimpleNamespace(bot=fake)
    return bot


def test_broadcast_reaches_subscribers_and_fixed_chat_once(env):
    env["subscribers"] = [1, 2, -100]
    fake = FakeBot()
    asyncio.run(make_bot(fake, fixed_chat_id=-100).broadcast(["p1", "p2"]))

    by_chat = {}
    for chat, text, kwargs in fake.sent:
        by_chat.setdefault(chat, []).append(text)
        assert kwargs["parse_mode"] == "HTML"
        assert kwargs["disable_web_page_preview"] is True
    assert by_chat == {1: ["p1", "p2"], 2: ["p1", "p2"], -100: ["p1", "p2"]}


def test_broadcast_without_subscribers_goes_to_fixed_chat(env):
    fake = FakeBot()
    asyncio.run(make_bot(fake, fixed_chat_id=-100).broadcast(["hi"]))
    assert [(c, t) for c, t, _ in fake.sent] == [(-100, "hi")]


def test_blocked_subscriber_is_removed_but_fixed_chat_never(env):
    env["subscribers"] = [1, 2]
    fake = FakeBot({1: [Forbidden("bot was blocked by the user")],
                    -100: [Forbidden("bot was kicked")]})
    asyncio.run(make_bot(fake, fixed_chat_id=-100).broadcast(["a", "b"]))
    assert env["removed"] == [1]
    assert [c for c, _, _ in fake.sent] == [2, 2]   # blocked chats get no further parts


def test_retry_after_is_honoured(env):
    env["subscribers"] = [1]
    fake = FakeBot({1: [RetryAfter(7)]})
    asyncio.run(make_bot(fake).broadcast(["a"]))
    assert 7 in env["sleeps"]
    assert [(c, t) for c, t, _ in fake.sent] == [(1, "a")]


def test_network_errors_retry_then_give_up(env):
    env["subscribers"] = [1, 2]
    fake = FakeBot({1: [TimedOut()] * 5})
    asyncio.run(make_bot(fake).broadcast(["a"]))
    assert [c for c, _, _ in fake.sent] == [2]      # chat 1 gave up, chat 2 still served
    assert env["removed"] == []


def test_bad_request_is_not_retried(env):
    env["subscribers"] = [1]
    fake = FakeBot({1: [BadRequest("can't parse entities"), None]})
    asyncio.run(make_bot(fake).broadcast(["a"]))
    assert fake.sent == [] and env["removed"] == []


def test_send_admin(env):
    fake = FakeBot()
    asyncio.run(make_bot(fake, admin_chat_id=42).send_admin("⚠️ alert"))
    assert [(c, t) for c, t, _ in fake.sent] == [(42, "⚠️ alert")]

    silent = FakeBot()
    asyncio.run(make_bot(silent).send_admin("⚠️ alert"))   # no admin chat configured: only logged
    assert silent.sent == []


def test_not_started_bot_is_a_noop(env):
    env["subscribers"] = [1]
    bot = tb.TelegramBot("token", FakePool(), fixed_chat_id=-100, admin_chat_id=42)
    asyncio.run(bot.broadcast(["a"]))
    asyncio.run(bot.send_admin("x"))                 # must not raise


def test_status_command_replies_with_current_status(env):
    status = ParseStatus(finished_at="2026-09-22 09:49:58 UTC",
                         banks={"tbank": BankStatus(status="done", services=1, methods=2)})
    replies = []

    async def reply_text(text, **kwargs):
        replies.append((text, kwargs))

    update = SimpleNamespace(message=SimpleNamespace(reply_text=reply_text))
    bot = make_bot(FakeBot(), status_provider=lambda: status)
    asyncio.run(bot._cmd_status(update, None))

    [(text, kwargs)] = replies
    assert "Последний разбор: 2026-09-22 09:49:58 UTC" in text and "Т-Банк" in text
    assert kwargs["parse_mode"] == "HTML"


def test_no_sleep_after_the_last_attempt(env):
    env["subscribers"] = [1]
    asyncio.run(make_bot(FakeBot({1: [TimedOut()] * 3})).broadcast(["a"]))
    assert env["sleeps"] == [tb.BACKOFF_BASE, tb.BACKOFF_BASE * 2]
