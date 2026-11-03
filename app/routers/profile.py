"""Профиль, личные границы и работа с данными пользователя."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..deps import (
    api_error,
    get_conn,
    get_current_user,
    public_user,
    require_patch,
)
from ..schemas import SettingsPatch, User

router = APIRouter(tags=["Profile"])


@router.get("/me", response_model=User)
async def me(user=Depends(get_current_user)):
    return public_user(user)


@router.patch("/me", response_model=User)
async def update_me(
    payload: SettingsPatch,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    patch = require_patch(payload)
    updated = await db.update_settings(conn, user["id"], patch)
    if updated is None:
        raise api_error(401, "session_invalid", "Неверная или истёкшая сессия")
    return public_user(updated)


@router.delete("/me/data", status_code=204)
async def delete_my_data(conn=Depends(get_conn), user=Depends(get_current_user)):
    """Удаляет профиль, события, задачи и настройки пользователя."""
    await db.delete_user_data(conn, user["id"])
