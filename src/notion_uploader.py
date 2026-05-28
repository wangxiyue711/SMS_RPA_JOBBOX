"""
Notion データベース アップロード モジュール

求職者情報をNotionの2つのデータベースに自動アップロード：
1. 【求職者DB】：求職者の基本情報（重複チェック付き）
2. 【応募DB】：各応募の詳細情報（毎回追記）
"""

import os
import sys
import json
import re
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

try:
    from notion_client import Client
    import notion_client
    # Version check moved to runtime to avoid import-time crashes
except ImportError:
    print("Warning: notion-client not installed")
    Client = None
    notion_client = None


def load_config() -> Optional[Dict[str, Any]]:
    """Notion設定ファイルを読み込む"""
    script_dir = Path(__file__).parent
    config_paths = [
        script_dir.parent / "config" / "notion_config.json",
        script_dir / ".." / "config" / "notion_config.json",
    ]
    
    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Warning: Notion config読み込み失敗: {e}")
    
    return None


def hiragana_to_katakana(text: str) -> str:
    """
    平假名转换为片假名
    """
    if not text:
        return text
    
    result = []
    for char in text:
        code = ord(char)
        # 平假名范围: U+3041 到 U+3096
        # 片假名范围: U+30A1 到 U+30F6
        # 偏移量: 0x60
        if 0x3041 <= code <= 0x3096:
            result.append(chr(code + 0x60))
        else:
            result.append(char)
    return ''.join(result)


def parse_name_and_furigana(name_str: str, furigana_str: str = '') -> tuple:
    """
    姓名から読み仮名を分離
    
    例: "飯川 智斗(いいかわ ちかと)" → ("飯川 智斗", "いいかわ ちかと")
    
    Args:
        name_str: 氏名（括弧付きの可能性あり）
        furigana_str: フリガナ（既に分離されている場合）
    
    Returns:
        (姓名, 読み仮名) のタプル
    """
    if not name_str:
        return ('', furigana_str)
    
    # 括弧内の読み仮名を検出
    import re
    match = re.search(r'([^\(（]+)[\(（]([^\)）]+)[\)）]', name_str)
    
    if match:
        # 括弧外が姓名、括弧内が読み仮名
        clean_name = match.group(1).strip()
        extracted_furigana = match.group(2).strip()
        
        # 既存のfuriganaがなければ抽出した読み仮名を使用
        final_furigana = furigana_str if furigana_str else extracted_furigana
        
        return (clean_name, final_furigana)
    
    # 括弧がない場合はそのまま
    return (name_str.strip(), furigana_str)


def extract_prefecture(address: str) -> str:
    """
    从地址中提取都道府县
    """
    if not address:
        return ""
    
    # 日本都道府县列表（优先匹配长的）
    prefectures = [
        '北海道',
        '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
        '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
        '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県', '岐阜県', '静岡県', '愛知県',
        '三重県', '滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県',
        '鳥取県', '島根県', '岡山県', '広島県', '山口県',
        '徳島県', '香川県', '愛媛県', '高知県',
        '福岡県', '佐賀県', '長崎県', '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県'
    ]
    
    # 检查地址中是否包含都道府县
    for pref in prefectures:
        if pref in address:
            return pref
    
    # 如果没有匹配到，返回原地址
    return address


def format_phone_for_notion(phone: str) -> str:
    """
    電話番号をNotion用にフォーマット
    Notionのphone_number型は国際形式を推奨
    """
    if not phone:
        return ""
    
    # 数字以外を除去
    digits = re.sub(r'[^\d]', '', phone)
    
    # ハイフン付き形式で返す
    if len(digits) == 11:
        return f"{digits[0:3]}-{digits[3:7]}-{digits[7:11]}"
    elif len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    
    return phone


