# Запускает JARVIS Remote: backend-сервер и HTTPS-туннель
# в двух отдельных окнах. Оставьте оба окна открытыми.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$remote = Join-Path $root "scripts\start_remote.ps1"
$tunnel = Join-Path $root "scripts\start_tunnel.ps1"

# Если сервер уже отвечает — не дублируем
try {
    Invoke-WebRequest -Uri "http://127.0.0.1:8765/" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop | Out-Null
    Write-Host "Сервер уже запущен, пропускаю start_remote."
} catch {
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) {
        Write-Host "Сервер уже запущен (401 без токена — ок), пропускаю."
    } else {
        Start-Process powershell -ArgumentList @(
            "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $remote
        )
        Write-Host "Запущен JARVIS Remote server (окно 1)."
        Start-Sleep -Seconds 3
    }
}

# Туннель: проверяем по свежему remote_url.json
$urlFile = Join-Path $root "data\remote_url.json"
$fresh = $false
if (Test-Path $urlFile) {
    $info = Get-Content $urlFile -Raw | ConvertFrom-Json
    if ($info.url -and $info.updated) {
        $age = (Get-Date) - [datetime]$info.updated
        $fresh = $age.TotalMinutes -lt 30
    }
}
if ($fresh) {
    try {
        Invoke-WebRequest -Uri "$($info.url)/" -UseBasicParsing -TimeoutSec 8 -ErrorAction Stop | Out-Null
        Write-Host "Туннель уже работает: $($info.url)"
        Write-Host "Данные для приложения: scripts\remote_info.ps1"
        exit 0
    } catch {
        # 401/403 — туннель жив, просто без токена
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -in 401,403) {
            Write-Host "Туннель уже работает: $($info.url)"
            Write-Host "Данные для приложения: scripts\remote_info.ps1"
            exit 0
        }
    }
}

Start-Process powershell -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-File", $tunnel
)
Write-Host "Запущен туннель (окно 2)."
Write-Host "Когда появится адрес — выполните scripts\remote_info.ps1"
