from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from .. import db
from ..deps import api_error, get_conn, get_current_user

router = APIRouter(prefix="/city-events", tags=["City events"])
MCP_URL = "https://spontanno.space/mcp"
_cache: dict[str, tuple[float, Any]] = {}


async def _fetch(tool: str, arguments: dict[str, Any], ttl: int) -> Any:
    key = f"{tool}:{sorted(arguments.items())}"
    saved = _cache.get(key)
    if saved and saved[0] > time.monotonic():
        return saved[1]
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(
                MCP_URL,
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": tool, "arguments": arguments}},
            )
            response.raise_for_status()
            result = response.json().get("result", {})
            if result.get("isError") or not result.get("structuredContent"):
                raise ValueError("Источник вернул ошибку")
            data = result["structuredContent"]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise api_error(503, "events_unavailable", "Афиша сейчас недоступна. Попробуй позже.") from exc
    _cache[key] = (time.monotonic() + ttl, data)
    return data


@router.get("/cities")
async def cities():
    data = await _fetch("list_cities", {"limit": 30}, 3600)
    if not isinstance(data.get("cities"), list):
        raise api_error(503, "events_unavailable", "Не удалось загрузить список городов")
    return sorted(
        [{"slug": item["slug"], "name": item["name"]} for item in data["cities"]
         if item.get("slug") and item.get("name")],
        key=lambda item: item["name"],
    )


@router.get("")
async def events(city: str = Query(min_length=2, max_length=80)):
    data = await _fetch("search_events", {
        "city": city, "when": "week", "sort": "soonest", "limit": 20,
    }, 900)
    result = []
    for item in data.get("events", []):
        start = item.get("starts_at")
        if not start:
            continue
        place = item.get("venue") or {}
        price = item.get("price") or {}
        result.append({
            "id": item["id"], "title": item.get("title") or "Мероприятие",
            "starts_at": start, "dates": [start],
            "place": place.get("name", "") if isinstance(place, dict) else "",
            "price": price.get("text", "") if isinstance(price, dict) else "",
            "age_restriction": item.get("age") or "",
            "url": item.get("url") or "",
        })
    return result


class ReminderInput(BaseModel):
    source_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    city: str = Field(min_length=2, max_length=80)
    starts_at: datetime
    title: str = Field(min_length=1, max_length=120)
    url: str = Field(max_length=500)


@router.get("/reminders")
async def list_reminders(conn=Depends(get_conn), user=Depends(get_current_user)):
    async with conn.execute(
        "SELECT id, source_id, city, title, starts_at, url FROM city_event_reminders "
        "WHERE user_id = ? ORDER BY starts_at", (user["id"],)
    ) as cur:
        return await cur.fetchall()


@router.post("/reminders", status_code=201)
async def create_reminder(payload: ReminderInput, conn=Depends(get_conn), user=Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    moment = payload.starts_at.replace(tzinfo=timezone.utc) if payload.starts_at.tzinfo is None else payload.starts_at
    if not now < moment <= now + timedelta(days=366):
        raise api_error(422, "validation_error", "Дата мероприятия должна быть в будущем")
    if not payload.url.startswith("https://spontanno.space/"):
        raise api_error(422, "validation_error", "Некорректная ссылка на мероприятие")
    detail = await _fetch("get_event", {"event": payload.source_id}, 900)
    source = detail.get("event") or {}
    possible_dates = {datetime.fromisoformat(date["starts_at"]).timestamp()
                      for date in source.get("schedule", {}).get("upcoming", [])
                      if date.get("starts_at")}
    possible_dates.add(datetime.fromisoformat(source["starts_at"]).timestamp())
    if moment.timestamp() not in possible_dates or source.get("url") != payload.url:
        raise api_error(422, "validation_error", "Дата или ссылка мероприятия изменилась. Обнови афишу.")
    title = str(source.get("title") or payload.title)[:120]
    reminder_id = db.new_id()
    await conn.execute(
        """INSERT INTO city_event_reminders
           (id, user_id, source_id, city, title, starts_at, url)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (user_id, source_id, starts_at) DO NOTHING""",
        (reminder_id, user["id"], payload.source_id, payload.city, title,
         moment.isoformat(), payload.url),
    )
    await conn.commit()
    async with conn.execute(
        "SELECT id, source_id, city, title, starts_at, url FROM city_event_reminders "
        "WHERE user_id = ? AND source_id = ? AND starts_at = ?",
        (user["id"], payload.source_id, moment.isoformat()),
    ) as cur:
        return await cur.fetchone()


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(reminder_id: str, conn=Depends(get_conn), user=Depends(get_current_user)):
    async with conn.execute(
        "DELETE FROM city_event_reminders WHERE id = ? AND user_id = ? RETURNING id",
        (reminder_id, user["id"]),
    ) as cur:
        deleted = await cur.fetchone()
    await conn.commit()
    if not deleted:
        raise api_error(404, "not_found", "Напоминание не найдено")
