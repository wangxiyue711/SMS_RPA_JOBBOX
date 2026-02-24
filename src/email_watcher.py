import imaplib
import email
import re
import time
import getpass
import sys
import os
from email.header import decode_header
import smtplib
from email.message import EmailMessage
import requests
import json
import base64
from typing import Optional
import unicodedata
import threading
from datetime import datetime, timedelta
import traceback
import socket
import html

# ============ 固定URL配置 ============
# 求人ボックスのログインページURL（メールから取得しなくなったため固定）
JOBBOX_LOGIN_URL = 'https://secure.kyujinbox.com/login'


def prompt_input(prompt, default=None):
    if default:
        v = input(f"{prompt} [{default}]: ")
        return v.strip() or default
    return input(f"{prompt}: ").strip()


def safe_set_memo_and_save(jb, memo_text, context=""):
    """安全地保存memo，处理WebDriverセッション错误"""
    try:
        jb.set_memo_and_save(memo_text)
        return True
    except Exception as e:
        error_msg = str(e)
        if 'HTTPConnectionPool' in error_msg and 'Max retries exceeded' in error_msg:
            print(f'メモ保存{context}時にWebDriverセッションエラーが発生しました: ブラウザが閉じられた可能性があります')
        elif 'WebDriver セッションが無効です' in error_msg:
            print(f'メモ保存{context}時にWebDriverセッションが無効になりました: ブラウザが閉じられた可能性があります')
        else:
            print(f'メモ保存{context}時に例外が発生しました: {e}')
        return False


def decode_subject(raw):
    if not raw:
        return ''
    parts = decode_header(raw)
    subject = ''
    for part, enc in parts:
        if isinstance(part, bytes):
            try:
                subject += part.decode(enc or 'utf-8')
            except Exception:
                subject += part.decode('utf-8', errors='ignore')
        else:
            subject += part
    return subject


def parse_jobbox_body(body):
    # 提取所需字段
    account_name = ''
    account_id = ''
    job_title = ''
    # url = ''  # 不再从邮件中提取URL，改用固定值
    
    # 支持多种邮件格式：既有【アカウント名】也有普通的 'アカウント名:'
    m = re.search(r'【?アカウント名】?[:：\s]*\s*(.+)', body)
    if m:
        account_name = m.group(1).strip()
    m = re.search(r'【?アカウントID】?[:：\s]*\s*(.+)', body)
    if m:
        account_id = m.group(1).strip()
    m = re.search(r'【?求人タイトル】?[:：\s]*\s*(.+)', body)
    if m:
        job_title = m.group(1).strip()
    
    # 提取応募No.（支持多种格式）
    oubo_no = ''
    m = re.search(r'【?応募No.?】?[:：\s]*([A-Za-z0-9\-]+)', body)
    if not m:
        m = re.search(r'応募No.?[:：\s]*([A-Za-z0-9\-]+)', body)
    if m:
        oubo_no = m.group(1).strip()
    
    # 提取掲載企業名 / 企業名 / 掲載会社 等表示发布企业名的字段
    employer_name = ''
    m = re.search(r'【?(?:掲載企業名|企業名|掲載会社)】?[:：\s]*\s*(.+)', body)
    if m:
        employer_name = m.group(1).strip()
    
    return {
        'account_name': account_name,
        'account_id': account_id,
        'job_title': job_title,
        'url': JOBBOX_LOGIN_URL,  # 使用固定URL
        'oubo_no': oubo_no,
        'employer_name': employer_name
    }


def parse_engage_body(body):
    """
    解析エンゲージ的应募通知邮件正文
    主题关键词: 【要対応】新着応募のお知らせ
    
    邮件格式示例（可能是转发消息）:
    ---------- Forwarded message ----------
    From: エンゲージ事務局 <system@en-gage.net>
    ...
    株式会社 P.P/東京本社
    上田 真義様
    
    エンゲージ事務局です。
    貴社の採用ページより応募がありました。
    
    【 応募職種 】
    【社会人経験なしでも高収入可】ゲームテスター...
    
    【 応募内容の閲覧用URL 】
    https://en-gage.net/company/manage/message/?apply_id=MTg0MTI0MzI=
    
    返回提取的信息字典
    """
    result = {
        'account_name': '',
        'job_title': '',
        'url': '',
        'employer_name': ''
    }
    
    # 提取アカウント名（在"エンゲージ事務局です"之前的公司名）
    # 方法1: 查找"エンゲージ事務局です"之前的非空行，且包含"株式会社"或"会社"等关键词
    lines = body.split('\n')
    engage_idx = -1
    for i, line in enumerate(lines):
        if 'エンゲージ事務局です' in line:
            engage_idx = i
            break
    
    if engage_idx > 0:
        # 向上查找最近的包含公司名特征的行
        for i in range(engage_idx - 1, -1, -1):
            line = lines[i].strip()
            # 跳过空行和邮件头信息
            if not line or line.startswith('To:') or line.startswith('From:') or line.startswith('Date:') or line.startswith('Subject:') or line.startswith('----------') or line.startswith('<') or '@' in line:
                continue
            # 如果包含"様"，跳过（这是收件人姓名）
            if '様' in line:
                continue
            # 如果包含公司特征词，或者是第一个非特殊字符的行
            if any(kw in line for kw in ['株式会社', '会社', '有限会社', '合同会社', '本社', '支社', '事業所']):
                result['account_name'] = line
                result['employer_name'] = line
                break
            # 如果这是一个普通文本行（非邮件头），也可能是公司名
            elif len(line) > 2 and not line.startswith('-') and not line.startswith('='):
                result['account_name'] = line
                result['employer_name'] = line
                break
    
    # 方法2: 如果上面没找到，尝试用正则表达式匹配公司名模式
    if not result['account_name']:
        # 在整个邮件中搜索公司名模式（在"エンゲージ事務局です"之前）
        engage_pos = body.find('エンゲージ事務局です')
        if engage_pos > 0:
            before_engage = body[:engage_pos]
            # 查找包含"株式会社"等的行
            m = re.search(r'((?:株式会社|有限会社|合同会社|合資会社)[^\n]+?)(?:\n|$)', before_engage)
            if m:
                result['account_name'] = m.group(1).strip()
                result['employer_name'] = result['account_name']
    
    # 提取【 応募職種 】（可能有多种格式）
    # 格式1: 【 応募職種 】
    m = re.search(r'【\s*応募職種\s*】\s*\n\s*(.+?)(?:\n|$)', body, re.MULTILINE)
    if m:
        result['job_title'] = m.group(1).strip()
    else:
        # 格式2: 【応募職種】（无空格）
        m = re.search(r'【応募職種】\s*\n\s*(.+?)(?:\n|$)', body, re.MULTILINE)
        if m:
            result['job_title'] = m.group(1).strip()
    
    # 提取【 応募内容の閲覧用URL 】（可能有多种格式）
    # 格式1: 【 応募内容の閲覧用URL 】
    m = re.search(r'【\s*応募内容の閲覧用URL\s*】\s*\n\s*(https?://[^\s]+)', body, re.MULTILINE)
    if m:
        result['url'] = m.group(1).strip()
    else:
        # 格式2: 【応募内容の閲覧用URL】（无空格）
        m = re.search(r'【応募内容の閲覧用URL】\s*\n\s*(https?://[^\s]+)', body, re.MULTILINE)
        if m:
            result['url'] = m.group(1).strip()
        else:
            # 格式3: 直接查找en-gage.net的URL
            m = re.search(r'(https://en-gage\.net/company/manage/message/\?apply_id=[A-Za-z0-9=]+)', body)
            if m:
                result['url'] = m.group(1).strip()
    
    if result['url']:
        # 从URL中提取apply_id作为oubo_no
        apply_id_match = re.search(r'apply_id=([A-Za-z0-9=]+)', result['url'])
        if apply_id_match:
            result['oubo_no'] = apply_id_match.group(1)
    
    return result


def normalize_phone_number(number):
    """Normalize and validate phone number for SMS PUBLISHER.

    Returns (normalized_number, is_valid, reason).
    - Removes non-digit chars.
    - If starts with '0' and env SMS_DEFAULT_COUNTRY is set (e.g. '81'),
      it will convert leading 0 to that country code.
    - Acceptable lengths: 6..20 digits (provider accepts various lengths);
      for numbers starting with '0' prefer 10 or 11 (JP style).
    """
    if not number:
        return ('', False, '空の番号')
    s = re.sub(r"\D+", '', str(number))
    if not s:
        return ('', False, '数字が含まれていません')

    # If starts with 0 (national format), optionally add country code
    if s.startswith('0'):
        # common Japan handling: 10 or 11 digits
        if len(s) not in (10, 11):
            # still allow but mark as suspicious
            reason = f'国内番号だが長さが期待値外({len(s)})'
        else:
            reason = ''
        default_cc = os.environ.get('SMS_DEFAULT_COUNTRY')
        if default_cc:
            # convert to international by replacing leading 0
            normalized = default_cc + s[1:]
            return (normalized, True if 6 <= len(normalized) <= 20 else False, reason or '国内->国際変換実施')
        else:
            # keep as-is (provider may accept), but validate length
            valid = len(s) >= 6 and len(s) <= 20
            return (s, valid, reason or ('長さ不正' if not valid else ''))

    # If already in international format (e.g., starts with country code)
    if 6 <= len(s) <= 20:
        return (s, True, '')
    return (s, False, f'長さが不正({len(s)})')


def to81FromLocal(number):
    """Convert local Japanese number starting with 0 to international 81 format.

    Examples:
      09012345678 -> 819012345678
      0312345678 -> 81312345678
    Returns converted string or None if conversion not applicable.
    """
    if not number:
        return None
    s = re.sub(r"\D+", '', str(number))
    if not s:
        return None
    # Already international with 81
    if s.startswith('81'):
        return s
    # Local national format starting with 0
    if s.startswith('0') and len(s) >= 9:
        return '81' + s[1:]
    # fallback: if starts with +81
    if s.startswith('+81'):
        return s.replace('+', '')
    return None
    return None


