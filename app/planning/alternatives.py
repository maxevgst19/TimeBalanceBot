"""«План Б»: варианты перестройки дня и их последствия.

Варианты не переносят дела молча (PROJECT_CONCEPT.md, раздел 6.2). Каждый
вариант сначала применяется «вслепую» к копии данных, план пересчитывается, и
пользователю показывается оставшийся дефицит. Вариант попадает в ответ только
если дефицит действительно уменьшается.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import aiosqlite

from .. import db
from .engine import (
    as_aware,
    build_plan,
    format_day,
    format_time,
    plural_minutes,
)
from .model import Boundaries, Conflict, EventRec, PlanResult, TaskRec, stable_id

MAX_VARIANTS = 2  # плюс «оставить как есть» — итого 2–3 варианта


@dataclass
class Candidate:
    alt_id: str
    title: str
    explanation: str
    changes: list[str]
    payload: dict[str, Any]
    remaining: int


def _dry_run(
    events: list[EventRec],
    tasks: list[TaskRec],
    boundaries: Boundaries,
    date_from: date,
    date_to: date,
    now: datetime,
    revision: str,
    conflict_id: str,
) -> int:
    """Считает оставшийся дефицит конфликта после «применения» варианта."""
    plan = build_plan(events, tasks, boundaries, date_from, date_to, now, revision)
    for conflict in plan.conflicts:
        if conflict.id == conflict_id:
            return conflict.shortage_min
    return 0


def _shift_event(events: list[EventRec], event_id: str, **delta: Any) -> list[EventRec] | None:
    result: list[EventRec] = []
    found = False
    for event in events:
        if event.id == event_id:
            found = True
            if "days" in delta:
                shift = timedelta(days=delta["days"])
            else:
                shift = timedelta(minutes=delta.get("minutes", 0))
            event = type(event)(
                **{
                    **event.__dict__,
                    "starts_at": event.starts_at + shift,
                    "ends_at": event.ends_at + shift,
                }
            )
        result.append(event)
    return result if found else None


def _postpone_task(tasks: list[TaskRec], task_id: str, days: int) -> list[TaskRec] | None:
    result: list[TaskRec] = []
    found = False
    for task in tasks:
        if task.id == task_id:
            found = True
            task = type(task)(**{**task.__dict__, "due_at": task.due_at + timedelta(days=days)})
        result.append(task)
    return result if found else None


def _set_splittable(tasks: list[TaskRec], task_id: str, value: bool) -> list[TaskRec] | None:
    result: list[TaskRec] = []
    found = False
    for task in tasks:
        if task.id == task_id:
            found = True
            task = type(task)(**{**task.__dict__, "splittable": value})
        result.append(task)
    return result if found else None


def _evaluate(
    *,
    alt_id: str,
    title: str,
    explanation: str,
    changes: list[str],
    payload: dict[str, Any],
    events: list[EventRec],
    tasks: list[TaskRec],
    boundaries: Boundaries,
    date_from: date,
    date_to: date,
    now: datetime,
    revision: str,
    conflict_id: str,
    baseline: int,
) -> Candidate | None:
    remaining = _dry_run(
        events, tasks, boundaries, date_from, date_to, now, revision, conflict_id
    )
    if remaining >= baseline:
        return None  # вариант не помогает — не показываем
    return Candidate(
        alt_id=alt_id,
        title=title,
        explanation=explanation,
        changes=changes,
        payload=payload,
        remaining=remaining,
    )


def generate_alternatives(
    conflict: Conflict,
    events: list[EventRec],
    tasks: list[TaskRec],
    boundaries: Boundaries,
    date_from: date,
    date_to: date,
    now: datetime,
    revision: str,
) -> list[Candidate]:
    baseline = conflict.shortage_min
    candidates: list[Candidate] = []

    if conflict.type == "overlap":
        candidates.extend(
            _overlap_variants(
                conflict, events, tasks, boundaries, date_from, date_to, now, revision, baseline
            )
        )
    else:
        candidates.extend(
            _shortage_variants(
                conflict, events, tasks, boundaries, date_from, date_to, now, revision, baseline
            )
        )

    candidates.sort(key=lambda item: item.remaining)
    selected = candidates[:MAX_VARIANTS]

    # «Оставить как есть» показывает риск просрочки и закрывает лимит 2–3 вариантов.
    if len(selected) < 3:
        selected.append(
            Candidate(
                alt_id=stable_id("alt", conflict.id, "keep"),
                title="Оставить как есть",
                explanation=(
                    f"Ничего не переносится. Под риском остаётся "
                    f"{plural_minutes(baseline)} — план не сойдётся."
                ),
                changes=[
                    "Дела остаются на своих местах",
                    f"Дефицит сохранится: {plural_minutes(baseline)}",
                ],
                payload={"kind": "none"},
                remaining=baseline,
            )
        )
    return selected


def _shortage_variants(
    conflict: Conflict,
    events: list[EventRec],
    tasks: list[TaskRec],
    boundaries: Boundaries,
    date_from: date,
    date_to: date,
    now: datetime,
    revision: str,
    baseline: int,
) -> list[Candidate]:
    variants: list[Candidate] = []
    by_id = {task.id: task for task in tasks}

    # 1. Разбить большое задание на части.
    for task_id in conflict.affected_task_ids:
        task = by_id.get(task_id)
        if task is None or task.splittable:
            continue
        updated = _set_splittable(tasks, task.id, True)
        if updated is None:
            continue
        candidate = _evaluate(
            alt_id=stable_id("alt", conflict.id, "split", task.id),
            title="Разбить задание на части",
            explanation=(
                f"«{task.title}» ({plural_minutes(task.estimated_min)}) делится на части: "
                "обязательная часть выполняется сегодня, остальное — в ближайшее окно."
            ),
            changes=[
                f"«{task.title}» можно делать частями",
                f"Сейчас целиком помещается только {plural_minutes(max(0, task.estimated_min - conflict.shortage_min))}",
            ],
            payload={"kind": "set_splittable", "task_id": task.id, "value": True},
            events=events,
            tasks=updated,
            boundaries=boundaries,
            date_from=date_from,
            date_to=date_to,
            now=now,
            revision=revision,
            conflict_id=conflict.id,
            baseline=baseline,
        )
        if candidate:
            variants.append(candidate)
        break

    # 2. Перенести гибкое дело на другой день.
    for event in events:
        if not event.movable:
            continue
        for days in (1, 2, 3, 7):
            updated = _shift_event(events, event.id, days=days)
            if updated is None:
                continue
            target = event.starts_at + timedelta(days=days)
            candidate = _evaluate(
                alt_id=stable_id("alt", conflict.id, "move_day", event.id, days),
                title="Перенести гибкое дело",
                explanation=(
                    f"«{event.title}» смещается на {format_day(target)} "
                    f"({format_time(target)}), освобождая окно под задания."
                ),
                changes=[
                    f"«{event.title}» → {format_day(target)}, {format_time(target)}",
                    "Освободившееся окно уходит под задания",
                ],
                payload={"kind": "move_event", "event_id": event.id, "delta_days": days},
                events=updated,
                tasks=tasks,
                boundaries=boundaries,
                date_from=date_from,
                date_to=date_to,
                now=now,
                revision=revision,
                conflict_id=conflict.id,
                baseline=baseline,
            )
            if candidate:
                variants.append(candidate)
                break
        if len(variants) >= MAX_VARIANTS:
            return variants

    # 3. Сдвинуть срок самого несрочного задания.
    if len(variants) < MAX_VARIANTS:
        postponed = sorted(
            (by_id[tid] for tid in conflict.affected_task_ids if tid in by_id),
            key=lambda task: (task.due_at, 0 if task.priority == "high" else 1),
            reverse=True,
        )
        for task in postponed:
            updated = _postpone_task(tasks, task.id, 1)
            if updated is None:
                continue
            target = task.due_at + timedelta(days=1)
            candidate = _evaluate(
                alt_id=stable_id("alt", conflict.id, "postpone", task.id),
                title="Сдвинуть срок несрочного задания",
                explanation=(
                    f"Срок «{task.title}» переносится на {format_day(target)}: "
                    "сегодня оно не успевает, а завтра для него есть окно."
                ),
                changes=[
                    f"«{task.title}» → срок {format_day(target)}",
                    "Сегодняшний план разгружается",
                ],
                payload={"kind": "postpone_task", "task_id": task.id, "delta_days": 1},
                events=events,
                tasks=updated,
                boundaries=boundaries,
                date_from=date_from,
                date_to=date_to,
                now=now,
                revision=revision,
                conflict_id=conflict.id,
                baseline=baseline,
            )
            if candidate:
                variants.append(candidate)
                break

    return variants


def _overlap_variants(
    conflict: Conflict,
    events: list[EventRec],
    tasks: list[TaskRec],
    boundaries: Boundaries,
    date_from: date,
    date_to: date,
    now: datetime,
    revision: str,
    baseline: int,
) -> list[Candidate]:
    variants: list[Candidate] = []
    by_id = {event.id: event for event in events}
    movable = [
        by_id[event_id]
        for event_id in conflict.affected_event_ids
        if event_id in by_id and by_id[event_id].movable
    ]

    for event in movable:
        # Сдвиг внутри дня: отодвигаем до конца пересечения + запас.
        for minutes in (conflict.shortage_min + 15, conflict.shortage_min + 30, 60, 120):
            updated = _shift_event(events, event.id, minutes=minutes)
            if updated is None:
                continue
            target = event.starts_at + timedelta(minutes=minutes)
            candidate = _evaluate(
                alt_id=stable_id("alt", conflict.id, "move_time", event.id, minutes),
                title="Сдвинуть дело в этот же день",
                explanation=(
                    f"«{event.title}» начинается в {format_time(target)} вместо "
                    f"{format_time(event.starts_at)} — пересечение исчезает."
                ),
                changes=[
                    f"«{event.title}» → {format_time(target)}",
                    f"Пересечение {plural_minutes(conflict.shortage_min)} снимается",
                ],
                payload={"kind": "move_event", "event_id": event.id, "delta_minutes": minutes},
                events=updated,
                tasks=tasks,
                boundaries=boundaries,
                date_from=date_from,
                date_to=date_to,
                now=now,
                revision=revision,
                conflict_id=conflict.id,
                baseline=baseline,
            )
            if candidate:
                variants.append(candidate)
                break
        if variants:
            break

    # Перенос на другой день — второй вариант.
    if len(variants) < MAX_VARIANTS:
        for event in movable:
            for days in (1, 2, 7):
                updated = _shift_event(events, event.id, days=days)
                if updated is None:
                    continue
                target = event.starts_at + timedelta(days=days)
                candidate = _evaluate(
                    alt_id=stable_id("alt", conflict.id, "move_day", event.id, days),
                    title="Перенести дело на другой день",
                    explanation=(
                        f"«{event.title}» переходит на {format_day(target)} "
                        f"({format_time(target)})."
                    ),
                    changes=[
                        f"«{event.title}» → {format_day(target)}, {format_time(target)}",
                        "Сегодняшнее пересечение снимается",
                    ],
                    payload={"kind": "move_event", "event_id": event.id, "delta_days": days},
                    events=updated,
                    tasks=tasks,
                    boundaries=boundaries,
                    date_from=date_from,
                    date_to=date_to,
                    now=now,
                    revision=revision,
                    conflict_id=conflict.id,
                    baseline=baseline,
                )
                if candidate:
                    variants.append(candidate)
                    break
            if variants:
                break

    return variants


# --------------------------------------------------------------------------
# Применение выбранного варианта
# --------------------------------------------------------------------------

async def apply_alternative(
    conn: aiosqlite.Connection,
    user: dict[str, Any],
    alternative: dict[str, Any],
) -> None:
    """Выполняет сохранённую мутацию. План пересчитается вызывающей стороной."""
    payload = alternative["payload"]
    kind = payload.get("kind")

    if kind == "none":
        return

    if kind == "set_splittable":
        await db.update_task(
            conn,
            user["id"],
            payload["task_id"],
            {"splittable": bool(payload.get("value", True))},
        )
        return

    if kind == "postpone_task":
        task = await db.get_task(conn, user["id"], payload["task_id"])
        if task is None:
            return
        new_due = as_aware(
            datetime.fromisoformat(task["due_at"]),
            _tz(user),
        ) + timedelta(days=int(payload.get("delta_days", 1)))
        await db.update_task(
            conn, user["id"], task["id"], {"due_at": new_due.isoformat()}
        )
        return

    if kind == "move_event":
        event = await db.get_event(conn, user["id"], payload["event_id"])
        if event is None:
            return
        if "delta_days" in payload:
            shift = timedelta(days=int(payload["delta_days"]))
        else:
            shift = timedelta(minutes=int(payload.get("delta_minutes", 0)))
        starts = as_aware(datetime.fromisoformat(event["starts_at"]), _tz(user)) + shift
        ends = as_aware(datetime.fromisoformat(event["ends_at"]), _tz(user)) + shift
        await db.update_event(
            conn,
            user["id"],
            event["id"],
            {"starts_at": starts.isoformat(), "ends_at": ends.isoformat()},
        )
        return

    raise ValueError(f"unknown alternative kind: {kind}")


def _tz(user: dict[str, Any]):
    from zoneinfo import ZoneInfo

    return ZoneInfo(user["settings"]["timezone"])
