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


def prompt_input(prompt, default=None):
    if default:
        v = input(f"{prompt} [{default}]: ")
        return v.strip() or default
    return input(f"{prompt}: ").strip()


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
    return {
        'account_name': account_name,
        'account_id': account_id,
        'job_title': job_title,
        'url': url,
        'oubo_no': oubo_no
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
    """Read accounts/{uid}/mail_settings/settings from Firestore using service account file."""
    sa_file = _find_service_account_file()
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
    # proceed to read the mail_settings document
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


def _get_target_segments(uid: Optional[str]) -> list:
    """Read all enabled segments from accounts/{uid}/target_segments collection from Firestore."""
    sa_file = _find_service_account_file()
    if not sa_file:
        return []
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
        return []
    
    project = sa.get('project_id') if isinstance(sa, dict) else None
    if not project:
        return []
    
    # Query the target_segments collection
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
            
            # Extract segment data
            segment = {
                'id': doc.get('name', '').split('/')[-1],
                'title': _extract_string_value(fields.get('title', {})),
                'enabled': _extract_bool_value(fields.get('enabled', {})),
                'priority': _extract_int_value(fields.get('priority', {})),
                'conditions': _extract_conditions(fields.get('conditions', {})),
                'actions': _extract_actions(fields.get('actions', {}))
            }
            
            # Only include enabled segments
            if segment['enabled']:
                segments.append(segment)
        
        # Sort by priority (lower number = higher priority)
        segments.sort(key=lambda x: x['priority'])
        return segments
        
    except Exception as e:
        print(f"Error reading target_segments: {e}")
        return []


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

    ok_mail, info_mail = send_mail_once(sender, sender_pass, to_email, subj or '', body or '')
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
    # Duplicate-send guard: if a recent sms_history with same oubo_no and tel and status 'sent'
    # exists within a short time window, skip writing to avoid duplicates.
    try:
        try:
            with open(sa_file, 'r', encoding='utf-8') as f:
                sa = json.load(f) # type: ignore
        except Exception:
            sa = None
        if sa and uid and doc:
            project = sa.get('project_id')
            if project:
                # prepare a structuredQuery to find recent matching records
                oubo = doc.get('oubo_no') or ''
                tel = doc.get('tel') or ''
                now_ts = int(time.time())
                recent_threshold = 120  # seconds
                body = {
                    "structuredQuery": {
                        "from": [{"collectionId": "sms_history"}],
                        "where": {
                            "compositeFilter": {
                                "op": "AND",
                                "filters": [
                                    {"fieldFilter": {"field": {"fieldPath": "oubo_no"}, "op": "EQUAL", "value": {"stringValue": str(oubo)}}},
                                    {"fieldFilter": {"field": {"fieldPath": "tel"}, "op": "EQUAL", "value": {"stringValue": str(tel)}}},
                                    {"fieldFilter": {"field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": "送信済"}}},
                                    {"fieldFilter": {"field": {"fieldPath": "sentAt"}, "op": "GREATER_THAN", "value": {"integerValue": str(now_ts - recent_threshold)}}}
                                ]
                            }
                        },
                        "limit": 1
                    }
                }
                # get short-lived token
                try:
                    from google.oauth2 import service_account
                    from google.auth.transport.requests import Request
                    creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
                    creds.refresh(Request())
                    token = creds.token
                    run_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents:runQuery'
                    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                    r = requests.post(run_url, headers=headers, json=body, timeout=8)
                    if r.status_code == 200:
                        try:
                            results = r.json()
                            if isinstance(results, list) and len(results) > 0:
                                # if any document matched, consider duplicate
                                # Each result entry may be an object with document key when matched
                                for entry in results:
                                    if entry and entry.get('document'):
                                        print('Detected recent duplicate sms_history entry; skipping write')
                                        return True
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception:
        pass
    try:
        import json
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
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
            print('Failed to write sms_history', r.status_code, r.text[:1000])
            return False
    except Exception as e:
        print('Exception writing sms_history:', e)
        return False


