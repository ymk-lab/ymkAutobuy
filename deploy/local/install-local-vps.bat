@echo off
setlocal
cd /d "%~dp0\..\.."
title Install local VPS: OpenD + API autostart
echo.
echo ========================================
echo  Local VPS one-key setup
echo  - Find / use Futu OpenD
echo  - Autostart OpenD + API + tunnel at logon
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-cloudflared.ps1"
if errorlevel 1 echo (cloudflared install skipped/failed - daemon can retry)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0find-opend.ps1"

echo.
echo Registering Windows logon autostart...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-autostart.ps1" -StartNow

echo.
echo Done. Check logs:
echo   deploy\local\logs\daemon.log
echo   deploy\local\logs\tunnel-url.txt
echo.
echo Tip: set FUTU_OPEND_EXE in .env if OpenD was not found.
echo Tip: for fixed public URL set CLOUDFLARE_TUNNEL_TOKEN + CLOUDFLARE_PUBLIC_URL
echo.
pause
