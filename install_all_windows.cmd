
@echo off
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

echo Installing packages... >> %LOGFILE% 2>&1
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

:: Create run_watcher.cmd (logs to logs\watcher.log and pauses at end)
echo @echo off>run_watcher.cmd
echo if not exist "logs" mkdir "logs" >>run_watcher.cmd
echo echo Starting watcher; logs -> logs\watcher.log >>run_watcher.cmd
echo if exist .venv\Scripts\activate.bat ( >>run_watcher.cmd
echo   call .venv\Scripts\activate.bat >>run_watcher.cmd
echo ) else ( >>run_watcher.cmd
echo   echo .venv not found - please run install_all_windows.cmd first to create venv. >>run_watcher.cmd
echo   pause >>run_watcher.cmd
echo   exit /b 1 >>run_watcher.cmd
echo ) >>run_watcher.cmd
echo if exist .venv\Scripts\python.exe ( >>run_watcher.cmd
echo   .venv\Scripts\python.exe -u src\email_watcher.py ^>^> "logs\watcher.log" 2^>^&1 >>run_watcher.cmd
echo ) else ( >>run_watcher.cmd
echo   python -u src\email_watcher.py ^>^> "logs\watcher.log" 2^>^&1 >>run_watcher.cmd
echo ) >>run_watcher.cmd
echo echo -------- watcher exited with code %%errorlevel%% ^>^> "logs\watcher.log" >>run_watcher.cmd
echo echo Output (last 50 lines): >>run_watcher.cmd
echo powershell -Command "Get-Content -Path 'logs\\watcher.log' -Tail 50" >>run_watcher.cmd
echo echo Press Enter to exit... >>run_watcher.cmd
echo pause >>run_watcher.cmd

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

