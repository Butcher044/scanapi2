"""Telegram message formatting: digest, alerts, /status (pure functions, offline)."""
from datetime import datetime, timezone

from app import notify_format as nf
from app.diff import Change
from app.parser_runner import BankStatus, ParseStatus

WHEN = datetime(2026, 9, 23, 7, 7, tzinfo=timezone.utc)  # 10:07 MSK


def _m(action, key, service="Счета", url="https://dev.bank/doc"):
    return Change("method", action, key, f"{service} / {key}", url)


def _digest(changes_by_bank, **kw):
    return nf.build_digest(changes_by_bank, when=WHEN, **kw)


def test_no_changes_means_no_message():
    assert _digest({}) == []
    assert _digest({"tbank": [], "sber": []}) == []


def test_digest_header_summary_and_lines():
    [text] = _digest({"tbank": [
        _m("added", "POST /v1/qr"),
        _m("removed", "DELETE /v1/old"),
        Change("service", "added", "Самозанятые", "Самозанятые", "https://dev.bank/se"),
        Change("field", "modified", "GET /v1/company", "Счета / GET /v1/company", "",
               old_value="-legacyId", new_value="+kpp2"),
    ]})
    assert text.startswith("📡 <b>Изменения API банков</b> — 23.09, 10:07 МСК")
    assert "🏦 <b>Т-Банк</b>: сервисы +1 · методы +1 −1 · поля изменены: 1" in text
    assert '🟢 Сервис «Самозанятые» · <a href="https://dev.bank/se">док</a>' in text
    assert '🟢 <code>POST /v1/qr</code> · Счета · <a href="https://dev.bank/doc">док</a>' in text
    assert "🔴 <code>DELETE /v1/old</code> · Счета" in text
    assert "🟡 <code>GET /v1/company</code>: +kpp2, −legacyId" in text
    # services first, then added, removed, field changes
    assert text.index("Самозанятые") < text.index("POST /v1/qr") < text.index("DELETE") < text.index("company")


def test_banks_follow_fixed_order_and_skip_empty():
    [text] = _digest({"sber": [_m("added", "GET /s")], "tochka": [], "tbank": [_m("added", "GET /t")]})
    assert text.index("Т-Банк") < text.index("Сбер")
    assert "Точка" not in text


def test_long_bank_list_is_truncated_with_dashboard_link():
    changes = [_m("added", f"GET /v1/m{i:02d}") for i in range(14)]
    [text] = _digest({"tbank": changes}, dashboard_url="https://mon.example")
    assert text.count("🟢 <code>") == nf.MAX_LINES_PER_BANK
    assert '…и ещё 4 — <a href="https://mon.example/changes">в дашборде</a>' in text


def test_truncation_without_dashboard_url_has_no_link():
    changes = [_m("added", f"GET /v1/m{i:02d}") for i in range(12)]
    [text] = _digest({"tbank": changes})
    assert "…и ещё 2" in text and "href=\"/changes\"" not in text


def test_bulk_change_shows_only_counts():
    changes = [_m("removed", f"GET /v1/m{i}") for i in range(nf.BULK_THRESHOLD + 1)]
    [text] = _digest({"alfabank": changes})
    assert f"методы −{nf.BULK_THRESHOLD + 1}" in text
    assert "<code>" not in text
    assert "переработ" in text


def test_dynamic_text_is_html_escaped_and_bad_urls_dropped():
    [text] = _digest({"tbank": [
        Change("method", "added", "GET /a<b>&c", "S<x> / GET /a<b>&c", "javascript:alert(1)"),
        Change("service", "added", 'Q"<i>', 'Q"<i>', 'https://x/?a="b"'),
    ]})
    assert "<code>GET /a&lt;b&gt;&amp;c</code> · S&lt;x&gt;" in text
    assert "javascript" not in text
    assert "«Q&quot;&lt;i&gt;»" in text
    assert 'href="https://x/?a=&quot;b&quot;"' in text


def test_many_field_changes_are_shortened():
    added = ", ".join(f"+f{i}" for i in range(20))
    [text] = _digest({"tbank": [Change("field", "modified", "GET /x", "S / GET /x", "", "", added)]})
    assert "+f0, +f1, +f2, +f3, +f4 … (+15)" in text


def test_digest_is_split_under_telegram_limit():
    long_service = "С" * 300
    by_bank = {b: [_m("added", f"GET /{b}/{i}", service=long_service) for i in range(10)]
               for b in ("tbank", "tochka", "alfabank", "sber")}
    parts = _digest(by_bank)
    assert len(parts) > 1
    assert all(len(p) <= nf.TG_LIMIT for p in parts)
    joined = "\n".join(parts)
    assert all(label in joined for label in ("Т-Банк", "Точка", "Альфа-Банк", "Сбер"))


def test_failure_and_recovery_alerts():
    text = nf.format_failure("alfabank", "article fetch failed <x>", rejected=False)
    assert text.startswith("⚠️ <b>Альфа-Банк</b>: разбор не удался")
    assert "<code>article fetch failed &lt;x&gt;</code>" in text

    rejected = nf.format_failure("sber", "10 methods vs 153", rejected=True)
    assert "снимок отклонён" in rejected

    assert nf.format_recovery("alfabank") == "✅ <b>Альфа-Банк</b>: разбор снова проходит"


def test_failure_error_is_trimmed():
    text = nf.format_failure("sber", "x" * 2000, rejected=False)
    assert len(text) < 700


def test_status_message():
    status = ParseStatus(
        running=False, started_at="2026-09-22 09:43:47 UTC", finished_at="2026-09-22 09:49:58 UTC",
        banks={
            "tbank": BankStatus(status="done", services=76, methods=498, changes=2),
            "tochka": BankStatus(status="error", error="boom"),
            "alfabank": BankStatus(),
            "sber": BankStatus(status="running"),
        },
    )
    text = nf.format_status(status)
    assert "Последний разбор: 2026-09-22 09:49:58 UTC" in text
    assert "✅ Т-Банк — 76 сервисов, 498 методов, изменений: 2" in text
    assert "❌ Точка — boom" in text
    assert "⏳ Сбер — идёт разбор" in text
    assert "▫️ Альфа-Банк — не запускался" in text


def test_status_when_never_run():
    assert nf.format_status(None) == "Разбор ещё не запускался."
    assert "Разбор идёт" in nf.format_status(ParseStatus(running=True, started_at="t", banks={}))


def test_oversized_bank_text_is_clipped_and_html_stays_balanced():
    huge = "x" * 10_000
    [text] = _digest({"tbank": [Change("method", "added", f"GET /{huge}", f"{huge} / GET /x", f"https://b/{huge}")]})
    assert len(text) < 1000
    assert text.count("<code>") == text.count("</code>")
    assert "href" not in text          # oversized URL dropped, not cut
