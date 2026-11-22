# Поднимает HTTPS-туннель к локальному JARVIS remote-серверу
# через Cloudflare quick tunnel (cloudflared.exe, без регистрации).
# Публичный URL сохраняется в data\remote_url.json
# Предварительно должен быть запущен scripts\start_remote.ps1
#
# Для постоянного адреса настройте named tunnel:
#   cloudflared tunnel login
#   cloudflared tunnel create jarvis
#   cloudflared tunnel route dns jarvis jarvis.example.com
# и укажите в config.json -> remote.tunnel_name = "jarvis"
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$target = "http://127.0.0.1:8765"
$logFile = ".\data\cloudflared.log"
$cloudflared = ".\tools\cloudflared.exe"
if (-not (Test-Path $cloudflared)) {
    $cloudflared = "cloudflared"
}

# Читаем config.json: поддержка named tunnel для постоянного URL
$tunnelName = ""
try {
    $cfg = Get-Content ".\config\config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.remote -and $cfg.remote.tunnel_name) {
        $tunnelName = [string]$cfg.remote.tunnel_name
    }
} catch {}

# Проверяем, что локальный сервер жив
try {
    Invoke-WebRequest -Uri "$target/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop | Out-Null
    Write-Host "Локальный сервер JARVIS отвечает (/health ok)."
} catch {
    Write-Host "ВНИМАНИЕ: локальный сервер не отвечает на $target/health"
    Write-Host "Сначала запустите: scripts\start_remote.ps1"
}

if ($tunnelName) {
    Write-Host "Запускаю named tunnel '$tunnelName' ..."
    Write-Host "URL задаётся маршрутом DNS (cloudflared tunnel route dns)."
    Write-Host "Оставьте это окно открытым. Ctrl+C — остановить."
    & $cloudflared tunnel run $tunnelName 2>&1 | ForEach-Object {
        $line = "$_"
        Write-Host $line
        Add-Content -Path $logFile -Value $line -Encoding UTF8
    }
    exit 0
}

Write-Host "Запускаю quick tunnel к $target ..."
Write-Host "ВНИМАНИЕ: quick tunnel выдаёт новый URL при каждом запуске."
Write-Host "Для постоянного адреса используйте named tunnel (см. шапку скрипта)."
Write-Host "Оставьте это окно открытым. Ctrl+C — остановить."

& $cloudflared tunnel --url $target --no-autoupdate 2>&1 |
    ForEach-Object {
        $line = "$_"
        Write-Host $line
        Add-Content -Path $logFile -Value $line -Encoding UTF8
        if ($line -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
            $publicUrl = $Matches[0]
            $status = @{
                url     = $publicUrl
                local   = $target
                provider = "cloudflare"
                updated = (Get-Date).ToString("o")
            }
            $status | ConvertTo-Json | Set-Content -Path ".\data\remote_url.json" -Encoding UTF8
            Write-Host ""
            Write-Host "==============================================="
            Write-Host " Публичный адрес: $publicUrl"
            Write-Host " Сохранён в data\remote_url.json"
            Write-Host "==============================================="
        }
    }