def watch_mail(imap_host, email_user, email_pass, uid=None, folder='INBOX', poll_seconds=30):
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
                            base_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/jobbox_accounts'
                            import requests
                            headers = {'Authorization': f'Bearer {token}'}
                            names = []
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
                                        jid = flds.get('jobbox_id', {}).get('stringValue')
                                        jpwd = flds.get('jobbox_password', {}).get('stringValue')
                                        if an:
                                            names.append(an)
                                            accounts.append({'account_name': an, 'jobbox_id': jid, 'jobbox_password': jpwd})
                                    page_token = data.get('nextPageToken')
                                    if not page_token:
                                        break
                                return accounts
                            except Exception:
                                return accounts

                        remote_accounts = get_jobbox_accounts(uid)
                        match_account = None
                        parsed_name = (parsed.get('account_name') or '').strip()
                        import re  # Ensure re module is available in this scope
                        def _norm(s):
                            return re.sub(r'\s+', '', (s or '').strip())
                        for ra in remote_accounts:
                            ra_name = ra.get('account_name')
                            if _norm(ra_name) == _norm(parsed_name) or _norm(ra_name) in _norm(parsed_name) or _norm(parsed_name) in _norm(ra_name):
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
                                        is_target = matching_segment is not None
                                        
                                        if is_target:
                                            print(f'この応募者はSMSの送信対象です。（「{matching_segment["title"]}」セグメントに該当）')
                                        else:
                                            print('この応募者はSMSの送信対象ではありません。')
                                        
                                        if is_target:
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
                                            sms_action = matching_segment['actions']['sms']
                                            tpl = sms_action['text'] if sms_action['enabled'] else None
                                            if tel and tpl and sms_action['enabled']:
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
                                                    success, info = send_sms_router(norm, tpl)
                                                    # If not dry-run, record history for both success and failure
                                                    if not dry_run_env and uid:
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
                                                                rec_status = '送信済'
                                                            else:
                                                                rec_status = f"送信失敗{status_code}" if status_code else '送信失敗'
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
                                                                'template': matching_segment.get('title') if matching_segment else 'unknown',
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
                                                    # Mail auto-reply (for target as well): call and capture result
                                                    mail_attempted = False
                                                    mail_ok = False
                                                    mail_info = {}
                                                    # Display email target status using new segment system
                                                    if is_target:
                                                        print(f'この応募者はメールの送信対象です。（「{matching_segment["title"]}」セグメントに該当）')
                                                    else:
                                                        print('この応募者はメールの送信対象ではありません。')
                                                    
                                                    # Send email using segment's mail content
                                                    mail_attempted = False
                                                    mail_ok = False
                                                    mail_info = {}
                                                    
                                                    if is_target:
                                                        try:
                                                            mail_action = matching_segment['actions']['mail']
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
                                                                        
                                                                        # Send HTML email
                                                                        mail_ok, mail_info = _send_html_mail(sender, sender_pass, to_email, subject, body)
                                                                        if mail_ok:
                                                                            print(f'メール送信成功: {to_email} (件名: {subject})')
                                                                        else:
                                                                            print(f'メール送信失敗: {to_email} - {mail_info}')
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

                                                    # Append Jobbox memo entries for SMS and MAIL results (do not overwrite)
                                                    try:
                                                        # SMS memo: only when candidate is target, and not dry-run
                                                        if is_target and (not dry_run_env):
                                                            try:
                                                                # Build SMS memo text. Include status code when present.
                                                                sms_note = 'RPA:SMS:送信済み' if success else 'RPA:SMS:送信失敗'
                                                                if isinstance(info, dict):
                                                                    try:
                                                                        raw_sc = info.get('status_code')
                                                                        sc = None
                                                                        if raw_sc is not None:
                                                                            # Coerce via str() first to handle unions like str|int|None
                                                                            try:
                                                                                sc = int(str(raw_sc))
                                                                            except Exception:
                                                                                sc = None
                                                                        if sc is not None:
                                                                            if not success:
                                                                                sms_note = f"RPA:SMS:送信失敗{sc}"
                                                                            else:
                                                                                sms_note = f"RPA:SMS:送信済み({sc})"
                                                                    except Exception:
                                                                        pass
                                                                try:
                                                                    if jb:
                                                                        jb.set_memo_and_save(sms_note)
                                                                except Exception as e:
                                                                    print('メモ保存(SMS)時に例外が発生しました:', e)
                                                            except Exception:
                                                                pass

                                                        # MAIL memo: if mail was attempted (real attempt) and not dry-run, record result
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
                                                                    if jb:
                                                                        jb.set_memo_and_save(mail_note)
                                                                except Exception as e:
                                                                    print('メモ保存(MAIL)時に例外が発生しました:', e)
                                                            except Exception:
                                                                pass
                                                    except Exception as e:
                                                        print('メモ追記処理で例外:', e)
                                            # Ensure jb is closed after processing this match_account
                                            try:
                                                jb.close()
                                            except Exception:
                                                pass
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
                                                send_auto_reply_if_configured(uid, mail_cfg, False, detail, jb)
                                            except Exception as e:
                                                print('メール送信処理中に例外が発生しました(対象外):', e)
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
                                                        try:
                                                            jb.set_memo_and_save('RPA:対象外')
                                                        except Exception as e:
                                                            print('メモ保存(対象外)時に例外が発生しました:', e)
                                                except Exception:
                                                    pass
                                except Exception as e:
                                    print(f'対象判定中に例外が発生しました: {e}')
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
                # Use updateMask to avoid overwriting the full document (which
                # can unintentionally clear other fields). Only update
                # nextSmsTemplate.
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
                            rec = {'tel': norm, 'status': '送信済', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
                            write_sms_history(uid, rec)
                        except Exception:
                            pass
                    return (True, info)
                else:
                    print('送信失敗(リトライ)', info)
                    if live:
                        try:
                            rec = {'tel': norm, 'status': f'送信失敗{r2.status_code}', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
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
                    rec = {'tel': norm, 'status': '送信済', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
                    write_sms_history(uid, rec)
                except Exception:
                    pass
            return (True, info)
        else:
            print('送信失敗', info)
            if live:
                try:
                    rec = {'tel': norm, 'status': f'送信失敗{r.status_code}', 'response': info, 'sentAt': int(time.time()), 'template': chosen_type}
                    write_sms_history(uid, rec)
                except Exception:
                    pass
            return (False, info)
    except Exception as e:
        # best-effort: record exception as failure in sms_history
        try:
            if live:
                rec = {'tel': norm if 'norm' in locals() else to_number, 'status': '送信失敗', 'response': {'error': str(e)}, 'sentAt': int(time.time()), 'template': chosen_type if 'chosen_type' in locals() else None}
                write_sms_history(uid, rec)
        except Exception:
            pass
        return (False, {'error': str(e)})


if __name__ == '__main__':
    main()
