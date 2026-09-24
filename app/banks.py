"""Single source of truth for supported banks."""
from __future__ import annotations

from importlib import import_module

BANK_KEYS: tuple[str, ...] = ("tbank", "tochka", "alfabank", "sber")

BANK_LABELS: dict[str, str] = {
    "tbank":    "Т-Банк",
    "tochka":   "Точка",
    "alfabank": "Альфа-Банк",
    "sber":     "Сбер",
}

_PARSERS: dict[str, tuple[str, str]] = {
    "tbank":    ("bank_api_parser.parsers.tbank_parser", "TBankParser"),
    "tochka":   ("bank_api_parser.parsers.tochka_parser", "TochkaParser"),
    "alfabank": ("bank_api_parser.parsers.alfabank_parser", "AlfaBankParser"),
    "sber":     ("bank_api_parser.parsers.sber_parser", "SberParser"),
}


def bank_label(bank: str) -> str:
    return BANK_LABELS.get(bank, bank)


def parser_class(bank: str):
    """Lazily import the parser so heavy deps load only when a bank is parsed."""
    try:
        module_name, class_name = _PARSERS[bank]
    except KeyError:
        raise ValueError(f"Unknown bank: {bank}") from None
    return getattr(import_module(module_name), class_name)
