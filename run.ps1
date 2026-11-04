param(
    [switch]$SetupOnly,
    [switch]$Reinstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Создаю виртуальное окружение .venv..."
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        throw "Python не найден. Установи Python 3.10+ с https://python.org и запусти скрипт снова."
    }
    & python -m venv $venv
}

if ($Reinstall -or -not (Test-Path (Join-Path $venv "pyvenv.cfg"))) {
    Write-Host "Устанавливаю зависимости..."
    & $python -m pip install --disable-pip-version-check -q --upgrade pip
    & $python -m pip install --disable-pip-version-check -q -r (Join-Path $root "requirements.txt")
} else {
    Write-Host "Проверяю зависимости..."
    & $python -m pip install --disable-pip-version-check -q -r (Join-Path $root "requirements.txt")
}

$envPath = Join-Path $root ".env"
if (-not (Test-Path $envPath)) {
    Copy-Item (Join-Path $root ".env.example") $envPath
    Write-Host "Создан файл .env из .env.example."
}

if ($SetupOnly) {
    Write-Host "Готово. Запуск: .\run.ps1"
    exit 0
}

Write-Host "Для локального запуска нужна PostgreSQL: docker compose up -d postgres"
Write-Host "MAX_BOT_TOKEN в .env нужен только для входа через MAX и бота."
Write-Host "Запускаю TimeBalance..."
& $python (Join-Path $root "code.py")
