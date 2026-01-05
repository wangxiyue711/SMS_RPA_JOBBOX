chcp 65001 >nul
setlocal enabledelayedexpansion

REM Auto-restart watcher for email_watcher.py
if not exist "logs" mkdir "logs"

REM Check if .venv exists
if not exist .venv\Scripts\python.exe (
  echo 仮想環境が見つかりません。install_all_windows.cmd を実行してください。
  pause
  exit /b 1
)

REM Check if another run_watcher.cmd is already running for this project
tasklist /V /FI "WINDOWTITLE eq RPA Monitoring*" 2>nul | find /I "cmd.exe" >nul
if not errorlevel 1 (
  echo.
  echo.
  pause
  exit /b 1
)

echo.

REM Prompt for UID and interval
set /p USER_UID=UIDを入力してください: 
if "%USER_UID%"=="" (
  echo UIDが必要です。
  pause
  exit /b 1
)

set /p USER_INTERVAL=監視間隔（秒・デフォルト30）: 
if "%USER_INTERVAL%"=="" set USER_INTERVAL=30

REM Change window title to identify this monitoring session
title RPA Monitoring - UID: %USER_UID%

echo.
echo EmailWatcherを起動しました。
echo.

:RESTART_LOOP
REM Ensure no duplicate email_watcher.py processes (by command line, PowerShell, filter by UID)
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'email_watcher.py' -and $_.CommandLine -match $env:USER_UID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [%date% %time%] EmailWatcher起動中... >> "logs\watcher.log"

REM Start python process with visible window
start "EmailWatcher" .venv\Scripts\python.exe -u src\email_watcher.py --uid %USER_UID% --interval %USER_INTERVAL%

REM Give it a moment to initialize
timeout /t 5 >nul

:CHECK_LOOP
REM Check if email_watcher.py process is running (by command line, PowerShell)
set FOUND=0
for /f %%P in ('powershell -NoProfile -Command "@(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'email_watcher.py' -and $_.CommandLine -match $env:USER_UID }).Count"') do set FOUND=%%P
if %FOUND%==0 (
  echo [%date% %time%] EmailWatcherが停止しました。10秒後に再起動します... >> "logs\watcher.log"
  REM Kill all email_watcher.py processes for this UID before restart
  powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'email_watcher.py' -and $_.CommandLine -match $env:USER_UID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
  timeout /t 10 >nul
  goto RESTART_LOOP
)

REM Wait 10 minutes before next check
timeout /t 600 /nobreak >nul
goto CHECK_LOOP

endlocal

