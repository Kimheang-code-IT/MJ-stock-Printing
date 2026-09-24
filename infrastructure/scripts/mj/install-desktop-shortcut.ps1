#Requires -Version 5.1
<#
.SYNOPSIS
  Create a desktop shortcut named "MJ Printing" that opens the app.

.DESCRIPTION
  Target: open-system.bat (which opens http://localhost in the default browser).
  Reuses mj.ico in this folder when present; never invents binary assets.
#>

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "mj-common.ps1")

$desktop = [Environment]::GetFolderPath("Desktop")
$linkPath = Join-Path $desktop "MJ Printing.lnk"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($linkPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\cmd.exe"
$shortcut.Arguments = "/c `"$PSScriptRoot\open-system.bat`""
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Open the MJ Printing stock & POS system"
$shortcut.IconLocation = Join-Path $PSScriptRoot "mj.ico,0"
if (-not (Test-Path (Join-Path $PSScriptRoot "mj.ico"))) {
  $shortcut.IconLocation = "%SystemRoot%\System32\SHELL32.dll,13"
}
$shortcut.Save()

Write-Host ""
Write-Host "Desktop shortcut created: $linkPath" -ForegroundColor Green
Write-Host "Double-click it to open http://localhost in your browser."
exit 0