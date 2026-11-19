param(
    [switch]$Tk
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $Pythonw)) {
    throw "Virtual environment not found. Run scripts\install.ps1 first."
}

$Script = if ($Tk) { "launcher.py" } else { "launcher_web.py" }

Start-Process -FilePath $Pythonw `
    -ArgumentList $Script `
    -WorkingDirectory $Root
