#Requires -Version 5.1
<#
.SYNOPSIS
  Remove the current-user Startup shortcut created by install-autostart.ps1.
#>

$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$linkPath = Join-Path $startup "MJ Stock POS (wait and open).lnk"

if (Test-Path $linkPath) {
  Remove-Item $linkPath -Force
  Write-Host "Auto-start removed (shortcut deleted)." -ForegroundColor Green
} else {
  Write-Host "No auto-start shortcut found - nothing to remove."
}
exit 0