"""Общие зависимости и формат ошибок API.

Формат ошибок повторяет ``components/schemas/ApiError`` из openapi.yaml:
``{"code": ..., "message": ..., "details": {...}}``.
"""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from . import db
from .config import Settings
from .security import SecurityError, read_session


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_conn(request: Request):
    async with request.app.state.db.connection() as raw:
        yield db.Connection(raw)


async def get_current_user(
    request: Request,
    conn=Depends(get_conn),
    settings=Depends(get_settings),
) -> dict[str, Any]:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise SecurityError("session_invalid")
    user_id = read_session(header[7:].strip(), settings.jwt_secret)
    user = await db.get_user(conn, user_id)
    if user is None:
        raise SecurityError("session_invalid")
    return user


class ApiException(Exception):
    """Ошибка API в формате ApiError; обрабатывается в app.main."""

    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            body["details"] = self.details
        return body


def api_error(status: int, code: str, message: str, details: dict | None = None) -> ApiException:
    return ApiException(status, code, message, details)


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """Публичный вид профиля: внутренний max_user_id наружу не уходит."""
    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "settings": user["settings"],
    }


def require_patch(payload: Any, code: str = "validation_error") -> dict[str, Any]:
    """Проверка ``minProperties: 1`` у патчей — пустое тело не должно ничего менять."""
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise api_error(
            422,
            code,
            "Тело запроса не содержит ни одного поля для изменения",
        )
    return data
