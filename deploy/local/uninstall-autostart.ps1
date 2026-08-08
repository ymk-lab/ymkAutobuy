param([string]$TaskName = "StructureGateBackend")
$ErrorActionPreference = "Continue"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
& (Join-Path $PSScriptRoot "stop-backend.ps1")
Write-Host ("Removed task " + $TaskName + " and stopped backend processes.")
