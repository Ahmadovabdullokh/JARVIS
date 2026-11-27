$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\install.ps1 first."
}

$GestureModel = Join-Path $Root "models\hand_landmarker.task"
if (-not (Test-Path -LiteralPath $GestureModel)) {
    throw "models\hand_landmarker.task not found. Run scripts\install.ps1 first."
}

& $Python -m pip install pyinstaller
& $Python scripts\gen_version.py
& $Python -m PyInstaller --noconfirm jarvis.spec

# Секреты (.env) в сборку не попадают. Пользователь задаёт ключи через
# переменные окружения или config.json в своём профиле.
$LeakedEnv = Join-Path $Root "dist\JARVIS\.env"
if (Test-Path -LiteralPath $LeakedEnv) {
    Remove-Item -LiteralPath $LeakedEnv -Force
    Write-Host "[JARVIS] Removed stale .env from dist (secrets must not ship)."
}

Write-Host "[JARVIS] Build complete: dist\JARVIS\JARVIS.exe"
