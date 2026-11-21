# Поднимает HTTPS-туннель к локальному JARVIS remote-серверу
# через Pinggy (ssh -R, без регистрации).
# Публичный URL сохраняется в data\remote_url.json
# Предварительно должен быть запущен scripts\start_remote.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$target = "http://127.0.0.1:8765"
$logFile = ".\data\pinggy.log"

# Проверяем, что локальный сервер жив
try {
    Invoke-WebRequest -Uri "$target/" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop | Out-Null
} catch {
    # 401 — тоже нормально: сервер отвечает, просто без токена
    if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) {
        Write-Host "Локальный сервер JARVIS Remote отвечает (401 без токена — ок)."
    } else {
        Write-Host "ВНИМАНИЕ: локальный сервер не отвечает на $target"
        Write-Host "Сначала запустите: scripts\start_remote.ps1"
    }
}

Write-Host "Запускаю туннель Pinggy к $target ..."
Write-Host "Оставьте это окно открытым. Ctrl+C — остановить."

# ssh печатает URL в stdout; перенаправляем в файл и показываем
ssh -p 443 -o StrictHostKeyChecking=no -o ServerAliveInterval=30 `
    -o ExitOnForwardFailure=yes -R0:localhost:8765 a.pinggy.io 2>&1 |
    ForEach-Object {
        $line = "$_"
        Write-Host $line
        Add-Content -Path $logFile -Value $line -Encoding UTF8
        if ($line -match "https://[a-zA-Z0-9.-]+\.(free\.pinggy\.net|run\.pinggy-free\.link|pinggy\.link|pinggy\.net)") {
            $publicUrl = $Matches[0]
            $status = @{
                url     = $publicUrl
                local   = $target
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
