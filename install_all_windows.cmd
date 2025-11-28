
@echo off
chcp 65001 >nul
REM Silent installer (no system-level installs). ASCII-only console output. Logs to install.log.
set LOGFILE=install.log
echo Starting installation... > %LOGFILE% 2>&1

setlocal enabledelayedexpansion

:: simple progress helper (ASCII only)
call :show_progress 0 "Starting"

:: Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Python not found. Please install Python 3.10+ and re-run. >> %LOGFILE% 2>&1
  echo [ERROR] Python not found. Please install Python 3.10+ and re-run.
  pause
  exit /b 1
) else (
  echo Python found. >> %LOGFILE% 2>&1
)

call :show_progress 10 "Python check"

:: Create venv
if not exist .venv (
  echo Creating virtual environment .venv ... >> %LOGFILE% 2>&1
  python -m venv .venv >> %LOGFILE% 2>&1
) else (
  echo .venv exists; skipping venv creation. >> %LOGFILE% 2>&1
)

call :show_progress 40 "Virtualenv"

:: Ensure pip path
set PIP=.venv\Scripts\pip.exe
if not exist %PIP% (
  echo [ERROR] pip not found in .venv; check Python/venv creation. >> %LOGFILE% 2>&1
  echo [ERROR] pip not found in .venv; check Python/venv creation.
  pause
  exit /b 1
)

echo Installing packages... >> %LOGFILE% 2>&1r
%PIP% install --upgrade pip >> %LOGFILE% 2>&1
%PIP% install -r requirements.txt >> %LOGFILE% 2>&1
%PIP% install webdriver-manager >> %LOGFILE% 2>&1

call :show_progress 80 "Installing packages"

:: Check service-account presence
if not exist service-account\* (
  echo [ERROR] service-account folder not found or empty. >> %LOGFILE% 2>&1
  echo [ERROR] service-account folder not found or empty.
  pause
  exit /b 1
)

:: Locate embedded template marker line number in THIS script (%~f0)
for /f "tokens=1 delims=:" %%L in ('findstr /n /c:"###__RUN_WATCHER_TEMPLATE_START__###" "%~f0"') do set TPL_LINE=%%L
if "%TPL_LINE%"=="" (
  echo [ERROR] Embedded template marker not found. >> %LOGFILE% 2>&1
  echo [ERROR] Embedded template marker not found.
  pause
  exit /b 1
)
set /a TPL_START=TPL_LINE+1

:: Delete old run_watcher.cmd if exists (reliable PowerShell removal)
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path 'run_watcher.cmd') { Remove-Item -Force 'run_watcher.cmd' }"
timeout /t 1 /nobreak >nul

:: Extract embedded template to run_watcher.cmd (no escaping issues)
more +%TPL_START% "%~f0" > run_watcher.cmd
if not exist "run_watcher.cmd" (
  echo [ERROR] run_watcher.cmd was not created. >> %LOGFILE% 2>&1
  echo [ERROR] run_watcher.cmd was not created.
  pause
  exit /b 1
)

call :show_progress 100 "Done"

echo Installation complete. Press Enter to exit. >> %LOGFILE% 2>&1
echo Installation complete. Press Enter to exit.
pause

endlocal

goto :eof

:show_progress <percent> <message>
:: Prints a simple ASCII progress bar and message
:show_progress
set PCT=%~1
set MSG=%~2
set /a FILLS=(PCT*40)/100
set BAR=
for /L %%i in (1,1,%FILLS%) do set BAR=!BAR!#
set /a SPACES=40-FILLS
for /L %%i in (1,1,%SPACES%) do set BAR=!BAR! 
echo [!BAR!] %PCT%% - %MSG%
goto :eof

###__RUN_WATCHER_TEMPLATE_START__###
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

REM Check if another run_watcher.cmd is already running for this project
tasklist /V /FI "WINDOWTITLE eq RPA Monitoring*" 2>nul | find /I "cmd.exe" >nul
if not errorlevel 1 (
  echo.
  echo [WARNING] Another RPA Monitoring window is already running!
  echo Please close the existing window first to avoid conflicts.
  echo.
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

REM Change window title to identify this monitoring session
title RPA Monitoring - UID: %USER_UID%

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
REM Ensure no duplicate email_watcher.py processes (by command line, PowerShell, filter by UID)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'email_watcher.py' -and $_.CommandLine -match $env:USER_UID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo [%date% %time%] Starting email_watcher.py... >> "logs\watcher.log"
echo [%date% %time%] Starting email_watcher.py...

REM Start python process with visible window
start "EmailWatcher" .venv\Scripts\python.exe -u src\email_watcher.py --uid %USER_UID% --interval %USER_INTERVAL%

REM Give it a moment to initialize
timeout /t 5 >nul

:CHECK_LOOP
REM Check if email_watcher.py process is running (by command line, PowerShell)
set FOUND=0
for /f %%P in ('powershell -NoProfile -Command "@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'email_watcher.py' -and $_.CommandLine -match $env:USER_UID }).Count"') do set FOUND=%%P
if %FOUND%==0 (
  echo [%date% %time%] [WARNING] email_watcher.py stopped. Restarting in 10 seconds... >> "logs\watcher.log"
  echo [%date% %time%] [WARNING] email_watcher.py stopped. Restarting in 10 seconds...
  REM Kill all email_watcher.py processes for this UID before restart
  powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'email_watcher.py' -and $_.CommandLine -match $env:USER_UID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
  timeout /t 10 >nul
  goto RESTART_LOOP
)

REM Wait 10 minutes before next check
timeout /t 600 /nobreak >nul
goto CHECK_LOOP

endlocal

