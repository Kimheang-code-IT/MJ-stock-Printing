#Requires -Version 5.1
<#
.SYNOPSIS
  Shared helpers for the local-only Windows deployment of Stock & POS.

.DESCRIPTION
  Thin functions used by the double-clickable .bat wrappers in this folder:
  start / stop / restart / open / wait-and-open / autostart install/remove.
  Everything works without administrator rights; Docker Desktop must be
  installed for the current user.

  The Compose files and `.env` live in the `infrastructure/` folder next to the
  `scripts/` folder. Set STOCKPOS_DIR to that folder to override autodetection.
#>

$ErrorActionPreference = "Stop"

# Deployment folder: the `infrastructure/` folder that contains
# docker-compose.yml, docker-compose.local.yml and `.env`.
# Autodetected from this script's location; override with STOCKPOS_DIR.
function Get-DeployRoot {
  if ($env:STOCKPOS_DIR) { return $env:STOCKPOS_DIR }
  if ($env:STOCKPOS_HOME) { return $env:STOCKPOS_HOME }
  # This file lives in infrastructure\scripts\stockpos\, so go up two levels.
  return (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

function Assert-Docker([switch]$Quiet) {
  $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $dockerCmd) {
    if ($Quiet) { return $false }
    Write-Host ""
    Write-Host "Docker is not available yet." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "If Docker Desktop is installed, it is still starting up." -ForegroundColor Yellow
    Write-Host "Please wait a moment and try again, or double-click" -ForegroundColor Yellow
    Write-Host "wait-and-open-system.bat which waits for Docker automatically." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "If this message keeps appearing, start 'Docker Desktop' from" -ForegroundColor Yellow
    Write-Host "the Start menu and make sure it is set to start with Windows:" -ForegroundColor Yellow
    Write-Host "  Docker Desktop > Settings > General > 'Start Docker Desktop when you sign in'" -ForegroundColor Yellow
    Write-Host ""
    return $false
  }
  # The engine may still be starting even though docker.exe exists.
  docker info *> $null
  if ($LASTEXITCODE -ne 0) {
    if ($Quiet) { return $false }
    Write-Host ""
    Write-Host "Docker Desktop is still starting up. Please try again in a minute." -ForegroundColor Yellow
    Write-Host "(Or double-click wait-and-open-system.bat — it waits for you.)" -ForegroundColor Yellow
    Write-Host ""
    return $false
  }
  return $true
}

function Get-ComposeArgs {
  return @("-f", "docker-compose.yml", "-f", "docker-compose.local.yml")
}

function Test-ComposeStack($Root) {
  return (Test-Path (Join-Path $Root "docker-compose.yml")) -and
         (Test-Path (Join-Path $Root "docker-compose.local.yml")) -and
         (Test-Path (Join-Path $Root ".env"))
}

function Get-FrontendPort($Root) {
  $port = "80"
  $envFile = Join-Path $Root ".env"
  if (Test-Path $envFile) {
    foreach ($line in (Get-Content $envFile)) {
      if ($line -match '^\s*FRONTEND_PORT\s*=\s*(.+)\s*$') { $port = $Matches[1].Trim() }
    }
  }
  return $port
}

function Get-ApiHealthUrl($Root) {
  # Same-origin through the frontend nginx proxy (the API port is not published).
  return "http://localhost:$(Get-FrontendPort $Root)/health/ready"
}

function Test-AppHealthy($Root) {
  try {
    $response = Invoke-WebRequest -Uri (Get-ApiHealthUrl $Root) -UseBasicParsing -TimeoutSec 4
    $ok = $response.Content -match '"status"\s*:\s*"ok"'
    if ($ok) { return $true }
  } catch { }
  return $false
}

function Start-Stack {
  $root = Get-DeployRoot
  if (-not (Test-ComposeStack $root)) {
    Write-Host "Deployment folder $root is not complete." -ForegroundColor Red
    Write-Host "It must contain docker-compose.yml, docker-compose.local.yml and .env"
    Write-Host "(run infrastructure\scripts\init-env.ps1 to create .env, then see"
    Write-Host " infrastructure\README.md for the first installation)."
    return 1
  }
  Set-Location $root
  if (-not (Assert-Docker)) { return 1 }
  Write-Host "Starting Stock & POS..." -ForegroundColor Cyan
  docker compose (Get-ComposeArgs) up -d 2>&1 | ForEach-Object { "$_" }
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker failed to start the stack. Check the message above." -ForegroundColor Red
    return $LASTEXITCODE
  }
  Write-Host "Containers are starting. The app opens automatically when healthy." -ForegroundColor Green
  Write-Host "App address: http://localhost:$(Get-FrontendPort $Root)"
  return 0
}