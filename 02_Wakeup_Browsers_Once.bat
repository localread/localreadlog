@echo off
setlocal
title LocalReadLog Browser Wakeup Once
set "LRL_ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0core\localreadlog_browser_wakeup_once.ps1" -Root "%LRL_ROOT%" -WaitSeconds 12 -VerboseLog
pause
