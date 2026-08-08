# Deploy Structure Gate UI to Firebase Hosting.
# Usage:
#   .\deploy.ps1 -ProjectId my-firebase-id -ApiBase https://xxx.trycloudflare.com
param(
  [Parameter(Mandatory = $true)][string]$ProjectId,
  [Parameter(Mandatory = $true)][string]$ApiBase,
  [string]$CorsOrigins = "",
  [switch]$CreateProject
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Assert-Ok($step) {
  if ($LASTEXITCODE -ne 0) {
    throw "$step failed (exit $LASTEXITCODE)"
  }
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
  throw "npm not found. Install Node.js LTS first."
}

$ApiBase = $ApiBase.Trim().TrimEnd("/")
$ProjectId = $ProjectId.Trim()

if ($ProjectId -match "YOUR_|PLACEHOLDER|example" -or $ProjectId.Length -lt 3) {
  throw @"
ProjectId 還是佔位字。請先建立 Firebase 專案：

  npx firebase login
  npx firebase projects:create ymk-autobuy --display-name "ymk Autobuy"
  # 或開 https://console.firebase.google.com/ → Add project
"@
}

if (
  $ApiBase -notmatch "^https://" -or
  $ApiBase -match "YOUR_|PLACEHOLDER|example\.com|TUNNEL_HOST" -or
  $ApiBase -match "127\.0\.0\.1|localhost"
) {
  throw @"
ApiBase 必須是公開的 https 隧道網址（不能用 127.0.0.1 / localhost）。
Firebase 頁面是 https，瀏覽器會擋掉打本機 http。

1) uvicorn 已在 :8787 即可
2) 另開視窗：cloudflared tunnel --url http://127.0.0.1:8787
3) 複製日誌中的 https://xxxx.trycloudflare.com
4) .\deploy.ps1 -ProjectId <id> -ApiBase https://xxxx.trycloudflare.com
"@
}

npm install
Assert-Ok "npm install"

if ($CreateProject) {
  Write-Host "Creating Firebase project $ProjectId ..."
  npx firebase projects:create $ProjectId --display-name "ymk Autobuy"
  if ($LASTEXITCODE -ne 0) {
    Write-Host "projects:create failed — ID 可能已被占用。改跑：npx firebase projects:list"
    throw "firebase projects:create failed"
  }
}

$rc = @{ projects = @{ default = $ProjectId } } | ConvertTo-Json -Depth 5
Set-Content -Path ".firebaserc" -Value $rc -Encoding UTF8

$env:QRESEARCH_API_BASE = $ApiBase
if ($CorsOrigins -eq "") {
  $CorsOrigins = "https://$ProjectId.web.app,https://$ProjectId.firebaseapp.com"
}
Write-Host "API_BASE=$env:QRESEARCH_API_BASE"
Write-Host "Remember to set on the API host: QRESEARCH_CORS_ORIGINS=$CorsOrigins"

Write-Host "Checking project access..."
npx firebase projects:list
Assert-Ok "firebase projects:list"

npx firebase use $ProjectId
if ($LASTEXITCODE -ne 0) {
  throw @"
無法選取專案 '$ProjectId'。帳號 ymk@twmlsws.edu.hk 下可能還沒有這個專案。

請執行其一：
  .\deploy.ps1 -ProjectId $ProjectId -ApiBase $ApiBase -CreateProject
或
  開 https://console.firebase.google.com/ 用同一 Google 帳號 Add project，
  再到 Project settings 複製真正的 Project ID。
"@
}

npm run deploy
Assert-Ok "firebase deploy"

Write-Host ""
Write-Host "Live:"
Write-Host "  https://$ProjectId.web.app"
Write-Host "  https://$ProjectId.firebaseapp.com"
