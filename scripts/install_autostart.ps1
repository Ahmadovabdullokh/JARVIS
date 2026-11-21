$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# Prefer the packaged app (real .exe, no console window); fall back to the venv.
$Exe = Join-Path $Root "dist\JARVIS\JARVIS.exe"
$Target = $null
$Arguments = $null
$IconLocation = $null

if (Test-Path -LiteralPath $Exe) {
    $Target = $Exe
    $IconLocation = $Exe
}
else {
    $Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
    if (-not (Test-Path -LiteralPath $Pythonw)) {
        throw "Neither dist\JARVIS\JARVIS.exe nor .venv found. Run scripts\install.ps1 / scripts\build.ps1 first."
    }
    $Target = $Pythonw
    $Arguments = "launcher_web.py"
}

$Shell = New-Object -ComObject WScript.Shell

function New-JarvisShortcut($Path) {
    $Shortcut = $Shell.CreateShortcut($Path)
    $Shortcut.TargetPath = $Target
    if ($Arguments) { $Shortcut.Arguments = $Arguments }
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.Description = "JARVIS personal assistant"
    if ($IconLocation) { $Shortcut.IconLocation = $IconLocation }
    $Shortcut.Save()
}

# Desktop shortcut.
$Desktop = [Environment]::GetFolderPath("Desktop")
New-JarvisShortcut (Join-Path $Desktop "JARVIS.lnk")

# Startup-folder shortcut: runs JARVIS at user logon (no admin rights needed).
# On workstation unlock the app itself restores its window
# (see _unlock_watch_loop in launcher_web.py).
$Startup = [Environment]::GetFolderPath("Startup")
New-JarvisShortcut (Join-Path $Startup "JARVIS.lnk")

Write-Host "[JARVIS] Desktop shortcut created."
Write-Host "[JARVIS] Autostart installed (at logon): $(Join-Path $Startup 'JARVIS.lnk')"
Write-Host "[JARVIS] Window is shown automatically on workstation unlock."
