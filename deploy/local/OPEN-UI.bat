@echo off
REM Opens Firebase with current tunnel API, else localhost.
cd /d "%~dp0"
set TUNNEL=
if exist "logs\tunnel-url.txt" (
  set /p TUNNEL=<logs\tunnel-url.txt
)
if not "%TUNNEL%"=="" (
  echo Opening Firebase with API %TUNNEL%
  start "" "https://ymk-autobuy.web.app/?api=%TUNNEL%"
) else (
  echo Opening local UI
  start "" "http://127.0.0.1:8787"
)
