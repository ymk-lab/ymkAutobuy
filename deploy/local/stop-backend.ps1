# Stop Structure Gate uvicorn (:8787) and cloudflared.
# Use -StopOpenD to also kill Futu OpenD / FutuOpenD.
param(
  [int]$Port = 8787,
  [switch]$StopOpenD
)

$ErrorActionPreference = "SilentlyContinue"
Write-Host "Stopping listeners on :$Port and cloudflared..."

# Stop daemon powershell watchdog if recorded
$pidFile = Join-Path $PSScriptRoot "logs\daemon.pid"
if (Test-Path $pidFile) {
  $daemonPid = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($daemonPid) { Stop-Process -Id ([int]$daemonPid) -Force -ErrorAction SilentlyContinue }
}

Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

Get-Process -Name "cloudflared" -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

Get-Process -Name "python","uvicorn" -ErrorAction SilentlyContinue |
  Where-Object {
    try {
      (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine -match "qresearch.web.paper_app|uvicorn"
    } catch { $false }
  } |
  ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

if ($StopOpenD) {
  Write-Host "Stopping OpenD..."
  Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -match "^(FutuOpenD|OpenD)$" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
}

Write-Host "Done."
