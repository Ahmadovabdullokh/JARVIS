$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\install.ps1 first."
}

& $Python -m pip install pyinstaller
& $Python -m PyInstaller --noconfirm jarvis.spec

Write-Host "[JARVIS] Build complete: dist\JARVIS.exe"
