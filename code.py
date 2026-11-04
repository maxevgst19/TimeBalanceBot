"""TimeBalance — единая точка входа.

Запуск из корня проекта::

    python code.py

Что происходит:

1. Если ``MINIAPP_MODE=link`` и адрес мини-приложения не задан, поднимается
   локальный сервер с ``miniapp/`` и HTTPS-туннель (localhost.run), а найденный
   адрес подставляется в ``MINIAPP_URL`` и ``MINI_APP_URL``.
2. Запускается приложение из ``app/main.py``: REST API мини-приложения и
   чат-бот MAX в одном процессе (``python code.py``).
3. Если зависимости бэкенда не установлены, запускается облегчённый бот из
   ``bot/max_bot.py`` — тот же вход в мини-приложение без API.

Перед запуском впиши токен в ``.env``: ``MAX_BOT_TOKEN=...``
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os

from bot.max_bot import main as run_lightweight_bot
from bot.miniapp_host import DemoHost


def _backend_available() -> bool:
    """Бэкенд запускаем только при установленных зависимостях."""
    needed = ("fastapi", "uvicorn", "aiosqlite", "pymaxbot")
    return all(importlib.util.find_spec(name) is not None for name in needed)


def _start_demo_host() -> DemoHost | None:
    """Туннель нужен только запасному режиму «обычная ссылка»."""
    mode = (os.getenv("MINIAPP_MODE") or "mini_app").strip().lower()
    if mode != "link":
        return None
    if (os.getenv("MINIAPP_URL") or os.getenv("MINI_APP_URL") or "").strip():
        return None

    print("Поднимаю демо-хостинг мини-приложения...", flush=True)
    demo = DemoHost()
    url = demo.start()
    if url:
        os.environ["MINIAPP_URL"] = url
        os.environ["MINI_APP_URL"] = url
        print(f"Мини-приложение доступно по адресу:\n{url}", flush=True)
    else:
        print(
            "Не удалось поднять туннель — кнопка будет open_app "
            "(мини-приложение из настроек бота).",
            flush=True,
        )
    return demo


def _run_backend() -> None:
    import uvicorn

    from app.config import Settings
    from app.main import create_app

    settings = Settings.from_env()
    logging.info("Запускаю бэкенд: API + бот MAX")
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )


def main_entry() -> None:
    demo = _start_demo_host()
    try:
        if os.getenv("TIMEBALANCE_BACKEND", "1").strip().lower() not in {
            "0",
            "false",
            "off",
            "no",
        } and _backend_available():
            _run_backend()
        else:
            print(
                "Бэкенд недоступен (нет fastapi/uvicorn/aiosqlite/pymaxbot) — "
                "запускаю облегчённого бота из bot/max_bot.py.",
                flush=True,
            )
            asyncio.run(run_lightweight_bot())
    except KeyboardInterrupt:
        print("\nОстановлено", flush=True)
    finally:
        if demo:
            demo.stop()


if __name__ == "__main__":
    main_entry()
