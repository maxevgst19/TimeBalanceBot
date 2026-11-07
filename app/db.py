from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class Query:


    def __init__(self, conn: AsyncConnection, sql: str, params: tuple | list = ()):
        self.conn = conn
        self.sql = sql.replace("?", "%s")
        self.params = tuple(value.isoformat() if isinstance(value, (date, datetime))
                            else value for value in params)
        self.cursor = None

    async def _run(self):
        self.cursor = await self.conn.execute(self.sql, self.params)
        return self.cursor

    def __await__(self):
        return self._run().__await__()

    async def __aenter__(self):
        return await self._run()

    async def __aexit__(self, *_exc):
        await self.cursor.close()


class Connection:
    def __init__(self, raw: AsyncConnection):
        self.raw = raw

    def execute(self, sql: str, params: tuple | list = ()) -> Query:
        return Query(self.raw, sql, params)

    async def commit(self) -> None:
        await self.raw.commit()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                      TEXT PRIMARY KEY,
    max_user_id             BIGINT UNIQUE,
    display_name            TEXT,
    timezone                TEXT NOT NULL DEFAULT 'Europe/Moscow',
    day_end                 TEXT NOT NULL DEFAULT '21:00',
    break_after_school_min  INTEGER NOT NULL DEFAULT 30,
    notifications_enabled   INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    category            TEXT NOT NULL,
    starts_at           TEXT NOT NULL,
    ends_at             TEXT NOT NULL,
    travel_before_min   INTEGER NOT NULL DEFAULT 0,
    travel_after_min    INTEGER NOT NULL DEFAULT 0,
    movable             INTEGER NOT NULL DEFAULT 0,
    recurrence_weekdays TEXT,
    recurrence_until    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);

CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    due_at        TEXT NOT NULL,
    estimated_min INTEGER NOT NULL,
    splittable    INTEGER NOT NULL DEFAULT 1,
    priority      TEXT NOT NULL DEFAULT 'normal',
    status        TEXT NOT NULL DEFAULT 'todo',
    spent_min     INTEGER NOT NULL DEFAULT 0,
    started_at_ms BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS spent_min INTEGER NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS started_at_ms BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS alternatives (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conflict_id   TEXT NOT NULL,
    plan_revision TEXT NOT NULL,
    payload       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alternatives_user ON alternatives(user_id);

CREATE TABLE IF NOT EXISTS notifications_sent (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind    TEXT NOT NULL,
    key     TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, kind, key)
);

CREATE TABLE IF NOT EXISTS city_event_reminders (
    id        TEXT PRIMARY KEY,
    user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    city      TEXT NOT NULL,
    title     TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    url       TEXT NOT NULL,
    UNIQUE (user_id, source_id, starts_at)
);
CREATE INDEX IF NOT EXISTS idx_city_reminders_user ON city_event_reminders(user_id, starts_at);
ALTER TABLE city_event_reminders ALTER COLUMN source_id TYPE TEXT USING source_id::text;

