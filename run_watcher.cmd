@echo off@echo off@echo off

chcp 65001 >nul

setlocal enabledelayedexpansionchcp 65001 >nulREM Activate venv and run the email watcher, redirect output to logs\watcher.log



REM Auto-restart watcher for email_watcher.pysetlocal enabledelayedexpansionif not exist "logs" mkdir "logs"

if not exist "logs" mkdir "logs"

if exist .venv\Scripts\python.exe (

REM Check if .venv exists

if not exist .venv\Scripts\python.exe (REM Auto-restart watcher for email_watcher.py  echo Using .venv\Scripts\python.exe

  echo [エラー] .venv が見つかりません。先に install_all_windows.cmd を実行してください。

  pauseif not exist "logs" mkdir "logs"  .venv\Scripts\python.exe -u src\email_watcher.py >>"logs\watcher.log" 2>&1

  exit /b 1

)) else (



REM Prompt for UID and intervalREM Check if .venv exists  echo ".venv python.exe not found - attempting to run system python." >>"logs\watcher.log" 2>&1

set /p USER_UID=UID を入力してください: 

if "%USER_UID%"=="" (if not exist .venv\Scripts\python.exe (  python -u src\email_watcher.py >>"logs\watcher.log" 2>&1

  echo [エラー] UID が必要です。

  pause  echo [ERROR] .venv not found - please run install_all_windows.cmd first.)

  exit /b 1

)  pauseecho -------- watcher exited with code %errorlevel% >>"logs\watcher.log"



set /p USER_INTERVAL=監視間隔（秒、デフォルト=30）:   exit /b 1echo Showing last 50 lines of logs\watcher.log

if "%USER_INTERVAL%"=="" set USER_INTERVAL=30

)powershell -Command "Get-Content -Path 'logs\\watcher.log' -Tail 50"

echo.

echo ========================================echo Press Enter to exit...

echo RPA監視システム起動

echo UID: %USER_UID%REM Prompt for UID and intervalpause

echo 監視間隔: %USER_INTERVAL% 秒

echo 自動再起動: 有効 10秒毎にチェックset /p USER_UID=UID: 

echo ログ: logs\watcher.logif "%USER_UID%"=="" (

echo ========================================  echo [ERROR] UID is required.

echo.  pause

echo このウィンドウを閉じるとRPAが停止します。  exit /b 1

echo email_watcher.py のウィンドウが自動で開きます。)

echo.

set /p USER_INTERVAL=Interval seconds (default=30): 

:RESTART_LOOPif "%USER_INTERVAL%"=="" set USER_INTERVAL=30

REM Kill any existing EmailWatcher windows first

for /f "tokens=2" %%p in ('tasklist /V /FI "WINDOWTITLE eq EmailWatcher*" 2^>nul ^| find /I "EmailWatcher"') do taskkill /PID %%p /F >nul 2>&1echo.

timeout /t 2 /nobreak >nulecho ========================================

echo RPA Monitoring System Started

echo [%date% %time%] email_watcher.py を起動中... >> "logs\watcher.log"echo UID: %USER_UID%

echo [%date% %time%] email_watcher.py を起動中...echo Interval: %USER_INTERVAL% seconds

echo Auto-restart: Enabled (check every 10 seconds)

REM Start python process with visible windowecho Log: logs\watcher.log

start "EmailWatcher" .venv\Scripts\python.exe -u src\email_watcher.py --uid %USER_UID% --interval %USER_INTERVAL%echo ========================================

echo.

REM Wait for process to initializeecho Close this window to stop RPA.

timeout /t 5 /nobreak >nulecho email_watcher.py window will open automatically.

echo.

:CHECK_LOOP

REM Check if email_watcher window still exists:RESTART_LOOP

tasklist /V /FI "WINDOWTITLE eq EmailWatcher*" 2>nul | find /I "EmailWatcher" >nulREM Kill any existing EmailWatcher windows first

if errorlevel 1 (for /f "tokens=2" %%p in ('tasklist /V /FI "WINDOWTITLE eq EmailWatcher*" 2^>nul ^| find /I "EmailWatcher"') do taskkill /PID %%p /F >nul 2>&1

  echo [%date% %time%] [警告] email_watcher.py が停止しました。10秒後に再起動します... >> "logs\watcher.log"timeout /t 2 /nobreak >nul

  echo [%date% %time%] [警告] email_watcher.py が停止しました。10秒後に再起動します...

  timeout /t 10 /nobreak >nulecho [%date% %time%] Starting email_watcher.py... >> "logs\watcher.log"

  goto RESTART_LOOPecho [%date% %time%] Starting email_watcher.py...

)

REM Start python process with visible window

REM Wait 10 seconds before next checkstart "EmailWatcher" .venv\Scripts\python.exe -u src\email_watcher.py --uid %USER_UID% --interval %USER_INTERVAL%

timeout /t 10 /nobreak >nul

goto CHECK_LOOPREM Wait for process to initialize

timeout /t 5 /nobreak >nul

endlocal

:CHECK_LOOP
REM Check if email_watcher window still exists
tasklist /V /FI "WINDOWTITLE eq EmailWatcher*" 2>nul | find /I "EmailWatcher" >nul
if errorlevel 1 (
  echo [%date% %time%] [WARNING] email_watcher.py stopped. Restarting in 10 seconds... >> "logs\watcher.log"
  echo [%date% %time%] [WARNING] email_watcher.py stopped. Restarting in 10 seconds...
  timeout /t 10 /nobreak >nul
  goto RESTART_LOOP
)

REM Wait 10 seconds before next check
timeout /t 10 /nobreak >nul
goto CHECK_LOOP

endlocal
