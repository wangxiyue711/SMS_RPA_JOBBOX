@echo off
REM Activate venv and run the email watcher, redirect output to logs\watcher.log
if not exist "logs" mkdir "logs"
if exist .venv\Scripts\python.exe (
  echo Using .venv\Scripts\python.exe
  .venv\Scripts\python.exe -u src\email_watcher.py >>"logs\watcher.log" 2>&1
) else (
  echo ".venv python.exe not found - attempting to run system python." >>"logs\watcher.log" 2>&1
  python -u src\email_watcher.py >>"logs\watcher.log" 2>&1
)
echo -------- watcher exited with code %errorlevel% >>"logs\watcher.log"
echo Showing last 50 lines of logs\watcher.log
powershell -Command "Get-Content -Path 'logs\\watcher.log' -Tail 50"
echo Press Enter to exit...
pause
