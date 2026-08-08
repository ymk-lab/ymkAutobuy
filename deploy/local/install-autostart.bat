@echo off
setlocal
cd /d "%~dp0\..\.."
title Install Structure Gate autostart
echo Register logon autostart for Structure Gate backend...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-autostart.ps1" -StartNow
echo.
pause
