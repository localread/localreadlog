@echo off
title Disable LocalReadLog Startup
powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $shortcut=Join-Path $startup 'LocalReadLog.lnk'; if (Test-Path $shortcut) { Remove-Item $shortcut -Force; Write-Host 'Removed:' $shortcut } else { Write-Host 'Startup shortcut was not found.' }"

echo.
echo Done.
echo.
pause
