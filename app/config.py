"""Конфигурация бэкенда TimeBalance.

Все секреты читаются из переменных окружения, чтобы токен бота не попал в репозиторий.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _derive_secret(bot_token: str) -> str:
    """Секрет сессий: явный JWT_SECRET либо производный от токена бота."""
    if not bot_token:
        return "timebalance-development-secret"
    return hashlib.sha256(("timebalance-session:" + bot_token).encode()).hexdigest()


@dataclass(frozen=True)
class Settings:
    bot_token: str = ""
    database_path: str = "timebalance.db"
    mini_app_url: str = ""
    session_ttl_seconds: int = 7 * 24 * 3600
    init_data_max_age_seconds: int = 24 * 3600
    day_start: str = "07:00"
    host: str = "127.0.0.1"
    port: int = 8000
    enable_bot: bool = True
    enable_notifier: bool = True
    notifier_interval_seconds: int = 60
    jwt_secret: str = ""

    @property
    def bot_enabled(self) -> bool:
        """Бот запускается только при наличии токена."""
        return self.enable_bot and bool(self.bot_token)

    @classmethod
    def from_env(cls) -> "Settings":
        # `.env` в корне проекта подхватывается автоматически; реальные переменные
        # окружения имеют приоритет (override=False у load_dotenv).
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:  # python-dotenv не установлен — работаем как раньше
            pass
        bot_token = _env("MAX_BOT_TOKEN", "")
        return cls(
            bot_token=bot_token,
            database_path=_env("TIMEBALANCE_DB", "timebalance.db"),
            mini_app_url=_env("MINI_APP_URL", ""),
            session_ttl_seconds=_env_int("SESSION_TTL_SECONDS", 7 * 24 * 3600),
            init_data_max_age_seconds=_env_int("INIT_DATA_MAX_AGE_SECONDS", 24 * 3600),
            day_start=_env("DAY_START", "07:00"),
            host=_env("HOST", "127.0.0.1"),
            port=_env_int("PORT", 8000),
            enable_bot=_env_bool("ENABLE_BOT", True),
            enable_notifier=_env_bool("ENABLE_NOTIFIER", True),
            notifier_interval_seconds=_env_int("NOTIFIER_INTERVAL_SECONDS", 60),
            jwt_secret=_env("JWT_SECRET", "") or _derive_secret(bot_token),
        )
