"""
定时任务调度器
定期检查并执行到期的SMS/MAIL发送任务
"""
import os
import sys
import time
import json
import re
from datetime import datetime, timedelta

# Add parent directory to path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from src.email_watcher import (
        send_mail_once, 
        apply_template_tokens,
        normalize_phone_number,
        write_sms_history,
        _get_mail_settings,
        _find_service_account_file,
        _make_fields_for_firestore,
        get_api_settings
    )
except ImportError:
    from email_watcher import (
        send_mail_once, 
        apply_template_tokens,
        normalize_phone_number,
        write_sms_history,
        _get_mail_settings,
        _find_service_account_file,
        _make_fields_for_firestore,
        get_api_settings
    )


def send_sms_via_api(uid, to_number, message):
    """通过API发送SMS
    
    Returns: (success, info)
    """
    import requests
    
    api_cfg = get_api_settings(uid) or {}
    provider = api_cfg.get('provider', 'sms_publisher')
    base = api_cfg.get('baseUrl')
    
    if not base:
        return False, {'note': 'no base URL configured'}
    
    # Build request
    from urllib.parse import urlparse
    try:
        parsed = urlparse(base)
        if parsed.path and parsed.path != '/':
            url = base
        else:
            url = base.rstrip('/') + '/send'
    except Exception:
        url = base
    
    api_id = api_cfg.get('apiId')
    api_pass = api_cfg.get('apiPass')
    auth_type = api_cfg.get('auth')
    
    headers = {'Accept': 'application/json'}
    
    # Build form data
    safe_msg = str(message).replace('&', '＆')
    data = {
        'mobilenumber': str(to_number),
        'smstext': safe_msg,
    }
    
    if auth_type == 'params' and api_id and api_pass:
        data['username'] = api_id
        data['password'] = api_pass
    
    # Add auth headers
    if auth_type == 'basic' and api_id and api_pass:
        import base64
        credentials = f'{api_id}:{api_pass}'
        encoded = base64.b64encode(credentials.encode()).decode()
        headers['Authorization'] = f'Basic {encoded}'
    elif auth_type == 'bearer' and api_pass:
        headers['Authorization'] = f'Bearer {api_pass}'
    
    headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8'
    headers.setdefault('User-Agent', 'sms-rpa/1.0')
    
    # Check for dry run
    dry_run = os.environ.get('DRY_RUN_SMS', 'false').lower() in ('1', 'true', 'yes')
    if dry_run:
        print(f'[DRY_RUN_SMS] would send to {to_number}: {message[:50]}...')
        return True, {'note': 'dry_run', 'status_code': 200}
    
    # Send request
    try:
        r = requests.post(url, headers=headers, data=data, timeout=30)
        status_code = r.status_code
        
        if status_code == 200:
            return True, {'status_code': status_code, 'response': r.text[:200]}
        else:
            return False, {'status_code': status_code, 'error': r.text[:200]}
    except Exception as e:
        return False, {'note': str(e)}


