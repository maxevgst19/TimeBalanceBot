"""План дня, «Что делать сейчас» и варианты «Плана Б»."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query

from .. import db
from ..config import Settings
from ..deps import api_error, get_conn, get_current_user, get_settings
from ..plan_service import (
    compute_plan,
    current_revision,
    find_conflict,
    parse_range,
    plan_to_api,
    remember_plan,
)
from ..planning import engine
from ..planning.alternatives import apply_alternative, generate_alternatives
from ..schemas import (
    Alternative,
    AlternativesRequest,
    ApplyRequest,
    NextAction,
    Plan,
)

router = APIRouter(prefix="/plan", tags=["Planning"])


def _check_range(date_from: date, date_to: date) -> None:
    try:
        parse_range(date_from, date_to)
    except ValueError as exc:
        raise api_error(422, "validation_error", str(exc))


@router.get("", response_model=Plan)
async def get_plan(
    date_from: Annotated[date, Query(alias="from")],
    date_to: Annotated[date, Query(alias="to")],
    conn=Depends(get_conn),
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    _check_range(date_from, date_to)
    plan, events, tasks = await compute_plan(
        conn, user, date_from, date_to, settings.day_start
    )
    remember_plan(user["id"], date_from, date_to, plan, events, tasks)
    return plan_to_api(plan)


@router.get("/next-action", response_model=NextAction)
async def get_next_action(
    conn=Depends(get_conn),
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    tz = ZoneInfo(user["settings"]["timezone"])
    now = datetime.now(tz)
    today = now.date()
    plan, events, tasks = await compute_plan(
        conn, user, today, today, settings.day_start, now=now
    )
    remember_plan(user["id"], today, today, plan, events, tasks)
    return engine.next_action(plan, tasks, now)


@router.post("/alternatives", response_model=list[Alternative])
async def build_alternatives(
    payload: AlternativesRequest,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    cached = find_conflict(user["id"], payload.conflict_id, payload.plan_revision)
    if cached is None or await current_revision(conn, user) != payload.plan_revision:
        raise api_error(
            409, "plan_changed", "План изменился; запросите варианты заново"
        )

    conflict = next(
        item for item in cached.plan.conflicts if item.id == payload.conflict_id
    )
    tz = ZoneInfo(user["settings"]["timezone"])
    boundaries = engine.boundaries_from_settings(user["settings"], settings.day_start)

    candidates = generate_alternatives(
        conflict=conflict,
        events=cached.events,
        tasks=cached.tasks,
        boundaries=boundaries,
        date_from=cached.date_from,
        date_to=cached.date_to,
        now=cached.plan.now or datetime.now(tz),
        revision=cached.plan.revision,
        original=cached.plan,
    )

    result = []
    for candidate in candidates:
        await db.save_alternative(
            conn,
            candidate.alt_id,
            user["id"],
            conflict.id,
            cached.plan.revision,
            candidate.payload,
        )
        result.append(
            {
                "id": candidate.alt_id,
                "title": candidate.title,
                "explanation": candidate.explanation,
                "changes": candidate.changes,
                "remaining_shortage_min": candidate.remaining,
            }
        )
    return result


@router.post("/alternatives/{alternative_id}/apply", response_model=Plan)
async def apply_plan_b(
    payload: ApplyRequest,
    alternative_id: Annotated[str, Path(alias="alternative_id")],
    conn=Depends(get_conn),
    user=Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    alternative = await db.get_alternative(conn, user["id"], alternative_id)
    if alternative is None:
        raise api_error(404, "not_found", "Вариант не найден")
    if (
        alternative["plan_revision"] != payload.plan_revision
        or await current_revision(conn, user) != payload.plan_revision
    ):
        raise api_error(
            409, "plan_changed", "План изменился; запросите варианты заново"
        )

    await apply_alternative(conn, user, alternative)

    # Пересчитываем по тому же диапазону, в котором конфликт был показан.
    cached = find_conflict(user["id"], alternative["conflict_id"], payload.plan_revision)
    tz = ZoneInfo(user["settings"]["timezone"])
    today = datetime.now(tz).date()
    date_from = cached.date_from if cached else today
    date_to = cached.date_to if cached else today + timedelta(days=6)

    plan, events, tasks = await compute_plan(
        conn, user, date_from, date_to, settings.day_start
    )
    remember_plan(user["id"], date_from, date_to, plan, events, tasks)
    return plan_to_api(plan)
