"""
Indeed CSV自動アップロードツール - GUI版
IndeedからダウンロードしたCSVファイルを応募管理表（Google Spreadsheet）に自動アップロードします。
"""

import sys
import os
import json
import csv
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
import traceback

# スクリプトのディレクトリをパスに追加
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir.parent / "src"))
sys.path.insert(0, str(script_dir))

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
    import threading
except ImportError:
    print("Error: tkinter がインストールされていません。")
    sys.exit(1)

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("Error: gspread または google-auth がインストールされていません。")
    print("インストール方法: pip install gspread google-auth")
    sys.exit(1)


def format_phone_number(phone: str) -> str:
    """
    电话番号をハイフン付き形式にフォーマットする。
    例: "09037208502" → "090-3720-8502"
        "+8109037208502" → "090-3720-8502"
    """
    if not phone:
        return ""
    
    # 数字以外を除去
    digits = re.sub(r'[^\d]', '', phone)
    
    # +81（日本の国際番号）を除去
    if digits.startswith('81') and len(digits) >= 12:
        digits = '0' + digits[2:]  # 81を除去して先頭に0を追加
    
    # 11桁の携帯電話番号（070/080/090で始まる）
    if len(digits) == 11 and digits[0:3] in ['070', '080', '090']:
        return f"{digits[0:3]}-{digits[3:7]}-{digits[7:11]}"
    
    # 10桁の固定電話番号
    elif len(digits) == 10:
        # 03, 06などの大都市の市外局番（2桁）
        if digits[0:2] in ['03', '04', '06']:
            return f"{digits[0:2]}-{digits[2:6]}-{digits[6:10]}"
        # その他の市外局番（3桁）
        else:
            return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    
    # 11桁のその他の番号
    elif len(digits) == 11:
        return f"{digits[0:3]}-{digits[3:7]}-{digits[7:11]}"
    
    # フォーマット不可の場合は元の値を返す
    return phone


def extract_prefecture(address: str) -> str:
    """
    住所から都道府県のみを抽出する。
    例: "東京都新宿区西新宿1-1-1" → "東京都"
        "神奈川県横浜市" → "神奈川県"
        "大阪府" → "大阪府"
    """
    if not address:
        return ""
    
    # 都道府県のリスト
    prefectures = [
        '北海道',
        '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
        '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
        '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県',
        '岐阜県', '静岡県', '愛知県', '三重県',
        '滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県',
        '鳥取県', '島根県', '岡山県', '広島県', '山口県',
        '徳島県', '香川県', '愛媛県', '高知県',
        '福岡県', '佐賀県', '長崎県', '熊本県', '大分県', '宮崎県', '鹿児島県',
        '沖縄県'
    ]
    
    # 住所から都道府県を抽出
    for prefecture in prefectures:
        if prefecture in address:
            return prefecture
    
    # 見つからない場合は元の値を返す
    return address


class ModernButton(tk.Button):
    """モダンなスタイルのボタン"""
    def __init__(self, parent, **kwargs):
        if "font" not in kwargs:
            kwargs["font"] = ("Yu Gothic UI", 10, "bold")
        
        super().__init__(
            parent,
            relief=tk.FLAT,
            borderwidth=0,
            cursor="hand2",
            **kwargs
        )
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        self.default_bg = kwargs.get("bg", "#2c2c2c")
        
    def on_enter(self, e):
        self.config(bg=self.lighten_color(self.default_bg))
        
    def on_leave(self, e):
        self.config(bg=self.default_bg)
    
    @staticmethod
    def lighten_color(color):
        """色を明るくする"""
        if color == "#2c2c2c":
            return "#4a4a4a"
        elif color == "#4a4a4a":
            return "#6a6a6a"
        elif color == "#6a6a6a":
            return "#8a8a8a"
        elif color == "#1a1a1a":
            return "#2c2c2c"
        return color


