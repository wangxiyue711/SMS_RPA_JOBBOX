@echo off
chcp 65001 >nul
title Indeed CSV アップロードツール - 依存関係インストール

echo ========================================
echo Indeed CSV アップローダー - セットアップ
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

echo 必要なパッケージをインストールしています...
echo.

python -m pip install --upgrade pip
python -m pip install gspread google-auth

echo.
echo ========================================
echo ✅ インストール完了！
echo ========================================
echo.
echo 次のステップ:
echo 1. config\indeed_config.json を開く
echo 2. spreadsheet_id を設定
echo 3. enabled を true に設定
echo 4. run_indeed_upload.cmd を実行
echo.
pause
