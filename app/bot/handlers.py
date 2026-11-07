"""Чат-бот MAX — точка входа в мини-приложение.

Роль бота ограничена (PROJECT_CONCEPT.md, раздел 8): дать короткое описание
и кнопку перехода в мини-приложение, а также доставлять редкие важные
уведомления от сервера. Планирование в чате не выполняется.
"""
from __future__ import annotations

from max_bot import Dispatcher

from ..config import Settings

WELCOME = (
    "<b>TimeBalance</b> — помогает понять, помещаются ли твои дела в реальный день.\n\n"
    "Расписание, дорога, задания и отдых живут на одной шкале. Если дел не "
    "хватает времени, бот покажет, сколько минут не хватает, и предложит "
    "«План Б».\n\n"
    "Всё планируется в мини-приложении — здесь только вход и уведомления."
)

ABOUT = (
    "<b>Как это работает</b>\n\n"
    "1. Добавь расписание — уроки, кружки и дорогу.\n"
    "2. Добавь задания: название, срок и примерную длительность.\n"
    "3. Экран «Сегодня» покажет свободные окна и ближайший риск.\n"
    "4. Если дела не помещаются — собери «План Б» и выбери вариант.\n\n"
    "План пересчитывается сразу после выбора."
)

FALLBACK = (
    "Я только провожу в мини-приложение: нажми «Открыть мини-приложение» "
    "или напиши /start."
)


def register_handlers(dp: Dispatcher, settings: Settings) -> None:
    """Регистрирует обработчики. Порядок важен: Dispatcher берёт первый подходящий."""

    @dp.message(commands=["start"])
    async def start(msg):
        await msg.answer(
            WELCOME,
            format="html",
            buttons=[
                [{"type": "open_app", "text": "Открыть мини-приложение"}],
                [{"text": "Как это работает", "payload": "about"}],
            ],
        )

    @dp.message(commands=["help"])
    async def help_command(msg):
        await msg.answer(
            "<b>Команды</b>\n"
            "/start — описание и вход в мини-приложение\n"
            "/help — эта справка",
            format="html",
            buttons=[[{"type": "open_app", "text": "Открыть мини-приложение"}]],
        )

    @dp.callback(payloads=["about"])
    async def about(cb):
        await cb.answer()
        await cb.reply(ABOUT, format="html")

    @dp.message()
    async def fallback(msg):
        await msg.answer(FALLBACK)
