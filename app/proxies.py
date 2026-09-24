"""Proxy list rules: URL validation, expiry, health check through the proxy."""
from __future__ import annotations

import ipaddress
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Mapping, Optional
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests

from bank_api_parser.tls import ca_bundle

logger = logging.getLogger(__name__)

SCHEMES = ("http", "https", "socks5", "socks5h")
MAX_URL_LENGTH = 500
WARN_DAYS = 3
MSK = ZoneInfo("Europe/Moscow")
CHECK_TIMEOUT = 15

# Plain-HTTP geo lookup (the free ip-api tier has no HTTPS); only IP/country are read.
GEO_URL = "http://ip-api.com/json/?fields=status,countryCode,query"
PROBE_URL = "https://developer.tbank.ru/"   # a bank portal: is it reachable through the proxy?


def validate_url(raw: str) -> str:
    url = raw.strip()
    if not url or len(url) > MAX_URL_LENGTH or any(c.isspace() for c in url):
        raise ValueError("укажите адрес прокси без пробелов, например socks5://user:pass@host:1080")
    parts = urlsplit(url)
    if parts.scheme not in SCHEMES:
        raise ValueError(f"поддерживаются схемы: {', '.join(SCHEMES)}")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("неверный порт") from exc
    if not parts.hostname or port is None:
        raise ValueError("нужны хост и порт: scheme://[user:pass@]host:port")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("адрес прокси не должен содержать путь или параметры")
    if _is_local(parts.hostname):
        raise ValueError("локальный адрес не может быть прокси")
    return url


def _is_local(host: str) -> bool:
    """Loopback/link-local/unspecified: this machine or cloud metadata, never a proxy.

    RFC1918 stays allowed — a proxy inside the office network is legitimate.
    """
    if host.lower() == "localhost" or host.lower().endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped   # ::ffff:127.0.0.1 is still this machine
    return ip.is_loopback or ip.is_link_local or ip.is_unspecified


def days_left(expires_at: Optional[datetime], now: datetime) -> Optional[int]:
    """Moscow calendar days until expiry (0 = expires today); negative once expired."""
    if expires_at is None:
        return None
    if expires_at <= now:
        return min(-1, (expires_at - now) // timedelta(days=1))
    return (expires_at.astimezone(MSK).date() - now.astimezone(MSK).date()).days


def usable_urls(rows: Iterable[Mapping], now: datetime) -> list[str]:
    return [r["url"] for r in rows if r["expires_at"] is None or r["expires_at"] > now]


def expiring(rows: Iterable[Mapping], now: datetime, warn_days: int = WARN_DAYS) -> list[Mapping]:
    """Proxies expiring within `warn_days` (or already expired) that nobody was told about."""
    limit = now + timedelta(days=warn_days)
    return [
        r for r in rows
        if r["expires_at"] is not None and r["expires_at"] <= limit and r["expiry_notified_at"] is None
    ]


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    ip: Optional[str] = None
    country: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


def _describe(exc: Exception) -> str:
    """Short reason without the exception text: it may contain the proxy password."""
    if isinstance(exc, requests.exceptions.ProxyError):
        return "прокси недоступен"
    if isinstance(exc, requests.exceptions.Timeout):
        return "таймаут"
    if isinstance(exc, requests.exceptions.SSLError):
        return "ошибка TLS"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "ошибка соединения"
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _geo(session: requests.Session) -> tuple[Optional[str], Optional[str]]:
    resp = session.get(GEO_URL, timeout=CHECK_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or data.get("status") != "success":
        return None, None
    return str(data.get("query") or "")[:64] or None, str(data.get("countryCode") or "")[:8] or None


def check(url: str) -> CheckResult:
    """Exit IP/country via a geo service, then the time to reach a bank portal (blocking)."""
    session = requests.Session()
    session.trust_env = False
    session.verify = ca_bundle()
    session.proxies = {"http": url, "https": url}
    try:
        try:
            ip, country = _geo(session)
        except (requests.RequestException, ValueError) as exc:
            return CheckResult(ok=False, error=_describe(exc))
        started = time.perf_counter()
        try:
            session.get(PROBE_URL, timeout=CHECK_TIMEOUT).raise_for_status()
        except requests.RequestException as exc:
            return CheckResult(ok=False, ip=ip, country=country, error=f"банк не ответил: {_describe(exc)}")
        latency = int((time.perf_counter() - started) * 1000)
        return CheckResult(ok=True, ip=ip, country=country, latency_ms=latency)
    except Exception as exc:  # noqa: BLE001 — a check must report, never crash the caller
        # Only the type: messages of proxy libraries may echo the URL with credentials
        logger.error("Proxy check crashed: %s", type(exc).__name__)
        return CheckResult(ok=False, error="ошибка проверки")
    finally:
        session.close()