CREATE TABLE IF NOT EXISTS notes (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day        TEXT NOT NULL,
    event_id   TEXT REFERENCES events(id) ON DELETE SET NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_user_day ON notes(user_id, day);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


async def open_db(url: str) -> AsyncConnectionPool:
    if not url:
        raise RuntimeError("DATABASE_URL не задан: требуется PostgreSQL")
    pool = AsyncConnectionPool(url, min_size=1, max_size=5, open=False,
                               kwargs={"row_factory": dict_row})
    await pool.open(wait=True)
    try:
        async with pool.connection() as conn:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    await conn.execute(statement)
    except Exception:
        await pool.close()
        raise
    return pool


DEFAULT_SETTINGS = {
    "timezone": "Europe/Moscow",
    "day_end": "21:00",
    "break_after_school_min": 30,
    "notifications_enabled": True,
}


def row_to_user(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "max_user_id": row["max_user_id"],
        "display_name": row["display_name"],
        "settings": {
            "timezone": row["timezone"],
            "day_end": row["day_end"],
            "break_after_school_min": row["break_after_school_min"],
            "notifications_enabled": bool(row["notifications_enabled"]),
        },
    }


async def get_user(conn: Connection, user_id: str) -> dict[str, Any] | None:
    async with conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
        row = await cur.fetchone()
    return row_to_user(row) if row else None


async def get_user_by_max_id(conn: Connection, max_user_id: int) -> dict[str, Any] | None:
    async with conn.execute("SELECT * FROM users WHERE max_user_id = ?", (max_user_id,)) as cur:
        row = await cur.fetchone()
    return row_to_user(row) if row else None


async def create_user(
    conn: Connection,
    max_user_id: int | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    user_id = new_id()
    cur = await conn.execute(
        """INSERT INTO users (id, max_user_id, display_name, timezone, day_end,
                              break_after_school_min, notifications_enabled, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(max_user_id) DO NOTHING""",
        (
            user_id,
            max_user_id,
            display_name,
            DEFAULT_SETTINGS["timezone"],
            DEFAULT_SETTINGS["day_end"],
            DEFAULT_SETTINGS["break_after_school_min"],
            int(DEFAULT_SETTINGS["notifications_enabled"]),
            now_iso(),
        ),
    )
    await conn.commit()
    if cur.rowcount == 0 and max_user_id is not None:
        existing = await get_user_by_max_id(conn, max_user_id)
        assert existing is not None
        return existing
    user = await get_user(conn, user_id)
    assert user is not None
    return user


async def get_or_create_by_max_id(
    conn: Connection, max_user_id: int, display_name: str | None
) -> dict[str, Any]:

    user = await get_user_by_max_id(conn, max_user_id)
    if user is not None:
        if display_name and not user["display_name"]:
            await conn.execute(
                "UPDATE users SET display_name = ? WHERE id = ?", (display_name, user["id"])
            )
            await conn.commit()
            user = await get_user(conn, user["id"])
        return user
    return await create_user(conn, max_user_id=max_user_id, display_name=display_name)


async def update_settings(
    conn: Connection, user_id: str, patch: dict[str, Any]
) -> dict[str, Any] | None:
    fields: list[str] = []
    values: list[Any] = []
    mapping = {
        "timezone": "timezone",
        "day_end": "day_end",
        "break_after_school_min": "break_after_school_min",
        "notifications_enabled": "notifications_enabled",
    }
    for key, column in mapping.items():
        if key in patch:
            value = patch[key]
            if key == "notifications_enabled":
                value = int(bool(value))
            fields.append(f"{column} = ?")
            values.append(value)
    if not fields:
        return await get_user(conn, user_id)
    values.append(user_id)
    await conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    await conn.commit()
    return await get_user(conn, user_id)


async def delete_user_data(conn: Connection, user_id: str) -> None:

    await conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    await conn.commit()


def row_to_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "starts_at": row["starts_at"],
        "ends_at": row["ends_at"],
        "travel_before_min": row["travel_before_min"],
        "travel_after_min": row["travel_after_min"],
        "movable": bool(row["movable"]),
        "recurrence": (
            {
                "weekdays": json.loads(row["recurrence_weekdays"]),
                **({"until": row["recurrence_until"]} if row["recurrence_until"] else {}),
            }
            if row["recurrence_weekdays"]
            else None
        ),
    }


async def list_events(conn: Connection, user_id: str) -> list[dict[str, Any]]:
    async with conn.execute(
        "SELECT * FROM events WHERE user_id = ? ORDER BY starts_at", (user_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [row_to_event(row) for row in rows]


async def get_event(conn: Connection, user_id: str, event_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        "SELECT * FROM events WHERE id = ? AND user_id = ?", (event_id, user_id)
    ) as cur:
        row = await cur.fetchone()
    return row_to_event(row) if row else None


async def create_event(conn: Connection, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    event_id = new_id()
    recurrence = data.get("recurrence")
    await conn.execute(
        """INSERT INTO events (id, user_id, title, category, starts_at, ends_at,
                               travel_before_min, travel_after_min, movable,
                               recurrence_weekdays, recurrence_until)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            user_id,
            data["title"],
            data["category"],
            data["starts_at"],
            data["ends_at"],
            data.get("travel_before_min", 0),
            data.get("travel_after_min", 0),
            int(data.get("movable", False)),
            json.dumps(sorted(recurrence["weekdays"])) if recurrence else None,
            recurrence.get("until") if recurrence else None,
        ),
    )
    await conn.commit()
    event = await get_event(conn, user_id, event_id)
    assert event is not None
    return event


async def update_event(
    conn: Connection, user_id: str, event_id: str, patch: dict[str, Any]
) -> dict[str, Any] | None:
    columns = {
        "title": "title",
        "category": "category",
        "starts_at": "starts_at",
        "ends_at": "ends_at",
        "travel_before_min": "travel_before_min",
        "travel_after_min": "travel_after_min",
        "movable": "movable",
    }
    fields: list[str] = []
    values: list[Any] = []
    for key, column in columns.items():
        if key in patch:
            value = patch[key]
            if key == "movable":
                value = int(bool(value))
            fields.append(f"{column} = ?")
            values.append(value)
    if "recurrence" in patch:
        recurrence = patch["recurrence"]
        if hasattr(recurrence, "model_dump"):
            recurrence = recurrence.model_dump(mode="json")
        fields.extend(["recurrence_weekdays = ?", "recurrence_until = ?"])
        values.extend([
            json.dumps(sorted(recurrence["weekdays"])),
            recurrence.get("until"),
        ])
    if fields:
        values.extend([event_id, user_id])
        await conn.execute(
            f"UPDATE events SET {', '.join(fields)} WHERE id = ? AND user_id = ?", values
        )
        await conn.commit()
    return await get_event(conn, user_id, event_id)


async def delete_event(conn: Connection, user_id: str, event_id: str) -> bool:
    cur = await conn.execute(
        "DELETE FROM events WHERE id = ? AND user_id = ?", (event_id, user_id)
    )
    await conn.commit()
    return cur.rowcount > 0


TASK_STATUSES = ("todo", "in_progress", "done")
TASK_PRIORITIES = ("normal", "high")


def row_to_task(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "due_at": row["due_at"],
        "estimated_min": row["estimated_min"],
        "splittable": bool(row["splittable"]),
        "priority": row["priority"],
        "status": row["status"],
        "spent_min": row["spent_min"],
        "started_at_ms": row["started_at_ms"],
    }


async def list_tasks(conn: Connection, user_id: str) -> list[dict[str, Any]]:
    async with conn.execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY due_at", (user_id,)
    ) as cur:
        rows = await cur.fetchall()
    return [row_to_task(row) for row in rows]


async def get_task(conn: Connection, user_id: str, task_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
    ) as cur:
        row = await cur.fetchone()
    return row_to_task(row) if row else None


async def create_task(conn: Connection, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    task_id = new_id()
    await conn.execute(
        """INSERT INTO tasks (id, user_id, title, due_at, estimated_min,
                              splittable, priority, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'todo')""",
        (
            task_id,
            user_id,
            data["title"],
            data["due_at"],
            data["estimated_min"],
            int(data.get("splittable", True)),
            data.get("priority", "normal"),
        ),
    )
    await conn.commit()
    task = await get_task(conn, user_id, task_id)
    assert task is not None
    return task


async def update_task(
    conn: Connection, user_id: str, task_id: str, patch: dict[str, Any]
) -> dict[str, Any] | None:
    columns = {
        "title": "title",
        "due_at": "due_at",
        "estimated_min": "estimated_min",
        "splittable": "splittable",
        "priority": "priority",
        "status": "status",
        "spent_min": "spent_min",
        "started_at_ms": "started_at_ms",
    }
    fields: list[str] = []
    values: list[Any] = []
    for key, column in columns.items():
        if key in patch:
            value = patch[key]
            if key == "splittable":
                value = int(bool(value))
            fields.append(f"{column} = ?")
            values.append(value)
    if fields:
        values.extend([task_id, user_id])
        await conn.execute(
            f"UPDATE tasks SET {', '.join(fields)} WHERE id = ? AND user_id = ?", values
        )
        await conn.commit()
    return await get_task(conn, user_id, task_id)


async def delete_task(conn: Connection, user_id: str, task_id: str) -> bool:
    cur = await conn.execute(
        "DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
    )
    await conn.commit()
    return cur.rowcount > 0


async def save_alternative(
    conn: Connection,
    alt_id: str,
    user_id: str,
    conflict_id: str,
    plan_revision: str,
    payload: dict[str, Any],
) -> None:
    await conn.execute(
        """INSERT INTO alternatives (id, user_id, conflict_id, plan_revision, payload, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               conflict_id = excluded.conflict_id,
               plan_revision = excluded.plan_revision,
               payload = excluded.payload,
               created_at = excluded.created_at""",
        (alt_id, user_id, conflict_id, plan_revision, json.dumps(payload, ensure_ascii=False), now_iso()),
    )
    await conn.commit()


async def get_alternative(
    conn: Connection, user_id: str, alt_id: str
) -> dict[str, Any] | None:
    async with conn.execute(
        "SELECT * FROM alternatives WHERE id = ? AND user_id = ?", (alt_id, user_id)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "conflict_id": row["conflict_id"],
        "plan_revision": row["plan_revision"],
        "payload": json.loads(row["payload"]),
    }


async def already_notified(conn: Connection, user_id: str, kind: str, key: str) -> bool:
    async with conn.execute(
        "SELECT 1 FROM notifications_sent WHERE user_id = ? AND kind = ? AND key = ?",
        (user_id, kind, key),
    ) as cur:
        return await cur.fetchone() is not None


async def mark_notified(conn: Connection, user_id: str, kind: str, key: str) -> None:
    await conn.execute(
        """INSERT INTO notifications_sent (user_id, kind, key, sent_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, kind, key) DO UPDATE SET sent_at = excluded.sent_at""",
        (user_id, kind, key, now_iso()),
    )
    await conn.commit()
