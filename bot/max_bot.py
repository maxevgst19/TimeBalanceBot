"""TimeBalance Bot для мессенджера MAX.

Бот — точка входа в мини-приложение: по команде /start он присылает
сообщение с кнопкой открытия приложения (кнопка типа open_app).

MAX Bot API: https://dev.max.ru/docs-api
Кнопки:      https://dev.max.ru/docs-api/use-cases/sending-messages/keyboard/
Мини-апп:    https://dev.max.ru/docs/webapps/introduction/

Запуск:
    python bot/max_bot.py
"""

import asyncio
import logging
import os
import ssl
from pathlib import Path

import certifi
import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

TOKEN = (os.getenv("MAX_BOT_TOKEN") or "").strip()
API_URL = (os.getenv("MAX_API_URL") or "https://platform-api2.max.ru").rstrip("/")

# Сертификаты Минцифры нужны для работы с API MAX (см. dev.max.ru/docs-api).
CERT_DIR = Path(__file__).resolve().parent.parent / "certs"
CA_FILES = (
    CERT_DIR / "russian_trusted_root_ca.pem",
    CERT_DIR / "russian_trusted_sub_ca.pem",
)


def build_ssl_context() -> ssl.SSLContext:
    """Системные CA + корневой и промежуточный сертификаты Минцифры."""
    context = ssl.create_default_context(cafile=certifi.where())
    for ca_file in CA_FILES:
        if ca_file.exists():
            context.load_verify_locations(cafile=str(ca_file))
        else:
            logging.warning("Не найден сертификат %s", ca_file)
    return context

WELCOME = (
    "Привет! Я TimeBalance — покажу, помещаются ли твои дела в реальный день.\n\n"
    "Внутри приложения:\n"
    "• шкала дня: школа, дорога, кружки, задания и отдых\n"
    "• честный расчёт свободного времени\n"
    "• «План Б», если дела не помещаются\n\n"
    "Открой приложение — план уже ждёт."
)

HELP = (
    "Как пользоваться\n\n"
    "1. Нажми «Открыть TimeBalance» — приложение запустится прямо в MAX.\n"
    "2. Добавь занятия и задания.\n"
    "3. Смотри шкалу дня и «План Б», если времени не хватает.\n\n"
    "Команды:\n"
    "/start — приветствие и кнопка запуска\n"
    "/help — эта справка"
)


