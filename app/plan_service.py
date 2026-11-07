from __future__ import annotations

from datetime import date, datetime, timedelta
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo


from . import db
from .planning import engine
from .planning.model import Boundaries, EventRec, PlanResult, TaskRec


async def load_events(conn: db.Connection, user: dict[str, Any]) -> list[EventRec]:
    tz = ZoneInfo(user["settings"]["timezone"])
    return [engine.event_to_rec(raw, tz) for raw in await db.list_events(conn, user["id"])]


async def load_tasks(conn: db.Connection, user: dict[str, Any]) -> list[TaskRec]:
    tz = ZoneInfo(user["settings"]["timezone"])
    return [engine.task_to_rec(raw, tz) for raw in await db.list_tasks(conn, user["id"])]


def boundaries_of(user: dict[str, Any], day_start: str) -> Boundaries:
    return engine.boundaries_from_settings(user["settings"], day_start)


async def compute_plan(
    conn: db.Connection,
    user: dict[str, Any],
    date_from: date,
    date_to: date,
    day_start: str,
    now: datetime | None = None,
) -> tuple[PlanResult, list[EventRec], list[TaskRec]]:
    settings = user["settings"]
    tz = ZoneInfo(settings["timezone"])
    moment = engine.as_aware(now, tz) if now else datetime.now(tz)

    raw_events = await db.list_events(conn, user["id"])
    raw_tasks = await db.list_tasks(conn, user["id"])

    events = [engine.event_to_rec(raw, tz) for raw in raw_events]
    tasks = [engine.task_to_rec(raw, tz) for raw in raw_tasks]
    boundaries = engine.boundaries_from_settings(settings, day_start)
    revision = engine.plan_revision(raw_events, raw_tasks, settings)

    plan = engine.build_plan(
        events, tasks, boundaries, date_from, date_to, moment, revision
    )
    return plan, events, tasks


def plan_to_api(plan: PlanResult) -> dict[str, Any]:
    return {
        "revision": plan.revision,
        "from": plan.date_from.isoformat(),
        "to": plan.date_to.isoformat(),
        "blocks": [
            {
                "kind": block.kind,
                "source_id": block.source_id,
                "starts_at": block.starts_at.isoformat(),
                "ends_at": block.ends_at.isoformat(),
                "title": block.title,
                "category": block.category,
                "movable": block.movable if block.kind == "event" else None,
            }
            for block in plan.blocks
        ],
        "conflicts": [
            {
                "id": conflict.id,
                "type": conflict.type,
                "shortage_min": conflict.shortage_min,
                "explanation": conflict.explanation,
                "affected_task_ids": conflict.affected_task_ids,
            }
            for conflict in plan.conflicts
        ],
        "free_min": plan.free_min,
        "planned_min": plan.planned_min,
    }


def expand_occurrences(
    event: dict[str, Any], date_from: date, date_to: date, tz: ZoneInfo
) -> list[dict[str, Any]]:

    rec = engine.event_to_rec(event, tz)
    range_start = datetime.combine(date_from, datetime.min.time(), tzinfo=tz)
    range_end = datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=tz)

    if not rec.weekdays:
        if rec.starts_at < range_end and rec.ends_at > range_start:
            return [event]
        return []

    result: list[dict[str, Any]] = []
    for start, end in engine.occurrences(rec, range_start, range_end):
        result.append({**event, "starts_at": start.isoformat(), "ends_at": end.isoformat(),
                       "series_starts_at": event["starts_at"]})
    return result


def parse_range(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise ValueError("to раньше from")
    if (date_to - date_from).days > engine.MAX_RANGE_DAYS - 1:
        raise ValueError(f"диапазон длиннее {engine.MAX_RANGE_DAYS} дней")


@dataclass
class CachedPlan:


    date_from: date
    date_to: date
    plan: PlanResult
    events: list[EventRec]
    tasks: list[TaskRec]


_plan_cache: dict[str, dict[tuple[date, date], CachedPlan]] = {}


def remember_plan(
    user_id: str,
    date_from: date,
    date_to: date,
    plan: PlanResult,
    events: list[EventRec],
    tasks: list[TaskRec],
) -> None:
    per_user = _plan_cache.setdefault(user_id, {})
    per_user[(date_from, date_to)] = CachedPlan(date_from, date_to, plan, events, tasks)

    while len(per_user) > 8:
        per_user.pop(next(iter(per_user)))


def find_conflict(
    user_id: str, conflict_id: str, revision: str
) -> CachedPlan | None:

    for cached in _plan_cache.get(user_id, {}).values():
        if cached.plan.revision != revision:
            continue
        if any(conflict.id == conflict_id for conflict in cached.plan.conflicts):
            return cached
    return None


async def current_revision(conn, user: dict[str, Any]) -> str:
    raw_events = await db.list_events(conn, user["id"])
    raw_tasks = await db.list_tasks(conn, user["id"])
    return engine.plan_revision(raw_events, raw_tasks, user["settings"])
