# Запуск JARVIS в режиме удалённого доступа (мобильный клиент).
# Окно на ПК не открывается; доступ идёт через туннель (start_tunnel_cf.ps1).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python launcher_remote.py
