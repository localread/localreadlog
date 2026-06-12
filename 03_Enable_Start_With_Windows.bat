@echo off
setlocal
set "APPDIR=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET=%STARTUP%\LocalReadLog_Start.vbs"
copy /Y "%APPDIR%01_Start_Background.vbs" "%TARGET%" >nul
if errorlevel 1 (
  echo 자동 실행 등록 실패
) else (
  echo Windows 시작 시 자동 실행 등록 완료: %TARGET%
)
pause
