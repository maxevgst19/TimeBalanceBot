#!/usr/bin/env bash
# Запуск TimeBalance на Linux / macOS: ./run.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root"

if [ ! -x ".venv/bin/python" ]; then
    echo "Создаю виртуальное окружение .venv..."
    python3 -m venv .venv
fi

echo "Проверяю зависимости..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "Создан файл .env из .env.example."
fi

echo "Для локального запуска нужна PostgreSQL: docker compose up -d postgres"
echo "MAX_BOT_TOKEN в .env нужен только для входа через MAX и бота."
echo "Запускаю TimeBalance..."
exec .venv/bin/python code.py
