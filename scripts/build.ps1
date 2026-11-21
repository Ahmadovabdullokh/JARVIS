$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run scripts\install.ps1 first."
}

& $Python -m pip install pyinstaller
& $Python scripts\gen_version.py
& $Python -m PyInstaller --noconfirm jarvis.spec

# The frozen app resolves .env relative to the exe dir (BASE_DIR/data).
# Copy it so API keys (GROQ_API_KEY, DEEPSEEK_API_KEY) are available.
if (Test-Path -LiteralPath ".env") {
    Copy-Item -LiteralPath ".env" -Destination "dist\JARVIS\.env" -Force
}

Write-Host "[JARVIS] Build complete: dist\JARVIS\JARVIS.exe"