def format_date_for_notion(date_str: str) -> Optional[str]:
    """
    日付をNotionのISO 8601形式に変換
    入力: "2026/05/20" or "2026-05-20" or "1946年4月1日" or Unix timestamp
    出力: "2026-05-20"
    """
    if not date_str:
        return None
    
    # Unix timestampの場合
    if isinstance(date_str, (int, float)):
        dt = datetime.fromtimestamp(date_str)
        return dt.strftime('%Y-%m-%d')
    
    # 文字列の場合
    date_str = str(date_str).strip()
    
    # 日本語形式: YYYY年MM月DD日（年齢表記などを削除）
    # 例: "1946年4月1日（80歳）" → "1946-04-01"
    ja_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
    if ja_match:
        year = ja_match.group(1)
        month = ja_match.group(2).zfill(2)
        day = ja_match.group(3).zfill(2)
        return f"{year}-{month}-{day}"
    
    # YYYY/MM/DD形式
    if '/' in date_str:
        parts = date_str.split()[0].split('/')  # 時刻部分を除去
        if len(parts) == 3:
            return f"{parts[0]}-{parts[1].zfill(2)}-{parts[2].zfill(2)}"
    
    # YYYY-MM-DD形式（既に正しい形式）
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str
    
    return None


def format_datetime_for_notion(date_input) -> Optional[str]:
    """
    日時をNotionのISO 8601形式に変換（時刻を含む）
    入力: Unix timestamp or datetime object or "YYYY/MM/DD HH:MM:SS"
    出力: "2026-05-20T14:07:00+09:00" (日本時間)
    """
    if not date_input:
        return None
    
    # Unix timestampの場合
    if isinstance(date_input, (int, float)):
        dt = datetime.fromtimestamp(date_input)
        # 日本時間（UTC+9）で出力
        return dt.strftime('%Y-%m-%dT%H:%M:%S+09:00')
    
    # datetimeオブジェクトの場合
    if isinstance(date_input, datetime):
        return date_input.strftime('%Y-%m-%dT%H:%M:%S+09:00')
    
    # 文字列の場合
    date_str = str(date_input).strip()
    
    # YYYY/MM/DD HH:MM:SS形式
    if '/' in date_str and ':' in date_str:
        try:
            # 日付と時刻を分離
            parts = date_str.split()
            if len(parts) >= 2:
                date_part = parts[0]  # YYYY/MM/DD
                time_part = parts[1]  # HH:MM:SS or HH:MM
                
                date_components = date_part.split('/')
                time_components = time_part.split(':')
                
                if len(date_components) == 3:
                    year = date_components[0]
                    month = date_components[1].zfill(2)
                    day = date_components[2].zfill(2)
                    
                    hour = time_components[0].zfill(2) if len(time_components) > 0 else '00'
                    minute = time_components[1].zfill(2) if len(time_components) > 1 else '00'
                    second = time_components[2].zfill(2) if len(time_components) > 2 else '00'
                    
                    return f"{year}-{month}-{day}T{hour}:{minute}:{second}+09:00"
        except Exception as e:
            print(f"[NotionUploader] 日時解析エラー: {e}")
            return None
    
    # 時刻がない場合は日付のみのフォーマットにフォールバック
    return format_date_for_notion(date_str)


