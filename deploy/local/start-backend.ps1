# One-click Structure Gate backend: uvicorn :8787 + Cloudflare quick tunnel.
# Usage:
#   powershell -ExecutionPolicy Bypass -File deploy\local\start-backend.ps1
#   or double-click start-backend.bat
param(
  [int]$Port = 0,
  [string]$HostAddress = "",
  [switch]$NoTunnel,
  [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

function Write-Step([string]$msg) {
  Write-Host ""
  Write-Host ("==> " + $msg) -ForegroundColor Cyan
}
function Write-Ok([string]$msg) {
  Write-Host ("OK  " + $msg) -ForegroundColor Green
}
function Write-Warn([string]$msg) {
  Write-Host ("!!  " + $msg) -ForegroundColor Yellow
}

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
      Set-Item -Path ("Env:" + $k) -Value $v
    }
  }
}

if ($Port -le 0) {
  if ($env:QRESEARCH_UI_PORT) { $Port = [int]$env:QRESEARCH_UI_PORT } else { $Port = 8787 }
}
if (-not $HostAddress) {
  if ($env:QRESEARCH_UI_HOST) { $HostAddress = $env:QRESEARCH_UI_HOST } else { $HostAddress = "127.0.0.1" }
}

$firebaseOrigins = "https://ymk-autobuy.web.app,https://ymk-autobuy.firebaseapp.com"
if (-not $env:QRESEARCH_CORS_ORIGINS -or $env:QRESEARCH_CORS_ORIGINS -eq "*") {
  $env:QRESEARCH_CORS_ORIGINS = $firebaseOrigins
} elseif ($env:QRESEARCH_CORS_ORIGINS -notmatch "ymk-autobuy") {
  $env:QRESEARCH_CORS_ORIGINS = ($env:QRESEARCH_CORS_ORIGINS + "," + $firebaseOrigins)
}

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  throw ("Missing venv python: " + $venvPy)
}

$env:PYTHONPATH = (Join-Path $Root "src")
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

Write-Step ("Repo: " + $Root)
Write-Host ("OpenD " + $env:FUTU_OPEND_HOST + ":" + $env:FUTU_OPEND_PORT + " env=" + $env:FUTU_TRD_ENV)
Write-Host ("CORS  " + $env:QRESEARCH_CORS_ORIGINS)

Write-Step ("Check port " + $Port)
$owned = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($owned) {
  $pids = $owned.OwningProcess | Select-Object -Unique
  foreach ($procId in $pids) {
    try {
      $p = Get-Process -Id $procId -ErrorAction Stop
      Write-Warn ("Port in use by PID " + $procId + " (" + $p.ProcessName + ") - stopping")
      Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    } catch { }
  }
  Start-Sleep -Seconds 1
}

$logs = Join-Path $Root "deploy\local\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$uiOutLog = Join-Path $logs "uvicorn.out.log"
$uiErrLog = Join-Path $logs "uvicorn.err.log"
$tunnelOutLog = Join-Path $logs "cloudflared.out.log"
$tunnelErrLog = Join-Path $logs "cloudflared.err.log"
$tunnelUrlFile = Join-Path $logs "tunnel-url.txt"

Write-Step ("Start uvicorn http://" + $HostAddress + ":" + $Port)
$uiArgs = @(
  "-m", "uvicorn", "qresearch.web.paper_app:app",
  "--host", $HostAddress,
  "--port", ("{0}" -f $Port)
)
$uiProc = Start-Process -FilePath $venvPy -ArgumentList $uiArgs `
  -WorkingDirectory $Root `
  -RedirectStandardOutput $uiOutLog `
  -RedirectStandardError $uiErrLog `
  -PassThru -WindowStyle Minimized

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
  foreach ($f in @($uiErrLog, $uiOutLog)) {
    if (Test-Path $f) {
      Get-Content $f -ErrorAction SilentlyContinue | Select-Object -Last 30 | ForEach-Object { Write-Host $_ }
    }
  }
  throw ("uvicorn failed to bind :" + $Port + " - see " + $uiErrLog)
}
Write-Ok ("UI PID " + $uiProc.Id + " -> http://127.0.0.1:" + $Port)

$tunnelUrl = ""
if (-not $NoTunnel) {
  $cfPath = $null
  $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
  if ($cmd) { $cfPath = $cmd.Source }
  if (-not $cfPath) {
    $candidates = @(
      (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\cloudflared.exe"),
      (Join-Path $env:ProgramFiles "cloudflared\cloudflared.exe"),
      (Join-Path $env:USERPROFILE "cloudflared.exe"),
      "C:\Tools\cloudflared.exe"
    )
    foreach ($c in $candidates) {
      if ($c -and (Test-Path $c)) { $cfPath = $c; break }
    }
  }

  if (-not $cfPath) {
    Write-Warn "cloudflared not found. Install: winget install Cloudflare.cloudflared"
  } else {
    Write-Step "Start Cloudflare quick tunnel"
    if (Test-Path $tunnelLog) { Remove-Item $tunnelLog -Force }
    $cfProc = Start-Process -FilePath $cfPath `
      -ArgumentList @("tunnel", "--url", ("http://127.0.0.1:{0}" -f $Port)) `
      -RedirectStandardOutput $tunnelLog `
      -RedirectStandardError $tunnelLog `
      -PassThru -WindowStyle Minimized

    for ($i = 0; $i -lt 60; $i++) {
      Start-Sleep -Milliseconds 500
      if (Test-Path $tunnelLog) {
        $text = Get-Content $tunnelLog -Raw -ErrorAction SilentlyContinue
        if ($text -and ($text -match "https://[a-z0-9-]+\.trycloudflare\.com")) {
          $tunnelUrl = $Matches[0]
          break
        }
      }
      if ($cfProc.HasExited) { break }
    }

    if ($tunnelUrl) {
      Set-Content -Path $tunnelUrlFile -Value $tunnelUrl -Encoding ASCII
      try { Set-Clipboard -Value $tunnelUrl } catch { }
      Write-Ok ("Tunnel " + $tunnelUrl + " (copied to clipboard)")
      Write-Ok ("Saved " + $tunnelUrlFile)
    } else {
      Write-Warn ("Tunnel URL not parsed yet - see " + $tunnelLog)
    }
  }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host (" Local UI : http://127.0.0.1:" + $Port)
Write-Host " Firebase : https://ymk-autobuy.web.app"
if ($tunnelUrl) {
  Write-Host (" API base : " + $tunnelUrl)
  Write-Host ""
  Write-Host " On Firebase page: click footer API button,"
  Write-Host " paste the tunnel URL, then Sync Account."
} else {
  Write-Host " (no tunnel) open local UI only"
}
Write-Host "========================================" -ForegroundColor Green
Write-Host "To stop: deploy\local\stop-backend.ps1"
Write-Host ""

if (-not $NoBrowser) {
  if ($tunnelUrl) {
    Start-Process "https://ymk-autobuy.web.app"
  } else {
    Start-Process ("http://127.0.0.1:" + $Port)
  }
}

Write-Host "Press Ctrl+C to exit this launcher (servers keep running)."
try {
  while ($true) { Start-Sleep -Seconds 3600 }
} catch { }
