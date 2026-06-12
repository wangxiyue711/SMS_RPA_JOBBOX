# SMS_RPA_JOBBOX

Next.js（App Router）の管理画面と、Python + Selenium のメール監視/自動送信ワーカー（Watcher）を含むプロジェクトです。

## セットアップ（Windows）

開発環境のセットアップ手順: `docs/dev-setup-ja.md`

Watcher を動かす（推奨）:

```bat
install_all_windows.cmd
run_watcher.cmd
```

Web（Next.js）を動かす:

```bash
npm install
npm run dev
```

※ `.env.local` はリポジトリ直下に作成してください。

## Indeed CSV アップロードツール

IndeedからダウンロードしたCSVファイルを応募管理表（Google Spreadsheet）に自動アップロードするGUIツールです。

### 初回セットアップ

1. **依存関係をインストール**
   ```bat
   install_indeed_uploader.cmd
   ```

2. **設定ファイルを編集**
   - `config/indeed_config.json` を開く
   - 以下の項目を設定：

   ```json
   {
     "enabled": true,                    // アップロード機能を有効化
     "spreadsheet_id": "YOUR_SHEET_ID",  // Google Spreadsheet ID
     "sheet_name": "管理表",              // シート名
     "csv_encoding": "utf-8-sig",        // CSV文字コード
     "default_values": {
       "進捗": "新規",                    // デフォルトのステータス
       "流入": "Indeed"                   // デフォルトの流入元
     },
     "skip_duplicates": true,            // 重複データをスキップ
     "duplicate_check_column": "アドレス" // 重複チェックに使う列
   }
   ```

3. **Spreadsheet ID の取得方法**
   - Google Spreadsheetを開く
   - URLから ID をコピー：
     ```
     https://docs.google.com/spreadsheets/d/【この部分がID】/edit
     ```

### 使い方

1. **GUIツールを起動**
   ```bat
   run_indeed_upload.cmd
   ```

2. **CSVファイルをアップロード**
   - 「📂 CSV ファイルを選択」ボタンでIndeed CSVを選択
   - データプレビューで内容を確認（最大10件表示）
   - 「🚀 アップロード実行」ボタンでアップロード開始

3. **設定の変更**
   - GUI内の「⚙️ 設定」ボタンから設定変更可能
   - Spreadsheet ID、シート名、重複チェック設定など

### 主な機能

- ✅ **自動データマッピング**: CSVの列を管理表の列に自動変換
- ✅ **重複チェック**: メールアドレスで重複を検出してスキップ
- ✅ **公式自動適用**: memo列や重複チェック列に自動で公式を挿入
- ✅ **デフォルト値設定**: 流入元やステータスに自動で値を設定
- ✅ **電話番号自動フォーマット**: `09037208502` → `090-3720-8502` に自動変換
- ✅ **リアルタイムログ**: アップロード進捗をリアルタイム表示
- ✅ **バッチ処理**: 複数行を一括アップロード
- ✅ **文字化け自動修復**: 複数のエンコーディングを自動検出（UTF-8, Shift-JIS, CP932など対応）

### CSV 文字化け対策

**完全自動対応！** ツールが自動的に正しいエンコーディングを検出します。

```json
"csv_encoding": "auto",  // 自動検出モード（推奨）
"encoding_fallbacks": [
  "utf-8-sig",   // Windows Excel
  "shift-jis",   // 日本語 Windows
  "cp932",       // Windows-31J
  "utf-8",       // Mac/Linux
  "iso-2022-jp", // JIS
  "euc-jp"       // Unix
]
```

- 📝 GUI上に検出されたエンコーディングが表示されます
- 🔍 プレビュー画面で文字化けを確認できます
- 📚 詳細は [CSV文字化け対策ガイド](docs/csv-encoding-guide.md) を参照

### カラムマッピング

`config/indeed_config.json` の `column_mapping` でCSV列とSpreadsheet列を対応付けます：

```json
"column_mapping": {
  "氏名": "名前",              // Indeed CSV「名前」→ Sheet「氏名」
  "アドレス": "メールアドレス",  // Indeed CSV「メールアドレス」→ Sheet「アドレス」
  "電話番号": "電話番号",       // そのまま対応
  "学歴": "学歴",              // そのまま対応
  "応募項目": "職歴名",         // Indeed CSV「職歴名」→ Sheet「応募項目」
  "転居備考": "勤務地",         // Indeed CSV「勤務地」→ Sheet「転居備考」
  "応募日": "日付",            // Indeed CSV「日付」→ Sheet「応募日」
  "備考": "応募者の質問連のある登録", // その他の情報を備考欄に
  "進捗": "",                  // 空欄 = default_values の値を使用
  "流入": "",                  // 空欄 = default_values の値を使用（"Indeed"）
  "担当CA": "",                // 空欄 = 手動入力用
  "B列(memo2)": "",            // 空欄 = 公式で自動計算
  "C列(memo3)": ""             // 空欄 = 公式で自動計算
}
```

### 公式の自動適用

設定ファイルの `formulas` セクションで、特定の列に自動的に公式を挿入できます：

```json
"formulas": {
  "C列(memo3)": "=COUNTIFS($K$3:$K{row},K{row},$L$3:$L{row},L{row})",
  "B列(memo2)": "=$K{row}&$L{row}&$C{row}",
  "重複": "=COUNTIF($AD:$AD,$AD{row})"
}
```

`{row}` は自動的に現在の行番号に置き換えられます。

### トラブルシューティング

**Q: アップロードボタンが無効のまま**
- A: `config/indeed_config.json` の `enabled` を `true` に設定してください

**Q: 認証エラーが発生する**
- A: `service-account/service-account` ファイルが正しく配置されているか確認してください

**Q: 重複データがスキップされない**
- A: `duplicate_check_column` の列名がSpreadsheetの列名と一致しているか確認してください

**Q: 公式が適用されない**
- A: `value_input_option` が `USER_ENTERED` になっていることを確認（自動設定）

## セキュリティの注意点

- service account JSON や `.env.local` は決して Git にコミットしないでください。誤ってコミットした場合、鍵をローテーションしてください。
