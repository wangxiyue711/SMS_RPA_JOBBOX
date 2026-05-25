"""
RPA即时上传功能模块 - 管理表Sheet
将求职者信息即时上传到Google Spreadsheet（管理表）

NOTE: 当前版本专用于「管理表」Sheet
      将来可扩展支持其他Sheet（例如：別Sheet1、別Sheet2等）
"""
import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("Warning: gspread or google-auth not installed")
    gspread = None


def format_phone_number(phone: str) -> str:
    """
    电话番号をハイフン付き形式にフォーマットする。
    例: "09037208502" → "090-3720-8502"
    """
    if not phone:
        return ""
    
    # 数字以外を除去
    digits = re.sub(r'[^\d]', '', phone)
    
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


def hiragana_to_katakana(text: str) -> str:
    """
    平假名を片假名に変換する。
    """
    if not text:
        return ""
    
    result = []
    for char in text:
        code = ord(char)
        if 0x3041 <= code <= 0x3096:
            result.append(chr(code + 0x60))
        else:
            result.append(char)
    
    return ''.join(result)


def extract_prefecture(address: str) -> str:
    """
    住所から都道府県のみを抽出する。
    """
    if not address:
        return ""
    
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
    
    for pref in prefectures:
        if pref in address:
            return pref
    
    return ""


def parse_name_and_furigana(name_with_furigana: str) -> tuple[str, str]:
    """
    括号付き氏名から、氏名とフリガナを分離する。
    例: "飯川 智斗(いいかわ ちかと)" → ("飯川 智斗", "イイカワ チカト")
    
    Args:
        name_with_furigana: 括号付き氏名
    
    Returns:
        (氏名, カタカナフリガナ) のタプル
    """
    if not name_with_furigana:
        return "", ""
    
    # 括号の有無をチェック
    if '(' in name_with_furigana and ')' in name_with_furigana:
        # 括号で分割
        parts = name_with_furigana.split('(')
        name = parts[0].strip()
        furigana_hiragana = parts[1].replace(')', '').strip()
        
        # ひらがなをカタカナに変換（スペース除去）
        furigana_katakana = hiragana_to_katakana(furigana_hiragana.replace(' ', ''))
        
        return name, furigana_katakana
    else:
        # 括号がない場合はそのまま返す
        return name_with_furigana.strip(), ""


def format_date_only(date_str: str) -> str:
    """
    日時から日付のみを抽出する（時刻を除去）。
    例: "2026/05/19 11:30:49" → "2026/05/19"
    """
    if not date_str:
        return ""
    
    parts = date_str.split()
    if parts:
        return parts[0]
    
    return date_str


def format_birth_date(birth_str: str) -> str:
    """
    生年月日を YYYY/MM/DD 形式に変換する。
    例: "1996年4月1日（30歳）" → "1996/04/01"
        "2003/05/24" → "2003/05/24" (そのまま)
    """
    if not birth_str:
        return ""
    
    # 年齢部分を除去（例: "（30歳）"）
    birth_str = re.sub(r'[（(]\d+[歳才][）)]', '', birth_str).strip()
    
    # すでに YYYY/MM/DD 形式の場合はそのまま返す
    if re.match(r'^\d{4}/\d{1,2}/\d{1,2}$', birth_str):
        # 月日を2桁に揃える
        parts = birth_str.split('/')
        if len(parts) == 3:
            year = parts[0]
            month = parts[1].zfill(2)
            day = parts[2].zfill(2)
            return f"{year}/{month}/{day}"
        return birth_str
    
    # 日本語形式の場合: "1996年4月1日" → "1996/04/01"
    match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', birth_str)
    if match:
        year = match.group(1)
        month = match.group(2).zfill(2)
        day = match.group(3).zfill(2)
        return f"{year}/{month}/{day}"
    
    # その他の形式はそのまま返す
    return birth_str


def map_account_name(account_name: str) -> str:
    """
    アカウント名を「流入」列のドロップダウン形式にマッピングする。
    """
    if not account_name:
        return ""
    
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
    
    for keyword, mapped_value in mappings:
        if keyword in account_name:
            return mapped_value
    
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


