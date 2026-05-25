"""
CSV履歴データをGoogle Spreadsheetにアップロードするスクリプト。

処理の流れ:
1. ダウンロードしたCSVファイルを読み込む
2. 設定された条件でフィルタリングを行う
3. Spreadsheetの列形式に合わせてデータを整形する
4. Google Spreadsheetに追記する
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("Error: gspread または google-auth がインストールされていません。")
    print("以下のコマンドでインストールしてください:")
    print("  pip install gspread google-auth")
    sys.exit(1)


# デフォルト設定
DEFAULT_CONFIG = {
    "spreadsheet_id": "1xDFKBb4sRUIdNexcUV7ODG26FhR9kTotKylI2S85bPk",
    "sheet_name": "管理表",
    "service_account_path": "service-account/service-account",
    "filters": {
        # フィルタ条件の例（設定ファイルでカスタマイズ可能）
        "性別": None,  # None = フィルタなし、または ["男性", "女性"]
        "年齢_min": None,  # 最小年齢
        "年齢_max": None,  # 最大年齢
        "送信結果": None,  # None = すべての送信結果を含む
        # 追加条件をここに設定できます
    },
    # CSV列からSpreadsheet列へのマッピング
    "column_mapping": {
        # Spreadsheet列名: CSV列名 または 固定値
        "CS備考": "",  # 空白
        "メール": "メールアドレス",
        "LINE": "",  # 空白
        "進捗": "",  # 空白
        "担当CA": "",  # 空白
        "氏名": "氏名",
        "フリガナ": "ふりがな",
        "電話番号": "電話番号",
        "アドレス": "メールアドレス",
        "生年月日": "生年月日",
        "年齢": "年齢",
        "性別": "性別",
        "学歴": "学校名",
        "居住地": "住所",
        "転居": "",  # 空白
        "転居備考": "",  # 空白
        "応募日": "送信日時",  # 送信日時を応募日として使用
        "面談日": "",  # 空白
        "面談時間": "",  # 空白
        "流入": "",  # 空白（または固定値を設定可）
        "応募項目": "求人タイトル",
        "掲載企業": "",  # 空白（CSVに企業情報がない場合）
        "担当CS": "",  # 空白
        "備考": "",  # 空白
    },
}


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    設定ファイルを読み込む。
    設定ファイルがない場合はデフォルト設定を使用する。
    """
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            # デフォルト設定とマージ
            config = DEFAULT_CONFIG.copy()
            config.update(user_config)
            print(f"設定ファイル読み込み: {config_path}")
            return config
        except Exception as e:
            print(f"Warning: 設定ファイルの読み込みに失敗しました: {e}")
            print("デフォルト設定を使用します。")
    else:
        print("設定ファイルが見つかりません。デフォルト設定を使用します。")
    
    return DEFAULT_CONFIG.copy()


def save_default_config(output_path: str) -> None:
    """
    デフォルト設定をJSONファイルとして保存する。
    """
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    print(f"デフォルト設定を保存しました: {output_path}")


