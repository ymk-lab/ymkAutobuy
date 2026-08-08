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

$ApiBase = $ApiBase.Trim().TrimEnd("/")
$ProjectId = $ProjectId.Trim()

if ($ProjectId -match "YOUR_|PLACEHOLDER|example" -or $ProjectId.Length -lt 3) {
  throw @"
ProjectId 還是佔位字。請先到 https://console.firebase.google.com/ 建立專案，再執行例如：

  .\deploy.ps1 -ProjectId ymk-autobuy -ApiBase https://xxxx.trycloudflare.com
"@
}
if ($ApiBase -notmatch "^https?://" -or $ApiBase -match "YOUR_|PLACEHOLDER|example\.com|TUNNEL_HOST") {
  throw @"
ApiBase 必須是真實後端／隧道網址（含 https://）。

1) 先開 uvicorn :8787
2) 另開視窗跑 quick tunnel，複製印出的 https://xxxx.trycloudflare.com
3) 再執行：

  .\deploy.ps1 -ProjectId <firebase專案ID> -ApiBase https://xxxx.trycloudflare.com
"@
}

npm install

$rc = @{ projects = @{ default = $ProjectId } } | ConvertTo-Json -Depth 5
Set-Content -Path ".firebaserc" -Value $rc -Encoding UTF8

$env:QRESEARCH_API_BASE = $ApiBase
if ($CorsOrigins -eq "") {
  $CorsOrigins = "https://$ProjectId.web.app,https://$ProjectId.firebaseapp.com"
}
Write-Host "API_BASE=$env:QRESEARCH_API_BASE"
Write-Host "Remember to set on the API host: QRESEARCH_CORS_ORIGINS=$CorsOrigins"

npx firebase login
npm run deploy

Write-Host ""
Write-Host "Live:"
Write-Host "  https://$ProjectId.web.app"
Write-Host "  https://$ProjectId.firebaseapp.com"
