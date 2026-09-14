#Requires -Version 5.1
<#
.SYNOPSIS
  Start the Stock & POS stack detached (no rebuild unless images are missing).

.DESCRIPTION
  Runs: docker compose -f docker-compose.yml up -d
  Production images are reused; nothing is rebuilt unnecessarily.
  Exits non-zero when Docker is unavailable so callers (wait-and-open) can retry.
#>

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stockpos-common.ps1")

$root = Get-DeployRoot
if (-not (Test-ComposeStack $root)) {
  Write-Host "Deployment folder $root is not complete." -ForegroundColor Red
  Write-Host "It must contain docker-compose.yml and .env"
  Write-Host "(see infrastructure\README.md, 'First installation')."
  exit 1
}

if (-not (Assert-Docker)) { exit 1 }

Set-Location $root
Write-Host "Starting Stock & POS..." -ForegroundColor Cyan
docker compose (Get-ComposeArgs) up -d
$code = $LASTEXITCODE
if ($code -ne 0) {
  Write-Host ""
  Write-Host "Docker could not start the system. Check the message above." -ForegroundColor Red
  exit $code
}

Write-Host ""
Write-Host "Stock & POS containers are starting." -ForegroundColor Green
Write-Host "App: http://localhost:$(Get-FrontendPort $root)"
Write-Host "(Double-click open-system.bat to open the browser now.)"
exit 0