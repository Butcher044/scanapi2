"""Site login: session cookie, closed /api for anonymous users, admin-only guard."""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import SESSION_TTL, Auth, LoginLimiter

logger = logging.getLogger(__name__)

COOKIE = "bm_session"
PUBLIC_API = frozenset({"/api/auth/login", "/api/auth/logout", "/api/health"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOCKOUT_SECONDS = 15 * 60

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth(request: Request) -> Auth:
    return request.app.state.auth


def _limiter(request: Request) -> LoginLimiter:
    return request.app.state.limiter


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_https(request: Request) -> bool:
    # uvicorn rewrites the scheme from X-Forwarded-Proto only for FORWARDED_ALLOW_IPS peers
    return request.url.scheme == "https"


def _same_origin(request: Request) -> bool:
    """Browsers send Origin on cross-site writes; SameSite=strict is the main CSRF guard."""
    origin = request.headers.get("origin")
    return origin is None or urlsplit(origin).netloc == request.headers.get("host", "")


async def auth_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    path = request.url.path
    if path.startswith("/api/"):
        if request.method not in _SAFE_METHODS and not _same_origin(request):
            return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        if path not in PUBLIC_API:
            role = _auth(request).verify(request.cookies.get(COOKIE, ""))
            if role is None:
                return JSONResponse({"detail": "Требуется вход"}, status_code=401)
            request.state.role = role
    return await call_next(request)


def require_admin(request: Request) -> None:
    if getattr(request.state, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Доступно только администратору")


class LoginBody(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
async def login(body: LoginBody, request: Request, response: Response) -> dict:
    ip, now = _client_ip(request), time.time()
    limiter = _limiter(request)
    if limiter.blocked(ip, now):
        raise HTTPException(status_code=429, detail="Слишком много попыток, попробуйте позже",
                            headers={"Retry-After": str(LOCKOUT_SECONDS)})
    role = _auth(request).check_password(body.password)
    if role is None:
        limiter.failure(ip, now)
        logger.warning("Failed login from %s", ip)
        raise HTTPException(status_code=401, detail="Неверный пароль")
    limiter.reset(ip)
    response.set_cookie(
        COOKIE, _auth(request).issue(role, now) or "", max_age=SESSION_TTL, path="/",
        httponly=True, samesite="strict", secure=_is_https(request),
    )
    logger.info("Login as %s from %s", role, ip)
    return {"role": role}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="strict", secure=_is_https(request))
    return {"ok": True}


@router.get("/me")
async def me(request: Request) -> dict:
    return {"role": request.state.role}
