"""Афиша KudaGo и напоминания о выбранных мероприятиях."""
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
BASE = "https://kudago.com/public-api/v1.4"
_cache: dict[str, tuple[float, Any]] = {}


async def _fetch(path: str, params: dict[str, Any], ttl: int) -> Any:
    key = f"{path}:{sorted(params.items())}"
    saved = _cache.get(key)
    if saved and saved[0] > time.monotonic():
        return saved[1]
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(BASE + path, params=params)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise api_error(503, "events_unavailable", "Афиша сейчас недоступна. Попробуй позже.") from exc
    _cache[key] = (time.monotonic() + ttl, data)
    return data


@router.get("/cities")
async def cities():
    data = await _fetch("/locations/", {"lang": "ru", "fields": "slug,name"}, 86400)
    if not isinstance(data, list):
        raise api_error(503, "events_unavailable", "Не удалось загрузить список городов")
    return sorted(
        [{"slug": item["slug"], "name": item["name"]} for item in data
         if item.get("slug") and item.get("name")],
        key=lambda item: item["name"],
    )


@router.get("")
async def events(city: str = Query(pattern=r"^[a-z0-9-]{2,32}$")):
    city_list = await cities()
    if city not in {item["slug"] for item in city_list}:
        raise api_error(422, "validation_error", "Выбери город из списка")
    now = int(time.time())
    data = await _fetch("/events/", {
        "lang": "ru", "location": city, "actual_since": now,
        "actual_until": now + 45 * 86400, "page_size": 30,
        "fields": "id,title,dates,site_url,price,place,age_restriction",
        "expand": "place", "order_by": "-publication_date",
    }, 900)
    result = []
    for item in data.get("results", []):
        dates = sorted((d for d in item.get("dates", []) if isinstance(d.get("start"), int)
                        and d["start"] >= now), key=lambda d: d["start"])
        if not dates:
            continue
        place = item.get("place") or {}
        result.append({
            "id": item["id"], "title": item.get("title") or "Мероприятие",
            "starts_at": datetime.fromtimestamp(dates[0]["start"], timezone.utc).isoformat(),
            "dates": [datetime.fromtimestamp(d["start"], timezone.utc).isoformat()
                      for d in dates[:8]],
            "place": place.get("title", "") if isinstance(place, dict) else "",
            "price": item.get("price") or "", "age_restriction": item.get("age_restriction") or "",
            "url": item.get("site_url") or "",
        })
    return result


class ReminderInput(BaseModel):
    source_id: int = Field(gt=0)
    city: str = Field(pattern=r"^[a-z0-9-]{2,32}$")
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
    if not payload.url.startswith("https://kudago.com/"):
        raise api_error(422, "validation_error", "Некорректная ссылка на мероприятие")
    source = await _fetch(f"/events/{payload.source_id}/", {
        "lang": "ru", "fields": "id,title,dates,site_url,location"
    }, 900)
    possible_dates = {int(date["start"]) for date in source.get("dates", [])
                      if isinstance(date.get("start"), int)}
    if int(moment.timestamp()) not in possible_dates or source.get("site_url") != payload.url:
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
