# Deploy Structure Gate UI to Firebase Hosting.
# Usage:
#   .\deploy.ps1 -ProjectId my-firebase-id -ApiBase https://xxx.trycloudflare.com
param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [Parameter(Mandatory = $true)][string]$ApiBase,
  [string]$CorsOrigins = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm not found. Install Node.js LTS first."
}
if (-not (Get-Command firebase -ErrorAction SilentlyContinue)) {
  Write-Host "Installing firebase-tools locally via npm..."
}

npm install

$rc = @{ projects = @{ default = $ProjectId } } | ConvertTo-Json -Depth 5
Set-Content -Path ".firebaserc" -Value $rc -Encoding UTF8

$env:QRESEARCH_API_BASE = $ApiBase.TrimEnd("/")
if ($CorsOrigins -eq "") {
  $CorsOrigins = "https://$ProjectId.web.app,https://$ProjectId.firebaseapp.com"
}
Write-Host "API_BASE=$env:QRESEARCH_API_BASE"
Write-Host "Remember to set on the API host: QRESEARCH_CORS_ORIGINS=$CorsOrigins"

npx firebase login --no-localhost
npm run deploy

Write-Host ""
Write-Host "Live:"
Write-Host "  https://$ProjectId.web.app"
Write-Host "  https://$ProjectId.firebaseapp.com"
