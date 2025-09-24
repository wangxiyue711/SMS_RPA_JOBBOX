import imaplib
import email
import re
import time
import getpass
import sys
import os
from email.header import decode_header


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


def watch_mail(imap_host, email_user, email_pass, folder='INBOX', poll_seconds=30):
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
                        print('応募者一覧のURLを検出しました。自動でログイン処理を実行します。')
                        print('注意：ページに CAPTCHA が表示された場合は、ブラウザで手動対応してください。')
                        try:
                            from jobbox_login import JobboxLogin
                        except Exception:
                            print('自動ログイン機能は無効です：`src/jobbox_login.py` を確認してください。')
                        else:
                            try:
                                jb = JobboxLogin(parsed.get('account_name'))
                            except Exception as e:
                                print(f'アカウントの初期化に失敗しました: {e}')
                            else:
                                try:
                                    jb.login_and_goto(parsed.get('url'), parsed.get('job_title'), parsed.get('oubo_no'))
                                except Exception as e:
                                    print(f'自動ログイン中に例外が発生しました: {e}')
                                finally:
                                    try:
                                        jb.close()
                                    except Exception:
                                        pass
                else:
                    # 非求人ボックス邮件，保持未读（不 fetch full body），不标记
                    pass
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print('\n监控停止，退出')
    finally:
        try:
            conn.close()
            conn.logout()
        except Exception:
            pass


def main():
    print('インタラクティブなメール監視を開始します')
    email_user = prompt_input('監視するメールアドレスを入力してください')
    # 16桁アプリパスワード：環境変数（EMAIL_WATCHER_PASS）を優先、なければ可視入力で取得
    env_pass = os.environ.get('EMAIL_WATCHER_PASS')
    if env_pass and len(env_pass) == 16:
        email_pass = env_pass
    else:
        while True:
            try:
                # 明示的に可視入力を使用（ユーザーの要求により隠し入力をやめる）
                email_pass = input('16桁のアプリパスワードを入力してください: ').strip()
            except Exception:
                email_pass = input('16桁のアプリパスワードを入力してください: ').strip()
            if len(email_pass) == 16:
                break
            print('16桁のアプリパスワードを正しく入力してください')
    imap_host = prompt_input('IMAPサーバーを入力してください（例: imap.gmail.com）', default='imap.gmail.com')
    poll = prompt_input('间隔', default='30')
    try:
        poll_seconds = int(poll)
    except Exception:
        poll_seconds = 30
    watch_mail(imap_host, email_user, email_pass, poll_seconds=poll_seconds)


if __name__ == '__main__':
    main()
