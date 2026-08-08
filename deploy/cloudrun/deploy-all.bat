@echo off
setlocal
cd /d "%~dp0"
title Deploy API (Cloud Run) + Firebase Hosting
echo.
echo This deploys FastAPI to Cloud Run and wires Firebase /api/** rewrite.
echo OpenD on your PC is NOT visible to Cloud Run.
echo For trading, pass OpenD VPS IP later, e.g.:
echo   powershell -File deploy.ps1 -ProjectId ymk-autobuy -OpenDHost YOUR_VPS_IP
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -ProjectId ymk-autobuy -Region asia-east1
echo.
pause
