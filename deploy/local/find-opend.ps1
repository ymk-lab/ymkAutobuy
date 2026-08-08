# Locate Futu OpenD exe and print / write suggestion for .env
$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$logs = Join-Path $Root "deploy\local\logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null

# Reuse daemon finder by dot-sourcing a tiny copy of search logic
function Find-OpenDExe {
  if ($env:FUTU_OPEND_EXE -and (Test-Path $env:FUTU_OPEND_EXE)) { return $env:FUTU_OPEND_EXE }
  $names = @("FutuOpenD.exe", "OpenD.exe")
  $roots = @(
    (Join-Path $env:APPDATA "com.futunn.FutuOpenD"),
    (Join-Path $env:APPDATA "Futu"),
    (Join-Path $env:LOCALAPPDATA "Programs"),
    (Join-Path $env:LOCALAPPDATA "Futu"),
    ${env:ProgramFiles},
    ${env:ProgramFiles(x86)},
    (Join-Path $env:USERPROFILE "Futu"),
    (Join-Path $env:USERPROFILE "OpenD"),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "Downloads")
  ) | Where-Object { $_ -and (Test-Path $_) }

  foreach ($r in $roots) {
    foreach ($n in $names) {
      $direct = Join-Path $r $n
      if (Test-Path $direct) { return $direct }
    }
  }
  foreach ($r in $roots) {
    try {
      $hit = Get-ChildItem -Path $r -Filter "FutuOpenD.exe" -Recurse -ErrorAction SilentlyContinue -Depth 5 |
        Select-Object -First 1
      if ($hit) { return $hit.FullName }
      $hit = Get-ChildItem -Path $r -Filter "OpenD.exe" -Recurse -ErrorAction SilentlyContinue -Depth 5 |
        Select-Object -First 1
      if ($hit) { return $hit.FullName }
    } catch { }
  }
  return $null
}

# load .env FUTU_OPEND_EXE if present
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
  Get-Content $envFile -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*FUTU_OPEND_EXE\s*=\s*(.+)\s*$') {
      $env:FUTU_OPEND_EXE = $Matches[1].Trim().Trim('"').Trim("'")
    }
  }
}

$exe = Find-OpenDExe
if ($exe) {
  Write-Host ("FOUND OpenD: " + $exe) -ForegroundColor Green
  Set-Content -Path (Join-Path $logs "opend-path.txt") -Value $exe -Encoding UTF8
  Write-Host "Add to .env:"
  Write-Host ("FUTU_OPEND_EXE=" + $exe)
} else {
  Write-Host "OpenD NOT FOUND." -ForegroundColor Yellow
  Write-Host "1) Install / unzip Futu Command-line OpenD or GUI OpenD"
  Write-Host "2) Put full path in .env, for example:"
  Write-Host "   FUTU_OPEND_EXE=C:\Users\YOU\OpenD\FutuOpenD.exe"
  Write-Host "Command-line OpenD can auto-login via FutuOpenD.xml or:"
  Write-Host "   FUTU_OPEND_LOGIN_ACCOUNT=..."
  Write-Host "   FUTU_OPEND_LOGIN_PWD=..."
}
