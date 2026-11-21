# Показывает адрес и токен для подключения мобильного приложения.
# Требует запущенных start_remote.ps1 и start_tunnel.ps1.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$publicFile = ".\data\remote_url.json"
$statusFile = ".\data\remote_status.json"
$configFile = ".\config\config.json"

$publicUrl = $null
if (Test-Path $publicFile) {
    $publicUrl = (Get-Content $publicFile -Raw | ConvertFrom-Json).url
}
if (-not $publicUrl -and (Test-Path $statusFile)) {
    $local = (Get-Content $statusFile -Raw | ConvertFrom-Json).url
    Write-Host "Публичный туннель не найден (data\remote_url.json)."
    Write-Host "Запущен только локальный сервер: $local"
    exit 0
}
if (-not $publicUrl) {
    Write-Host "Ничего не запущено. Сначала:"
    Write-Host "  scripts\start_remote.ps1"
    Write-Host "  scripts\start_tunnel.ps1"
    exit 1
}

$token = $null
if (Test-Path $configFile) {
    $cfg = Get-Content $configFile -Raw | ConvertFrom-Json
    if ($cfg.remote -and $cfg.remote.token) { $token = $cfg.remote.token }
}
if (-not $token) {
    Write-Host "Токен не найден в config.json (remote.token)."
    Write-Host "Запустите scripts\start_remote.ps1, чтобы он создал токен."
    exit 1
}

Write-Host ""
Write-Host "==============================================="
Write-Host " JARVIS Remote — данные для приложения"
Write-Host "==============================================="
Write-Host " Адрес сервера (введите в приложении):"
Write-Host "   $publicUrl"
Write-Host ""
Write-Host " Токен:"
Write-Host "   $token"
Write-Host "==============================================="
