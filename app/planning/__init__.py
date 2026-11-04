"""Алгоритм планирования TimeBalance: интервалы, конфликты, «План Б»."""
from .engine import build_plan, next_action, plan_revision
from .model import Block, Boundaries, Conflict, EventRec, PlanResult, TaskRec

__all__ = [
    "Block",
    "Boundaries",
    "Conflict",
    "EventRec",
    "PlanResult",
    "TaskRec",
    "build_plan",
    "next_action",
    "plan_revision",
]
