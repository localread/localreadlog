@echo off
title Enable LocalReadLog Startup
set "LRL_TARGET=%~dp001_Start_Background.vbs"
set "LRL_WORKDIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $shortcut=Join-Path $startup 'LocalReadLog.lnk'; $target=$env:LRL_TARGET; $work=$env:LRL_WORKDIR; if (!(Test-Path $target)) { Write-Host 'Target not found:' $target; exit 1 }; $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($shortcut); $s.TargetPath=$target; $s.WorkingDirectory=$work; $s.Description='Start LocalReadLog in background'; $s.Save(); Write-Host 'Created:' $shortcut; Write-Host 'Target :' $target"

echo.
echo Done. LocalReadLog will start in the background after Windows login.
echo Startup sequence: wake browsers once, close only browsers started by this script, then start LocalReadLog.
echo You can remove it later with 04_Disable_Start_With_Windows.bat or by deleting LocalReadLog.lnk from shell:startup.
echo.
pause
