from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from max_bot import Dispatcher

from .. import db
from ..config import Settings

logger = logging.getLogger(__name__)

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


def register_handlers(dp: Dispatcher, settings: Settings, pool=None) -> None:


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


    @dp.callback()
    async def stale_action(cb):
        if not cb.payload or not cb.payload.startswith(
            ("stale_move:", "stale_drop:", "stale_keep:")
        ):
            return
        if pool is None:
            await cb.answer("Нет соединения с базой")
            return
        action, _, task_id = cb.payload.partition(":")
        try:
            async with pool.connection() as raw:
                conn = db.Connection(raw)
                user = await db.get_user_by_max_id(conn, cb.user_id)
                if not user:
                    await cb.answer("Профиль не найден")
                    return
                task = await db.get_task(conn, user["id"], task_id)
                if not task:
                    await cb.answer("Задание уже удалено")
                    return
                if action == "stale_move":
                    tz = ZoneInfo(user["settings"]["timezone"])
                    today = datetime.now(tz).date()
                    await db.update_task(
                        conn, user["id"], task_id,
                        {"due_at": f"{today.isoformat()}T23:59:59"},
                    )
                    await cb.answer("Перенесено на сегодня")
                elif action == "stale_drop":
                    await db.delete_task(conn, user["id"], task_id)
                    await cb.answer("Убрано из списка")
                else:
                    await cb.answer("Хорошо, больше не спрошу")
        except Exception:
            logger.exception("Ошибка действия по протухшему заданию %s", task_id)
            await cb.answer("Не получилось, попробуй ещё раз")

    @dp.message()
    async def fallback(msg):
        await msg.answer(FALLBACK)
