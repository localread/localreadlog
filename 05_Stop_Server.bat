@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0core\localreadlog_stop.ps1" -Root "%~dp0"
pause
