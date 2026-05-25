"""
CSV履歴データをGoogle Spreadsheetにアップロード - GUI版
ファイル選択ダイアログでCSVを手動選択してアップロードします。
"""

import sys
import os
import json
from pathlib import Path
import traceback

# スクリプトのディレクトリをパスに追加
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext, ttk
    import threading
except ImportError:
    print("Error: tkinter がインストールされていません。")
    sys.exit(1)

# 元のアップロードスクリプトをインポート
try:
    from upload_to_spreadsheet import (
        load_config,
        read_csv_file,
        apply_filters,
        map_columns,
        upload_to_spreadsheet,
        load_service_account,
    )
except ImportError as e:
    print(f"Error: upload_to_spreadsheet.py のインポートに失敗しました: {e}")
    sys.exit(1)


class ModernButton(tk.Button):
    """モダンなスタイルのボタン"""
    def __init__(self, parent, **kwargs):
        # デフォルトフォント設定
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
        self.default_bg = kwargs.get("bg", "#2196F3")
        
    def on_enter(self, e):
        self.config(bg=self.lighten_color(self.default_bg))
        
    def on_leave(self, e):
        self.config(bg=self.default_bg)
    
    @staticmethod
    def lighten_color(color):
        """色を明るくする"""
        colors = {
            "#000000": "#333333",
            "#ffffff": "#f0f0f0",
        }
        return colors.get(color, color)


