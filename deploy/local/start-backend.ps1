# One-click Structure Gate backend: uvicorn :8787 + Cloudflare quick tunnel.
# Double-click start-backend.bat, or:
#   powershell -ExecutionPolicy Bypass -File deploy\local\start-backend.ps1
param(
  [int]$Port = 0,
  [string]$HostAddress = "",
  [switch]$NoTunnel,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }

# Load .env (simple KEY=VALUE)
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
  Get-Content $envFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $i = $line.IndexOf("=")
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
    if (-not [string]::IsNullOrWhiteSpace($k)) {
      Set-Item -Path "Env:$k" -Value $v
    }
  }
}

if ($Port -le 0) {
  $Port = if ($env:QRESEARCH_UI_PORT) { [int]$env:QRESEARCH_UI_PORT } else { 8787 }
}
if (-not $HostAddress) {
  $HostAddress = if ($env:QRESEARCH_UI_HOST) { $env:QRESEARCH_UI_HOST } else { "127.0.0.1" }
}

# CORS for Firebase UI (merge if user already set)
$firebaseOrigins = "https://ymk-autobuy.web.app,https://ymk-autobuy.firebaseapp.com"
if (-not $env:QRESEARCH_CORS_ORIGINS -or $env:QRESEARCH_CORS_ORIGINS -eq "*") {
  $env:QRESEARCH_CORS_ORIGINS = $firebaseOrigins
} elseif ($env:QRESEARCH_CORS_ORIGINS -notmatch "ymk-autobuy") {
  $env:QRESEARCH_CORS_ORIGINS = "$($env:QRESEARCH_CORS_ORIGINS),$firebaseOrigins"
}

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  throw "找不到 $venvPy — 先建立 venv 並安裝依賴。"
}

$env:PYTHONPATH = Join-Path $Root "src"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

Write-Step "Repo: $Root"
Write-Host "OpenD expect $($env:FUTU_OPEND_HOST):$($env:FUTU_OPEND_PORT)  env=$($env:FUTU_TRD_ENV)"
Write-Host "CORS  $($env:QRESEARCH_CORS_ORIGINS)"

# Free port if occupied
Write-Step "Check port $Port"
$owned = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($owned) {
  $pids = $owned.OwningProcess | Select-Object -Unique
  foreach ($procId in $pids) {
    try {
      $p = Get-Process -Id $procId -ErrorAction Stop
      Write-Warn "Port $Port in use by PID $procId ($($p.ProcessName)) — stopping it"
      Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    } catch { }
  }
  Start-Sleep -Seconds 1
}

$logs = Join-Path $Root "deploy\local\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$uiLog = Join-Path $logs "uvicorn.log"
$tunnelLog = Join-Path $logs "cloudflared.log"
$tunnelUrlFile = Join-Path $logs "tunnel-url.txt"

Write-Step "Start uvicorn http://${HostAddress}:${Port}"
$uiArgs = @(
  "-m", "uvicorn", "qresearch.web.paper_app:app",
  "--host", $HostAddress,
  "--port", "$Port"
)
$uiProc = Start-Process -FilePath $venvPy -ArgumentList $uiArgs `
  -WorkingDirectory $Root `
  -RedirectStandardOutput $uiLog `
  -RedirectStandardError $uiLog `
  -PassThru -WindowStyle Minimized

# Wait until port listens
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 250
  if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    $ready = $true
    break
  }
  if ($uiProc.HasExited) { break }
}
if (-not $ready) {
  Write-Host (Get-Content $uiLog -ErrorAction SilentlyContinue | Select-Object -Last 30)
  throw "uvicorn failed to bind :$Port — see $uiLog"
}
Write-Ok "UI PID $($uiProc.Id) → http://127.0.0.1:$Port"

$tunnelUrl = ""
if (-not $NoTunnel) {
  $cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
  if (-not $cloudflared) {
    $candidates = @(
      "$env:LOCALAPPDATA\Microsoft\WinGet\Links\cloudflared.exe",
      "$env:ProgramFiles\cloudflared\cloudflared.exe",
      "$env:USERPROFILE\cloudflared.exe",
      "C:\Tools\cloudflared.exe"
    )
    foreach ($c in $candidates) {
      if (Test-Path $c) { $cloudflared = @{ Source = $c }; break }
    }
  }

  if (-not $cloudflared) {
    Write-Warn "cloudflared not found — UI only on localhost. Install: winget install Cloudflare.cloudflared"
  } else {
    Write-Step "Start Cloudflare quick tunnel"
    if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }
    $cfBin = if ($cloudflared.Source) { $cloudflared.Source } else { $cloudflared.Path }
    $cfProc = Start-Process -FilePath $cfBin `
      -ArgumentList @("tunnel", "--url", "http://127.0.0.1:$Port") `
      -RedirectStandardOutput $tunnelLog `
      -RedirectStandardError $tunnelLog `
      -PassThru -WindowStyle Minimized

    for ($i = 0; $i -lt 60; $i++) {
      Start-Sleep -Milliseconds 500
      if (Test-Path $tunnelLog) {
        $text = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($text -match "https://[a-z0-9-]+\.trycloudflare\.com") {
          $tunnelUrl = $Matches[0]
          break
        }
      }
      if ($cfProc.HasExited) { break }
    }

    if ($tunnelUrl) {
      Set-Content -Path $tunnelUrlFile -Value $tunnelUrl -Encoding UTF8
      try { Set-Clipboard -Value $tunnelUrl } catch { }
      Write-Ok "Tunnel $tunnelUrl  (copied to clipboard)"
      Write-Ok "Saved $tunnelUrlFile"
    } else {
      Write-Warn "Tunnel URL not parsed yet — see $tunnelLog"
    }
  }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " Local UI : http://127.0.0.1:$Port"
Write-Host " Firebase : https://ymk-autobuy.web.app"
if ($tunnelUrl) {
  Write-Host " API base : $tunnelUrl"
  Write-Host ""
  Write-Host " On Firebase page: click footer API button,"
  Write-Host " paste the tunnel URL, then Sync Account."
} else {
  Write-Host " (no tunnel) open local UI only"
}
Write-Host "========================================" -ForegroundColor Green
Write-Host "Leave this window open. Ctrl+C stops helpers note only;"
Write-Host "To stop servers: close minimized cloudflared/uvicorn or run stop-backend.ps1"
Write-Host ""

if (-not $NoBrowser) {
  if ($tunnelUrl) {
    Start-Process "https://ymk-autobuy.web.app"
  } else {
    Start-Process "http://127.0.0.1:$Port"
  }
}

# Keep console alive and show live tips
Write-Host "Press Ctrl+C to exit this launcher (servers keep running in background)."
try {
  while ($true) { Start-Sleep -Seconds 3600 }
} catch {
  # ignore
}