class MaxBot:
    def __init__(self, token: str):
        self.token = token
        self.username = (os.getenv("MAX_BOT_USERNAME") or "").strip()
        self.client = httpx.AsyncClient(
            base_url=API_URL,
            headers={"Authorization": token},
            timeout=httpx.Timeout(90.0, connect=15.0),
            verify=build_ssl_context(),
        )

    async def close(self):
        await self.client.aclose()

    # ------------------------------------------------------------------ API
    async def api(self, method: str, path: str, **kwargs):
        response = await self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            logging.error(
                "MAX API %s %s -> %s: %s",
                method, path, response.status_code, response.text[:500],
            )
        response.raise_for_status()
        return response.json()

    async def load_me(self) -> dict:
        """GET /me — имя и username бота (нужны для кнопки open_app и ссылки)."""
        me = await self.api("GET", "/me")
        self.username = self.username or (me.get("username") or "")
        logging.info("Бот: %s (@%s)", me.get("name"), self.username)
        return me

    async def set_commands(self):
        """PATCH /me/commands — список команд в меню бота."""
        try:
            await self.api("PATCH", "/me/commands", json={
                "commands": [
                    {"name": "start", "description": "Открыть приложение"},
                    {"name": "help", "description": "Как пользоваться"},
                ]
            })
        except Exception as exc:  # не критично для работы
            logging.warning("Не удалось обновить команды: %s", exc)

    # ------------------------------------------------------- клавиатура
    def app_keyboard(self) -> dict | None:
        """Клавиатура с кнопкой запуска мини-приложения."""
        mode = (os.getenv("MINIAPP_MODE") or "mini_app").strip().lower()
        miniapp_url = (os.getenv("MINIAPP_URL") or "").strip()

        # Запасной режим: обычная ссылка (открывается в браузере).
        if mode == "link" and miniapp_url:
            return {
                "type": "inline_keyboard",
                "payload": {
                    "buttons": [[{
                        "type": "link",
                        "text": "Открыть TimeBalance",
                        "url": miniapp_url,
                    }]]
                },
            }

        # Основной режим: мини-приложение внутри MAX (open_app).
        if not self.username:
            return None

        return {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [[{
                    "type": "open_app",
                    "text": "Открыть TimeBalance",
                    "web_app": self.username,
                }]]
            },
        }

    # ------------------------------------------------------------ отправка
    async def send(self, text: str, *, user_id: int | None = None,
                   chat_id: int | None = None, with_button: bool = True):
        payload: dict = {"text": text}
        if with_button:
            keyboard = self.app_keyboard()
            if keyboard:
                payload["attachments"] = [keyboard]

        params: dict = {}
        if user_id is not None:
            params["user_id"] = user_id
        elif chat_id is not None:
            params["chat_id"] = chat_id
        else:
            raise ValueError("Нужен user_id или chat_id")

        await self.api("POST", "/messages", params=params, json=payload)

    async def send_welcome(self, *, user_id: int):
        await self.send(WELCOME, user_id=user_id)

    # ----------------------------------------------------------- обработка
    async def handle_update(self, update: dict):
        update_type = update.get("update_type")

        if update_type == "bot_started":
            user = update.get("user") or {}
            user_id = user.get("user_id")
            if user_id:
                await self.send_welcome(user_id=user_id)
            return

        if update_type != "message_created":
            return

        message = update.get("message") or {}
        sender = message.get("sender") or {}
        if sender.get("is_bot"):
            return

        recipient = message.get("recipient") or {}
        body = message.get("body") or {}
        text = (body.get("text") or "").strip()

        if recipient.get("chat_type") == "dialog":
            target = {"user_id": sender.get("user_id")}
        else:
            target = {"chat_id": recipient.get("chat_id")}
        if not any(target.values()):
            return

        command = text.split()[0].lower() if text else ""
        if command.startswith("/help"):
            await self.send(HELP, with_button=False, **target)
        elif command.startswith("/start"):
            await self.send_welcome(**target)
        else:
            await self.send(
                "Открой приложение — там весь план дня и «План Б».",
                **target,
            )

    # -------------------------------------------------------- long polling
    async def run(self):
        marker = None
        logging.info("Long polling запущен (%s)", API_URL)

        while True:
            params: dict = {
                "timeout": 30,
                "limit": 100,
                "types": ["message_created", "bot_started"],
            }
            if marker:
                params["marker"] = marker
            try:
                data = await self.api("GET", "/updates", params=params)
            except Exception as exc:
                logging.warning("Ошибка опроса обновлений: %s", exc)
                await asyncio.sleep(3)
                continue

            marker = data.get("marker") or marker
            for update in data.get("updates") or []:
                try:
                    await self.handle_update(update)
                except Exception:
                    logging.exception("Ошибка обработки обновления")


async def main():
    if not TOKEN:
        raise SystemExit(
            "Не найден MAX_BOT_TOKEN.\n"
            "Создай файл .env рядом с README и впиши:\n"
            "MAX_BOT_TOKEN=токен_из_business.max.ru"
        )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    bot = MaxBot(TOKEN)
    try:
        try:
            await bot.load_me()
        except httpx.ConnectError as exc:
            logging.error("Не удалось подключиться к MAX API: %s", exc)
            logging.error(
                "Проверь интернет и сертификаты в папке certs/ "
                "(корневой и промежуточный Минцифры)."
            )
            raise
        await bot.set_commands()
        await bot.run()
    finally:
        await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
