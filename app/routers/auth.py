"""Обмен проверенных данных запуска MAX на сессию мини-приложения."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from .. import db
from ..config import Settings
from ..deps import get_conn, get_settings, public_user
from ..schemas import AuthMaxRequest, SessionResponse
from ..security import SecurityError, issue_session, validate_init_data

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/max", response_model=SessionResponse)
async def auth_max(
    payload: AuthMaxRequest,
    conn=Depends(get_conn),
    settings: Settings = Depends(get_settings),
):
    # Клиент присылает window.WebApp.initData (подписанную), а не initDataUnsafe.
    params = validate_init_data(
        payload.init_data, settings.bot_token, settings.init_data_max_age_seconds
    )

    raw_user = params.get("user")
    if not raw_user:
        raise SecurityError("missing_user")
    try:
        user_data = json.loads(raw_user)
    except (TypeError, ValueError):
        raise SecurityError("init_data_invalid")

    max_user_id = user_data.get("id")
    if not isinstance(max_user_id, int):
        raise SecurityError("missing_user")

    display_name = user_data.get("first_name") or user_data.get("username")
    # Один школьник в боте и в мини-приложении — одна запись.
    user = await db.get_or_create_by_max_id(conn, max_user_id, display_name)

    token, ttl = issue_session(
        user["id"], settings.jwt_secret, settings.session_ttl_seconds
    )
    return {
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": ttl,
        "user": public_user(user),
    }
