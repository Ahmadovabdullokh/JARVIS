param(
    [switch]$Installer
)

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

$Cloudflared = Join-Path $Root "tools\cloudflared.exe"
if (-not (Test-Path -LiteralPath $Cloudflared)) {
    Write-Warning "tools\cloudflared.exe not found: tunnel autostart will be unavailable."
}

# PyInstaller-сборке и установщику нужен запас на диске (SSD ~20 ГБ).
$Drive = (Get-Item -LiteralPath $Root).PSDrive
$FreeGb = [math]::Round($Drive.Free / 1GB, 1)
if ($FreeGb -lt 5) {
    throw "Not enough free space: $FreeGb GB. At least 5 GB is required for the build."
}
Write-Host "[JARVIS] Free space: $FreeGb GB"

Write-Host "[JARVIS] Cleaning previous build output..."
foreach ($Path in @("build\JARVIS", "dist\JARVIS")) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

# Версия PyInstaller закреплена: сборка не зависит от свежего релиза.
& $Python -m pip install --disable-pip-version-check "pyinstaller==6.22.3"
& $Python scripts\gen_version.py
& $Python -m PyInstaller --noconfirm --clean jarvis.spec

# Секреты (.env) в сборку не попадают. Пользователь задаёт ключи через
# переменные окружения или config.json в своём профиле.
$LeakedEnv = Join-Path $Root "dist\JARVIS\.env"
if (Test-Path -LiteralPath $LeakedEnv) {
    Remove-Item -LiteralPath $LeakedEnv -Force
    Write-Host "[JARVIS] Removed stale .env from dist (secrets must not ship)."
}

$DistDir = Join-Path $Root "dist\JARVIS"
$SizeMb = [math]::Round(
    ((Get-ChildItem -LiteralPath $DistDir -Recurse -File |
        Measure-Object -Property Length -Sum).Sum / 1MB), 1
)
Write-Host "[JARVIS] Build complete: $DistDir\JARVIS.exe ($SizeMb MB)"

if ($Installer) {
    $Iscc = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
        Select-Object -First 1
    if (-not $Iscc) {
        throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isinfo.php or run without -Installer."
    }
    & $Iscc (Join-Path $Root "packaging\jarvis.iss")
    Write-Host "[JARVIS] Installer: dist_installer\JARVIS-Setup.exe"
}
