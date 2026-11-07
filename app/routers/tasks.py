from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from .. import db
from ..deps import api_error, get_conn, get_current_user, require_patch
from ..schemas import Task, TaskInput, TaskPatch

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("", response_model=list[Task])
async def list_tasks(
    due_before: date | None = None,
    status: str | None = None,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    if status is not None and status not in ("todo", "in_progress", "done"):
        raise api_error(422, "validation_error", "Недопустимый статус задачи")

    tasks = await db.list_tasks(conn, user["id"])
    if due_before is not None:
        limit = f"{due_before.isoformat()}T23:59:59"
        tasks = [task for task in tasks if task["due_at"] <= limit]
    if status is not None:
        tasks = [task for task in tasks if task["status"] == status]
    return tasks


@router.post("", response_model=Task, status_code=201)
async def create_task(
    payload: TaskInput,
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    return await db.create_task(conn, user["id"], payload.model_dump(mode="json"))


@router.patch("/{task_id}", response_model=Task)
async def update_task(
    payload: TaskPatch,
    task_id: Annotated[str, Path(alias="task_id")],
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    patch = require_patch(payload)
    updated = await db.update_task(conn, user["id"], task_id, patch)
    if updated is None:
        raise api_error(404, "not_found", "Задание не найдено")
    return updated


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: Annotated[str, Path(alias="task_id")],
    conn=Depends(get_conn),
    user=Depends(get_current_user),
):
    if not await db.delete_task(conn, user["id"], task_id):
        raise api_error(404, "not_found", "Задание не найдено")
