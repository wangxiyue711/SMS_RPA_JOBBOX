# Indeed CSV アップローダー 配布ガイド

## 📦 配布用フォルダ構成

他の人にIndeed CSV アップローダーを提供する際は、以下のファイルのみを送付してください：

```
indeed_uploader/                    # 配布用フォルダ（任意の名前でOK）
│
├── scripts/
│   └── indeed_upload_gui.py       # ✅ メインプログラム（必須）
│
├── config/
│   └── indeed_config.json         # ✅ 設定ファイル（必須）
│
├── service-account/
│   └── service-account            # ✅ Google認証ファイル（必須）
│
├── run_indeed_upload.cmd          # ✅ 起動スクリプト（必須）
├── install_indeed_uploader.cmd    # ✅ インストールスクリプト（推奨）
│
└── docs/                          # 📚 ドキュメント（推奨）
    ├── indeed-upload-guide.md     # 使用説明書
    └── csv-encoding-guide.md      # CSV文字化け対応ガイド
```

## ✅ 必須ファイル（4つ）

### 1. **scripts/indeed_upload_gui.py**
- メインのGUIプログラム
- サイズ: 約30KB
- 内容: Python GUIアプリケーション本体

### 2. **config/indeed_config.json**
- 設定ファイル（カラムマッピング、公式など）
- サイズ: 約2KB
- 内容: Spreadsheet ID、カラムマッピング、デフォルト値

### 3. **service-account/service-account**
- Google Sheets API認証用のJSONファイル
- サイズ: 約2KB
- ⚠️ **重要**: このファイルは機密情報です。信頼できる人にのみ送付してください

### 4. **run_indeed_upload.cmd**
- プログラム起動用バッチファイル
- サイズ: 約1KB
- 内容: Pythonチェック＋GUIアプリ起動

## 📋 推奨ファイル（3つ）

### 5. **install_indeed_uploader.cmd**
- 依存パッケージのインストールスクリプト
- サイズ: 約1KB
- 用途: 初回セットアップ時に実行

### 6. **docs/indeed-upload-guide.md**
- 使用方法の詳細ガイド
- サイズ: 約8KB
- 内容: 初期設定、使い方、FAQ

### 7. **docs/csv-encoding-guide.md**
- CSV文字化け問題の対応ガイド
- サイズ: 約5KB
- 内容: エンコーディング説明、トラブルシューティング

## 📤 配布手順

### ステップ1: フォルダを作成

```bash
# 新しいフォルダを作成
mkdir indeed_uploader
```

### ステップ2: 必須ファイルをコピー

```bash
# フォルダ構造を作成
mkdir indeed_uploader\scripts
mkdir indeed_uploader\config
mkdir indeed_uploader\service-account
mkdir indeed_uploader\docs

# ファイルをコピー
copy scripts\indeed_upload_gui.py indeed_uploader\scripts\
copy config\indeed_config.json indeed_uploader\config\
copy service-account\service-account indeed_uploader\service-account\
copy run_indeed_upload.cmd indeed_uploader\
copy install_indeed_uploader.cmd indeed_uploader\
copy docs\indeed-upload-guide.md indeed_uploader\docs\
copy docs\csv-encoding-guide.md indeed_uploader\docs\
```

### ステップ3: ZIPファイルを作成

```bash
# PowerShellを使用してZIP圧縮
Compress-Archive -Path indeed_uploader -DestinationPath indeed_uploader.zip
```

### ステップ4: 配布

- **indeed_uploader.zip** を相手に送付
- または、**indeed_uploader** フォルダごと共有

## 🚀 受け取った側の使用手順

### 初回セットアップ（1回のみ）

1. **ZIPを解凍**
   ```
   indeed_uploader.zip を右クリック → すべて展開
   ```

2. **Pythonをインストール**（未インストールの場合）
   - Python 3.8以上が必要
   - https://www.python.org/downloads/ からダウンロード
   - インストール時に「Add Python to PATH」にチェック

3. **依存パッケージをインストール**
   ```
   install_indeed_uploader.cmd をダブルクリック
   ```
   - gspread と google-auth がインストールされます

### 毎回の使用方法

1. **プログラムを起動**
   ```
   run_indeed_upload.cmd をダブルクリック
   ```

2. **CSVファイルを選択してアップロード**
   - GUIで操作するだけ

## ⚠️ 注意事項

### セキュリティ

- **service-account** ファイルは機密情報です
- Google Sheetsへのフルアクセス権限を持っています
- 信頼できる人にのみ配布してください
- 不要になったら削除してください

### Spreadsheet ID

- **config/indeed_config.json** 内のSpreadsheet IDは配布先の環境に合わせて変更可能です
- 各ユーザーが自分のスプレッドシートにアップロードしたい場合は、設定画面から変更できます

### Python環境

- Python 3.8以上が必要
- WindowsのPATHにPythonが登録されている必要があります
- `python --version` コマンドで確認可能

## 📊 合計サイズ

- **必須ファイルのみ**: 約35KB（service-accountを除く）
- **推奨ファイル含む**: 約50KB（service-accountを除く）
- **ZIP圧縮後**: 約15-20KB

非常に軽量なので、メールやチャットで簡単に送付できます。

## 🔄 更新時の対応

プログラムを更新した場合：

1. **indeed_upload_gui.py** のみを差し替え
2. 設定変更があれば **indeed_config.json** も差し替え
3. 他のファイルは通常変更不要

## 📝 カスタマイズ

配布前に以下をカスタマイズすることも可能：

### config/indeed_config.json

```json
{
  "spreadsheet_id": "受け取り側のスプレッドシートID",
  "sheet_name": "管理表",
  "default_values": {
    "進捗": "",
    "流入": "indeed"
  }
}
```

### サービスアカウント

- 各ユーザーが独自のGoogle Cloud Projectを持っている場合
- それぞれのservice-accountファイルを使用可能

## 🎯 まとめ

**最小構成（4ファイル）**:
```
✅ scripts/indeed_upload_gui.py
✅ config/indeed_config.json
✅ service-account/service-account
✅ run_indeed_upload.cmd
```

**推奨構成（+3ファイル）**:
```
📋 install_indeed_uploader.cmd
📚 docs/indeed-upload-guide.md
📚 docs/csv-encoding-guide.md
```

これらのファイルをフォルダにまとめて配布すれば、受け取った人はすぐに使用開始できます！
