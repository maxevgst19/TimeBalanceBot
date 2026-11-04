"""Базовые типы алгоритма планирования.

Даты везде осознанные (с часовым поясом). Длительности — в минутах.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

# Стабильный источник имён: один и тот же конфликт получает один и тот же id,
# пока исходные данные не изменились. Без этого нельзя запрашивать «План Б»
# для конфликта, показанного на предыдущем экране.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "timebalance.max")


def stable_id(*parts: object) -> str:
    return str(uuid.uuid5(NAMESPACE, "|".join(str(part) for part in parts)))


@dataclass(frozen=True)
class EventRec:
    id: str
    title: str
    category: str
    starts_at: datetime
    ends_at: datetime
    travel_before_min: int = 0
    travel_after_min: int = 0
    movable: bool = False
    weekdays: tuple[int, ...] | None = None
    until: date | None = None


@dataclass(frozen=True)
class TaskRec:
    id: str
    title: str
    due_at: datetime
    estimated_min: int
    splittable: bool = True
    priority: str = "normal"
    status: str = "todo"


@dataclass(frozen=True)
class Boundaries:
    """Личные границы учебного дня (PROJECT_CONCEPT.md, раздел 6.5)."""

    timezone: str
    day_start: time
    day_end: time
    break_after_school_min: int


@dataclass
class Block:
    kind: str  # event | travel | break | task | free
    starts_at: datetime
    ends_at: datetime
    title: str
    source_id: str | None = None
    category: str | None = None
    movable: bool = False

    @property
    def minutes(self) -> int:
        return max(0, int(round((self.ends_at - self.starts_at).total_seconds() / 60)))


@dataclass
class Conflict:
    id: str
    type: str
    shortage_min: int
    explanation: str
    affected_task_ids: list[str] = field(default_factory=list)
    # Внутреннее поле: нужно, чтобы «План Б» знал, какое событие переносить.
    # В ответ API не сериализуется.
    affected_event_ids: list[str] = field(default_factory=list)


@dataclass
class PlanResult:
    revision: str
    date_from: date
    date_to: date
    blocks: list[Block]
    conflicts: list[Conflict]
    free_min: int
    planned_min: int
    considered_tasks: list[TaskRec] = field(default_factory=list)
    unplaced: dict[str, int] = field(default_factory=dict)
    free_capacity_min: int = 0
    now: datetime | None = None
