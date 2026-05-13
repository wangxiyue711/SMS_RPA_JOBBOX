@echo off
chcp 65001 >nul
setlocal

set DEFAULT_TARGET_URL=https://xn--pckua2a7gp15o89zb.com/93187E31781E495BAB

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set PYTHON_EXE=

if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe --version >nul 2>&1
  if not errorlevel 1 (
    set PYTHON_EXE=.venv\Scripts\python.exe
  )
)

if "%PYTHON_EXE%"=="" (
  where python >nul 2>&1
  if not errorlevel 1 (
    set PYTHON_EXE=python
  ) else (
    where py >nul 2>&1
    if not errorlevel 1 (
      set PYTHON_EXE=py -3
    )
  )
)

if "%PYTHON_EXE%"=="" (
  echo [ERROR] Python not found.
  echo [ERROR] Please install Python or create .venv first.
  pause
  exit /b 1
)

echo ========================================
echo Job Site Scraper
echo 出力項目: キーワード + タイトル + 企業名 + 企業種別
echo ========================================
echo.

set TARGET_URL=%~1
if "%TARGET_URL%"=="" set TARGET_URL=%DEFAULT_TARGET_URL%
if "%TARGET_URL%"=="" (
  echo [ERROR] URL is required.
  pause
  exit /b 1
)

echo 求人サイト URL: %TARGET_URL%

set TARGET_KEYWORD=%~2
if "%TARGET_KEYWORD%"=="" set /p TARGET_KEYWORD=検索キーワード（複数指定は , / 、 / or）: 
if "%TARGET_KEYWORD%"=="" (
  echo [ERROR] Keyword is required.
  pause
  exit /b 1
)

set TARGET_COUNT=%~3
if "%TARGET_COUNT%"=="" set /p TARGET_COUNT=取得件数（Enterで既定値）: 

echo.
if "%TARGET_COUNT%"=="" (
  call %PYTHON_EXE% scripts\job_site_scraper.py --url "%TARGET_URL%" --keyword "%TARGET_KEYWORD%"
) else (
  call %PYTHON_EXE% scripts\job_site_scraper.py --url "%TARGET_URL%" --keyword "%TARGET_KEYWORD%" --max-results "%TARGET_COUNT%"
)

echo.
pause
endlocal