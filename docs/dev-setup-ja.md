# 開発環境セットアップガイド（Windows）

対象: このリポジトリを **ローカルPC(Windows)** で動かし、

- Web管理画面（Next.js）
- 監視/送信ワーカー（Python + Selenium）
  を開発・動作確認できる状態にします。

---

## 1. 前提（インストールしておくもの）

- Windows 10/11
- Git
- Node.js: `22.x`（package.json の engines に合わせる）
- Python: 3.10+（`install_all_windows.cmd` が `python` を利用）
- Google Chrome（Seleniumで使用）
- （推奨）VS Code

### Node のバージョンについて

- `node -v` が `v22.*` になるように揃えてください。
- 複数バージョンを使う場合は nvm-windows を使うのがおすすめです。

---

## 2. リポジトリ取得

```powershell
cd C:\work
git clone <your-repo-url>
cd SMS_RPA_JOBBOX
```

---

## 3. サービスアカウント（Firestoreアクセス）

このRPAは Firestore を REST API 経由で読み書きするため、**サービスアカウントJSON** が必要です。

### 配置場所

以下のどれかに JSON を配置してください（どれか1つでOK）:

- `src/service-account`（推奨: 実装がこのパスを検出します）
- `service-account/service-account`（インストーラがフォルダ存在チェックをします）

> 注意: Gitに絶対コミットしないでください。

---

## 4. Python 依存関係（Watcher）

### 4.1 ワンクリック（推奨）

```bat
install_all_windows.cmd
```

このスクリプトが以下を行います:

- `.venv` 作成
- `requirements.txt` と `webdriver-manager` のインストール
- `run_watcher.cmd` の生成/更新

### 4.2 手動でやる場合

```powershell
python -m venv .venv
.\.venv\Scripts\pip.exe install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\pip.exe install webdriver-manager
```

---

## 5. Web（Next.js）依存関係

```powershell
npm install
```

### 5.1 `.env.local`（Webログイン/Firebase）

ルートに `.env.local` を作成し、Firebase Web App の値を設定してください。

最低限（クライアント側）:

- `NEXT_PUBLIC_FIREBASE_API_KEY`
- `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
- `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
- `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
- `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`
- `NEXT_PUBLIC_FIREBASE_APP_ID`

サーバー側（Admin SDK を使うAPIがある場合）:

- `FIREBASE_PROJECT_ID`
- `FIREBASE_CLIENT_EMAIL`
- `FIREBASE_PRIVATE_KEY`（`\n` を実改行に変換して使います）

---

## 6. Firestore 側に入れる設定（重要）

Watcher は基本的に Firestore から設定を読みます。

最低限必要になりやすいドキュメント:

- `accounts/{uid}/mail_settings/settings`
  - `email`（監視するGmail）
  - `appPass`（Gmailのアプリパスワード 16桁）
  - （任意）`replyEmail`, `replyAppPass`
- `accounts/{uid}/engage_mail_settings/settings`
  - `email`, `appPass`
- `accounts/{uid}/api_settings/settings`
  - `provider`, `baseUrl`, `apiId`, `apiPass`, `auth` など
- `accounts/{uid}/target_settings/settings`
  - SMSテンプレ、AB設定、セグメント条件など

> どれが不足しているかは、Watcher 起動時にコンソールに不足メッセージが出ます。

---

## 7. Watcher の起動（メール監視 + 自動送信）

### 7.1 推奨起動方法（自動再起動付き）

```bat
run_watcher.cmd
```

起動後に:

- UID を入力
- 監視間隔（秒）を入力（デフォルト30）

### 7.2 直接起動（デバッグ向け）

```powershell
.\.venv\Scripts\python.exe -u src\email_watcher.py --uid <UID> --interval 30
```

---

## 8. Web 管理画面の起動

```powershell
npm run dev
```

ブラウザで `http://localhost:3000` を開きます。

---

## 9. Dry-run（実送信しない安全モード）

テスト中に実際の送信を止めたい場合:

- SMS: `DRY_RUN_SMS=true`
- MAIL: `DRY_RUN_MAIL=true`

例（cmd）:

```bat
set DRY_RUN_SMS=true
set DRY_RUN_MAIL=true
run_watcher.cmd
```

---

## 10. 定時送信（scheduled_tasks）だけを動かす

Watcher 本体もスレッドで定時送信を回しますが、単独で回したい場合:

```powershell
.\.venv\Scripts\python.exe scripts\scheduled_dispatcher.py <UID>
```

---

## 11. よくあるトラブルシュート

- **service account が見つからない**
  - `src/service-account` に JSON があるか確認
- **Gmail でログインできない / IMAPが弾かれる**
  - Gmail 側で IMAP を有効化
  - 2段階認証ON → アプリパスワード(16桁)を使用
  - `Account exceeded command or bandwidth limits` が出る場合: IMAP を短時間に叩きすぎて一時的に制限されています
    - しばらく待ってから再実行（数分〜）
    - Watcher を二重起動していないか確認（同じメールに対して複数プロセス/端末が同時接続すると悪化）
    - 監視間隔を上げる（例: `--interval 120`）
    - 退避時間は `RPA_IMAP_RECONNECT_MAX_SECONDS` / `RPA_IMAP_RECONNECT_BASE_SECONDS` で調整可能
- **Selenium が起動しない**
  - Chrome がインストールされているか
  - 企業端末のポリシーで WebDriver がブロックされていないか
- **SMSが送れない**
  - `accounts/{uid}/api_settings/settings` の `baseUrl`/認証を確認
  - まず `DRY_RUN_SMS=true` でリクエスト構築だけ確認
