# Local-VPS watchdog: OpenD + uvicorn + cloudflared (Task Scheduler / autostart).
# Order: start OpenD -> wait API port -> uvicorn -> tunnel.
# Prefer named tunnel when CLOUDFLARE_TUNNEL_TOKEN is set (.env).
param(
  [int]$Port = 0,
  [int]$CheckSeconds = 20,
  [int]$StartupDelaySeconds = 20,
  [int]$OpenDWaitSeconds = 90
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
$opendPathFile = Join-Path $logs "opend-path.txt"
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

function Test-PortListen([int]$p) {
  return [bool](Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
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

function Find-OpenDExe {
  if ($env:FUTU_OPEND_EXE -and (Test-Path $env:FUTU_OPEND_EXE)) {
    return $env:FUTU_OPEND_EXE
  }
  $names = @("FutuOpenD.exe", "OpenD.exe")
  $roots = @(
    (Join-Path $env:APPDATA "com.futunn.FutuOpenD"),
    (Join-Path $env:APPDATA "Futu"),
    (Join-Path $env:LOCALAPPDATA "Programs"),
    (Join-Path $env:LOCALAPPDATA "Futu"),
    ${env:ProgramFiles},
    ${env:ProgramFiles(x86)},
    (Join-Path $env:USERPROFILE "Futu"),
    (Join-Path $env:USERPROFILE "OpenD"),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "Downloads")
  ) | Where-Object { $_ -and (Test-Path $_) }

  foreach ($r in $roots) {
    foreach ($n in $names) {
      $direct = Join-Path $r $n
      if (Test-Path $direct) { return $direct }
    }
  }

  # Limited recursive search (depth-ish via Get-ChildItem -Depth)
  foreach ($r in $roots) {
    try {
      $hit = Get-ChildItem -Path $r -Filter "FutuOpenD.exe" -Recurse -ErrorAction SilentlyContinue -Depth 5 |
        Select-Object -First 1
      if ($hit) { return $hit.FullName }
      $hit = Get-ChildItem -Path $r -Filter "OpenD.exe" -Recurse -ErrorAction SilentlyContinue -Depth 5 |
        Select-Object -First 1
      if ($hit) { return $hit.FullName }
    } catch { }
  }
  return $null
}

function Test-OpenDProcess {
  $procs = Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -match "^(FutuOpenD|OpenD|FutuOpenD.*)$"
  }
  return [bool]$procs
}

function Start-OpenD([string]$exe, [int]$opendPort) {
  if (Test-PortListen $opendPort) {
    Write-Log ("OpenD port already listening :" + $opendPort)
    return $true
  }
  if (-not $exe) {
    Write-Log "OpenD exe not found. Set FUTU_OPEND_EXE in .env to full path of FutuOpenD.exe / OpenD.exe"
    return $false
  }
  if (-not (Test-Path $exe)) {
    Write-Log ("OpenD exe missing: " + $exe)
    return $false
  }

  Set-Content -Path $opendPathFile -Value $exe -Encoding UTF8
  $workDir = Split-Path -Parent $exe
  $argList = @()
  if ($env:FUTU_OPEND_LOGIN_ACCOUNT) {
    $argList += ("-login_account={0}" -f $env:FUTU_OPEND_LOGIN_ACCOUNT)
  }
  if ($env:FUTU_OPEND_LOGIN_PWD) {
    $argList += ("-login_pwd={0}" -f $env:FUTU_OPEND_LOGIN_PWD)
  }
  if ($env:FUTU_OPEND_LANG) {
    $argList += ("-lang={0}" -f $env:FUTU_OPEND_LANG)
  }

  Write-Log ("Starting OpenD: " + $exe)
  if ($argList.Count -gt 0) {
    Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $workDir -WindowStyle Minimized | Out-Null
  } else {
    # Use XML next to exe (recommended). GUI OpenD may need interactive login once.
    Start-Process -FilePath $exe -WorkingDirectory $workDir -WindowStyle Minimized | Out-Null
  }

  $deadline = (Get-Date).AddSeconds($OpenDWaitSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-PortListen $opendPort) {
      Write-Log ("OpenD ready on :" + $opendPort)
      return $true
    }
    Start-Sleep -Seconds 2
  }
  Write-Log ("OpenD started but port :" + $opendPort + " not listening within " + $OpenDWaitSeconds + "s (login/XML?)")
  return $false
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
$hostAddr = if ($env:QRESEARCH_UI_HOST) { $env:QRESEARCH_UI_HOST } else { "0.0.0.0" }
$opendPort = if ($env:FUTU_OPEND_PORT) { [int]$env:FUTU_OPEND_PORT } else { 11111 }
$skipOpenD = ($env:QRESEARCH_SKIP_OPEND -eq "1")

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

# Single-instance guard
if (Test-Path $pidFile) {
  $oldPid = 0
  try { $oldPid = [int]((Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)) } catch { }
  if ($oldPid -gt 0 -and $oldPid -ne $PID) {
    $old = Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if ($old -and $old.ProcessName -match "powershell|pwsh") {
      Write-Log ("Another daemon PID=" + $oldPid + " already running; exiting")
      exit 0
    }
  }
}
Set-Content -Path $pidFile -Value $PID -Encoding ASCII
Write-Log ("Daemon start PID=" + $PID + " ui=:" + $Port + " opend=:" + $opendPort + " delay=" + $StartupDelaySeconds + "s")
Start-Sleep -Seconds $StartupDelaySeconds

$opendExe = $null
if (-not $skipOpenD) {
  $opendExe = Find-OpenDExe
  if ($opendExe) {
    Write-Log ("OpenD exe: " + $opendExe)
    Set-Content -Path $opendPathFile -Value $opendExe -Encoding UTF8
  } else {
    Write-Log "OpenD exe not auto-detected - set FUTU_OPEND_EXE in .env"
  }
}

Write-Log "Resolving cloudflared..."
$cfPath = Get-CloudflaredPath
if ($cfPath) { Write-Log ("cloudflared: " + $cfPath) } else { Write-Log "cloudflared missing" }

# Write OpenD path into .env hint file for user
if ($opendExe) {
  $envHint = Join-Path $logs "opend-env-snippet.txt"
  Set-Content -Path $envHint -Value ("FUTU_OPEND_EXE=" + $opendExe) -Encoding ASCII
}

while ($true) {
  try {
    Import-DotEnv
    if ($env:FUTU_OPEND_PORT) { $opendPort = [int]$env:FUTU_OPEND_PORT }
    $skipOpenD = ($env:QRESEARCH_SKIP_OPEND -eq "1")

    if (-not $skipOpenD) {
      if (-not $opendExe) { $opendExe = Find-OpenDExe }
      if (-not (Test-PortListen $opendPort)) {
        Write-Log ("OpenD port :" + $opendPort + " down; starting...")
        [void](Start-OpenD -exe $opendExe -opendPort $opendPort)
      }
    }

    $opendUp = $skipOpenD -or (Test-PortListen $opendPort)
    $apiUp = Test-PortListen $Port

    if (-not $apiUp) {
      if ($opendUp -or (-not $opendExe)) {
        Start-Uvicorn -p $Port -hostAddr $hostAddr -py $venvPy
        Start-Sleep -Seconds 3
        $apiUp = Test-PortListen $Port
        Write-Log ("uvicorn listening=" + $apiUp)
      } else {
        Write-Log "Waiting for OpenD before starting uvicorn"
      }
    }

    if ($cfPath) {
      if (-not (Test-CloudflaredRunning)) {
        if ($apiUp) {
          Write-Log "cloudflared not running; starting tunnel..."
          Start-Tunnel -cf $cfPath -p $Port
          Start-Sleep -Seconds 2
        } else {
          Write-Log "Skip tunnel until API listens"
        }
      }
    }

    # Heartbeat status line every loop
    $tu = ""
    if (Test-Path $tunnelUrlFile) { $tu = (Get-Content $tunnelUrlFile -ErrorAction SilentlyContinue | Select-Object -First 1) }
    Write-Log ("status opend=" + (Test-PortListen $opendPort) + " api=" + (Test-PortListen $Port) + " tunnelProc=" + (Test-CloudflaredRunning) + " url=" + $tu)
  } catch {
    Write-Log ("loop error: " + $_.Exception.Message)
  }
  Start-Sleep -Seconds $CheckSeconds
}
