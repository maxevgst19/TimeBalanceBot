"""Редкие важные уведомления от сервера в чат MAX.

Уведомления не отправляются на каждый пересчёт (DESIGN_STANDARD.md, раздел 8):
одна причина — одно сообщение, дедупликация по таблице ``notifications_sent``.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import aiosqlite

from .. import db
from ..config import Settings
from ..plan_service import compute_plan
from ..planning.engine import format_time, plural_minutes

logger = logging.getLogger(__name__)

WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)

REMINDER_WINDOW_MIN = 15


async def _send(bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text=text, format="html")
    except Exception:  # noqa: BLE001 - сбой отправки не должен ронять планировщик
        logger.exception("Не удалось отправить уведомление пользователю %s", user_id)


async def check_user(
    bot, conn: aiosqlite.Connection, settings: Settings, user: dict
) -> None:
    if not user["settings"]["notifications_enabled"]:
        return
    max_user_id = user.get("max_user_id")
    if not max_user_id:
        return

    tz = ZoneInfo(user["settings"]["timezone"])
    now = datetime.now(tz)
    today = now.date()

    plan, _events, _tasks = await compute_plan(
        conn, user, today, today + timedelta(days=1), settings.day_start, now=now
    )

    # 1. Перегрузка дня — одно сообщение в сутки.
    overload = max(
        (c for c in plan.conflicts if c.shortage_min > 0),
        key=lambda c: c.shortage_min,
        default=None,
    )
    if overload is not None:
        key = today.isoformat()
        if not await db.already_notified(conn, user["id"], "overload", key):
            day_name = WEEKDAYS_RU[now.weekday()]
            text = (
                f"<b>{day_name.capitalize()} перегружена</b>: "
                f"не хватает {plural_minutes(overload.shortage_min)}.\n"
                "Открой мини-приложение и собери «План Б»."
            )
            await _send(bot, max_user_id, text)
            await db.mark_notified(conn, user["id"], "overload", key)

    # 2. Скоро начинается событие — напоминание один раз на экземпляр.
    for block in plan.blocks:
        if block.kind != "event":
            continue
        minutes_left = int((block.starts_at - now).total_seconds() // 60)
        if not 0 <= minutes_left <= REMINDER_WINDOW_MIN:
            continue
        key = f"{block.source_id}:{block.starts_at.isoformat()}"
        if await db.already_notified(conn, user["id"], "event", key):
            continue
        await _send(
            bot,
            max_user_id,
            f"Через {plural_minutes(max(1, minutes_left))}: "
            f"<b>{block.title}</b> в {format_time(block.starts_at)}.",
        )
        await db.mark_notified(conn, user["id"], "event", key)


async def run_notifier(
    bot,
    conn: aiosqlite.Connection,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    logger.info("Планировщик уведомлений запущен")
    while not stop.is_set():
        try:
            async with conn.execute(
                "SELECT * FROM users WHERE notifications_enabled = 1 "
                "AND max_user_id IS NOT NULL"
            ) as cur:
                users = await cur.fetchall()
            for row in users:
                if stop.is_set():
                    break
                user = db.row_to_user(row)
                try:
                    await check_user(bot, conn, settings, user)
                except Exception:  # noqa: BLE001
                    logger.exception("Ошибка проверки пользователя %s", user["id"])
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка цикла уведомлений")

        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.notifier_interval_seconds)
        except asyncio.TimeoutError:
            pass
    logger.info("Планировщик уведомлений остановлен")
