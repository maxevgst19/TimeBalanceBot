"""Сквозные тесты REST API: авторизация, данные, план и «План Б»."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

BOT_TOKEN = "1234567890:TEST_TOKEN_FOR_API_TESTS"
DAY = "2026-11-03"


def _sign(params: dict[str, str], token: str = BOT_TOKEN) -> str:
    launch = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, launch.encode(), hashlib.sha256).hexdigest()


def build_init_data(user_id: int = 777, auth_date: int | None = None) -> str:
    params = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "user": json.dumps({"id": user_id, "first_name": "Ирина"}, ensure_ascii=False),
        "query_id": "00000000-0000-0000-0000-000000000007",
    }
    params["hash"] = _sign(params)
    return "&".join(
        f"{key}={urllib.parse.quote(value, safe='')}" for key, value in params.items()
    )


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        bot_token=BOT_TOKEN,
        enable_bot=False,
        enable_notifier=False,
        database_path=str(tmp_path / "api-test.db"),
        jwt_secret="test-secret",
        mini_app_url="https://example.com/app",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture()
def auth(client):
    response = client.post("/api/v1/auth/max", json={"init_data": build_init_data()})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_miniapp_is_served_with_max_bridge(client):
    page = client.get("/miniapp/")
    assert page.status_code == 200
    assert "https://st.max.ru/js/max-web-app.js" in page.text
    assert client.get("/miniapp/app.min.js").status_code == 200


def test_auth_returns_session_and_user(client):
    response = client.post("/api/v1/auth/max", json={"init_data": build_init_data()})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0
    assert body["user"]["settings"]["day_end"] == "21:00"
    assert "max_user_id" not in body["user"], "внутренний id не должен утекать"


def test_auth_rejects_tampered_init_data(client):
    raw = build_init_data(user_id=777)
    forged = raw.replace("777", "778", 1)
    assert forged != raw, "подделка должна менять строку"
    response = client.post("/api/v1/auth/max", json={"init_data": forged})
    assert response.status_code == 401
    assert response.json()["code"] == "init_data_invalid"


def test_auth_requires_token(client, auth):
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["code"] == "session_invalid"


def test_me_returns_profile(client, auth):
    response = client.get("/api/v1/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["settings"]["timezone"] == "Europe/Moscow"


def test_patch_settings(client, auth):
    response = client.patch(
        "/api/v1/me",
        headers=auth,
        json={"day_end": "22:30", "break_after_school_min": 45},
    )
    assert response.status_code == 200
    assert response.json()["settings"]["day_end"] == "22:30"
    assert response.json()["settings"]["break_after_school_min"] == 45


def test_empty_patch_is_rejected(client, auth):
    response = client.patch("/api/v1/me", headers=auth, json={})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_invalid_day_end_is_rejected(client, auth):
    response = client.patch("/api/v1/me", headers=auth, json={"day_end": "25:99"})
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------

def test_create_list_and_delete_event(client, auth):
    payload = {
        "title": "Школа",
        "category": "school",
        "starts_at": f"{DAY}T08:00:00+03:00",
        "ends_at": f"{DAY}T14:00:00+03:00",
    }
    created = client.post("/api/v1/events", headers=auth, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    listed = client.get(
        "/api/v1/events", headers=auth, params={"from": DAY, "to": DAY}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [event_id]

    deleted = client.delete(f"/api/v1/events/{event_id}", headers=auth)
    assert deleted.status_code == 204

    missing = client.delete(f"/api/v1/events/{event_id}", headers=auth)
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"


def test_event_with_inverted_times_is_rejected(client, auth):
    response = client.post(
        "/api/v1/events",
        headers=auth,
        json={
            "title": "Кружок",
            "category": "extra",
            "starts_at": f"{DAY}T16:00:00+03:00",
            "ends_at": f"{DAY}T15:00:00+03:00",
        },
    )
    assert response.status_code == 422


def test_event_range_longer_than_31_days_is_rejected(client, auth):
    response = client.get(
        "/api/v1/events",
        headers=auth,
        params={"from": DAY, "to": "2027-01-15"},
    )
    assert response.status_code == 422


def test_recurring_event_expands(client, auth):
    response = client.post(
        "/api/v1/events",
        headers=auth,
        json={
            "title": "Секция",
            "category": "extra",
            "starts_at": f"{DAY}T16:00:00+03:00",
            "ends_at": f"{DAY}T17:30:00+03:00",
            "recurrence": {"weekdays": [2]},
        },
    )
    assert response.status_code == 201

    listed = client.get(
        "/api/v1/events", headers=auth, params={"from": DAY, "to": "2026-11-30"}
    )
    assert listed.status_code == 200
    assert len(listed.json()) >= 4, "еженедельное событие должно развернуться"


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

def test_task_lifecycle(client, auth):
    created = client.post(
        "/api/v1/tasks",
        headers=auth,
        json={
            "title": "Алгебра",
            "due_at": f"{DAY}T23:59:00+03:00",
            "estimated_min": 70,
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    assert created.json()["status"] == "todo"

    patched = client.patch(
        f"/api/v1/tasks/{task_id}", headers=auth, json={"status": "done"}
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "done"

    listed = client.get("/api/v1/tasks", headers=auth, params={"status": "done"})
    assert [item["id"] for item in listed.json()] == [task_id]

    assert client.delete(f"/api/v1/tasks/{task_id}", headers=auth).status_code == 204


def test_task_estimate_bounds(client, auth):
    response = client.post(
        "/api/v1/tasks",
        headers=auth,
        json={"title": "X", "due_at": f"{DAY}T23:59:00+03:00", "estimated_min": 2},
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# План и «План Б»
# --------------------------------------------------------------------------

def _seed_overlapping_events(client, auth) -> None:
    """Два пересекающихся события — конфликт не зависит от текущего времени."""
    for payload in (
        {
            "title": "Школа",
            "category": "school",
            "starts_at": f"{DAY}T10:00:00+03:00",
            "ends_at": f"{DAY}T11:00:00+03:00",
        },
        {
            "title": "Секция",
            "category": "extra",
            "starts_at": f"{DAY}T10:30:00+03:00",
            "ends_at": f"{DAY}T12:00:00+03:00",
            "movable": True,
        },
    ):
        created = client.post("/api/v1/events", headers=auth, json=payload)
        assert created.status_code == 201, created.text


def test_plan_returns_blocks_and_conflicts(client, auth):
    _seed_overlapping_events(client, auth)

    response = client.get(
        "/api/v1/plan", headers=auth, params={"from": DAY, "to": DAY}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["from"] == DAY and body["to"] == DAY
    assert body["revision"]
    assert {block["kind"] for block in body["blocks"]} >= {"event", "free"}
    assert body["conflicts"], "пересечение должно дать конфликт"
    assert body["conflicts"][0]["type"] == "overlap"
    assert body["planned_min"] > 0


def test_plan_rejects_reversed_range(client, auth):
    response = client.get(
        "/api/v1/plan", headers=auth, params={"from": DAY, "to": "2026-11-01"}
    )
    assert response.status_code == 422


def test_next_action_returns_step(client, auth):
    _seed_overlapping_events(client, auth)
    response = client.get("/api/v1/plan/next-action", headers=auth)
    assert response.status_code == 200
    assert response.json()["kind"] in {"task", "event", "rest"}


def test_alternatives_and_apply(client, auth):
    _seed_overlapping_events(client, auth)

    plan = client.get(
        "/api/v1/plan", headers=auth, params={"from": DAY, "to": DAY}
    ).json()
    conflict = next(c for c in plan["conflicts"] if c["type"] == "overlap")

    response = client.post(
        "/api/v1/plan/alternatives",
        headers=auth,
        json={"conflict_id": conflict["id"], "plan_revision": plan["revision"]},
    )
    assert response.status_code == 200, response.text
    alternatives = response.json()
    assert 1 <= len(alternatives) <= 3, "по контракту 2–3 варианта"
    for item in alternatives:
        assert item["title"] and item["explanation"]
        assert item["changes"]
        assert item["remaining_shortage_min"] <= conflict["shortage_min"]

    apply = client.post(
        f"/api/v1/plan/alternatives/{alternatives[0]['id']}/apply",
        headers=auth,
        json={"plan_revision": plan["revision"]},
    )
    assert apply.status_code == 200, apply.text
    assert apply.json()["revision"] != plan["revision"], "ревизия должна смениться"


def test_alternatives_reject_stale_revision(client, auth):
    _seed_overlapping_events(client, auth)
    plan = client.get(
        "/api/v1/plan", headers=auth, params={"from": DAY, "to": DAY}
    ).json()
    conflict = plan["conflicts"][0]

    response = client.post(
        "/api/v1/plan/alternatives",
        headers=auth,
        json={"conflict_id": conflict["id"], "plan_revision": "deadbeefdeadbeef"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "plan_changed"


def test_alternatives_reject_unknown_conflict(client, auth):
    plan = client.get(
        "/api/v1/plan", headers=auth, params={"from": DAY, "to": DAY}
    ).json()
    response = client.post(
        "/api/v1/plan/alternatives",
        headers=auth,
        json={"conflict_id": "00000000-0000-0000-0000-000000000000",
              "plan_revision": plan["revision"]},
    )
    assert response.status_code == 409


def test_apply_unknown_alternative_is_404(client, auth):
    response = client.post(
        "/api/v1/plan/alternatives/00000000-0000-0000-0000-000000000000/apply",
        headers=auth,
        json={"plan_revision": "deadbeefdeadbeef"},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Данные
# --------------------------------------------------------------------------

def test_delete_my_data_wipes_everything(client, auth):
    client.post(
        "/api/v1/events",
        headers=auth,
        json={
            "title": "Школа",
            "category": "school",
            "starts_at": f"{DAY}T08:00:00+03:00",
            "ends_at": f"{DAY}T14:00:00+03:00",
        },
    )
    client.post(
        "/api/v1/tasks",
        headers=auth,
        json={"title": "Алгебра", "due_at": f"{DAY}T23:59:00+03:00",
              "estimated_min": 70},
    )

    assert client.delete("/api/v1/me/data", headers=auth).status_code == 204
    # Сессия привязана к удалённому профилю — доступ закрыт.
    assert client.get("/api/v1/me", headers=auth).status_code == 401


# --------------------------------------------------------------------------
# Контракт спецификации
# --------------------------------------------------------------------------

def test_openapi_paths_are_relative_to_server(client):
    spec = client.get("/openapi.json").json()
    assert spec["servers"] == [{"url": "/api/v1"}]
    assert "/auth/max" in spec["paths"]
    assert "/api/v1/auth/max" not in spec["paths"]
