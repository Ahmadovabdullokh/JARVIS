$ErrorActionPreference = "Stop"
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "JARVIS.lnk"

if (Test-Path -LiteralPath $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath -Force
    Write-Host "[JARVIS] Autostart removed: $ShortcutPath"
}
else {
    Write-Host "[JARVIS] Autostart shortcut not found."
}
