"""Signed session cookie (SPEC §4) and the shared FastAPI dependencies."""

import re

from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import Settings
from .domain import User
from .store import Store

COOKIE = "tacit_session"
MAX_AGE = 30 * 24 * 3600
LOCAL_ORIGIN = re.compile(r"^http://(localhost|127\.0\.0\.1)(:\d{1,5})?$")
STATE_CHANGING = {"POST", "PATCH", "PUT", "DELETE"}


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> Store:
    return request.app.state.store


def _serializer(settings: Settings) -> URLSafeTimedSerializer:
    if settings.session_secret is None:
        raise HTTPException(503, "SESSION_SECRET is not set")
    return URLSafeTimedSerializer(settings.session_secret.get_secret_value(), salt="session")


def set_session(response: Response, settings: Settings, user_id: str) -> None:
    token = _serializer(settings).dumps({"uid": user_id})
    secure = bool(settings.public_base_url and settings.public_base_url.startswith("https"))
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=secure, path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def session_uid(request: Request) -> str | None:
    settings = get_settings(request)
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        data = _serializer(settings).loads(token, max_age=MAX_AGE)
    except BadSignature:
        return None
    uid = data.get("uid") if isinstance(data, dict) else None
    return uid if isinstance(uid, str) else None


def current_user(request: Request) -> User:
    uid = session_uid(request)
    user = get_store(request).get_user(uid) if uid else None
    if user is None:
        raise HTTPException(401, "not signed in")
    return user


def origin_allowed(origin: str, settings: Settings) -> bool:
    if settings.public_base_url and origin == settings.public_base_url:
        return True
    return bool(LOCAL_ORIGIN.match(origin))


def guard(method: str, path: str, origin: str | None, settings: Settings) -> tuple[int, str] | None:
    """The §4 checks done before routing: 503 without a secret, 403 for a foreign Origin."""
    if not path.startswith("/api/"):
        return None
    if settings.session_secret is None and not (method == "GET" and path == "/api/config"):
        return 503, "SESSION_SECRET is not set"
    if method in STATE_CHANGING and origin is not None and not origin_allowed(origin, settings):
        return 403, "bad origin"
    return None
