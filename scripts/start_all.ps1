param(
    [switch]$NoHud,
    [switch]$NoPhone,
    [switch]$Tunnel,
    [switch]$NoWindow
)

# Запуск всего JARVIS одной командой:
# backend + HUD + remote-сервер + Telegram-бот (в одном процессе
# launcher_remote.py), опционально туннель и APK на USB-телефоне.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Не найдено .venv. Сначала выполните: scripts\install.ps1"
}

# Для автозапуска: без лишнего окна консоли (логи всё равно в data\).
$PythonExe = $Python
if ($NoWindow) {
    $Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if (Test-Path -LiteralPath $Pythonw) {
        $PythonExe = $Pythonw
    }
}

$HealthUrl = "http://127.0.0.1:8765/health"

function Test-JarvisHealth {
    try {
        Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 `
            -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Find-Adb {
    $candidates = @()
    if ($env:ANDROID_HOME) {
        $candidates += Join-Path $env:ANDROID_HOME "platform-tools\adb.exe"
    }
    if ($env:ANDROID_SDK_ROOT) {
        $candidates += Join-Path $env:ANDROID_SDK_ROOT "platform-tools\adb.exe"
    }
    if ($env:USERPROFILE) {
        $candidates += Join-Path $env:USERPROFILE "android-sdk\platform-tools\adb.exe"
    }
    if ($env:LOCALAPPDATA) {
        $candidates += Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
    }
    $localProps = Join-Path $Root "android\local.properties"
    if (Test-Path -LiteralPath $localProps) {
        $match = Select-String -Path $localProps -Pattern '^sdk\.dir=(.+)$' |
            Select-Object -First 1
        if ($match) {
            $sdk = $match.Matches[0].Groups[1].Value.Trim()
            $sdk = $sdk -replace '\\\\', '\'
            $candidates += Join-Path $sdk "platform-tools\adb.exe"
        }
    }
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $adbCommand = Get-Command adb -ErrorAction SilentlyContinue
    if ($adbCommand) {
        return $adbCommand.Source
    }
    return $null
}

function Find-Gradle {
    $localGradle = Join-Path $env:USERPROFILE "gradle-8.9\bin\gradle.bat"
    if (Test-Path -LiteralPath $localGradle) {
        return $localGradle
    }
    $gradleCommand = Get-Command gradle -ErrorAction SilentlyContinue
    if ($gradleCommand) {
        return $gradleCommand.Source
    }
    return $null
}

# 1. Backend + remote-сервер + Telegram-бот (+ HUD).
$core = $null
if (Test-JarvisHealth) {
    Write-Host "JARVIS уже отвечает на $HealthUrl — второй экземпляр не запускаю."
} else {
    $coreArgs = @("launcher_remote.py")
    if ($NoHud) {
        $coreArgs += "--no-hud"
    }
    $core = Start-Process -FilePath $PythonExe -ArgumentList $coreArgs `
        -WorkingDirectory $Root -PassThru
    Write-Host "Запускаю backend, remote-сервер и Telegram-бота (PID $($core.Id))..."
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-JarvisHealth) {
            $ready = $true
            break
        }
        if ($core.HasExited) {
            break
        }
    }
    if (-not $ready) {
        Write-Host "ВНИМАНИЕ: $HealthUrl не ответил. Смотрите окно JARVIS и data\jarvis.log."
    }
}

# 2. HTTPS-туннель Cloudflare (по флагу -Tunnel).
$tunnel = $null
if ($Tunnel) {
    $tunnelScript = Join-Path $Root "scripts\start_tunnel_cf.ps1"
    $tunnelArgs = "-NoExit -ExecutionPolicy Bypass -File `"$tunnelScript`""
    $tunnel = Start-Process powershell -ArgumentList $tunnelArgs -PassThru
    Write-Host "Туннель Cloudflare запускается в отдельном окне (PID $($tunnel.Id))."
}

# 3. APK на подключённом по USB телефоне.
if (-not $NoPhone) {
    $adb = Find-Adb
    if (-not $adb) {
        Write-Host "adb не найден — пропускаю установку APK (ключ -NoPhone отключает шаг)."
    } else {
        $devices = & $adb devices 2>$null |
            Where-Object { $_ -match '\sdevice$' }
        if (-not $devices) {
            Write-Host "USB-телефон не найден — пропускаю установку APK."
        } else {
            $gradle = Find-Gradle
            if ($gradle) {
                Write-Host "Собираю debug APK..."
                Push-Location (Join-Path $Root "android")
                try {
                    & $gradle assembleDebug
                } finally {
                    Pop-Location
                }
                if ($LASTEXITCODE -ne 0) {
                    Write-Host "Сборка APK не удалась — пробую установить существующий файл."
                }
            }
            $apk = Join-Path $Root "android\app\build\outputs\apk\debug\app-debug.apk"
            if (Test-Path -LiteralPath $apk) {
                Write-Host "Устанавливаю APK на телефон..."
                & $adb install -r $apk
                if ($LASTEXITCODE -eq 0) {
                    & $adb shell am start -n "com.jarvis.remote/.MainActivity" |
                        Out-Null
                    Write-Host "APK установлен и открыт."
                } else {
                    Write-Host "adb install завершился с ошибкой."
                }
            } else {
                Write-Host "APK не найден: $apk"
            }
        }
    }
}

# 4. Адрес и токен для приложения.
Start-Sleep -Seconds 1
Write-Host ""
$RemoteInfo = Join-Path $Root "scripts\remote_info.ps1"
if (Test-Path -LiteralPath $RemoteInfo) {
    & $RemoteInfo
}

Write-Host ""
if ($core) {
    Write-Host "Готово. Остановить JARVIS: Stop-Process -Id $($core.Id)"
} else {
    Write-Host "Готово. JARVIS уже был запущен до этого скрипта."
}
if ($tunnel) {
    Write-Host "Остановить туннель: Stop-Process -Id $($tunnel.Id)"
}
