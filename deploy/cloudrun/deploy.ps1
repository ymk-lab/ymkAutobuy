# Deploy Structure Gate API to Cloud Run and wire Firebase Hosting /api rewrite.
# Prerequisites: gcloud, firebase CLI (npx), Docker (or Cloud Build).
param(
  [string]$ProjectId = "ymk-autobuy",
  [string]$Region = "asia-east1",
  [string]$Service = "sg-api",
  [string]$OpenDHost = "",
  [int]$OpenDPort = 11111,
  [switch]$SkipFirebase
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

function Assert-Ok([string]$step) {
  if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)" }
}

if (-not (Get-Command gcloud -ErrorAction SilentlyContinue)) {
  throw "gcloud not found. Install Google Cloud SDK first."
}

Write-Host "==> Project $ProjectId  region $Region  service $Service"
gcloud config set project $ProjectId
Assert-Ok "gcloud config set project"

Write-Host "==> Enable APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firebasehosting.googleapis.com
Assert-Ok "enable APIs"

$envVars = @(
  "QRESEARCH_SG_PAPER_ONLY=1",
  "QRESEARCH_FUTU_ALLOW_LIVE=0",
  "QRESEARCH_SG_PAPER_SUBMIT=0",
  "FUTU_TRD_ENV=SIMULATE",
  ("FUTU_OPEND_PORT={0}" -f $OpenDPort),
  "QRESEARCH_CORS_ORIGINS=*",
  "PYTHONPATH=/app/src"
)
if ($OpenDHost) {
  $envVars += ("FUTU_OPEND_HOST={0}" -f $OpenDHost)
} else {
  $envVars += "FUTU_OPEND_HOST=127.0.0.1"
  Write-Host "NOTE: FUTU_OPEND_HOST=127.0.0.1 inside Cloud Run cannot see your PC OpenD."
  Write-Host "      Pass -OpenDHost <VPS_IP> when OpenD is on a server."
}
$envCsv = [string]::Join(",", $envVars)

Write-Host "==> Build & deploy Cloud Run (Cloud Build)"
gcloud run deploy $Service `
  --source $Root `
  --region $Region `
  --platform managed `
  --allow-unauthenticated `
  --port 8080 `
  --timeout 3600 `
  --cpu 1 `
  --memory 1Gi `
  --set-env-vars $envCsv
Assert-Ok "gcloud run deploy"

$apiUrl = gcloud run services describe $Service --region $Region --format="value(status.url)"
Write-Host ("Cloud Run URL: " + $apiUrl)

# Write firebase.json with run rewrite
$firebaseDir = Join-Path $Root "deploy\firebase"
$firebaseJson = @"
{
  "hosting": {
    "public": "public",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "headers": [
      {
        "source": "/config.js",
        "headers": [{ "key": "Cache-Control", "value": "no-store, max-age=0" }]
      },
      {
        "source": "/static/**",
        "headers": [{ "key": "Cache-Control", "value": "public,max-age=300" }]
      }
    ],
    "rewrites": [
      {
        "source": "/api/**",
        "run": {
          "serviceId": "$Service",
          "region": "$Region"
        }
      },
      {
        "source": "/config.js",
        "destination": "/config.js"
      },
      {
        "source": "**",
        "destination": "/index.html"
      }
    ]
  }
}
"@
[System.IO.File]::WriteAllText((Join-Path $firebaseDir "firebase.json"), $firebaseJson + "`n")

if (-not $SkipFirebase) {
  Write-Host "==> Deploy Firebase Hosting (same-origin /api via Cloud Run)"
  Push-Location $firebaseDir
  try {
    if (-not (Test-Path "node_modules")) { npm install; Assert-Ok "npm install" }
    $rc = @{ projects = @{ default = $ProjectId } } | ConvertTo-Json -Depth 5
    [System.IO.File]::WriteAllText((Join-Path $PWD ".firebaserc"), $rc + "`n")
    # Empty API base => browser calls same-origin /api/*
    $env:QRESEARCH_API_BASE = ""
    npm run build
    Assert-Ok "firebase build"
    npx firebase use $ProjectId
    Assert-Ok "firebase use"
    npx firebase deploy --only hosting
    Assert-Ok "firebase deploy"
  } finally {
    Pop-Location
  }
}

Write-Host ""
Write-Host "Done."
Write-Host ("  UI : https://{0}.web.app" -f $ProjectId)
Write-Host ("  API: {0}  (also https://{1}.web.app/api/...)" -f $apiUrl, $ProjectId)
Write-Host "Clear old tunnel in browser: DevTools > Application > Local Storage > delete qresearch_api_base"
if (-not $OpenDHost) {
  Write-Host "OpenD still on your PC? Keep using start-backend.bat + tunnel, or move OpenD to a VPS and redeploy with -OpenDHost."
}
