#Requires -Version 5.1
<#
.SYNOPSIS
  Add Stock & POS to the current user's Windows Startup folder (no admin needed).

.DESCRIPTION
  Creates wait-and-open-system.lnk in:
    %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
  The shortcut runs the wait-and-open script minimized. Windows runs Startup
  shortcuts at sign-in; Docker Desktop (configured to start at sign-in) brings
  the engine up, compose services restart automatically (restart:
  unless-stopped), the script waits for health, then the browser opens once.
#>

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "mj-common.ps1")

$startup = [Environment]::GetFolderPath("Startup")
$linkPath = Join-Path $startup "MJ Stock POS (wait and open).lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\cmd.exe"
$shortcut.Arguments = "/c `"$PSScriptRoot\wait-and-open-system.bat`" >> `"$env:TEMP\mj-autostart.log`" 2>&1"
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.WindowStyle = 7
$shortcut.Description = "Stock & POS: start containers, wait for health, open the app"
$shortcut.IconLocation = Join-Path $PSScriptRoot "mj.ico,0"
if (-not (Test-Path (Join-Path $PSScriptRoot "mj.ico"))) {
  # No .ico shipped — fall back to a stock icon; never invent binary assets.
  $shortcut.IconLocation = "%SystemRoot%\System32\SHELL32.dll,13"
}
$shortcut.Save()

Write-Host ""
Write-Host "Auto-start installed (current user only)." -ForegroundColor Green
Write-Host "Startup shortcut: $linkPath"
Write-Host ""
Write-Host "Also make sure Docker Desktop starts automatically:"
Write-Host "  Docker Desktop > Settings > General > 'Start Docker Desktop when you sign in'"
Write-Host ""
Write-Host "To undo, run remove-autostart.bat (or delete the shortcut above)."
exit 0