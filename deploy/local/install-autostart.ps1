# Register Windows Task Scheduler job: start Structure Gate backend at user logon.
# Run once:
#   powershell -ExecutionPolicy Bypass -File deploy\local\install-autostart.ps1
param(
  [string]$TaskName = "StructureGateBackend",
  [switch]$StartNow
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$daemon = Join-Path $Root "deploy\local\run-backend-daemon.ps1"
if (-not (Test-Path $daemon)) { throw ("Missing " + $daemon) }

$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$daemon`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -RestartCount 5 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -MultipleInstances IgnoreNew

# Hidden / background
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -Principal $principal `
  -Description "Local VPS: OpenD + uvicorn + cloudflared at logon" | Out-Null

Write-Host ("Registered scheduled task: " + $TaskName)
Write-Host "Starts at Windows logon for user: $($env:USERNAME)"
Write-Host "Boot order: OpenD -> API :8787 -> cloudflared"
Write-Host ""
Write-Host "Set OpenD path in .env if needed:"
Write-Host "  FUTU_OPEND_EXE=C:\path\to\FutuOpenD.exe"
Write-Host "Optional stable public URL:"
Write-Host "  CLOUDFLARE_TUNNEL_TOKEN=..."
Write-Host "  CLOUDFLARE_PUBLIC_URL=https://your-fixed-hostname"
Write-Host ""
Write-Host "Logs: deploy\local\logs\daemon.log"
Write-Host "One-key install: deploy\local\install-local-vps.bat"
Write-Host "Remove autostart: deploy\local\uninstall-autostart.ps1"

if ($StartNow) {
  Write-Host "Starting task now..."
  Start-ScheduledTask -TaskName $TaskName
  Start-Sleep -Seconds 3
  Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Format-List
}
