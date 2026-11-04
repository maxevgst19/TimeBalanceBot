"""Регрессионные тесты замечаний ревью.

1. «План Б» не должен показывать ложное улучшение: после сдвига события
   ``conflict_id`` пересечения меняется, хотя пересечение осталось.
2. Повторяющееся занятие не должно появляться раньше начальной даты серии.
3. ``Settings.from_env()`` подхватывает ``.env`` из корня проекта, но реальные
   переменные окружения имеют приоритет.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.planning.alternatives import residual_deficit
from app.planning.engine import build_plan, occurrences
from app.planning.model import Boundaries, EventRec

TZ = ZoneInfo("Europe/Moscow")
DAY = date(2026, 11, 3)  # вторник
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=TZ)

BOUNDARIES = Boundaries(
    timezone="Europe/Moscow",
    day_start=time(7, 0),
    day_end=time(21, 0),
    break_after_school_min=0,
)


def at(hour: int, minute: int, day: date = DAY) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=TZ)


def _shift(event: EventRec, minutes: int) -> EventRec:
    return type(event)(
        **{
            **event.__dict__,
            "starts_at": event.starts_at + timedelta(minutes=minutes),
            "ends_at": event.ends_at + timedelta(minutes=minutes),
        }
    )


# --------------------------------------------------------------------------
# 1. Ложное улучшение в «Плане Б»
# --------------------------------------------------------------------------

def test_residual_deficit_keeps_counting_after_id_changes():
    """Пересечение осталось → остаток не равен 0, хоть id и сменился.

    Раньше остаток искался по прежнему ``conflict_id``: сдвинутое событие
    даёт новый id (он собирается из времени), находки не было — и вариант
    отчитывался о нуле, как будто пересечения больше нет.
    """
    first = EventRec(
        id="ev-a",
        title="Урок",
        category="school",
        starts_at=at(10, 0),
        ends_at=at(11, 0),
    )
    second = EventRec(
        id="ev-b",
        title="Кружок",
        category="extra",
        starts_at=at(10, 30),
        ends_at=at(12, 0),
        movable=True,
    )

    original = build_plan([first, second], [], BOUNDARIES, DAY, DAY, NOW, "rev")
    conflict = next(c for c in original.conflicts if c.type == "overlap")
    assert conflict.shortage_min == 30

    # Сдвиг на 15 минут: пересечение 10:45–11:00 осталось, но id другой.
    shifted = build_plan(
        [first, _shift(second, 15)], [], BOUNDARIES, DAY, DAY, NOW, "rev"
    )
    new_conflicts = [c for c in shifted.conflicts if c.type == "overlap"]
    assert new_conflicts, "пересечение должно сохраниться"
    assert new_conflicts[0].id != conflict.id, "id действительно изменился"

    residual = residual_deficit(shifted, conflict, original)
    assert residual == 15, f"остаток 0 показал бы ложное улучшение, got {residual}"
    assert residual < conflict.shortage_min, "но улучшение всё же есть"


def test_residual_deficit_is_zero_when_overlap_actually_resolved():
    """Честное решение: пересечение ушло → остаток 0, вариант показывается."""
    first = EventRec(
        id="ev-a",
        title="Урок",
        category="school",
        starts_at=at(10, 0),
        ends_at=at(11, 0),
    )
    second = EventRec(
        id="ev-b",
        title="Кружок",
        category="extra",
        starts_at=at(10, 30),
        ends_at=at(12, 0),
        movable=True,
    )

    original = build_plan([first, second], [], BOUNDARIES, DAY, DAY, NOW, "rev")
    conflict = next(c for c in original.conflicts if c.type == "overlap")

    # Сдвиг на 90 минут: 12:00–13:30, пересечения с 10:00–11:00 нет.
    fixed = build_plan(
        [first, _shift(second, 90)], [], BOUNDARIES, DAY, DAY, NOW, "rev"
    )
    assert not [c for c in fixed.conflicts if c.type == "overlap"]
    assert residual_deficit(fixed, conflict, original) == 0


def test_residual_deficit_counts_new_overlap_as_regression():
    """Перенос снял пересечение, но породил новое — это не улучшение до нуля."""
    first = EventRec(
        id="ev-a",
        title="Урок",
        category="school",
        starts_at=at(10, 0),
        ends_at=at(11, 0),
    )
    second = EventRec(
        id="ev-b",
        title="Кружок",
        category="extra",
        starts_at=at(10, 30),
        ends_at=at(11, 30),
        movable=True,
    )
    third = EventRec(
        id="ev-c",
        title="Тренировка",
        category="extra",
        starts_at=at(13, 0),
        ends_at=at(14, 0),
    )

    original = build_plan(
        [first, second, third], [], BOUNDARIES, DAY, DAY, NOW, "rev"
    )
    conflict = next(c for c in original.conflicts if c.type == "overlap")
    assert conflict.shortage_min == 30

    # Сдвиг на 150 минут: 13:00–14:00 → новое пересечение с тренировкой.
    moved = build_plan(
        [first, _shift(second, 150), third], [], BOUNDARIES, DAY, DAY, NOW, "rev"
    )
    assert [c for c in moved.conflicts if c.type == "overlap"]
    assert residual_deficit(moved, conflict, original) > 0


# --------------------------------------------------------------------------
# 2. Повторение раньше начальной даты серии
# --------------------------------------------------------------------------

def test_recurrence_never_appears_before_series_start():
    """Серия по вторникам, начало 10 ноября — 3 ноября быть не должно."""
    weekly = EventRec(
        id="ev-weekly",
        title="Секция",
        category="extra",
        starts_at=at(16, 0, date(2026, 11, 10)),  # вторник
        ends_at=at(17, 30, date(2026, 11, 10)),
        weekdays=(2,),
    )
    range_start = at(0, 0, date(2026, 11, 3))
    range_end = at(0, 0, date(2026, 11, 11))

    found = occurrences(weekly, range_start, range_end)
    assert [start.date() for start, _ in found] == [date(2026, 11, 10)]


def test_recurrence_counts_days_before_and_after_start():
    """До старта серии — пусто, после — все положенные даты."""
    weekly = EventRec(
        id="ev-weekly",
        title="Секция",
        category="extra",
        starts_at=at(16, 0, date(2026, 11, 10)),
        ends_at=at(17, 30, date(2026, 11, 10)),
        weekdays=(2,),
    )
    # Диапазон целиком до начала серии.
    before = occurrences(weekly, at(0, 0, date(2026, 11, 3)), at(0, 0, date(2026, 11, 9)))
    assert before == []

    # Три вторника после старта.
    after = occurrences(weekly, at(0, 0, date(2026, 11, 10)), at(0, 0, date(2026, 11, 30)))
    assert [start.date() for start, _ in after] == [
        date(2026, 11, 10),
        date(2026, 11, 17),
        date(2026, 11, 24),
    ]


# --------------------------------------------------------------------------
# 3. Загрузка .env
# --------------------------------------------------------------------------

def test_settings_load_dotenv_from_project_root(tmp_path_factory):
    """``.env`` в корне читается автоматически, если переменная не задана явно."""
    from pathlib import Path

    from app.config import Settings

    root = Path(__file__).resolve().parent.parent
    dotenv_path = root / ".env"
    backup = dotenv_path.read_text(encoding="utf-8") if dotenv_path.exists() else None
    sentinel = f"MINI_APP_URL=https://dotenv.example/{os.getpid()}"

    # Очищаем переменную, чтобы она могла прийти только из .env.
    had_var = "MINI_APP_URL" in os.environ
    old_var = os.environ.pop("MINI_APP_URL", None)
    touched: list[str] = []
    try:
        dotenv_path.write_text(sentinel + "\n", encoding="utf-8")
        settings = Settings.from_env()
        assert settings.mini_app_url.startswith("https://dotenv.example/")

        # Реальная переменная окружения сильнее файла.
        os.environ["MINI_APP_URL"] = "https://env-wins.example/"
        touched.append("MINI_APP_URL")
        assert Settings.from_env().mini_app_url == "https://env-wins.example/"
    finally:
        for key in touched:
            os.environ.pop(key, None)
        if old_var is not None or had_var:
            os.environ["MINI_APP_URL"] = old_var
        if backup is None:
            dotenv_path.unlink(missing_ok=True)
        else:
            dotenv_path.write_text(backup, encoding="utf-8")
