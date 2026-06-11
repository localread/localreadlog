@echo off
setlocal EnableExtensions
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

for %%I in ("%~dp0..") do set "ROOT_DIR=%%~fI"
set "CORE_DIR=%ROOT_DIR%\core"
set "DATA_DIR=%ROOT_DIR%\data"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%" >nul 2>nul
set "LOG_FILE=%DATA_DIR%\localreadlog_background.log"

echo.>> "%LOG_FILE%"
echo IMPORTANT: Extract the ZIP first. Recommended folder: C:\LocalReadLog>> "%LOG_FILE%"

call :check_already_running
if defined LRL_ALREADY_RUNNING exit /b 0

set "PY_EXE="
set "PY_ARGS="
call :find_python
if not defined PY_EXE exit /b 1

echo.>> "%LOG_FILE%"
echo ===== LocalReadLog background start =====>> "%LOG_FILE%"
echo %DATE% %TIME%>> "%LOG_FILE%"

echo [1/2] Scan browser history>> "%LOG_FILE%"
"%PY_EXE%" %PY_ARGS% "%CORE_DIR%\localreadlog_backup.py" >> "%LOG_FILE%" 2>&1

echo [2/2] Start server>> "%LOG_FILE%"
"%PY_EXE%" %PY_ARGS% "%CORE_DIR%\localreadlog_server.py" >> "%LOG_FILE%" 2>&1

echo Server process ended.>> "%LOG_FILE%"
exit /b


:check_already_running
set "RUNNING_PORT="
set "FIND_PORT_PS1=%CORE_DIR%\localreadlog_find_server_port.ps1"
if exist "%FIND_PORT_PS1%" (
    for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%FIND_PORT_PS1%" -Root "%ROOT_DIR%" 2^>nul`) do (
        if not defined RUNNING_PORT set "RUNNING_PORT=%%P"
    )
)
if defined RUNNING_PORT (
    echo %RUNNING_PORT%> "%DATA_DIR%\localreadlog_server_port.txt"
    echo LocalReadLog is already running on port %RUNNING_PORT%.>> "%LOG_FILE%"
    echo Opening the existing server instead of starting a duplicate.>> "%LOG_FILE%"
    set "LRL_ALREADY_RUNNING=1"
    exit /b 0
)
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
