"""TimeBalance — точка входа.

Запуск из корня проекта::

    python code.py

Что происходит:

1. Если ``MINIAPP_MODE=link`` и адрес мини-приложения не задан, поднимается
   локальный сервер с ``miniapp/`` и HTTPS-туннель (localhost.run).
   Найденный адрес подставляется в ``MINIAPP_URL``.
2. Запускается бот MAX из ``bot/max_bot.py``.

Перед запуском впиши токен в ``.env``: ``MAX_BOT_TOKEN=...``
"""

from __future__ import annotations

import asyncio
import os

from bot.max_bot import main as run_bot
from bot.miniapp_host import DemoHost


def _start_demo_host() -> DemoHost | None:
    """Туннель нужен только запасному режиму «обычная ссылка»."""
    mode = (os.getenv("MINIAPP_MODE") or "mini_app").strip().lower()
    if mode != "link":
        return None
    if (os.getenv("MINIAPP_URL") or "").strip():
        return None

    print("Поднимаю демо-хостинг мини-приложения...", flush=True)
    demo = DemoHost()
    url = demo.start()
    if url:
        os.environ["MINIAPP_URL"] = url
        print(f"Мини-приложение доступно по адресу:\n{url}", flush=True)
    else:
        print(
            "Не удалось поднять туннель — кнопка будет open_app "
            "(мини-приложение из настроек бота).",
            flush=True,
        )
    return demo


def main_entry() -> None:
    demo = _start_demo_host()
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\nБот остановлен", flush=True)
    finally:
        if demo:
            demo.stop()


if __name__ == "__main__":
    main_entry()
