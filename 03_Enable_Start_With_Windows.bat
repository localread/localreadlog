@echo off
title Enable LocalReadLog Startup
set "LRL_TARGET=%~dp001_Start_Background.vbs"
set "LRL_WORKDIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $shortcut=Join-Path $startup 'LocalReadLog.lnk'; $target=$env:LRL_TARGET; $work=$env:LRL_WORKDIR; $w=New-Object -ComObject WScript.Shell; $s=$w.CreateShortcut($shortcut); $s.TargetPath=$target; $s.WorkingDirectory=$work; $s.Description='Start LocalReadLog in background with auto update'; $s.Save(); Write-Host 'Created:' $shortcut"

echo.
echo Done. LocalReadLog will start in the background after Windows login.
echo It includes hourly auto update while running.
echo You can remove it later with 04_Disable_Start_With_Windows.bat.
echo.
pause
