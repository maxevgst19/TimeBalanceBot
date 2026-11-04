"""Сверка сгенерированной спецификации с контрактом openapi.yaml.

Запуск: python scripts/check_openapi.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

# Служебные эндпоинты, которых нет в контракте мини-приложения.
ALLOWED_EXTRA = {"/health"}


def normalize_path(path: str) -> str:
    """eventId / task_id / alternativeId -> {} — имена параметров не важны."""
    return re.sub(r"\{[^}]+\}", "{}", path).replace("_", "").lower()


def methods(spec: dict) -> set[tuple[str, str]]:
    result = set()
    for path, item in spec["paths"].items():
        for method, definition in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                result.add((normalize_path(path), method.upper()))
    return result


def main() -> int:
    settings = Settings(
        bot_token="1:SMOKE",
        enable_bot=False,
        enable_notifier=False,
        database_url="",
        jwt_secret="smoke",
    )
    generated = create_app(settings).openapi()

    contract = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))

    contract_paths = {normalize_path(p) for p in contract["paths"]}
    filtered = {
        **generated,
        "paths": {
            p: v for p, v in generated["paths"].items() if p not in ALLOWED_EXTRA
        },
    }
    generated_paths = {normalize_path(p) for p in filtered["paths"]}

    ok = True
    if contract_paths != generated_paths:
        ok = False
        print("PATHS: контракт без покрытия :", sorted(contract_paths - generated_paths))
        print("PATHS: лишнее в генерации    :", sorted(generated_paths - contract_paths))
    else:
        print(f"PATHS: совпадают ({len(contract_paths)})")

    if methods(contract) != methods(filtered):
        ok = False
        print("METHODS: контракт без покрытия :", sorted(methods(contract) - methods(filtered)))
        print("METHODS: лишнее в генерации    :", sorted(methods(filtered) - methods(contract)))
    else:
        print(f"METHODS: совпадают ({len(methods(contract))})")

    servers = generated.get("servers")
    if servers != [{"url": "/api/v1"}]:
        ok = False
        print(f"SERVERS: ожидалось /api/v1, получено {servers}")
    else:
        print("SERVERS: /api/v1")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
