from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class SecurityError(Exception):


    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or _DEFAULT_MESSAGES.get(code, "Unauthorized")


_DEFAULT_MESSAGES = {
    "init_data_invalid": "Данные запуска приложения не прошли проверку",
    "init_data_expired": "Данные запуска устарели, откройте приложение заново",
    "missing_user": "В данных запуска нет пользователя",
    "session_invalid": "Неверная или истёкшая сессия",
    "unauthorized": "Неверная или истёкшая сессия",
}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def validate_init_data(init_data: str, bot_token: str, max_age_seconds: int) -> dict[str, str]:

    if not init_data or not bot_token:
        raise SecurityError("init_data_invalid")

    pairs = parse_qsl(init_data, keep_blank_values=True)
    if not pairs:
        raise SecurityError("init_data_invalid")

    names = [name for name, _ in pairs]
    if names.count("hash") != 1:
        raise SecurityError("init_data_invalid")

    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise SecurityError("init_data_invalid")
        seen.add(name)

    params = dict(pairs)
    original_hash = params.pop("hash")


    launch_params = "\n".join(f"{name}={value}" for name, value in sorted(params.items()))

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(secret_key, launch_params.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, original_hash):
        raise SecurityError("init_data_invalid")

    auth_date = params.get("auth_date", "")
    if not auth_date.isdigit():
        raise SecurityError("init_data_invalid")

    age = int(time.time()) - int(auth_date)
    if age < -60:
        raise SecurityError("init_data_invalid")
    if max_age_seconds > 0 and age > max_age_seconds:
        raise SecurityError("init_data_expired")

    return params


def issue_session(user_id: str, secret: str, ttl_seconds: int) -> tuple[str, int]:

    now = int(time.time())
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url_encode(
        json.dumps({"sub": user_id, "iat": now, "exp": now + ttl_seconds}, separators=(",", ":")).encode()
    )
    signing_input = f"{header}.{payload}"
    signature = _b64url_encode(
        hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    )
    return f"{signing_input}.{signature}", ttl_seconds


def read_session(token: str, secret: str) -> str:

    if not token:
        raise SecurityError("session_invalid")

    parts = token.split(".")
    if len(parts) != 3:
        raise SecurityError("session_invalid")

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}"
    expected = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    try:
        actual = _b64url_decode(signature_b64)
    except Exception:
        raise SecurityError("session_invalid")
    if not hmac.compare_digest(expected, actual):
        raise SecurityError("session_invalid")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise SecurityError("session_invalid")

    if payload.get("alg") is not None and payload.get("alg") != "HS256":
        raise SecurityError("session_invalid")

    try:
        expires_at = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        raise SecurityError("session_invalid")
    if expires_at < int(time.time()):
        raise SecurityError("session_invalid")

    subject = payload.get("sub")
    if not subject:
        raise SecurityError("session_invalid")
    return str(subject)
