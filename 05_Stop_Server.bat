@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Stop LocalReadLog Server
set "ROOT_DIR=%~dp0"
set "STOP_PS1=%ROOT_DIR%core\localreadlog_stop.ps1"

echo Stopping LocalReadLog...
echo.

if exist "%STOP_PS1%" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%STOP_PS1%"
) else (
    echo Stop script not found: %STOP_PS1%
    echo Running emergency stop instead.
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'localreadlog' -and $_.CommandLine -notmatch '05_Stop_Server|localreadlog_stop' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F }; Get-NetTCPConnection -LocalPort 8787,8877,18787,28787 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { taskkill /PID $_.OwningProcess /T /F }"
)

echo.
echo If the server page still opens, run this file as administrator.
echo.
pause
