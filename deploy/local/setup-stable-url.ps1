# Setup stable public API URL (Cloudflare Named Tunnel) and bake it into Firebase once.
# After this, https://ymk-autobuy.web.app always calls your fixed hostname — no more pasting.
#
# Prerequisites:
# 1) Cloudflare Zero Trust -> Networks -> Tunnels -> Create tunnel
# 2) Public hostname -> http://127.0.0.1:8787
# 3) Copy tunnel token
#
# Usage:
#   .\deploy\local\setup-stable-url.ps1 -PublicUrl https://sg-api.yourdomain.com -TunnelToken eyJ...
#   .\deploy\local\setup-stable-url.ps1   # interactive prompts
param(
  [string]$PublicUrl = "",
  [string]$TunnelToken = "",
  [string]$FirebaseProjectId = "ymk-autobuy",
  [switch]$SkipFirebaseDeploy
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$envFile = Join-Path $Root ".env"

function Upsert-Env([string]$key, [string]$value) {
  $lines = @()
  if (Test-Path $envFile) {
    $lines = Get-Content $envFile -Encoding UTF8
  }
  $found = $false
  $out = foreach ($ln in $lines) {
    if ($ln -match ("^\s*" + [regex]::Escape($key) + "\s*=")) {
      $found = $true
      "{0}={1}" -f $key, $value
    } else {
      $ln
    }
  }
  if (-not $found) {
    $out = @($out) + ("{0}={1}" -f $key, $value)
  }
  $text = ($out -join "`n") + "`n"
  [System.IO.File]::WriteAllText($envFile, $text, [System.Text.UTF8Encoding]::new($false))
}

Write-Host "=== Stable API URL setup ==="
Write-Host "Quick tunnel URLs change every restart. Named Tunnel does not."
Write-Host ""
Write-Host "Create tunnel here (new UI):"
Write-Host "  https://dash.cloudflare.com/ -> Networking -> Tunnels -> Create a tunnel"
Write-Host "  (NOT one.dash.cloudflare.com Zero Trust -> Networks)"
Write-Host "Published application / route should point to:"
Write-Host "  http://127.0.0.1:8787"
Write-Host "You need a domain already on Cloudflare for the fixed hostname."
Write-Host "Token: tunnel Overview -> Add a replica / Install connector -> copy token"
Write-Host ""

if (-not $TunnelToken) {
  $TunnelToken = Read-Host "CLOUDFLARE_TUNNEL_TOKEN"
}
if (-not $PublicUrl) {
  $PublicUrl = Read-Host "Public URL (https://api.your-domain.com)"
}

$TunnelToken = $TunnelToken.Trim()
$PublicUrl = $PublicUrl.Trim().TrimEnd("/")
if (-not $TunnelToken) { throw "Tunnel token required" }
if ($PublicUrl -notmatch "^https://") { throw "PublicUrl must start with https://" }

Upsert-Env "CLOUDFLARE_TUNNEL_TOKEN" $TunnelToken
Upsert-Env "CLOUDFLARE_PUBLIC_URL" $PublicUrl
Write-Host ("Wrote .env CLOUDFLARE_PUBLIC_URL=" + $PublicUrl)

# Restart backend so named tunnel is used
Write-Host "Restarting local backend..."
& (Join-Path $PSScriptRoot "stop-backend.ps1")
Start-Sleep -Seconds 2
try {
  Start-ScheduledTask -TaskName "StructureGateBackend" -ErrorAction Stop
  Write-Host "Started scheduled task StructureGateBackend"
} catch {
  Write-Host "Task not found; starting start-backend.ps1 -NoBrowser"
  Start-Process powershell -ArgumentList @(
    "-NoProfile", "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $PSScriptRoot "start-backend.ps1"),
    "-NoBrowser"
  ) -WindowStyle Minimized
}

if (-not $SkipFirebaseDeploy) {
  Write-Host "Deploying Firebase with fixed ApiBase (one time)..."
  $fb = Join-Path $Root "deploy\firebase\deploy.ps1"
  powershell -NoProfile -ExecutionPolicy Bypass -File $fb -ProjectId $FirebaseProjectId -ApiBase $PublicUrl
}

Write-Host ""
Write-Host "DONE. Open (no paste needed):"
Write-Host ("  https://{0}.web.app/?api=clear" -f $FirebaseProjectId)
Write-Host "Then normal:"
Write-Host ("  https://{0}.web.app" -f $FirebaseProjectId)
Write-Host ("API is always: {0}" -f $PublicUrl)
