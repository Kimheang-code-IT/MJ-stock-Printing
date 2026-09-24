#Requires -Version 5.1
<#
.SYNOPSIS
  Restart the Stock & POS application safely (volumes preserved).

.DESCRIPTION
  docker compose restart-equivalent: up -d re-creates only containers whose
  config/image changed, keeps volumes, and re-runs migrations on the API
  (alembic upgrade head - append-only, never resets data).
#>

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "mj-common.ps1")

$root = Get-DeployRoot
if (-not (Test-ComposeStack $root)) {
  Write-Host "Deployment folder $root is not complete (docker-compose.yml + .env)." -ForegroundColor Red
  exit 1
}
if (-not (Assert-Docker)) { exit 1 }

Set-Location $root
Write-Host "Restarting Stock & POS (data is preserved)..." -ForegroundColor Cyan
docker compose (Get-ComposeArgs) up -d
$code = $LASTEXITCODE
if ($code -ne 0) {
  Write-Host "Docker could not restart the system. Check the message above." -ForegroundColor Red
  exit $code
}
Write-Host ""
Write-Host "Restarted. App: http://localhost:$(Get-FrontendPort $root)" -ForegroundColor Green
exit 0