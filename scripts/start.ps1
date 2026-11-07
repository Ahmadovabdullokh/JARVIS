$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Pythonw)) {
    throw "Virtual environment not found. Run scripts\install.ps1 first."
}

Start-Process -FilePath $Pythonw `
    -ArgumentList "launcher.py" `
    -WorkingDirectory $Root
