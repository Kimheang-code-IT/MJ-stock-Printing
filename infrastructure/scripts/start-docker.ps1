# Start the development Stock & POS stack in Docker (build + detach).
# Runs from the infrastructure/ folder so .env and the compose files are found.
$ErrorActionPreference = 'Stop'
$Infra = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Infra
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { '80' }
$ApiPort = if ($env:API_HOST_PORT) { $env:API_HOST_PORT } else { '8100' }
Write-Host ""
Write-Host "Stock & POS development stack is starting (mj-stock-management-db, mj-stock-management-redis, mj-stock-management-api, mj-stock-management-frontend)."
Write-Host "  Frontend (nginx): http://localhost:$FrontendPort"
Write-Host "  API docs:         http://localhost:$ApiPort/docs"
Write-Host ""
Write-Host "For a local-only production run use: .\scripts\mj\start-system.ps1"
Write-Host "Check status: docker compose ps"
Write-Host "View logs:    docker compose logs -f mj-stock-management-frontend mj-stock-management-api"
