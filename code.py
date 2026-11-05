"""Точка входа TimeBalance: ``python code.py``.

Запускает REST API мини-приложения и чат-бот MAX в одном процессе.
Настройки читаются из переменных окружения — см. ``.env.example``.
"""
import asyncio
import sys

from app.main import run
from dotenv import load_dotenv

if sys.platform == "win32":
    # psycopg на Windows не работает с ProactorEventLoop — нужен SelectorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    load_dotenv()
    run()