def get_pending_tasks(uid):
    """获取待执行的定时任务
    
    Returns: list of task dicts with id and data
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        print('service-account file not found')
        return []
    
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        import requests
        
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(
            sa, scopes=['https://www.googleapis.com/auth/datastore']
        )
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        print(f'Failed to get service account token: {e}')
        return []
    
    project = sa.get('project_id')
    if not project:
        print('No project_id in service account')
        return []
    
    # Query pending tasks for this user where nextRun <= now
    now_ms = int(datetime.now().timestamp() * 1000)
    collection_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/scheduled_tasks'
    headers = {'Authorization': f'Bearer {token}'}
    
    try:
        r = requests.get(collection_url, headers=headers, timeout=10)
        if r.status_code != 200:
            print(f'Failed to get scheduled tasks: {r.status_code}')
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
            
            # Only process pending tasks that are due
            if status == 'pending' and next_run <= now_ms:
                task_data = {
                    'id': doc_id,
                    'uid': fields.get('uid', {}).get('stringValue', ''),
                    'taskType': task_type,
                    'status': status,
                    'scheduledTime': fields.get('scheduledTime', {}).get('stringValue', ''),
                    'nextRun': next_run,
                    'to': fields.get('to', {}).get('stringValue', ''),
                    'template': fields.get('template', {}).get('stringValue', ''),
                    'segmentId': fields.get('segmentId', {}).get('stringValue', ''),
                    'ouboNo': fields.get('ouboNo', {}).get('stringValue', ''),
                }
                
                # Extract applicantDetail (nested map)
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
        print(f'Error getting pending tasks: {e}')
        return []


def update_task_status(uid, task_id, status, error_msg=None):
    """更新任务状态
    
    Args:
        uid: User ID
        task_id: Task document ID
        status: 'completed', 'failed', or 'pending'
        error_msg: Error message if failed
    """
    sa_file = _find_service_account_file()
    if not sa_file:
        return False
    
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        import requests
        
        with open(sa_file, 'r', encoding='utf-8') as f:
            sa = json.load(f)
        creds = service_account.Credentials.from_service_account_info(
            sa, scopes=['https://www.googleapis.com/auth/datastore']
        )
        creds.refresh(Request())
        token = creds.token
    except Exception as e:
        print(f'Failed to get service account token: {e}')
        return False
    
    project = sa.get('project_id')
    if not project:
        return False
    
    doc_url = f'https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/accounts/{uid}/scheduled_tasks/{task_id}'
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    # Prepare update data
    update_data = {
        'status': {'stringValue': status},
        'updatedAt': {'integerValue': str(int(datetime.now().timestamp() * 1000))}
    }
    
    if status == 'completed':
        update_data['completedAt'] = {'integerValue': str(int(datetime.now().timestamp() * 1000))}
    elif status == 'failed' and error_msg:
        update_data['errorMsg'] = {'stringValue': str(error_msg)}
    
    try:
        # Use PATCH to update specific fields
        params = {'updateMask.fieldPaths': ','.join(update_data.keys())}
        r = requests.patch(
            doc_url,
            headers=headers,
            params=params,
            json={'fields': update_data},
            timeout=10
        )
        if r.status_code not in (200, 204):
            print(f'Failed to update task status: {r.status_code} {r.text}')
            return False
        return True
    except Exception as e:
        print(f'Error updating task status: {e}')
        return False


def execute_sms_task(task):
    """执行SMS发送任务"""
    uid = task.get('uid', '')
    to_number = task.get('to', '')
    template = task.get('template', '')
    applicant_detail = task.get('applicantDetail', {})
    oubo_no = task.get('ouboNo', '')
    
    print(f'执行SMS任务: to={to_number}')
    
    # Normalize phone number
    norm, ok, reason = normalize_phone_number(to_number)
    if not ok:
        print(f'電話番号の検証に失敗: {to_number} -> {reason}')
        return False, f'invalid phone: {reason}'
    
    # Apply template tokens
    try:
        message = apply_template_tokens(template, applicant_detail)
    except Exception:
        message = template
    
    # Send SMS
    success, info = send_sms_via_api(uid, norm, message)
    
    # Write to history
    if uid:
        try:
            rec = {
                'name': applicant_detail.get('applicant_name', ''),
                'gender': applicant_detail.get('gender', ''),
                'birth': applicant_detail.get('birth', ''),
                'email': applicant_detail.get('email', ''),
                'tel': norm,
                'addr': applicant_detail.get('addr', ''),
                'school': applicant_detail.get('school', ''),
                'oubo_no': oubo_no,
                'status': '送信済（S）' if success else '送信失敗（S）',
                'template': 'scheduled',
                'response': info if isinstance(info, dict) else {'note': str(info)},
                'sentAt': int(time.time())
            }
            write_sms_history(uid, rec)
        except Exception as e:
            print(f'Failed to write SMS history: {e}')
    
    if success:
        print(f'SMS送信成功: {norm}')
        return True, None
    else:
        error_msg = str(info) if info else 'unknown error'
        print(f'SMS送信失敗: {error_msg}')
        return False, error_msg


def execute_mail_task(task):
    """执行MAIL发送任务"""
    uid = task.get('uid', '')
    to_email = task.get('to', '')
    template = task.get('template', '')
    subject_template = task.get('subject', '')
    applicant_detail = task.get('applicantDetail', {})
    oubo_no = task.get('ouboNo', '')
    
    print(f'执行MAIL任务: to={to_email}')
    
    if not to_email:
        return False, 'no recipient email'
    
    # Get mail settings
    mail_cfg = _get_mail_settings(uid)
    sender = mail_cfg.get('replyEmail') or mail_cfg.get('email', '')
    sender_pass = mail_cfg.get('replyAppPass') or mail_cfg.get('appPass', '')
    
    if not sender or not sender_pass:
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
    
    # Write to history
    if uid:
        try:
            rec = {
                'name': applicant_detail.get('applicant_name', ''),
                'gender': applicant_detail.get('gender', ''),
                'birth': applicant_detail.get('birth', ''),
                'email': to_email,
                'tel': applicant_detail.get('tel', ''),
                'addr': applicant_detail.get('addr', ''),
                'school': applicant_detail.get('school', ''),
                'oubo_no': oubo_no,
                'status': '送信済（M）' if success else '送信失敗（M）',
                'template': 'scheduled',
                'response': info if isinstance(info, dict) else {'note': str(info)},
                'sentAt': int(time.time())
            }
            write_sms_history(uid, rec)
        except Exception as e:
            print(f'Failed to write MAIL history: {e}')
    
    if success:
        print(f'MAIL送信成功: {to_email}')
        return True, None
    else:
        error_msg = str(info) if info else 'unknown error'
        print(f'MAIL送信失敗: {error_msg}')
        return False, error_msg


def process_scheduled_tasks(uid):
    """处理用户的所有待执行定时任务"""
    print(f'检查用户 {uid} 的定时任务...')
    
    tasks = get_pending_tasks(uid)
    if not tasks:
        print('没有待执行的任务')
        return
    
    print(f'找到 {len(tasks)} 个待执行任务')
    
    for task in tasks:
        task_id = task.get('id')
        task_type = task.get('taskType')
        
        print(f'\n处理任务 {task_id} (类型: {task_type})')
        
        success = False
        error_msg = None
        
        if task_type == 'sms':
            success, error_msg = execute_sms_task(task)
        elif task_type == 'mail':
            success, error_msg = execute_mail_task(task)
        else:
            print(f'未知任务类型: {task_type}')
            error_msg = f'unknown task type: {task_type}'
        
        # Update task status
        if success:
            update_task_status(uid, task_id, 'completed')
            print(f'任务 {task_id} 执行成功')
        else:
            update_task_status(uid, task_id, 'failed', error_msg)
            print(f'任务 {task_id} 执行失敗: {error_msg}')


def main():
    """主函数: 定期检查所有用户的定时任务"""
    # Get UID from command line or environment
    uid = None
    if len(sys.argv) > 1:
        uid = sys.argv[1]
    else:
        uid = os.environ.get('UID')
    
    if not uid:
        print('Usage: python scheduled_dispatcher.py <UID>')
        print('Or set UID environment variable')
        sys.exit(1)
    
    print(f'定时任务调度器启动 (UID: {uid})')
    print('每分钟检查一次待执行任务...')
    
    # Main loop: check every minute
    while True:
        try:
            process_scheduled_tasks(uid)
        except KeyboardInterrupt: 
            print('\n停止定时任务调度器')
            break
        except Exception as e:
            print(f'执行任务时发生错误: {e}')
        
        # Wait 1 minute before next check
        print('\n等待下一次检查...')
        time.sleep(60)
 

if __name__ == '__main__':
    main()