def check_person_exists(notion: Client, database_id: str, phone: str) -> Optional[str]: # type: ignore
    """
    【求職者DB】で同じ電話番号の人が存在するかチェック
    
    Args:
        notion: Notion Client
        database_id: 求職者DBのID
        phone: チェックする電話番号（フォーマット済み）
    
    Returns:
        存在する場合はそのページID、存在しない場合はNone
    """
    try:
        # 电话番号で検索
        print(f"[NotionUploader] 重複チェック: TEL={phone}")
        
        if not hasattr(notion, 'databases'):
            print(f"[NotionUploader] ⚠️ notion.databasesが存在しません")
            print(f"[NotionUploader] 正しいPython環境でnotion-clientをインストールしてください")
            print(f"[NotionUploader] 現在のPython: {sys.executable}")
            return None
        
        if not hasattr(notion.databases, 'query'):
            print(f"[NotionUploader] ⚠️ notion.databases.queryが存在しません")
            print(f"[NotionUploader] notion-clientのバージョンが古すぎます")
            return None
        
        # Notion APIのphone_number型はequalsフィルタをサポートしていないため
        # 全件取得（ページネーション対応）
        all_results = []
        has_more = True
        start_cursor = None
        page_count = 0
        
        while has_more:
            page_count += 1
            query_params = {
                "database_id": database_id,
                "page_size": 100
            }
            if start_cursor:
                query_params["start_cursor"] = start_cursor
            
            response = notion.databases.query(**query_params)
            all_results.extend(response.get("results", []))
            
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")
        
        # コード側で電話番号をチェック
        for page in all_results:
            properties = page.get("properties", {})
            tel_prop = properties.get("TEL", {})
            
            # phone_number型のプロパティから値を取得
            existing_phone = tel_prop.get("phone_number")
            
            if existing_phone == phone:
                page_id = page["id"]
                print(f"[NotionUploader] ✓ 既存レコード発見: {page_id} (TEL: {existing_phone})")
                return page_id
        
        print(f"[NotionUploader] ✓ 既存レコードなし（新規作成）")
        return None
    
    except AttributeError as e:
        # notion-clientのバージョンが古い可能性
        print(f"[NotionUploader] ⚠️ AttributeError: {e}")
        print(f"[NotionUploader] databases.query()がサポートされていません。重複チェックをスキップします。")
        print(f"[NotionUploader] pip install --upgrade notion-client を実行してください")
        return None
    except Exception as e:
        print(f"[NotionUploader] 求職者存在チェックエラー: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


def upload_to_person_db(
    notion: Client, # type: ignore
    database_id: str,
    applicant_data: Dict[str, Any]
) -> Optional[str]:
    """
    【求職者DB】に求職者の基本情報をアップロード
    
    Returns:
        作成されたページのID（既に存在する場合はそのID）
    """
    try:
        name_raw = applicant_data.get('name', '')
        furigana_raw = applicant_data.get('furigana', '')
        
        # 姓名と読み仮名を分離
        name, furigana = parse_name_and_furigana(name_raw, furigana_raw)
        
        if not name:
            print("[NotionUploader] 氏名が空のためスキップ")
            return None
        
        # 電話番号で既存チェック
        tel = applicant_data.get('tel', '')
        if tel:
            phone = format_phone_for_notion(tel)
            existing_id = check_person_exists(notion, database_id, phone)
            if existing_id:
                print(f"[NotionUploader] 求職者DB: {phone} は既に存在します（スキップ）")
                return existing_id
        
        # 新規作成
        properties = {
            "求職者名": {
                "title": [
                    {
                        "text": {
                            "content": name
                        }
                    }
                ]
            }
        }
        
        # フリガナ（平假名转片假名）
        if furigana:
            katakana = hiragana_to_katakana(furigana)
            properties["フリガナ"] = {
                "rich_text": [
                    {
                        "text": {
                            "content": katakana
                        }
                    }
                ]
            }
        
        # 電話番号
        if applicant_data.get('tel'):
            phone = format_phone_for_notion(applicant_data['tel'])
            properties["TEL"] = {
                "phone_number": phone
            }
        
        # メールアドレス
        if applicant_data.get('email'):
            properties["メールアドレス"] = {
                "email": applicant_data['email']
            }
        
        # 生年月日
        birth_date = format_date_for_notion(applicant_data.get('birth'))
        if birth_date:
            properties["生年月日"] = {
                "date": {
                    "start": birth_date
                }
            }
        
        # 性別
        if applicant_data.get('gender'):
            properties["性別"] = {
                "select": {
                    "name": applicant_data['gender']
                }
            }
        
        # 居住地（都道府県のみ）
        if applicant_data.get('addr'):
            prefecture = extract_prefecture(applicant_data['addr'])
            if prefecture:
                properties["居住地"] = {
                    "select": {
                        "name": prefecture
                    }
                }
        
        # ページ作成
        response = notion.pages.create(
            parent={"database_id": database_id},
            properties=properties
        )
        
        page_id = response["id"]
        print(f"[NotionUploader] ✅ 求職者DB: {name} を追加しました")
        return page_id
    
    except Exception as e:
        print(f"[NotionUploader] ❌ 求職者DBアップロードエラー: {e}")
        import traceback
        traceback.print_exc()
        return None


def upload_to_application_db(
    notion: Client, # type: ignore
    database_id: str,
    applicant_data: Dict[str, Any],
    person_page_id: Optional[str] = None
) -> bool:
    """
    【応募DB】に応募情報をアップロード（完全な求職者情報を含む）
    
    Args:
        notion: Notion Client
        database_id: 応募DBのID
        applicant_data: 応募者データ
        person_page_id: 求職者DBのページID（関連付け用）
    
    Returns:
        成功時True
    """
    try:
        name_raw = applicant_data.get('name', '')
        furigana_raw = applicant_data.get('furigana', '')
        
        # 姓名と読み仮名を分離
        name, furigana = parse_name_and_furigana(name_raw, furigana_raw)
        
        if not name:
            print("[NotionUploader] 求職者名が空のためスキップ")
            return False
        
        # properties初期化（titleは自動生成）
        properties = {}
        
        # 求職者名（関連フィールド - 求職者DBへのリレーション）
        if person_page_id:
            properties["求職者名"] = {
                "relation": [
                    {
                        "id": person_page_id
                    }
                ]
            }
        else:
            print("[NotionUploader] 警告: 求職者DBのページIDがありません")
        
        # フリガナ（平假名转片假名）
        if furigana:
            katakana = hiragana_to_katakana(furigana)
            properties["フリガナ"] = {
                "rich_text": [
                    {
                        "text": {
                            "content": katakana
                        }
                    }
                ]
            }
        
        # TEL
        if applicant_data.get('tel'):
            phone = format_phone_for_notion(applicant_data['tel'])
            properties["TEL"] = {
                "phone_number": phone
            }
        
        # メールアドレス
        if applicant_data.get('email'):
            properties["メールアドレス"] = {
                "email": applicant_data['email']
            }
        
        # 生年月日
        birth_date = format_date_for_notion(applicant_data.get('birth'))
        if birth_date:
            properties["生年月日"] = {
                "date": {
                    "start": birth_date
                }
            }
        
        # 性別
        if applicant_data.get('gender'):
            properties["性別"] = {
                "select": {
                    "name": applicant_data['gender']
                }
            }
        
        # 居住地（都道府県のみ）
        if applicant_data.get('addr'):
            prefecture = extract_prefecture(applicant_data['addr'])
            if prefecture:
                properties["居住地"] = {
                    "select": {
                        "name": prefecture
                    }
                }
        
        # 応募日時
        sent_at = applicant_data.get('sent_at')
        if sent_at:
            app_datetime = format_datetime_for_notion(sent_at)
            if app_datetime:
                properties["応募日時"] = {
                    "date": {
                        "start": app_datetime
                    }
                }
        else:
            # sent_atがない場合は現在日時
            properties["応募日時"] = {
                "date": {
                    "start": datetime.now().strftime('%Y-%m-%dT%H:%M:%S+09:00')
                }
            }
        
        # 応募媒体（固定：求人ボックス）
        properties["応募媒体"] = {
            "select": {
                "name": "求人ボックス"
            }
        }
        
        # 応募企業
        if applicant_data.get('employer_name'):
            properties["応募企業"] = {
                "rich_text": [
                    {
                        "text": {
                            "content": applicant_data['employer_name']
                        }
                    }
                ]
            }
        
        # 応募勤務地
        work_location = []
        if applicant_data.get('work_prefecture'):
            work_location.append(applicant_data['work_prefecture'])
        if applicant_data.get('work_address'):
            work_location.append(applicant_data['work_address'])
        
        if work_location:
            properties["応募勤務地"] = {
                "rich_text": [
                    {
                        "text": {
                            "content": ''.join(work_location)
                        }
                    }
                ]
            }
        
        # ページ作成
        notion.pages.create(
            parent={"database_id": database_id},
            properties=properties
        )
        
        print(f"[NotionUploader] ✅ 応募DB: {name} の応募情報を追加しました")
        return True
    
    except Exception as e:
        print(f"[NotionUploader] ❌ 応募DBアップロードエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def upload_applicant_to_notion(applicant_data: Dict[str, Any]) -> bool:
    """
    求職者情報をNotionにアップロード（メインエントリーポイント）
    
    処理フロー：
    1. 【求職者DB】で氏名をチェック
       - 存在しない → 新規追加
       - 存在する → スキップ
    2. 【応募DB】に応募情報を追加（毎回）
    
    Args:
        applicant_data: 求職者データ
            - name: 氏名
            - furigana: フリガナ
            - tel: 電話番号
            - email: メールアドレス
            - birth: 生年月日
            - age: 年齢
            - gender: 性別
            - addr: 居住地
            - job_title: 求人タイトル
            - employer_name: 掲載企業
            - account_name: アカウント名
            - sent_at: 応募日時（Unix timestamp）
    
    Returns:
        成功時True
    """
    if not Client:
        print("[NotionUploader] notion-client未インストール、Notionアップロードをスキップします")
        return False
    
    try:
        # 設定ファイルを読み込む
        config = load_config()
        if not config:
            print("[NotionUploader] notion_config.jsonが見つかりません")
            return False
        
        # 有効/無効チェック
        if not config.get('enabled', False):
            print("[NotionUploader] Notionアップロードは無効化されています（config.enabled=false）")
            return False
        
        # API Key チェック
        api_key = config.get('api_key')
        if not api_key:
            print("[NotionUploader] Notion API Keyが設定されていません")
            return False
        
        # データベースID チェック
        person_db_config = config.get('databases', {}).get('求職者DB', {})
        app_db_config = config.get('databases', {}).get('応募DB', {})
        
        person_db_id = person_db_config.get('database_id')
        app_db_id = app_db_config.get('database_id')
        
        if not person_db_id or not app_db_id:
            print("[NotionUploader] データベースIDが設定されていません")
            return False
        
        # Notion Client 初期化
        notion = Client(auth=api_key)
        
        # 1. 【求職者DB】に追加（重複チェック付き）
        person_page_id = upload_to_person_db(notion, person_db_id, applicant_data)
        
        # デバッグ情報
        if person_page_id:
            print(f"[NotionUploader] 求職者DBページID: {person_page_id}")
        else:
            print(f"[NotionUploader] ⚠️ 求職者DBページIDがNullです")
        
        # 2. 【応募DB】に追加（毎回）
        success = upload_to_application_db(notion, app_db_id, applicant_data, person_page_id)
        
        return success
    
    except Exception as e:
        print(f"[NotionUploader] ❌ Notionアップロード全体エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # テスト用
    test_data = {
        'name': 'テスト太郎',
        'furigana': 'テストタロウ',
        'tel': '09012345678',
        'email': 'test@example.com',
        'gender': '男性',
        'age': 25,
        'birth': '1999/01/01',
        'addr': '東京都',
        'account_name': '株式会社テスト',
        'job_title': 'エンジニア募集',
        'employer_name': '株式会社サンプル',
        'sent_at': None,  # Noneの場合は現在時刻
    }
    
    print("=" * 60)
    print("Notion アップロードテスト")
    print("=" * 60)
    result = upload_applicant_to_notion(test_data)
    print(f"\nテスト結果: {'成功 ✅' if result else '失敗 ❌'}")
