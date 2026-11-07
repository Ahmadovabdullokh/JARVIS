$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $Pythonw)) {
    throw "Virtual environment not found. Run scripts\install.ps1 first."
}

$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "JARVIS.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Pythonw
$Shortcut.Arguments = "launcher.py"
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = "JARVIS personal assistant"
$Shortcut.Save()

Write-Host "[JARVIS] Autostart installed: $ShortcutPath"
