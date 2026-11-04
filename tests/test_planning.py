"""Тесты алгоритма планирования: окна, раскладка, конфликты, «Что сейчас»."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.planning.engine import (
    build_busy,
    build_plan,
    free_windows,
    next_action,
    occurrences,
    plan_revision,
)
from app.planning.model import Boundaries, EventRec, TaskRec

TZ = ZoneInfo("Europe/Moscow")
DAY = date(2026, 11, 3)  # вторник
RANGE_END = date(2026, 11, 3)
# Конец диапазона «включительно»: 00:00 следующего дня.
RANGE_END_DT = datetime.combine(DAY + timedelta(days=1), time.min, tzinfo=TZ)
NOW = datetime(2026, 11, 3, 10, 0, tzinfo=TZ)

BOUNDARIES = Boundaries(
    timezone="Europe/Moscow",
    day_start=time(7, 0),
    day_end=time(21, 0),
    break_after_school_min=30,
)


def at(hour: int, minute: int, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def school(day: date = DAY) -> EventRec:
    return EventRec(
        id="ev-school",
        title="Школа",
        category="school",
        starts_at=datetime.combine(day, time(8, 0), tzinfo=TZ),
        ends_at=datetime.combine(day, time(14, 0), tzinfo=TZ),
    )


def club(day: date = DAY) -> EventRec:
    return EventRec(
        id="ev-club",
        title="Секция",
        category="extra",
        starts_at=datetime.combine(day, time(16, 0), tzinfo=TZ),
        ends_at=datetime.combine(day, time(17, 30), tzinfo=TZ),
        travel_before_min=25,
        travel_after_min=25,
    )


def task(
    task_id: str,
    minutes: int,
    due_hour: int = 23,
    due_minute: int = 59,
    **kwargs,
) -> TaskRec:
    return TaskRec(
        id=task_id,
        title=kwargs.pop("title", f"Задание {task_id}"),
        due_at=at(due_hour, due_minute) + timedelta(**kwargs.pop("due_kwargs", {})),
        estimated_min=minutes,
        **kwargs,
    )


def make_plan(events, tasks, now=NOW, day_from=DAY, day_to=RANGE_END):
    return build_plan(
        events, tasks, BOUNDARIES, day_from, day_to, now, revision="test-revision"
    )


# --------------------------------------------------------------------------
# Свободные окна
# --------------------------------------------------------------------------

def test_free_windows_account_for_school_travel_and_break():
    """Между школой и секцией окно сокращено на дорогу и перерыв после школы."""
    busy = build_busy([school(), club()], BOUNDARIES, at(0, 0), RANGE_END_DT)
    windows = free_windows(busy, BOUNDARIES, at(0, 0), RANGE_END_DT)
    spans = [(w.starts_at.strftime("%H:%M"), w.ends_at.strftime("%H:%M")) for w in windows]
    # Дорога обратно занимает 17:30–17:55, поэтому окно начинается в 17:55.
    assert spans == [("07:00", "08:00"), ("14:30", "15:35"), ("17:55", "21:00")]


def test_free_windows_never_cross_day_end():
    busy = build_busy([], BOUNDARIES, at(0, 0), RANGE_END_DT)
    windows = free_windows(busy, BOUNDARIES, at(0, 0), RANGE_END_DT)
    assert all(w.ends_at <= at(21, 0) for w in windows)


# --------------------------------------------------------------------------
# Раскладка задач
# --------------------------------------------------------------------------

def test_task_fits_into_free_window():
    plan = make_plan([school(), club()], [task("t1", 40)])
    task_blocks = [b for b in plan.blocks if b.kind == "task"]
    assert len(task_blocks) == 1
    assert plan.unplaced == {}
    # Задание встаёт в первое свободное окно после перерыва.
    assert task_blocks[0].starts_at == at(14, 30)
    assert task_blocks[0].ends_at == at(15, 10)


def test_splittable_task_is_split_across_windows():
    plan = make_plan([school(), club()], [task("t1", 200)])
    blocks = [b for b in plan.blocks if b.kind == "task"]
    assert len(blocks) > 1, "длинная делимая задача должна разделиться на части"
    assert sum(b.minutes for b in blocks) == 200
    assert plan.unplaced == {}


def test_shortage_is_reported_with_exact_minutes():
    """Дефицит считается по факту: 280 минут задач при 250 свободных."""
    plan = make_plan([school(), club()], [task("t1", 100), task("t2", 180)])
    assert plan.unplaced == {"t2": 30}

    shortage = next(c for c in plan.conflicts if c.type == "time_shortage")
    assert shortage.shortage_min == 30
    assert "30" in shortage.explanation
    # Под риском — только то, что не помещается: t1 встал целиком.
    assert set(shortage.affected_task_ids) == {"t2"}


def test_no_conflict_when_everything_fits():
    plan = make_plan([school(), club()], [task("t1", 40), task("t2", 60)])
    assert plan.unplaced == {}
    assert plan.conflicts == []


def test_non_splittable_task_needs_single_window():
    """Задача на 90 минут не делимая: в окне 65 минут она не помещается."""
    plan = make_plan(
        [school(), club()], [task("t1", 90, splittable=False)]
    )
    # Длинное окно 18:00–21:00 есть, поэтому неделимая задача встаёт целиком.
    assert plan.unplaced == {}


def test_non_splittable_task_fails_when_no_window_is_long_enough():
    evening = EventRec(
        id="ev-evening",
        title="Вечерние занятия",
        category="extra",
        starts_at=at(19, 0),
        ends_at=at(21, 0),
    )
    plan = make_plan(
        [school(), club(), evening],
        [task("t1", 90, splittable=False)],
    )
    assert plan.unplaced == {"t1": 90}
    deadline = next(c for c in plan.conflicts if c.type == "deadline")
    assert deadline.shortage_min == 90
    assert deadline.affected_task_ids == ["t1"]


def test_tasks_are_never_placed_after_day_end():
    plan = make_plan([school(), club()], [task("t1", 400)])
    assert all(b.ends_at <= at(21, 0) for b in plan.blocks if b.kind == "task")


def test_finished_tasks_are_not_planned():
    done = TaskRec(
        id="t1",
        title="Сделано",
        due_at=at(23, 59),
        estimated_min=120,
        status="done",
    )
    plan = make_plan([school(), club()], [done])
    assert [b for b in plan.blocks if b.kind == "task"] == []


# --------------------------------------------------------------------------
# Пересечения
# --------------------------------------------------------------------------

def test_overlap_between_events_is_reported():
    extra = EventRec(
        id="ev-extra",
        title="Кружок",
        category="extra",
        starts_at=at(13, 0),
        ends_at=at(15, 0),
    )
    plan = make_plan([school(), extra], [])
    overlap = next(c for c in plan.conflicts if c.type == "overlap")
    assert overlap.shortage_min == 60
    assert "Школа" in overlap.explanation and "Кружок" in overlap.explanation


def test_travel_overlapping_next_event_is_reported():
    """Дорога до секции заходит на урок — это тоже конфликт."""
    late_school = EventRec(
        id="ev-school",
        title="Школа",
        category="school",
        starts_at=at(8, 0),
        ends_at=at(15, 50),
    )
    plan = make_plan([late_school, club()], [])
    assert any(c.type == "overlap" for c in plan.conflicts)


# --------------------------------------------------------------------------
# Ревизия и повторения
# --------------------------------------------------------------------------

def test_revision_changes_when_data_changes():
    a = plan_revision([{"id": 1}], [], {"day_end": "21:00"})
    b = plan_revision([{"id": 1}], [], {"day_end": "22:00"})
    c = plan_revision([{"id": 1}], [], {"day_end": "21:00"})
    assert a != b
    assert a == c


def test_weekly_recurrence_expands_within_range():
    weekly = EventRec(
        id="ev-weekly",
        title="Секция",
        category="extra",
        starts_at=at(16, 0),
        ends_at=at(17, 30),
        weekdays=(2,),  # вторник
    )
    found = occurrences(weekly, at(0, 0), RANGE_END_DT)
    assert len(found) == 1

    two_weeks = occurrences(weekly, at(0, 0), at(23, 59) + timedelta(days=13))
    assert len(two_weeks) == 2


def test_recurrence_until_stops_series():
    weekly = EventRec(
        id="ev-weekly",
        title="Секция",
        category="extra",
        starts_at=at(16, 0),
        ends_at=at(17, 30),
        weekdays=(2,),
        until=DAY,
    )
    found = occurrences(weekly, at(0, 0), at(23, 59) + timedelta(days=14))
    assert len(found) == 1


# --------------------------------------------------------------------------
# «Что делать сейчас»
# --------------------------------------------------------------------------

def test_next_action_during_lesson_is_the_lesson():
    plan = make_plan([school(), club()], [task("t1", 40)])
    action = next_action(plan, [task("t1", 40)], at(10, 0))
    assert action["kind"] == "event"
    assert action["title"] == "Школа"


def test_next_action_during_break_is_rest():
    plan = make_plan([school(), club()], [task("t1", 40)])
    action = next_action(plan, [task("t1", 40)], at(14, 15))
    assert action["kind"] == "rest"
    assert "отдыха" in action["title"]


def test_next_action_in_free_window_offers_a_task():
    """Свободное окно + невыполненное задание → конкретный шаг на 15–40 минут."""
    tasks = [task("t1", 100)]
    plan = make_plan([school(), club()], tasks)
    action = next_action(plan, tasks, at(19, 0))
    assert action["kind"] == "task"
    assert action["task_id"] == "t1"
    assert 15 <= action["suggested_min"] <= 40


def test_next_action_after_day_end_is_rest():
    tasks = [task("t1", 40)]
    plan = make_plan([school(), club()], tasks)
    action = next_action(plan, tasks, at(22, 0))
    assert action["kind"] == "rest"