def get_api_settings(uid):
    """
    从 Firestore 读取 accounts/{uid}/api_settings/settings
    返回 dict: { provider, baseUrl, apiId, apiPass }
    """
    if not uid:
        return {}
    sa_candidates = [
        os.path.join(os.getcwd(), 'service-account'),
        os.path.join(os.path.dirname(__file__), '..', 'service-account'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account'),
        os.path.join(os.getcwd(), 'src', 'service-account'),
    ]
    sa_file = None
    for c in sa_candidates:
        if os.path.isfile(c):
            sa_file = c
            break
    if not sa_file:
        # fallback to envs only
        return {
            'provider': os.environ.get('SMS_PROVIDER') or os.environ.get('API_PROVIDER'),
            'baseUrl': os.environ.get('SMS_PUBLISHER_BASEURL') or os.environ.get('API_BASEURL'),
            'apiId': os.environ.get('SMS_PUBLISHER_APIID') or os.environ.get('API_ID'),
            'apiPass': os.environ.get('SMS_PUBLISHER_APIPASS') or os.environ.get('SMS_PUBLISHER_TOKEN') or os.environ.get('API_PASS')
        }
    try:
        import json
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception:
        # can't read service account -> fallback to envs
        return {
            'provider': os.environ.get('SMS_PROVIDER') or os.environ.get('API_PROVIDER'),
            'baseUrl': os.environ.get('SMS_PUBLISHER_BASEURL') or os.environ.get('API_BASEURL'),
            'apiId': os.environ.get('SMS_PUBLISHER_APIID') or os.environ.get('API_ID'),
            'apiPass': os.environ.get('SMS_PUBLISHER_APIPASS') or os.environ.get('SMS_PUBLISHER_TOKEN') or os.environ.get('API_PASS')
        }
    project = sa.get('project_id')
    if not project:
        return {}
    url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/api_settings/settings'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        fields = data.get('fields', {})
        res = {}
        res['provider'] = fields.get('provider', {}).get('stringValue') if fields.get('provider') else None
        res['baseUrl'] = fields.get('baseUrl', {}).get('stringValue') if fields.get('baseUrl') else None
        res['apiId'] = fields.get('apiId', {}).get('stringValue') if fields.get('apiId') else None
        res['apiPass'] = fields.get('apiPass', {}).get('stringValue') if fields.get('apiPass') else None
        # Fallback to environment variables for any missing values
        if not res.get('provider'):
            res['provider'] = os.environ.get('SMS_PROVIDER') or os.environ.get('API_PROVIDER')
        if not res.get('baseUrl'):
            res['baseUrl'] = os.environ.get('SMS_PUBLISHER_BASEURL') or os.environ.get('API_BASEURL')
        if not res.get('apiId'):
            res['apiId'] = os.environ.get('SMS_PUBLISHER_APIID') or os.environ.get('API_ID')
        if not res.get('apiPass'):
            res['apiPass'] = os.environ.get('SMS_PUBLISHER_APIPASS') or os.environ.get('SMS_PUBLISHER_TOKEN') or os.environ.get('API_PASS')
        return res
    except Exception:
        # If Firestore read fails at runtime, still try environment variables
        fallback = {
            'provider': os.environ.get('SMS_PROVIDER') or os.environ.get('API_PROVIDER'),
            'baseUrl': os.environ.get('SMS_PUBLISHER_BASEURL') or os.environ.get('API_BASEURL'),
            'apiId': os.environ.get('SMS_PUBLISHER_APIID') or os.environ.get('API_ID'),
            'apiPass': os.environ.get('SMS_PUBLISHER_APIPASS') or os.environ.get('SMS_PUBLISHER_TOKEN') or os.environ.get('API_PASS')
        }
        return fallback

def pick_and_rotate_template(uid):
    """Module-level helper: decide A/B and best-effort update nextSmsTemplate in Firestore.

    Returns chosen 'A' or 'B'.
    """
    sa_candidates = [
        os.path.join(os.getcwd(), 'service-account'),
        os.path.join(os.path.dirname(__file__), '..', 'service-account'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account'),
        os.path.join(os.getcwd(), 'src', 'service-account'),
    ]
    sa_file = None
    for c in sa_candidates:
        if os.path.isfile(c):
            sa_file = c; break
    if not sa_file:
        return 'A'  # fallback
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception:
        return 'A'
    project = sa.get('project_id')
    if not project:
        return 'A'

    doc_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/target_settings/settings'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        r = requests.get(doc_url, headers=headers, timeout=8)
        if r.status_code != 200:
            return 'A'
        data = r.json()
        fields = data.get('fields', {})
        useA = True if (not fields.get('smsUseA')) else (fields.get('smsUseA', {}).get('booleanValue') is True)
        useB = True if (not fields.get('smsUseB')) else (fields.get('smsUseB', {}).get('booleanValue') is True)
        next_t = 'A'
        if fields.get('nextSmsTemplate') and fields.get('nextSmsTemplate').get('stringValue'):
            next_t = fields.get('nextSmsTemplate').get('stringValue')

        # Decide chosen and next
        if next_t == 'A' and useA:
            chosen = 'A'
            new_next = 'B' if useB else 'A'
        elif next_t == 'B' and useB:
            chosen = 'B'
            new_next = 'A' if useA else 'B'
        else:
            # fallback: pick A if available else B
            if useA:
                chosen = 'A'
                new_next = 'B' if useB else 'A'
            elif useB:
                chosen = 'B'
                new_next = 'A'
            else:
                # none enabled -> default A
                return 'A'

        # write back new_next (best-effort)
        patch_body = {'fields': {'nextSmsTemplate': {'stringValue': new_next}}}
        # PATCH to the document path
        try:
            # Use updateMask to update only the nextSmsTemplate field to avoid
            # replacing the whole document (which would clear other fields).
            r2 = requests.patch(
                doc_url,
                params={'updateMask.fieldPaths': 'nextSmsTemplate'},
                headers={**headers, 'Content-Type': 'application/json'},
                json=patch_body,
                timeout=8,
            )
            # ignore result; best-effort
        except Exception:
            pass
        return chosen
    except Exception:
        return 'A'


def _find_service_account_file():
    sa_candidates = [
        os.path.join(os.getcwd(), 'service-account'),
        os.path.join(os.path.dirname(__file__), '..', 'service-account'),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account'),
        os.path.join(os.getcwd(), 'src', 'service-account'),
    ]
    for c in sa_candidates:
        if os.path.isfile(c):
            return c
    return None


def _get_mail_settings(uid: str) -> dict:
    """Read accounts/{uid}/mail_settings/settings from Firestore using service account file.

    Returns dict with possible keys 'email', 'appPass', 'replyEmail', 'replyAppPass'.
    Empty dict on failure.
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        return {}
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception:
        return {}

    project = sa.get('project_id') if isinstance(sa, dict) else None
    if not project:
        return {}
    url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/mail_settings/settings'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        fields = data.get('fields', {})
        res = {}
        if 'email' in fields:
            res['email'] = fields.get('email', {}).get('stringValue')
        if 'appPass' in fields:
            res['appPass'] = fields.get('appPass', {}).get('stringValue')
        if 'replyEmail' in fields:
            res['replyEmail'] = fields.get('replyEmail', {}).get('stringValue')
        if 'replyAppPass' in fields:
            res['replyAppPass'] = fields.get('replyAppPass', {}).get('stringValue')
        return res
    except Exception:
        return {}
    


def _extract_string_value(field):
    """Extract string value from Firestore field."""   
    return field.get('stringValue', '')

def _extract_bool_value(field):
    """Extract boolean value from Firestore field."""
    return field.get('booleanValue', False)

def _extract_int_value(field):
    """Extract integer value from Firestore field."""
    return int(field.get('integerValue', 0))

def _extract_conditions(conditions_field):
    """Extract conditions from Firestore mapValue."""
    if conditions_field.get('mapValue'):
        fields = conditions_field['mapValue'].get('fields', {})
        return {
            'nameTypes': _extract_name_types(fields.get('nameTypes', {})),
            'genders': _extract_genders(fields.get('genders', {})),
            'ageRanges': _extract_age_ranges(fields.get('ageRanges', {}))
        }
    return {}

def _extract_name_types(name_types_field):
    """Extract nameTypes from Firestore mapValue."""
    if name_types_field.get('mapValue'):
        fields = name_types_field['mapValue'].get('fields', {})
        return {
            'kanji': _extract_bool_value(fields.get('kanji', {})),
            'katakana': _extract_bool_value(fields.get('katakana', {})),
            'hiragana': _extract_bool_value(fields.get('hiragana', {})),
            'alpha': _extract_bool_value(fields.get('alpha', {}))
        }
    return {}


def _get_target_segments(uid: Optional[str]) -> list:
    """Read enabled segments from accounts/{uid}/target_segments.

    Returns list of segment dicts sorted by priority. Each segment contains
    id, title, enabled, priority, conditions, actions.
    """
    sa_file = _find_service_account_file()
    if not sa_file or not uid:
        return []
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception:
        return []

    project = sa.get('project_id') if isinstance(sa, dict) else None
    if not project:
        return []

    collection_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/target_segments'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        r = requests.get(collection_url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        documents = data.get('documents', [])
        segments = []
        for doc in documents:
            fields = doc.get('fields', {})
            seg = {
                'id': doc.get('name', '').split('/')[-1],
                'title': _extract_string_value(fields.get('title', {})),
                'enabled': _extract_bool_value(fields.get('enabled', {})),
                'priority': _extract_int_value(fields.get('priority', {})),
                'conditions': _extract_conditions(fields.get('conditions', {})),
                'actions': _extract_actions(fields.get('actions', {})),
            }
            if seg['enabled']:
                segments.append(seg)
        segments.sort(key=lambda x: x.get('priority', 0))
        return segments
    except Exception as e:
        print(f'Error reading target_segments: {e}')
        return []


def _get_engage_target_segments(uid: Optional[str]) -> list:
    """Read enabled segments from accounts/{uid}/engage_target_segments for エンゲージ.

    Returns list of segment dicts sorted by priority. Each segment contains
    id, title, enabled, priority, conditions, actions.
    """
    sa_file = _find_service_account_file()
    if not sa_file or not uid:
        return []
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception:
        return []

    project = sa.get('project_id') if isinstance(sa, dict) else None
    if not project:
        return []

    collection_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/engage_target_segments'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        r = requests.get(collection_url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        data = r.json()
        documents = data.get('documents', [])
        segments = []
        for doc in documents:
            fields = doc.get('fields', {})
            seg = {
                'id': doc.get('name', '').split('/')[-1],
                'title': _extract_string_value(fields.get('title', {})),
                'enabled': _extract_bool_value(fields.get('enabled', {})),
                'priority': _extract_int_value(fields.get('priority', {})),
                'conditions': _extract_conditions(fields.get('conditions', {})),
                'actions': _extract_actions(fields.get('actions', {})),
            }
            if seg['enabled']:
                segments.append(seg)
        segments.sort(key=lambda x: x.get('priority', 0))
        return segments
    except Exception as e:
        print(f'Error reading engage_target_segments: {e}')
        return []


def _get_engage_mail_settings(uid: str) -> dict:
    """Read accounts/{uid}/engage_mail_settings/settings from Firestore.

    Returns dict with possible keys 'email', 'appPass', 'replyEmail', 'replyAppPass'.
    Empty dict on failure.
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        return {}
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception:
        return {}

    project = sa.get('project_id') if isinstance(sa, dict) else None
    if not project:
        return {}
    url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/engage_mail_settings/settings'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return {}
        data = r.json()
        fields = data.get('fields', {})
        res = {}
        if 'email' in fields:
            res['email'] = fields['email'].get('stringValue')
        if 'appPass' in fields:
            res['appPass'] = fields['appPass'].get('stringValue')
        if 'replyEmail' in fields:
            res['replyEmail'] = fields['replyEmail'].get('stringValue')
        if 'replyAppPass' in fields:
            res['replyAppPass'] = fields['replyAppPass'].get('stringValue')
        return res
    except Exception:
        return {}


def _extract_genders(genders_field):
    """Extract genders from Firestore mapValue."""
    if genders_field.get('mapValue'):
        fields = genders_field['mapValue'].get('fields', {})
        return {
            'male': _extract_bool_value(fields.get('male', {})),
            'female': _extract_bool_value(fields.get('female', {}))
        }
    return {}

def _extract_age_ranges(age_ranges_field):
    """Extract ageRanges from Firestore mapValue."""
    if age_ranges_field.get('mapValue'):
        fields = age_ranges_field['mapValue'].get('fields', {})
        return {
            'maleMin': _extract_int_value(fields.get('maleMin', {})),
            'maleMax': _extract_int_value(fields.get('maleMax', {})),
            'femaleMin': _extract_int_value(fields.get('femaleMin', {})),
            'femaleMax': _extract_int_value(fields.get('femaleMax', {}))
        }
    return {}

def _extract_actions(actions_field):
    """Extract actions from Firestore mapValue."""
    if actions_field.get('mapValue'):
        fields = actions_field['mapValue'].get('fields', {})
        return {
            'sms': _extract_sms_action(fields.get('sms', {})),
            'mail': _extract_mail_action(fields.get('mail', {}))
        }
    return {}


def calc_age_from_birth_str(birth_str):
    """尝试从各种常见出生日期字符串解析出精确年龄。

    支持格式示例：
      - "1990年10月30日"
      - "1990-10-30" / "1990/10/30"
      - "1990年10月"
      - 仅年份 "1990"

    返回整数年龄（精确到月日），解析失败返回 None。
    """
    if not birth_str:
        return None
    try:
        import re
        from datetime import datetime

        s = str(birth_str).strip()

        # 1) YYYY年M月D日
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            b = datetime(y, mo, d)
            today = datetime.now()
            age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
            return age

        # 2) YYYY-M-D or YYYY/M/D
        m2 = re.search(r"(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})", s)
        if m2:
            y, mo, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            b = datetime(y, mo, d)
            today = datetime.now()
            age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
            return age

        # 3) YYYY年M月 (no day) -> assume day=1 for conservative calc
        m3 = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", s)
        if m3:
            y, mo = int(m3.group(1)), int(m3.group(2))
            b = datetime(y, mo, 1)
            today = datetime.now()
            age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
            return age

        # 4) Only year
        m4 = re.search(r"(\d{4})", s)
        if m4:
            y = int(m4.group(1))
            # Fallback to year-only: still return approximate age but indicate it's approximate by returning int
            from datetime import datetime as _dt
            return _dt.now().year - y

        return None
    except Exception:
        return None

def _extract_sms_action(sms_field):
    """Extract SMS action from Firestore mapValue."""
    if sms_field.get('mapValue'):
        fields = sms_field['mapValue'].get('fields', {})
        return {
            'enabled': _extract_bool_value(fields.get('enabled', {})),
            'text': _extract_string_value(fields.get('text', {})),
            'sendMode': _extract_string_value(fields.get('sendMode', {})) or 'immediate',
            'scheduledTime': _extract_string_value(fields.get('scheduledTime', {})) or '09:00',
            'delayMinutes': _extract_int_value(fields.get('delayMinutes', {})) or 30
        }
    return {}

def _extract_mail_action(mail_field):
    """Extract mail action from Firestore mapValue."""
    if mail_field.get('mapValue'):
        fields = mail_field['mapValue'].get('fields', {})
        return {
            'enabled': _extract_bool_value(fields.get('enabled', {})),
            'subject': _extract_string_value(fields.get('subject', {})),
            'body': _extract_string_value(fields.get('body', {})),
            'sendMode': _extract_string_value(fields.get('sendMode', {})) or 'immediate',
            'scheduledTime': _extract_string_value(fields.get('scheduledTime', {})) or '09:00',
            'delayMinutes': _extract_int_value(fields.get('delayMinutes', {})) or 30
        }
    return {}


def apply_template_tokens(template_text: str, data_map: dict) -> str:
    """Replace template tokens like {{applicant_name}}, {{job_title}}, {{company}}.

    - data_map: dict that may contain keys 'applicant_name', 'job_title', 'company' or
      their synonyms. Values will be stringified. If template contains HTML tags,
      inserted values will be HTML-escaped to avoid injecting raw HTML.
    """
    if not template_text:
        return template_text
    try:
        import html as _html
    except Exception:
        _html = None

    text = str(template_text)
    is_html = bool(re.search(r'<[^>]+>', text))

    # normalise data_map values to strings
    norm_map = {}
    for k, v in (data_map or {}).items():
        try:
            norm_map[str(k)] = '' if v is None else str(v)
        except Exception:
            norm_map[str(k)] = ''

    # helper to resolve synonyms
    def resolve_key(key: str) -> str:
        k = key.lower()
        # applicant name
        if k in ('applicant_name', 'applicant', 'name', '氏名'):
            return norm_map.get('applicant_name') or norm_map.get('name') or norm_map.get('氏名') or ''
        # employer / poster company / 掲載企業名 / 企業名 / 会社名 (publishing company)
        if k in ('employer_name', 'employer', 'poster_company', '掲載企業名', '企業名', '会社名'):
            return (
                norm_map.get('employer_name')
                or norm_map.get('employer')
                or norm_map.get('poster_company')
                or norm_map.get('企業名')
                or norm_map.get('掲載企業名')
                or norm_map.get('会社名')
                or ''
            )
        # job title / position / 求人タイトル / 職種
        if k in ('position', 'job_title', 'jobtitle', '求人タイトル', '職種'):
            return (
                norm_map.get('job_title')
                or norm_map.get('position')
                or norm_map.get('求人タイトル')
                or norm_map.get('職種')
                or ''
            )
        # company / account name / アカウント名 (account/recruiter name, distinct from 会社名)
        if k in ('company', 'account_name', 'accountname', 'アカウント名'):
            return norm_map.get('company') or norm_map.get('account_name') or norm_map.get('accountname') or norm_map.get('アカウント名') or ''
        # generic fallback
        return norm_map.get(key) or norm_map.get(key.lower()) or ''

    # Support ASCII word chars plus Hiragana/Katakana/Kanji inside token keys
    token_re = re.compile(r"{{\s*([a-zA-Z0-9_\u3040-\u30ff\u4e00-\u9fff]+)\s*}}")

    def _repl(m):
        key = m.group(1)
        val = resolve_key(key)
        if is_html and _html:
            return _html.escape(val)
        return val

    try:
        return token_re.sub(_repl, text)
    except Exception:
        return text


def _match_segment_conditions(applicant_detail, segment_conditions):
    """
    Check if applicant matches segment conditions.
    Returns True ONLY if ALL THREE conditions match: name, gender, and age.
    
    applicant_detail: dict with keys like name, age, gender, etc.
    segment_conditions: dict with nameTypes, genders, ageRanges
    """
    # Get applicant data - ALL THREE are required
    name = applicant_detail.get('name', '').strip()
    gender = applicant_detail.get('gender', '').strip()  # '男性' or '女性'
    age = applicant_detail.get('age', 0)
    
    # All three fields must be present
    if not name or not gender or not age:
        return False
    
    # 1. Check name type condition
    name_type = _detect_name_type(name)
    name_conditions = segment_conditions.get('nameTypes', {})
    
    # Name type condition must be set and match
    if not name_conditions.get(name_type, False):
        return False
    
    # 2. Check gender condition
    gender_conditions = segment_conditions.get('genders', {})
    
    if gender == '男性':
        if not gender_conditions.get('male', False):
            return False
    elif gender == '女性':
        if not gender_conditions.get('female', False):
            return False
    else:
        return False  # Unknown gender
    
    # 3. Check age range condition
    age_ranges = segment_conditions.get('ageRanges', {})
    
    if gender == '男性':
        min_age = age_ranges.get('maleMin', 0)
        max_age = age_ranges.get('maleMax', 999)
        if not (min_age <= age <= max_age):
            return False
    elif gender == '女性':
        min_age = age_ranges.get('femaleMin', 0)
        max_age = age_ranges.get('femaleMax', 999)
        if not (min_age <= age <= max_age):
            return False
    
    # All three conditions passed
    return True


def _detect_name_type(name):
    """
    Detect the type of name (kanji, katakana, hiragana, alpha).
    Returns the primary type found.
    """
    if not name:
        return 'alpha'
    
    # Count different character types
    kanji_count = 0
    katakana_count = 0
    hiragana_count = 0
    alpha_count = 0
    
    for char in name:
        if '\u4e00' <= char <= '\u9fff':  # CJK Unified Ideographs (Kanji)
            kanji_count += 1
        elif '\u30a0' <= char <= '\u30ff':  # Katakana
            katakana_count += 1
        elif '\u3040' <= char <= '\u309f':  # Hiragana
            hiragana_count += 1
        elif char.isalpha():  # ASCII letters
            alpha_count += 1
    
    # Return the most common type
    counts = {
        'kanji': kanji_count,
        'katakana': katakana_count, 
        'hiragana': hiragana_count,
        'alpha': alpha_count
    }
    
    # counts.get may return Optional[int], which can confuse static type checkers
    # Provide a key function that always returns int (default 0) to be explicit.
    return max(counts, key=lambda k: counts.get(k, 0))


def _find_matching_segment(applicant_detail, segments):
    """
    Find the first segment that matches the applicant.
    Returns the matching segment or None.
    Segments are already sorted by priority.
    """
    for i, segment in enumerate(segments):
        segment_title = segment.get('title', f'セグメント{i+1}')
        if _match_segment_conditions(applicant_detail, segment['conditions']):
            print(f"【{segment_title}】対象。")
            return segment
        else:
            print(f"【{segment_title}】非対象。")
    return None


def send_mail_once(from_addr, app_pass, to_addr, subject, body):
    """Send a single email using SMTP SSL (Gmail compatible).

    from_addr: full email address used as sender
    app_pass: 16-char app password
    to_addr: recipient email
    subject/body: strings
    Returns (success, info_dict)
    """
    if not to_addr:
        return (False, {'note': 'no recipient'})
    if not from_addr or not app_pass:
        return (False, {'note': 'missing sender credentials'})
    dry = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')
    if dry:
        print(f"[DRY_RUN_MAIL] would send mail from={from_addr} to={to_addr} subj={subject}")
        return (True, {'note': 'dry_run'})
    try:
        from email.header import Header
        from email.utils import parseaddr, formataddr
        msg = EmailMessage()

        # Helper: attempt to extract a pure ASCII addr-spec; fallback to regex
        def _extract_addr(addr):
            a = str(addr or '')
            name, email_addr = parseaddr(a)
            # If parseaddr gave an ASCII addr-spec, accept it
            if email_addr and all(ord(c) < 128 for c in email_addr):
                return (name or '', email_addr)
            # fallback: find ascii-like addr via regex
            m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", a)
            if m:
                return (name or '', m.group(0))
            # nothing usable
            return (name or '', '')

        # Parse and build headers with UTF-8 display names
        from_name, from_email = _extract_addr(from_addr)
        to_name, to_email = _extract_addr(to_addr)

        debug = os.environ.get('DEBUG_MAIL', 'false').lower() in ('1', 'true', 'yes')
        if debug:
            print(f"[DEBUG_MAIL] parsed from_name={repr(from_name)} from_email={repr(from_email)}")
            print(f"[DEBUG_MAIL] parsed to_name={repr(to_name)} to_email={repr(to_email)}")

        # If we couldn't extract a pure ascii addr-spec for envelope, fail clearly
        if not from_email or not to_email:
            return (False, {'error': 'invalid_envelope_address', 'from_raw': str(from_addr), 'to_raw': str(to_addr), 'note': 'failed to extract ASCII addr-spec for SMTP envelope'})

        # Header values: allow non-ASCII display names
        from_header = formataddr((str(Header(from_name or '', 'utf-8')), from_email))
        to_header = formataddr((str(Header(to_name or '', 'utf-8')), to_email))
        msg['From'] = from_header
        msg['To'] = to_header
        # Ensure UTF-8 safe subject and body for Japanese text
        msg['Subject'] = str(Header(subject or '', 'utf-8'))
        
        # Check if body contains HTML tags (simple detection)
        body_content = body or ''
        is_html = bool(re.search(r'<[^>]+>', body_content))
        
        if is_html:
            # Set HTML content with fallback plain text
            import html
            plain_text = html.unescape(re.sub(r'<[^>]+>', '', body_content))
            msg.set_content(plain_text, charset='utf-8')
            msg.add_alternative(body_content, subtype='html', charset='utf-8')
        else:
            # Plain text content
            msg.set_content(body_content, charset='utf-8')
        # Use Gmail SMTP by default
        smtp_host = os.environ.get('EMAIL_SMTP_HOST', 'smtp.gmail.com')
        smtp_port = int(os.environ.get('EMAIL_SMTP_PORT', '465'))
        debug = os.environ.get('DEBUG_MAIL', 'false').lower() in ('1', 'true', 'yes')
        if debug:
            print(f"[DEBUG_MAIL] connecting SMTP_SSL host={smtp_host} port={smtp_port}")
        # Ensure local_hostname used for EHLO/HELO is ASCII-only to avoid
        # smtplib attempting to encode a non-ASCII hostname with ascii codec.
        try:
            import socket
            lh = os.environ.get('EMAIL_SMTP_LOCALHOST') or socket.getfqdn()
            # if contains non-ascii, fall back
            try:
                lh.encode('ascii')
            except Exception:
                lh = 'localhost'
        except Exception:
            lh = 'localhost'

        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20, local_hostname=lh) as s:
            if debug:
                print(f"[DEBUG_MAIL] login as {from_email}")
            s.login(from_email, app_pass)
            # Envelope addresses must be ASCII addr-specs; use parsed emails
            if debug:
                print(f"[DEBUG_MAIL] send_message envelope from={from_email} to={to_email}")
            s.send_message(msg, from_addr=from_email, to_addrs=[to_email])
        return (True, {'note': 'sent'})
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return (False, {'error': str(e), 'traceback': tb})


def _send_html_mail(from_addr, app_pass, to_addr, subject, html_body):
    """Send HTML email with automatic fallback to plain text.
    
    This function specifically handles HTML content from the rich text editor.
    """
    return send_mail_once(from_addr, app_pass, to_addr, subject, html_body)


def send_via_sms_publisher(to_number, body, api_cfg):
    """Send SMS via SMS PUBLISHER (module-level function shared by both jobbox and engage).

    Supports:
    - GET or POST (tries POST, can be configured by api_cfg['method'])
    - Authentication: Bearer token (apiPass), Basic (apiId/apiPass), or param-based (apiId/apiPass in query/form)
    - Success criteria: HTTP 2xx OR JSON body with truthy `success`/`ok` field.

    api_cfg keys: baseUrl, apiId, apiPass, method (optional 'GET'|'POST'), path (optional)
    """
    dry_run = os.environ.get("DRY_RUN_SMS", "false").lower() in ("1", "true", "yes")
    if dry_run:
        print(f"DRY_RUN_SMS enabled — would send to {to_number}: {body}")
        return (True, {'note': 'dry_run'})

    base = api_cfg.get("baseUrl") or os.environ.get("SMS_PUBLISHER_BASEURL")
    api_id = api_cfg.get("apiId") or os.environ.get("SMS_PUBLISHER_APIID")
    api_pass = api_cfg.get("apiPass") or os.environ.get("SMS_PUBLISHER_APIPASS")
    method = (api_cfg.get("method") or os.environ.get("SMS_PUBLISHER_METHOD") or "POST").upper()
    path = api_cfg.get("path") or os.environ.get("SMS_PUBLISHER_PATH") or "/send"

    if not base:
        print("No SMS PUBLISHER baseUrl configured.")
        return (False, {'error': 'no baseUrl'})

    # If base contains a non-root path, respect it as the full endpoint.
    # Only append `path` when base is host/root only.
    from urllib.parse import urlparse
    try:
        parsed = urlparse(base)
        if parsed.path and parsed.path not in ('', '/'):
            url = base
        else:
            url = base.rstrip('/') + (path if path.startswith('/') else '/' + path)
    except Exception:
        url = base.rstrip('/') + (path if path.startswith('/') else '/' + path)
    
    headers = {"Accept": "application/json"}
    timeout = int(os.environ.get("SMS_PUBLISHER_TIMEOUT", "15"))

    # Build auth and params/payload
    params = {}
    data = {}
    json_payload = None
    auth = None

    # Standard field names we will try (align with working example)
    field_to = api_cfg.get("fieldTo") or os.environ.get("SMS_PUBLISHER_FIELD_TO") or "mobilenumber"
    field_message = api_cfg.get("fieldMessage") or os.environ.get("SMS_PUBLISHER_FIELD_MESSAGE") or "smstext"

    # Prefer Bearer token if api_pass present and api_cfg indicates token or no api_id provided
    if api_pass and (not api_id or api_cfg.get("auth") == "bearer"):
        headers["Authorization"] = f"Bearer {api_pass}"
        # ensure values are strings as provider requires JSON values quoted
        json_payload = {field_to: str(to_number), field_message: str(body)}

    # If auth explicitly basic
    elif api_id and api_pass and api_cfg.get("auth") == "basic":
        # Build Basic auth header (Base64 of id:pass) per provider docs
        import base64
        pair = f"{api_id}:{api_pass}"
        enc = base64.b64encode(pair.encode('utf-8')).decode('ascii')
        headers['Authorization'] = f"Basic {enc}"
        # prefer form-encoded for basic auth but ensure values sent as strings
        data = {field_to: str(to_number), field_message: str(body)}
        json_payload = None

    # Param-based API key (apiId/apiPass as query params)
    elif api_id and api_pass and api_cfg.get("auth") == "params":
        # params-based auth: add apiId/apiPass to query/form
        params.update({"apiId": api_id, "apiPass": api_pass})
        params.update({field_to: str(to_number), field_message: str(body)})

    # Flexible fallback: prefer Basic when both apiId and apiPass exist,
    # otherwise fall back to Bearer if only apiPass present, else unauthenticated JSON.
    else:
        if api_id and api_pass:
            # prefer Basic auth when username+password available
            import base64
            pair = f"{api_id}:{api_pass}"
            enc = base64.b64encode(pair.encode('utf-8')).decode('ascii')
            headers['Authorization'] = f"Basic {enc}"
            data = {field_to: str(to_number), field_message: str(body)}
        elif api_pass:
            headers["Authorization"] = f"Bearer {api_pass}"
            json_payload = {field_to: str(to_number), field_message: str(body)}
        else:
            # No credentials: still try unauthenticated call with JSON
            json_payload = {field_to: str(to_number), field_message: str(body)}

    # Ensure headers for form posts
    headers.setdefault('User-Agent', 'sms-rpa/1.0')
    headers.setdefault('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8')

    try:
        if method == "GET":
            # Use params for GET
            req_params = params.copy()
            if json_payload:
                req_params.update(json_payload)
            if data:
                req_params.update(data)
            r = requests.get(url, headers=headers, params=req_params, timeout=timeout)
        else:
            # POST
            if json_payload is not None:
                r = requests.post(url, headers=headers, json=json_payload, params=params, timeout=timeout,
                                  auth=locals().get('auth', None))
            elif data:
                r = requests.post(url, headers=headers, data=data, params=params, timeout=timeout,
                                  auth=locals().get('auth', None))
            else:
                r = requests.post(url, headers=headers, json={field_to: to_number, field_message: body}, params=params,
                                  timeout=timeout, auth=locals().get('auth', None))

        # If provider returns 560 (invalid mobile), try converting to 81-prefixed and retry once
        if r.status_code == 560:
            try:
                alt = to81FromLocal(str(to_number))
            except Exception:
                alt = None
            if alt:
                data_alt = dict(data) if data else {}
                data_alt[field_to] = alt
                print('Retrying with 81 prefixed number:', alt)
                r2 = requests.post(url, headers=headers, data=data_alt, params=params, timeout=timeout)
                # treat r2
                if 200 <= r2.status_code < 300:
                    info_r2 = {'status_code': r2.status_code, 'text': r2.text[:2000]}
                    try:
                        info_r2['json'] = r2.json()
                    except Exception:
                        pass
                    print('送信成功(リトライ)', info_r2)
                    return (True, info_r2)
                else:
                    info_r2 = {'status_code': r2.status_code, 'text': r2.text[:2000]}
                    print('送信失敗(リトライ)', info_r2)
                    return (False, info_r2)

        # Check HTTP status
        info_r = {'status_code': r.status_code, 'text': r.text[:2000]}
        if 200 <= r.status_code < 300:
            try:
                info_r['json'] = r.json()
            except Exception:
                pass
            print(f"SMS PUBLISHER returned 2xx for {to_number}: {r.status_code}")
            return (True, info_r)
        else:
            print(f"SMS PUBLISHER HTTP {r.status_code}: {r.text[:1000]}")
            return (False, info_r)

    except requests.RequestException as e:
        print(f"Network error sending SMS via SMS PUBLISHER: {e}")
        return (False, {'error': str(e)})


def send_sms_router(to_number, body, provider, api_settings):
    """Route SMS sending to appropriate provider (module-level function shared by both jobbox and engage).
    
    Args:
        to_number: Phone number to send to
        body: Message body
        provider: Provider name (e.g., 'sms_publisher')
        api_settings: API configuration dict
    
    Returns: (success, info)
    """
    if provider == 'sms_publisher':
        return send_via_sms_publisher(to_number, body, api_settings)
    # fallback: dry run / log
    dry = os.environ.get('DRY_RUN_SMS') in ('1','true','True')
    if dry:
        print(f"[DRY_RUN] SMS ({provider}) => to={to_number} body={body}")
        return (True, {'note': 'dry_run'})
    print(f"未対応のプロバイダ: {provider} - ログに記録します。")
    with open('sms_outbox.log', 'a', encoding='utf-8') as f:
        f.write(f"{time.time()}\t{provider}\t{to_number}\t{body}\n")
    return (True, {'note': 'logged'})


def send_auto_reply_if_configured(uid, mail_cfg, is_target, detail, jb=None):
    """If target settings request auto-reply, send mail to candidate.

    This helper can be called for both target and non-target candidates.
    """
    try:
        mail_cfg = mail_cfg or {}
    except Exception:
        mail_cfg = {}
    # Ensure auto is defined regardless of whether exception occurred above
    auto = bool(mail_cfg.get('autoReply', False))
    debug = os.environ.get('DEBUG_MAIL', 'false').lower() in ('1', 'true', 'yes')
    if not auto:
        if debug:
            print('[DEBUG_MAIL] autoReply is disabled -> skip sending')
        return (False, False, {'note': 'autoReply disabled'})

    # Accept multiple possible keys for email address
    to_email = (
        detail.get('email')
        or detail.get('メール')
        or detail.get('メールアドレス')
        or detail.get('mail')
        or detail.get('Mail')
        or detail.get('emailAddress')
        or detail.get('Email')
        or ''
    )
    should_send = False
    if is_target and mail_cfg.get('mailUseTarget', True):
        should_send = True
    if (not is_target) and mail_cfg.get('mailUseNonTarget', False):
        should_send = True
    if not should_send:
        if debug:
            print(f"[DEBUG_MAIL] should_send=false (is_target={is_target}, mailUseTarget={mail_cfg.get('mailUseTarget', True)}, mailUseNonTarget={mail_cfg.get('mailUseNonTarget', False)}) -> skip")
        return (False, False, {'note': 'send suppressed by mailUseTarget/mailUseNonTarget'})
    if not to_email:
        msg = 'メール送信を要求されていますが、送信先メールアドレスがありません。スキップします。'
        if debug:
            print('[DEBUG_MAIL]', msg)
        else:
            print(msg)
        return (False, False, {'error': 'missing recipient'})

    subj = mail_cfg.get('mailSubjectA') if is_target else mail_cfg.get('mailSubjectB')
    body = mail_cfg.get('mailTemplateA') if is_target else mail_cfg.get('mailTemplateB')

    # get sender creds from env or cloud
    mail_settings = _get_mail_settings(uid) if uid else {}
    sender = mail_settings.get('replyEmail') or os.environ.get('EMAIL_WATCHER_ADDR') or mail_settings.get('email')
    sender_pass = mail_settings.get('replyAppPass') or os.environ.get('EMAIL_WATCHER_PASS') or mail_settings.get('appPass')
    if not sender:
        msg = '送信元メールアドレスが見つかりません。メール送信をスキップします。'
        if debug:
            print('[DEBUG_MAIL]', msg)
        else:
            print(msg)
        return (False, False, {'error': 'missing sender'})

    mail_dry = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')
    if mail_dry:
        print(f"[DRY_RUN_MAIL] would send mail from={sender} to={to_email} subj={subj}")
        if debug:
            print('[DEBUG_MAIL] DRY_RUN_MAIL is enabled -> no real send')
        # Treat dry-run as not actually attempted so callers don't treat it as a real send
        return (False, False, {'note': 'dry_run'})

    # Apply template tokens using detail map if available (detail keys expected by caller)
    try:
        data_for_mail = {}
        # Debug: print detail input to check if employer_name is present
        if debug:
            print(f"[DEBUG_MAIL] detail keys: {list(detail.keys()) if isinstance(detail, dict) else 'not dict'}")
            if isinstance(detail, dict) and 'employer_name' in detail:
                print(f"[DEBUG_MAIL] detail.employer_name: '{detail.get('employer_name')}'")
        
        # Build a rich data map with multiple synonym keys (English + Japanese)
        if isinstance(detail, dict):
            # Applicant name
            name_val = detail.get('name') or detail.get('\u6c0f\u540d') or detail.get('氏名')
            data_for_mail['applicant_name'] = name_val
            data_for_mail['name'] = name_val
            data_for_mail['氏名'] = name_val

            # Job title / position (several possible source keys)
            jt = (
                detail.get('job_title')
                or detail.get('\u6c42\u4eba\u30bf\u30a4\u30c8\u30eb')
                or detail.get('jobTitle')
                or detail.get('求人タイトル')
                or detail.get('職種')
            )
            data_for_mail['job_title'] = jt
            data_for_mail['position'] = jt
            data_for_mail['jobtitle'] = jt
            data_for_mail['求人タイトル'] = jt
            data_for_mail['職種'] = jt

            # Company / account name (several possible source keys)
            comp = (
                detail.get('account_name')
                or detail.get('\u30a2\u30ab\u30a6\u30f3\u30c8\u540d')
                or detail.get('company')
                or detail.get('会社名')
                or detail.get('アカウント名')
            )
            data_for_mail['company'] = comp
            data_for_mail['account_name'] = comp
            data_for_mail['accountname'] = comp
            data_for_mail['会社名'] = comp
            data_for_mail['アカウント名'] = comp
            # Employer / poster company (distinct from account_name)
            emp = (
                detail.get('employer_name')
                or detail.get('\u6392\u8868\u4f1a\u793e\u540d')
                or detail.get('掲載企業名')
                or detail.get('企業名')
                or detail.get('poster_company')
            )
            data_for_mail['employer_name'] = emp
            data_for_mail['employer'] = emp
            data_for_mail['掲載企業名'] = emp
            data_for_mail['企業名'] = emp
            data_for_mail['会社名'] = emp  # 追加：会社名トークン用
    except Exception:
        data_for_mail = {}

    try:
        # Debug print of the data map and raw templates to help diagnose missing fields
        if debug:
            try:
                printable = {}
                for k, v in (data_for_mail or {}).items():
                    try:
                        printable[k] = (v[:120] + '...') if isinstance(v, str) and len(v) > 120 else v
                    except Exception:
                        printable[k] = v
                print('[DEBUG_MAIL] data_for_mail:', printable)
                print('[DEBUG_MAIL] raw subj:', (subj or '')[:200])
                print('[DEBUG_MAIL] raw body :', re.sub(r'\s+', ' ', (body or ''))[:300])
            except Exception:
                pass
        subj_to_send = apply_template_tokens(subj or '', data_for_mail)
        body_to_send = apply_template_tokens(body or '', data_for_mail)

        # Diagnostic: if template contains tokens whose values are empty, log details
        try:
            token_re = re.compile(r"{{\s*([a-zA-Z0-9_\u3040-\u30ff\u4e00-\u9fff]+)\s*}}")
            raw_tokens = set(token_re.findall((subj or '') + ' ' + (body or '')))
            missing = []
            if raw_tokens:
                for tk in raw_tokens:
                    k = tk.lower()
                    val = ''
                    # resolve similarly to apply_template_tokens
                    if k in ('applicant_name', 'applicant', 'name', '氏名'):
                        val = (data_for_mail.get('applicant_name') or data_for_mail.get('name') or data_for_mail.get('氏名') or '')
                    elif k in ('position', 'job_title', 'jobtitle', '求人タイトル', '職種'):
                        val = (data_for_mail.get('job_title') or data_for_mail.get('position') or data_for_mail.get('求人タイトル') or data_for_mail.get('職種') or '')
                    elif k in ('employer_name', 'employer', 'poster_company', '掲載企業名', '企業名', '会社名'):
                        val = (data_for_mail.get('employer_name') or data_for_mail.get('employer') or data_for_mail.get('poster_company') or data_for_mail.get('企業名') or data_for_mail.get('掲載企業名') or data_for_mail.get('会社名') or '')
                    elif k in ('company', 'account_name', 'accountname', 'アカウント名'):
                        val = (data_for_mail.get('company') or data_for_mail.get('account_name') or data_for_mail.get('accountname') or data_for_mail.get('アカウント名') or '')
                    else:
                        val = data_for_mail.get(tk) or data_for_mail.get(k) or ''
                    if not val:
                        missing.append(tk)
            if missing:
                try:
                    import datetime
                    ts = datetime.datetime.utcnow().isoformat() + 'Z'
                    logline = {
                        'ts': ts,
                        'uid': uid,
                        'to': to_email,
                        'missing_tokens': missing,
                        'raw_subj': (subj or '')[:300],
                        'raw_body_excerpt': re.sub(r'\s+', ' ', (body or ''))[:400],
                    }
                    # Trim data_for_mail for logging
                    printable = {}
                    for k, v in (data_for_mail or {}).items():
                        try:
                            s = v if v is not None else ''
                            s = str(s)
                            printable[k] = s[:200] + '...' if len(s) > 200 else s
                        except Exception:
                            printable[k] = ''
                    logline['data_for_mail'] = printable
                    try:
                        os.makedirs(os.path.join(os.getcwd(), 'logs'), exist_ok=True)
                        with open(os.path.join(os.getcwd(), 'logs', 'watcher.log'), 'a', encoding='utf-8') as lf:
                            lf.write(str(logline) + '\n')
                    except Exception:
                        pass
                    if debug:
                        print('[DEBUG_MAIL] missing token values detected:', logline)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        subj_to_send = subj or ''
        body_to_send = body or ''

    ok_mail, info_mail = send_mail_once(sender, sender_pass, to_email, subj_to_send, body_to_send)
    if ok_mail:
        print(f"メール送信成功: to={to_email}")
        try:
            # NOTE: remove direct memo write here to avoid duplicate memo lines.
            # The caller will construct a mail_note and call jb.set_memo_and_save once.
            pass
        except Exception:
            pass
        return (True, True, info_mail if isinstance(info_mail, dict) else {'note': str(info_mail)})
    else:
        print(f"メール送信失敗: to={to_email} info={info_mail}")
        return (True, False, info_mail if isinstance(info_mail, dict) else {'note': str(info_mail)})


def _make_fields_for_firestore(doc: dict) -> dict:
    fields = {}
    for k, v in doc.items():
        if v is None:
            continue
        if isinstance(v, bool):
            fields[k] = {'booleanValue': v}
        elif isinstance(v, int):
            fields[k] = {'integerValue': str(v)}
        elif isinstance(v, dict):
            # nested map
            fields[k] = {'mapValue': {'fields': _make_fields_for_firestore(v)}}
        else:
            fields[k] = {'stringValue': str(v)}
    return fields


def create_scheduled_task(uid: str, task_type: str, task_data: dict) -> bool:
    """Create a scheduled task in Firestore under accounts/{uid}/scheduled_tasks.
    
    Args:
        uid: User ID
        task_type: 'sms' or 'mail'
        task_data: dict containing:
            - scheduledTime: 'HH:mm' format
            - to: recipient (phone number for SMS, email for mail)
            - template: message template with tokens
            - applicant_detail: dict with applicant info for token replacement
            - subject: (for mail only) email subject
            - segment_id: ID of the segment that triggered this task
            - oubo_no: 応募No
            
    Returns True on success.
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        print('service-account file not found; cannot create scheduled task')
        return False
    
    try:
        import json
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        print(f'Failed to get service account token: {e}')
        return False
    
    project = sa.get('project_id')
    if not project:
        print('No project_id in service account')
        return False
    
    # Calculate next execution datetime based on scheduledTime
    from datetime import datetime, timedelta
    import re
    
    scheduled_time = task_data.get('scheduledTime', '09:00')
    match = re.match(r'(\d{1,2}):(\d{2})', scheduled_time)
    if not match:
        print(f'Invalid scheduledTime format: {scheduled_time}')
        return False
    
    hour, minute = int(match.group(1)), int(match.group(2))
    now = datetime.now()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # If the time has passed today, schedule for tomorrow
    if next_run <= now:
        next_run += timedelta(days=1)
    
    print(f'時刻送信登録: {next_run.strftime("%m/%d %H:%M")}')
    
    # Create task document
    task_doc = {
        'uid': uid,
        'taskType': task_type,
        'status': 'pending',
        'scheduledTime': scheduled_time,
        'nextRun': int(next_run.timestamp() * 1000),  # milliseconds
        'createdAt': int(datetime.now().timestamp() * 1000),
        'to': task_data.get('to', ''),
        'template': task_data.get('template', ''),
        'applicantDetail': task_data.get('applicant_detail', {}),
        'segmentId': task_data.get('segment_id', ''),
        'ouboNo': task_data.get('oubo_no', ''),
    }
    
    if task_type == 'mail':
        task_doc['subject'] = task_data.get('subject', '')
    
    fields = _make_fields_for_firestore(task_doc)
    
    collection_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/scheduled_tasks'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        r = requests.post(collection_url, headers=headers, json={'fields': fields}, timeout=10)
        if r.status_code not in (200, 201):
            print(f'タスク登録失敗: {r.status_code}')
            return False
        return True
    except Exception as e:
        print(f'エラー: {e}')
        return False


def create_delayed_task(uid: str, task_type: str, next_run: int, task_data: dict) -> bool:
    """Create a delayed task in Firestore under accounts/{uid}/scheduled_tasks.
    
    Args:
        uid: User ID
        task_type: 'sms' or 'mail'
        next_run: Unix timestamp (seconds) when the task should execute
        task_data: dict containing:
            - delayMinutes: number of minutes to delay
            - to: recipient (phone number for SMS, email for mail)
            - template: message template with tokens
            - applicant_detail: dict with applicant info for token replacement
            - subject: (for mail only) email subject
            - segment_id: ID of the segment that triggered this task
            - oubo_no: 応募No
            
    Returns True on success.
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        print('service-account file not found; cannot create delayed task')
        return False
    
    try:
        import json
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        print(f'Failed to get service account token: {e}')
        return False
    
    project = sa.get('project_id')
    if not project:
        print('No project_id in service account')
        return False
    
    from datetime import datetime
    delay_minutes = task_data.get('delayMinutes', 30)
    print(f'予約送信登録: {delay_minutes}分後')
    
    # Create task document
    task_doc = {
        'uid': uid,
        'taskType': task_type,
        'status': 'pending',
        'sendMode': 'delayed',
        'delayMinutes': delay_minutes,
        'nextRun': int(next_run * 1000),  # convert seconds to milliseconds
        'createdAt': int(datetime.now().timestamp() * 1000),
        'to': task_data.get('to', ''),
        'template': task_data.get('template', ''),
        'applicantDetail': task_data.get('applicant_detail', {}),
        'segmentId': task_data.get('segment_id', ''),
        'ouboNo': task_data.get('oubo_no', ''),
    }
    
    if task_type == 'mail':
        task_doc['subject'] = task_data.get('subject', '')
    
    fields = _make_fields_for_firestore(task_doc)
    
    collection_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/scheduled_tasks'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        r = requests.post(collection_url, headers=headers, json={'fields': fields}, timeout=10)
        if r.status_code not in (200, 201):
            print(f'予約タスク登録失敗: {r.status_code}')
            return False
        return True
    except Exception as e:
        print(f'エラー: {e}')
        return False


def write_sms_history(uid: str, doc: dict) -> bool:
    """Write a minimal sms_history document under accounts/{uid}/sms_history using service account.

    Returns True on success.
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        print('service-account file not found; cannot write history')
        return False

    # Helper: load service account and obtain access token
    sa = None
    token = None
    project = None
    try:
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
        project = sa.get('project_id')
    except Exception:
        sa = None
        token = None
        project = None

    # Try multiple matching strategies to find an existing history doc to merge into.
    # Strategies (priority order):
    # 1) oubo_no + tel (recent window)
    # 2) oubo_no + email (recent)
    # 3) tel + email (recent)
    # 4) email only (within short time window)
    try:
        if token and project and uid and doc:
            oubo = (doc.get('oubo_no') or doc.get('oubo') or '').strip()
            tel = (doc.get('tel') or doc.get('電話番号') or '').strip()
            email_addr = (doc.get('email') or doc.get('メール') or '').strip()
            now_ts = int(time.time())
            recent_threshold = 300
            short_threshold = 120
            run_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents:runQuery'
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

            # helper to run a structuredQuery and return first document (or None)
            def _run_query(filters, limit=1, order_by_sentAt=False):
                body = {"structuredQuery": {"from": [{"collectionId": "sms_history"}], "limit": limit}}
                if filters:
                    if len(filters) == 1:
                        body['structuredQuery']['where'] = filters[0]
                    else:
                        body['structuredQuery']['where'] = {"compositeFilter": {"op": "AND", "filters": filters}}
                if order_by_sentAt:
                    body['structuredQuery']['orderBy'] = [{"field": {"fieldPath": "sentAt"}, "direction": "DESC"}]
                try:
                    r = requests.post(run_url, headers=headers, json=body, timeout=8)
                    if r.status_code != 200:
                        return None
                    results = r.json()
                    for item in results:
                        if item.get('document'):
                            return item.get('document')
                except Exception:
                    return None
                return None

            # build simple fieldFilter helper
            def ff(fieldPath, op, value, valueType='stringValue'):
                return {"fieldFilter": {"field": {"fieldPath": fieldPath}, "op": op, "value": {valueType: str(value)}}}

            # Strategy 1: oubo + tel (recent)
            existing_doc = None
            if oubo and tel:
                filters = [ff('oubo_no', 'EQUAL', oubo), ff('tel', 'EQUAL', tel), ff('sentAt', 'GREATER_THAN', now_ts - recent_threshold, valueType='integerValue')]
                existing_doc = _run_query(filters, limit=1, order_by_sentAt=True)

            # Strategy 2: oubo + email
            if not existing_doc and oubo and email_addr:
                filters = [ff('oubo_no', 'EQUAL', oubo), ff('email', 'EQUAL', email_addr), ff('sentAt', 'GREATER_THAN', now_ts - recent_threshold, valueType='integerValue')]
                existing_doc = _run_query(filters, limit=1, order_by_sentAt=True)

            # Strategy 3: tel + email
            if not existing_doc and tel and email_addr:
                filters = [ff('tel', 'EQUAL', tel), ff('email', 'EQUAL', email_addr), ff('sentAt', 'GREATER_THAN', now_ts - recent_threshold, valueType='integerValue')]
                existing_doc = _run_query(filters, limit=1, order_by_sentAt=True)

            # Strategy 4: email only within short window
            if not existing_doc and email_addr:
                filters = [ff('email', 'EQUAL', email_addr), ff('sentAt', 'GREATER_THAN', now_ts - short_threshold, valueType='integerValue')]
                existing_doc = _run_query(filters, limit=1, order_by_sentAt=True)

            # Helper: read Firestore field value
            def _read_field(f):
                if not f:
                    return None
                if 'stringValue' in f:
                    return f.get('stringValue')
                if 'integerValue' in f:
                    try:
                        return int(f.get('integerValue'))
                    except Exception:
                        return f.get('integerValue')
                if 'booleanValue' in f:
                    return f.get('booleanValue')
                if 'mapValue' in f:
                    mv = f.get('mapValue', {}).get('fields', {})
                    return {k: _read_field(v) for k, v in mv.items()}
                return None

            if existing_doc:
                existing_name = existing_doc.get('name')
                existing_fields = existing_doc.get('fields', {})

                # extract existing channel states/responses
                existing_sms_state = _read_field(existing_fields.get('sms_status'))
                existing_mail_state = _read_field(existing_fields.get('mail_status'))
                existing_resp = _read_field(existing_fields.get('response')) or {}
                existing_sentAt = _read_field(existing_fields.get('sentAt'))

                # infer incoming states from doc
                inc_sms_state = None
                inc_mail_state = None
                inc_sms_resp = None
                inc_mail_resp = None
                # If caller provided explicit sms_status/mail_status use them
                if doc.get('sms_status'):
                    inc_sms_state = doc.get('sms_status')
                if doc.get('mail_status'):
                    inc_mail_state = doc.get('mail_status')
                # else infer from status text
                sraw = (doc.get('status') or '').lower()
                if not inc_sms_state and ('送信済' in (doc.get('status') or '') or '済' in (doc.get('status') or '')) and '（m）' not in sraw and '（s）' in sraw:
                    inc_sms_state = 'sent'
                if not inc_mail_state and ('（m）' in (doc.get('status') or '') or '（M）' in (doc.get('status') or '') or 'mail' in sraw):
                    # treat as mail attempt
                    if '失敗' in (doc.get('status') or '') or 'fail' in sraw:
                        inc_mail_state = 'failed'
                    else:
                        inc_mail_state = 'sent'
                # responses
                # read response into a local variable once so type-checkers can
                # reason about its type (and to avoid calling .get on None)
                resp = doc.get('response')
                if isinstance(resp, dict):
                    # try to separate sms vs mail keys if present
                    if 'sms' in resp:
                        inc_sms_resp = resp.get('sms')
                    if 'mail' in resp:
                        inc_mail_resp = resp.get('mail')
                    # otherwise put as mail if email present
                    if not inc_sms_resp and not inc_mail_resp:
                        if email_addr:
                            inc_mail_resp = resp
                        else:
                            inc_sms_resp = resp
                else:
                    # primitive response -> assign based on presence of tel/email
                    if email_addr:
                        inc_mail_resp = resp
                    else:
                        inc_sms_resp = resp

                # merge states: incoming overrides existing for the channel
                final_sms_state = existing_sms_state or None
                final_mail_state = existing_mail_state or None
                if inc_sms_state:
                    final_sms_state = inc_sms_state
                if inc_mail_state:
                    final_mail_state = inc_mail_state

                # normalize helper
                def _norm(s):
                    if not s:
                        return None
                    s2 = str(s).lower()
                    if 'fail' in s2 or '失敗' in s2:
                        return 'failed'
                    if 'sent' in s2 or '送信' in s2 or '済' in s2:
                        return 'sent'
                    return s

                final_sms_state = _norm(final_sms_state)
                final_mail_state = _norm(final_mail_state)

                # merge responses
                final_resp = {}
                if existing_resp and isinstance(existing_resp, dict):
                    if 'sms' in existing_resp:
                        final_resp['sms'] = existing_resp.get('sms')
                    if 'mail' in existing_resp:
                        final_resp['mail'] = existing_resp.get('mail')
                if inc_sms_resp is not None:
                    final_resp['sms'] = inc_sms_resp
                if inc_mail_resp is not None:
                    final_resp['mail'] = inc_mail_resp

                # decide status string per user's rules
                status_str = ''
                if not final_sms_state and not final_mail_state:
                    status_str = '対象外'
                else:
                    # failures reported as failed channels
                    failed_parts = []
                    sent_parts = []
                    if final_mail_state == 'failed':
                        failed_parts.append('M')
                    if final_sms_state == 'failed':
                        failed_parts.append('S')
                    if final_mail_state == 'sent':
                        sent_parts.append('M')
                    if final_sms_state == 'sent':
                        sent_parts.append('S')

                    if failed_parts:
                        status_str = '送信失敗（' + '+'.join(failed_parts) + '）'
                    else:
                        if sent_parts:
                            order = []
                            if 'M' in sent_parts:
                                order.append('M')
                            if 'S' in sent_parts:
                                order.append('S')
                            status_str = '送信済（' + '+'.join(order) + '）'
                        else:
                            status_str = '対象外'

                # prepare write_doc fields
                write_doc = {}
                if oubo:
                    write_doc['oubo_no'] = oubo
                if tel:
                    write_doc['tel'] = tel
                if email_addr:
                    write_doc['email'] = email_addr
                # Ensure sentAt is an integer. If existing_sentAt is numeric-string, coerce it.
                try:
                    if existing_sentAt is not None and not isinstance(existing_sentAt, dict):
                        write_doc['sentAt'] = int(existing_sentAt)
                    else:
                        write_doc['sentAt'] = now_ts
                except (ValueError, TypeError):
                    write_doc['sentAt'] = now_ts
                write_doc['sms_status'] = final_sms_state
                write_doc['mail_status'] = final_mail_state
                if final_resp:
                    write_doc['response'] = final_resp
                write_doc['status'] = status_str

                # Preserve/append additional fields from incoming doc.
                # IMPORTANT: This merge path previously patched only a minimal set of fields,
                # which caused other fields (and newly-added ones like work_prefecture/work_address)
                # to be missing in Firestore, resulting in blank CSV columns.
                def _nonempty(v):
                    if v is None:
                        return False
                    if isinstance(v, (int, bool)):
                        return True
                    return str(v).strip() != ''

                def _pick_from_doc(*keys):
                    for kk in keys:
                        try:
                            if kk in doc and _nonempty(doc.get(kk)):
                                return doc.get(kk)
                        except Exception:
                            continue
                    return None

                # Common passthrough fields
                name_val = _pick_from_doc('name', '氏名')
                if _nonempty(name_val):
                    write_doc['name'] = name_val
                gender_val = _pick_from_doc('gender', '性別')
                if _nonempty(gender_val):
                    write_doc['gender'] = gender_val
                birth_val = _pick_from_doc('birth', '生年月日')
                if _nonempty(birth_val):
                    write_doc['birth'] = birth_val
                age_val = _pick_from_doc('age')
                if _nonempty(age_val):
                    write_doc['age'] = age_val

                addr_val = _pick_from_doc('addr', '住所')
                if _nonempty(addr_val):
                    write_doc['addr'] = addr_val
                school_val = _pick_from_doc('school', '学校名')
                if _nonempty(school_val):
                    write_doc['school'] = school_val

                # Job title can appear under multiple keys
                job_title_val = _pick_from_doc('job_title', 'jobTitle', '求人タイトル', 'kyujin', 'title')
                if _nonempty(job_title_val):
                    write_doc['job_title'] = job_title_val

                # New: job posting public URL (求人URL)
                job_url_val = _pick_from_doc('job_url', 'jobUrl', '求人URL')
                if _nonempty(job_url_val):
                    write_doc['job_url'] = job_url_val

                template_val = _pick_from_doc('template')
                if _nonempty(template_val):
                    write_doc['template'] = template_val

                # Employer/company
                employer_val = _pick_from_doc('employer_name', 'employer', '会社名', '企業名', '掲載企業名')
                if _nonempty(employer_val):
                    write_doc['employer_name'] = employer_val

                # New: work location (prefecture + address)
                wp = _pick_from_doc('work_prefecture', 'workPrefecture')
                wa = _pick_from_doc('work_address', 'workAddress')
                if _nonempty(wp):
                    write_doc['work_prefecture'] = wp
                if _nonempty(wa):
                    write_doc['work_address'] = wa

                # PATCH existing document
                try:
                    patch_url = f'https://firestore.googleapis.com/v1/{existing_name}'
                    # Use updateMask to avoid deleting other existing fields.
                    params = {'updateMask.fieldPaths': ','.join(write_doc.keys())}
                    r = requests.patch(
                        patch_url,
                        headers={**headers, 'Content-Type': 'application/json'},
                        params=params,
                        json={'fields': _make_fields_for_firestore(write_doc)},
                        timeout=12,
                    )
                    if r.status_code in (200, 201):
                        try:
                            print(f'Merged sms_history into {existing_name} status={write_doc.get("status")}')
                        except Exception:
                            pass
                        return True
                    else:
                        print('Failed to patch existing sms_history:', r.status_code, r.text[:500])
                except Exception as e:
                    print('Exception patching existing sms_history:', e)

    except Exception as e:
        print('Error during matching existing sms_history (non-fatal):', e)

    # Fallback: create a new sms_history document
    try:
        if not sa:
            with open(sa_file, 'r', encoding='utf-8') as f:
                sa = json.load(f)
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
        project = sa.get('project_id')
        if not project:
            print('service account missing project_id')
            return False
        url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/sms_history'
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        body = {'fields': _make_fields_for_firestore(doc)}
        r = requests.post(url, headers=headers, json=body, timeout=15)
        if r.status_code in (200, 201):
            return True
        else:
            print(f'Firestore書き込み失敗: {r.status_code}, {r.text[:500]}')
            return False
    except Exception as e:
        print('Exception writing sms_history:', e)
        return False


def send_sms_via_api(uid, to_number, message):
    """通过API发送SMS (用于定时任务执行) - 与即时送信使用相同的逻辑
    
    Returns: (success, info)
    """
    api_cfg = get_api_settings(uid) or {}
    provider = api_cfg.get('provider', 'sms_publisher')
    base = api_cfg.get('baseUrl')
    
    if not base:
        return False, {'note': 'no base URL configured'}
    
    # Build URL - same logic as immediate send
    from urllib.parse import urlparse
    method = (api_cfg.get('method') or 'POST').upper()
    path = api_cfg.get('path') or '/send'
    
    try:
        parsed = urlparse(base)
        if parsed.path and parsed.path not in ('', '/'):
            url = base
        else:
            url = base.rstrip('/') + (path if path.startswith('/') else '/' + path)
    except Exception:
        url = base.rstrip('/') + (path if path.startswith('/') else '/' + path)
    
    api_id = api_cfg.get('apiId')
    api_pass = api_cfg.get('apiPass')
    auth_type = api_cfg.get('auth')
    
    headers = {'Accept': 'application/json'}
    headers['User-Agent'] = 'sms-rpa/1.0'
    headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
    
    # Field names (same as immediate send)
    field_to = api_cfg.get('fieldTo') or 'mobilenumber'
    field_message = api_cfg.get('fieldMessage') or 'smstext'
    
    # Build form data - replace ampersand like immediate send
    safe_msg = str(message).replace('&', '＆')
    data = {
        field_to: str(to_number),
        field_message: safe_msg,
    }
    
    # Authentication - same logic as immediate send
    if auth_type == 'bearer' and api_pass:
        headers['Authorization'] = f'Bearer {api_pass}'
    elif auth_type == 'basic' and api_id and api_pass:
        import base64
        pair = f'{api_id}:{api_pass}'
        encoded = base64.b64encode(pair.encode('utf-8')).decode('ascii')
        headers['Authorization'] = f'Basic {encoded}'
    elif auth_type == 'params' and api_id and api_pass:
        data['username'] = api_id
        data['password'] = api_pass
    else:
        # Fallback: prefer Basic when both id and pass exist
        if api_id and api_pass:
            import base64
            pair = f'{api_id}:{api_pass}'
            encoded = base64.b64encode(pair.encode('utf-8')).decode('ascii')
            headers['Authorization'] = f'Basic {encoded}'
        elif api_pass:
            headers['Authorization'] = f'Bearer {api_pass}'
    
    # Check for dry run
    dry_run = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
    if dry_run:
        return True, {'note': 'dry_run', 'status_code': 200}
    
    # Send request
    timeout = int(os.environ.get('SMS_PUBLISHER_TIMEOUT', '30'))
    try:
        r = requests.post(url, headers=headers, data=data, timeout=timeout)
        status_code = r.status_code
        
        # Handle 560 (invalid mobile) - retry with 81 prefix like immediate send
        if status_code == 560:
            alt = to81FromLocal(str(to_number))
            if alt:
                data_alt = dict(data)
                data_alt[field_to] = alt
                r = requests.post(url, headers=headers, data=data_alt, timeout=timeout)
                status_code = r.status_code
        
        # Check success - same as immediate send (200-299)
        info_r = {'status_code': status_code, 'text': r.text[:2000]}
        try:
            info_r['json'] = r.json()
        except Exception:
            pass
        
        if 200 <= status_code < 300:
            return True, info_r
        else:
            return False, info_r
    except Exception as e:
        return False, {'error': str(e)}


def get_pending_scheduled_tasks(uid):
    """获取待执行的定时任务"""
    sa_file = _find_service_account_file()
    if not sa_file:
        return []
    
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(
            sa, scopes=['https://www.googleapis.com/auth/datastore']
        )
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        print(f'[定時タスク] Failed to get token: {e}')
        return []
    
    project = sa.get('project_id')
    if not project:
        return []
    
    # Query pending tasks within execution window
    # 使用更精确的时间窗口：只执行在当前时间之前且在未来2分钟内的任务
    now = datetime.now()
    now_ms = int(now.timestamp() * 1000)
    # 允许2分钟的执行窗口（防止错过任务）
    future_window_ms = int((now.timestamp() + 120) * 1000)
    
    collection_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/scheduled_tasks'
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        r = requests.get(collection_url, headers=headers, timeout=10)
        if r.status_code != 200:
            return []
        
        data = r.json()
        documents = data.get('documents', [])
        
        tasks = []
        for doc in documents:
            doc_id = doc['name'].split('/')[-1]
            fields = doc.get('fields', {})
            
            status = fields.get('status', {}).get('stringValue', '')
            next_run = int(fields.get('nextRun', {}).get('integerValue', '0'))
            task_type = fields.get('taskType', {}).get('stringValue', '')
            scheduled_time = fields.get('scheduledTime', {}).get('stringValue', '')
            
            # Only process pending tasks that are due (within execution window)
            # 任务必须：1) 状态为pending 2) nextRun已经到达 3) 不超过未来2分钟
            if status == 'pending' and next_run <= now_ms:
                # 计算任务与当前时间的差距
                time_diff_seconds = (now_ms - next_run) / 1000
                
                # 如果任务超过10分钟还未执行，可能是系统故障导致，记录警告
                if time_diff_seconds > 600:
                    print(f'[定時任務] 警告: タスク {doc_id} は予定時刻から {int(time_diff_seconds/60)} 分遅延しています (scheduled: {scheduled_time})')
                
                # 提取任务时间信息用于日志
                next_run_dt = datetime.fromtimestamp(next_run / 1000)
                time_diff_min = int(time_diff_seconds / 60)
                
                # 简化日志：只在延迟超过2分钟时显示警告
                if time_diff_seconds > 120:
                    print(f'⚠️ タスク遅延 {time_diff_min}分 - {task_type} ({scheduled_time})')

                task_data = {
                    'id': doc_id,
                    'uid': fields.get('uid', {}).get('stringValue', ''),
                    'taskType': task_type,
                    'to': fields.get('to', {}).get('stringValue', ''),
                    'template': fields.get('template', {}).get('stringValue', ''),
                    'segmentId': fields.get('segmentId', {}).get('stringValue', ''),
                    'ouboNo': fields.get('ouboNo', {}).get('stringValue', ''),
                }
                
                # Extract applicantDetail
                applicant_detail_field = fields.get('applicantDetail', {})
                if applicant_detail_field.get('mapValue'):
                    detail_fields = applicant_detail_field['mapValue'].get('fields', {})
                    applicant_detail = {}
                    for k, v in detail_fields.items():
                        if v.get('stringValue') is not None:
                            applicant_detail[k] = v['stringValue']
                    task_data['applicantDetail'] = applicant_detail
                else:
                    task_data['applicantDetail'] = {}
                
                if task_type == 'mail':
                    task_data['subject'] = fields.get('subject', {}).get('stringValue', '')
                
                tasks.append(task_data)
        
        return tasks
    except Exception as e:
        print(f'タスク取得エラー: {e}')
        return []


def update_scheduled_task_status(uid, task_id, status, error_msg=None):
    """更新定时任务状态（失败时）或删除任务（成功时）"""
    sa_file = _find_service_account_file()
    if not sa_file:
        return False
    
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(
            sa, scopes=['https://www.googleapis.com/auth/datastore']
        )
        creds.refresh(Request())
        token = creds.token
    except Exception:
        return False
    
    project = sa.get('project_id')
    if not project:
        return False
    
    doc_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/scheduled_tasks/{task_id}'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        if status == 'completed':
            # 成功时：删除任务文档（防止重复执行）
            r = requests.delete(doc_url, headers=headers, timeout=10)
            return r.status_code in (200, 204)
        else:
            # 失败时：更新状态为failed
            update_data = {
                'status': {'stringValue': status},
                'updatedAt': {'integerValue': str(int(datetime.now().timestamp() * 1000))}
            }
            
            if error_msg:
                update_data['errorMsg'] = {'stringValue': str(error_msg)}
            
            params = {'updateMask.fieldPaths': ','.join(update_data.keys())}
            r = requests.patch(
                doc_url,
                headers=headers,
                params=params,
                json={'fields': update_data},
                timeout=10
            )
            return r.status_code in (200, 204)
    except Exception:
        return False


def execute_scheduled_sms_task(task, write_history=True):
    """执行SMS定时任务"""
    uid = task.get('uid', '')
    to_number = task.get('to', '')
    template = task.get('template', '')
    applicant_detail = task.get('applicantDetail', {})
    oubo_no = task.get('ouboNo', '')
    
    print(f'📱 SMS送信: {to_number[:3]}****{to_number[-4:]}')
    
    # Normalize phone number
    norm, ok, reason = normalize_phone_number(to_number)
    if not ok:
        print(f'❌ 電話番号エラー: {reason}')
        return False, f'invalid phone: {reason}'
    
    # Apply template tokens
    try:
        message = apply_template_tokens(template, applicant_detail)
    except Exception as e:
        message = template
    
    # Send SMS
    success, info = send_sms_via_api(uid, norm, message)
    
    # Write to history (only if write_history=True)
    if write_history and uid:
        try:
            rec = {
                'name': applicant_detail.get('applicant_name', ''),
                'gender': applicant_detail.get('gender', ''),
                'birth': applicant_detail.get('birth', ''),
                'email': applicant_detail.get('email', ''),
                'tel': norm,
                'addr': applicant_detail.get('addr', ''),
                'employer_name': applicant_detail.get('employer_name', '') or applicant_detail.get('会社名', '') or applicant_detail.get('企業名', ''),
                'work_prefecture': applicant_detail.get('work_prefecture', '') or applicant_detail.get('workPrefecture', ''),
                'work_address': applicant_detail.get('work_address', '') or applicant_detail.get('workAddress', ''),
                'school': applicant_detail.get('school', ''),
                'oubo_no': oubo_no,
                'job_title': applicant_detail.get('kyujin') or applicant_detail.get('title') or '',
                'job_url': applicant_detail.get('job_url') or applicant_detail.get('jobUrl') or '',
                'status': '送信済（S）' if success else '送信失敗（S）',
                'template': 'scheduled',
                'response': info if isinstance(info, dict) else {'note': str(info)},
                'sentAt': int(time.time())
            }
            write_sms_history(uid, rec)
        except Exception as e:
            print(f'履歴書込エラー: {e}')
    
    if success:
        print(f'✅ SMS送信完了')
        return True, None
    else:
        print(f'❌ SMS送信失敗')
        return False, str(info) if info else 'unknown error'


def execute_scheduled_mail_task(task, write_history=True):
    """执行MAIL定时任务"""
    uid = task.get('uid', '')
    to_email = task.get('to', '')
    template = task.get('template', '')
    subject_template = task.get('subject', '')
    applicant_detail = task.get('applicantDetail', {})
    oubo_no = task.get('ouboNo', '')
    
    print(f'📧 MAIL送信: {to_email}')
    
    if not to_email:
        print(f'❌ メールアドレスなし')
        return False, 'no recipient email'
    
    # Get mail settings
    mail_cfg = _get_mail_settings(uid)
    sender = mail_cfg.get('replyEmail') or mail_cfg.get('email', '')
    sender_pass = mail_cfg.get('replyAppPass') or mail_cfg.get('appPass', '')
    
    if not sender or not sender_pass:
        print(f'❌ メール設定未完了')
        return False, 'mail settings not configured'
    
    # Apply template tokens
    try:
        subject = apply_template_tokens(subject_template, applicant_detail)
        body = apply_template_tokens(template, applicant_detail)
    except Exception:
        subject = subject_template
        body = template
    
    # Send mail
    success, info = send_mail_once(sender, sender_pass, to_email, subject, body)
    
    # Write to history (only if write_history=True)
    if write_history and uid:
        try:
            rec = {
                'name': applicant_detail.get('applicant_name', ''),
                'gender': applicant_detail.get('gender', ''),
                'birth': applicant_detail.get('birth', ''),
                'email': to_email,
                'tel': applicant_detail.get('tel', ''),
                'addr': applicant_detail.get('addr', ''),
                'employer_name': applicant_detail.get('employer_name', '') or applicant_detail.get('会社名', '') or applicant_detail.get('企業名', ''),
                'work_prefecture': applicant_detail.get('work_prefecture', '') or applicant_detail.get('workPrefecture', ''),
                'work_address': applicant_detail.get('work_address', '') or applicant_detail.get('workAddress', ''),
                'school': applicant_detail.get('school', ''),
                'oubo_no': oubo_no,
                'job_title': applicant_detail.get('kyujin') or applicant_detail.get('title') or '',
                'job_url': applicant_detail.get('job_url') or applicant_detail.get('jobUrl') or '',
                'status': '送信済（M）' if success else '送信失敗（M）',
                'template': 'scheduled',
                'response': info if isinstance(info, dict) else {'note': str(info)},
                'sentAt': int(time.time())
            }
            write_sms_history(uid, rec)
        except Exception as e:
            print(f'履歴書込エラー: {e}')
    
    if success:
        print(f'✅ MAIL送信完了')
        return True, None
    else:
        print(f'❌ MAIL送信失敗')
        return False, str(info) if info else 'unknown error'


def process_scheduled_tasks_once(uid):
    """处理一次待执行的定时任务"""
    tasks = get_pending_scheduled_tasks(uid)
    if not tasks:
        return
    
    print(f'⏰ 実行タスク {len(tasks)}件')
    
    # Group tasks by (uid, oubo_no, scheduledTime) to combine SMS+MAIL into one history record
    from collections import defaultdict
    task_groups = defaultdict(list)
    
    for task in tasks:
        oubo_no = task.get('ouboNo', '')
        scheduled_time = task.get('scheduledTime', '')
        group_key = (uid, oubo_no, scheduled_time)
        task_groups[group_key].append(task)
    
    # Process each group
    for group_key, group_tasks in task_groups.items():
        sms_task = None
        mail_task = None
        
        # Separate SMS and MAIL tasks
        for task in group_tasks:
            if task.get('taskType') == 'sms':
                sms_task = task
            elif task.get('taskType') == 'mail':
                mail_task = task
        
        # Execute tasks
        sms_success = False
        sms_info = {}
        mail_success = False
        mail_info = {}
        
        if sms_task:
            try:
                # Execute SMS but DON'T write history in execute_scheduled_sms_task
                sms_success, sms_error = execute_scheduled_sms_task(sms_task, write_history=False)
                sms_info = {'note': sms_error} if sms_error else {'status': 'sent'}
                update_scheduled_task_status(uid, sms_task.get('id'), 'completed' if sms_success else 'failed', sms_error)
            except Exception as e:
                sms_info = {'error': str(e)}
                update_scheduled_task_status(uid, sms_task.get('id'), 'failed', str(e))
        
        if mail_task:
            try:
                # Execute MAIL but DON'T write history in execute_scheduled_mail_task
                mail_success, mail_error = execute_scheduled_mail_task(mail_task, write_history=False)
                mail_info = {'note': mail_error} if mail_error else {'status': 'sent'}
                update_scheduled_task_status(uid, mail_task.get('id'), 'completed' if mail_success else 'failed', mail_error)
            except Exception as e:
                mail_info = {'error': str(e)}
                update_scheduled_task_status(uid, mail_task.get('id'), 'failed', str(e))
        
        # Write COMBINED history record if any task was executed
        if sms_task or mail_task:
            try:
                # Get applicant details from either task (prefer sms_task first)
                task_with_data = sms_task if sms_task else mail_task
                if not task_with_data:
                    continue
                    
                applicant_detail = task_with_data.get('applicantDetail', {})
                oubo_no = task_with_data.get('ouboNo', '')
                
                # Determine combined status
                if sms_task and mail_task:
                    if sms_success and mail_success:
                        status = '送信済（M+S）'
                    elif sms_success and not mail_success:
                        status = '送信済（S）+送信失敗（M）'
                    elif not sms_success and mail_success:
                        status = '送信失敗（S）+送信済（M）'
                    else:
                        status = '送信失敗（M+S）'
                elif sms_task:
                    status = '送信済（S）' if sms_success else '送信失敗（S）'
                elif mail_task:
                    status = '送信済（M）' if mail_success else '送信失敗（M）'
                else:
                    status = '送信失敗（S）'
                
                # Create combined response
                combined_response = {}
                if sms_task and sms_info:
                    combined_response['sms'] = sms_info
                if mail_task and mail_info:
                    combined_response['mail'] = mail_info
                
                # Write combined history
                rec = {
                    'name': applicant_detail.get('applicant_name', ''),
                    'gender': applicant_detail.get('gender', ''),
                    'birth': applicant_detail.get('birth', ''),
                    'email': applicant_detail.get('email', ''),
                    'tel': applicant_detail.get('tel', ''),
                    'addr': applicant_detail.get('addr', ''),
                    'employer_name': applicant_detail.get('employer_name', '') or applicant_detail.get('会社名', '') or applicant_detail.get('企業名', ''),
                    'work_prefecture': applicant_detail.get('work_prefecture', '') or applicant_detail.get('workPrefecture', ''),
                    'work_address': applicant_detail.get('work_address', '') or applicant_detail.get('workAddress', ''),
                    'school': applicant_detail.get('school', ''),
                    'oubo_no': oubo_no,
                    'job_title': applicant_detail.get('kyujin') or applicant_detail.get('title') or '',
                    'job_url': applicant_detail.get('job_url') or applicant_detail.get('jobUrl') or '',
                    'status': status,
                    'template': 'scheduled',
                    'response': combined_response,
                    'sentAt': int(time.time())
                }
                write_sms_history(uid, rec)
                print(f'✅ 履歴書込: {status}')
            except Exception as e:
                print(f'❌ 履歴書込エラー: {e}')


def scheduled_task_worker(uid, stop_event):
    """后台线程：每5秒检查并执行定时任务（提高时间精确度）"""
    print('🔄 scheduled_tasks監視開始 ')
    
    while not stop_event.is_set():
        try:
            process_scheduled_tasks_once(uid)
        except Exception as e:
            print(f'エラー: {e}')
            try:
                import traceback
                tb = traceback.format_exc()
                log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
                if not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                with open(os.path.join(log_dir, 'scheduled_errors.log'), 'a', encoding='utf-8') as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] UID={uid}\n{tb}\n")
            except Exception:
                pass
        
        # Wait 5 seconds (improved accuracy for faster response)
        stop_event.wait(5)
    
    print('時刻送信監視停止')


def watch_mail(imap_host, email_user, email_pass, uid=None, folder='INBOX', poll_seconds=30, label='Mailbox', category='auto'):  # type: ignore
    import re
    print(f'[{label}] IMAPサーバー({imap_host})に接続中... User: {email_user}')
    mailbox_type = (category or 'auto').lower()
    handle_jobbox = mailbox_type in ('auto', 'jobbox')
    handle_engage = mailbox_type in ('auto', 'engage')
    max_unseen_scan = int(os.environ.get('RPA_MAX_UNREAD_SCAN', '50'))
    try:
        conn = imaplib.IMAP4_SSL(imap_host)
        conn.login(email_user, email_pass)
        print(f'[{label}] ログインしました。未読メールを監視します')
    except Exception as e:
        print(f'[{label}] ❌ ログイン失敗: {e}')
        return

    def reconnect_mailbox(reason):
        nonlocal conn
        print(f'[{label}] ⚠️  IMAP接続状態異常: {reason}')
        print(f'[{label}] 再接続を試みます...')
        try:
            try:
                conn.logout()
            except Exception:
                pass
            conn = imaplib.IMAP4_SSL(imap_host)
            conn.login(email_user, email_pass)
            select_status, _ = conn.select(folder)
            if select_status != 'OK':
                raise imaplib.IMAP4.error(f'select failed: {select_status}')
            print(f'[{label}] ✓ 再接続成功')
            return True
        except Exception as reconnect_err:
            print(f'[{label}] ❌ 再接続失敗: {reconnect_err}')
            return False

    try:
        while True:
            try:
                select_status, _ = conn.select(folder)
                if select_status != 'OK':
                    raise imaplib.IMAP4.error(f'select failed: {select_status}')
                # 查找所有未读邮件
                status, data = conn.search(None, 'UNSEEN')
            except (imaplib.IMAP4.abort, imaplib.IMAP4.error, socket.error, ConnectionResetError, OSError) as e:
                if not reconnect_mailbox(e):
                    time.sleep(poll_seconds)
                    continue
                try:
                    status, data = conn.search(None, 'UNSEEN')
                except (imaplib.IMAP4.abort, imaplib.IMAP4.error, socket.error, ConnectionResetError, OSError) as retry_err:
                    if not reconnect_mailbox(retry_err):
                        time.sleep(poll_seconds)
                    continue

            if status != 'OK':
                time.sleep(poll_seconds)
                continue
            ids = data[0].split()
            total_unseen = len(ids)
            if total_unseen > max_unseen_scan > 0:
                ids = ids[-max_unseen_scan:]
            # print(f"[{label}] [DEBUG] Found {total_unseen} unread emails in {folder}")
            if not ids:
                # 没有未读
                time.sleep(poll_seconds)
                continue
            for num in ids:
                # 先只抓头部，避免把非目标邮件标记为已读
                try:
                    status, msg_data = conn.fetch(num, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])')
                except (imaplib.IMAP4.abort, imaplib.IMAP4.error, socket.error, ConnectionResetError, OSError) as e:
                    if not reconnect_mailbox(f'fetch中: {e}'):
                        break  # 退出当前循环，等待下次监视周期
                    try:
                        # 再次尝试fetch
                        status, msg_data = conn.fetch(num, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])')
                    except (imaplib.IMAP4.abort, imaplib.IMAP4.error, socket.error, ConnectionResetError, OSError) as reconnect_err:
                        print(f'[{label}] ❌ fetch再試行失敗: {reconnect_err}')
                        break  # 退出当前循环，等待下次监视周期
                        
                if status != 'OK' or not msg_data:
                    continue
                # msg_data can contain tuples; find the first bytes payload
                hdr_bytes = None
                for part in msg_data:
                    if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], (bytes, bytearray)):
                        hdr_bytes = bytes(part[1])
                        break
                    if isinstance(part, (bytes, bytearray)):
                        hdr_bytes = bytes(part)
                        break
                subject_raw = ''
                if hdr_bytes:
                    try:
                        hdr_msg = email.message_from_bytes(hdr_bytes)
                        subject_raw = decode_subject(hdr_msg.get('Subject') or '')
                    except Exception:
                        try:
                            raw = hdr_bytes.decode('utf-8', errors='ignore')
                            subj_match = re.search(r'Subject:\s*(.*)', raw)
                            subject_raw = decode_subject(subj_match.group(1).strip()) if subj_match else ''
                        except Exception:
                            subject_raw = ''
                
                # Normalize subject to handle full-width/half-width chars consistently
                subject = unicodedata.normalize('NFKC', subject_raw) if subject_raw else ''
                
                # Detect Engage marker (brackets may normalize to ASCII, so check broadly)
                has_engage_marker = False
                if subject_raw and '要対応' in subject_raw:
                    has_engage_marker = True
                elif subject and '要対応' in subject:
                    has_engage_marker = True
                
                # print(f"[{label}] [DEBUG] 未読メール検出: {subject}")
                
                # ===== 判断求人ボックス邮件（特征：新着応募のお知らせ，但不含要対応标签）=====
                # 注意：必须排除“要対応”标记，因为那是エンゲージ邮件的特征
                is_jobbox_subject = '新着応募のお知らせ' in subject and not has_engage_marker
                if handle_jobbox and is_jobbox_subject:
                    # 获取整封邮件正文（不影响已读标记，使用 PEEK）
                    status, full = conn.fetch(num, '(BODY.PEEK[])')
                    if status != 'OK' or not full:
                        continue
                    # find bytes payload in full
                    full_bytes = None
                    for part in full:
                        if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], (bytes, bytearray)):
                            full_bytes = bytes(part[1])
                            break
                        if isinstance(part, (bytes, bytearray)):
                            full_bytes = bytes(part)
                            break
                    if not full_bytes:
                        continue
                    msg = email.message_from_bytes(full_bytes)
                    body = ''
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            if ctype == 'text/plain':
                                payload = part.get_payload(decode=True)
                                if isinstance(payload, (bytes, bytearray)):
                                    try:
                                        body = payload.decode(part.get_content_charset() or 'utf-8', errors='ignore')
                                    except Exception:
                                        body = payload.decode('utf-8', errors='ignore')
                                elif isinstance(payload, str):
                                    body = payload
                                break
                    else:
                        payload = msg.get_payload(decode=True)
                        if isinstance(payload, (bytes, bytearray)):
                            body = payload.decode(msg.get_content_charset() or 'utf-8', errors='ignore')
                        elif isinstance(payload, str):
                            body = payload
                    parsed = parse_jobbox_body(body)
                    print(f'[{label}] ---- 求人ボックスの未読メールを検出 ----')
                    print(f'[{label}] 件名:', subject)
                    print(f'[{label}] アカウント名:', parsed['account_name'])
                    print(f'[{label}] アカウントID:', parsed['account_id'])
                    print(f'[{label}] 求人タイトル:', parsed['job_title'])
                    print(f'[{label}] ログインURL（固定）:', parsed['url'])
                    # 标记为已读
                    conn.store(num, '+FLAGS', '\\Seen')
                    # アカウント名が見つかったら自動でログイン処理を実行（URLは固定値を使用）
                    if parsed.get('account_name'):
                        print(f'[{label}] アカウント情報を検出しました。固定URLを使用して自動ログイン処理を実行します。')

                        # 从 Firestore 的 jobbox_accounts 列表中查找匹配的 account_name
                        def get_jobbox_accounts(uid):
                            if not uid:
                                return []
                            # simple per-uid cache to avoid repeated expensive Firestore list calls
                            cache = getattr(get_jobbox_accounts, '_cache', None)
                            if cache is None:
                                get_jobbox_accounts._cache = {}
                                cache = get_jobbox_accounts._cache
                            CACHE_TTL = 300  # seconds
                            if uid in cache:
                                ts, accounts = cache[uid]
                                if time.time() - ts < CACHE_TTL:
                                    print(f"[{label}] [DEBUG_JOBBOX] returning cached jobbox_accounts for uid={uid} (age={int(time.time()-ts)}s)")
                                    return accounts
                            sa_candidates = [
                                os.path.join(os.getcwd(), 'service-account'),
                                os.path.join(os.path.dirname(__file__), '..', 'service-account'),
                                os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account'),
                                os.path.join(os.getcwd(), 'src', 'service-account'),
                            ]
                            sa_file = None
                            for c in sa_candidates:
                                if os.path.isfile(c):
                                    sa_file = c; break
                            if not sa_file:
                                return []
                            try:
                                import json
                                from google.oauth2 import service_account
                                from google.auth.transport.requests import Request
                                t0 = time.time()
                                with open(sa_file, 'r', encoding='utf-8') as f:
                                    sa = json.load(f)
                                creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
                                creds.refresh(Request())
                                token = creds.token
                                t1 = time.time()
                                print(f"[{label}] [DEBUG_JOBBOX] service-account load+token refresh took {int((t1-t0)*1000)}ms")
                            except Exception:
                                return []
                            project = sa.get('project_id')
                            if not project:
                                return []
                            base_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/jobbox_accounts'
                            import requests
                            headers = {'Authorization': f'Bearer {token}'}
                            names = []
                            accounts = []
                            page_token = None
                            try:
                                t_start = time.time()
                                network_time = 0.0
                                while True:
                                    params = {'pageSize': 100}
                                    if page_token:
                                        params['pageToken'] = page_token
                                    tn0 = time.time()
                                    r = requests.get(base_url, headers=headers, params=params, timeout=10)
                                    tn1 = time.time()
                                    network_time += (tn1 - tn0)
                                    if r.status_code != 200:
                                        print(f"[{label}] [DEBUG_JOBBOX] requests.get returned {r.status_code}")
                                        break
                                    data = r.json()
                                    docs = data.get('documents', [])
                                    for d in docs:
                                        flds = d.get('fields', {})
                                        an = flds.get('account_name', {}).get('stringValue')
                                        jid = flds.get('jobbox_id', {}).get('stringValue')
                                        jpwd = flds.get('jobbox_password', {}).get('stringValue')
                                        if an:
                                            names.append(an)
                                            accounts.append({'account_name': an, 'jobbox_id': jid, 'jobbox_password': jpwd})
                                    page_token = data.get('nextPageToken')
                                    if not page_token:
                                        break
                                t_end = time.time()
                                print(f"[{label}] [DEBUG_JOBBOX] fetched {len(accounts)} accounts in {int((t_end-t_start)*1000)}ms (network {int(network_time*1000)}ms)")
                                # store in cache
                                try:
                                    cache[uid] = (time.time(), accounts)
                                except Exception:
                                    pass
                                return accounts
                            except Exception as e:
                                print(f"[{label}] [DEBUG_JOBBOX] exception while fetching jobbox_accounts: {e}")
                                return accounts

                        remote_accounts = get_jobbox_accounts(uid)
                        match_account = None
                        parsed_name = (parsed.get('account_name') or '').strip()
                        import re  # Ensure re module is available in this scope

                        def _norm(s: str) -> str:
                            """Normalize a company/account name for exact comparison.

                            - Unicode NFKC normalize to unify full/half width
                            - remove all whitespace
                            - lower-case ASCII
                            Do NOT strip company suffixes and DO NOT use contains-based matching.
                            """
                            if not s:
                                return ''
                            t = unicodedata.normalize('NFKC', s)
                            t = re.sub(r"\s+", '', t)
                            try:
                                t = t.lower()
                            except Exception:
                                pass
                            return t

                        parsed_norm = _norm(parsed_name)

                        # Only accept exact normalized match. No suffix stripping, no contains.
                        for ra in remote_accounts:
                            ra_name = ra.get('account_name') or ''
                            ra_norm = _norm(ra_name)
                            if ra_norm and ra_norm == parsed_norm:
                                match_account = ra
                                break

                        if not match_account:
                            print(f"[{label}] メール内のアカウント名 '{parsed_name}' は jobbox_accounts に見つかりませんでした。自動ログインをスキップします。")
                            continue

                        try:
                            from jobbox_login import JobboxLogin
                        except Exception:
                            print(f'[{label}] 自動ログイン機能は無効です：`src/jobbox_login.py` を確認してください。')
                        else:
                            try:
                                jb = JobboxLogin(match_account)
                            except Exception as e:
                                print(f'[{label}] アカウントの初期化に失敗しました: {e}')
                            else:
                                try:
                                    info = jb.login_and_goto(parsed.get('url'), parsed.get('job_title'), parsed.get('oubo_no'))
                                except Exception as e:
                                    print(f'[{label}] 自動ログイン中に例外が発生しました: {e}')
                                    info = None
                                # 不在此处关闭 jb；保留会话以便在发送成功时写入メモ。
                                # 如果 login_and_goto 返回了 detail，则调用云端的 target_settings 做匹配判定
                                try:
                                    if info and isinstance(info, dict) and info.get('detail'):
                                        detail = info.get('detail') or {}

                                        def get_target_settings(uid):
                                            if not uid:
                                                return {}
                                            sa_candidates = [
                                                os.path.join(os.getcwd(), 'service-account'),
                                                os.path.join(os.path.dirname(__file__), '..', 'service-account'),
                                                os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account'),
                                                os.path.join(os.getcwd(), 'src', 'service-account'),
                                            ]
                                            sa_file = None
                                            for c in sa_candidates:
                                                if os.path.isfile(c):
                                                    sa_file = c
                                                    break
                                            if not sa_file:
                                                return {}
                                            try:
                                                import json
                                                from google.oauth2 import service_account
                                                from google.auth.transport.requests import Request
                                                with open(sa_file, 'r', encoding='utf-8') as f:
                                                    sa = json.load(f)
                                                creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
                                                creds.refresh(Request())
                                                token = creds.token
                                            except Exception:
                                                return {}
                                            project = sa.get('project_id')
                                            if not project:
                                                return {}
                                            url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/target_settings/settings'
                                            import requests
                                            headers = {'Authorization': f'Bearer {token}'}
                                            try:
                                                r = requests.get(url, headers=headers, timeout=10)
                                                if r.status_code != 200:
                                                    return {}
                                                data = r.json()
                                                fields = data.get('fields', {})
                                                res = {}
                                                nt = fields.get('nameTypes', {}).get('mapValue', {}).get('fields', {})
                                                if nt:
                                                    res['nameTypes'] = {
                                                        'kanji': nt.get('kanji', {}).get('booleanValue', True),
                                                        'katakana': nt.get('katakana', {}).get('booleanValue', True),
                                                        'hiragana': nt.get('hiragana', {}).get('booleanValue', True),
                                                        'alpha': nt.get('alpha', {}).get('booleanValue', True),
                                                    }
                                                gd = fields.get('genders', {}).get('mapValue', {}).get('fields', {})
                                                if gd:
                                                    res['genders'] = {
                                                        'male': gd.get('male', {}).get('booleanValue', True),
                                                        'female': gd.get('female', {}).get('booleanValue', True),
                                                    }
                                                ar = fields.get('ageRanges', {}).get('mapValue', {}).get('fields', {})
                                                if ar:
                                                    def iv(k, default):
                                                        v = ar.get(k, {}).get('integerValue')
                                                        try:
                                                            return int(v)
                                                        except:
                                                            return default
                                                    res['ageRanges'] = {
                                                        'maleMin': iv('maleMin', 18), 'maleMax': iv('maleMax', 99),
                                                        'femaleMin': iv('femaleMin', 18), 'femaleMax': iv('femaleMax', 99)
                                                    }
                                                res['smsTemplateA'] = fields.get('smsTemplateA', {}).get('stringValue')
                                                res['smsTemplateB'] = fields.get('smsTemplateB', {}).get('stringValue')
                                                # mail related fields
                                                res['autoReply'] = fields.get('autoReply', {}).get('booleanValue') if fields.get('autoReply') is not None else False
                                                res['mailUseTarget'] = fields.get('mailUseTarget', {}).get('booleanValue') if fields.get('mailUseTarget') is not None else True
                                                res['mailUseNonTarget'] = fields.get('mailUseNonTarget', {}).get('booleanValue') if fields.get('mailUseNonTarget') is not None else False
                                                res['mailTemplateA'] = fields.get('mailTemplateA', {}).get('stringValue') if fields.get('mailTemplateA') else None
                                                res['mailTemplateB'] = fields.get('mailTemplateB', {}).get('stringValue') if fields.get('mailTemplateB') else None
                                                res['mailSubjectA'] = fields.get('mailSubjectA', {}).get('stringValue') if fields.get('mailSubjectA') else None
                                                res['mailSubjectB'] = fields.get('mailSubjectB', {}).get('stringValue') if fields.get('mailSubjectB') else None
                                                return res
                                            except Exception:
                                                return {}

                                        def evaluate_target(detail, settings):
                                            try:
                                                name = detail.get('name','') or ''
                                                gender = detail.get('gender','') or ''
                                                birth = detail.get('birth','') or ''

                                                def detect_name_types(s):
                                                    types = set()
                                                    if re.search(r'[\u4E00-\u9FFF]', s): types.add('kanji')
                                                    if re.search(r'[\u30A0-\u30FF]', s): types.add('katakana')
                                                    if re.search(r'[\u3040-\u309F]', s): types.add('hiragana')
                                                    if re.search(r'[A-Za-z]', s): types.add('alpha')
                                                    return types

                                                name_ok = True
                                                nts = settings.get('nameTypes', {})
                                                if nts:
                                                    detected = detect_name_types(name)
                                                    if detected:
                                                        allowed = set(k for k,v in nts.items() if v)
                                                        if not (detected & allowed):
                                                            name_ok = False

                                                gender_ok = True
                                                gsets = settings.get('genders', {})
                                                if gsets:
                                                    g = None
                                                    if '男' in gender: g = 'male'
                                                    elif '女' in gender: g = 'female'
                                                    if g and not gsets.get(g, True):
                                                        gender_ok = False

                                                age_ok = True
                                                ar = settings.get('ageRanges', {})
                                                if ar:
                                                    # 尝试根据完整出生日期精确计算年龄（如果可行）
                                                    parsed_age = None
                                                    try:
                                                        parsed_age = calc_age_from_birth_str(birth)
                                                    except Exception:
                                                        parsed_age = None

                                                    if parsed_age is not None:
                                                        age = parsed_age
                                                        if '男' in gender:
                                                            if age < ar.get('maleMin', 0) or age > ar.get('maleMax', 999):
                                                                age_ok = False
                                                        elif '女' in gender:
                                                            if age < ar.get('femaleMin', 0) or age > ar.get('femaleMax', 999):
                                                                age_ok = False
                                                        else:
                                                            if not (ar.get('maleMin',0) <= age <= ar.get('maleMax',999) or ar.get('femaleMin',0) <= age <= ar.get('femaleMax',999)):
                                                                age_ok = False
                                                    else:
                                                        # 无法解析出生日期 -> 保持兼容旧逻辑：不把无法解析视为不符合年龄条件
                                                        age_ok = True

                                                return bool(name_ok and gender_ok and age_ok)
                                            except Exception:
                                                return False

                                        # Calculate age from birth date if not present
                                        if 'age' not in detail or not detail.get('age'):
                                            birth_str = detail.get('birth', '') or ''
                                            parsed_age = None
                                            if birth_str:
                                                try:
                                                    parsed_age = calc_age_from_birth_str(birth_str)
                                                except Exception:
                                                    parsed_age = None

                                            # 仅在成功解析出年龄时写入 detail['age']，解析失败则不修改 age 字段
                                            if parsed_age is not None:
                                                detail['age'] = parsed_age

                                        # Load all target segments and check if applicant matches any
                                        segments = _get_target_segments(uid)
                                        
                                        matching_segment = _find_matching_segment(detail, segments)
                                        
                                        # Determine if applicant is a target (using new segment system)
                                        # Check separately for SMS and mail targets
                                        sms_target_segment = None
                                        mail_target_segment = None
                                        
                                        if matching_segment:
                                            # Check if this segment has SMS enabled
                                            if matching_segment['actions']['sms']['enabled']:
                                                sms_target_segment = matching_segment
                                            # Check if this segment has mail enabled  
                                            if matching_segment['actions']['mail']['enabled']:
                                                mail_target_segment = matching_segment
                                        
                                        # Initialize flags for SMS and Mail (ensure availability in all branches)
                                        sms_attempted = False
                                        sms_ok = False
                                        sms_info = {}
                                        mail_attempted = False
                                        mail_ok = False
                                        mail_info = {}
                                        needs_combined_status = False

                                        # For backward compatibility, keep is_target for SMS logic
                                        is_target = sms_target_segment is not None
                                        
                                        if sms_target_segment:
                                            print(f'[{label}] この応募者はSMSの送信対象です。（「{sms_target_segment["title"]}」セグメントに該当）')
                                        else:
                                            print(f'[{label}] この応募者はSMSの送信対象ではありません。')
                                        
                                        if mail_target_segment:
                                            print(f'[{label}] この応募者はメールの送信対象です。（「{mail_target_segment["title"]}」セグメントに該当）')
                                        else:
                                            print(f'[{label}] この応募者はメールの送信対象ではありません。')

                                        # Determine if we need combined status logic
                                        if sms_target_segment and mail_target_segment:
                                            # Check if both SMS and Mail will actually be attempted
                                            tel = detail.get('tel') or detail.get('電話番号') or ''
                                            try:
                                                sms_action = sms_target_segment['actions']['sms']
                                                tpl = sms_action['text'] if sms_action.get('enabled') else None
                                                will_attempt_sms = bool(tel and tpl and sms_action.get('enabled'))
                                            except Exception:
                                                will_attempt_sms = False
                                            
                                            try:
                                                mail_action = mail_target_segment['actions']['mail']
                                                to_email = detail.get('email', '').strip()
                                                will_attempt_mail = bool(mail_action.get('enabled') and mail_action.get('subject') and mail_action.get('body') and to_email)
                                            except Exception:
                                                will_attempt_mail = False
                                            
                                            needs_combined_status = will_attempt_sms and will_attempt_mail
                                        
                                        # Handle SMS sending
                                        if sms_target_segment:
                                            # 读取 api settings，按 provider 路由
                                            api_settings = get_api_settings(uid)
                                            provider = (api_settings.get('provider') or 'sms_publisher')


                                            tel = detail.get('tel') or detail.get('電話番号') or ''
                                            
                                            # Use segment's SMS content
                                            sms_action = sms_target_segment['actions']['sms']
                                            tpl = sms_action['text'] if sms_action['enabled'] else None
                                            sms_send_mode = sms_action.get('sendMode', 'immediate')
                                            sms_scheduled_time = sms_action.get('scheduledTime', '09:00')
                                            sms_delay_minutes = sms_action.get('delayMinutes', 30)
                                            
                                            # Debug: print SMS action settings
                                            print(f'[{label}] [DEBUG] SMS Action Settings:')
                                            print(f'[{label}]   sendMode: {sms_send_mode}')
                                            print(f'[{label}]   scheduledTime: {sms_scheduled_time}')
                                            print(f'[{label}]   delayMinutes: {sms_delay_minutes}')
                                            print(f'[{label}]   sms_action keys: {list(sms_action.keys())}')
                                            
                                            if tel and tpl and sms_target_segment and sms_action['enabled']:
                                                norm, ok, reason = normalize_phone_number(tel)
                                                dry_run_env = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
                                                if not ok:
                                                    print(f'[{label}] 電話番号の検証に失敗しました: {tel} -> {norm} 理由: {reason}。SMSは送信されません。')
                                                    # write target-out / invalid-phone history when not dry-run
                                                    if not dry_run_env and uid:
                                                        try:
                                                            rec = {
                                                                'name': detail.get('name'),
                                                                'gender': detail.get('gender'),
                                                                'birth': detail.get('birth'),
                                                                'email': detail.get('email'),
                                                                'tel': norm,
                                                                'addr': detail.get('addr'),
                                                                'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                                'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                                'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                                'school': detail.get('school'),
                                                                'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                                'job_title': detail.get('kyujin') or '',
                                                                'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                                'status': '送信失敗',
                                                                'response': {'note': f'invalid phone: {reason}'},
                                                                'sentAt': int(time.time())
                                                            }
                                                            ok_write = write_sms_history(str(uid), rec)
                                                            if not ok_write:
                                                                print(f'[{label}] Failed to write sms_history for invalid phone')
                                                        except Exception as e:
                                                            print(f'[{label}] Exception when writing sms_history for invalid phone:', e)
                                                elif sms_send_mode == 'scheduled':
                                                    # 定时发送: 创建定时任务
                                                    print(f'[{label}] SMS時刻送信を設定します: {sms_scheduled_time}')
                                                    # Prepare COMPLETE applicant data (for both template substitution AND history writing)
                                                    try:
                                                        company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                        employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                        jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                        try:
                                                            if not jt and 'info' in locals() and isinstance(info, dict):
                                                                jt = info.get('title') or jt
                                                        except Exception:
                                                            pass
                                                        try:
                                                            if not jt and 'parsed' in locals() and isinstance(parsed, dict):
                                                                jt = parsed.get('job_title') or jt
                                                        except Exception:
                                                            pass
                                                        
                                                        # Include ALL fields needed for template substitution AND history writing
                                                        applicant_detail_for_task = {
                                                            # Template substitution fields
                                                            'name': detail.get('name'),
                                                            'applicant_name': detail.get('name'),
                                                            'job_title': jt,
                                                            'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                            'company': company_val,
                                                            'account_name': company_val,
                                                            'employer_name': employer_val,
                                                            'employer': employer_val,
                                                            '会社名': employer_val,
                                                            # History writing fields
                                                            'gender': detail.get('gender'),
                                                            'birth': detail.get('birth'),
                                                            'age': detail.get('age'),
                                                            'email': detail.get('email') or detail.get('メール') or detail.get('メールアドレス'),
                                                            'tel': detail.get('tel') or detail.get('電話番号'),
                                                            'addr': detail.get('addr') or detail.get('住所'),
                                                            'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                            'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                            'school': detail.get('school') or detail.get('学校名'),
                                                        }
                                                    except Exception as e:
                                                        print(f'[{label}] [SMS時刻] applicant_detail構築エラー: {e}')
                                                        applicant_detail_for_task = {}
                                                    
                                                    task_ok = create_scheduled_task(
                                                        uid=str(uid),
                                                        task_type='sms',
                                                        task_data={
                                                            'scheduledTime': sms_scheduled_time,
                                                            'to': norm,
                                                            'template': tpl,
                                                            'applicant_detail': applicant_detail_for_task,
                                                            'segment_id': sms_target_segment.get('id', ''),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted') or '',
                                                        }
                                                    )
                                                    if task_ok:
                                                        # DON'T set sms_attempted=True here - scheduled tasks should not write history until execution
                                                        print(f'SMS時刻送信タスク作成成功: {sms_scheduled_time}')
                                                    else:
                                                        print('SMS時刻送信タスク作成失敗')
                                                elif sms_send_mode == 'delayed':
                                                    # 延迟发送: 在指定分钟数后发送
                                                    print(f'SMS予約送信を設定します: {sms_delay_minutes}分後')
                                                    # Calculate nextRun timestamp (current time + delay minutes)
                                                    from datetime import datetime, timedelta
                                                    next_run_dt = datetime.now() + timedelta(minutes=sms_delay_minutes)
                                                    next_run_timestamp = int(next_run_dt.timestamp())
                                                    
                                                    # Prepare COMPLETE applicant data
                                                    try:
                                                        company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                        employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                        jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                        try:
                                                            if not jt and 'info' in locals() and isinstance(info, dict):
                                                                jt = info.get('title') or jt
                                                        except Exception:
                                                            pass
                                                        try:
                                                            if not jt and 'parsed' in locals() and isinstance(parsed, dict):
                                                                jt = parsed.get('job_title') or jt
                                                        except Exception:
                                                            pass
                                                        
                                                        applicant_detail_for_task = {
                                                            'name': detail.get('name'),
                                                            'applicant_name': detail.get('name'),
                                                            'job_title': jt,
                                                            'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                            'company': company_val,
                                                            'account_name': company_val,
                                                            'employer_name': employer_val,
                                                            'employer': employer_val,
                                                            '会社名': employer_val,
                                                            'gender': detail.get('gender'),
                                                            'birth': detail.get('birth'),
                                                            'age': detail.get('age'),
                                                            'email': detail.get('email') or detail.get('メール') or detail.get('メールアドレス'),
                                                            'tel': detail.get('tel') or detail.get('電話番号'),
                                                            'addr': detail.get('addr') or detail.get('住所'),
                                                            'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                            'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                            'school': detail.get('school') or detail.get('学校名'),
                                                        }
                                                    except Exception as e:
                                                        print(f'[SMS予約] applicant_detail構築エラー: {e}')
                                                        applicant_detail_for_task = {}
                                                    
                                                    task_ok = create_delayed_task(
                                                        uid=str(uid),
                                                        task_type='sms',
                                                        next_run=next_run_timestamp,
                                                        task_data={
                                                            'delayMinutes': sms_delay_minutes,
                                                            'to': norm,
                                                            'template': tpl,
                                                            'applicant_detail': applicant_detail_for_task,
                                                            'segment_id': sms_target_segment.get('id', ''),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted') or '',
                                                        }
                                                    )
                                                    if task_ok:
                                                        print(f'SMS予約送信タスク作成成功: {sms_delay_minutes}分後 ({next_run_dt.strftime("%Y-%m-%d %H:%M:%S")})')
                                                    else:
                                                        print('SMS予約送信タスク作成失敗')
                                                else:
                                                    # Prepare data map for token substitution in SMS
                                                    try:
                                                        # Provide canonical SMS data keys that match mail template tokens
                                                        # so both SMS and Mail use the same set: applicant_name, job_title, employer_name
                                                        company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                        # employer_name may be present from parsed email body; prefer that for publishing-company name
                                                        employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                        # job_title fallback: prefer detail, but also fallback to info.title or parsed.job_title when available
                                                        jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                        try:
                                                            if not jt and 'info' in locals() and isinstance(info, dict):
                                                                jt = info.get('title') or jt
                                                        except Exception:
                                                            pass
                                                        try:
                                                            if not jt and 'parsed' in locals() and isinstance(parsed, dict):
                                                                jt = parsed.get('job_title') or jt
                                                        except Exception:
                                                            pass
                                                        sms_data = {
                                                            'applicant_name': detail.get('name'),
                                                            'job_title': jt,
                                                            # include both company/account and employer aliases for backward compatibility
                                                            'company': company_val,
                                                            'account_name': company_val,
                                                            'employer_name': employer_val,
                                                            'employer': employer_val,
                                                            '会社名': employer_val,
                                                        }
                                                    except Exception:
                                                        sms_data = {}
                                                    try:
                                                        tpl_to_send = apply_template_tokens(tpl, sms_data)
                                                    except Exception:
                                                        tpl_to_send = tpl

                                                    success, info = send_sms_router(norm, tpl_to_send, provider, api_settings)
                                                    sms_attempted = True
                                                    sms_ok = success
                                                    sms_info = info
                                                    
                                                    # If not combined status needed, write SMS history immediately
                                                    if not needs_combined_status and not dry_run_env and uid:
                                                        try:
                                                            # determine status_code if available
                                                            status_code = None
                                                            if isinstance(info, dict) and 'status_code' in info:
                                                                try:
                                                                    sc = info.get('status_code')
                                                                    if sc is not None:
                                                                        status_code = int(str(sc))
                                                                except Exception:
                                                                    status_code = None
                                                            if success:
                                                                rec_status = '送信済（S）'
                                                            else:
                                                                rec_status = '送信失敗（S）'
                                                            rec = {
                                                                'name': detail.get('name'),
                                                                'gender': detail.get('gender'),
                                                                'birth': detail.get('birth'),
                                                                'email': detail.get('email'),
                                                                'tel': norm,
                                                                'addr': detail.get('addr'),
                                                                'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                                'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                                'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                                'school': detail.get('school'),
                                                                'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                                'job_title': detail.get('kyujin') or detail.get('title') or '',
                                                                'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                                'status': rec_status,
                                                                'template': sms_target_segment.get('title') if sms_target_segment else 'unknown',
                                                                'response': info if isinstance(info, dict) else {'note': str(info)},
                                                                'sentAt': int(time.time())
                                                            }
                                                            try:
                                                                ok_write = write_sms_history(str(uid), rec)
                                                            except Exception:
                                                                ok_write = False
                                                            if not ok_write:
                                                                print('Failed to write sms_history after send/failure')
                                                        except Exception as e:
                                                            print('Exception when writing sms_history (result record):', e)
                                                    # Only write Jobbox memo when candidate is target, send succeeded, exact HTTP 200, and not dry-run
                                                    if success and not dry_run_env:
                                                        try:
                                                            if isinstance(info, dict) and 'status_code' in info:
                                                                try:
                                                                    sc = info.get('status_code')
                                                                    if sc is not None:
                                                                        status_code = int(str(sc))
                                                                except Exception:
                                                                    status_code = None
                                                        except Exception:
                                                            status_code = None
                                                    # Previously: only wrote history on success; now we've recorded both cases
                                                        try:
                                                            status_code = None
                                                            if isinstance(info, dict) and 'status_code' in info:
                                                                try:
                                                                    sc = info.get('status_code')
                                                                    if sc is not None:
                                                                        status_code = int(str(sc))
                                                                except Exception:
                                                                    status_code = None
                                                        except Exception:
                                                            status_code = None


                                                    # Collect memo lines and write a single combined memo for this applicant
                                                    try:
                                                        memo_lines = []
                                                        # Determine label/title to use: prefer sms_target_segment title, else mail_target_segment title, else use ID
                                                        label = None
                                                        try:
                                                            if sms_target_segment:
                                                                label = sms_target_segment.get('title') or sms_target_segment.get('id') or 'SMS対象'
                                                            elif mail_target_segment:
                                                                label = mail_target_segment.get('title') or mail_target_segment.get('id') or 'MAIL対象'
                                                        except Exception as e:
                                                            print(f'label取得エラー: {e}')
                                                            label = None

                                                        # SMS result
                                                        try:
                                                            if is_target:
                                                                if success:
                                                                    # Check if this is a scheduled send
                                                                    if sms_send_mode == 'scheduled' and isinstance(info, dict) and 'scheduled' in info.get('note', ''):
                                                                        # Get next run date for scheduled task
                                                                        from datetime import datetime, timedelta
                                                                        import re
                                                                        scheduled_time = sms_scheduled_time
                                                                        match = re.match(r'(\d{1,2}):(\d{2})', scheduled_time)
                                                                        if match:
                                                                            hour, minute = int(match.group(1)), int(match.group(2))
                                                                            now = datetime.now()
                                                                            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                                                                            if next_run <= now:
                                                                                next_run += timedelta(days=1)
                                                                            scheduled_date = next_run.strftime('%Y/%m/%d')
                                                                            sms_result = f'SMS（時刻送信{scheduled_date}）'
                                                                        else:
                                                                            sms_result = f'SMS（時刻送信）'
                                                                    else:
                                                                        sms_result = 'sms送信済'
                                                                else:
                                                                    # try to include status code if available
                                                                    sc = None
                                                                    if isinstance(info, dict):
                                                                        try:
                                                                            raw_sc = info.get('status_code')
                                                                            if raw_sc is not None:
                                                                                sc = int(str(raw_sc))
                                                                        except Exception:
                                                                            sc = None
                                                                    sms_result = f'sms送信失敗{sc}' if sc is not None else 'sms送信失敗'
                                                            else:
                                                                sms_result = 'sms未送信'
                                                        except Exception:
                                                            sms_result = 'sms未送信'

                                                        # Mail result
                                                        try:
                                                            if mail_attempted:
                                                                if mail_ok:
                                                                    # Check if this is a scheduled send
                                                                    if mail_send_mode == 'scheduled' and isinstance(mail_info, dict) and 'scheduled' in mail_info.get('note', ''):
                                                                        # Get next run date for scheduled task
                                                                        from datetime import datetime, timedelta
                                                                        import re
                                                                        scheduled_time = mail_scheduled_time
                                                                        match = re.match(r'(\d{1,2}):(\d{2})', scheduled_time)
                                                                        if match:
                                                                            hour, minute = int(match.group(1)), int(match.group(2))
                                                                            now = datetime.now()
                                                                            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                                                                            if next_run <= now:
                                                                                next_run += timedelta(days=1)
                                                                            scheduled_date = next_run.strftime('%Y/%m/%d')
                                                                            mail_result = f'MAIL（時刻送信{scheduled_date}）'
                                                                        else:
                                                                            mail_result = f'MAIL（時刻送信）'
                                                                    else:
                                                                        mail_result = 'mail送信済'
                                                                else:
                                                                    # try to include code or error
                                                                    mail_code = None
                                                                    if isinstance(mail_info, dict):
                                                                        mail_code = mail_info.get('status_code') or mail_info.get('code') or mail_info.get('error')
                                                                    elif mail_info is not None:
                                                                        mail_code = str(mail_info)
                                                                    mail_result = f'mail送信失敗{mail_code}' if mail_code else 'mail送信失敗'
                                                            else:
                                                                mail_result = 'mail未送信'
                                                        except Exception:
                                                            mail_result = 'mail未送信'

                                                        # If no label matched, write '対象外'
                                                        # Only write comprehensive memo if label exists (matched a segment)
                                                        # If no label (target-out), memo will be written at Line 3811 instead
                                                        if label:
                                                            # Don't add timestamp here - set_memo_and_save will auto-append it
                                                            memo_text = f"【{label}】：{sms_result}/{mail_result}"
                                                            try:
                                                                if 'jb' in locals() and jb:
                                                                    safe_set_memo_and_save(jb, memo_text, '(まとめ)')
                                                            except Exception as e:
                                                                print('メモ保存(まとめ)時に例外が発生しました:', e)
                                                    except Exception as e:
                                                        print('合并メモ処理で例外:', e)
                                            # If tel or template was missing, record that fact (do not run this when we successfully sent above)
                                            if not (tel and tpl):
                                                print('電話番号またはテンプレートが不足しているため、SMSは送信されませんでした。')
                                                dry_run_env = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
                                                if not dry_run_env and uid:
                                                    try:
                                                        rec = {
                                                            'name': detail.get('name'),
                                                            'gender': detail.get('gender'),
                                                            'birth': detail.get('birth'),
                                                            'email': detail.get('email'),
                                                            'tel': detail.get('tel') or detail.get('電話番号') or '',
                                                            'addr': detail.get('addr'),
                                                            'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                            'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                            'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                            'school': detail.get('school'),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                            'job_title': detail.get('kyujin') or '',
                                                            'status': '送信失敗',
                                                            'response': {'note': 'missing tel or template'},
                                                            'sentAt': int(time.time())
                                                        }
                                                        ok_write = write_sms_history(str(uid), rec)
                                                        if not ok_write:
                                                            print('Failed to write sms_history for missing tel/template')
                                                    except Exception as e:
                                                        print('Exception when writing sms_history for missing tel/template:', e)
                                        
                                        # Handle Mail sending (independent of SMS)
                                        mail_attempted = False
                                        mail_ok = False
                                        mail_info = {}
                                        mail_send_mode = 'immediate'
                                        mail_scheduled_time = '09:00'
                                        
                                        if mail_target_segment:
                                            try:
                                                mail_action = mail_target_segment['actions']['mail']
                                                mail_send_mode = mail_action.get('sendMode', 'immediate')
                                                mail_scheduled_time = mail_action.get('scheduledTime', '09:00')
                                                mail_delay_minutes = mail_action.get('delayMinutes', 30)
                                                
                                                # Debug: print MAIL action settings
                                                print(f'[DEBUG] MAIL Action Settings:')
                                                print(f'  sendMode: {mail_send_mode}')
                                                print(f'  scheduledTime: {mail_scheduled_time}')
                                                print(f'  delayMinutes: {mail_delay_minutes}')
                                                print(f'  mail_action keys: {list(mail_action.keys())}')
                                                
                                                if mail_action['enabled'] and mail_action['subject'] and mail_action['body']:
                                                    to_email = detail.get('email', '').strip()
                                                    if to_email:
                                                        # Get mail settings (sender credentials)
                                                        mail_cfg = _get_mail_settings(str(uid) if uid is not None else "")
                                                        sender = mail_cfg.get('replyEmail') or mail_cfg.get('email', '')
                                                        sender_pass = mail_cfg.get('replyAppPass') or mail_cfg.get('appPass', '')
                                                        
                                                        if sender and sender_pass:
                                                            subject = mail_action['subject']
                                                            body = mail_action['body']

                                                            # Apply template tokens before sending (subject + body)
                                                            try:
                                                                # Build a data map for template replacement with multiple fallbacks.
                                                                applicant_name = ''
                                                                job_title_val = ''
                                                                company_val = ''
                                                                employer_name_val = ''  # 追加：勤務先名
                                                                if isinstance(detail, dict):
                                                                    applicant_name = detail.get('name') or detail.get('氏名') or detail.get('\u6c0f\u540d') or ''
                                                                    job_title_val = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                                    company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company') or ''
                                                                    employer_name_val = detail.get('employer_name') or detail.get('掲載企業名') or detail.get('企業名') or ''  # 追加

                                                                # fallback to info.title returned by find_and_check_applicant
                                                                try:
                                                                    if not job_title_val and 'info' in locals() and isinstance(info, dict):
                                                                        job_title_val = info.get('title') or job_title_val
                                                                except Exception:
                                                                    pass

                                                                # fallback to parsed values (from the initial Jobbox notice email)
                                                                try:
                                                                    if not job_title_val and 'parsed' in locals() and isinstance(parsed, dict):
                                                                        job_title_val = parsed.get('job_title') or job_title_val
                                                                except Exception:
                                                                    pass
                                                                try:
                                                                    if not company_val and 'parsed' in locals() and isinstance(parsed, dict):
                                                                        company_val = parsed.get('account_name') or company_val
                                                                except Exception:
                                                                    pass
                                                                # fallback for employer_name from parsed values
                                                                try:
                                                                    if not employer_name_val and 'parsed' in locals() and isinstance(parsed, dict):
                                                                        employer_name_val = parsed.get('employer_name') or employer_name_val
                                                                except Exception:
                                                                    pass

                                                                # fallback to jb.account if available
                                                                try:
                                                                    if not company_val and 'jb' in locals() and getattr(jb, 'account', None):
                                                                        company_val = (jb.account.get('account_name') if isinstance(jb.account, dict) else None) or company_val
                                                                except Exception:
                                                                    pass

                                                                data_for_mail = {
                                                                    # Template substitution fields
                                                                    'applicant_name': applicant_name,
                                                                    'name': applicant_name,
                                                                    '氏名': applicant_name,
                                                                    'job_title': job_title_val,
                                                                    'job_url': (detail.get('job_url') or detail.get('jobUrl') or '') if isinstance(detail, dict) else '',
                                                                    'position': job_title_val,
                                                                    '求人タイトル': job_title_val,
                                                                    '職種': job_title_val,
                                                                    'company': company_val,
                                                                    'account_name': company_val,
                                                                    'アカウント名': company_val,
                                                                    'employer_name': employer_name_val,
                                                                    'employer': employer_name_val,
                                                                    '会社名': employer_name_val,
                                                                    '掲載企業名': employer_name_val,
                                                                    '企業名': employer_name_val,
                                                                    # History writing fields (for scheduled tasks)
                                                                    'gender': detail.get('gender') if isinstance(detail, dict) else '',
                                                                    'birth': detail.get('birth') if isinstance(detail, dict) else '',
                                                                    'age': detail.get('age') if isinstance(detail, dict) else '',
                                                                    'email': to_email,
                                                                    'tel': detail.get('tel') or detail.get('電話番号') if isinstance(detail, dict) else '',
                                                                    'addr': detail.get('addr') or detail.get('住所') if isinstance(detail, dict) else '',
                                                                    'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') if isinstance(detail, dict) else '',
                                                                    'work_address': detail.get('work_address') or detail.get('workAddress') if isinstance(detail, dict) else '',
                                                                    'school': detail.get('school') or detail.get('学校名') if isinstance(detail, dict) else '',
                                                                }
                                                            except Exception:
                                                                data_for_mail = {}
                                                            
                                                            # Check send mode
                                                            if mail_send_mode == 'scheduled':
                                                                # 定时发送MAIL: 创建定时任务
                                                                print(f'MAIL時刻送信を設定します: {mail_scheduled_time}')
                                                                task_ok = create_scheduled_task(
                                                                    uid=str(uid),
                                                                    task_type='mail',
                                                                    task_data={
                                                                        'scheduledTime': mail_scheduled_time,
                                                                        'to': to_email,
                                                                        'template': body,
                                                                        'subject': subject,
                                                                        'applicant_detail': data_for_mail,
                                                                        'segment_id': mail_target_segment.get('id', ''),
                                                                        'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted') or '',
                                                                    }
                                                                )
                                                                if task_ok:
                                                                    # DON'T set mail_attempted=True here - scheduled tasks should not write history until execution
                                                                    print(f'MAIL時刻送信タスク作成成功: {mail_scheduled_time}')
                                                                else:
                                                                    print('MAIL時刻送信タスク作成失敗')
                                                            elif mail_send_mode == 'delayed':
                                                                # 延迟发送MAIL: 在指定分钟数后发送
                                                                print(f'MAIL予約送信を設定します: {mail_delay_minutes}分後')
                                                                # Calculate nextRun timestamp
                                                                from datetime import datetime, timedelta
                                                                next_run_dt = datetime.now() + timedelta(minutes=mail_delay_minutes)
                                                                next_run_timestamp = int(next_run_dt.timestamp())
                                                                
                                                                task_ok = create_delayed_task(
                                                                    uid=str(uid),
                                                                    task_type='mail',
                                                                    next_run=next_run_timestamp,
                                                                    task_data={
                                                                        'delayMinutes': mail_delay_minutes,
                                                                        'to': to_email,
                                                                        'template': body,
                                                                        'subject': subject,
                                                                        'applicant_detail': data_for_mail,
                                                                        'segment_id': mail_target_segment.get('id', ''),
                                                                        'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted') or '',
                                                                    }
                                                                )
                                                                if task_ok:
                                                                    print(f'MAIL予約送信タスク作成成功: {mail_delay_minutes}分後 ({next_run_dt.strftime("%Y-%m-%d %H:%M:%S")})')
                                                                else:
                                                                    print('MAIL予約送信タスク作成失敗')
                                                            else:
                                                                # 即时发送
                                                                mail_attempted = True
                                                                try:
                                                                    subject_to_send = apply_template_tokens(subject or '', data_for_mail)
                                                                    body_to_send = apply_template_tokens(body or '', data_for_mail)
                                                                except Exception:
                                                                    subject_to_send = subject or ''
                                                                    body_to_send = body or ''

                                                                # Debug: show data_for_mail and substituted values
                                                                debug_mail = os.environ.get('DEBUG_MAIL', 'false').lower() in ('1','true','yes')
                                                                if debug_mail:
                                                                    try:
                                                                        print('[DEBUG_MAIL] data_for_mail keys:', list(data_for_mail.keys()))
                                                                        print('[DEBUG_MAIL] employer_name:', data_for_mail.get('employer_name', 'None'))
                                                                        print('[DEBUG_MAIL] 会社名:', data_for_mail.get('会社名', 'None'))
                                                                        print('[DEBUG_MAIL] substituted subject:', (subject_to_send or '')[:120])
                                                                        print('[DEBUG_MAIL] substituted body   :', re.sub(r'\s+', ' ', (body_to_send or ''))[:180])
                                                                    except Exception:
                                                                        pass

                                                                # Check if DRY_RUN_MAIL is enabled
                                                                mail_dry = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')
                                                                if mail_dry:
                                                                    print(f'[DRY_RUN_MAIL] would send mail from={sender} to={to_email} subj={subject_to_send}')
                                                                    mail_ok, mail_info = True, {'note': 'dry_run'}
                                                                else:
                                                                    # Send HTML email (body may be HTML; apply_template_tokens already HTML-escapes values if needed)
                                                                    mail_ok, mail_info = _send_html_mail(sender, sender_pass, to_email, subject_to_send, body_to_send)
                                                                
                                                                if mail_ok:
                                                                    print(f'メール送信成功: {to_email} (件名: {subject_to_send})')
                                                                else:
                                                                    print(f'メール送信失敗: {to_email} - {mail_info}')

                                                                # If not combined status needed, write mail history immediately
                                                                mail_dry_env = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')

                                                                if not needs_combined_status and not mail_dry_env and uid:
                                                                    try:
                                                                        rec = {
                                                                            'name': detail.get('name'),
                                                                            'gender': detail.get('gender'),
                                                                            'birth': detail.get('birth'),
                                                                            'email': detail.get('email'),
                                                                            'tel': detail.get('tel') or detail.get('電話番号') or '',
                                                                            'addr': detail.get('addr'),
                                                                            'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                                            'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                                            'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                                            'school': detail.get('school'),
                                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                                            'job_title': detail.get('kyujin') or detail.get('title') or '',
                                                                            'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                                            'status': '送信済（M）' if mail_ok else '送信失敗（M）',  # M for Mail
                                                                            'response': mail_info if isinstance(mail_info, dict) else {'note': str(mail_info)},
                                                                            'sentAt': int(time.time())
                                                                        }
                                                                        ok_write_history = write_sms_history(str(uid), rec)  # Use same table as SMS
                                                                        if not ok_write_history:
                                                                            print('履歴の書き込みに失敗しました（メール）')
                                                                    except Exception as e:
                                                                        print(f'履歴書き込み例外（メール）: {e}')
                                                        else:
                                                            print('メール設定が不完全です（送信者またはパスワードが不足）')
                                                            mail_info = {'error': 'incomplete mail settings'}
                                                    else:
                                                        print('応募者のメールアドレスが見つかりません')
                                                        mail_info = {'error': 'no email address'}
                                                else:
                                                    print('メール機能が無効か、件名/本文が設定されていません')
                                                    mail_info = {'error': 'mail action disabled or incomplete'}
                                            except Exception as e:
                                                print(f'メール送信処理中に例外が発生しました: {e}')
                                                mail_info = {'error': str(e)}
                                        
                                        # Add mail memo if mail was attempted and not in dry-run mode
                                        if mail_attempted and (not os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')):
                                            try:
                                                mail_note = 'RPA:メール:送信済み' if mail_ok else 'RPA:メール:送信失敗'
                                                # Try to extract a concise note from mail_info
                                                info_snip = ''
                                                try:
                                                    if isinstance(mail_info, dict):
                                                        info_snip = mail_info.get('note') or mail_info.get('error') or str(mail_info.get('status_code', ''))
                                                        if info_snip and isinstance(info_snip, dict):
                                                            info_snip = ''
                                                    else:
                                                        info_snip = str(mail_info)
                                                except Exception:
                                                    info_snip = ''
                                                if info_snip:
                                                    mail_note = f"{mail_note} ({info_snip})"
                                                try:
                                                    if 'jb' in locals() and jb:
                                                        safe_set_memo_and_save(jb, mail_note, '(MAIL)')
                                                except Exception as e:
                                                    print('メモ保存(MAIL)時に例外が発生しました:', e)
                                            except Exception as e:
                                                print('メール memo 処理で例外:', e)
                                        
                                        # Handle combined status history writing if both SMS and Mail were attempted
                                        if needs_combined_status and uid:
                                            dry_run_sms = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
                                            dry_run_mail = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')
                                            
                                            if not (dry_run_sms and dry_run_mail):  # Write history unless both are dry-run
                                                try:
                                                    # Determine combined status
                                                    if sms_attempted and mail_attempted:
                                                        # both channels attempted
                                                        if sms_ok and mail_ok:
                                                            combined_status = '送信済（M+S）'
                                                        elif sms_ok and not mail_ok:
                                                            combined_status = '送信済（S）+送信失敗（M）'
                                                        elif not sms_ok and mail_ok:
                                                            combined_status = '送信失敗（S）+送信済（M）'
                                                        else:
                                                            combined_status = '送信失敗（M+S）'
                                                    elif sms_attempted and not mail_attempted:
                                                        combined_status = '送信済（S）' if sms_ok else '送信失敗（S）'
                                                    elif not sms_attempted and mail_attempted:
                                                        combined_status = '送信済（M）' if mail_ok else '送信失敗（M）'
                                                    else:
                                                        combined_status = '送信失敗（S）'
                                                    
                                                    # Create combined response info
                                                    combined_response = {}
                                                    if sms_attempted and isinstance(sms_info, dict):
                                                        combined_response['sms'] = sms_info
                                                    if mail_attempted and isinstance(mail_info, dict):
                                                        combined_response['mail'] = mail_info
                                                    
                                                    # Create combined history record
                                                    rec = {
                                                        'name': detail.get('name'),
                                                        'gender': detail.get('gender'),
                                                        'birth': detail.get('birth'),
                                                        'email': detail.get('email'),
                                                        'tel': detail.get('tel') or detail.get('電話番号') or '',
                                                        'addr': detail.get('addr'),
                                                        'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                        'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                        'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                        'school': detail.get('school'),
                                                        'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                        'job_title': detail.get('kyujin') or detail.get('title') or '',
                                                        'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                        'status': combined_status,
                                                        'response': combined_response if combined_response else {'note': 'combined attempt'},
                                                        'sentAt': int(time.time())
                                                    }
                                                    
                                                    ok_write_combined = write_sms_history(str(uid), rec)
                                                    if not ok_write_combined:
                                                        print('組み合わせ履歴の書き込みに失敗しました')
                                                except Exception as e:
                                                    print(f'組み合わせ履歴書き込み例外: {e}')
                                        
                                        else:
                                            # For non-target applicants, use the old mail system (if configured)
                                            dry_run_env = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
                                            # Mail auto-reply for non-target (if configured)
                                            try:
                                                # Create timestamp for non-target users (if needed) but
                                                # pass actual mail/target settings dict to send_auto_reply_if_configured
                                                now_ts = int(time.time())
                                                try:
                                                    mail_cfg = get_target_settings(uid)
                                                except Exception:
                                                    mail_cfg = {}
                                                # Call auto-reply helper and capture result so we can write mail_history
                                                try:
                                                    mail_sent_ok, mail_sent_flag, mail_sent_info = send_auto_reply_if_configured(uid, mail_cfg, False, detail, jb)
                                                except Exception as e:
                                                    mail_sent_ok, mail_sent_flag, mail_sent_info = (False, False, {'error': str(e)})

                                                # Write sms_history if not dry-run (same table as SMS, with M suffix)
                                                try:
                                                    mail_dry_env2 = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')

                                                    if not mail_dry_env2 and uid and mail_sent_flag:  # Only write if mail was actually attempted
                                                        # Add (M) suffix to status to distinguish mail from SMS
                                                        base_status = '送信済' if (mail_sent_ok and mail_sent_flag) else ('送信失敗' if mail_sent_ok and not mail_sent_flag else '送信抑制')
                                                        mail_status = f'{base_status}（M）'
                                                        rec = {
                                                            'name': detail.get('name'),
                                                            'gender': detail.get('gender'),
                                                            'birth': detail.get('birth'),
                                                            'email': detail.get('email'),
                                                            'tel': detail.get('tel') or detail.get('電話番号') or '',
                                                            'addr': detail.get('addr'),
                                                            'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                            'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                            'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                            'school': detail.get('school'),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                            'job_title': detail.get('kyujin') or '',
                                                            'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                            'status': mail_status,
                                                            'response': mail_sent_info if isinstance(mail_sent_info, dict) else {'note': str(mail_sent_info)},
                                                            'sentAt': int(time.time())
                                                        }
                                                        ok_write_mail2 = write_sms_history(str(uid), rec)  # Use same table as SMS
                                                        if not ok_write_mail2:
                                                            print('Failed to write mail_history (non-target)')
                                                except Exception as e:
                                                    print('Exception when writing mail_history (non-target):', e)
                                            except Exception as e:
                                                print('メール送信処理中に例外が発生しました(対象外):', e)
                                            if not dry_run_env and uid:
                                                try:
                                                    # If any channel was attempted (SMS or Mail), do not write a
                                                    # separate "対象外" record. This avoids duplicate rows when
                                                    # one channel is intentionally disabled/off and the other
                                                    # was sent or when an auto-reply mail was attempted.
                                                    any_attempted = bool(locals().get('mail_sent_flag') or locals().get('mail_attempted') or locals().get('sms_attempted'))
                                                    if any_attempted:
                                                        print('Skipping target-out history write: a channel was attempted for this applicant')
                                                    else:
                                                        rec = {
                                                            'name': detail.get('name'),
                                                            'gender': detail.get('gender'),
                                                            'birth': detail.get('birth'),
                                                            'email': detail.get('email'),
                                                            'tel': detail.get('tel') or detail.get('電話番号') or '',
                                                            'addr': detail.get('addr'),
                                                            'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                            'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                            'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                            'school': detail.get('school'),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                            'job_title': detail.get('kyujin') or '',
                                                            'job_url': detail.get('job_url') or detail.get('jobUrl') or '',
                                                            'status': '対象外',
                                                            'response': {'note': 'evaluated as not target'},
                                                            'sentAt': int(time.time())
                                                        }
                                                        ok_write = write_sms_history(str(uid), rec)
                                                        if not ok_write:
                                                            print('Failed to write sms_history for target-out')
                                                except Exception as e:
                                                    print('Exception when writing sms_history for target-out:', e)
                                                # 写入 Jobbox メモ为「RPA:対象外」，如果我们仍然持有 jb 会话且不是 dry-run
                                                try:
                                                    if (not dry_run_env) and 'jb' in locals() and jb:
                                                        safe_set_memo_and_save(jb, 'RPA:対象外', '(対象外)')
                                                except Exception:
                                                    pass
                                except Exception as e:
                                    print(f'対象判定中に例外が発生しました: {e}')
                                
                                # Ensure jb is closed after all memo operations are completed
                                try:
                                    if 'jb' in locals() and jb:
                                        jb.close()
                                except Exception:
                                    pass
                
                is_engage_subject = has_engage_marker and '新着応募' in subject
                if handle_engage and is_engage_subject:
                    # ===== エンゲージ邮件处理 =====
                    # 获取整封邮件正文（不影响已读标记，使用 PEEK）
                    status, full = conn.fetch(num, '(BODY.PEEK[])')
                    if status != 'OK' or not full:
                        continue
                    
                    full_bytes = None
                    for part in full:
                        if isinstance(part, tuple) and len(part) > 1 and isinstance(part[1], (bytes, bytearray)):
                            full_bytes = bytes(part[1])
                            break
                        if isinstance(part, (bytes, bytearray)):
                            full_bytes = bytes(part)
                            break
                    
                    if not full_bytes:
                        continue
                    
                    msg = email.message_from_bytes(full_bytes)
                    body = ''
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            if ctype == 'text/plain':
                                payload = part.get_payload(decode=True)
                                if isinstance(payload, (bytes, bytearray)):
                                    try:
                                        body = payload.decode(part.get_content_charset() or 'utf-8', errors='ignore')
                                    except Exception:
                                        body = payload.decode('utf-8', errors='ignore')
                                elif isinstance(payload, str):
                                    body = payload
                                break
                    else:
                        payload = msg.get_payload(decode=True)
                        if isinstance(payload, (bytes, bytearray)):
                            body = payload.decode(msg.get_content_charset() or 'utf-8', errors='ignore')
                        elif isinstance(payload, str):
                            body = payload
                    
                    parsed = parse_engage_body(body)
                    print('---- エンゲージの未読メールを検出 ----')
                    print('件名:', subject)
                    print('アカウント名:', parsed['account_name'])
                    print('応募職種:', parsed['job_title'])
                    print('URL:', parsed['url'])
                    
                    # 标记为已读
                    conn.store(num, '+FLAGS', '\\Seen')
                    
                    # アカウント名が見つかったら自動でログイン処理を実行
                    if parsed.get('account_name') and parsed.get('url'):
                        print('エンゲージのアカウント情報を検出しました。自動ログイン処理を実行します。')
                        
                        # 从 Firestore 的 engage_accounts 列表中查找匹配的 account_name
                        def get_engage_accounts(uid):
                            if not uid:
                                return []
                            sa_file = _find_service_account_file()
                            if not sa_file:
                                return []
                            try:
                                from google.oauth2 import service_account
                                from google.auth.transport.requests import Request
                                with open(sa_file, 'r', encoding='utf-8') as f:
                                    sa = json.load(f)
                                creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
                                creds.refresh(Request())
                                token = creds.token
                            except Exception:
                                return []
                            project = sa.get('project_id')
                            if not project:
                                return []
                            base_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/engage_accounts'
                            headers = {'Authorization': f'Bearer {token}'}
                            accounts = []
                            page_token = None
                            try:
                                while True:
                                    params = {'pageSize': 100}
                                    if page_token:
                                        params['pageToken'] = page_token
                                    r = requests.get(base_url, headers=headers, params=params, timeout=10)
                                    if r.status_code != 200:
                                        break
                                    data = r.json()
                                    docs = data.get('documents', [])
                                    for d in docs:
                                        flds = d.get('fields', {})
                                        an = flds.get('account_name', {}).get('stringValue')
                                        eid = flds.get('engage_id', {}).get('stringValue')
                                        epwd = flds.get('engage_password', {}).get('stringValue')
                                        if an:
                                            accounts.append({'account_name': an, 'engage_id': eid, 'engage_password': epwd})
                                    page_token = data.get('nextPageToken')
                                    if not page_token:
                                        break
                                return accounts
                            except Exception:
                                return accounts
                        
                        remote_accounts = get_engage_accounts(uid)
                        match_account = None
                        parsed_name = (parsed.get('account_name') or '').strip()
                        
                        def _norm(s: str) -> str:
                            import re
                            if not s:
                                return ''
                            t = unicodedata.normalize('NFKC', s)
                            t = re.sub(r"\s+", '', t)
                            try:
                                t = t.lower()
                            except Exception:
                                pass
                            return t
                        
                        parsed_norm = _norm(parsed_name)
                        
                        # 精确匹配账号名
                        for ra in remote_accounts:
                            ra_name = ra.get('account_name') or ''
                            ra_norm = _norm(ra_name)
                            if ra_norm and ra_norm == parsed_norm:
                                match_account = ra
                                break
                        
                        if not match_account:
                            print(f"メール内のアカウント名 '{parsed_name}' は engage_accounts に見つかりませんでした。自動ログインをスキップします。")
                            print('=' * 50)
                            continue
                        
                        # エンゲージ自動ログイン処理（完全な異常捕获，不会闪退）
                        engage = None
                        try:
                            # print('[エンゲージ] ===== RPA処理を開始します =====')
                            try:
                                from engage_login import EngageLogin
                                # print('[エンゲージ] ✓ EngageLoginモジュールを読み込みました')
                            except Exception as import_err:
                                print(f'[エンゲージ] ❌ EngageLogin読み込みエラー: {import_err}')
                                print('  `src/engage_login.py` を確認してください。')
                                print('  処理をスキップして次のメールに進みます。')
                                print('=' * 50)
                                continue
                            
                            try:
                                # print(f'[エンゲージ] EngageLoginを初期化します...')
                                # print(f'  アカウント名: {match_account.get("account_name")}')
                                # print(f'  ID: {match_account.get("engage_id")}')
                                # print(f'  URL: {parsed.get("url")}')
                                
                                try:
                                    engage = EngageLogin(match_account)
                                    # print('[エンゲージ] ✓ ブラウザ初期化成功')
                                except Exception as init_err:
                                    print(f'[エンゲージ] ❌ ブラウザ初期化エラー: {init_err}')
                                    print('  ChromeDriverが正しくインストールされているか確認してください。')
                                    import traceback
                                    traceback.print_exc()
                                    print('  処理をスキップして次のメールに進みます。')
                                    print('=' * 50)
                                    continue
                                
                                # print('[エンゲージ] login_and_goto()を呼び出します...')
                                try:
                                    # メールから取得した職種名を渡す
                                    info = engage.login_and_goto(parsed.get('url'), parsed.get('job_title', ''))
                                    # print(f'[エンゲージ] ✓ login_and_goto()完了: {type(info)}')
                                except Exception as login_err:
                                    print(f'[エンゲージ] ❌ ログイン処理エラー: {login_err}')
                                    import traceback
                                    traceback.print_exc()
                                    print('  処理をスキップして次のメールに進みます。')
                                    try:
                                        if engage:
                                            engage.close()
                                            # print('[エンゲージ] ブラウザを閉じました')
                                    except:
                                        pass
                                    print('=' * 50)
                                    continue
                                
                                if info and isinstance(info, dict) and info.get('detail'):
                                    detail = info.get('detail') or {}
                                    
                                    # 応募Noを追加（URLから取得）
                                    if not detail.get('oubo_no') and parsed.get('oubo_no'):
                                        detail['oubo_no'] = parsed.get('oubo_no')
                                        detail['応募No'] = parsed.get('oubo_no')
                                    
                                    # アカウント名と求人タイトルを追加
                                    detail['account_name'] = parsed.get('account_name')
                                    # 職種名はlogin_and_goto()で既に設定済み（メールから取得）
                                    detail['job_title'] = info.get('title', '') or parsed.get('job_title', '')
                                    detail['employer_name'] = parsed.get('employer_name')
                                    detail['company'] = parsed.get('account_name')
                                    
                                    # 年齢を計算（まだ取得できていない場合）
                                    if 'age' not in detail or not detail.get('age'):
                                        birth_str = detail.get('birth', '') or ''
                                        if birth_str:
                                            try:
                                                parsed_age = calc_age_from_birth_str(birth_str)
                                                if parsed_age is not None:
                                                    detail['age'] = parsed_age
                                            except Exception:
                                                pass
                                    
                                    # エンゲージのsegment配置を読取
                                    segments = _get_engage_target_segments(uid)
                                    if not segments:
                                        print('エンゲージのセグメント設定が見つかりません')
                                        # 履歴に記録（対象外として）
                                        try:
                                            rec = {
                                                'name': detail.get('name'),
                                                'furigana': detail.get('furigana', ''),
                                                'gender': detail.get('gender'),
                                                'birth': detail.get('birth'),
                                                'age': detail.get('age'),
                                                'email': detail.get('email'),
                                                'tel': detail.get('tel'),
                                                'addr': detail.get('addr'),
                                                'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                'oubo_no': detail.get('oubo_no'),
                                                'job_title': detail.get('title') or '',
                                                'source': 'engage',
                                                'platform': 'エンゲージ',
                                                'status': '対象外',
                                                'response': {'note': 'セグメント設定なし'},
                                                'sentAt': int(time.time())
                                            }
                                            write_sms_history(str(uid), rec)
                                        except Exception:
                                            pass
                                    else:
                                        # セグメントマッチング
                                        matching_segment = _find_matching_segment(detail, segments)
                                        
                                        if matching_segment:
                                            print(f'✓ セグメント「{matching_segment["title"]}」に該当します（エンゲージ）')
                                            
                                            # ===== SMS/Mail送信処理（求人ボックスと同じロジックを使用）=====
                                            # エンゲージ専用のmail_settingsを読み込む
                                            engage_mail_settings = _get_engage_mail_settings(uid)
                                            
                                            # SMS/Mail送信フラグ
                                            sms_attempted = False
                                            sms_ok = False
                                            sms_info = {}
                                            mail_attempted = False
                                            mail_ok = False
                                            mail_info = {}
                                            
                                            # SMS/Mailが両方有効かチェック
                                            needs_combined_status = False
                                            try:
                                                tel = detail.get('tel') or detail.get('電話番号') or ''
                                                sms_action = matching_segment['actions']['sms']
                                                tpl = sms_action['text'] if sms_action.get('enabled') else None
                                                will_attempt_sms = bool(tel and tpl and sms_action.get('enabled'))
                                            except Exception:
                                                will_attempt_sms = False
                                            
                                            try:
                                                mail_action = matching_segment['actions']['mail']
                                                to_email = detail.get('email', '').strip()
                                                will_attempt_mail = bool(mail_action.get('enabled') and mail_action.get('subject') and mail_action.get('body') and to_email)
                                            except Exception:
                                                will_attempt_mail = False
                                            
                                            needs_combined_status = will_attempt_sms and will_attempt_mail
                                            
                                            # ===== SMS送信処理 =====
                                            if matching_segment:
                                                # API設定を取得（求人ボックスと同じAPIを使用）
                                                api_settings = get_api_settings(uid)
                                                provider = (api_settings.get('provider') or 'sms_publisher')
                                                
                                                # エンゲージ流程中使用模块级别的SMS发送函数
                                                tel = detail.get('tel') or detail.get('電話番号') or ''
                                                
                                                # セグメントのSMS設定を使用
                                                sms_action = matching_segment['actions']['sms']
                                                tpl = sms_action['text'] if sms_action['enabled'] else None
                                                sms_send_mode = sms_action.get('sendMode', 'immediate')
                                                sms_scheduled_time = sms_action.get('scheduledTime', '09:00')
                                                sms_delay_minutes = sms_action.get('delayMinutes', 30)
                                                
                                                if tel and tpl and matching_segment and sms_action['enabled']:
                                                    norm, ok, reason = normalize_phone_number(tel)
                                                    dry_run_env = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
                                                    
                                                    if not ok:
                                                        print(f'電話番号の検証に失敗: {tel} -> {norm} 理由: {reason}')
                                                        if not dry_run_env and uid:
                                                            try:
                                                                rec = {
                                                                    'name': detail.get('name'),
                                                                    'furigana': detail.get('furigana', ''),
                                                                    'gender': detail.get('gender'),
                                                                    'birth': detail.get('birth'),
                                                                    'age': detail.get('age'),
                                                                    'email': detail.get('email'),
                                                                    'tel': norm,
                                                                    'addr': detail.get('addr'),
                                                                    'school': detail.get('school'),
                                                                    'oubo_no': detail.get('oubo_no'),
                                                                    'job_title': detail.get('title') or '',
                                                                    'source': 'engage',
                                                                    'platform': 'エンゲージ',
                                                                    'status': '送信失敗',
                                                                    'response': {'note': f'invalid phone: {reason}'},
                                                                    'sentAt': int(time.time())
                                                                }
                                                                write_sms_history(str(uid), rec)
                                                            except Exception as e:
                                                                print(f'履歴記録エラー: {e}')
                                                    
                                                    elif sms_send_mode == 'scheduled':
                                                        # 定時送信
                                                        print(f'SMS時刻送信を設定します: {sms_scheduled_time}')
                                                        try:
                                                            company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                            employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                            jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                            
                                                            applicant_detail_for_task = {
                                                                'name': detail.get('name'),
                                                                'applicant_name': detail.get('name'),
                                                                'job_title': jt,
                                                                'company': company_val,
                                                                'account_name': company_val,
                                                                'employer_name': employer_val,
                                                                'employer': employer_val,
                                                                '会社名': employer_val,
                                                                'gender': detail.get('gender'),
                                                                'birth': detail.get('birth'),
                                                                'age': detail.get('age'),
                                                                'email': detail.get('email'),
                                                                'tel': detail.get('tel'),
                                                                'addr': detail.get('addr'),
                                                                'school': detail.get('school'),
                                                            }
                                                        except Exception as e:
                                                            print(f'[SMS時刻] applicant_detail構築エラー: {e}')
                                                            applicant_detail_for_task = {}
                                                        
                                                        task_ok = create_scheduled_task(
                                                            uid=str(uid),
                                                            task_type='sms',
                                                            task_data={
                                                                'scheduledTime': sms_scheduled_time,
                                                                'to': norm,
                                                                'template': tpl,
                                                                'applicant_detail': applicant_detail_for_task,
                                                                'segment_id': matching_segment.get('id', ''),
                                                                'oubo_no': detail.get('oubo_no') or '',
                                                            }
                                                        )
                                                        if task_ok:
                                                            print(f'SMS時刻送信タスク作成成功: {sms_scheduled_time}')
                                                        else:
                                                            print('SMS時刻送信タスク作成失敗')
                                                    
                                                    elif sms_send_mode == 'delayed':
                                                        # 延迟送信
                                                        print(f'SMS予約送信を設定します: {sms_delay_minutes}分後')
                                                        from datetime import datetime, timedelta
                                                        next_run_dt = datetime.now() + timedelta(minutes=sms_delay_minutes)
                                                        next_run_timestamp = int(next_run_dt.timestamp())
                                                        
                                                        try:
                                                            company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                            employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                            jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                            
                                                            applicant_detail_for_task = {
                                                                'name': detail.get('name'),
                                                                'applicant_name': detail.get('name'),
                                                                'job_title': jt,
                                                                'company': company_val,
                                                                'account_name': company_val,
                                                                'employer_name': employer_val,
                                                                'employer': employer_val,
                                                                '会社名': employer_val,
                                                                'gender': detail.get('gender'),
                                                                'birth': detail.get('birth'),
                                                                'age': detail.get('age'),
                                                                'email': detail.get('email'),
                                                                'tel': detail.get('tel'),
                                                                'addr': detail.get('addr'),
                                                                'school': detail.get('school'),
                                                            }
                                                        except Exception as e:
                                                            print(f'[SMS予約] applicant_detail構築エラー: {e}')
                                                            applicant_detail_for_task = {}
                                                        
                                                        task_ok = create_delayed_task(
                                                            uid=str(uid),
                                                            task_type='sms',
                                                            next_run=next_run_timestamp,
                                                            task_data={
                                                                'delayMinutes': sms_delay_minutes,
                                                                'to': norm,
                                                                'template': tpl,
                                                                'applicant_detail': applicant_detail_for_task,
                                                                'segment_id': matching_segment.get('id', ''),
                                                                'oubo_no': detail.get('oubo_no') or '',
                                                            }
                                                        )
                                                        if task_ok:
                                                            print(f'SMS予約送信タスク作成成功: {sms_delay_minutes}分後 ({next_run_dt.strftime("%Y-%m-%d %H:%M:%S")})')
                                                        else:
                                                            print('SMS予約送信タスク作成失敗')
                                                    
                                                    else:
                                                        # 即時送信
                                                        try:
                                                            company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                            employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                            jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                            
                                                            sms_data = {
                                                                'applicant_name': detail.get('name'),
                                                                'job_title': jt,
                                                                'company': company_val,
                                                                'account_name': company_val,
                                                                'employer_name': employer_val,
                                                                'employer': employer_val,
                                                                '会社名': employer_val,
                                                            }
                                                        except Exception:
                                                            sms_data = {}
                                                        
                                                        try:
                                                            tpl_to_send = apply_template_tokens(tpl, sms_data)
                                                        except Exception:
                                                            tpl_to_send = tpl
                                                        
                                                        success, info = send_sms_router(norm, tpl_to_send, provider, api_settings)
                                                        sms_attempted = True
                                                        sms_ok = success
                                                        sms_info = info
                                                        
                                                        # 显示SMS发送结果
                                                        if success:
                                                            print(f'✅ SMS送信完了')
                                                        else:
                                                            print(f'❌ SMS送信失敗')
                                                        
                                                        # 単独SMS送信の場合は即座に履歴記録
                                                        if not needs_combined_status and not dry_run_env and uid:
                                                            try:
                                                                rec_status = '送信済（S）' if success else '送信失敗（S）'
                                                                rec = {
                                                                    'name': detail.get('name'),
                                                                    'furigana': detail.get('furigana', ''),
                                                                    'gender': detail.get('gender'),
                                                                    'birth': detail.get('birth'),
                                                                    'age': detail.get('age'),
                                                                    'email': detail.get('email'),
                                                                    'tel': norm,
                                                                    'addr': detail.get('addr'),
                                                                    'school': detail.get('school'),
                                                                    'oubo_no': detail.get('oubo_no'),
                                                                    'job_title': detail.get('title') or '',
                                                                    'source': 'engage',
                                                                    'platform': 'エンゲージ',
                                                                    'segment_title': matching_segment.get('title'),
                                                                    'status': rec_status,
                                                                    'response': info if isinstance(info, dict) else {'note': str(info)},
                                                                    'sentAt': int(time.time())
                                                                }
                                                                write_sms_history(str(uid), rec)
                                                            except Exception as e:
                                                                print(f'SMS履歴記録エラー: {e}')
                                            
                                            # ===== Mail送信処理 =====
                                            if matching_segment:
                                                try:
                                                    mail_action = matching_segment['actions']['mail']
                                                    to_email = detail.get('email', '').strip()
                                                    
                                                    if mail_action.get('enabled') and mail_action.get('subject') and mail_action.get('body') and to_email:
                                                        mail_send_mode = mail_action.get('sendMode', 'immediate')
                                                        mail_scheduled_time = mail_action.get('scheduledTime', '09:00')
                                                        mail_delay_minutes = mail_action.get('delayMinutes', 30)
                                                        
                                                        # エンゲージ専用のmail_settings取得
                                                        sender = engage_mail_settings.get('replyEmail') or engage_mail_settings.get('email')
                                                        sender_pass = engage_mail_settings.get('replyAppPass') or engage_mail_settings.get('appPass')
                                                        
                                                        if not sender or not sender_pass:
                                                            print('メール送信元の設定が見つかりません（engage_mail_settings）')
                                                        else:
                                                            if mail_send_mode == 'scheduled':
                                                                # 定時送信
                                                                print(f'メール時刻送信を設定します: {mail_scheduled_time}')
                                                                try:
                                                                    company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                                    employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                                    jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                                    
                                                                    applicant_detail_for_task = {
                                                                        'name': detail.get('name'),
                                                                        'applicant_name': detail.get('name'),
                                                                        'job_title': jt,
                                                                        'company': company_val,
                                                                        'account_name': company_val,
                                                                        'employer_name': employer_val,
                                                                        'employer': employer_val,
                                                                        '会社名': employer_val,
                                                                        'gender': detail.get('gender'),
                                                                        'birth': detail.get('birth'),
                                                                        'age': detail.get('age'),
                                                                        'email': detail.get('email'),
                                                                        'tel': detail.get('tel'),
                                                                        'addr': detail.get('addr'),
                                                                        'school': detail.get('school'),
                                                                    }
                                                                except Exception as e:
                                                                    print(f'[メール時刻] applicant_detail構築エラー: {e}')
                                                                    applicant_detail_for_task = {}
                                                                
                                                                task_ok = create_scheduled_task(
                                                                    uid=str(uid),
                                                                    task_type='mail',
                                                                    task_data={
                                                                        'scheduledTime': mail_scheduled_time,
                                                                        'to': to_email,
                                                                        'template': mail_action.get('body'),
                                                                        'subject': mail_action.get('subject'),
                                                                        'applicant_detail': applicant_detail_for_task,
                                                                        'segment_id': matching_segment.get('id', ''),
                                                                        'oubo_no': detail.get('oubo_no') or '',
                                                                    }
                                                                )
                                                                if task_ok:
                                                                    print(f'メール時刻送信タスク作成成功: {mail_scheduled_time}')
                                                                else:
                                                                    print('メール時刻送信タスク作成失敗')
                                                            
                                                            elif mail_send_mode == 'delayed':
                                                                # 延迟送信
                                                                print(f'メール予約送信を設定します: {mail_delay_minutes}分後')
                                                                from datetime import datetime, timedelta
                                                                next_run_dt = datetime.now() + timedelta(minutes=mail_delay_minutes)
                                                                next_run_timestamp = int(next_run_dt.timestamp())
                                                                
                                                                try:
                                                                    company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                                    employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                                    jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                                    
                                                                    applicant_detail_for_task = {
                                                                        'name': detail.get('name'),
                                                                        'applicant_name': detail.get('name'),
                                                                        'job_title': jt,
                                                                        'company': company_val,
                                                                        'account_name': company_val,
                                                                        'employer_name': employer_val,
                                                                        'employer': employer_val,
                                                                        '会社名': employer_val,
                                                                        'gender': detail.get('gender'),
                                                                        'birth': detail.get('birth'),
                                                                        'age': detail.get('age'),
                                                                        'email': detail.get('email'),
                                                                        'tel': detail.get('tel'),
                                                                        'addr': detail.get('addr'),
                                                                        'school': detail.get('school'),
                                                                    }
                                                                except Exception as e:
                                                                    print(f'[メール予約] applicant_detail構築エラー: {e}')
                                                                    applicant_detail_for_task = {}
                                                                
                                                                task_ok = create_delayed_task(
                                                                    uid=str(uid),
                                                                    task_type='mail',
                                                                    next_run=next_run_timestamp,
                                                                    task_data={
                                                                        'delayMinutes': mail_delay_minutes,
                                                                        'to': to_email,
                                                                        'template': mail_action.get('body'),
                                                                        'subject': mail_action.get('subject'),
                                                                        'applicant_detail': applicant_detail_for_task,
                                                                        'segment_id': matching_segment.get('id', ''),
                                                                        'oubo_no': detail.get('oubo_no') or '',
                                                                    }
                                                                )
                                                                if task_ok:
                                                                    print(f'メール予約送信タスク作成成功: {mail_delay_minutes}分後 ({next_run_dt.strftime("%Y-%m-%d %H:%M:%S")})')
                                                                else:
                                                                    print('メール予約送信タスク作成失敗')
                                                            
                                                            else:
                                                                # 即時送信
                                                                try:
                                                                    company_val = detail.get('account_name') or detail.get('アカウント名') or detail.get('company')
                                                                    employer_val = detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or company_val
                                                                    jt = detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or ''
                                                                    
                                                                    mail_data = {
                                                                        'applicant_name': detail.get('name'),
                                                                        'job_title': jt,
                                                                        'company': company_val,
                                                                        'account_name': company_val,
                                                                        'employer_name': employer_val,
                                                                        'employer': employer_val,
                                                                        '会社名': employer_val,
                                                                    }
                                                                except Exception:
                                                                    mail_data = {}
                                                                
                                                                try:
                                                                    subj_to_send = apply_template_tokens(mail_action.get('subject'), mail_data)
                                                                    body_to_send = apply_template_tokens(mail_action.get('body'), mail_data)
                                                                except Exception:
                                                                    subj_to_send = mail_action.get('subject')
                                                                    body_to_send = mail_action.get('body')
                                                                
                                                                dry_run_mail = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')
                                                                if dry_run_mail:
                                                                    print(f"[DRY_RUN_MAIL] would send to {to_email}: {subj_to_send}")
                                                                    mail_attempted = True
                                                                    mail_ok = True
                                                                    mail_info = {'note': 'dry_run'}
                                                                else:
                                                                    ok_mail, info_mail = send_mail_once(sender, sender_pass, to_email, subj_to_send, body_to_send)
                                                                    mail_attempted = True
                                                                    mail_ok = ok_mail
                                                                    mail_info = info_mail
                                                                    
                                                                    # 显示Mail发送结果
                                                                    if ok_mail:
                                                                        print(f'✅ MAIL送信完了')
                                                                    else:
                                                                        print(f'❌ MAIL送信失敗')
                                                                
                                                                # 単独メール送信の場合は即座に履歴記録
                                                                if not needs_combined_status and not dry_run_mail and uid:
                                                                    try:
                                                                        rec_status = '送信済（M）' if mail_ok else '送信失敗（M）'
                                                                        rec = {
                                                                            'name': detail.get('name'),
                                                                            'furigana': detail.get('furigana', ''),
                                                                            'gender': detail.get('gender'),
                                                                            'birth': detail.get('birth'),
                                                                            'age': detail.get('age'),
                                                                            'email': to_email,
                                                                            'tel': detail.get('tel'),
                                                                            'addr': detail.get('addr'),
                                                                            'school': detail.get('school'),
                                                                            'oubo_no': detail.get('oubo_no'),
                                                                            'job_title': detail.get('title') or '',
                                                                            'source': 'engage',
                                                                            'platform': 'エンゲージ',
                                                                            'segment_title': matching_segment.get('title'),
                                                                            'status': rec_status,
                                                                            'response': mail_info if isinstance(mail_info, dict) else {'note': str(mail_info)},
                                                                            'sentAt': int(time.time())
                                                                        }
                                                                        write_sms_history(str(uid), rec)
                                                                    except Exception as e:
                                                                        print(f'メール履歴記録エラー: {e}')
                                                
                                                except Exception as e:
                                                    print(f'メール送信エラー: {e}')
                                            
                                            # SMS+Mail両方試行した場合の統合履歴記録
                                            if needs_combined_status and (sms_attempted or mail_attempted):
                                                dry_run_env = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
                                                dry_run_mail = os.environ.get('DRY_RUN_MAIL', 'false').lower() in ('1', 'true', 'yes')
                                                
                                                if not (dry_run_env and dry_run_mail) and uid:
                                                    try:
                                                        # 統合ステータス決定
                                                        if sms_ok and mail_ok:
                                                            combined_status = '送信済（M+S）'
                                                        elif sms_ok and not mail_ok:
                                                            combined_status = '送信済（S）'
                                                        elif not sms_ok and mail_ok:
                                                            combined_status = '送信済（M）'
                                                        else:
                                                            combined_status = '送信失敗（M+S）'
                                                        
                                                        combined_response = {
                                                            'sms': sms_info if isinstance(sms_info, dict) else {'note': str(sms_info)},
                                                            'mail': mail_info if isinstance(mail_info, dict) else {'note': str(mail_info)}
                                                        }
                                                        
                                                        rec = {
                                                            'name': detail.get('name'),
                                                            'furigana': detail.get('furigana', ''),
                                                            'gender': detail.get('gender'),
                                                            'birth': detail.get('birth'),
                                                            'age': detail.get('age'),
                                                            'email': detail.get('email'),
                                                            'tel': detail.get('tel'),
                                                            'addr': detail.get('addr'),
                                                            'school': detail.get('school'),
                                                            'oubo_no': detail.get('oubo_no'),
                                                            'job_title': detail.get('kyujin') or detail.get('title') or '',
                                                            'source': 'engage',
                                                            'platform': 'エンゲージ',
                                                            'segment_title': matching_segment.get('title'),
                                                            'status': combined_status,
                                                            'response': combined_response,
                                                            'sentAt': int(time.time())
                                                        }
                                                        write_sms_history(str(uid), rec)
                                                        print(f'✓ 統合履歴記録: {combined_status}')
                                                    except Exception as e:
                                                        print(f'統合履歴記録エラー: {e}')
                                        
                                        else:
                                            print('× セグメント条件に該当しません（エンゲージ）')
                                            # 対象外として記録
                                            try:
                                                rec = {
                                                    'name': detail.get('name'),
                                                    'furigana': detail.get('furigana', ''),
                                                    'gender': detail.get('gender'),
                                                    'birth': detail.get('birth'),
                                                    'age': detail.get('age'),
                                                    'email': detail.get('email'),
                                                    'tel': detail.get('tel'),
                                                    'addr': detail.get('addr'),
                                                    'employer_name': detail.get('employer_name') or detail.get('会社名') or detail.get('企業名') or '',
                                                    'work_prefecture': detail.get('work_prefecture') or detail.get('workPrefecture') or '',
                                                    'work_address': detail.get('work_address') or detail.get('workAddress') or '',
                                                    'oubo_no': detail.get('oubo_no'),
                                                    'job_title': detail.get('title') or '',
                                                    'source': 'engage',
                                                    'platform': 'エンゲージ',
                                                    'status': '対象外',
                                                    'response': {'note': 'セグメント条件不一致'},
                                                    'sentAt': int(time.time())
                                                }
                                                write_sms_history(str(uid), rec)
                                            except Exception:
                                                pass
                                
                                print('[エンゲージ] ブラウザを閉じます...')
                                try:
                                    engage.close()
                                    print('[エンゲージ] ✓ ブラウザ終了完了')
                                except Exception as close_err:
                                    print(f'[エンゲージ] ⚠️  ブラウザ終了エラー: {close_err}')
                                
                                print('[エンゲージ] ===== RPA処理完了 =====')
                                
                            except Exception as e:
                                print('=' * 60)
                                print('[エンゲージ] ❌ 処理中に例外が発生しました')
                                print('=' * 60)
                                print(f'エラータイプ: {type(e).__name__}')
                                print(f'エラー内容: {e}')
                                print('-' * 60)
                                import traceback
                                traceback.print_exc()
                                print('=' * 60)
                                print('⚠️  エラーが発生しましたが、プログラムは継続します。')
                                print('次のメール処理に進みます...')
                                # 确保浏览器关闭
                                try:
                                    if engage:
                                        engage.close()
                                        print('[エンゲージ] ブラウザを閉じました')
                                except Exception:
                                    pass
                        
                        except Exception as outer_err:
                            print('=' * 60)
                            print('[エンゲージ] ❌ 予期しないエラーが発生しました')
                            print('=' * 60)
                            print(f'エラータイプ: {type(outer_err).__name__}')
                            print(f'エラー内容: {outer_err}')
                            import traceback
                            traceback.print_exc()
                            print('=' * 60)
                            print('⚠️  プログラムは継続します。')
                            # 最后的保险措施
                            try:
                                if engage:
                                    engage.close()
                            except:
                                pass
                    
                    print('=' * 50)
                
                else:
                    # 非求人ボックス・非エンゲージ邮件，保持未读（不 fetch full body），不标记
                    pass
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print('\nRPAを停止しました。終了します')
    finally:
        try:
            conn.close()
            conn.logout()
        except Exception:
            pass


def main():
    print('RPA（求人ボックス用）を開始します')
    
    # 支持命令行参数：--uid UID --interval SECONDS
    import argparse
    parser = argparse.ArgumentParser(description='Email Watcher for 求人ボックス')
    parser.add_argument('--uid', type=str, help='UID（ユーザーID）')
    parser.add_argument('--interval', type=int, help='監視間隔（秒）', default=30)
    args = parser.parse_args()
    
    # 如果命令行提供了 UID，使用它；否则交互式输入
    if args.uid:
        uid = args.uid
        print(f'UID: {uid}')
    else:
        uid = prompt_input('UID を入力してください')

    # 从 Firestore 拉取该 UID 下的 mail_settings/settings 文档（返回 dict 包含 email 和 appPass）
    def get_mail_settings(uid):
        sa_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account')
        candidates = [
            os.path.join(os.getcwd(), 'service-account'),
            os.path.join(os.path.dirname(__file__), '..', 'service-account'),
            sa_path,
            os.path.join(os.getcwd(), 'src', 'service-account'),
        ]
        sa_file = None
        for c in candidates:
            if os.path.isfile(c):
                sa_file = c
                break
        if not sa_file:
            return {}
        try:
            import json
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
            with open(sa_file, 'r', encoding='utf-8') as f:
                sa = json.load(f)
            creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
            creds.refresh(Request())
            token = creds.token
        except Exception:
            return {}
        project = sa.get('project_id')
        if not project:
            return {}
        url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/mail_settings/settings'
        import requests
        headers = {'Authorization': f'Bearer {token}'}
        res = {}
        try:
            # 1. Fetch Jobbox settings (mail_settings)
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                fields = data.get('fields', {})
                if 'email' in fields:
                    res['email'] = fields['email'].get('stringValue')
                if 'appPass' in fields:
                    res['appPass'] = fields['appPass'].get('stringValue')
            
            # 2. Fetch Engage settings (engage_mail_settings)
            url_engage = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/engage_mail_settings/settings'
            r_engage = requests.get(url_engage, headers=headers, timeout=10)
            if r_engage.status_code == 200:
                data_engage = r_engage.json()
                fields_engage = data_engage.get('fields', {})
                if 'email' in fields_engage:
                    res['engageEmail'] = fields_engage['email'].get('stringValue')
                if 'appPass' in fields_engage:
                    res['engageAppPass'] = fields_engage['appPass'].get('stringValue')
                print(f"[DEBUG] Loaded Engage settings: {res.get('engageEmail')}")
            else:
                print(f"[DEBUG] Engage settings not found (status: {r_engage.status_code})")
            
            return res
        except Exception as e:
            print(f"[DEBUG] Error loading settings: {e}")
            return res

    settings = get_mail_settings(uid) or {}
    
    # 監視対象リストを作成
    monitor_targets = []

    # 1. 求人ボックス用メール（mail_settings）
    jobbox_user = settings.get('email')
    jobbox_pass = settings.get('appPass')
    env_pass = os.environ.get('EMAIL_WATCHER_PASS')
    if env_pass and len(env_pass) == 16:
        jobbox_pass = env_pass

    if jobbox_user and jobbox_pass:
        monitor_targets.append({
            'host': 'imap.gmail.com',
            'user': jobbox_user,
            'pass': jobbox_pass,
            'label': 'Jobbox',
            'category': 'jobbox'
        })
    else:
        print("-" * 40)
        print("求人ボックス用メール設定が不足しています。")
        print(f"accounts/{uid}/mail_settings/settings に email と appPass を登録してください。")
        print("-" * 40)
    
    # 2. エンゲージ用メール（engage_mail_settings）
    engage_user = settings.get('engageEmail')
    engage_pass = settings.get('engageAppPass')
    
    if engage_user and engage_pass:
        monitor_targets.append({
            'host': 'imap.gmail.com',
            'user': engage_user,
            'pass': engage_pass,
            'label': 'Engage',
            'category': 'engage'
        })
    else:
        print("-" * 40)
        print("エンゲージ用メール設定が見つかりませんでした。")
        print(f"accounts/{uid}/engage_mail_settings/settings に engageEmail と engageAppPass を設定してください。")
        print("-" * 40)

    if not monitor_targets:
        print('メール監視対象がありません。Firestoreの設定を確認してから再実行してください。')
        return

    # 共通設定
    imap_host = 'imap.gmail.com'
    
    # 如果命令行提供了 interval，使用它；否则交互式输入
    if args.interval and args.interval > 0:
        poll_seconds = args.interval
        print(f'監視間隔: {poll_seconds}秒')
    else:
        poll = prompt_input('間隔', default='30')
        try:
            poll_seconds = int(poll)
        except Exception:
            poll_seconds = 30
    
    # 启动定时任务后台线程 (UID単位で1つだけ)
    stop_event = threading.Event()
    if uid:
        task_thread = threading.Thread(target=scheduled_task_worker, args=(uid, stop_event), daemon=True)
        task_thread.start()
        print(f"スケジュール送信タスクを開始しました (UID: {uid})")

    # 各アカウントの監視スレッドを起動
    threads = []
    for target in monitor_targets:
        t = threading.Thread(
            target=watch_mail, 
            args=(target['host'], target['user'], target['pass'], uid, 'INBOX', poll_seconds, target['label'], target.get('category', 'auto'))
        )
        t.daemon = True
        t.start()
        threads.append(t)
        print(f"監視スレッド起動: {target['label']} ({target['user']})")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print('\nRPAを停止しました。終了します')



def send_sms_once(uid, to_number, template_type=None, live=False):
    """Send a single SMS using account uid. Returns (success, info).

    template_type: 'A' or 'B'
    live: if True, actually perform HTTP request; if False, just print constructed request.
    """
    # Read API settings
    api_cfg = get_api_settings(uid) or {}
    provider = (api_cfg.get('provider') or 'sms_publisher')
    base = api_cfg.get('baseUrl')
    if not base:
        return (False, 'no baseUrl configured for uid')

    # Read templates from target_settings
    def _get_target_settings_top(uid):
        sa_candidates = [
            os.path.join(os.getcwd(), 'service-account'),
            os.path.join(os.path.dirname(__file__), '..', 'service-account'),
            os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account'),
            os.path.join(os.getcwd(), 'src', 'service-account'),
        ]
        sa_file = None
        for c in sa_candidates:
            if os.path.isfile(c):
                sa_file = c; break
        if not sa_file:
            return {}
        try:
            import json
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
            with open(sa_file, 'r', encoding='utf-8') as f:
                sa = json.load(f)
            creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
            creds.refresh(Request())
            token = creds.token
        except Exception:
            return {}
        project = sa.get('project_id')
        if not project:
            return {}
        url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/target_settings/settings'
        import requests
        headers = {'Authorization': f'Bearer {token}'}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                return {}
            data = r.json()
            fields = data.get('fields', {})
            res = {}
            res['smsTemplateA'] = fields.get('smsTemplateA', {}).get('stringValue')
            res['smsTemplateB'] = fields.get('smsTemplateB', {}).get('stringValue')
            return res
        except Exception:
            return {}

    # Pick template based on target_settings and rotate nextSmsTemplate.
    # NOTE: This uses the module-level pick_and_rotate_template (best-effort GET then PATCH).

    ts = _get_target_settings_top(uid)
    tpl = None
    # If caller explicitly passed 'A' or 'B', use it; otherwise consult cloud settings via rotation helper
    if template_type in ('A', 'B'):
        chosen_type = template_type
    else:
        chosen_type = pick_and_rotate_template(uid)
    if chosen_type == 'A':
        tpl = ts.get('smsTemplateA')
    else:
        tpl = ts.get('smsTemplateB')
    if not tpl:
        return (False, 'no template found')

    # Normalize number
    norm, ok, reason = normalize_phone_number(to_number)
    if not ok:
        return (False, f'phone invalid: {reason}')

    # Build request per provider (only sms_publisher currently supported)
    if provider != 'sms_publisher':
        return (False, f'unsupported provider: {provider}')

    # default send config
    method = (api_cfg.get('method') or 'POST').upper()
    path = api_cfg.get('path') or '/send'
    # If base contains a path component (non-root), treat base as full URL. Otherwise append path.
    from urllib.parse import urlparse
    try:
        parsed = urlparse(base)
        if parsed.path and parsed.path not in ('', '/'):
            url = base
        else:
            url = base.rstrip('/') + (path if path.startswith('/') else '/' + path)
    except Exception:
        url = base.rstrip('/') + (path if path.startswith('/') else '/' + path)
    field_to = api_cfg.get('fieldTo') or 'to'
    field_message = api_cfg.get('fieldMessage') or 'message'

    headers = {'Accept': 'application/json'}
    params = {}
    data = None
    api_id = api_cfg.get('apiId')
    api_pass = api_cfg.get('apiPass')
    auth_type = api_cfg.get('auth')

    # For this provider, prefer form-encoded params: mobilenumber / smstext
    # Replace ampersand in message to avoid form parsing issues (match example)
    safe_msg = str(tpl).replace('&', '＆')
    # Build form data. If auth_type == 'params' include username/password in form; otherwise include only mobilenumber and smstext
    data = {
        'mobilenumber': str(norm),
        'smstext': safe_msg,
    }
    if auth_type == 'params' and api_id and api_pass:
        data['username'] = api_id
        data['password'] = api_pass

    # Header precedence: add Basic or Bearer if explicitly requested
    if auth_type == 'basic' and api_id and api_pass:
        import base64
        pair = f"{api_id}:{api_pass}"
        enc = base64.b64encode(pair.encode('utf-8')).decode('ascii')
        headers['Authorization'] = f'Basic {enc}'
    elif auth_type == 'bearer' and api_pass:
        headers['Authorization'] = f'Bearer {api_pass}'
    else:
        # If auth_type not specified but we have apiId+apiPass, prefer Basic auth
        if not auth_type and api_id and api_pass:
            import base64
            pair = f"{api_id}:{api_pass}"
            enc = base64.b64encode(pair.encode('utf-8')).decode('ascii')
            headers['Authorization'] = f'Basic {enc}'

    # Set content-type for form
    headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
    headers.setdefault('User-Agent', 'sms-rpa/1.0')

    # Show constructed request (form)
    print('--- SMS送信（構築内容）---')
    print('URL:', url)
    print('Method:', 'POST (form)')
    print('Headers:', headers)
    print('Params:', params)
    print('Form data:', data)

    if not live:
        return (True, 'dry run, no request sent')

    # perform request (POST form)
    try:
        r = requests.post(url, headers=headers, data=data, params=params, timeout=15)
        info = {'status_code': r.status_code, 'text': r.text[:2000]}
        # If provider returns 560 (invalid mobile), try converting to 81-prefixed and retry once
        if r.status_code == 560:
            alt = to81FromLocal(str(norm)) if 'to81' not in locals() else None
            if alt:
                data_alt = dict(data)
                data_alt['mobilenumber'] = alt
                print('Retrying with 81 prefixed number:', alt)
                try:
                    r2 = requests.post(url, headers=headers, data=data_alt, params=params, timeout=15)
                except Exception as e:
                    print('Retry request failed:', e)
                    return (False, {'error': str(e)})
                info = {'status_code': r2.status_code, 'text': r2.text[:2000]}
                if 200 <= r2.status_code < 300:
                    try:
                        info['json'] = r2.json()
                    except Exception:
                        pass
                    print('送信成功(リトライ)', info)
                    if live:
                        try:
                            # record the actual chosen_type used for this send
                            rec = {'tel': norm, 'status': '送信済（S）', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
                            write_sms_history(uid, rec)
                        except Exception:
                            pass
                    return (True, info)
                else:
                    print('送信失敗(リトライ)', info)
                    if live:
                        try:
                            rec = {'tel': norm, 'status': f'送信失敗（S）{r2.status_code}', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
                            write_sms_history(uid, rec)
                        except Exception:
                            pass
                    return (False, info)

        if 200 <= r.status_code < 300:
            try:
                info['json'] = r.json()
            except Exception:
                pass
            print('送信成功', info)
            if live:
                try:
                    # record the actual chosen_type used for this send
                    rec = {'tel': norm, 'status': '送信済（S）', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
                    write_sms_history(uid, rec)
                except Exception:
                    pass
            return (True, info)
        else:
            print('送信失敗', info)
            if live:
                try:
                    rec = {'tel': norm, 'status': f'送信失敗（S）{r.status_code}', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
                    write_sms_history(uid, rec)
                except Exception:
                    pass
            return (False, info)
    except Exception as e:
        # best-effort: record exception as failure in sms_history
        try:
            if live:
                rec = {'tel': norm if 'norm' in locals() else to_number, 'status': '送信失敗（S）', 'response': {'error': str(e)}, 'sentAt': int(time.time()), 'template': chosen_type if 'chosen_type' in locals() else None}
                write_sms_history(uid, rec)
        except Exception:
            pass
        return (False, {'error': str(e)})


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("\n" + "="*60)
        print("❌ 予期せぬエラーが発生しました (Fatal Error)")
        print("="*60) 
        print(f"エラー内容: {e}")
        import traceback
        traceback.print_exc()
        
        # エラーログをファイルに保存
        try:
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            log_file = os.path.join(log_dir, f'crash_{int(time.time())}.log')
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(f"Time: {datetime.now()}\n")
                f.write(f"Error: {e}\n")
                f.write(traceback.format_exc())
            print(f"\nエラーログを保存しました: {log_file}")
        except Exception:
            pass
            
        print("="*60)
    finally:
        print("\nプログラムを終了するにはEnterキーを押してください...")
        input()
