import os, json, re, sys
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, 'src')
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from email_watcher import apply_template_tokens, _find_service_account_file  # type: ignore


def _get_target_settings(uid: str) -> dict:
    """A minimal reader for accounts/{uid}/target_settings/settings via Firestore REST using service-account.
    Returns dict with mailSubjectA/B and mailTemplateA/B.
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        raise RuntimeError('service-account file not found')
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
        project = sa.get('project_id')
        if not project:
            raise RuntimeError('service account missing project_id')
    except Exception as e:
        raise RuntimeError(f'failed to prepare service account creds: {e}')

    url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/target_settings/settings'
    import requests
    r = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f'get target_settings failed: {r.status_code}')
    data = r.json().get('fields', {})
    def _s(v):
        return (v or {}).get('stringValue') if isinstance(v, dict) else None
    def _b(v, dv=False):
        if isinstance(v, dict) and 'booleanValue' in v:
            return bool(v.get('booleanValue'))
        return dv
    return {
        'autoReply': _b(data.get('autoReply'), False),
        'mailUseTarget': _b(data.get('mailUseTarget'), True),
        'mailUseNonTarget': _b(data.get('mailUseNonTarget'), False),
        'mailSubjectA': _s(data.get('mailSubjectA')) or '',
        'mailTemplateA': _s(data.get('mailTemplateA')) or '',
        'mailSubjectB': _s(data.get('mailSubjectB')) or '',
        'mailTemplateB': _s(data.get('mailTemplateB')) or '',
    }

def _get_segments(uid: str) -> list:
    sa_file = _find_service_account_file()
    if not sa_file:
        raise RuntimeError('service-account file not found')
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        token = creds.token
        project = sa.get('project_id')
        if not project:
            raise RuntimeError('service account missing project_id')
    except Exception as e:
        raise RuntimeError(f'failed to prepare service account creds: {e}')

    import requests
    url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/target_segments'
    r = requests.get(url, headers={'Authorization': f'Bearer {token}'}, timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f'get target_segments failed: {r.status_code}')
    docs = r.json().get('documents', []) or []
    segs = []
    for d in docs:
        fields = (d or {}).get('fields', {})
        def _s(v):
            return (v or {}).get('stringValue') if isinstance(v, dict) else None
        def _b(v, dv=False):
            if isinstance(v, dict) and 'booleanValue' in v:
                return bool(v.get('booleanValue'))
            return dv
        def _i(v, dv=0):
            try:
                return int((v or {}).get('integerValue')) if isinstance(v, dict) else dv
            except Exception:
                return dv
        seg = {
            'id': (d.get('name','').split('/')[-1]) or None,
            'title': _s(fields.get('title')) or '',
            'enabled': _b(fields.get('enabled'), False),
            'priority': _i(fields.get('priority'), 0),
            'mail': {
                'enabled': _b(((fields.get('actions') or {}).get('mapValue') or {}).get('fields', {}).get('mail'), False),
            }
        }
        # Extract mail action map fully
        try:
            mail_map = (((fields.get('actions') or {}).get('mapValue') or {}).get('fields', {}).get('mail') or {})
            if 'mapValue' in mail_map:
                mf = (mail_map['mapValue'] or {}).get('fields', {})
                seg['mail'] = {
                    'enabled': _b(mf.get('enabled'), False),
                    'subject': _s(mf.get('subject')) or '',
                    'body': _s(mf.get('body')) or '',
                }
        except Exception:
            pass
        segs.append(seg)
    # sort by priority asc
    segs.sort(key=lambda x: x.get('priority', 0))
    return segs


def preview(uid: str, target: bool, detail: dict, segment_id: Optional[str] = None, list_only: bool = False):
    ts = _get_target_settings(uid)
    segs = _get_segments(uid)
    if list_only:
        print('=== SEGMENTS ===')
        for s in segs:
            print(f"{s.get('id')} | prio={s.get('priority')} | enabled={s.get('enabled')} | title={s.get('title')}")
        return

    # Decide source of subject/body
    subject = ''
    body = ''
    chosen_src = ''
    if segment_id:
        sel = next((s for s in segs if s.get('id') == segment_id), None)
        if not sel:
            raise RuntimeError(f'segment id not found: {segment_id}')
        mail = (sel.get('mail') or {})
        subject = mail.get('subject') or ''
        body = mail.get('body') or ''
        chosen_src = f"segment:{segment_id}"
    else:
        if not ts.get('autoReply'):
            print('[NOTE] autoReply=false -> 本来不会发送自动回复邮件')
        if target and not ts.get('mailUseTarget', True):
            print('[NOTE] mailUseTarget=false -> 本来不会给目标发送邮件')
        if (not target) and not ts.get('mailUseNonTarget', False):
            print('[NOTE] mailUseNonTarget=false -> 本来不会给非目标发送邮件')
        subject = ts['mailSubjectA'] if target else ts['mailSubjectB']
        body = ts['mailTemplateA'] if target else ts['mailTemplateB']
        chosen_src = 'target_settings(A/B)'

    # 构造 data_map（与生产一致的同义词容错）
    data_map = {
        'applicant_name': detail.get('name') or detail.get('氏名'),
        'job_title': detail.get('job_title') or detail.get('求人タイトル') or detail.get('jobTitle') or detail.get('職種'),
        'company': detail.get('account_name') or detail.get('アカウント名') or detail.get('company') or detail.get('会社名'),
    }

    subject_out = apply_template_tokens(subject or '', data_map)
    body_out = apply_template_tokens(body or '', data_map)

    print('=== PREVIEW MAIL ===')
    print('Source     :', chosen_src)
    print('Target?    :', target)
    print('Subject(raw):', subject)
    print('Body(raw)  :', (body or '')[:500])
    print('--- After substitution ---')
    print('Subject    :', subject_out)
    print('Body       :', body_out)


def main():
    import argparse
    p = argparse.ArgumentParser(description='Preview mail content without sending (simulate RPA composition).')
    p.add_argument('--uid', required=True, help='accounts/{uid} to read target_settings from')
    p.add_argument('--target', action='store_true', help='preview as target (A); default is non-target (B)')
    p.add_argument('--detail', help='JSON of detail fields (name, job_title, account_name, etc.)')
    p.add_argument('--segment-id', help='Preview using a specific segment actions.mail (subject/body)')
    p.add_argument('--list-segments', action='store_true', help='List segments and exit')
    args = p.parse_args()

    detail = {}
    if args.detail:
        try:
            detail = json.loads(args.detail)
        except Exception:
            print('[WARN] detail JSON 解析失败，使用空对象')
            detail = {}
    # 提供一个合理的默认 detail，方便快速试用
    if not detail:
        detail = {
            'name': 'テスト 太郎',
            'job_title': 'WEBデザイナー',
            'account_name': 'りくらぼ株式会社',
            'email': 'foo@example.com',
        }

    preview(args.uid, bool(args.target), detail, segment_id=args.segment_id, list_only=bool(args.list_segments))


if __name__ == '__main__':
    main()