def load_config() -> Optional[Dict[str, Any]]:
    """
    設定ファイルを読み込む
    """
    script_dir = Path(__file__).parent
    config_paths = [
        script_dir.parent / "config" / "upload_config.json",
        script_dir / ".." / "config" / "upload_config.json",
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: config読み込み失敗: {e}")
    
    return None


def upload_applicant_to_kanri_sheet(applicant_data: Dict[str, Any], uid: Optional[str] = None) -> bool:
    """
    求職者データを即時に「管理表」Sheetにアップロードする
    
    Args:
        applicant_data: 求職者データ (name, tel, email, gender, age, birth, addr, 
                                       account_name, job_title, employer_name, etc.)
        uid: ユーザーID（オプション）
    
    Returns:
        bool: アップロード成功時True
    
    NOTE: この関数は「管理表」Sheet専用です
          他のSheetに対応する場合は、upload_applicant_to_XXX_sheet()を別途作成してください
    """
    if not gspread:
        print("[管理表SheetUploader] gspread未インストール、Sheetアップロードをスキップします")
        return False
    
    try:
        # 設定ファイルを読み込む（管理表Sheet用）
        config = load_config()
        if not config:
            print("[管理表SheetUploader] 設定ファイルが見つかりません")
            return False
        
        # 有効/無効チェック
        if not config.get('enabled', True):
            print("[管理表SheetUploader] ⚠️ 管理表Sheetへのアップロードは無効化されています（config.enabled=false）")
            return False
        
        # サービスアカウントファイルのパスを解決
        sa_path = config.get('service_account_path', 'service-account/service-account')
        if not os.path.isabs(sa_path):
            script_dir = Path(__file__).parent.parent
            sa_path = str(script_dir / sa_path)
        
        if not os.path.exists(sa_path):
            print(f"[管理表SheetUploader] サービスアカウントファイルが見つかりません: {sa_path}")
            return False
        
        # サービスアカウントで認証
        with open(sa_path, "r", encoding="utf-8") as f:
            sa_info = json.load(f)
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        client = gspread.authorize(creds)
        
        # スプレッドシートを開く
        spreadsheet_id = config.get('spreadsheet_id')
        sheet_name = config.get('sheet_name', '管理表')
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # 列マッピング設定を取得
        column_mapping = config.get('column_mapping', {})
        
        # K列（氏名列）の最初の空白行を見つける（GUIと同じロジック）
        # column_mappingの順序でK列を特定
        column_names = list(column_mapping.keys())
        name_col_index = None
        for i, col_name in enumerate(column_names):
            if col_name == "氏名":
                name_col_index = i  # 0-indexed
                break
        
        # 全データを取得してK列が空白の最初の行を見つける
        target_row = 2  # デフォルトはヘッダーの次の行
        if name_col_index is not None:
            try:
                all_values = worksheet.get_all_values()
                
                for i, row in enumerate(all_values, start=1):
                    if i == 1:  # ヘッダー行はスキップ
                        continue
                    
                    # K列（氏名列）が空白かチェック
                    k_value = row[name_col_index] if len(row) > name_col_index else ""
                    if not k_value.strip():
                        target_row = i
                        print(f"[管理表SheetUploader] K列が空白の最初の行を検出: {target_row}行目")
                        break
                else:
                    # すべての行にK列データがある場合、最後の行の次
                    target_row = len(all_values) + 1
                    print(f"[管理表SheetUploader] すべての行にデータあり、最終行の次（{target_row}行目）に追記")
            except Exception as e:
                print(f"[管理表SheetUploader] K列検索エラー（デフォルト行を使用）: {e}")
                target_row = 2
        
        # 氏名とフリガナを解析（column_mappingから正しいフィールド名を取得）
        name_field = column_mapping.get('氏名', '')
        name_with_furigana = applicant_data.get(name_field, '') if name_field else ''
        parsed_name, parsed_furigana_katakana = parse_name_and_furigana(name_with_furigana)
        
        # フリガナが解析で取得できなかった場合、ふりがなフィールドから取得
        if not parsed_furigana_katakana:
            furigana_field = column_mapping.get('フリガナ', '')
            furigana_raw = applicant_data.get(furigana_field, '') if furigana_field else ''
            parsed_furigana_katakana = hiragana_to_katakana(furigana_raw)
        
        print(f"[管理表SheetUploader] 氏名: {parsed_name}, フリガナ: {parsed_furigana_katakana}")
        
        # データを整形
        row_data = []
        from datetime import datetime
        
        # 応募日を取得（sent_atから）
        sent_at = applicant_data.get('sent_at')
        if sent_at:
            # sent_atがUnix timestamp（数値）の場合
            if isinstance(sent_at, (int, float)):
                oubo_date = datetime.fromtimestamp(sent_at).strftime('%Y/%m/%d')
            # sent_atが文字列の場合（例: "2026/05/20 12:36"）
            else:
                oubo_date = format_date_only(str(sent_at))
        else:
            # sent_atがない場合は現在日時をフォールバック
            oubo_date = datetime.now().strftime('%Y/%m/%d')
        
        for sheet_col, csv_col in column_mapping.items():
            if not csv_col:
                # 空白列
                row_data.append("")
            elif sheet_col == "氏名":
                row_data.append(parsed_name)
            elif sheet_col == "フリガナ":
                row_data.append(parsed_furigana_katakana)
            elif sheet_col == "電話番号":
                tel = applicant_data.get('tel', '')
                row_data.append(format_phone_number(tel))
            elif sheet_col == "アドレス" or sheet_col == "メール":
                row_data.append(applicant_data.get('email', ''))
            elif sheet_col == "生年月日":
                # 生年月日を YYYY/MM/DD 形式に変換
                birth = applicant_data.get('birth', '')
                row_data.append(format_birth_date(birth))
            elif sheet_col == "年齢":
                age = applicant_data.get('age', '')
                row_data.append(str(age) if age else '')
            elif sheet_col == "性別":
                row_data.append(applicant_data.get('gender', ''))
            elif sheet_col == "学歴":
                # 学歴は空白にする
                row_data.append("")
            elif sheet_col == "居住地":
                addr = applicant_data.get('addr', '')
                row_data.append(extract_prefecture(addr))
            elif sheet_col == "応募日":
                row_data.append(oubo_date)
            elif sheet_col == "流入":
                account_name = applicant_data.get('account_name', '')
                row_data.append(map_account_name(account_name))
            elif sheet_col == "応募項目":
                row_data.append(applicant_data.get('job_title', ''))
            elif sheet_col == "掲載企業":
                row_data.append(applicant_data.get('employer_name', ''))
            elif csv_col == "勤務地":
                # 勤務地情報を結合（転居備考列に対応）
                work_pref = applicant_data.get('work_prefecture', '')
                work_addr = applicant_data.get('work_address', '')
                row_data.append(combine_work_location(work_pref, work_addr))
            else:
                row_data.append("")
        
        # 指定した行に挿入（Sheetの行数制限を確認）
        actual_row = target_row  # 実際に挿入された行番号を記録
        try:
            current_row_count = worksheet.row_count
            if target_row > current_row_count:
                # 行数を超える場合はappend_rowを使用
                print(f"[管理表SheetUploader] target_row({target_row})がSheet行数({current_row_count})を超えるため、append_rowを使用")
                worksheet.append_row(row_data, value_input_option='USER_ENTERED')
                actual_row = current_row_count + 1  # append_rowは最後の行の次に追加
                print(f"[管理表SheetUploader] ✅ {parsed_name} のデータを管理表Sheetの末尾に追加しました")
            else:
                worksheet.insert_row(row_data, target_row, value_input_option='USER_ENTERED')
                actual_row = target_row
                print(f"[管理表SheetUploader] ✅ {parsed_name} のデータを管理表Sheet（{target_row}行目）に追加しました")
        except Exception as insert_error:
            # insert_rowが失敗した場合のフォールバック
            print(f"[管理表SheetUploader] insert_row失敗、append_rowで再試行: {insert_error}")
            worksheet.append_row(row_data, value_input_option='USER_ENTERED')
            actual_row = worksheet.row_count  # append後の最終行
            print(f"[管理表SheetUploader] ✅ {parsed_name} のデータを管理表Sheetの末尾に追加しました")
        
        # 公式を適用
        formulas = config.get('formulas')
        if formulas:
            column_indices = {col_name: idx for idx, col_name in enumerate(column_mapping.keys())}
            
            for col_name, formula_template in formulas.items():
                if col_name in column_indices:
                    col_index = column_indices[col_name]
                    # 列インデックスをA1表記に変換（0→A, 1→B, ..., 26→AA, 27→AB, ...）
                    col_letter = column_index_to_letter(col_index)
                    
                    # 公式を生成
                    formula = formula_template.replace("{row}", str(actual_row))
                    cell_address = f"{col_letter}{actual_row}"
                    
                    try:
                        worksheet.update(
                            values=[[formula]],
                            range_name=cell_address,
                            value_input_option="USER_ENTERED"
                        )
                    except Exception as formula_error:
                        print(f"[管理表SheetUploader]   ⚠️ {col_name}の公式設定失敗: {formula_error}")
        
        return True
        
    except Exception as e:
        print(f"[管理表SheetUploader] ❌ 管理表Sheetアップロードエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


# 別名: 将来の拡張性のため、既存の関数名もサポート
upload_applicant_to_sheet = upload_applicant_to_kanri_sheet


# ============================================================
# 応募者リスト Sheet用の関数群
# ============================================================

def load_oubosha_config() -> Optional[Dict[str, Any]]:
    """
    応募者リストSheet用の設定ファイルを読み込む
    """
    script_dir = Path(__file__).parent
    config_paths = [
        script_dir.parent / "config" / "oubosha_list_config.json",
        script_dir / ".." / "config" / "oubosha_list_config.json",
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: oubosha_list_config読み込み失敗: {e}")
    
    return None


def split_datetime_for_oubosha(sent_at: Optional[int] = None) -> tuple[str, str]:
    """
    送信日時を応募日（年月日）と応募時間（時:分）に分割する
    
    Args:
        sent_at: Unix timestamp（秒単位）、Noneの場合は現在時刻
    
    Returns:
        (応募日, 応募時間) のタプル
        例: ("2026/05/20", "14:30")
    """
    from datetime import datetime
    
    if sent_at:
        dt = datetime.fromtimestamp(sent_at)
    else:
        dt = datetime.now()
    
    oubo_date = dt.strftime('%Y/%m/%d')
    oubo_time = dt.strftime('%H:%M')
    
    return oubo_date, oubo_time


def combine_work_location(work_prefecture: str, work_address: str) -> str:
    """
    勤務地（都道府県）と勤務先住所を組み合わせる
    
    Args:
        work_prefecture: 勤務地都道府県（例: "東京都"）
        work_address: 勤務先住所（例: "渋谷区道玄坂1-2-3"）
    
    Returns:
        組み合わせた勤務地（例: "東京都渋谷区道玄坂1-2-3"）
    """
    if not work_prefecture and not work_address:
        return ""
    
    # 都道府県が住所に既に含まれている場合は重複を避ける
    if work_prefecture and work_address and work_address.startswith(work_prefecture):
        return work_address
    
    # 両方ある場合は結合
    if work_prefecture and work_address:
        return f"{work_prefecture}{work_address}"
    
    # どちらか一方のみある場合
    return work_prefecture or work_address


def upload_applicant_to_oubosha_list(applicant_data: Dict[str, Any], uid: Optional[str] = None) -> bool:
    """
    求職者データを即時に「応募者リスト」Sheetにアップロードする
    
    Args:
        applicant_data: 求職者データ (name, tel, email, gender, age, birth, addr, 
                                       account_name, job_title, employer_name, 
                                       work_prefecture, work_address, sent_at, etc.)
        uid: ユーザーID（オプション）
    
    Returns:
        bool: アップロード成功時True
    """
    if not gspread:
        print("[応募者リストUploader] gspread未インストール、Sheetアップロードをスキップします")
        return False
    
    try:
        # 設定ファイルを読み込む（応募者リストSheet用）
        config = load_oubosha_config()
        if not config:
            print("[応募者リストUploader] oubosha_list_config.jsonが見つかりません")
            return False
        
        # 有効/無効チェック
        if not config.get('enabled', True):
            print("[応募者リストUploader] ⚠️ 応募者リストSheetへのアップロードは無効化されています（config.enabled=false）")
            return False
        
        # サービスアカウントファイルのパスを解決
        sa_path = config.get('service_account_path', 'service-account/service-account')
        if not os.path.isabs(sa_path):
            script_dir = Path(__file__).parent.parent
            sa_path = str(script_dir / sa_path)
        
        if not os.path.exists(sa_path):
            print(f"[応募者リストUploader] サービスアカウントファイルが見つかりません: {sa_path}")
            return False
        
        # サービスアカウントで認証
        with open(sa_path, "r", encoding="utf-8") as f:
            sa_info = json.load(f)
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
        client = gspread.authorize(creds)
        
        # スプレッドシートを開く
        spreadsheet_id = config.get('spreadsheet_id')
        sheet_name = config.get('sheet_name', '応募者リスト')
        
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        
        # 列マッピング設定を取得
        column_mapping = config.get('column_mapping', {})
        
        # 送信日時を分割
        sent_at = applicant_data.get('sent_at')
        oubo_date, oubo_time = split_datetime_for_oubosha(sent_at)
        
        # 勤務地を組み合わせ
        work_location = combine_work_location(
            applicant_data.get('work_prefecture', ''),
            applicant_data.get('work_address', '')
        )
        
        # 氏名とフリガナを解析（column_mappingから正しいフィールド名を取得）
        name_field = column_mapping.get('応募者名', '')
        name_with_furigana = applicant_data.get(name_field, '') if name_field else ''
        parsed_name, parsed_furigana_katakana = parse_name_and_furigana(name_with_furigana)
        
        # フリガナが解析で取得できなかった場合、ふりがなフィールドから取得
        if not parsed_furigana_katakana:
            furigana_field = column_mapping.get('フリガナ', '')
            furigana_raw = applicant_data.get(furigana_field, '') if furigana_field else ''
            parsed_furigana_katakana = hiragana_to_katakana(furigana_raw)
        
        print(f"[応募者リストUploader] 氏名: {parsed_name}, フリガナ: {parsed_furigana_katakana}")
        
        # データを整形（A列から順番に - 正しい順序を保証）
        # A列は空白、B列はステータス（手動入力用）、C列から応募者名
        expected_order = [
            "memo", "ステータス", "応募者名", "フリガナ", "電話番号", 
            "性別", "生年月日", "年齢", "居住地", "会社名", 
            "職種名", "勤務地", "応募日", "応募時間", "担当CA", 
            "面談日", "面談時間", "備考"
        ]
        
        row_data = []
        
        for sheet_col in expected_order:
            csv_col = column_mapping.get(sheet_col, "")
            
            if not csv_col:
                # 空白列（memo, ステータス, 担当CA, 面談日, 面談時間, 備考）
                row_data.append("")
            elif sheet_col == "応募者名":
                row_data.append(parsed_name)
            elif sheet_col == "フリガナ":
                row_data.append(parsed_furigana_katakana)
            elif sheet_col == "電話番号":
                tel = applicant_data.get('tel', '')
                row_data.append(format_phone_number(tel))
            elif sheet_col == "性別":
                row_data.append(applicant_data.get('gender', ''))
            elif sheet_col == "生年月日":
                # 生年月日を YYYY/MM/DD 形式に変換
                birth = applicant_data.get('birth', '')
                row_data.append(format_birth_date(birth))
            elif sheet_col == "年齢":
                age = applicant_data.get('age', '')
                row_data.append(str(age) if age else '')
            elif sheet_col == "居住地":
                # 住所から都道府県を抽出
                addr = applicant_data.get('addr', '')
                row_data.append(extract_prefecture(addr))
            elif sheet_col == "会社名":
                row_data.append(applicant_data.get('employer_name', ''))
            elif sheet_col == "職種名":
                row_data.append(applicant_data.get('job_title', ''))
            elif sheet_col == "勤務地":
                row_data.append(work_location)
            elif sheet_col == "応募日":
                row_data.append(oubo_date)
            elif sheet_col == "応募時間":
                row_data.append(oubo_time)
            else:
                row_data.append("")
        
        # updateメソッドで範囲指定して書き込み（append_rowのバグ回避）
        all_values = worksheet.get_all_values()
        next_row = len(all_values) + 1
        range_notation = f'A{next_row}:R{next_row}'
        
        worksheet.update(range_notation, [row_data], value_input_option='RAW')
        
        # 生年月日、年齢、応募日、応募時間を右揃えに設定
        # 生年月日: G列（index 6）、年齢: H列（index 7）、応募日: M列（index 12）、応募時間: N列（index 13）
        format_requests = {
            "horizontalAlignment": "RIGHT"
        }
        
        # G列（生年月日）
        worksheet.format(f'G{next_row}', format_requests)
        # H列（年齢）
        worksheet.format(f'H{next_row}', format_requests)
        # M列（応募日）
        worksheet.format(f'M{next_row}', format_requests)
        # N列（応募時間）
        worksheet.format(f'N{next_row}', format_requests)
        
        # 公式を適用
        formulas = config.get('formulas')
        if formulas:
            column_indices = {col_name: idx for idx, col_name in enumerate(column_mapping.keys())}
            
            for col_name, formula_template in formulas.items():
                if col_name in column_indices:
                    col_index = column_indices[col_name]
                    # 列インデックスをA1表記に変換（0→A, 1→B, ..., 26→AA, 27→AB, ...）
                    col_letter = column_index_to_letter(col_index)
                    
                    # 公式を生成
                    formula = formula_template.replace("{row}", str(next_row))
                    cell_address = f"{col_letter}{next_row}"
                    
                    try:
                        worksheet.update(
                            values=[[formula]],
                            range_name=cell_address,
                            value_input_option="USER_ENTERED"
                        )
                    except Exception as formula_error:
                        print(f"[応募者リストUploader]   ⚠️ {col_name}の公式設定失敗: {formula_error}")
        
        print(f"[応募者リストUploader] ✅ {parsed_name} のデータを応募者リストに追加しました")
        return True
        
    except Exception as e:
        print(f"[応募者リストUploader] ❌ 応募者リストアップロードエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # テスト用 - 両方のSheetへのアップロードテスト
    test_data = {
        'name': 'テスト太郎',
        'furigana': 'てすとたろう',
        'tel': '09012345678',
        'email': 'test@example.com',
        'gender': '男性',
        'age': 25,
        'birth': '1999/01/01',
        'addr': '東京都新宿区',
        'account_name': '東京本社',
        'job_title': 'エンジニア募集',
        'employer_name': '株式会社テスト',
        'school': 'テスト大学',
        'work_prefecture': '東京都',
        'work_address': '渋谷区道玄坂1-2-3',
        'sent_at': None,  # Noneの場合は現在時刻
    }
    
    print("=" * 60)
    print("1. 管理表Sheet アップロードテスト")
    print("=" * 60)
    result1 = upload_applicant_to_kanri_sheet(test_data)
    print(f"\nテスト結果: {'成功 ✅' if result1 else '失敗 ❌'}")
    
    print("\n" + "=" * 60)
    print("2. 応募者リストSheet アップロードテスト")
    print("=" * 60)
    result2 = upload_applicant_to_oubosha_list(test_data)
    print(f"\nテスト結果: {'成功 ✅' if result2 else '失敗 ❌'}")

