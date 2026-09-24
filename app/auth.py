"""Password login with two roles and stateless signed session tokens.

Token: "<role>.<expires>.<signature>". The signature covers a fingerprint of the
role's current password, so changing a password in .env logs that role out.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections import deque
from typing import Literal, Mapping, Optional, get_args

Role = Literal["admin", "team"]
ROLES: tuple[Role, ...] = get_args(Role)
SESSION_TTL = 30 * 24 * 3600


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class Auth:
    def __init__(self, passwords: Mapping[Role, str], secret: bytes, ttl: int = SESSION_TTL):
        self._passwords = {role: passwords.get(role, "") for role in ROLES}
        self._secret = secret
        self._ttl = ttl

    def check_password(self, password: str) -> Optional[Role]:
        """Role whose password matches; every role is compared to keep timing flat."""
        found: Optional[Role] = None
        for role, expected in self._passwords.items():
            if hmac.compare_digest(password.encode(), expected.encode()) and expected:
                found = role
        return found

    def issue(self, role: Role, now: Optional[float] = None) -> Optional[str]:
        if not self._passwords.get(role):
            return None
        expires = int((time.time() if now is None else now) + self._ttl)
        payload = f"{role}.{expires}"
        return f"{payload}.{self._sign(role, payload)}"

    def verify(self, token: str, now: Optional[float] = None) -> Optional[Role]:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] not in ROLES or not parts[1].isdigit():
            return None
        role, expires, signature = parts
        if not self._passwords.get(role):
            return None
        if not hmac.compare_digest(signature, self._sign(role, f"{role}.{expires}")):
            return None
        if int(expires) < (time.time() if now is None else now):
            return None
        return role

    def _sign(self, role: str, payload: str) -> str:
        fingerprint = hashlib.sha256(self._passwords[role].encode()).hexdigest()
        message = f"{payload}.{fingerprint}".encode()
        return _b64(hmac.new(self._secret, message, hashlib.sha256).digest())


class LoginLimiter:
    """At most `max_failures` wrong passwords per key (client IP) within `window` seconds."""

    def __init__(self, max_failures: int = 5, window: float = 15 * 60):
        self._max = max_failures
        self._window = window
        self._failures: dict[str, deque[float]] = {}

    def blocked(self, key: str, now: float) -> bool:
        return len(self._recent(key, now)) >= self._max

    def failure(self, key: str, now: float) -> None:
        self._recent(key, now).append(now)

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)

    def _recent(self, key: str, now: float) -> deque[float]:
        # Drop stale keys so an unauthenticated flood cannot grow the dict forever
        for stale in [k for k, q in self._failures.items() if q and q[-1] <= now - self._window]:
            del self._failures[stale]
        failures = self._failures.setdefault(key, deque())
        while failures and failures[0] <= now - self._window:
            failures.popleft()
        return failures
