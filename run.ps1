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

$lines = @(Get-Content $envPath)
$token = ""
foreach ($line in $lines) {
    if ($line -match '^MAX_BOT_TOKEN=(.*)$') {
        $token = $matches[1].Trim()
    }
}

if ([string]::IsNullOrWhiteSpace($token)) {
    Write-Host ""
    Write-Host "Нужен токен бота MAX."
    Write-Host "Получить: business.max.ru -> Чат-боты -> нужный бот -> три точки -> Настройки -> Токен."
    $entered = Read-Host "Вставь MAX_BOT_TOKEN"
    if ([string]::IsNullOrWhiteSpace($entered)) {
        throw "Без MAX_BOT_TOKEN бот не запустится."
    }
    $token = $entered.Trim()
    $updated = foreach ($line in $lines) {
        if ($line -match '^MAX_BOT_TOKEN=') { "MAX_BOT_TOKEN=$token" } else { $line }
    }
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($envPath, $updated, $utf8)
    Write-Host "Токен сохранён в .env (файл не попадает в git)."
}

if ($SetupOnly) {
    Write-Host "Готово. Запуск: .\run.ps1"
    exit 0
}

Write-Host "Запускаю TimeBalance..."
& $python (Join-Path $root "code.py")
