import imaplib
import email
import re
import time
import getpass
import sys
import os
from email.header import decode_header
import requests


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
    url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/api_settings/settings'
    import requests
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
            # some setups call it API pass or token
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
                                finally:
                                    try:
                                        jb.close()
                                    except Exception:
                                        pass
                                # 如果 login_and_goto 返回了 detail，则调用云端的 target_settings 做匹配判定
                                try:
                                    if info and isinstance(info, dict) and info.get('detail'):
                                        detail = info.get('detail')

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

                                        ts = get_target_settings(uid)
                                        is_target = evaluate_target(detail, ts)
                                        if is_target:
                                            print('この応募者は SMS の送信対象です。')
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
                                                    return True

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
                                                                try:
                                                                    j = r2.json()
                                                                    print('送信成功(リトライ)', {'status_code': r2.status_code, 'json': j})
                                                                except Exception:
                                                                    print('送信成功(リトライ)', {'status_code': r2.status_code, 'text': r2.text[:2000]})
                                                                return True
                                                            else:
                                                                print('送信失敗(リトライ)', {'status_code': r2.status_code, 'text': r2.text[:2000]})
                                                                return False

                                                    # Check HTTP status
                                                    if 200 <= r.status_code < 300:
                                                        # Try to parse JSON and check for success flags
                                                        try:
                                                            j = r.json()
                                                            if isinstance(j, dict):
                                                                if j.get("success") in (True, "true", "True", 1) or j.get("ok") in (True, "true", "True", 1):
                                                                    print(f"SMS PUBLISHER reported success for {to_number}")
                                                                    return True
                                                                # If no explicit flag, assume 2xx is success
                                                            print(f"SMS PUBLISHER returned 2xx for {to_number}: {r.status_code}")
                                                            return True
                                                        except ValueError:
                                                            # Not JSON, but 2xx -> success
                                                            print(f"SMS PUBLISHER returned 2xx for {to_number}: {r.status_code} (non-JSON)")
                                                            return True
                                                    else:
                                                        # Non-2xx
                                                        txt = r.text[:1000]
                                                        print(f"SMS PUBLISHER HTTP {r.status_code}: {txt}")
                                                        # Try JSON error details
                                                        try:
                                                            j = r.json()
                                                            if isinstance(j, dict) and (j.get("success") in (False, "false", "False", 0) or j.get("ok") in (False, "false", "False", 0)):
                                                                return False
                                                        except ValueError:
                                                            pass
                                                        return False

                                                except requests.RequestException as e:
                                                    print(f"Network error sending SMS via SMS PUBLISHER: {e}")
                                                    return False

                                            def send_sms_router(to_number, body):
                                                if provider == 'sms_publisher':
                                                    return send_via_sms_publisher(to_number, body, api_settings)
                                                # fallback: dry run / log
                                                dry = os.environ.get('DRY_RUN_SMS') in ('1','true','True')
                                                if dry:
                                                    print(f"[DRY_RUN] SMS ({provider}) => to={to_number} body={body}")
                                                    return True
                                                print(f"未対応のプロバイダ: {provider} - ログに記録します。")
                                                with open('sms_outbox.log', 'a', encoding='utf-8') as f:
                                                    f.write(f"{time.time()}\t{provider}\t{to_number}\t{body}\n")
                                                return True

                                            tel = detail.get('tel') or detail.get('電話番号') or ''
                                            tpl = ts.get('smsTemplateA') if ts.get('smsTemplateA') else ts.get('smsTemplateB')
                                            if tel and tpl:
                                                norm, ok, reason = normalize_phone_number(tel)
                                                if not ok:
                                                    print(f'電話番号の検証に失敗しました: {tel} -> {norm} 理由: {reason}。SMSは送信されません。')
                                                else:
                                                    send_sms_router(norm, tpl)
                                            else:
                                                print('電話番号またはテンプレートが不足しているため、SMSは送信されませんでした。')
                                        else:
                                            print('この応募者は SMS の対象外です。')
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


if __name__ == '__main__':
    main()


def send_sms_once(uid, to_number, template_type='A', live=False):
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

    ts = _get_target_settings_top(uid)
    tpl = None
    if template_type == 'A':
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
                r2 = requests.post(url, headers=headers, data=data_alt, params=params, timeout=15)
                info = {'status_code': r2.status_code, 'text': r2.text[:2000]}
                if 200 <= r2.status_code < 300:
                    try:
                        info['json'] = r2.json()
                    except Exception:
                        pass
                    print('送信成功(リトライ)', info)
                    return (True, info)
                else:
                    print('送信失敗(リトライ)', info)
                    return (False, info)

        if 200 <= r.status_code < 300:
            try:
                info['json'] = r.json()
            except Exception:
                pass
            print('送信成功', info)
            return (True, info)
        else:
            print('送信失敗', info)
            return (False, info)
    except Exception as e:
        return (False, str(e))
