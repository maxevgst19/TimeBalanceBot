"""Модели запросов и ответов, повторяющие контракт openapi.yaml."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Общие
# --------------------------------------------------------------------------

class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Auth / Profile
# --------------------------------------------------------------------------

class AuthMaxRequest(BaseModel):
    init_data: str = Field(min_length=1)


class Settings(BaseModel):
    timezone: str = Field(min_length=1, examples=["Europe/Moscow"])
    day_end: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$", examples=["21:00"])
    break_after_school_min: int = Field(ge=0, le=180)
    notifications_enabled: bool


class SettingsPatch(BaseModel):
    timezone: str | None = Field(default=None, min_length=1)
    day_end: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    break_after_school_min: int | None = Field(default=None, ge=0, le=180)
    notifications_enabled: bool | None = None


class User(BaseModel):
    id: str
    display_name: str | None = None
    settings: Settings


class SessionResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(ge=1)
    user: User


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

class Recurrence(BaseModel):
    weekdays: list[int] = Field(min_length=1, max_length=7)
    until: date | None = None

    @field_validator("weekdays")
    @classmethod
    def _check_weekdays(cls, value: list[int]) -> list[int]:
        if any(day < 1 or day > 7 for day in value):
            raise ValueError("weekdays must be between 1 and 7")
        if len(set(value)) != len(value):
            raise ValueError("weekdays must be unique")
        return sorted(value)


class EventInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    category: Literal["school", "extra", "personal"]
    starts_at: datetime
    ends_at: datetime
    travel_before_min: int = Field(default=0, ge=0, le=240)
    travel_after_min: int = Field(default=0, ge=0, le=240)
    movable: bool = False
    recurrence: Recurrence | None = None


class EventPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    category: Literal["school", "extra", "personal"] | None = None
    recurrence: Recurrence | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    travel_before_min: int | None = Field(default=None, ge=0, le=240)
    travel_after_min: int | None = Field(default=None, ge=0, le=240)
    movable: bool | None = None


class Event(EventInput):
    id: str
    series_starts_at: datetime | None = None


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

class TaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    due_at: datetime
    estimated_min: int = Field(ge=5, le=480)
    splittable: bool = True
    priority: Literal["normal", "high"] = "normal"


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    due_at: datetime | None = None
    estimated_min: int | None = Field(default=None, ge=5, le=480)
    splittable: bool | None = None
    priority: Literal["normal", "high"] | None = None
    status: Literal["todo", "in_progress", "done"] | None = None
    spent_min: int | None = Field(default=None, ge=0)
    started_at_ms: int | None = Field(default=None, ge=0)


class Task(TaskInput):
    id: str
    status: Literal["todo", "in_progress", "done"]
    spent_min: int = Field(ge=0)
    started_at_ms: int = Field(ge=0)


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

class TimeBlock(BaseModel):
    kind: Literal["event", "task", "travel", "break", "free"]
    source_id: str | None = None
    starts_at: datetime
    ends_at: datetime
    title: str
    # Дополнительно к openapi.yaml: нужно мини-приложению для цветовой категории
    # и отметки о переносимости (DESIGN_STANDARD.md, разделы 4 и 7).
    category: str | None = None
    movable: bool | None = None


class PlanConflict(BaseModel):
    id: str
    type: Literal["time_shortage", "overlap", "deadline"]
    shortage_min: int = Field(ge=0)
    explanation: str
    affected_task_ids: list[str] = []


class Plan(BaseModel):
    revision: str
    from_: date = Field(alias="from")
    to: date
    blocks: list[TimeBlock]
    conflicts: list[PlanConflict]
    free_min: int = Field(ge=0)
    planned_min: int = Field(ge=0)

    model_config = {"populate_by_name": True}


class NextAction(BaseModel):
    kind: Literal["task", "event", "rest"]
    title: str
    task_id: str | None = None
    suggested_min: int | None = Field(default=None, ge=0)
    starts_at: datetime | None = None


class AlternativesRequest(BaseModel):
    conflict_id: str
    plan_revision: str


class ApplyRequest(BaseModel):
    plan_revision: str


class Alternative(BaseModel):
    id: str
    title: str
    explanation: str
    changes: list[str]
    remaining_shortage_min: int = Field(ge=0)
