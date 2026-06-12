@echo off
title Disable LocalReadLog Startup
powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); $shortcut=Join-Path $startup 'LocalReadLog.lnk'; if (Test-Path $shortcut) { Remove-Item $shortcut -Force; Write-Host 'Deleted:' $shortcut } else { Write-Host 'Not found:' $shortcut }"
echo.
pause
