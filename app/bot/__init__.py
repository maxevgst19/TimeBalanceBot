"""Чат-бот MAX: проводник в мини-приложение и канал уведомлений."""
from .handlers import register_handlers
from .notifier import run_notifier

__all__ = ["register_handlers", "run_notifier"]
