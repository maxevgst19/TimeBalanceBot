"""Точка входа: ``python code.py`` — БД + REST API + бот MAX, одна команда.

При запуске поднимает локальный PostgreSQL и прописывает DATABASE_URL.
При завершении процесса (Ctrl+C, остановка в PyCharm, диспетчер задач)
postgres останавливается и исчезает из диспетчера задач.
"""
import asyncio
import sys

from dotenv import load_dotenv

if sys.platform == "win32":
    # psycopg на Windows не работает с ProactorEventLoop — нужен SelectorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    load_dotenv()

    from dbserver import ensure_server

    ensure_server(cleanup_mode="stop", die_with_process=True)

    from app.main import run

    run()
