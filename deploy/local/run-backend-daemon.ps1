# Headless watchdog: keep uvicorn + cloudflared running (for Task Scheduler / autostart).
# Prefer named tunnel when CLOUDFLARE_TUNNEL_TOKEN is set in .env (stable hostname).
param(
  [int]$Port = 0,
  [int]$CheckSeconds = 20,
  [int]$StartupDelaySeconds = 15
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

$logs = Join-Path $Root "deploy\local\logs"
$binDir = Join-Path $Root "deploy\local\bin"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

$daemonLog = Join-Path $logs "daemon.log"
$uiOutLog = Join-Path $logs "uvicorn.out.log"
$uiErrLog = Join-Path $logs "uvicorn.err.log"
$tunnelOutLog = Join-Path $logs "cloudflared.out.log"
$tunnelErrLog = Join-Path $logs "cloudflared.err.log"
$tunnelUrlFile = Join-Path $logs "tunnel-url.txt"
$pidFile = Join-Path $logs "daemon.pid"

function Write-Log([string]$msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  Add-Content -Path $daemonLog -Value $line -Encoding UTF8
}

function Import-DotEnv {
  $envFile = Join-Path $Root ".env"
  if (-not (Test-Path $envFile)) { return }
  Get-Content $envFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) { return }
    $i = $line.IndexOf("=")
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
    if ($k) { Set-Item -Path ("Env:" + $k) -Value $v }
  }
}

function Get-CloudflaredPath {
  $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $candidates = @(
    (Join-Path $binDir "cloudflared.exe"),
    (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\cloudflared.exe"),
    (Join-Path $env:ProgramFiles "cloudflared\cloudflared.exe"),
    (Join-Path $env:USERPROFILE "cloudflared.exe")
  )
  foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) { return $c }
  }
  $dest = Join-Path $binDir "cloudflared.exe"
  $url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
  try {
    Write-Log ("Downloading cloudflared -> " + $dest)
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    return $dest
  } catch {
    Write-Log ("cloudflared download failed: " + $_.Exception.Message)
    return $null
  }
}

function Test-PortListen([int]$p) {
  return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Start-Uvicorn([int]$p, [string]$hostAddr, [string]$py) {
  Write-Log ("Starting uvicorn on " + $hostAddr + ":" + $p)
  $args = @(
    "-m", "uvicorn", "qresearch.web.paper_app:app",
    "--host", $hostAddr,
    "--port", ("{0}" -f $p)
  )
  Start-Process -FilePath $py -ArgumentList $args `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $uiOutLog `
    -RedirectStandardError $uiErrLog `
    -WindowStyle Hidden | Out-Null
}

function Start-Tunnel([string]$cf, [int]$p) {
  $token = $env:CLOUDFLARE_TUNNEL_TOKEN
  if ($token) {
    Write-Log "Starting named Cloudflare tunnel (token)"
    if ($env:CLOUDFLARE_PUBLIC_URL) {
      Set-Content -Path $tunnelUrlFile -Value $env:CLOUDFLARE_PUBLIC_URL.TrimEnd("/") -Encoding ASCII
    }
    Start-Process -FilePath $cf `
      -ArgumentList @("tunnel", "--no-autoupdate", "run", "--token", $token) `
      -RedirectStandardOutput $tunnelOutLog `
      -RedirectStandardError $tunnelErrLog `
      -WindowStyle Hidden | Out-Null
    return
  }

  Write-Log ("Starting quick tunnel -> http://127.0.0.1:" + $p)
  Start-Process -FilePath $cf `
    -ArgumentList @("tunnel", "--url", ("http://127.0.0.1:{0}" -f $p)) `
    -RedirectStandardOutput $tunnelOutLog `
    -RedirectStandardError $tunnelErrLog `
    -WindowStyle Hidden | Out-Null

  for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    foreach ($f in @($tunnelErrLog, $tunnelOutLog)) {
      if (-not (Test-Path $f)) { continue }
      $text = Get-Content $f -Raw -ErrorAction SilentlyContinue
      if ($text -and ($text -match "https://[a-z0-9-]+\.trycloudflare\.com")) {
        Set-Content -Path $tunnelUrlFile -Value $Matches[0] -Encoding ASCII
        Write-Log ("Quick tunnel URL " + $Matches[0])
        return
      }
    }
  }
  Write-Log "Quick tunnel URL not parsed yet"
}

function Test-CloudflaredRunning {
  return [bool](Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue)
}

# --- main ---
Import-DotEnv
if ($Port -le 0) {
  if ($env:QRESEARCH_UI_PORT) { $Port = [int]$env:QRESEARCH_UI_PORT } else { $Port = 8787 }
}
$hostAddr = if ($env:QRESEARCH_UI_HOST) { $env:QRESEARCH_UI_HOST } else { "127.0.0.1" }

$firebaseOrigins = "https://ymk-autobuy.web.app,https://ymk-autobuy.firebaseapp.com"
if (-not $env:QRESEARCH_CORS_ORIGINS -or $env:QRESEARCH_CORS_ORIGINS -eq "*") {
  $env:QRESEARCH_CORS_ORIGINS = $firebaseOrigins
} elseif ($env:QRESEARCH_CORS_ORIGINS -notmatch "ymk-autobuy") {
  $env:QRESEARCH_CORS_ORIGINS = ($env:QRESEARCH_CORS_ORIGINS + "," + $firebaseOrigins)
}

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  Write-Log ("FATAL missing " + $venvPy)
  exit 2
}
$env:PYTHONPATH = (Join-Path $Root "src")
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

Set-Content -Path $pidFile -Value $PID -Encoding ASCII
Write-Log ("Daemon start PID=" + $PID + " port=" + $Port + " delay=" + $StartupDelaySeconds + "s")
Start-Sleep -Seconds $StartupDelaySeconds

$cfPath = Get-CloudflaredPath

while ($true) {
  try {
    Import-DotEnv
    if (-not (Test-PortListen $Port)) {
      Start-Uvicorn -p $Port -hostAddr $hostAddr -py $venvPy
      Start-Sleep -Seconds 2
    }

    if ($cfPath) {
      if (-not (Test-CloudflaredRunning)) {
        Start-Tunnel -cf $cfPath -p $Port
        Start-Sleep -Seconds 2
      }
    } else {
      Write-Log "cloudflared missing; UI only on localhost"
    }
  } catch {
    Write-Log ("loop error: " + $_.Exception.Message)
  }
  Start-Sleep -Seconds $CheckSeconds
}
