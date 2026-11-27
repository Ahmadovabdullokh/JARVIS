param(
    # Playwright + Chromium (~300-400 МБ) — только по явному запросу.
    [switch]$WithPlaywright
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
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

foreach ($Exe in @($Python, $Pythonw)) {
    if (Test-Path -LiteralPath $Exe) {
        & icacls $Exe /setintegritylevel Medium *> $null
    }
}

& $Python -m pip install --upgrade pip
& $Python -m pip install -r requirements.txt

# MediaPipe для жестов ставим без зависимостей, чтобы не менять
# закреплённые версии opencv-python и sounddevice.
try {
    & $Python -m pip install --no-deps "mediapipe==1.2.3"
    & $Python -m pip install "absl-py~=2.3" "flatbuffers~=25.9"
}
catch {
    Write-Warning "MediaPipe install failed: $_"
    Write-Warning "Gestures will be unavailable until MediaPipe is installed."
}

$ModelDir = Join-Path $Root "models"
$ModelPath = Join-Path $ModelDir "hand_landmarker.task"
if (-not (Test-Path -LiteralPath $ModelPath)) {
    try {
        New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null
        $ModelUrl = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
        Write-Host "[JARVIS] Downloading hand_landmarker.task..."
        Invoke-WebRequest -Uri $ModelUrl -OutFile $ModelPath -UseBasicParsing
    }
    catch {
        Write-Warning "Gesture model download failed: $_"
        Write-Warning "Download hand_landmarker.task into models/ manually."
    }
}

if (-not (Test-Path -LiteralPath "config\config.json")) {
    Copy-Item -LiteralPath "config\config.example.json" `
        -Destination "config\config.json"
    Write-Host "[JARVIS] Created config\config.json from example."
}

if ($WithPlaywright) {
    try {
        & $Python -m pip install "playwright==1.64.1"
        & $Python -m playwright install chromium
    }
    catch {
        Write-Warning "Playwright chromium install failed: $_"
        Write-Warning "Run: .venv\Scripts\python.exe -m playwright install chromium"
    }
}
else {
    Write-Host "[JARVIS] Playwright пропущен (browser automation опционально: install.ps1 -WithPlaywright)."
}

Write-Host "[JARVIS] Running diagnostics..."
& $Python -m app.doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Some diagnostics failed. Review the report above."
}

Write-Host "[JARVIS] Installation complete."
Write-Host "Start with: scripts\start.ps1"
