"""Поднимает локальную БД вручную (отдельно от сервера) и пишет DATABASE_URL в .env.

Обычно не нужен: ``code.py`` поднимает БД сам. Оставлен для запуска базы без сервера.
"""
from dbserver import ensure_server

print("READY " + ensure_server(cleanup_mode=None))
