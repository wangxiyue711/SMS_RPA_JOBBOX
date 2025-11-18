@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM Auto-restart watcher for email_watcher.py
if not exist "logs" mkdir "logs"

REM Check if .venv exists
if not exist .venv\Scripts\python.exe (
  echo [ERROR] .venv not found - please run install_all_windows.cmd first.
  pause
  exit /b 1
)

REM Prompt for UID and interval
set /p USER_UID=UID: 
if "%USER_UID%"=="" (
  echo [ERROR] UID is required.
  pause
  exit /b 1
)

set /p USER_INTERVAL=Interval seconds (default=30): 
if "%USER_INTERVAL%"=="" set USER_INTERVAL=30

echo.
echo ========================================
echo RPA Monitoring System Started
echo UID: %USER_UID%
echo Interval: %USER_INTERVAL% seconds
echo Auto-restart: Enabled (check every 10 seconds)
echo Log: logs\watcher.log
echo ========================================
echo.
echo Close this window to stop RPA.
echo email_watcher.py window will open automatically.
echo.

:RESTART_LOOP
REM Ensure no duplicate EmailWatcher windows
taskkill /F /FI "WINDOWTITLE eq EmailWatcher*" >nul 2>&1

echo [%date% %time%] Starting email_watcher.py... >> "logs\watcher.log"
echo [%date% %time%] Starting email_watcher.py...

REM Start python process with visible window
start "EmailWatcher" .venv\Scripts\python.exe -u src\email_watcher.py --uid %USER_UID% --interval %USER_INTERVAL%

REM Give it a moment to initialize
timeout /t 5 >nul

:CHECK_LOOP
REM Check if email_watcher window still exists
tasklist /V /FI "WINDOWTITLE eq EmailWatcher*" 2>nul | find /I "EmailWatcher" >nul
if errorlevel 1 (
  echo [%date% %time%] [WARNING] email_watcher.py stopped. Restarting in 10 seconds... >> "logs\watcher.log"
  echo [%date% %time%] [WARNING] email_watcher.py stopped. Restarting in 10 seconds...
  timeout /t 10 >nul
  goto RESTART_LOOP
)

REM Wait 10 seconds before next check
timeout /t 10 >nul
goto CHECK_LOOP

endlocal
