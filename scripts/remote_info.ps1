# Показывает адрес и токен для подключения мобильного приложения.
# Требует запущенного start_remote.ps1 (туннель — по желанию).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$publicFile = ".\data\remote_url.json"
$statusFile = ".\data\remote_status.json"
$configFile = ".\config\config.json"

$publicUrl = $null
if (Test-Path $publicFile) {
    $publicUrl = (Get-Content $publicFile -Raw | ConvertFrom-Json).url
}
$localUrl = $null
$lanUrl = $null
if (Test-Path $statusFile) {
    $status = Get-Content $statusFile -Raw | ConvertFrom-Json
    $localUrl = $status.url
    if ($status.PSObject.Properties.Name -contains "lan_url") {
        $lanUrl = $status.lan_url
    }
}
if (-not $publicUrl -and -not $lanUrl) {
    Write-Host "Сервер не запущен. Сначала:"
    Write-Host "  scripts\start_remote.ps1"
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
if ($lanUrl) {
    Write-Host " Домашний Wi-Fi (телефон в той же сети):"
    Write-Host "   $lanUrl"
    Write-Host ""
}
if ($publicUrl) {
    Write-Host " Через интернет (туннель):"
    Write-Host "   $publicUrl"
    Write-Host ""
}
Write-Host " Локально на ПК: $localUrl"
Write-Host ""
Write-Host " Токен:"
Write-Host "   $token"
Write-Host "==============================================="
