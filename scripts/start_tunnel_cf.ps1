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
$publicUrl = ""
$protocol = "http2"
try {
    $cfg = Get-Content ".\config\config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.remote -and $cfg.remote.tunnel_name) {
        $tunnelName = [string]$cfg.remote.tunnel_name
    }
    if ($cfg.remote -and $cfg.remote.public_url) {
        $publicUrl = ([string]$cfg.remote.public_url).TrimEnd("/")
    }
    if ($cfg.remote -and $cfg.remote.tunnel_protocol) {
        $protocol = ([string]$cfg.remote.tunnel_protocol).Trim().ToLower()
    }
} catch {}

# QUIC (UDP) часто блокируется — по умолчанию идём по TCP/HTTP2.
$protocolArgs = @()
if ($protocol -in @("http2", "quic")) {
    $protocolArgs = @("--protocol", $protocol)
} else {
    $protocol = "default"
}
Write-Host "Транспорт cloudflared: $protocol"

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
    if ($publicUrl) {
        $status = @{
            url      = $publicUrl
            local    = $target
            provider = "cloudflare-named"
            updated  = (Get-Date).ToString("o")
        }
        $status | ConvertTo-Json | Set-Content -Path ".\data\remote_url.json" -Encoding UTF8
        Write-Host "Публичный адрес: $publicUrl (сохранён в data\remote_url.json)"
    } else {
        Write-Host "Совет: укажите remote.public_url в config.json — QR-код сразу получит постоянный адрес."
    }
    Write-Host "Оставьте это окно открытым. Ctrl+C — остановить."
    & $cloudflared tunnel @protocolArgs run $tunnelName 2>&1 | ForEach-Object {
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

& $cloudflared tunnel @protocolArgs --url $target --no-autoupdate 2>&1 |
    ForEach-Object {
        $line = "$_"
        Write-Host $line
        Add-Content -Path $logFile -Value $line -Encoding UTF8
        if ($line -match "https://[a-zA-Z0-9-]+\.trycloudflare\.com") {
            $publicUrl = $Matches[0]
            Write-Host "Проверяю доступность $publicUrl ..."
            $ready = $false
            for ($i = 0; $i -lt 12; $i++) {
                try {
                    Invoke-WebRequest -Uri "$publicUrl/health" -UseBasicParsing `
                        -TimeoutSec 5 -ErrorAction Stop | Out-Null
                    $ready = $true
                    break
                } catch {
                    Start-Sleep -Seconds 5
                }
            }
            if ($ready) {
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
            } else {
                Write-Host "ВНИМАНИЕ: $publicUrl не отвечает на /health."
                Write-Host "Адрес не сохранён, чтобы телефон не получил мёртвую ссылку."
                Write-Host "Проверьте сеть/фаервол: QUIC часто блокируется — оставлен HTTP/2."
            }
        }
    }
