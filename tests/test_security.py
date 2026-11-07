from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse

import pytest

from app.security import (
    SecurityError,
    issue_session,
    read_session,
    validate_init_data,
)

BOT_TOKEN = "1234567890:TEST_TOKEN_FOR_UNIT_TESTS"


def sign(params: dict[str, str], token: str = BOT_TOKEN) -> str:
    launch = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, launch.encode(), hashlib.sha256).hexdigest()


def build_init_data(
    user_id: int = 777,
    auth_date: int | None = None,
    token: str = BOT_TOKEN,
    extra: dict[str, str] | None = None,
    tamper: str | None = None,
) -> str:
    params: dict[str, str] = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "user": json.dumps(
            {"id": user_id, "first_name": "Ирина"}, ensure_ascii=False
        ),
        "query_id": "00000000-0000-0000-0000-000000000001",
    }
    if extra:
        params.update(extra)
    params["hash"] = sign({k: v for k, v in params.items()}, token)
    if tamper:
        params[tamper] = "подделано"
    return "&".join(
        f"{key}={urllib.parse.quote(value, safe='')}" for key, value in params.items()
    )


def test_valid_init_data_accepted():
    params = validate_init_data(build_init_data(), BOT_TOKEN, 86400)
    assert params["query_id"].startswith("00000000")
    assert json.loads(params["user"])["id"] == 777


def test_tampered_value_rejected():
    raw = build_init_data()
    forged = raw.replace("777", "778", 1)
    with pytest.raises(SecurityError):
        validate_init_data(forged, BOT_TOKEN, 86400)


def test_wrong_token_rejected():
    raw = build_init_data(token=BOT_TOKEN)
    with pytest.raises(SecurityError):
        validate_init_data(raw, "999999:ANOTHER_TOKEN", 86400)


def test_duplicate_parameter_rejected():

    raw = build_init_data() + "&auth_date=1"
    with pytest.raises(SecurityError):
        validate_init_data(raw, BOT_TOKEN, 86400)


def test_missing_hash_rejected():
    raw = build_init_data()
    without_hash = "&".join(
        part for part in raw.split("&") if not part.startswith("hash=")
    )
    with pytest.raises(SecurityError):
        validate_init_data(without_hash, BOT_TOKEN, 86400)


def test_expired_auth_date_rejected():
    old = int(time.time()) - 7 * 24 * 3600
    with pytest.raises(SecurityError) as exc:
        validate_init_data(build_init_data(auth_date=old), BOT_TOKEN, 86400)
    assert exc.value.code == "init_data_expired"


def test_empty_init_data_rejected():
    with pytest.raises(SecurityError):
        validate_init_data("", BOT_TOKEN, 86400)


def test_session_roundtrip():
    token, ttl = issue_session("user-1", "secret", 60)
    assert ttl == 60
    assert read_session(token, "secret") == "user-1"


def test_session_rejected_with_other_secret():
    token, _ = issue_session("user-1", "secret", 60)
    with pytest.raises(SecurityError):
        read_session(token, "other-secret")


def test_expired_session_rejected():
    token, _ = issue_session("user-1", "secret", -10)
    with pytest.raises(SecurityError):
        read_session(token, "secret")


def test_malformed_session_rejected():
    with pytest.raises(SecurityError):
        read_session("not-a-token", "secret")
