#Requires -Version 5.1
<#
.SYNOPSIS
  Delete ALL data from the Stock & POS database (schema and migrations stay).

.DESCRIPTION
  Runs the backend wipe script inside the api image so the correct
  DATABASE_URL / REDIS_URL from infrastructure\.env are used. Every table row
  is removed, alembic_version is kept, and Redis is flushed (sessions, locks,
  revoked tokens). The app then starts empty: create the first administrator on
  the Setup page.

  Without -Yes the script asks for confirmation. Use -NoRedis to keep Redis.

.EXAMPLE
  .\infrastructure\scripts\clear-data.ps1
.EXAMPLE
  .\infrastructure\scripts\clear-data.ps1 -Yes
#>

param(
  [switch]$Yes,
  [switch]$NoRedis
)

$ErrorActionPreference = "Stop"

$infraDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeFile = Join-Path $infraDir "docker-compose.yml"
$envFile = Join-Path $infraDir ".env"

if (-not (Test-Path $composeFile)) {
  Write-Error "Missing $composeFile"
}
if (-not (Test-Path $envFile)) {
  Write-Host "No .env found in $infraDir" -ForegroundColor Yellow
  Write-Host "Run infrastructure\scripts\init-env.ps1 first."
  exit 1
}

Set-Location $infraDir

$scriptArgs = @("python", "scripts/clear_data.py")
if ($Yes) { $scriptArgs += "--yes" }
if ($NoRedis) { $scriptArgs += "--no-redis" }

Write-Host "Clearing all Stock & POS data..." -ForegroundColor Cyan
docker compose -f docker-compose.yml run --rm api @scriptArgs
$code = $LASTEXITCODE
if ($code -ne 0) {
  Write-Host "Clear failed (exit $code)." -ForegroundColor Red
  exit $code
}

Write-Host ""
Write-Host "All data cleared. Open the app and finish the first-time setup." -ForegroundColor Green
exit 0
