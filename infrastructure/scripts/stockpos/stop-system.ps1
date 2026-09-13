#Requires -Version 5.1
<#
.SYNOPSIS
  Stop the Stock & POS application containers safely.

.DESCRIPTION
  docker compose stop + docker compose stop (no 'down', no volume removal).
  PostgreSQL data (pgdata), media (mediadata) and any backups are preserved.
  Redis data is also preserved by default; it is transient anyway.
#>

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "stockpos-common.ps1")

$root = Get-DeployRoot
if (-not (Test-ComposeStack $root)) {
  Write-Host "Deployment folder $root is not complete (docker-compose.yml + docker-compose.local.yml + .env)." -ForegroundColor Red
  exit 1
}
if (-not (Assert-Docker)) { exit 1 }

Set-Location $root
Write-Host "Stopping Stock & POS (your data is NOT deleted)..." -ForegroundColor Cyan
docker compose (Get-ComposeArgs) stop
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host ""
Write-Host "Stopped. Database, images and backups are untouched." -ForegroundColor Green
Write-Host "Start again with start-system.bat."
exit 0