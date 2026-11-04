"""События: уроки, кружки и другие занятия."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query

from .. import db
from ..deps import api_error, get_conn, get_current_user, require_patch
from ..plan_service import expand_occurrences, parse_range
from ..schemas import Event, EventInput, EventPatch

router = APIRouter(prefix="/events", tags=["Events"])


def _validate_range(date_from: date, date_to: date) -> None:
    try:
        parse_range(date_from, date_to)
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc))


def _check_interval(starts_at: datetime, ends_at: datetime) -> None:
    if ends_at <= starts_at:
        raise api_error(
            422, "validation_error", "ends_at должно быть позже starts_at"
        )


@router.get("", response_model=list[Event])
async def list_events(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    _validate_range(date_from, date_to)
    tz = ZoneInfo(user["settings"]["timezone"])
    result = []
    for raw in await db.list_events(conn, user["id"]):
        result.extend(expand_occurrences(raw, date_from, date_to, tz))
    result.sort(key=lambda item: item["starts_at"])
    return result


@router.post("", response_model=Event, status_code=201)
async def create_event(
    payload: EventInput,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    data = payload.model_dump(mode="json")
    _check_interval(payload.starts_at, payload.ends_at)
    return await db.create_event(conn, user["id"], data)


@router.patch("/{event_id}", response_model=Event)
async def update_event(
    payload: EventPatch,
    event_id: Annotated[str, Path(alias="event_id")],
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    patch = require_patch(payload)
    existing = await db.get_event(conn, user["id"], event_id)
    if existing is None:
        raise api_error(404, "not_found", "Событие не найдено")

    starts_at = (
        patch.get("starts_at")
        if "starts_at" in patch
        else datetime.fromisoformat(existing["starts_at"])
    )
    ends_at = (
        patch.get("ends_at")
        if "ends_at" in patch
        else datetime.fromisoformat(existing["ends_at"])
    )
    _check_interval(starts_at, ends_at)

    updated = await db.update_event(conn, user["id"], event_id, patch)
    if updated is None:
        raise api_error(404, "not_found", "Событие не найдено")
    return updated


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: Annotated[str, Path(alias="event_id")],
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    if not await db.delete_event(conn, user["id"], event_id):
        raise api_error(404, "not_found", "Событие не найдено")
