"""Telegram messages (HTML parse mode): change digest, admin alerts, /status.

Pure functions — no I/O, so the whole format is unit-tested offline.
Every piece of text that comes from bank documentation is HTML-escaped.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from typing import TYPE_CHECKING, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from app.banks import BANK_KEYS, bank_label
from app.diff import Change
from app.proxies import days_left
from bank_api_parser.proxy import mask

if TYPE_CHECKING:
    from app.parser_runner import BankStatus, ParseStatus

TG_LIMIT = 4096            # Telegram hard limit for one message
MAX_LINES_PER_BANK = 10    # longer lists end with "…and N more"
BULK_THRESHOLD = 30        # more changes than this: counts only (docs were restructured)
MAX_FIELDS_SHOWN = 5
MAX_ERROR_CHARS = 400
MAX_NAME_CHARS = 200       # bank-supplied names/URLs are capped so one line never nears TG_LIMIT
MAX_URL_CHARS = 500

MSK = ZoneInfo("Europe/Moscow")
_EMOJI = {"added": "🟢", "removed": "🔴", "modified": "🟡"}
_ORDER = {("service", "added"): 0, ("service", "removed"): 1,
          ("method", "added"): 2, ("method", "removed"): 3, ("field", "modified"): 4}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _e(text: str) -> str:
    return escape(text or "", quote=True)


def _clip(text: str, limit: int = MAX_NAME_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _link(url: str, title: str) -> str:
    """Only http(s) links; anything else (javascript:, relative, oversized) is dropped."""
    if not url.startswith(("https://", "http://")) or len(url) > MAX_URL_CHARS:
        return ""
    return f'<a href="{_e(url)}">{_e(title)}</a>'


def _with_link(text: str, url: str) -> str:
    link = _link(url, "док")
    return f"{text} · {link}" if link else text


def _service_of(change: Change) -> str:
    return change.entity_path.split(" / ", 1)[0] if " / " in change.entity_path else ""


def _field_diff(change: Change) -> str:
    added = [f.strip() for f in change.new_value.split(",") if f.strip()]
    removed = [f"−{f.strip().lstrip('-')}" for f in change.old_value.split(",") if f.strip()]
    items = added + removed
    shown = ", ".join(items[:MAX_FIELDS_SHOWN])
    extra = len(items) - MAX_FIELDS_SHOWN
    return _clip(f"{shown} … (+{extra})" if extra > 0 else shown, MAX_NAME_CHARS * 2)


# ── Digest ────────────────────────────────────────────────────────────────────

def _change_line(c: Change) -> str:
    emoji = _EMOJI.get(c.action, "⚪")
    if c.change_type == "service":
        return _with_link(f"{emoji} Сервис «{_e(_clip(c.entity_name))}»", c.url)
    name = _e(_clip(c.entity_name))
    if c.change_type == "field":
        return f"{emoji} <code>{name}</code>: {_e(_field_diff(c))}"
    service = _clip(_service_of(c))
    text = f"{emoji} <code>{name}</code>" + (f" · {_e(service)}" if service else "")
    return _with_link(text, c.url)


def _counts(changes: Sequence[Change]) -> str:
    def n(kind: str, action: str) -> int:
        return sum(1 for c in changes if c.change_type == kind and c.action == action)

    parts = []
    for kind, label in (("service", "сервисы"), ("method", "методы")):
        plus, minus = n(kind, "added"), n(kind, "removed")
        if plus or minus:
            parts.append(" ".join([label, *([f"+{plus}"] if plus else []), *([f"−{minus}"] if minus else [])]))
    if fields := n("field", "modified"):
        parts.append(f"поля изменены: {fields}")
    return " · ".join(parts)


def _bank_block(bank: str, changes: Sequence[Change], dashboard_url: str) -> list[str]:
    head = f"🏦 <b>{_e(bank_label(bank))}</b>: {_counts(changes)}"
    if len(changes) > BULK_THRESHOLD:
        note = "Слишком много изменений разом — похоже на переработку документации."
        more = _link(f"{dashboard_url}/changes", "Подробности в дашборде") if dashboard_url else ""
        return [head, note, *([more] if more else [])]

    ordered = sorted(changes, key=lambda c: _ORDER.get((c.change_type, c.action), 9))
    lines = [head, *(_change_line(c) for c in ordered[:MAX_LINES_PER_BANK])]
    rest = len(ordered) - MAX_LINES_PER_BANK
    if rest > 0:
        where = _link(f"{dashboard_url}/changes", "в дашборде") if dashboard_url else "в дашборде"
        lines.append(f"…и ещё {rest} — {where}")
    return lines


def _pack(blocks: list[list[str]], limit: int) -> list[str]:
    """Greedy packing into messages ≤ limit.

    Blocks are separated by a blank line; a block that alone exceeds the limit
    is split between its lines.
    """
    messages: list[str] = []
    current = ""

    def add(piece: str, sep: str) -> None:
        nonlocal current
        candidate = f"{current}{sep}{piece}" if current else piece
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                messages.append(current)
            current = piece[:limit]

    for block in blocks:
        text = "\n".join(block)
        if len(text) <= limit:
            add(text, "\n\n")
        else:
            add(block[0], "\n\n")
            for line in block[1:]:
                add(line, "\n")
    return [*messages, current] if current else messages


def build_digest(
    changes_by_bank: Mapping[str, Sequence[Change]],
    *,
    when: datetime,
    dashboard_url: str = "",
) -> list[str]:
    """Messages for one parse run; [] when nothing changed."""
    banks = [b for b in BANK_KEYS if changes_by_bank.get(b)]
    banks += [b for b in changes_by_bank if b not in BANK_KEYS and changes_by_bank[b]]
    if not banks:
        return []
    header = f"📡 <b>Изменения API банков</b> — {when.astimezone(MSK):%d.%m, %H:%M} МСК"
    blocks = [[header], *(_bank_block(b, changes_by_bank[b], dashboard_url.rstrip("/")) for b in banks)]
    return _pack(blocks, TG_LIMIT)


# ── Admin alerts ──────────────────────────────────────────────────────────────

def format_failure(bank: str, error: str, *, rejected: bool) -> str:
    reason = "снимок отклонён (резко меньше методов, чем в прошлый раз)" if rejected else "разбор не удался"
    detail = _clip(error, MAX_ERROR_CHARS)
    return (
        f"⚠️ <b>{_e(bank_label(bank))}</b>: {reason}\n"
        f"<code>{_e(detail)}</code>\n"
        "В дашборде остаются данные прошлого успешного разбора."
    )


def format_recovery(bank: str) -> str:
    return f"✅ <b>{_e(bank_label(bank))}</b>: разбор снова проходит"


# ── /status ───────────────────────────────────────────────────────────────────

def _plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _bank_status_line(bank: str, st: BankStatus) -> str:
    label = _e(bank_label(bank))
    if st.status == "done":
        return (f"✅ {label} — {st.services} {_plural(st.services, 'сервис', 'сервиса', 'сервисов')}, "
                f"{st.methods} {_plural(st.methods, 'метод', 'метода', 'методов')}, изменений: {st.changes}")
    if st.status == "error":
        return f"❌ {label} — {_e(_clip(st.error or 'ошибка', MAX_ERROR_CHARS))}"
    if st.status == "running":
        return f"⏳ {label} — идёт разбор"
    return f"▫️ {label} — не запускался"


def format_status(status: Optional[ParseStatus]) -> str:
    if status is None or (not status.running and not status.finished_at):
        return "Разбор ещё не запускался."
    head = (f"⏳ Разбор идёт с {status.started_at}" if status.running
            else f"Последний разбор: {status.finished_at}")
    return "\n".join([head, *(_bank_status_line(b, st) for b, st in status.banks.items())])


MAX_PROXIES_LISTED = 30


def _proxy_line(row: Mapping, now: datetime) -> str:
    left = days_left(row["expires_at"], now)
    when = row["expires_at"].astimezone(MSK).strftime("%d.%m.%Y")
    state = "истёк" if left is not None and left < 0 else f"истекает {when}"
    label = f" ({_e(_clip(row['label'], 60))})" if row.get("label") else ""
    return f"• <code>{_e(_clip(mask(row['url']), 120))}</code>{label} — {state}"


def format_proxy_expiry(rows: Sequence[Mapping], now: datetime) -> str:
    lines = [_proxy_line(r, now) for r in rows[:MAX_PROXIES_LISTED]]
    more = len(rows) - MAX_PROXIES_LISTED
    tail = [f"…и ещё {more}"] if more > 0 else []
    return "\n".join(["⏳ <b>Прокси скоро истекают</b>", *lines, *tail,
                      "Продлите или замените их в «Настройках»."])
