@echo off
cd /d "%~dp0"
title Setup stable Cloudflare URL
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-stable-url.ps1"
echo.
pause
