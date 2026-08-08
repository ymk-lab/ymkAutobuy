@echo off
REM Opens the current UI: prefers tunnel-url.txt, else localhost.
cd /d "%~dp0"
set URL=
if exist "logs\tunnel-url.txt" (
  set /p URL=<logs\tunnel-url.txt
)
if "%URL%"=="" set URL=http://127.0.0.1:8787
echo Opening %URL%
start "" "%URL%"
