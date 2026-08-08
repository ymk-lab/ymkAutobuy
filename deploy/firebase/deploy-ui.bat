@echo off
setlocal
cd /d "%~dp0"
title Deploy Structure Gate UI to Firebase
echo Deploying UI only (API URL set later in the webpage)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy.ps1" -ProjectId ymk-autobuy -UiSetsApi
echo.
pause
