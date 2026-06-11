@echo off
chcp 65001 >nul
title LocalReadLog Error Check
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "ROOT_DIR=%~dp0"
set "CORE_DIR=%ROOT_DIR%core"
cd /d "%ROOT_DIR%"

echo.
echo IMPORTANT: Extract the ZIP first. Do not run LocalReadLog from inside the ZIP.
echo Recommended folder: C:\LocalReadLog
echo.

set "PY_EXE="
set "PY_ARGS="

call :find_python
if not defined PY_EXE goto no_python

echo.
echo [1/2] Scanning browser history...
"%PY_EXE%" %PY_ARGS% "%CORE_DIR%\localreadlog_backup.py"
if errorlevel 1 (
    echo.
    echo Browser history scan failed. The server will still try to start.
    echo.
)

echo.
echo [2/2] Starting LocalReadLog server...
echo.
echo PC address:
echo   http://127.0.0.1:8787
echo.
echo If it does not open, try:
echo   http://127.0.0.1:8877
echo   http://127.0.0.1:18787
echo   http://127.0.0.1:28787
echo.
echo Mobile address is shown in the Settings tab after the server opens.
echo Auto update is included while this server is running.
echo.
"%PY_EXE%" %PY_ARGS% "%CORE_DIR%\localreadlog_server.py"

echo.
echo LocalReadLog server stopped or an error occurred.
echo.
pause
exit /b

:find_python
py -3 -c "import sys; sys.exit(0 if sys.version_info[0] == 3 and sys.version_info[1] in range(8,99) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_EXE=py"
    set "PY_ARGS=-3"
    exit /b
)

python -c "import sys; sys.exit(0 if sys.version_info[0] == 3 and sys.version_info[1] in range(8,99) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_EXE=python"
    set "PY_ARGS="
    exit /b
)

python3 -c "import sys; sys.exit(0 if sys.version_info[0] == 3 and sys.version_info[1] in range(8,99) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_EXE=python3"
    set "PY_ARGS="
    exit /b
)

exit /b

:no_python
echo.
echo Python 3.8 or later was not found.
echo.
echo Easy install from PowerShell:
echo   winget install -e --id Python.Python.3.12
echo.
echo After installation, close this window and run 01_Start_Background.vbs again.
echo.
echo If Windows opens Microsoft Store when you type python,
echo disable App execution aliases for python.exe/python3.exe in Windows Settings.
echo.
pause
exit /b 1
