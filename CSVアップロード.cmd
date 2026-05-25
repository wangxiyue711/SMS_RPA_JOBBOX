@echo off
REM =============================================================================
REM CSV履歴データをGoogle Spreadsheetにアップロード - GUI版
REM 
REM 使用方法: ダブルクリックで実行 → GUIウィンドウが開きます
REM =============================================================================

setlocal enabledelayedexpansion
chcp 65001 > nul

REM ===== Python自動検出 =====
set PYTHON_EXE=

REM 方法1: where コマンドで検出
where python > nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%i in ('where python 2^>nul') do (
        set "PYTHON_EXE=%%i"
        goto :python_found
    )
)

REM 方法2: 一般的なインストール場所を探す
set COMMON_PATHS=^
    "%LOCALAPPDATA%\Programs\Python\Python*\python.exe";^
    "C:\Python*\python.exe";^
    "%PROGRAMFILES%\Python*\python.exe";^
    "%PROGRAMFILES(X86)%\Python*\python.exe";^
    "%USERPROFILE%\AppData\Local\Programs\Python\Python*\python.exe"

for %%p in (%COMMON_PATHS%) do (
    for /f "delims=" %%f in ('dir %%p /b /s 2^>nul') do (
        set "PYTHON_EXE=%%f"
        goto :python_found
    )
)

REM 方法3: py.exe ランチャーを使用（Windows Store版など）
where py > nul 2>&1
if not errorlevel 1 (
    set "PYTHON_EXE=py"
    goto :python_found
)

REM Pythonが見つからない場合
cls
echo.
echo ╔════════════════════════════════════════════════════════════════════════╗
echo ║                        ⚠ Pythonが見つかりません                         ║
echo ╚════════════════════════════════════════════════════════════════════════╝
echo.
echo このツールを使用するには、Pythonのインストールが必要です。
echo.
echo 【インストール手順】
echo.
echo   1. 以下のURLからPythonをダウンロード:
echo      https://www.python.org/downloads/
echo.
echo   2. インストール時に "Add Python to PATH" にチェックを入れる
echo.
echo   3. インストール後、このツールを再度実行してください
echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
pause
exit /b 1

:python_found

REM ===== Python動作確認 =====
"%PYTHON_EXE%" --version > nul 2>&1
if errorlevel 1 (
    cls
    echo Python の実行に失敗しました: %PYTHON_EXE%
    pause
    exit /b 1
)

REM Pythonバージョン取得
for /f "tokens=2" %%v in ('"%PYTHON_EXE%" --version 2^>^&1') do set PY_VERSION=%%v

REM スクリプトのディレクトリ
set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%
cd /d "%SCRIPT_DIR%"

REM パス設定
set PYTHON_SCRIPT=%SCRIPT_DIR%\scripts\upload_gui.py
set CONFIG_FILE=%SCRIPT_DIR%\config\upload_config.json

REM スクリプト存在確認
if not exist "%PYTHON_SCRIPT%" (
    cls
    echo.
    echo ✗ スクリプトが見つかりません: %PYTHON_SCRIPT%
    echo.
    echo ファイル構成を確認してください。
    pause
    exit /b 1
)

REM ===== 依存ライブラリの確認とインストール =====
"%PYTHON_EXE%" -c "import gspread" > nul 2>&1
if errorlevel 1 (
    cls
    echo.
    echo ╔════════════════════════════════════════════════════════════════════════╗
    echo ║                    必要なライブラリをインストール中...                   ║
    echo ╚════════════════════════════════════════════════════════════════════════╝
    echo.
    echo Python バージョン: %PY_VERSION%
    echo.
    echo 必要なライブラリ（gspread, google-auth）をインストールしています...
    echo しばらくお待ちください。
    echo.
    
    "%PYTHON_EXE%" -m pip install --quiet gspread google-auth
    
    if errorlevel 1 (
        echo.
        echo ✗ インストールに失敗しました。
        echo.
        echo 手動でインストールを試してください:
        echo   %PYTHON_EXE% -m pip install gspread google-auth
        echo.
        pause
        exit /b 1
    )
    
    echo.
    echo ✓ ライブラリのインストールが完了しました！
    echo.
    timeout /t 2 > nul
)

REM 設定ファイル作成
if not exist "%CONFIG_FILE%" (
    if not exist "%SCRIPT_DIR%\config" mkdir "%SCRIPT_DIR%\config"
    "%PYTHON_EXE%" "%SCRIPT_DIR%\scripts\upload_to_spreadsheet.py" --save-config "%CONFIG_FILE%" > nul 2>&1
)

REM ===== GUIを起動 =====
"%PYTHON_EXE%" "%PYTHON_SCRIPT%"

if errorlevel 1 (
    echo.
    echo GUIの起動に失敗しました。
    pause
)
    echo.
    echo GUIの起動に失敗しました。
    pause
)
