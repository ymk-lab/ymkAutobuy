# Deploy Structure Gate UI to Firebase Hosting.
# Examples:
#   .\deploy.ps1 -ProjectId ymk-autobuy
#   .\deploy.ps1 -ProjectId ymk-autobuy -UiSetsApi
#   .\deploy.ps1 -ProjectId ymk-autobuy -ApiBase https://abc-def-123.trycloudflare.com
param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [string]$ApiBase = "",
  [string]$CorsOrigins = "",
  [switch]$CreateProject,
  [switch]$UiSetsApi
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Assert-Ok([string]$step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$step failed (exit $LASTEXITCODE)"
  }
}

function Test-ValidApiBase([string]$url) {
  if ([string]::IsNullOrWhiteSpace($url)) { return $false }
  if ($url -notmatch '^https://') { return $false }
  if ($url -match '127\.0\.0\.1|localhost') { return $false }
  if ($url -match 'YOUR_|PLACEHOLDER|TUNNEL_HOST|example\.com|xxxx\.|random-words') { return $false }
  if ($url -match '^https://\.trycloudflare\.com/?$') { return $false }
  # Real quick-tunnel hosts look like: https://foo-bar-baz.trycloudflare.com
  if ($url -match '^https://[a-zA-Z0-9][a-zA-Z0-9-]*\.trycloudflare\.com/?$') { return $true }
  # Allow other https origins (named tunnel / custom domain)
  if ($url -match '^https://[a-zA-Z0-9][a-zA-Z0-9.-]+[a-zA-Z0-9](:\d+)?/?$') { return $true }
  return $false
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm not found. Install Node.js LTS first."
}

$ApiBase = $ApiBase.Trim().TrimEnd("/")
$ProjectId = $ProjectId.Trim()

if ($ProjectId -match "YOUR_|PLACEHOLDER|example" -or $ProjectId.Length -lt 3) {
  throw "Invalid ProjectId. Example: .\deploy.ps1 -ProjectId ymk-autobuy"
}

# Default: ship UI only; set API URL later in the webpage footer.
if ($UiSetsApi -or [string]::IsNullOrWhiteSpace($ApiBase) -or $ApiBase -eq "none") {
  $ApiBase = ""
  Write-Host "API_BASE empty -> set tunnel URL in Firebase page footer after deploy."
} elseif (-not (Test-ValidApiBase $ApiBase)) {
  Write-Host "Invalid ApiBase: $ApiBase"
  Write-Host "Use a real tunnel URL, for example:"
  Write-Host "  https://abc-def-123.trycloudflare.com"
  Write-Host "Or deploy UI only:"
  Write-Host "  .\deploy.ps1 -ProjectId $ProjectId -UiSetsApi"
  throw "Invalid ApiBase"
}

npm install
Assert-Ok "npm install"

if ($CreateProject) {
  Write-Host "Creating Firebase project $ProjectId ..."
  npx firebase projects:create $ProjectId --display-name "ymk Autobuy"
  Assert-Ok "firebase projects:create"
}

$rcObj = @{ projects = @{ default = $ProjectId } }
$rcJson = $rcObj | ConvertTo-Json -Depth 5
# UTF-8 no BOM for .firebaserc
[System.IO.File]::WriteAllText((Join-Path $PWD ".firebaserc"), $rcJson + "`n")

$env:QRESEARCH_API_BASE = $ApiBase
if ($CorsOrigins -eq "") {
  $CorsOrigins = "https://$ProjectId.web.app,https://$ProjectId.firebaseapp.com"
}
Write-Host "API_BASE=$($env:QRESEARCH_API_BASE)"
Write-Host "Set on API host: QRESEARCH_CORS_ORIGINS=$CorsOrigins"

Write-Host "Checking project access..."
npx firebase projects:list
Assert-Ok "firebase projects:list"

npx firebase use $ProjectId
if ($LASTEXITCODE -ne 0) {
  throw "Cannot select project '$ProjectId'. Login with the Google account that owns it, then retry."
}

npm run deploy
Assert-Ok "firebase deploy"

Write-Host ""
Write-Host "Live:"
Write-Host "  https://$ProjectId.web.app"
Write-Host "  https://$ProjectId.firebaseapp.com"
if (-not $ApiBase) {
  Write-Host ""
  Write-Host "Next:"
  Write-Host "  1) Run deploy\local\start-backend.bat"
  Write-Host "  2) Open https://$ProjectId.web.app"
  Write-Host "  3) Click footer API button and paste the tunnel URL"
}