class IndeedUploadApp:
    """Indeed CSV アップロードアプリケーション"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Indeed CSV → 応募管理表 アップロードツール")
        self.root.geometry("800x700")
        self.root.configure(bg="#f5f5f5")
        
        # 設定ファイルのパス
        self.config_path = script_dir.parent / "config" / "indeed_config.json"
        self.config = self.load_config()
        
        # 選択されたファイル
        self.selected_file = None
        self.detected_encoding = None  # 検出されたエンコーディング
        
        # UI構築
        self.setup_ui()
        
        # 中央配置
        self.center_window()
    
    def detect_encoding(self, file_path: str) -> str:
        """CSVファイルのエンコーディングを自動検出"""
        config_encoding = self.config.get('csv_encoding', 'auto')
        
        # 設定で特定のエンコーディングが指定されている場合
        if config_encoding != 'auto' and config_encoding != '':
            return config_encoding
        
        # 試行するエンコーディングのリスト
        fallback_encodings = self.config.get('encoding_fallbacks', [
            'utf-8-sig', 'shift-jis', 'cp932', 'utf-8', 'iso-2022-jp', 'euc-jp'
        ])
        
        self.log("🔍 エンコーディング自動検出中...")
        
        for encoding in fallback_encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    # ファイル全体を読んでみる
                    content = f.read()
                    # 正常に読めたら、このエンコーディングを使用
                    if content and not any(c == '�' for c in content[:1000]):
                        self.log(f"✅ エンコーディング検出: {encoding}")
                        return encoding
            except (UnicodeDecodeError, UnicodeError, LookupError):
                continue
            except Exception as e:
                self.log(f"⚠️ {encoding} での読み込み失敗: {e}")
                continue
        
        # どれも失敗した場合はデフォルト
        self.log("⚠️ エンコーディング検出失敗、utf-8-sig を使用")
        return 'utf-8-sig'
    
    def read_csv_with_encoding(self, file_path: str, encoding: Optional[str] = None) -> List[Dict[str, str]]:
        """指定されたエンコーディングでCSVを読み込む"""
        if encoding is None:
            encoding = self.detect_encoding(file_path)
            self.detected_encoding = encoding
        
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            return rows
        except Exception as e:
            self.log(f"❌ CSV読み込みエラー ({encoding}): {e}")
            raise
    
    def center_window(self):
        """ウィンドウを画面中央に配置"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
    
    def setup_ui(self):
        """UI要素を作成"""
        # ヘッダー
        header_frame = tk.Frame(self.root, bg="#1a1a1a", height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        title_label = tk.Label(
            header_frame,
            text="📋 Indeed CSV アップローダー",
            font=("Yu Gothic UI", 18, "bold"),
            bg="#1a1a1a",
            fg="white"
        )
        title_label.pack(pady=20)
        
        # メインコンテンツエリア
        main_frame = tk.Frame(self.root, bg="#e8e8e8")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 設定情報
        info_frame = tk.LabelFrame(
            main_frame,
            text="📊 アップロード先設定",
            font=("Yu Gothic UI", 11, "bold"),
            bg="#ffffff",
            fg="#1a1a1a",
            relief=tk.FLAT,
            borderwidth=2
        )
        info_frame.pack(fill=tk.X, pady=(0, 15))
        
        info_inner = tk.Frame(info_frame, bg="#ffffff")
        info_inner.pack(fill=tk.X, padx=15, pady=10)
        
        # Spreadsheet ID
        tk.Label(
            info_inner,
            text=f"📄 Spreadsheet ID: {self.config.get('spreadsheet_id', 'NOT SET')}",
            font=("Yu Gothic UI", 9),
            bg="#ffffff",
            fg="#4a4a4a",
            anchor="w"
        ).pack(fill=tk.X, pady=2)
        
        # Sheet名
        tk.Label(
            info_inner,
            text=f"📝 シート名: {self.config.get('sheet_name', 'NOT SET')}",
            font=("Yu Gothic UI", 9),
            bg="#ffffff",
            fg="#4a4a4a",
            anchor="w"
        ).pack(fill=tk.X, pady=2)
        
        # ファイル選択エリア
        file_frame = tk.LabelFrame(
            main_frame,
            text="📁 CSV ファイル選択",
            font=("Yu Gothic UI", 11, "bold"),
            bg="#ffffff",
            fg="#1a1a1a",
            relief=tk.FLAT,
            borderwidth=2
        )
        file_frame.pack(fill=tk.X, pady=(0, 15))
        
        file_inner = tk.Frame(file_frame, bg="#ffffff")
        file_inner.pack(fill=tk.X, padx=15, pady=15)
        
        # ファイル選択ボタン
        select_btn = ModernButton(
            file_inner,
            text="📂 CSV ファイルを選択",
            command=self.select_file,
            bg="#2c2c2c",
            fg="white",
            padx=20,
            pady=12,
            font=("Yu Gothic UI", 11, "bold")
        )
        select_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # ファイル情報表示エリア
        file_info_frame = tk.Frame(file_inner, bg="#ffffff")
        file_info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # ファイル名表示
        self.file_label = tk.Label(
            file_info_frame,
            text="ファイルが選択されていません",
            font=("Yu Gothic UI", 10),
            bg="#ffffff",
            fg="#8a8a8a",
            anchor="w"
        )
        self.file_label.pack(fill=tk.X)
        
        # エンコーディング表示
        self.encoding_label = tk.Label(
            file_info_frame,
            text="",
            font=("Yu Gothic UI", 8),
            bg="#ffffff",
            fg="#4a4a4a",
            anchor="w"
        )
        self.encoding_label.pack(fill=tk.X)
        
        # プレビューエリア
        preview_frame = tk.LabelFrame(
            main_frame,
            text="👁️ データプレビュー (最大10件)",
            font=("Yu Gothic UI", 11, "bold"),
            bg="#ffffff",
            fg="#1a1a1a",
            relief=tk.FLAT,
            borderwidth=2
        )
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Treeview（テーブル）
        tree_frame = tk.Frame(preview_frame, bg="#ffffff")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # スクロールバー
        tree_scroll_y = tk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        tree_scroll_x = tk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        
        self.tree = ttk.Treeview(
            tree_frame,
            yscrollcommand=tree_scroll_y.set,
            xscrollcommand=tree_scroll_x.set,
            selectmode='browse',
            height=8
        )
        
        tree_scroll_y.config(command=self.tree.yview)
        tree_scroll_x.config(command=self.tree.xview)
        
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # アップロードボタン
        button_frame = tk.Frame(main_frame, bg="#e8e8e8")
        button_frame.pack(fill=tk.X)
        
        self.upload_btn = ModernButton(
            button_frame,
            text="🚀 アップロード実行",
            command=self.start_upload,
            bg="#2c2c2c",
            fg="white",
            padx=30,
            pady=15,
            font=("Yu Gothic UI", 12, "bold"),
            state=tk.DISABLED
        )
        self.upload_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # 設定ボタン
        config_btn = ModernButton(
            button_frame,
            text="⚙️ 設定",
            command=self.open_settings,
            bg="#4a4a4a",
            fg="white",
            padx=20,
            pady=15,
            font=("Yu Gothic UI", 11, "bold")
        )
        config_btn.pack(side=tk.LEFT)
        
        # ログエリア
        log_frame = tk.LabelFrame(
            main_frame,
            text="📝 ログ",
            font=("Yu Gothic UI", 11, "bold"),
            bg="#ffffff",
            fg="#1a1a1a",
            relief=tk.FLAT,
            borderwidth=2
        )
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(15, 0))
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            height=8,
            font=("Consolas", 9),
            bg="#f5f5f5",
            fg="#1a1a1a",
            relief=tk.FLAT,
            borderwidth=0
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 初期ログメッセージ
        self.log("✅ アプリケーションが起動しました")
        self.log("📂 CSV ファイルを選択してください")
    
    def load_config(self) -> Dict[str, Any]:
        """設定ファイルを読み込む"""
        if not self.config_path.exists():
            messagebox.showerror(
                "エラー",
                f"設定ファイルが見つかりません:\n{self.config_path}"
            )
            return {}
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            messagebox.showerror(
                "エラー",
                f"設定ファイルの読み込みに失敗しました:\n{e}"
            )
            return {}
    
    def select_file(self):
        """CSVファイルを選択"""
        file_path = filedialog.askopenfilename(
            title="Indeed CSV ファイルを選択",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialdir=os.path.expanduser("~/Downloads")
        )
        
        if file_path:
            self.selected_file = file_path
            self.file_label.config(
                text=os.path.basename(file_path),
                fg="#2c2c2c"
            )
            self.log(f"📁 ファイル選択: {os.path.basename(file_path)}")
            
            # プレビュー読み込み
            self.load_preview()
            
            # アップロードボタン有効化
            self.upload_btn.config(state=tk.NORMAL)
    
    def load_preview(self):
        """CSVファイルのプレビューを読み込む"""
        if not self.selected_file:
            return
        
        try:
            # Treeviewをクリア
            self.tree.delete(*self.tree.get_children())
            
            # CSVを読み込む（自動エンコーディング検出）
            rows = self.read_csv_with_encoding(self.selected_file)
            
            # エンコーディング情報を表示
            if self.detected_encoding:
                self.encoding_label.config(
                    text=f"📝 エンコーディング: {self.detected_encoding}",
                    fg="#2c2c2c"
                )
            
            if not rows:
                self.log("⚠️ CSVファイルが空です")
                return
            
            # カラム設定
            columns = list(rows[0].keys())
            self.tree['columns'] = columns
            self.tree['show'] = 'headings'
            
            for col in columns:
                self.tree.heading(col, text=col)
                self.tree.column(col, width=120, minwidth=80)
            
            # データ追加（最大10件）
            for row in rows[:10]:
                values = [row.get(col, '') for col in columns]
                self.tree.insert('', tk.END, values=values)
            
            self.log(f"✅ プレビュー読み込み完了: {len(rows)} 件中 {min(10, len(rows))} 件表示")
            
        except Exception as e:
            self.log(f"❌ プレビュー読み込みエラー: {e}")
            self.encoding_label.config(
                text="❌ 読み込み失敗",
                fg="#6a6a6a"
            )
            messagebox.showerror("エラー", f"CSVファイルの読み込みに失敗しました:\n{e}\n\nconfig/indeed_config.json の encoding_fallbacks を確認してください。")
    
    def log(self, message: str):
        """ログメッセージを追加"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def start_upload(self):
        """アップロード開始"""
        if not self.selected_file:
            messagebox.showwarning("警告", "CSVファイルを選択してください")
            return
        
        if not self.config.get('enabled', False):
            messagebox.showwarning(
                "警告",
                "アップロード機能が無効です。\n設定で有効化してください。"
            )
            return
        
        # 確認ダイアログ
        result = messagebox.askyesno(
            "確認",
            f"以下のファイルをアップロードしますか？\n\n{os.path.basename(self.selected_file)}\n\nアップロード先:\n{self.config.get('sheet_name', 'NOT SET')}"
        )
        
        if result:
            # バックグラウンドでアップロード実行
            self.upload_btn.config(state=tk.DISABLED)
            thread = threading.Thread(target=self.upload_process, daemon=True)
            thread.start()
    
    def upload_process(self):
        """アップロード処理（バックグラウンド）"""
        try:
            self.log("🚀 アップロード開始...")
            
            # CSVデータ読み込み（自動エンコーディング検出 or 検出済みエンコーディング使用）
            rows = self.read_csv_with_encoding(self.selected_file, self.detected_encoding)
            
            self.log(f"📊 データ読み込み完了: {len(rows)} 件")
            
            # Google Sheets認証
            self.log("🔐 Google Sheets 認証中...")
            client = self.authenticate_google_sheets()
            
            # Spreadsheet取得
            spreadsheet_id = self.config.get('spreadsheet_id')
            sheet_name = self.config.get('sheet_name', '応募管理表')
            
            spreadsheet = client.open_by_key(spreadsheet_id)
            worksheet = spreadsheet.worksheet(sheet_name)
            
            self.log(f"📝 シート接続成功: {sheet_name}")
            
            # 既存データ取得（重複チェック用）
            existing_data = []
            if self.config.get('skip_duplicates', True):
                try:
                    existing_data = worksheet.get_all_records()
                    self.log(f"📄 既存データ: {len(existing_data)} 件")
                except Exception as e:
                    # 表頭重複エラーを処理
                    if 'duplicates' in str(e):
                        self.log(f"⚠️ Spreadsheet の表頭に重複があります。重複チェックをスキップします。")
                        self.log(f"⚠️ 解決方法: Spreadsheet の1行目（列名）に重複がないか確認してください。")
                        # 重複チェックを無効化
                        existing_data = []
                    else:
                        raise
            else:
                self.log(f"📄 重複チェック: 無効")
            
            # カラムマッピング
            column_mapping = self.config.get('column_mapping', {})
            formulas = self.config.get('formulas', {})
            
            # アップロード準備（バッチ処理）
            success_count = 0
            skip_count = 0
            error_count = 0
            upload_batch = []  # バッチアップロード用のリスト
            names_to_upload = []  # ログ表示用の名前リスト
            
            self.log("📦 データ検証中...")
            
            # ステップ1: データ検証とバッチ準備
            for idx, row in enumerate(rows, 1):
                try:
                    # 姓名の空白チェック
                    name_csv_field = column_mapping.get('氏名', '名前')
                    name_value = row.get(name_csv_field, '').strip()
                    
                    if not name_value:
                        self.log(f"⏭️  [{idx}/{len(rows)}] スキップ（姓名が空白）")
                        skip_count += 1
                        continue
                    
                    # 重複チェック
                    if self.config.get('skip_duplicates', True):
                        duplicate_column = self.config.get('duplicate_check_column', 'メールアドレス')
                        csv_field = column_mapping.get(duplicate_column, duplicate_column)
                        check_value = row.get(csv_field, '').strip()
                        
                        if check_value and any(
                            str(existing.get(duplicate_column, '')).strip() == check_value
                            for existing in existing_data
                        ):
                            self.log(f"⏭️  [{idx}/{len(rows)}] スキップ（重複）: {check_value}")
                            skip_count += 1
                            continue
                    
                    # データ変換
                    upload_row = self.map_row_data(row, column_mapping)
                    upload_batch.append(upload_row)
                    names_to_upload.append(name_value)
                    
                except Exception as e:
                    self.log(f"❌ [{idx}/{len(rows)}] 検証エラー: {e}")
                    error_count += 1
            
            # ステップ2: 空白行を検出（K列の氏名を基準）
            start_row = 2  # デフォルトはヘッダーの次の行
            if upload_batch:
                try:
                    self.log("🔍 空白行を検出中...")
                    all_values = worksheet.get_all_values()
                    
                    # K列（氏名列、インデックス10）が最初に空白になる行を見つける
                    K_COLUMN_INDEX = 10  # K列は11列目（0-indexed で10）
                    
                    for i, row in enumerate(all_values, start=1):
                        if i == 1:  # ヘッダー行はスキップ
                            continue
                        
                        # K列が空白かチェック
                        k_value = row[K_COLUMN_INDEX] if len(row) > K_COLUMN_INDEX else ""
                        if not k_value.strip():
                            start_row = i
                            self.log(f"✅ 空白行を検出: K列（氏名）が空白の行 → 行{start_row}")
                            break
                    else:
                        # すべての行にK列データがある場合、最後の行の次に追記
                        start_row = len(all_values) + 1
                        self.log(f"✅ 空白行を検出: すべての行にデータあり → 最終行の次（行{start_row}）から追記")
                    
                except Exception as e:
                    self.log(f"⚠️ 空白行検出エラー（デフォルト位置を使用）: {e}")
                    start_row = 2
            
            # ステップ3: バッチアップロード（空白行から開始）
            if upload_batch:
                try:
                    self.log(f"📤 バッチアップロード開始: {len(upload_batch)} 件（行{start_row}から）")
                    start_cell = f"A{start_row}"
                    worksheet.update(values=upload_batch, range_name=start_cell, value_input_option='USER_ENTERED')
                    success_count = len(upload_batch)
                    
                    # 各行の名前をログ出力
                    for idx, name in enumerate(names_to_upload, 1):
                        self.log(f"✅ [{idx}/{len(names_to_upload)}] アップロード成功: {name}")
                    
                except Exception as e:
                    self.log(f"❌ バッチアップロードエラー: {e}")
                    error_count = len(upload_batch)
                    success_count = 0
            
            # ステップ4: 公式を一括適用
            if success_count > 0 and formulas:
                try:
                    self.log("📝 公式を一括適用中...")
                    self.apply_formulas_batch(worksheet, formulas, start_row, success_count, column_mapping)
                    self.log("✅ 公式適用完了")
                except Exception as e:
                    self.log(f"⚠️ 公式適用エラー: {e}")
                    # 公式エラーは致命的ではないので続行
            
            # 完了メッセージ
            self.log("=" * 50)
            self.log(f"🎉 アップロード完了!")
            self.log(f"   ✅ 成功: {success_count} 件")
            self.log(f"   ⏭️  スキップ: {skip_count} 件")
            self.log(f"   ❌ エラー: {error_count} 件")
            self.log("=" * 50)
            
            messagebox.showinfo(
                "完了",
                f"アップロードが完了しました！\n\n成功: {success_count} 件\nスキップ: {skip_count} 件\nエラー: {error_count} 件"
            )
            
        except Exception as e:
            self.log(f"❌ 致命的エラー: {e}")
            self.log(traceback.format_exc())
            messagebox.showerror("エラー", f"アップロードに失敗しました:\n{e}")
        
        finally:
            self.upload_btn.config(state=tk.NORMAL)
    
    def authenticate_google_sheets(self):
        """Google Sheets認証"""
        sa_path = self.config.get('service_account_path', 'service-account/service-account')
        
        if not os.path.isabs(sa_path):
            sa_path = str(script_dir.parent / sa_path)
        
        if not os.path.exists(sa_path):
            raise FileNotFoundError(f"サービスアカウントファイルが見つかりません: {sa_path}")
        
        with open(sa_path, "r", encoding="utf-8") as f:
            sa_info = json.load(f)
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        return gspread.authorize(creds)
    
    def apply_formulas(self, worksheet, formulas: Dict[str, str], row_number: int, column_mapping: Dict[str, str]):
        """指定された行に公式を適用（旧方式 - 互換性のため保持）"""
        try:
            # 列名からアルファベット列インデックスを取得
            sheet_columns = list(column_mapping.keys())
            
            for col_name, formula_template in formulas.items():
                if col_name in sheet_columns:
                    col_index = sheet_columns.index(col_name)
                    col_letter = self.get_column_letter(col_index)
                    
                    # 公式テンプレートの {row} を実際の行番号に置き換え
                    formula = formula_template.replace('{row}', str(row_number))
                    
                    # セルに公式を書き込み（新しいAPI形式）
                    cell_address = f"{col_letter}{row_number}"
                    worksheet.update(values=[[formula]], range_name=cell_address, value_input_option='USER_ENTERED')
                    
        except Exception as e:
            self.log(f"⚠️ 公式適用エラー（行{row_number}）: {e}")
    
    def apply_formulas_batch(self, worksheet, formulas: Dict[str, str], start_row: int, row_count: int, column_mapping: Dict[str, str]):
        """複数行に公式を一括適用（バッチ処理）"""
        try:
            sheet_columns = list(column_mapping.keys())
            
            # 各公式列について、全行分のセル範囲とデータを準備
            for col_name, formula_template in formulas.items():
                if col_name in sheet_columns:
                    col_index = sheet_columns.index(col_name)
                    col_letter = self.get_column_letter(col_index)
                    
                    # この列の全行分の公式を生成
                    formulas_list = []
                    for i in range(row_count):
                        row_number = start_row + i
                        formula = formula_template.replace('{row}', str(row_number))
                        formulas_list.append([formula])
                    
                    # セル範囲を指定して一括更新
                    range_name = f"{col_letter}{start_row}:{col_letter}{start_row + row_count - 1}"
                    worksheet.update(values=formulas_list, range_name=range_name, value_input_option='USER_ENTERED')
                    self.log(f"  📐 {col_name} に公式を適用: {range_name}")
                    
        except Exception as e:
            self.log(f"⚠️ バッチ公式適用エラー: {e}")
    
    def get_column_letter(self, col_index: int) -> str:
        """列インデックスからExcelのアルファベット列名を取得（0-based）"""
        result = ""
        col_index += 1  # 1-based に変換
        while col_index > 0:
            col_index -= 1
            result = chr(col_index % 26 + ord('A')) + result
            col_index //= 26
        return result
    
    def map_row_data(self, csv_row: Dict[str, str], column_mapping: Dict[str, str]) -> List[str]:
        """CSVの行データをSpreadsheetの形式にマッピング"""
        # Spreadsheetのカラム順序（設定ファイルのcolumn_mappingの順序）
        sheet_columns = list(column_mapping.keys())
        default_values = self.config.get('default_values', {})
        formulas = self.config.get('formulas', {})
        
        mapped_row = []
        for sheet_col in sheet_columns:
            # 公式列の場合は空欄のまま（後で公式が適用される）
            if sheet_col in formulas:
                mapped_row.append('')
                continue
            
            csv_col = column_mapping.get(sheet_col, '')
            
            if not csv_col:
                # 空のマッピング
                # 1. デフォルト値があればそれを使用
                if sheet_col in default_values:
                    mapped_row.append(default_values[sheet_col])
                # 2. 旧バージョン互換性（ステータス列）
                elif sheet_col == 'ステータス':
                    mapped_row.append(self.config.get('default_status', '新規'))
                # 3. 完全に空白
                else:
                    mapped_row.append('')
            else:
                # CSVから値を取得
                value = csv_row.get(csv_col, '').strip()
                
                # 電話番号の場合はフォーマット
                if '電話番号' in sheet_col or 'tel' in sheet_col.lower():
                    value = format_phone_number(value)
                
                # 居住地の場合は都道府県のみ抽出
                if '居住地' in sheet_col:
                    value = extract_prefecture(value)
                
                mapped_row.append(value)
        
        return mapped_row
    
    def open_settings(self):
        """設定ダイアログを開く"""
        SettingsDialog(self.root, self.config_path, callback=self.reload_config)
    
    def reload_config(self):
        """設定を再読み込み"""
        self.config = self.load_config()
        self.log("⚙️ 設定を再読み込みしました")
        self.setup_ui()


class SettingsDialog(tk.Toplevel):
    """設定ダイアログ"""
    
    def __init__(self, parent, config_path, callback=None):
        super().__init__(parent)
        self.title("設定")
        self.geometry("600x320")
        self.configure(bg="#e8e8e8")
        self.resizable(False, False)
        
        self.config_path = config_path
        self.callback = callback
        
        # モーダル設定
        self.transient(parent)
        self.grab_set()
        
        self.setup_ui()
        self.load_current_config()
        
        # 中央配置
        self.center_window()
    
    def center_window(self):
        """ウィンドウを画面中央に配置"""
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
    
    def setup_ui(self):
        """UI構築"""
        # ヘッダー
        header_frame = tk.Frame(self, bg="#1a1a1a", height=60)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        tk.Label(
            header_frame,
            text="⚙️ Indeed CSV アップロード設定",
            font=("Yu Gothic UI", 16, "bold"),
            bg="#1a1a1a",
            fg="white"
        ).pack(pady=15)
        
        # メインフレーム
        main_frame = tk.Frame(self, bg="#e8e8e8")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Spreadsheet設定
        sheet_frame = tk.LabelFrame(
            main_frame,
            text="📊 Google Spreadsheet",
            font=("Yu Gothic UI", 10, "bold"),
            bg="#ffffff",
            fg="#1a1a1a"
        )
        sheet_frame.pack(fill=tk.X, pady=(0, 10))
        
        sheet_inner = tk.Frame(sheet_frame, bg="#ffffff")
        sheet_inner.pack(fill=tk.X, padx=15, pady=10)
        
        # Spreadsheet ID
        tk.Label(
            sheet_inner,
            text="Spreadsheet ID:",
            font=("Yu Gothic UI", 9),
            bg="#ffffff"
        ).grid(row=0, column=0, sticky=tk.W, pady=5)
        
        self.spreadsheet_id_entry = tk.Entry(
            sheet_inner,
            font=("Yu Gothic UI", 9),
            width=50
        )
        self.spreadsheet_id_entry.grid(row=0, column=1, sticky=tk.EW, pady=5, padx=(10, 0))
        
        # Sheet名
        tk.Label(
            sheet_inner,
            text="シート名:",
            font=("Yu Gothic UI", 9),
            bg="#ffffff"
        ).grid(row=1, column=0, sticky=tk.W, pady=5)
        
        self.sheet_name_entry = tk.Entry(
            sheet_inner,
            font=("Yu Gothic UI", 9),
            width=50
        )
        self.sheet_name_entry.grid(row=1, column=1, sticky=tk.EW, pady=5, padx=(10, 0))
        
        sheet_inner.columnconfigure(1, weight=1)
        
        # ボタン
        button_frame = tk.Frame(main_frame, bg="#e8e8e8")
        button_frame.pack(fill=tk.X, pady=(20, 0))
        
        ModernButton(
            button_frame,
            text="💾 保存",
            command=self.save_config,
            bg="#2c2c2c",
            fg="white",
            padx=30,
            pady=12,
            font=("Yu Gothic UI", 11, "bold")
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ModernButton(
            button_frame,
            text="❌ キャンセル",
            command=self.destroy,
            bg="#6a6a6a",
            fg="white",
            padx=30,
            pady=12,
            font=("Yu Gothic UI", 11, "bold")
        ).pack(side=tk.LEFT)
    
    def load_current_config(self):
        """現在の設定を読み込んで表示"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            self.spreadsheet_id_entry.insert(0, config.get('spreadsheet_id', ''))
            self.sheet_name_entry.insert(0, config.get('sheet_name', '管理表'))
            
        except Exception as e:
            messagebox.showerror("エラー", f"設定の読み込みに失敗しました:\n{e}")
    
    def save_config(self):
        """設定を保存"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 更新
            config['spreadsheet_id'] = self.spreadsheet_id_entry.get().strip()
            config['sheet_name'] = self.sheet_name_entry.get().strip()
            
            # 保存
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            
            messagebox.showinfo("成功", "設定を保存しました")
            
            # コールバック実行
            if self.callback:
                self.callback()
            
            self.destroy()
            
        except Exception as e:
            messagebox.showerror("エラー", f"設定の保存に失敗しました:\n{e}")


def main():
    """メイン関数"""
    root = tk.Tk()
    app = IndeedUploadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
