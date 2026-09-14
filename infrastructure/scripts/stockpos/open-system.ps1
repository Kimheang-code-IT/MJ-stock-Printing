#Requires -Version 5.1
<#
.SYNOPSIS
  Open http://localhost in the default browser (single window, no duplicates).
#>

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stockpos-common.ps1")

$root = Get-DeployRoot
$url = "http://localhost:$(Get-FrontendPort $root)"

if (-not (Assert-Docker -Quiet)) {
  # Docker not ready — still open a friendly local page so the click is not a dead end.
  Write-Host "The app is not running yet (Docker is not ready)."
  Write-Host "Double-click start-system.bat, or wait-and-open-system.bat to start and open automatically."
  exit 1
}

if (-not (Test-AppHealthy $root)) {
  Write-Host "The system is still starting up. The browser will open shortly..." -ForegroundColor Cyan
  $deadline = (Get-Date).AddSeconds(90)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    if (Test-AppHealthy $root) { break }
  }
  if (-not (Test-AppHealthy $root)) {
    Write-Host "The system did not become healthy within 90 seconds." -ForegroundColor Yellow
    Write-Host "Try restart-system.bat, or see infrastructure\README.md > Troubleshooting."
    # Still try to open so the user sees the browser's own connection error.
    Start-Process "http://localhost"
    exit 1
  }
}

# Invoke-Item on a URL opens exactly one default-browser window per call.
Start-Process $url
exit 0