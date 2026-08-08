# Ensure cloudflared exists in deploy/local/bin (no admin / winget required).
# Skips download if binary already works or is locked by a running process.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$binDir = Join-Path $Root "deploy\local\bin"
New-Item -ItemType Directory -Force -Path $binDir | Out-Null
$out = Join-Path $binDir "cloudflared.exe"
$url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"

function Test-CloudflaredOk([string]$path) {
  if (-not (Test-Path $path)) { return $false }
  try {
    $p = Start-Process -FilePath $path -ArgumentList @("--version") -Wait -PassThru -WindowStyle Hidden `
      -RedirectStandardOutput (Join-Path $env:TEMP "cf-ver-out.txt") `
      -RedirectStandardError (Join-Path $env:TEMP "cf-ver-err.txt")
    return ($p.ExitCode -eq 0)
  } catch {
    return $false
  }
}

# Already on PATH?
$cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
if ($cmd -and (Test-CloudflaredOk $cmd.Source)) {
  Write-Host ("OK cloudflared on PATH: " + $cmd.Source)
  exit 0
}

if (Test-CloudflaredOk $out) {
  Write-Host ("OK already installed: " + $out)
  & $out --version
  exit 0
}

# File exists but locked / broken — try stop then replace
$running = Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue
if ($running -and (Test-Path $out)) {
  Write-Host "cloudflared is running; keeping existing binary (skip download)."
  Write-Host ("OK " + $out)
  exit 0
}

Write-Host "Downloading $url"
Write-Host (" -> " + $out)
$tmp = Join-Path $binDir ("cloudflared.download." + [guid]::NewGuid().ToString("n") + ".exe")
try {
  Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
  if (Test-Path $out) {
    try { Remove-Item $out -Force } catch { }
  }
  Move-Item -Path $tmp -Destination $out -Force
  & $out --version
  Write-Host "OK. Re-run deploy\local\start-backend.bat or install-local-vps.bat"
  exit 0
} catch {
  if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue }
  if (Test-Path $out) {
    Write-Host ("Download/replace failed but existing file present: " + $out)
    Write-Host $_.Exception.Message
    exit 0
  }
  Write-Host ("FAILED: " + $_.Exception.Message)
  exit 1
}
