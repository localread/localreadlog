@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>nul
if not "%errorlevel%"=="0" (
    echo Requesting administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Adding Windows Firewall rule for LocalReadLog mobile access...
echo Ports: 8787, 8877, 18787, 28787

netsh advfirewall firewall delete rule name="LocalReadLog Mobile Access" >nul 2>nul
netsh advfirewall firewall add rule name="LocalReadLog Mobile Access" dir=in action=allow protocol=TCP localport=8787,8877,18787,28787 profile=private >nul

if errorlevel 1 (
    echo Failed to add firewall rule.
    echo Try running this file as administrator.
) else (
    echo Done.
    echo Mobile access should now work on the same Wi-Fi network.
)

echo.
echo If it still does not work, check that PC and phone are on the same Wi-Fi.
pause
