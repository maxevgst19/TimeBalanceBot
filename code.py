"""TimeBalance Bot — точка входа.

Запуск из корня проекта:
    python code.py

Что происходит:
1. Если в .env не задан MINIAPP_URL, поднимается локальный сервер с miniapp/
   и HTTPS-туннель (localhost.run). Кнопка в боте ведёт на этот адрес.
2. Запускается бот MAX из bot/max_bot.py.

Перед запуском впиши токен в .env:  MAX_BOT_TOKEN=...
"""

import asyncio
import os

from bot.miniapp_host import DemoHost
from bot.max_bot import main


def main_entry():
    mode = (os.getenv("MINIAPP_MODE") or "mini_app").strip().lower()
    demo = None

    # Туннель нужен только для запасного режима «обычная ссылка».
    if mode == "link" and not (os.getenv("MINIAPP_URL") or "").strip():
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

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nБот остановлен", flush=True)
    finally:
        if demo:
            demo.stop()


if __name__ == "__main__":
    main_entry()
