# Install cloudflared into deploy/local/bin (no admin / winget required).
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$binDir = Join-Path $Root "deploy\local\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$out = Join-Path $binDir "cloudflared.exe"
$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
Write-Host "Downloading $url"
Write-Host " -> $out"
Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
& $out --version
Write-Host "OK. Re-run deploy\local\start-backend.bat"
