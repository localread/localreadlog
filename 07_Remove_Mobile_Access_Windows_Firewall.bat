@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>nul
if not "%errorlevel%"=="0" (
    echo Requesting administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Removing Windows Firewall rule for LocalReadLog mobile access...
netsh advfirewall firewall delete rule name="LocalReadLog Mobile Access" >nul 2>nul

echo Done.
pause
