"""Роутеры REST API мини-приложения (контракт — openapi.yaml)."""
from . import auth, events, planning, profile, tasks

__all__ = ["auth", "events", "planning", "profile", "tasks"]
