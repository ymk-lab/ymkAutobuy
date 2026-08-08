@echo off
setlocal
cd /d "%~dp0\..\.."
title Structure Gate backend
echo Starting Structure Gate backend (uvicorn + tunnel)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-backend.ps1" %*
echo.
pause
