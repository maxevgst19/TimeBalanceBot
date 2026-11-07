from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import db
from ..deps import api_error, get_conn, get_current_user
from ..plan_service import expand_occurrences

router = APIRouter(prefix="/notes", tags=["Notes"])


class NoteInput(BaseModel):
    day: date
    text: str = Field(min_length=1, max_length=500)
    event_id: str | None = None


async def _validate(payload: NoteInput, conn, user) -> tuple[str, str]:
    content = payload.text.strip()
    if not content:
        raise api_error(422, "validation_error", "Напиши текст заметки")
    day = payload.day.isoformat()
    tz = ZoneInfo(user["settings"]["timezone"])
    if payload.day < datetime.now(tz).date():
        raise api_error(422, "validation_error", "Выбери сегодня или будущий день")
    if payload.event_id:
        event = await db.get_event(conn, user["id"], payload.event_id)
        occurrences = expand_occurrences(event, payload.day, payload.day, tz) if event else []
        if not occurrences:
            raise api_error(422, "validation_error", "В этот день нет выбранного занятия")
    return day, content


@router.get("")
async def list_notes(conn=Depends(get_conn), user=Depends(get_current_user)):
    async with conn.execute(
        "SELECT id, day, event_id, text FROM notes WHERE user_id = ? ORDER BY day, created_at",
        (user["id"],),
    ) as cur:
        return await cur.fetchall()


@router.post("", status_code=201)
async def create_note(payload: NoteInput, conn=Depends(get_conn), user=Depends(get_current_user)):
    day, content = await _validate(payload, conn, user)
    note_id = db.new_id()
    await conn.execute(
        "INSERT INTO notes (id, user_id, day, event_id, text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (note_id, user["id"], day, payload.event_id, content, db.now_iso()),
    )
    await conn.commit()
    return {"id": note_id, "day": day, "event_id": payload.event_id, "text": content}


@router.put("/{note_id}")
async def update_note(note_id: str, payload: NoteInput, conn=Depends(get_conn), user=Depends(get_current_user)):
    day, content = await _validate(payload, conn, user)
    async with conn.execute(
        "UPDATE notes SET day = ?, event_id = ?, text = ? WHERE id = ? AND user_id = ? RETURNING id",
        (day, payload.event_id, content, note_id, user["id"]),
    ) as cur:
        updated = await cur.fetchone()
    await conn.commit()
    if not updated:
        raise api_error(404, "not_found", "Заметка не найдена")
    return {"id": note_id, "day": day, "event_id": payload.event_id, "text": content}


@router.delete("/{note_id}", status_code=204)
async def delete_note(note_id: str, conn=Depends(get_conn), user=Depends(get_current_user)):
    async with conn.execute(
        "DELETE FROM notes WHERE id = ? AND user_id = ? RETURNING id", (note_id, user["id"]),
    ) as cur:
        deleted = await cur.fetchone()
    await conn.commit()
    if not deleted:
        raise api_error(404, "not_found", "Заметка не найдена")
