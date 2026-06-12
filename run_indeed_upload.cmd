@echo off
chcp 65001 >nul
title Indeed CSV アップロードツール

echo ========================================
echo Indeed CSV → 応募管理表 アップロード
echo ========================================
echo.

REM Pythonが利用可能か確認
python --version >nul 2>&1
if errorlevel 1 (
    echo エラー: Python が見つかりません
    echo.
    echo Python をインストールするか、PATH に追加してください。
    echo ダウンロード: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Python バージョン:
python --version
echo.

REM スクリプトを実行
echo GUIを起動しています...
python "%~dp0scripts\indeed_upload_gui.py"

if errorlevel 1 (
    echo.
    echo エラーが発生しました。
    pause
)