def load_service_account(sa_path: str) -> Dict[str, Any]:
    """
    サービスアカウントJSONを読み込む。
    """
    # 相対パスの場合、スクリプトのディレクトリを基準にする
    if not os.path.isabs(sa_path):
        script_dir = Path(__file__).parent.parent  # scriptsの親ディレクトリ
        sa_path = str(script_dir / sa_path)
    
    if not os.path.exists(sa_path):
        print(f"Error: サービスアカウントファイルが見つかりません: {sa_path}")
        sys.exit(1)
    
    try:
        with open(sa_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error: サービスアカウントファイルの読み込みに失敗しました: {e}")
        sys.exit(1)


def read_csv_file(csv_path: str) -> List[Dict[str, str]]:
    """
    CSVファイルを読み込んで辞書のリストとして返す。
    """
    if not os.path.exists(csv_path):
        print(f"Error: CSVファイルが見つかりません: {csv_path}")
        sys.exit(1)
    
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:  # BOM対応
            reader = csv.DictReader(f)
            data = list(reader)
        print(f"CSVファイル読み込み: {csv_path} ({len(data)}行)")
        return data
    except Exception as e:
        print(f"Error: CSVファイルの読み込みに失敗しました: {e}")
        sys.exit(1)


def apply_filters(data: List[Dict[str, str]], filters: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    フィルタ条件を適用してデータを絞り込む。
    """
    filtered = []
    
    for row in data:
        # 各フィルタ条件をチェック
        match = True
        
        # 性別フィルタ
        if filters.get("性別") and row.get("性別"):
            if row["性別"] not in filters["性別"]:
                match = False
        
        # 年齢フィルタ（最小）
        if match and filters.get("年齢_min") is not None:
            try:
                age = int(row.get("年齢", "0"))
                if age < filters["年齢_min"]:
                    match = False
            except ValueError:
                pass
        
        # 年齢フィルタ（最大）
        if match and filters.get("年齢_max") is not None:
            try:
                age = int(row.get("年齢", "0"))
                if age > filters["年齢_max"]:
                    match = False
            except ValueError:
                pass
        
        # 送信結果フィルタ
        if match and filters.get("送信結果"):
            result = row.get("送信結果", "")
            if not any(r in result for r in filters["送信結果"]):
                match = False
        
        # カスタムフィルタを追加する場合はここに記述
        
        if match:
            filtered.append(row)
    
    print(f"フィルタ適用後: {len(filtered)}行 (元: {len(data)}行)")
    return filtered


def extract_prefecture(address: str) -> str:
    """
    住所から都道府県のみを抽出する。
    """
    if not address:
        return ""
    
    # 日本の都道府県リスト
    prefectures = [
        "北海道",
        "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
        "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
        "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
        "岐阜県", "静岡県", "愛知県", "三重県",
        "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
        "鳥取県", "島根県", "岡山県", "広島県", "山口県",
        "徳島県", "香川県", "愛媛県", "高知県",
        "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県",
        "沖縄県"
    ]
    
    # 住所から都道府県を検索
    for pref in prefectures:
        if pref in address:
            return pref
    
    return ""


def format_date_only(date_str: str) -> str:
    """
    日時から日付のみを抽出する（時刻を除去）。
    例: "2026/05/19 11:30:49" → "2026/05/19"
    """
    if not date_str:
        return ""
    
    # スペースで分割して日付部分のみを取得
    parts = date_str.split()
    if parts:
        return parts[0]
    
    return date_str


def hiragana_to_katakana(text: str) -> str:
    """
    平假名を片假名に変換する。
    例: "たなか" → "タナカ"
    """
    if not text:
        return ""
    
    result = []
    for char in text:
        # 平假名の Unicode 範囲: 0x3041-0x3096
        # 片假名の Unicode 範囲: 0x30A1-0x30F6
        # オフセット: 0x60
        code = ord(char)
        if 0x3041 <= code <= 0x3096:
            # 平假名を片假名に変換
            result.append(chr(code + 0x60))
        else:
            # 平假名以外はそのまま
            result.append(char)
    
    return ''.join(result)


def format_phone_number(phone: str) -> str:
    """
    電話番号をハイフン付き形式にフォーマットする。
    例: "09037208502" → "090-3720-8502"
        "0312345678" → "03-1234-5678"
    """
    if not phone:
        return ""
    
    # 数字以外を除去
    digits = re.sub(r'[^\d]', '', phone)
    
    # 先頭にタブ文字がある場合は除去
    if digits.startswith('\t'):
        digits = digits[1:]
    
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


def map_account_name(account_name: str) -> str:
    """
    アカウント名を「流入」列のドロップダウン形式にマッピングする。
    例: "株式会社 P.P/東京本社" → "東京求人ボックス"
    """
    if not account_name:
        return ""
    
    # キーワードマッピング（優先順位順）
    mappings = [
        ("人材紹介事業部", "人材紹介事業部求人ボックス"),
        ("紹介事業部", "紹介事業部求人ボックス"),
        ("採用事務局", "採用事務局求人ボックス"),
        ("採用本部", "採用本部求人ボックス"),
        ("採用人事部", "採用人事部求人ボックス"),
        ("採用窓口", "採用窓口求人ボックス"),
        ("人事部", "人事部求人ボックス"),
        ("東京本社", "東京求人ボックス"),
        ("東京", "東京求人ボックス"),
        ("本社", "本社求人ボックス"),
    ]
    
    # キーワードに基づいてマッピング
    for keyword, mapped_value in mappings:
        if keyword in account_name:
            return mapped_value
    
    # マッチしない場合はデフォルト
    return "新求人ボックス"


def column_index_to_letter(col_index: int) -> str:
    """
    列インデックス（0-based）をExcelの列文字に変換する。
    例: 0→A, 25→Z, 26→AA, 27→AB, 29→AD
    
    Args:
        col_index: 列のインデックス（0始まり）
    
    Returns:
        Excel列文字（A, B, ..., Z, AA, AB, ...）
    """
    result = []
    col_index += 1  # 1-basedに変換
    
    while col_index > 0:
        col_index -= 1
        result.append(chr(65 + (col_index % 26)))
        col_index //= 26
    
    return ''.join(reversed(result))


def map_columns(row: Dict[str, str], mapping: Dict[str, str]) -> List[str]:
    """
    CSV行をSpreadsheet列形式にマッピングする。
    """
    result = []
    
    for sheet_col, csv_col in mapping.items():
        # 特殊処理が必要な列（設定ファイルで空白でも処理する）
        if sheet_col == "転居備考":
            # 転居備考は「勤務地（都道府県）」と「勤務地」を合併
            pref = row.get("勤務地（都道府県）", "").strip()
            addr = row.get("勤務地", "").strip()
            if pref and addr:
                value = f"{pref}{addr}"
            elif pref:
                value = pref
            elif addr:
                value = addr
            else:
                value = ""
            result.append(value)
        elif not csv_col:  # 空白または未設定
            result.append("")
        elif csv_col in row:  # CSV列から取得
            value = row[csv_col]
            
            # 電話番号をハイフン付き形式にフォーマット
            if sheet_col == "電話番号":
                value = format_phone_number(value)
            
            # フリガナは平假名を片假名に変換
            if sheet_col == "フリガナ":
                value = hiragana_to_katakana(value)
            
            # 居住地は都道府県のみを抽出
            if sheet_col == "居住地":
                value = extract_prefecture(value)
            
            # 応募日は日付のみを抽出（時刻を除去）
            if sheet_col == "応募日":
                value = format_date_only(value)
            
            # 流入はアカウント名をドロップダウン形式にマッピング
            if sheet_col == "流入":
                value = map_account_name(value)
            
            result.append(value)
        else:
            # CSV列が見つからない場合は空白
            result.append("")
    
    # デバッグ: 最初の行のマッピング詳細を表示（1回だけ）
    if not hasattr(map_columns, "_debug_shown"):
        print("\n--- 列マッピング詳細 (1行目) ---")
        for i, (sheet_col, csv_col) in enumerate(mapping.items(), start=1):
            value = result[i-1] if i <= len(result) else ""
            display_value = value[:20] if value else "(空白)"
            print(f"  列{i:2d} '{sheet_col:12s}' ← '{csv_col:15s}' = {display_value}...")
        print("-" * 60)
        map_columns._debug_shown = True
    
    return result


def upload_to_spreadsheet(
    spreadsheet_id: str,
    sheet_name: str,
    data: List[List[str]],
    service_account: Dict[str, Any],
    start_row: Optional[int] = None,
    formulas: Optional[Dict[str, str]] = None,
    column_mapping: Optional[Dict[str, str]] = None,
) -> None:
    """
    Google Spreadsheetにデータをアップロードする。
    
    Args:
        start_row: 書き込み開始行番号（指定しない場合は自動検出）
        formulas: 列名をキー、公式テンプレートを値とする辞書（例: {"B列(memo2)": "=$J{row}&$I{row}&$C{row}"}）
        column_mapping: 列マッピング（公式の列インデックスを取得するために使用）
    """
    try:
        # 認証
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(service_account, scopes=scopes)
        client = gspread.authorize(creds)
        
        # スプレッドシートを開く
        print(f"Spreadsheet接続中: {spreadsheet_id}")
        spreadsheet = client.open_by_key(spreadsheet_id)
        
        # ワークシートを取得
        try:
            worksheet = spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"Error: ワークシート '{sheet_name}' が見つかりません。")
            print("利用可能なワークシート:")
            for ws in spreadsheet.worksheets():
                print(f"  - {ws.title}")
            sys.exit(1)
        
        print(f"ワークシート '{sheet_name}' に接続しました。")
        
        # ヘッダー行を取得して確認
        header_row = worksheet.row_values(1)
        print(f"表のヘッダー: {', '.join(header_row[:5])}... (全{len(header_row)}列)")
        
        # デバッグ: 最初の行のマッピングを表示
        if data:
            print("\n--- データマッピング確認 (1行目) ---")
            first_row = data[0]
            for i, (header, value) in enumerate(zip(header_row, first_row)):
                if i < 10:  # 最初の10列のみ表示
                    print(f"  列{i+1} '{header}': {value[:30] if value else '(空白)'}{'...' if len(str(value)) > 30 else ''}")
            if len(header_row) > 10:
                print(f"  ... 他 {len(header_row) - 10} 列")
            print("-" * 50 + "\n")
        
        # 最終行を取得（K列の氏名を基準に空白行を検出）
        all_values = worksheet.get_all_values()
        
        if start_row:
            # ユーザー指定の行番号を使用
            next_row = start_row
            print(f"ユーザー指定の開始行: {next_row}")
        else:
            # K列（氏名列、インデックス10）が最初に空白になる行を見つける
            K_COLUMN_INDEX = 10  # K列は11列目（0-indexed で10）
            next_row = 2  # ヘッダーの次の行から開始
            
            for i, row in enumerate(all_values, start=1):
                if i == 1:  # ヘッダー行はスキップ
                    continue
                
                # K列が空白かチェック
                k_value = row[K_COLUMN_INDEX] if len(row) > K_COLUMN_INDEX else ""
                if not k_value.strip():
                    next_row = i
                    print(f"自動検出: K列（氏名）が空白の最初の行を検出 → 行{next_row}")
                    break
            else:
                # すべての行にK列データがある場合、最後の行の次に追記
                next_row = len(all_values) + 1
                print(f"自動検出: すべての行にデータあり → 最終行の次（行{next_row}）から追記")
        
        print(f"データを追記中... (開始行: {next_row}, 追加行数: {len(data)})")
        
        # データを一括追記（効率化）
        if data:
            # 範囲を指定して書き込む（gspread最新版の引数順序に対応）
            start_cell = f"A{next_row}"
            worksheet.update(values=data, range_name=start_cell, value_input_option="USER_ENTERED")
            print(f"✓ {len(data)}行のデータをアップロードしました！（行{next_row}～{next_row + len(data) - 1}）")
            
            # 公式を適用
            if formulas and column_mapping:
                # 列名からインデックスへのマッピングを作成
                column_indices = {col_name: idx for idx, col_name in enumerate(column_mapping.keys())}
                
                for col_name, formula_template in formulas.items():
                    if col_name in column_indices:
                        col_index = column_indices[col_name]
                        # 列インデックスをA1表記に変換（0→A, 1→B, ..., 26→AA, 27→AB, ...）
                        col_letter = column_index_to_letter(col_index)
                        
                        # 各行に公式を適用
                        formula_updates = []
                        for i in range(len(data)):
                            row_num = next_row + i
                            formula = formula_template.replace("{row}", str(row_num))
                            cell_address = f"{col_letter}{row_num}"
                            formula_updates.append({
                                "range": cell_address,
                                "values": [[formula]]
                            })
                        
                        # 公式を一括更新
                        if formula_updates:
                            for update in formula_updates:
                                worksheet.update(
                                    values=update["values"],
                                    range_name=update["range"],
                                    value_input_option="USER_ENTERED"
                                )
        else:
            print("アップロードするデータがありません。")
        
    except Exception as e:
        print(f"Error: Spreadsheetへのアップロードに失敗しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="CSV履歴データをGoogle Spreadsheetにアップロードします。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # CSVファイルをアップロード
  python upload_to_spreadsheet.py history_2026_05_19_10_30_00.csv

  # 設定ファイルを使用
  python upload_to_spreadsheet.py history.csv --config config/upload_config.json

  # デフォルト設定ファイルを生成
  python upload_to_spreadsheet.py --save-config config/upload_config.json
        """,
    )
    
    parser.add_argument(
        "csv_file",
        nargs="?",
        help="アップロードするCSVファイルのパス",
    )
    
    parser.add_argument(
        "--config",
        "-c",
        help="設定ファイルのパス（JSON形式）",
    )
    
    parser.add_argument(
        "--save-config",
        help="デフォルト設定をJSONファイルとして保存する",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実際にアップロードせず、処理内容のみを表示する",
    )
    
    args = parser.parse_args()
    
    try:
        # デフォルト設定を保存して終了
        if args.save_config:
            save_default_config(args.save_config)
            return
        
        # CSVファイルが指定されていない場合
        if not args.csv_file:
            parser.print_help()
            return
        
        # 設定を読み込む
        config = load_config(args.config)
        
        # CSVファイルを読み込む
        csv_data = read_csv_file(args.csv_file)
        
        # デバッグ: CSV列名を表示
        if csv_data:
            csv_columns = list(csv_data[0].keys())
            print(f"CSV列名: {', '.join(csv_columns[:5])}... (全{len(csv_columns)}列)")
            print(f"CSV最初の行サンプル:")
            for i, (key, value) in enumerate(list(csv_data[0].items())[:5]):
                print(f"  '{key}': {value[:30] if value else '(空白)'}{'...' if len(str(value)) > 30 else ''}")
            print()
        
        # フィルタを適用
        filtered_data = apply_filters(csv_data, config["filters"])
        
        if not filtered_data:
            print("フィルタ後のデータがありません。処理を終了します。")
            return
        
        # 列をマッピング
        mapped_data = []
        for row in filtered_data:
            mapped_row = map_columns(row, config["column_mapping"])
            mapped_data.append(mapped_row)
        
        # Dry-runモード
        if args.dry_run:
            print("\n--- Dry-run モード ---")
            print(f"アップロード対象: {len(mapped_data)}行")
            print("\nサンプルデータ (最初の3行):")
            headers = list(config["column_mapping"].keys())
            print("  " + " | ".join(headers[:5]) + " ...")
            for i, row in enumerate(mapped_data[:3]):
                print(f"  {i+1}: " + " | ".join(row[:5]) + " ...")
            print("\n実際にアップロードするには --dry-run オプションを外してください。")
            return
        
        # サービスアカウントを読み込む
        service_account = load_service_account(config["service_account_path"])
        
        # Spreadsheetにアップロード
        upload_to_spreadsheet(
            config["spreadsheet_id"],
            config["sheet_name"],
            mapped_data,
            service_account,
            formulas=config.get("formulas"),
            column_mapping=config["column_mapping"],
        )
        
        print("\n処理が完了しました！")
    
    except KeyboardInterrupt:
        print("\n\n処理が中断されました。")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: 予期しないエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
