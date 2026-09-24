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
  `scripts/` folder. Set MJ_DIR to that folder to override autodetection.
#>

$ErrorActionPreference = "Stop"

# Deployment folder: the `infrastructure/` folder that contains
# docker-compose.yml and `.env`.
# Autodetected from this script's location; override with MJ_DIR.
function Get-DeployRoot {
  if ($env:MJ_DIR) { return $env:MJ_DIR }
  if ($env:MJ_HOME) { return $env:MJ_HOME }
  # This file lives in infrastructure\scripts\mj\, so go up two levels.
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
    Write-Host "(Or double-click wait-and-open-system.bat - it waits for you.)" -ForegroundColor Yellow
    Write-Host ""
    return $false
  }
  return $true
}

function Get-ComposeArgs {
  return @("-f", "docker-compose.yml")
}

function Test-ComposeStack($Root) {
  return (Test-Path (Join-Path $Root "docker-compose.yml")) -and
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

# Location of the shipped app logo (frontend assets). Returns $null when the
# repository layout is not present (e.g. a packaged install without the source).
function Get-AppLogoPng {
  $candidates = @(
    (Join-Path $PSScriptRoot "..\..\..\frontend\app\assets\images\logo.png"),
    (Join-Path (Get-DeployRoot) "..\frontend\app\assets\images\logo.png")
  )
  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { return (Resolve-Path $candidate).Path }
  }
  return $null
}

# Build a multi-resolution .ico from a PNG using System.Drawing (Windows only).
function New-IcoFromPng {
  param(
    [Parameter(Mandatory = $true)][string]$PngPath,
    [Parameter(Mandatory = $true)][string]$IcoPath
  )
  Add-Type -AssemblyName System.Drawing
  $sizes = @(16, 32, 48, 64, 128, 256)
  $source = [System.Drawing.Image]::FromFile($PngPath)
  try {
    $images = New-Object System.Collections.Generic.List[byte[]]
    foreach ($size in $sizes) {
      $bitmap = New-Object System.Drawing.Bitmap($size, $size)
      try {
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
          $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
          $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
          $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
          $graphics.DrawImage($source, 0, 0, $size, $size)
        } finally { $graphics.Dispose() }
        $pngStream = New-Object System.IO.MemoryStream
        try {
          $bitmap.Save($pngStream, [System.Drawing.Imaging.ImageFormat]::Png)
          $images.Add($pngStream.ToArray())
        } finally { $pngStream.Dispose() }
      } finally { $bitmap.Dispose() }
    }

    $file = [System.IO.File]::Create($IcoPath)
    try {
      $writer = New-Object System.IO.BinaryWriter($file)
      try {
        # ICONDIR header: reserved, type (1 = icon), image count.
        $writer.Write([UInt16]0)
        $writer.Write([UInt16]1)
        $writer.Write([UInt16]$sizes.Count)
        # ICONDIRENTRY per image, followed by the PNG payloads.
        $offset = 6 + (16 * $sizes.Count)
        for ($i = 0; $i -lt $sizes.Count; $i++) {
          $dimension = if ($sizes[$i] -ge 256) { 0 } else { $sizes[$i] }
          $writer.Write([Byte]$dimension)   # width (0 = 256)
          $writer.Write([Byte]$dimension)   # height (0 = 256)
          $writer.Write([Byte]0)            # palette color count
          $writer.Write([Byte]0)            # reserved
          $writer.Write([UInt16]1)          # color planes
          $writer.Write([UInt16]32)         # bits per pixel
          $writer.Write([UInt32]$images[$i].Length)
          $writer.Write([UInt32]$offset)
          $offset += $images[$i].Length
        }
        foreach ($bytes in $images) { $writer.Write($bytes) }
      } finally { $writer.Dispose() }
    } finally { $file.Dispose() }
  } finally { $source.Dispose() }
}

# Path to the shortcut icon: the shipped/ generated mj.ico, generated once from
# the app logo when missing. Returns $null when no icon can be produced.
function Get-AppIconPath {
  $icoPath = Join-Path $PSScriptRoot "mj.ico"
  if (Test-Path $icoPath) { return $icoPath }
  $pngPath = Get-AppLogoPng
  if (-not $pngPath) { return $null }
  try {
    New-IcoFromPng -PngPath $pngPath -IcoPath $icoPath
  } catch {
    return $null
  }
  if (Test-Path $icoPath) { return $icoPath }
  return $null
}

function Start-Stack {
  $root = Get-DeployRoot
  if (-not (Test-ComposeStack $root)) {
    Write-Host "Deployment folder $root is not complete." -ForegroundColor Red
    Write-Host "It must contain docker-compose.yml and .env"
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