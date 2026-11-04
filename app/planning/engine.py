"""Алгоритм планирования TimeBalance.

Реализует базовый алгоритм MVP из PROJECT_CONCEPT.md, раздел 9, — работа
интервалами без ИИ:

1. строим занятые интервалы на диапазон дат (события, дорога, перерывы);
2. находим свободные окна в пределах учебного дня;
3. раскладываем задачи по окнам по срочности;
4. считаем неразмещённые минуты и описываем конкретный конфликт;
5. из конфликта собираются варианты «Плана Б» (см. alternatives.py).
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .model import Block, Boundaries, Conflict, EventRec, PlanResult, TaskRec, stable_id

MAX_RANGE_DAYS = 31


# --------------------------------------------------------------------------
# Вспомогательные функции
# --------------------------------------------------------------------------

def plural_minutes(value: int) -> str:
    """Склонение: «1 минута», «2 минуты», «5 минут»."""
    value = abs(value)
    last_two = value % 100
    last = value % 10
    if 11 <= last_two <= 14:
        form = "минут"
    elif last == 1:
        form = "минута"
    elif 2 <= last <= 4:
        form = "минуты"
    else:
        form = "минут"
    return f"{value} {form}"


def human_duration(minutes: int) -> str:
    """Короткая запись длительности: «45 мин», «1 ч 20 мин», «2 ч»."""
    if minutes < 60:
        return f"{minutes} мин"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"{hours} ч"
    return f"{hours} ч {rest} мин"


def format_time(value: datetime) -> str:
    return value.strftime("%H:%M")


def format_day(value: datetime | date) -> str:
    return value.strftime("%d.%m")


def as_aware(value: datetime, tz: ZoneInfo) -> datetime:
    """Наивное время трактуем как локальное время пользователя."""
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def parse_iso(value: str, tz: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return as_aware(parsed, tz)


# --------------------------------------------------------------------------
# Конвертация записей хранилища в типы алгоритма
# --------------------------------------------------------------------------

def event_to_rec(raw: dict, tz: ZoneInfo) -> EventRec:
    recurrence = raw.get("recurrence") or {}
    return EventRec(
        id=raw["id"],
        title=raw["title"],
        category=raw["category"],
        starts_at=parse_iso(raw["starts_at"], tz),
        ends_at=parse_iso(raw["ends_at"], tz),
        travel_before_min=int(raw.get("travel_before_min", 0)),
        travel_after_min=int(raw.get("travel_after_min", 0)),
        movable=bool(raw.get("movable", False)),
        weekdays=tuple(recurrence["weekdays"]) if recurrence.get("weekdays") else None,
        until=date.fromisoformat(recurrence["until"]) if recurrence.get("until") else None,
    )


def task_to_rec(raw: dict, tz: ZoneInfo) -> TaskRec:
    return TaskRec(
        id=raw["id"],
        title=raw["title"],
        due_at=parse_iso(raw["due_at"], tz),
        estimated_min=max(0, int(raw["estimated_min"]) - int(raw.get("spent_min", 0))),
        splittable=bool(raw.get("splittable", True)),
        priority=raw.get("priority", "normal"),
        status=raw.get("status", "todo"),
    )


def boundaries_from_settings(settings: dict, day_start: str) -> Boundaries:
    return Boundaries(
        timezone=settings["timezone"],
        day_start=time.fromisoformat(day_start),
        day_end=time.fromisoformat(settings["day_end"]),
        break_after_school_min=int(settings["break_after_school_min"]),
    )


# --------------------------------------------------------------------------
# Шаг 1: занятые интервалы
# --------------------------------------------------------------------------

def occurrences(event: EventRec, range_start: datetime, range_end: datetime) -> list[tuple[datetime, datetime]]:
    """Экземпляры события, попадающие в диапазон (одно или повторение)."""
    if not event.weekdays:
        if event.starts_at < range_end and event.ends_at > range_start:
            return [(event.starts_at, event.ends_at)]
        return []

    tz = event.starts_at.tzinfo
    duration = event.ends_at - event.starts_at
    clock = event.starts_at.time()
    result: list[tuple[datetime, datetime]] = []

    day = range_start.date()
    last_day = (range_end - timedelta(microseconds=1)).date()
    while day <= last_day:
        if day.isoweekday() in event.weekdays and (event.until is None or day <= event.until):
            start = datetime.combine(day, clock, tzinfo=tz)
            end = start + duration
            if start >= event.starts_at and start < range_end and end > range_start:
                result.append((start, end))
        day += timedelta(days=1)
    return result


def build_busy(
    events: list[EventRec],
    boundaries: Boundaries,
    range_start: datetime,
    range_end: datetime,
) -> list[Block]:
    """События, дорога до/после и обязательный перерыв после школы."""
    tz = ZoneInfo(boundaries.timezone)
    blocks: list[Block] = []
    school_ends: dict[date, datetime] = {}

    for event in events:
        for start, end in occurrences(event, range_start, range_end):
            if event.travel_before_min > 0:
                blocks.append(
                    Block(
                        "travel",
                        start - timedelta(minutes=event.travel_before_min),
                        start,
                        f"Дорога: {event.title}",
                        source_id=event.id,
                        category="travel",
                        movable=event.movable,
                    )
                )
            blocks.append(
                Block(
                    "event",
                    start,
                    end,
                    event.title,
                    source_id=event.id,
                    category=event.category,
                    movable=event.movable,
                )
            )
            if event.travel_after_min > 0:
                blocks.append(
                    Block(
                        "travel",
                        end,
                        end + timedelta(minutes=event.travel_after_min),
                        f"Дорога: {event.title}",
                        source_id=event.id,
                        category="travel",
                        movable=event.movable,
                    )
                )
            # Перерыв после школы считаем от последнего урока в этот день.
            if event.category == "school":
                current = school_ends.get(start.date())
                if current is None or end > current:
                    school_ends[start.date()] = end

    if boundaries.break_after_school_min > 0:
        for day, school_end in school_ends.items():
            break_start = school_end
            break_end = school_end + timedelta(minutes=boundaries.break_after_school_min)
            if break_start < range_end and break_end > range_start:
                blocks.append(
                    Block(
                        "break",
                        break_start,
                        break_end,
                        "Перерыв после школы",
                        source_id=None,
                        category="rest",
                    )
                )

    return blocks


# --------------------------------------------------------------------------
# Шаг 2: свободные окна
# --------------------------------------------------------------------------

def free_windows(
    busy: list[Block],
    boundaries: Boundaries,
    range_start: datetime,
    range_end: datetime,
) -> list[Block]:
    """Свободное время внутри учебного дня: [day_start, day_end] минус занятость."""
    tz = ZoneInfo(boundaries.timezone)
    ordered = sorted(busy, key=lambda block: block.starts_at)
    result: list[Block] = []

    day = range_start.date()
    last_day = (range_end - timedelta(microseconds=1)).date()
    while day <= last_day:
        window_start = datetime.combine(day, boundaries.day_start, tzinfo=tz)
        window_end = datetime.combine(day, boundaries.day_end, tzinfo=tz)
        if window_end <= window_start:
            window_end += timedelta(days=1)

        window_start = max(window_start, range_start)
        window_end = min(window_end, range_end)

        if window_end > window_start:
            cursor = window_start
            for block in ordered:
                if block.ends_at <= window_start or block.starts_at >= window_end:
                    continue
                busy_start = max(block.starts_at, window_start)
                busy_end = min(block.ends_at, window_end)
                if busy_start > cursor:
                    result.append(Block("free", cursor, busy_start, "Свободно"))
                cursor = max(cursor, busy_end)
                if cursor >= window_end:
                    break
            if cursor < window_end:
                result.append(Block("free", cursor, window_end, "Свободно"))

        day += timedelta(days=1)
    return result


# --------------------------------------------------------------------------
# Шаг 3: раскладка задач
# --------------------------------------------------------------------------

def place_tasks(
    tasks: list[TaskRec],
    windows: list[Block],
    now: datetime,
    range_end: datetime,
) -> tuple[list[Block], dict[str, int], list[TaskRec], int]:
    """Раскладывает задачи по окнам.

    Возвращает (блоки задач, неразмещённые минуты по id, учитанные задачи,
    суммарная ёмкость свободных окон).
    """
    considered = [
        task for task in tasks if task.status != "done" and task.due_at <= range_end
    ]
    considered.sort(
        key=lambda task: (
            task.due_at,
            0 if task.priority == "high" else 1,
            task.estimated_min,
        )
    )

    # Окна, доступные для работы: прошлое сегодня исключается.
    usable: list[list[datetime]] = []
    capacity = 0
    for window in windows:
        start = max(window.starts_at, now)
        if window.ends_at > start:
            usable.append([start, window.ends_at])
            capacity += int(round((window.ends_at - start).total_seconds() / 60))

    placed: list[Block] = []
    unplaced: dict[str, int] = {}

    for task in considered:
        remaining = task.estimated_min
        for window in usable:
            if remaining <= 0:
                break
            if window[1] <= window[0]:
                continue
            # Работа не может заканчиваться позже срока сдачи.
            limit = min(window[1], task.due_at)
            if limit <= window[0]:
                continue
            span = int((limit - window[0]).total_seconds() // 60)
            if span <= 0:
                continue

            if task.splittable:
                take = min(span, remaining)
            else:
                # Неделимая задача требует одно окно нужной длины.
                if span < task.estimated_min:
                    continue
                take = remaining

            if take <= 0:
                continue

            start = window[0]
            end = start + timedelta(minutes=take)
            placed.append(
                Block("task", start, end, task.title, source_id=task.id, category="task")
            )
            remaining -= take
            window[0] = end

        if remaining > 0:
            unplaced[task.id] = remaining

    return placed, unplaced, considered, capacity


# --------------------------------------------------------------------------
# Шаг 4: конфликты
# --------------------------------------------------------------------------

def detect_overlaps(busy: list[Block]) -> list[Conflict]:
    """Пересечения событий и дороги: причина конфликта должна быть видна."""
    items = sorted(
        (block for block in busy if block.source_id is not None),
        key=lambda block: block.starts_at,
    )
    conflicts: list[Conflict] = []

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[j].starts_at >= items[i].ends_at:
                break
            if items[i].source_id == items[j].source_id:
                continue
            start = max(items[i].starts_at, items[j].starts_at)
            end = min(items[i].ends_at, items[j].ends_at)
            if end <= start:
                continue
            overlap_min = int(round((end - start).total_seconds() / 60))
            first, second = items[i], items[j]
            conflicts.append(
                Conflict(
                    id=stable_id(
                        "overlap",
                        first.source_id,
                        second.source_id,
                        start.isoformat(),
                        end.isoformat(),
                    ),
                    type="overlap",
                    shortage_min=overlap_min,
                    explanation=(
                        f"«{first.title}» ({format_time(first.starts_at)}–{format_time(first.ends_at)}) "
                        f"пересекается с «{second.title}» "
                        f"({format_time(second.starts_at)}–{format_time(second.ends_at)}): "
                        f"{plural_minutes(overlap_min)} на одно время."
                    ),
                    affected_event_ids=sorted(
                        {str(first.source_id), str(second.source_id)}
                    ),
                )
            )
    return conflicts


def build_conflicts(
    plan_tasks: list[TaskRec],
    unplaced: dict[str, int],
    required_min: int,
    free_capacity_min: int,
    busy: list[Block],
    date_from: date,
    date_to: date,
) -> list[Conflict]:
    conflicts = detect_overlaps(busy)
    if not unplaced:
        return conflicts

    total_unplaced = sum(unplaced.values())
    by_id = {task.id: task for task in plan_tasks}
    affected = [task_id for task_id in unplaced if task_id in by_id]

    if required_min > free_capacity_min:
        # Общий дефицит: ровно та карточка «Не хватает N минут» из концепции.
        horizon = min(by_id[task_id].due_at for task_id in affected) if affected else None
        horizon_text = f" До {format_day(horizon)}." if horizon else ""
        conflicts.append(
            Conflict(
                id=stable_id("time_shortage", date_from.isoformat(), date_to.isoformat()),
                type="time_shortage",
                shortage_min=total_unplaced,
                explanation=(
                    f"Задачи требуют {human_duration(required_min)} свободного времени, "
                    f"а свободных окон только {human_duration(free_capacity_min)}."
                    f"{horizon_text} Не хватает {plural_minutes(total_unplaced)}."
                ),
                affected_task_ids=affected,
            )
        )
        return conflicts

    # Ёмкость есть, но задачи фрагментированы: объясняем каждую по отдельности.
    for task_id, minutes in sorted(unplaced.items(), key=lambda item: by_id[item[0]].due_at):
        task = by_id[task_id]
        reason = (
            f"нужно {plural_minutes(task.estimated_min)} подряд, "
            f"а до срока {format_day(task.due_at)} такого окна нет"
            if not task.splittable
            else f"до срока {format_day(task.due_at)} не помещается {plural_minutes(minutes)}"
        )
        conflicts.append(
            Conflict(
                id=stable_id("deadline", task.id),
                type="deadline",
                shortage_min=minutes,
                explanation=f"«{task.title}» не успевает к сроку: {reason}.",
                affected_task_ids=[task.id],
            )
        )
    return conflicts


# --------------------------------------------------------------------------
# Сборка плана
# --------------------------------------------------------------------------

def plan_revision(events: list[dict], tasks: list[dict], settings: dict) -> str:
    """Хеш исходных данных: меняется при каждой правке — контракт требует."""
    payload = json.dumps(
        {"events": events, "tasks": tasks, "settings": settings},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_plan(
    events: list[EventRec],
    tasks: list[TaskRec],
    boundaries: Boundaries,
    date_from: date,
    date_to: date,
    now: datetime,
    revision: str,
) -> PlanResult:
    tz = ZoneInfo(boundaries.timezone)
    range_start = datetime.combine(date_from, time.min, tzinfo=tz)
    range_end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)

    busy = build_busy(events, boundaries, range_start, range_end)
    windows = free_windows(busy, boundaries, range_start, range_end)
    placed, unplaced, considered, capacity = place_tasks(tasks, windows, now, range_end)
    leftover = [
        Block("free", window.starts_at, window.ends_at, "Свободно")
        for window in windows
        if window.ends_at > window.starts_at
    ]

    # Итоговые «свободные» минуты — окна, в которые ничего не разместили.
    consumed: list[tuple[datetime, datetime]] = sorted(
        ((block.starts_at, block.ends_at) for block in placed),
        key=lambda pair: pair[0],
    )
    free_min = 0
    for window in leftover:
        cursor = window.starts_at
        for start, end in consumed:
            if end <= cursor:
                continue
            if start >= window.ends_at:
                break
            if start > cursor:
                free_min += int(round((start - cursor).total_seconds() / 60))
            cursor = max(cursor, end)
            if cursor >= window.ends_at:
                break
        if cursor < window.ends_at:
            free_min += int(round((window.ends_at - cursor).total_seconds() / 60))

    planned_min = sum(block.minutes for block in busy + placed)

    conflicts = build_conflicts(
        plan_tasks=considered,
        unplaced=unplaced,
        required_min=sum(task.estimated_min for task in considered),
        free_capacity_min=capacity,
        busy=busy,
        date_from=date_from,
        date_to=date_to,
    )

    blocks = sorted(busy + placed + leftover, key=lambda block: (block.starts_at, block.ends_at))

    return PlanResult(
        revision=revision,
        date_from=date_from,
        date_to=date_to,
        blocks=blocks,
        conflicts=conflicts,
        free_min=max(0, free_min),
        planned_min=planned_min,
        considered_tasks=considered,
        unplaced=unplaced,
        free_capacity_min=capacity,
        now=now,
    )


# --------------------------------------------------------------------------
# «Что делать сейчас»
# --------------------------------------------------------------------------

def next_action(plan: PlanResult, tasks: list[TaskRec], now: datetime) -> dict:
    """Один выполнимый следующий шаг на ближайшие 15–40 минут (раздел 6.4)."""
    open_tasks = sorted(
        (task for task in tasks if task.status != "done"),
        key=lambda task: (task.due_at, 0 if task.priority == "high" else 1),
    )

    current = next(
        (
            block
            for block in plan.blocks
            if block.starts_at <= now < block.ends_at and block.kind != "free"
        ),
        None,
    )

    if current is not None:
        if current.kind == "task" and current.source_id:
            left = int((current.ends_at - now).total_seconds() // 60)
            return {
                "kind": "task",
                "title": current.title,
                "task_id": current.source_id,
                "suggested_min": max(1, left),
                "starts_at": now.isoformat(),
            }
        if current.kind == "break":
            return _rest(plan, now, title="Время отдыха")
        return {
            "kind": "event",
            "title": current.title,
            "task_id": None,
            "suggested_min": max(1, current.minutes),
            "starts_at": current.starts_at.isoformat(),
        }

    free = next(
        (
            block
            for block in plan.blocks
            if block.kind == "free" and block.starts_at <= now < block.ends_at
        ),
        None,
    )

    if free is not None:
        window_min = int((free.ends_at - now).total_seconds() // 60)
        suggestion = max(15, min(40, window_min))
        for task in open_tasks:
            if task.estimated_min <= window_min:
                return {
                    "kind": "task",
                    "title": task.title,
                    "task_id": task.id,
                    "suggested_min": min(task.estimated_min, suggestion) if task.splittable
                    else task.estimated_min,
                    "starts_at": now.isoformat(),
                }
        if open_tasks and open_tasks[0].splittable and window_min >= 15:
            task = open_tasks[0]
            return {
                "kind": "task",
                "title": task.title,
                "task_id": task.id,
                "suggested_min": suggestion,
                "starts_at": now.isoformat(),
            }
        return _rest(plan, now, title="Свободное время")

    return _rest(plan, now, title="Свободное время")


def _rest(plan: PlanResult, now: datetime, title: str) -> dict:
    upcoming = next(
        (block for block in plan.blocks if block.starts_at > now and block.kind != "free"),
        None,
    )
    if upcoming is not None:
        text = f"{title} — следующее дело в {format_time(upcoming.starts_at)}"
        starts_at = upcoming.starts_at.isoformat()
    else:
        text = f"{title} — дел по плану больше нет"
        starts_at = now.isoformat()
    return {
        "kind": "rest",
        "title": text,
        "task_id": None,
        "suggested_min": None,
        "starts_at": starts_at,
    }
