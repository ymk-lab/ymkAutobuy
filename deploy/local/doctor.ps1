# One-shot health check for local VPS backend.
$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
$logs = Join-Path $Root "deploy\local\logs"

Write-Host "=== PORTS ==="
$ports = netstat -ano | Select-String -Pattern ":8787|:11111"
if ($ports) { $ports | ForEach-Object { $_.Line } } else { Write-Host "(no listeners on 8787/11111)" }

Write-Host ""
Write-Host "=== TASK ==="
$task = Get-ScheduledTask -TaskName "StructureGateBackend" -ErrorAction SilentlyContinue
if ($task) {
  $task | Get-ScheduledTaskInfo | Format-List TaskName,LastRunTime,LastTaskResult,NextRunTime
} else {
  Write-Host "StructureGateBackend task not found"
}

Write-Host "=== DAEMON LOG (tail 40) ==="
$daemon = Join-Path $logs "daemon.log"
if (Test-Path $daemon) { Get-Content $daemon -Tail 40 } else { Write-Host "missing daemon.log" }

Write-Host ""
Write-Host "=== UVICORN ERR (tail 30) ==="
$uerr = Join-Path $logs "uvicorn.err.log"
if (Test-Path $uerr) { Get-Content $uerr -Tail 30 } else { Write-Host "missing uvicorn.err.log" }

Write-Host ""
Write-Host "=== TUNNEL URL ==="
$tu = Join-Path $logs "tunnel-url.txt"
if (Test-Path $tu) { Get-Content $tu } else { Write-Host "missing tunnel-url.txt" }

Write-Host ""
Write-Host "=== PROCESSES ==="
Get-Process -Name powershell,python,cloudflared,FutuOpenD,OpenD -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,StartTime |
  Format-Table -AutoSize
if (-not (Get-Process -Name python,cloudflared,FutuOpenD,OpenD -ErrorAction SilentlyContinue)) {
  Write-Host "(no python/cloudflared/OpenD processes)"
}

Write-Host ""
Write-Host "=== QUICK FIX ==="
Write-Host "1) Start OpenD and login SIMULATE"
Write-Host "2) .\deploy\local\stop-backend.ps1"
Write-Host "3) Start-ScheduledTask -TaskName StructureGateBackend"
Write-Host "   or:  .\deploy\local\start-backend.bat"