class SettingsDialog(tk.Toplevel):
    """設定ダイアログ"""
    def __init__(self, parent, config_path):
        super().__init__(parent)
        self.title("設定")
        self.geometry("650x500")
        self.configure(bg="#f5f5f5")
        self.resizable(False, False)
        
        self.config_path = config_path
        self.result = None
        
        # モーダル設定
        self.transient(parent)
        self.grab_set()
        
        self.setup_ui()
        self.load_current_config()
        
        # 中央配置
        self.update_idletasks()
        x = (self.winfo_screenwidth() // 2) - (self.winfo_width() // 2)
        y = (self.winfo_screenheight() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")
    
    def setup_ui(self):
        # タイトル
        title_frame = tk.Frame(self, bg="#000000", height=60)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)
        
        title_label = tk.Label(
            title_frame,
            text="⚙️ アップロード設定",
            font=("Yu Gothic UI", 14, "bold"),
            bg="#000000",
            fg="#ffffff",
            pady=15
        )
        title_label.pack()
        
        # メインフレーム
        main_frame = tk.Frame(self, bg="white", padx=30, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Spreadsheet URL/ID
        tk.Label(
            main_frame,
            text="Spreadsheet URL または ID:",
            font=("Yu Gothic UI", 10, "bold"),
            bg="white",
            anchor="w"
        ).pack(fill=tk.X, pady=(0, 5))
        
        self.url_entry = tk.Entry(
            main_frame,
            font=("Yu Gothic UI", 10),
            relief=tk.SOLID,
            borderwidth=1
        )
        self.url_entry.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(
            main_frame,
            text="💡 例: https://docs.google.com/spreadsheets/d/1ABC.../edit",
            font=("Yu Gothic UI", 8),
            fg="#666",
            bg="white",
            anchor="w"
        ).pack(fill=tk.X, pady=(0, 15))
        
        # シート名
        tk.Label(
            main_frame,
            text="シート名:",
            font=("Yu Gothic UI", 10, "bold"),
            bg="white",
            anchor="w"
        ).pack(fill=tk.X, pady=(0, 5))
        
        self.sheet_entry = tk.Entry(
            main_frame,
            font=("Yu Gothic UI", 10),
            relief=tk.SOLID,
            borderwidth=1
        )
        self.sheet_entry.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(
            main_frame,
            text="💡 例: 管理表, データ, Sheet1",
            font=("Yu Gothic UI", 8),
            fg="#666",
            bg="white",
            anchor="w"
        ).pack(fill=tk.X, pady=(0, 15))
        
        # ボタン
        btn_frame = tk.Frame(self, bg="#f5f5f5")
        btn_frame.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        cancel_btn = ModernButton(
            btn_frame,
            text="キャンセル",
            command=self.cancel,
            bg="#ffffff",
            fg="#000000",
            padx=30,
            pady=10,
            width=12
        )
        cancel_btn.pack(side=tk.RIGHT, padx=5)
        
        save_btn = ModernButton(
            btn_frame,
            text="保存",
            command=self.save,
            bg="#000000",
            fg="white",
            padx=30,
            pady=10,
            width=12
        )
        save_btn.pack(side=tk.RIGHT, padx=5)
    
    def load_current_config(self):
        """現在の設定を読み込む"""
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                # Spreadsheet ID を入力
                self.url_entry.insert(0, config.get("spreadsheet_id", ""))
                
                # シート名を入力
                self.sheet_entry.insert(0, config.get("sheet_name", "管理表"))
        except:
            pass
    
    def extract_spreadsheet_id(self, url_or_id):
        """URLからSpreadsheet IDを抽出"""
        url_or_id = url_or_id.strip()
        
        # すでにIDの形式の場合
        if "/" not in url_or_id and len(url_or_id) > 30:
            return url_or_id
        
        # URLからIDを抽出
        import re
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', url_or_id)
        if match:
            return match.group(1)
        
        return url_or_id
    
    def save(self):
        """設定を保存"""
        url_or_id = self.url_entry.get().strip()
        sheet_name = self.sheet_entry.get().strip()
        
        if not url_or_id:
            messagebox.showwarning("警告", "Spreadsheet URLまたはIDを入力してください。")
            return
        
        if not sheet_name:
            messagebox.showwarning("警告", "シート名を入力してください。")
            return
        
        try:
            # Spreadsheet IDを抽出
            spreadsheet_id = self.extract_spreadsheet_id(url_or_id)
            
            # 現在の設定を読み込む
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            else:
                from upload_to_spreadsheet import DEFAULT_CONFIG
                config = DEFAULT_CONFIG.copy()
            
            # 更新
            config["spreadsheet_id"] = spreadsheet_id
            config["sheet_name"] = sheet_name
            
            # 保存
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            self.result = True
            self.destroy()
            
        except Exception as e:
            messagebox.showerror("エラー", f"設定の保存に失敗しました:\n{e}")
    
    def cancel(self):
        """キャンセル"""
        self.result = False
        self.destroy()


class UploadApp:
    def __init__(self, root):
        self.root = root
        self.root.title("CSV履歴アップローダー")
        self.root.geometry("900x700")
        self.root.configure(bg="#f5f5f5")
        
        # アイコン設定（オプション）
        try:
            self.root.iconbitmap(default="icon.ico")
        except:
            pass
        
        # 設定ファイルのパス
        self.config_path = script_dir.parent / "config" / "upload_config.json"
        self.csv_file = None
        self.is_processing = False
        
        # フィルタ設定変数
        self.filter_kanji = tk.BooleanVar(value=True)
        self.filter_katakana = tk.BooleanVar(value=True)
        self.filter_hiragana = tk.BooleanVar(value=True)
        self.filter_alphabet = tk.BooleanVar(value=True)
        
        self.male_age_min = tk.StringVar(value="18")
        self.male_age_max = tk.StringVar(value="99")
        self.female_age_min = tk.StringVar(value="18")
        self.female_age_max = tk.StringVar(value="99")
        
        # 起始行号
        self.start_row = tk.StringVar(value="")
        
        self.setup_ui()
        self.load_gui_filters()  # 設定を読み込む
        
    def setup_ui(self):
        # ヘッダー
        header_frame = tk.Frame(self.root, bg="#000000", height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        title_label = tk.Label(
            header_frame,
            text="📊 CSV履歴データ → Spreadsheet",
            font=("Yu Gothic UI", 18, "bold"),
            bg="#000000",
            fg="#ffffff",
            pady=20
        )
        title_label.pack()
        
        # 設定ボタン（ヘッダー内）
        settings_btn = tk.Button(
            header_frame,
            text="⚙️ 設定",
            command=self.open_settings,
            bg="#ffffff",
            fg="#000000",
            font=("Yu Gothic UI", 9, "bold"),
            relief=tk.FLAT,
            borderwidth=0,
            cursor="hand2",
            padx=15,
            pady=5
        )
        settings_btn.place(relx=0.95, rely=0.5, anchor="e")
        
        # メインコンテナ
        main_container = tk.Frame(self.root, bg="#f5f5f5")
        main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # ステップ1: ファイル選択
        step1_frame = tk.LabelFrame(
            main_container,
            text="  ステップ 1: CSVファイルを選択  ",
            font=("Yu Gothic UI", 11, "bold"),
            bg="white",
            fg="#333",
            padx=20,
            pady=15
        )
        step1_frame.pack(fill=tk.X, pady=(0, 15))
        
        file_info_frame = tk.Frame(step1_frame, bg="white")
        file_info_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.file_label = tk.Label(
            file_info_frame,
            text="ファイルが選択されていません",
            font=("Yu Gothic UI", 10),
            fg="#999",
            bg="white",
            wraplength=550,
            justify=tk.LEFT,
            anchor="w"
        )
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        btn_frame = tk.Frame(step1_frame, bg="white")
        btn_frame.pack()
        
        self.select_btn = ModernButton(
            btn_frame,
            text="📁 ファイルを選択",
            command=self.select_file,
            bg="#000000",
            fg="white",
            padx=25,
            pady=10,
            width=15
        )
        self.select_btn.pack(side=tk.LEFT, padx=5)
        
        self.auto_btn = ModernButton(
            btn_frame,
            text="🔍 最新のCSVを検索",
            command=self.find_latest_csv,
            bg="#000000",
            fg="white",
            padx=25,
            pady=10,
            width=18
        )
        self.auto_btn.pack(side=tk.LEFT, padx=5)
        
        # フィルタ設定セクション
        filter_frame = tk.LabelFrame(
            main_container,
            text="  フィルタ設定（任意）  ",
            font=("Yu Gothic UI", 11, "bold"),
            bg="white",
            fg="#333",
            padx=20,
            pady=15
        )
        filter_frame.pack(fill=tk.X, pady=(0, 15))
        
        # 氏名フィルタ
        name_filter_frame = tk.Frame(filter_frame, bg="white")
        name_filter_frame.pack(fill=tk.X, pady=(0, 10))
        
        name_label = tk.Label(
            name_filter_frame,
            text="氏名:",
            font=("Yu Gothic UI", 10, "bold"),
            bg="white"
        )
        name_label.pack(side=tk.LEFT, padx=(0, 15))
        
        tk.Checkbutton(
            name_filter_frame,
            text="漢字名",
            variable=self.filter_kanji,
            bg="white",
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Checkbutton(
            name_filter_frame,
            text="カタカナ名",
            variable=self.filter_katakana,
            bg="white",
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Checkbutton(
            name_filter_frame,
            text="ひらがな名",
            variable=self.filter_hiragana,
            bg="white",
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Checkbutton(
            name_filter_frame,
            text="アルファベット名",
            variable=self.filter_alphabet,
            bg="white",
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=5)
        
        # 年齢フィルタ
        age_filter_frame = tk.Frame(filter_frame, bg="white")
        age_filter_frame.pack(fill=tk.X)
        
        # 男性の年齢範囲
        male_frame = tk.Frame(age_filter_frame, bg="white")
        male_frame.pack(side=tk.LEFT, padx=(0, 30))
        
        tk.Label(
            male_frame,
            text="男性の年齢範囲:",
            font=("Yu Gothic UI", 10, "bold"),
            bg="white"
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Entry(
            male_frame,
            textvariable=self.male_age_min,
            width=5,
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Label(male_frame, text="歳 -", bg="white", font=("Yu Gothic UI", 9)).pack(side=tk.LEFT, padx=2)
        
        tk.Entry(
            male_frame,
            textvariable=self.male_age_max,
            width=5,
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Label(male_frame, text="歳", bg="white", font=("Yu Gothic UI", 9)).pack(side=tk.LEFT, padx=2)
        
        # 女性の年齢範囲
        female_frame = tk.Frame(age_filter_frame, bg="white")
        female_frame.pack(side=tk.LEFT)
        
        tk.Label(
            female_frame,
            text="女性の年齢範囲:",
            font=("Yu Gothic UI", 10, "bold"),
            bg="white"
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Entry(
            female_frame,
            textvariable=self.female_age_min,
            width=5,
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Label(female_frame, text="歳 -", bg="white", font=("Yu Gothic UI", 9)).pack(side=tk.LEFT, padx=2)
        
        tk.Entry(
            female_frame,
            textvariable=self.female_age_max,
            width=5,
            font=("Yu Gothic UI", 9)
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Label(female_frame, text="歳", bg="white", font=("Yu Gothic UI", 9)).pack(side=tk.LEFT, padx=2)
        
        # ステップ2: プレビュー
        step2_frame = tk.LabelFrame(
            main_container,
            text="  ステップ 2: データを確認  ",
            font=("Yu Gothic UI", 11, "bold"),
            bg="white",
            fg="#333",
            padx=20,
            pady=15
        )
        step2_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        self.preview_text = scrolledtext.ScrolledText(
            step2_frame,
            wrap=tk.WORD,
            width=80,
            height=12,
            font=("Consolas", 9),
            bg="#fafafa",
            fg="#333",
            relief=tk.FLAT,
            borderwidth=0,
            padx=10,
            pady=10
        )
        self.preview_text.pack(fill=tk.BOTH, expand=True)
        self.preview_text.insert("1.0", "CSVファイルを選択すると、ここにプレビューが表示されます。\n\n💡 ヒント:\n• 「最新のCSVを検索」ボタンでダウンロードフォルダから自動検索\n• または「ファイルを選択」ボタンで手動選択")
        self.preview_text.config(state=tk.DISABLED)
        
        # ステップ3: アクション
        step3_frame = tk.LabelFrame(
            main_container,
            text="  ステップ 3: アップロード  ",
            font=("Yu Gothic UI", 11, "bold"),
            bg="white",
            fg="#333",
            padx=20,
            pady=15
        )
        step3_frame.pack(fill=tk.X)
        
        # 起始行号設定
        row_frame = tk.Frame(step3_frame, bg="white")
        row_frame.pack(pady=(0, 10))
        
        tk.Label(
            row_frame,
            text="書き込み開始行:",
            font=("Yu Gothic UI", 10, "bold"),
            bg="white"
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Entry(
            row_frame,
            textvariable=self.start_row,
            width=10,
            font=("Yu Gothic UI", 10)
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Label(
            row_frame,
            text="行目から (空白=自動検出)",
            font=("Yu Gothic UI", 9),
            fg="#666666",
            bg="white"
        ).pack(side=tk.LEFT, padx=5)
        
        action_btn_frame = tk.Frame(step3_frame, bg="white")
        action_btn_frame.pack()
        
        self.preview_btn = ModernButton(
            action_btn_frame,
            text="👁️ プレビューのみ",
            command=self.preview_upload,
            bg="#ffffff",
            fg="#000000",
            font=("Yu Gothic UI", 11, "bold"),
            padx=30,
            pady=12,
            width=18,
            state=tk.DISABLED
        )
        self.preview_btn.pack(side=tk.LEFT, padx=10)
        
        self.upload_btn = ModernButton(
            action_btn_frame,
            text="🚀 アップロード実行",
            command=self.upload_csv,
            bg="#000000",
            fg="white",
            font=("Yu Gothic UI", 11, "bold"),
            padx=30,
            pady=12,
            width=18,
            state=tk.DISABLED
        )
        self.upload_btn.pack(side=tk.LEFT, padx=10)
        
        # ステータスバー
        status_frame = tk.Frame(self.root, bg="#e0e0e0", height=35)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        status_frame.pack_propagate(False)
        
        self.status_label = tk.Label(
            status_frame,
            text="📌 準備完了 - CSVファイルを選択してください",
            font=("Yu Gothic UI", 9),
            bg="#e0e0e0",
            fg="#555",
            anchor=tk.W,
            padx=15
        )
        self.status_label.pack(fill=tk.BOTH, expand=True)
    
    def get_custom_filters(self):
        """GUIで設定したカスタムフィルタを取得"""
        filters = {
            "name_types": [],
            "male_age_min": None,
            "male_age_max": None,
            "female_age_min": None,
            "female_age_max": None,
        }
        
        # 氏名タイプ
        if self.filter_kanji.get():
            filters["name_types"].append("kanji")
        if self.filter_katakana.get():
            filters["name_types"].append("katakana")
        if self.filter_hiragana.get():
            filters["name_types"].append("hiragana")
        if self.filter_alphabet.get():
            filters["name_types"].append("alphabet")
        
        # 年齢範囲
        try:
            filters["male_age_min"] = int(self.male_age_min.get()) if self.male_age_min.get() else None
            filters["male_age_max"] = int(self.male_age_max.get()) if self.male_age_max.get() else None
            filters["female_age_min"] = int(self.female_age_min.get()) if self.female_age_min.get() else None
            filters["female_age_max"] = int(self.female_age_max.get()) if self.female_age_max.get() else None
        except ValueError:
            pass
        
        return filters
    
    def apply_custom_filters(self, data, custom_filters):
        """カスタムフィルタを適用"""
        filtered = []
        
        for row in data:
            match = True
            
            # 氏名タイプフィルタ
            if custom_filters["name_types"]:
                name = row.get("氏名", "")
                name_type = self.detect_name_type(name)
                if name_type not in custom_filters["name_types"]:
                    match = False
            
            # 年齢フィルタ（性別別）
            if match:
                gender = row.get("性別", "")
                try:
                    age = int(row.get("年齢", "0"))
                    
                    if "男" in gender:
                        if custom_filters["male_age_min"] and age < custom_filters["male_age_min"]:
                            match = False
                        if custom_filters["male_age_max"] and age > custom_filters["male_age_max"]:
                            match = False
                    elif "女" in gender:
                        if custom_filters["female_age_min"] and age < custom_filters["female_age_min"]:
                            match = False
                        if custom_filters["female_age_max"] and age > custom_filters["female_age_max"]:
                            match = False
                except (ValueError, KeyError):
                    pass
            
            if match:
                filtered.append(row)
        
        return filtered
    
    def detect_name_type(self, name):
        """氏名のタイプを判定"""
        if not name:
            return "unknown"
        
        # スペースと括弧を除去
        name_clean = name.replace(" ", "").replace("　", "").split("(")[0].split("（")[0]
        
        has_kanji = any('\u4e00' <= c <= '\u9fff' for c in name_clean)
        has_katakana = any('\u30a0' <= c <= '\u30ff' for c in name_clean)
        has_hiragana = any('\u3040' <= c <= '\u309f' for c in name_clean)
        has_alphabet = any(c.isalpha() and ord(c) < 128 for c in name_clean)
        
        if has_alphabet:
            return "alphabet"
        elif has_kanji:
            return "kanji"
        elif has_katakana:
            return "katakana"
        elif has_hiragana:
            return "hiragana"
        else:
            return "unknown"
    
    def load_gui_filters(self):
        """GUIフィルタ設定を読み込む"""
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                gui_filters = config.get("gui_filters", {})
                
                # 氏名タイプ
                name_types = gui_filters.get("name_types", {})
                self.filter_kanji.set(name_types.get("kanji", True))
                self.filter_katakana.set(name_types.get("katakana", True))
                self.filter_hiragana.set(name_types.get("hiragana", True))
                self.filter_alphabet.set(name_types.get("alphabet", True))
                
                # 年齢範囲
                age_ranges = gui_filters.get("age_ranges", {})
                self.male_age_min.set(str(age_ranges.get("male_min", 18)))
                self.male_age_max.set(str(age_ranges.get("male_max", 99)))
                self.female_age_min.set(str(age_ranges.get("female_min", 18)))
                self.female_age_max.set(str(age_ranges.get("female_max", 99)))
        except Exception as e:
            print(f"フィルタ設定の読み込みに失敗: {e}")
    
    def save_gui_filters(self):
        """GUIフィルタ設定を保存する"""
        try:
            # 現在の設定を読み込む
            config = {}
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            
            # GUIフィルタ設定を更新
            config["gui_filters"] = {
                "name_types": {
                    "kanji": self.filter_kanji.get(),
                    "katakana": self.filter_katakana.get(),
                    "hiragana": self.filter_hiragana.get(),
                    "alphabet": self.filter_alphabet.get()
                },
                "age_ranges": {
                    "male_min": int(self.male_age_min.get()) if self.male_age_min.get() else 18,
                    "male_max": int(self.male_age_max.get()) if self.male_age_max.get() else 99,
                    "female_min": int(self.female_age_min.get()) if self.female_age_min.get() else 18,
                    "female_max": int(self.female_age_max.get()) if self.female_age_max.get() else 99
                }
            }
            
            # 保存
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"フィルタ設定の保存に失敗: {e}")
    
    def open_settings(self):
        """設定ダイアログを開く"""
        dialog = SettingsDialog(self.root, self.config_path)
        self.root.wait_window(dialog)
        
        if dialog.result:
            messagebox.showinfo(
                "成功",
                "設定を保存しました！\n\n変更内容は次回のアップロードから反映されます。"
            )
    
    def select_file(self):
        """ファイル選択ダイアログ"""
        initial_dir = os.path.expanduser("~/Downloads")
        
        file_path = filedialog.askopenfilename(
            title="CSVファイルを選択",
            initialdir=initial_dir,
            filetypes=[
                ("CSV files", "*.csv"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            self.set_csv_file(file_path)
    
    def find_latest_csv(self):
        """最新のCSVファイルを検索"""
        download_dir = Path.home() / "Downloads"
        csv_files = list(download_dir.glob("history_*.csv"))
        
        if not csv_files:
            messagebox.showinfo(
                "情報",
                "ダウンロードフォルダに history_*.csv ファイルが見つかりませんでした。\n\n手動でファイルを選択してください。"
            )
            return
        
        # 最新のファイルを取得
        latest_file = max(csv_files, key=lambda p: p.stat().st_mtime)
        self.set_csv_file(str(latest_file))
    
    def set_csv_file(self, file_path):
        """CSVファイルを設定"""
        self.csv_file = file_path
        filename = os.path.basename(file_path)
        self.file_label.config(text=f"✓ {file_path}", fg="#4CAF50")
        self.upload_btn.config(state=tk.NORMAL)
        self.preview_btn.config(state=tk.NORMAL)
        self.status_label.config(text=f"📁 ファイルを選択: {filename}")
        self.load_preview()
    
    def load_preview(self):
        """CSVのプレビューを表示"""
        if not self.csv_file:
            return
        
        try:
            with open(self.csv_file, "r", encoding="utf-8-sig") as f:
                lines = f.readlines()[:6]
            
            preview = "".join(lines)
            if len(lines) > 5:
                preview += "\n... (以下省略)\n"
            
            preview += f"\n💡 「プレビューのみ」ボタンで詳細情報を確認できます。"
            
            self.preview_text.config(state=tk.NORMAL)
            self.preview_text.delete("1.0", tk.END)
            self.preview_text.insert("1.0", preview)
            self.preview_text.config(state=tk.DISABLED)
        except Exception as e:
            self.preview_text.config(state=tk.NORMAL)
            self.preview_text.delete("1.0", tk.END)
            self.preview_text.insert("1.0", f"プレビューの読み込みに失敗しました:\n{e}")
            self.preview_text.config(state=tk.DISABLED)
    
    def preview_upload(self):
        """アップロード内容をプレビュー"""
        if not self.csv_file or self.is_processing:
            return
        
        self.is_processing = True
        self.status_label.config(text="⏳ プレビュー処理中...")
        self.disable_buttons()
        
        def process():
            try:
                config = load_config(str(self.config_path))
                csv_data = read_csv_file(self.csv_file)
                
                # 標準フィルタを適用
                filtered_data = apply_filters(csv_data, config["filters"])
                
                # カスタムフィルタを適用
                custom_filters = self.get_custom_filters()
                filtered_data = self.apply_custom_filters(filtered_data, custom_filters)
                
                if not filtered_data:
                    self.root.after(0, lambda: self.show_error(
                        "フィルタ後のデータがありません。\n設定ファイルのフィルタ条件を確認してください。"
                    ))
                    return
                
                preview_info = self.create_preview_info(csv_data, filtered_data, config)
                self.root.after(0, lambda: self.show_preview_result(preview_info))
                
            except Exception as e:
                error_msg = f"プレビュー処理中にエラーが発生しました:\n\n{str(e)}\n\n{traceback.format_exc()}"
                self.root.after(0, lambda: self.show_error(error_msg))
            finally:
                self.root.after(0, self.enable_buttons)
                self.root.after(0, lambda: self.status_label.config(text="📌 準備完了"))
                self.is_processing = False
        
        thread = threading.Thread(target=process, daemon=True)
        thread.start()
    
    def create_preview_info(self, csv_data, filtered_data, config):
        """プレビュー情報を作成"""
        info = "=" * 70 + "\n"
        info += "📊 アップロード プレビュー\n"
        info += "=" * 70 + "\n\n"
        info += f"元のデータ行数: {len(csv_data)} 行\n"
        info += f"フィルタ後の行数: {len(filtered_data)} 行\n"
        info += f"アップロード先: {config['sheet_name']}\n\n"
        
        info += "サンプルデータ (最初の3行):\n"
        info += "-" * 70 + "\n"
        
        headers = list(config["column_mapping"].keys())
        for i, row in enumerate(filtered_data[:3], 1):
            mapped_row = map_columns(row, config["column_mapping"])
            info += f"\n【データ {i}】\n"
            for header, value in zip(headers[:8], mapped_row[:8]):
                if value:
                    info += f"  {header}: {value}\n"
        
        info += "\n" + "=" * 70 + "\n"
        info += f"✓ 合計 {len(filtered_data)} 行がアップロードされます\n"
        info += "=" * 70
        
        return info
    
    def show_preview_result(self, text):
        """プレビュー結果を表示"""
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.insert("1.0", text)
        self.preview_text.config(state=tk.DISABLED)
    
    def upload_csv(self):
        """CSVをアップロード"""
        if not self.csv_file or self.is_processing:
            return
        
        if not messagebox.askyesno(
            "確認",
            "選択したCSVファイルをSpreadsheetにアップロードします。\n\nよろしいですか？",
            icon="question"
        ):
            return
        
        self.is_processing = True
        self.status_label.config(text="🚀 アップロード中... しばらくお待ちください")
        self.disable_buttons()
        
        def process():
            try:
                config = load_config(str(self.config_path))
                csv_data = read_csv_file(self.csv_file)
                
                # 標準フィルタを適用
                filtered_data = apply_filters(csv_data, config["filters"])
                
                # カスタムフィルタを適用
                custom_filters = self.get_custom_filters()
                filtered_data = self.apply_custom_filters(filtered_data, custom_filters)
                
                if not filtered_data:
                    self.root.after(0, lambda: self.show_error(
                        "フィルタ後のデータがありません。"
                    ))
                    return
                
                mapped_data = [map_columns(row, config["column_mapping"]) for row in filtered_data]
                service_account = load_service_account(config["service_account_path"])
                
                # 開始行番号を取得（空白の場合は自動検出）
                start_row_str = self.start_row.get().strip()
                start_row_value = None  # デフォルトは自動検出
                
                if start_row_str:
                    try:
                        start_row_value = int(start_row_str)
                        if start_row_value < 2:
                            raise ValueError("開始行は2以上である必要があります（1行目はヘッダー）")
                    except ValueError as e:
                        self.root.after(0, lambda: self.show_error(f"開始行番号が無効です:\n{e}"))
                        return
                
                upload_to_spreadsheet(
                    config["spreadsheet_id"],
                    config["sheet_name"],
                    mapped_data,
                    service_account,
                    start_row=start_row_value,
                    formulas=config.get("formulas"),
                    column_mapping=config["column_mapping"],
                )
                
                self.root.after(0, lambda: self.show_success(len(mapped_data)))
                
            except Exception as e:
                error_msg = f"アップロード中にエラーが発生しました:\n\n{str(e)}"
                if "APIError" in str(e) or "403" in str(e):
                    error_msg += "\n\n💡 Google Sheets APIが有効になっているか確認してください。"
                self.root.after(0, lambda: self.show_error(error_msg))
            finally:
                self.root.after(0, self.enable_buttons)
                self.root.after(0, lambda: self.status_label.config(text="📌 準備完了"))
                self.is_processing = False
        
        thread = threading.Thread(target=process, daemon=True)
        thread.start()
    
    def show_success(self, row_count):
        """成功メッセージを表示"""
        # フィルタ設定を保存
        self.save_gui_filters()
        
        messagebox.showinfo(
            "成功",
            f"✓ {row_count} 行のデータをアップロードしました！\n\nSpreadsheetを確認してください。",
            icon="info"
        )
    
    def show_error(self, message):
        """エラーメッセージを表示"""
        messagebox.showerror("エラー", message)
    
    def disable_buttons(self):
        """ボタンを無効化"""
        self.select_btn.config(state=tk.DISABLED)
        self.auto_btn.config(state=tk.DISABLED)
        self.upload_btn.config(state=tk.DISABLED)
        self.preview_btn.config(state=tk.DISABLED)
    
    def enable_buttons(self):
        """ボタンを有効化"""
        self.select_btn.config(state=tk.NORMAL)
        self.auto_btn.config(state=tk.NORMAL)
        if self.csv_file:
            self.upload_btn.config(state=tk.NORMAL)
            self.preview_btn.config(state=tk.NORMAL)


def main():
    root = tk.Tk()
    app = UploadApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
