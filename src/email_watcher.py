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
    url = ''
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
    # 找到応募者一覧的 URL：支持带说明的下一行，也支持直接键值对如 '応募者一覧URL: https...'
    m = re.search(r'応募者一覧はこちらからご確認ください[\s\S]*?\n(https?://\S+)', body)
    if not m:
        m = re.search(r'応募者一覧URL[:：\s]*\s*(https?://\S+)', body)
    if not m:
        m = re.search(r'応募者一覧[:：\s]*\s*(https?://\S+)', body)
    if m:
        url = m.group(1).strip()
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
        'url': url,
        'oubo_no': oubo_no,
        'employer_name': employer_name
    }


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

    Returns dict with possible keys 'email' and 'appPass'. Empty dict on failure.
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

def _extract_sms_action(sms_field):
    """Extract SMS action from Firestore mapValue."""
    if sms_field.get('mapValue'):
        fields = sms_field['mapValue'].get('fields', {})
        return {
            'enabled': _extract_bool_value(fields.get('enabled', {})),
            'text': _extract_string_value(fields.get('text', {}))
        }
    return {}

def _extract_mail_action(mail_field):
    """Extract mail action from Firestore mapValue."""
    if mail_field.get('mapValue'):
        fields = mail_field['mapValue'].get('fields', {})
        return {
            'enabled': _extract_bool_value(fields.get('enabled', {})),
            'subject': _extract_string_value(fields.get('subject', {})),
            'body': _extract_string_value(fields.get('body', {}))
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
    sender = os.environ.get('EMAIL_WATCHER_ADDR') or mail_settings.get('email')
    sender_pass = os.environ.get('EMAIL_WATCHER_PASS') or mail_settings.get('appPass')
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
                write_doc['sentAt'] = int(existing_sentAt or now_ts)
                write_doc['sms_status'] = final_sms_state
                write_doc['mail_status'] = final_mail_state
                if final_resp:
                    write_doc['response'] = final_resp
                write_doc['status'] = status_str

                # PATCH existing document
                try:
                    patch_url = f'https://firestore.googleapis.com/v1/{existing_name}'
                    r = requests.patch(patch_url, headers={**headers, 'Content-Type': 'application/json'}, json={'fields': _make_fields_for_firestore(write_doc)}, timeout=12)
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



def watch_mail(imap_host, email_user, email_pass, uid=None, folder='INBOX', poll_seconds=30):  # type: ignore
    print('IMAPサーバーに接続しています...')
    conn = imaplib.IMAP4_SSL(imap_host)
    conn.login(email_user, email_pass)
    print('ログインしました。未読メールを監視します（Ctrl+C で停止）')
    try:
        while True:
            conn.select(folder)
            # 查找所有未读邮件
            status, data = conn.search(None, 'UNSEEN')
            if status != 'OK':
                time.sleep(poll_seconds)
                continue
            ids = data[0].split()
            if not ids:
                # 没有未读
                time.sleep(poll_seconds)
                continue
            for num in ids:
                # 先只抓头部，避免把非目标邮件标记为已读
                status, msg_data = conn.fetch(num, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])')
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
                subject = ''
                if hdr_bytes:
                    try:
                        hdr_msg = email.message_from_bytes(hdr_bytes)
                        subject = decode_subject(hdr_msg.get('Subject') or '')
                    except Exception:
                        try:
                            raw = hdr_bytes.decode('utf-8', errors='ignore')
                            subj_match = re.search(r'Subject:\s*(.*)', raw)
                            subject = decode_subject(subj_match.group(1).strip()) if subj_match else ''
                        except Exception:
                            subject = ''
                # 简单判断是否为求人ボックス（主题包含关键词）
                if '新着応募のお知らせ' in subject:
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
                    print('---- 求人ボックスの未読メールを検出 ----')
                    print('件名:', subject)
                    print('アカウント名:', parsed['account_name'])
                    print('アカウントID:', parsed['account_id'])
                    print('求人タイトル:', parsed['job_title'])
                    print('応募者一覧URL:', parsed['url'])
                    # 标记为已读
                    conn.store(num, '+FLAGS', '\\Seen')
                    # URL が見つかったら自動でログイン処理を実行（確認プロンプトは表示しない）
                    if parsed.get('url') and parsed.get('account_name'):
                        print('応募者一覧のURLを検出しました。\n自動でログイン処理を実行します。')

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
                                    print(f"[DEBUG_JOBBOX] returning cached jobbox_accounts for uid={uid} (age={int(time.time()-ts)}s)")
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
                                print(f"[DEBUG_JOBBOX] service-account load+token refresh took {int((t1-t0)*1000)}ms")
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
                                        print(f"[DEBUG_JOBBOX] requests.get returned {r.status_code}")
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
                                print(f"[DEBUG_JOBBOX] fetched {len(accounts)} accounts in {int((t_end-t_start)*1000)}ms (network {int(network_time*1000)}ms)")
                                # store in cache
                                try:
                                    cache[uid] = (time.time(), accounts)
                                except Exception:
                                    pass
                                return accounts
                            except Exception as e:
                                print(f"[DEBUG_JOBBOX] exception while fetching jobbox_accounts: {e}")
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
                            print(f"メール内のアカウント名 '{parsed_name}' は jobbox_accounts に見つかりませんでした。自動ログインをスキップします。")
                            continue

                        try:
                            from jobbox_login import JobboxLogin
                        except Exception:
                            print('自動ログイン機能は無効です：`src/jobbox_login.py` を確認してください。')
                        else:
                            try:
                                jb = JobboxLogin(match_account)
                            except Exception as e:
                                print(f'アカウントの初期化に失敗しました: {e}')
                            else:
                                try:
                                    info = jb.login_and_goto(parsed.get('url'), parsed.get('job_title'), parsed.get('oubo_no'))
                                except Exception as e:
                                    print(f'自動ログイン中に例外が発生しました: {e}')
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
                                                    y = None
                                                    m = re.search(r'(19|20)\d{2}', birth)
                                                    if m:
                                                        try:
                                                            y = int(m.group(0))
                                                        except:
                                                            y = None
                                                    if y:
                                                        import datetime
                                                        now = datetime.datetime.now().year
                                                        age = now - y
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
                                                        age_ok = True

                                                return bool(name_ok and gender_ok and age_ok)
                                            except Exception:
                                                return False

                                        # Calculate age from birth date if not present
                                        if 'age' not in detail or not detail.get('age'):
                                            birth_str = detail.get('birth', '') or ''
                                            calculated_age = 0
                                            if birth_str:
                                                try:
                                                    # Try to extract year from birth string (e.g., "1980年1月12日" or "1980年1月12日（45歳）")
                                                    import re
                                                    year_match = re.search(r'(\d{4})年', birth_str)
                                                    if year_match:
                                                        birth_year = int(year_match.group(1))
                                                        import datetime
                                                        current_year = datetime.datetime.now().year
                                                        calculated_age = current_year - birth_year
                                                except Exception as e:
                                                    pass
                                            
                                            # Add calculated age to detail
                                            detail['age'] = calculated_age

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
                                            print(f'この応募者はSMSの送信対象です。（「{sms_target_segment["title"]}」セグメントに該当）')
                                        else:
                                            print('この応募者はSMSの送信対象ではありません。')
                                        
                                        if mail_target_segment:
                                            print(f'この応募者はメールの送信対象です。（「{mail_target_segment["title"]}」セグメントに該当）')
                                        else:
                                            print('この応募者はメールの送信対象ではありません。')

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

                                            def send_via_sms_publisher(to_number, body, api_cfg):
                                                """Send SMS via SMS PUBLISHER.

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
                                                    return False

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

                                            def send_sms_router(to_number, body):
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

                                            tel = detail.get('tel') or detail.get('電話番号') or ''
                                            
                                            # Use segment's SMS content
                                            sms_action = sms_target_segment['actions']['sms']
                                            tpl = sms_action['text'] if sms_action['enabled'] else None
                                            if tel and tpl and sms_target_segment and sms_action['enabled']:
                                                norm, ok, reason = normalize_phone_number(tel)
                                                dry_run_env = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
                                                if not ok:
                                                    print(f'電話番号の検証に失敗しました: {tel} -> {norm} 理由: {reason}。SMSは送信されません。')
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
                                                                'school': detail.get('school'),
                                                                'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                                'status': '送信失敗',
                                                                'response': {'note': f'invalid phone: {reason}'},
                                                                'sentAt': int(time.time())
                                                            }
                                                            ok_write = write_sms_history(str(uid), rec)
                                                            if not ok_write:
                                                                print('Failed to write sms_history for invalid phone')
                                                        except Exception as e:
                                                            print('Exception when writing sms_history for invalid phone:', e)
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

                                                    success, info = send_sms_router(norm, tpl_to_send)
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
                                                                'school': detail.get('school'),
                                                                'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
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
                                                        # Determine label/title to use: prefer sms_target_segment title, else mail_target_segment title, else None
                                                        label = None
                                                        try:
                                                            if sms_target_segment and sms_target_segment.get('title'):
                                                                label = sms_target_segment.get('title')
                                                            elif mail_target_segment and mail_target_segment.get('title'):
                                                                label = mail_target_segment.get('title')
                                                        except Exception:
                                                            label = None

                                                        # SMS result
                                                        try:
                                                            if is_target:
                                                                if success:
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
                                                        if not label:
                                                            memo_text = '対象外'
                                                        else:
                                                            ts = time.localtime()
                                                            ts_str = time.strftime('%Y/%m/%d, %H:%M', ts)
                                                            memo_text = f"【{label}】：{sms_result}/{mail_result}，{ts_str}"

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
                                                            'school': detail.get('school'),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
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
                                        
                                        if mail_target_segment:
                                            try:
                                                mail_action = mail_target_segment['actions']['mail']
                                                if mail_action['enabled'] and mail_action['subject'] and mail_action['body']:
                                                    to_email = detail.get('email', '').strip()
                                                    if to_email:
                                                        # Get mail settings (sender credentials)
                                                        mail_cfg = _get_mail_settings(str(uid) if uid is not None else "")
                                                        sender = mail_cfg.get('email', '')
                                                        sender_pass = mail_cfg.get('appPass', '')
                                                        
                                                        if sender and sender_pass:
                                                            mail_attempted = True
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
                                                                    'applicant_name': applicant_name,
                                                                    'name': applicant_name,
                                                                    '氏名': applicant_name,
                                                                    'job_title': job_title_val,
                                                                    'position': job_title_val,
                                                                    '求人タイトル': job_title_val,
                                                                    '職種': job_title_val,
                                                                    'company': company_val,
                                                                    'account_name': company_val,
                                                                    'アカウント名': company_val,
                                                                    'employer_name': employer_name_val,
                                                                    'employer': employer_name_val,
                                                                    '会社名': employer_name_val,  # 重要：会社名トークン用
                                                                    '掲載企業名': employer_name_val,
                                                                    '企業名': employer_name_val,
                                                                }
                                                            except Exception:
                                                                data_for_mail = {}
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
                                                            
                                                            mail_attempted = True
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
                                                                        'school': detail.get('school'),
                                                                        'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                                        'status': '送信済（M）' if mail_ok else '送信失敗（M）',  # M for Mail
                                                                        'response': mail_info if isinstance(mail_info, dict) else {'note': str(mail_info)},
                                                                        'sentAt': int(time.time())
                                                                    }
                                                                    ok_write_history = write_sms_history(str(uid), rec)  # Use same table as SMS
                                                                    if not ok_write_history:
                                                                        logger.error('履歴の書き込みに失敗しました（メール）')
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
                                                        'school': detail.get('school'),
                                                        'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                        'status': combined_status,
                                                        'response': combined_response if combined_response else {'note': 'combined attempt'},
                                                        'sentAt': int(time.time())
                                                    }
                                                    
                                                    ok_write_combined = write_sms_history(str(uid), rec)
                                                    if not ok_write_combined:
                                                        logger.error('組み合わせ履歴の書き込みに失敗しました')
                                                except Exception as e:
                                                    logger.error(f'組み合わせ履歴書き込み例外: {e}')
                                        
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
                                                            'school': detail.get('school'),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
                                                            'status': mail_status,
                                                            'response': mail_sent_info if isinstance(mail_sent_info, dict) else {'note': str(mail_sent_info)},
                                                            'sentAt': int(time.time())
                                                        }
                                                        ok_write_mail2 = write_sms_history(str(uid), rec)  # Use same table as SMS
                                                        if not ok_write_mail2:
                                                            logger.error('Failed to write mail_history (non-target)')
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
                                                            'school': detail.get('school'),
                                                            'oubo_no': detail.get('oubo_no') or detail.get('応募No') or detail.get('oubo_no_extracted'),
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
                else:
                    # 非求人ボックス邮件，保持未读（不 fetch full body），不标记
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
    # 全角日语提示：输入 UID（ユーザーID）
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
            return res
        except Exception:
            return {}

    settings = get_mail_settings(uid)
    email_user = settings.get('email')
    if not email_user:
        email_user = prompt_input('監視するメールアドレスを入力してください')
    # 16桁アプリパスワード：環境変数（EMAIL_WATCHER_PASS）を優先、なければ可視入力で取得
    env_pass = os.environ.get('EMAIL_WATCHER_PASS')
    if env_pass and len(env_pass) == 16:
        email_pass = env_pass
    else:
        # 尝试从云端读取 appPass
        cloud_app_pass = settings.get('appPass') if settings else None
        if cloud_app_pass and len(cloud_app_pass) == 16:
            email_pass = cloud_app_pass
        else:
            while True:
                try:
                    # 明示的可视入力（保留原行为）
                    email_pass = input('16桁のアプリパスワードを入力してください: ').strip()
                except Exception:
                    email_pass = input('16桁のアプリパスワードを入力してください: ').strip()
                if len(email_pass) == 16:
                    break
                print('16桁のアプリパスワードを正しく入力してください')
    # 直接使用默认 IMAP サーバー，不再要求手动确认
    imap_host = 'imap.gmail.com'
    poll = prompt_input('間隔', default='30')
    try:
        poll_seconds = int(poll)
    except Exception:
        poll_seconds = 30
    watch_mail(imap_host, email_user, email_pass, uid=uid, poll_seconds=poll_seconds)


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
    main()
