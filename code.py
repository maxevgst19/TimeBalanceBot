"""Точка входа TimeBalance: ``python code.py``.

Запускает REST API мини-приложения и чат-бот MAX в одном процессе.
Настройки читаются из переменных окружения — см. ``.env.example``.
"""
from app.main import run

if __name__ == "__main__":
    run()
