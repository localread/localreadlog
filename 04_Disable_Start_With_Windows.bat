@echo off
setlocal
set "TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LocalReadLog_Start.vbs"
if exist "%TARGET%" del /f /q "%TARGET%"
echo Windows 시작 시 자동 실행 해제 완료
pause
