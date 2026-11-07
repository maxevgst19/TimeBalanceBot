"""Редкие важные уведомления от сервера в чат MAX.

Уведомления не отправляются на каждый пересчёт (DESIGN_STANDARD.md, раздел 8):
одна причина — одно сообщение, дедупликация по таблице ``notifications_sent``.
"""
from __future__ import annotations

import asyncio
import html
import logging
from html import escape
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from psycopg_pool import AsyncConnectionPool


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

MONTHS_RU = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

REMINDER_WINDOW_MIN = 15

# «Протухшие» задания: старше STALE_DAYS дней — тихий вопрос вместо свалки.
STALE_DAYS = 14
STALE_MAX_PER_CYCLE = 3

# Сколько минут заложить на сборы, когда напоминаем, когда вставать.
WAKE_PREP_MIN = 20

def _ru_date(iso_date: str) -> str:
    """«2026-10-21» → «21 октября»."""
    try:
        day, month = int(iso_date[8:10]), int(iso_date[5:7])
        return f"{day} {MONTHS_RU[month - 1]}"
    except (ValueError, IndexError):
        return iso_date


async def _send(bot, user_id: int, text: str, buttons=None) -> bool:
    try:
        await bot.send_message(user_id, text=text, format="html", buttons=buttons)
        return True
    except Exception:  # noqa: BLE001 - сбой отправки не должен ронять планировщик
        logger.exception("Не удалось отправить уведомление пользователю %s", user_id)
        return False


async def check_user(
    bot, conn: db.Connection, settings: Settings, user: dict
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
            if await _send(bot, max_user_id, text):
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
        sent = await _send(
            bot,
            max_user_id,
            f"Через {plural_minutes(max(1, minutes_left))}: "
            f"<b>{block.title}</b> в {format_time(block.starts_at)}.",
        )
        if sent:
            await db.mark_notified(conn, user["id"], "event", key)

    # 3. Выбранные городские мероприятия: утром в день проведения или за час,
    # если событие начинается раньше 10:00.
    async with conn.execute(
        "SELECT id, title, starts_at, url FROM city_event_reminders WHERE user_id = ? "
        "AND starts_at >= ? AND starts_at <= ?",
        (user["id"], (now.astimezone(timezone.utc) - timedelta(days=1)).isoformat(),
         (now.astimezone(timezone.utc) + timedelta(days=2)).isoformat()),
    ) as cur:
        reminders = await cur.fetchall()
    for reminder in reminders:
        start = datetime.fromisoformat(reminder["starts_at"]).astimezone(tz)
        morning = start.replace(hour=9, minute=0, second=0, microsecond=0)
        send_at = min(morning, start - timedelta(hours=1))
        if not send_at <= now < start:
            continue
        if await db.already_notified(conn, user["id"], "city_event", reminder["id"]):
            continue
        sent = await _send(bot, max_user_id,
                           f"<b>Сегодня мероприятие:</b> {escape(reminder['title'])}\n"
                           f"Начало: {format_time(start)}. <a href=\"{escape(reminder['url'], quote=True)}\">Подробнее</a>")
        if sent:
            await db.mark_notified(conn, user["id"], "city_event", reminder["id"])

    # 3. Когда вставать: вечером — один раз на завтра, по первому делу дня.
    if now.hour >= settings.wake_hour:
        tomorrow = today + timedelta(days=1)
        key = tomorrow.isoformat()
        if not await db.already_notified(conn, user["id"], "wake", key):
            busy = sorted(
                (b for b in plan.blocks
                 if b.kind != "free" and b.starts_at.date() == tomorrow),
                key=lambda b: b.starts_at,
            )
            if busy:
                first = busy[0]
                travel_min = 0
                first_start = first.starts_at
                title = first.title
                if first.kind == "travel":
                    # Дорога впереди: первое «настоящее» дело — следующий блок.
                    travel_min = first.minutes
                    nxt = next((b for b in busy[1:] if b.kind != "travel"), None)
                    if nxt is not None:
                        title = nxt.title
                        first_start = nxt.starts_at
                wake_at = first.starts_at - timedelta(minutes=WAKE_PREP_MIN)
                if wake_at > now:
                    text = (
                        f"На завтра: первое — <b>{html.escape(title)}</b> "
                        f"в {format_time(first_start)}"
                    )
                    if travel_min:
                        text += f", в пути {plural_minutes(travel_min)}"
                    text += f" → вставай в {format_time(wake_at)}."
                    if await _send(bot, max_user_id, text):
                        await db.mark_notified(conn, user["id"], "wake", key)

    # 4. Протухшие задания: старше двух недель — спросить один раз на срок.
    tasks = await db.list_tasks(conn, user["id"])
    cutoff = (today - timedelta(days=STALE_DAYS)).isoformat()
    stale = [t for t in tasks if t["status"] != "done" and t["due_at"][:10] < cutoff]
    for task in stale[:STALE_MAX_PER_CYCLE]:
        key = f"{task['id']}:{task['due_at'][:10]}"
        if await db.already_notified(conn, user["id"], "stale", key):
            continue
        text = (
            f"Задание висит уже {STALE_DAYS} дней: "
            f"«{html.escape(task['title'])}».\n"
            f"Срок был {_ru_date(task['due_at'][:10])}. Ещё актуально?"
        )
        buttons = [
            [
                {"text": "Перенести на сегодня", "payload": f"stale_move:{task['id']}"},
                {"text": "Убрать", "payload": f"stale_drop:{task['id']}"},
            ],
            [{"text": "Оставить", "payload": f"stale_keep:{task['id']}"}],
        ]
        if await _send(bot, max_user_id, text, buttons=buttons):
            await db.mark_notified(conn, user["id"], "stale", key)


async def run_notifier(
    bot,
    pool: AsyncConnectionPool,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    logger.info("Планировщик уведомлений запущен")
    while not stop.is_set():
        try:
            async with pool.connection() as raw:
                conn = db.Connection(raw)
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
                        await raw.rollback()
                        logger.exception("Ошибка проверки пользователя %s", user["id"])
        except Exception:  # noqa: BLE001
            logger.exception("Ошибка цикла уведомлений")

        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.notifier_interval_seconds)
        except asyncio.TimeoutError:
            pass
    logger.info("Планировщик уведомлений остановлен")
