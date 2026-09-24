"""Outgoing proxies for the parsers: per-request round-robin, direct connection as fallback.

The runner calls set_active() before a parse; every session created afterwards
(base_parser._create_session) mounts an adapter that picks the next proxy for
each request. A proxy that fails to connect cools down for a while; when no
proxy works, the request goes out directly.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

COOLDOWN = 300.0     # seconds a failed proxy is skipped
MAX_ATTEMPTS = 3     # proxies tried per request before going direct


def mask(url: str) -> str:
    """Proxy URL with the password replaced by *** (safe for logs and the UI)."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    netloc = f"{parts.username}:***@{host}" + (f":{parts.port}" if parts.port else "")
    return urlunsplit(parts._replace(netloc=netloc))


class ProxyRotator:
    """Thread-safe round-robin over proxy URLs (Alfa parses in a thread pool)."""

    def __init__(
        self,
        urls: Sequence[str],
        *,
        cooldown: float = COOLDOWN,
        max_attempts: int = MAX_ATTEMPTS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._urls = tuple(urls)
        self._cooldown = cooldown
        self._max_attempts = max_attempts
        self._clock = clock
        self._next = 0
        self._failed_at: dict[str, float] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._urls)

    def candidates(self) -> list[str]:
        """Proxies to try for one request, starting after the previous request's first."""
        if not self._urls:
            return []
        with self._lock:
            start = self._next
            self._next = (self._next + 1) % len(self._urls)
            now = self._clock()
            ordered = self._urls[start:] + self._urls[:start]
            alive = [u for u in ordered if now - self._failed_at.get(u, -self._cooldown) >= self._cooldown]
        return alive[: self._max_attempts]

    def report_failure(self, url: str) -> None:
        with self._lock:
            self._failed_at = {**self._failed_at, url: self._clock()}


class RotatingProxyAdapter(HTTPAdapter):
    def __init__(self, rotator: ProxyRotator, **kwargs: Any):
        self._rotator = rotator
        super().__init__(**kwargs)

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        for url in self._rotator.candidates():
            try:
                return super().send(request, **{**kwargs, "proxies": {"http": url, "https": url}})
            # ConnectionError covers ProxyError, SSL and connect timeouts; a proxy can also
            # accept the connection and then hang, which surfaces as ReadTimeout.
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                self._rotator.report_failure(url)
                logger.warning("Proxy %s failed (%s), trying next", mask(url), type(exc).__name__)
        return super().send(request, **kwargs)


_active: Optional[ProxyRotator] = None


def set_active(rotator: Optional[ProxyRotator]) -> None:
    global _active
    _active = rotator


def active() -> Optional[ProxyRotator]:
    return _active


def make_adapter(**kwargs: Any) -> HTTPAdapter:
    rotator = _active
    if rotator is None or not len(rotator):
        return HTTPAdapter(**kwargs)
    return RotatingProxyAdapter(rotator, **kwargs)
