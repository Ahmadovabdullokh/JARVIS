param(
    [switch]$SkipPlaywright
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

Write-Host "[JARVIS] Python project: $Root"

if (-not (Test-Path -LiteralPath ".venv")) {
    Write-Host "[JARVIS] Creating virtual environment..."
    python -m venv .venv
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt

if (-not (Test-Path -LiteralPath "config\config.json")) {
    Copy-Item -LiteralPath "config\config.example.json" `
        -Destination "config\config.json"
    Write-Host "[JARVIS] Created config\config.json from example."
}

if (-not $SkipPlaywright) {
    try {
        & $Python -m playwright install chromium
    }
    catch {
        Write-Warning "Playwright chromium install failed: $_"
        Write-Warning "Run: .venv\Scripts\python.exe -m playwright install chromium"
    }
}

Write-Host "[JARVIS] Running diagnostics..."
& $Python -m app.doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Some diagnostics failed. Review the report above."
}

Write-Host "[JARVIS] Installation complete."
Write-Host "Start with: scripts\start.ps1"
