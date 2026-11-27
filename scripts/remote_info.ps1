# Показывает адрес и токен для подключения мобильного приложения.
# Требует запущенного start_remote.ps1 (туннель — по желанию).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$publicFile = ".\data\remote_url.json"
$statusFile = ".\data\remote_status.json"
$configFile = ".\config\config.json"

$configPublicUrl = $null
$token = $null
if (Test-Path $configFile) {
    $cfg = Get-Content $configFile -Raw | ConvertFrom-Json
    if ($cfg.remote -and $cfg.remote.public_url) {
        $configPublicUrl = [string]$cfg.remote.public_url
    }
    if ($cfg.remote -and $cfg.remote.token) { $token = $cfg.remote.token }
}
$publicUrl = $configPublicUrl
if (-not $publicUrl -and (Test-Path $publicFile)) {
    $publicUrl = (Get-Content $publicFile -Raw | ConvertFrom-Json).url
}
$localUrl = $null
$lanUrl = $null
$tailscaleUrl = $null
if (Test-Path $statusFile) {
    $status = Get-Content $statusFile -Raw | ConvertFrom-Json
    $localUrl = $status.url
    if ($status.PSObject.Properties.Name -contains "lan_url") {
        $lanUrl = $status.lan_url
    }
    if ($status.PSObject.Properties.Name -contains "tailscale_url") {
        $tailscaleUrl = $status.tailscale_url
    }
}
if (-not $tailscaleUrl) {
    $tsExe = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $tsExe) {
        $tsIp = (& $tsExe ip -4 2>$null | Select-Object -First 1)
        if ($tsIp -and $tsIp -match '^100\.') {
            $tsPort = 8765
            if ($cfg.remote -and $cfg.remote.port) { $tsPort = [int]$cfg.remote.port }
            $tailscaleUrl = "http://${tsIp}:${tsPort}/"
        }
    }
}
if (-not $tailscaleUrl -and -not $publicUrl -and -not $lanUrl) {
    Write-Host "Сервер не запущен. Сначала:"
    Write-Host "  scripts\start_remote.ps1"
    exit 1
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
if ($tailscaleUrl) {
    Write-Host " В любой сети (Tailscale на ПК и телефоне, один аккаунт):"
    Write-Host "   $tailscaleUrl"
    Write-Host ""
}
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
Write-Host " QR-код: JARVIS → Настройки → «Показать QR для телефона»"
Write-Host " (ссылка содержит адрес и токен; сканируйте приложением JARVIS)"
Write-Host ""
Write-Host " Токен:"
Write-Host "   $token"
Write-Host "==============================================="
