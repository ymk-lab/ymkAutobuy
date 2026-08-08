# Stop Structure Gate uvicorn (:8787) and cloudflared quick tunnels.
param([int]$Port = 8787)

$ErrorActionPreference = "SilentlyContinue"
Write-Host "Stopping listeners on :$Port and cloudflared..."

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

Write-Host "Done."
