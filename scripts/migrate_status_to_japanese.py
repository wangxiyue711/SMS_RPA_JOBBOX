"""Batch-migrate Firestore sms_history documents with status 'sent' -> '送信済'.

Usage:
  - Place a service-account JSON file in one of the repository's service-account locations.
  - Run in dry-run mode to see which documents would be changed:
      python scripts\migrate_status_to_japanese.py --dry-run
  - To actually apply changes (be careful):
      python scripts\migrate_status_to_japanese.py --apply

Options:
  --uid UID      Optional: restrict migration to a single account UID
  --dry-run      Default: True; only list documents
  --apply        Apply changes (must be explicit)

The script uses Firestore REST API and service account credentials (google.oauth2.service_account).
"""
import os
import json
import argparse
import time
from typing import Optional

try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import Request
    import requests
except Exception:
    # We won't import at top-level failure; allow script to report missing deps
    pass

SERVICE_ACCOUNT_CANDIDATES = [
    os.path.join(os.getcwd(), 'service-account'),
    os.path.join(os.path.dirname(__file__), '..', 'service-account'),
    os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'service-account'),
    os.path.join(os.getcwd(), 'src', 'service-account'),
]


def find_service_account() -> Optional[str]:
    for p in SERVICE_ACCOUNT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return None


def get_access_token(sa_path: str) -> Optional[dict]:
    try:
        with open(sa_path, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(sa, scopes=['https://www.googleapis.com/auth/datastore'])
        creds.refresh(Request())
        return {'token': creds.token, 'project': sa.get('project_id')}
    except Exception as e:
        print('Failed to load service account or obtain token:', e)
        return None


def list_sms_history_docs(project: str, token: str, uid: Optional[str] = None):
    base = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents'
    coll = 'sms_history'
    if uid:
        url = f"{base}/accounts/{uid}/{coll}"
        headers = {'Authorization': f'Bearer {token}'}
        try:
            docs = []
            page_token = None
            while True:
                params = {'pageSize': 200}
                if page_token:
                    params['pageToken'] = page_token
                r = requests.get(url, headers=headers, params=params, timeout=20)
                if r.status_code != 200:
                    print('Failed to list documents:', r.status_code, r.text[:300])
                    break
                data = r.json()
                docs.extend(data.get('documents', []))
                page_token = data.get('nextPageToken')
                if not page_token:
                    break
            return docs
        except Exception as e:
            print('Error listing documents:', e)
            return []
    else:
        # list across accounts not directly supported; user should pass uid when possible
        print('No uid provided: please run per-account by passing --uid to avoid scanning entire project.')
        return []


def doc_status_field(doc: dict):
    try:
        fields = doc.get('fields', {})
        s = fields.get('status', {})
        return s.get('stringValue')
    except Exception:
        return None


def update_doc_status(project: str, token: str, uid: str, doc_name: str, new_status: str) -> bool:
    url = f'https://firestore.googleapis.com/v1/{doc_name}?updateMask.fieldPaths=status'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    body = {'fields': {'status': {'stringValue': new_status}}}
    try:
        r = requests.patch(url, headers=headers, json=body, timeout=20)
        if r.status_code in (200, 201):
            return True
        else:
            print('Failed to update', doc_name, r.status_code, r.text[:300])
            return False
    except Exception as e:
        print('Error updating doc:', e)
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--uid', help='Account UID to migrate (required)', required=True)
    p.add_argument('--dry-run', action='store_true', default=True, help='List documents only')
    p.add_argument('--apply', action='store_true', help='Actually apply changes')
    args = p.parse_args()

    sa = find_service_account()
    if not sa:
        print('No service-account file found in candidates. Please place one or pass path by editing the script.')
        return
    tok = get_access_token(sa)
    if not tok:
        return
    token = tok['token']
    project = tok['project']
    print('Using project', project)

    docs = list_sms_history_docs(project, token, uid=args.uid)
    if not docs:
        print('No documents found or failed to list.')
        return

    to_update = []
    for d in docs:
        st = doc_status_field(d)
        if st == 'sent':
            to_update.append(d)

    print(f'Found {len(to_update)} documents with status=="sent" under account {args.uid}.')
    for d in to_update:
        name = d.get('name')
        fields = d.get('fields', {})
        tel = fields.get('tel', {}).get('stringValue')
        sentAt = fields.get('sentAt', {}).get('integerValue') or fields.get('sentAt', {}).get('timestampValue')
        print('-', name, 'tel=', tel, 'sentAt=', sentAt)

    if args.apply:
        print('Applying updates...')
        success = 0
        for d in to_update:
            name = d.get('name')
            uid = args.uid
            if update_doc_status(project, token, uid, name, '送信済'):
                success += 1
        print(f'Updated {success}/{len(to_update)} documents.')
    else:
        print('Dry-run mode. No changes applied.')


if __name__ == '__main__':
    main()
