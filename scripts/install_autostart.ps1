$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# Launch the app directly (pythonw / packaged exe). launcher_web starts the
# HUD, the remote server for the phone and Telegram automatically.
# Avoid a PowerShell-backed shortcut: some antivirus suites delete those
# from the Startup folder. Use scripts\start_all.ps1 manually for tunnel/APK.
$Exe = Join-Path $Root "dist\JARVIS\JARVIS.exe"
$VenvPythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$Shell = New-Object -ComObject WScript.Shell

function Set-JarvisShortcut($Directory, [string[]]$Names) {
    foreach ($Name in $Names) {
        $Path = Join-Path $Directory $Name
        try {
            $Shortcut = $Shell.CreateShortcut($Path)
            if (Test-Path -LiteralPath $VenvPythonw) {
                $Shortcut.TargetPath = $VenvPythonw
                $Shortcut.Arguments = "launcher_web.py"
            }
            elseif (Test-Path -LiteralPath $Exe) {
                $Shortcut.TargetPath = $Exe
            }
            else {
                throw "Neither .venv\Scripts\pythonw.exe nor dist\JARVIS\JARVIS.exe found."
            }
            $Shortcut.WorkingDirectory = $Root
            $Shortcut.Description = "JARVIS personal assistant"
            if (Test-Path -LiteralPath $Exe) {
                $Shortcut.IconLocation = $Exe
            }
            $Shortcut.Save()
            Start-Sleep -Seconds 2
            if (Test-Path -LiteralPath $Path) {
                return $Path
            }
        }
        catch {
            # Name blocked by antivirus or a locked file: try the next one.
        }
    }
    return $null
}

# Desktop shortcut.
$Desktop = [Environment]::GetFolderPath("Desktop")
$DesktopShortcut = Set-JarvisShortcut $Desktop @("JARVIS.lnk", "JARVIS App.lnk")

# Startup-folder shortcut: runs JARVIS at user logon (no admin rights needed).
# On workstation unlock the app itself restores its window
# (see _unlock_watch_loop in launcher_web.py).
$Startup = [Environment]::GetFolderPath("Startup")
$StartupShortcut = Set-JarvisShortcut $Startup @("JARVIS.lnk", "JARVIS App.lnk")

if ($DesktopShortcut) {
    Write-Host "[JARVIS] Desktop shortcut: $DesktopShortcut"
}
else {
    Write-Warning "[JARVIS] Could not create a desktop shortcut (blocked by antivirus?)."
}

if ($StartupShortcut) {
    Write-Host "[JARVIS] Autostart installed (at logon): $StartupShortcut"
    Write-Host "[JARVIS] The app starts the HUD, phone server and Telegram bot."
}
else {
    Write-Warning ("[JARVIS] Could not create an autostart shortcut. " +
        "Allow JARVIS in your antivirus or add an exception for the Startup folder.")
}
