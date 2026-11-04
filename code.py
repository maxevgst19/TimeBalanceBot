"""Точка входа TimeBalance: ``python code.py``.

Запускает REST API мини-приложения и чат-бот MAX в одном процессе.
Настройки читаются из переменных окружения — см. ``.env.example``.
"""
from app.main import run
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    run()
