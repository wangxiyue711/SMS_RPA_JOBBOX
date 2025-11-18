#!/usr/bin/env python3
"""
Debug script to check Firestore history collections
"""
import os
import json
import requests
import time
from datetime import datetime

def check_firestore_history(uid):
    """Check both sms_history and mail_history collections"""
    
    # Find service account file
    sa_candidates = [
        os.path.join(os.getcwd(), 'service-account'),
        os.path.join(os.path.dirname(__file__), 'service-account'),
        os.path.join(os.getcwd(), 'src', 'service-account'),
    ]
    sa_file = None
    for c in sa_candidates:
        if os.path.isfile(c):
            sa_file = c
            break
    
    if not sa_file:
        print("Service account file not found!")
        return
    
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
        project = sa.get('project_id')
        
        if not project:
            print("No project_id in service account")
            return
        
        # Get today's timestamp range
        today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        now = int(time.time())
        
        print(f"Checking history for UID: {uid}")
        print(f"Today's range: {today_start} - {now}")
        print(f"Today's date: {datetime.fromtimestamp(today_start)} - {datetime.fromtimestamp(now)}")
        print("="*50)
        
        # Check sms_history collection
        print("Checking sms_history collection:")
        sms_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/sms_history'
        headers = {'Authorization': f'Bearer {token}'}
        
        try:
            r = requests.get(sms_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                documents = data.get('documents', [])
                print(f"Total sms_history documents: {len(documents)}")
                
                today_docs = []
                for doc in documents:
                    fields = doc.get('fields', {})
                    sent_at = fields.get('sentAt', {}).get('integerValue')
                    if sent_at and int(sent_at) >= today_start:
                        today_docs.append({
                            'id': doc['name'].split('/')[-1],
                            'sentAt': int(sent_at),
                            'status': fields.get('status', {}).get('stringValue', ''),
                            'email': fields.get('email', {}).get('stringValue', ''),
                            'name': fields.get('name', {}).get('stringValue', ''),
                        })
                
                print(f"Today's sms_history records: {len(today_docs)}")
                for doc in sorted(today_docs, key=lambda x: x['sentAt'], reverse=True):
                    dt = datetime.fromtimestamp(doc['sentAt'])
                    print(f"  - {dt}: {doc['status']} | {doc['name']} | {doc['email']}")
                    
            else:
                print(f"Failed to get sms_history: {r.status_code}")
        except Exception as e:
            print(f"Error checking sms_history: {e}")
        
        print("\n" + "="*50)
        
        # Check mail_history collection
        print("Checking mail_history collection:")
        mail_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/mail_history'
        
        try:
            r = requests.get(mail_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                documents = data.get('documents', [])
                print(f"Total mail_history documents: {len(documents)}")
                
                today_docs = []
                for doc in documents:
                    fields = doc.get('fields', {})
                    sent_at = fields.get('sentAt', {}).get('integerValue')
                    if sent_at and int(sent_at) >= today_start:
                        today_docs.append({
                            'id': doc['name'].split('/')[-1],
                            'sentAt': int(sent_at),
                            'status': fields.get('status', {}).get('stringValue', ''),
                            'email': fields.get('email', {}).get('stringValue', ''),
                            'name': fields.get('name', {}).get('stringValue', ''),
                        })
                
                print(f"Today's mail_history records: {len(today_docs)}")
                for doc in sorted(today_docs, key=lambda x: x['sentAt'], reverse=True):
                    dt = datetime.fromtimestamp(doc['sentAt'])
                    print(f"  - {dt}: {doc['status']} | {doc['name']} | {doc['email']}")
                    
            else:
                print(f"Failed to get mail_history: {r.status_code}")
        except Exception as e:
            print(f"Error checking mail_history: {e}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    uid = input("Enter UID: ").strip()
    if uid:
        check_firestore_history(uid)
    else:
        print("No UID provided")