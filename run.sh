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

token="$(grep -E '^MAX_BOT_TOKEN=' .env | head -n1 | cut -d= -f2- | xargs || true)"
if [ -z "$token" ]; then
    echo
    echo "Нужен токен бота MAX: business.max.ru -> Чат-боты -> нужный бот -> Настройки -> Токен."
    read -r -p "Вставь MAX_BOT_TOKEN: " token
    if [ -z "$token" ]; then
        echo "Без MAX_BOT_TOKEN бот не запустится." >&2
        exit 1
    fi
    tmp="$(mktemp)"
    awk -v t="$token" '/^MAX_BOT_TOKEN=/{print "MAX_BOT_TOKEN=" t; next} {print}' .env > "$tmp"
    mv "$tmp" .env
    echo "Токен сохранён в .env (файл не попадает в git)."
fi

echo "Запускаю TimeBalance..."
exec .venv/bin/python code.py
