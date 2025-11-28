"""
エンゲージ (en-gage.net) 自動ログインモジュール

このモジュールは求人ボックスと同様のRPA機能を提供します：
1. エンゲージにログイン
2. 応募者詳細ページへアクセス
3. 応募者情報（氏名、性別、年齢、連絡先など）を抽出
4. ブラウザセッションの管理

TODO: 実装が必要です
参考: src/jobbox_login.py
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as WW
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import json, time, os, re, unicodedata, datetime
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag


class EngageLogin:
    """エンゲージ自動ログインクラス
    
    使用例:
        account = {
            'account_name': '株式会社 P.P/東京本社',
            'engage_id': 'user@example.com',
            'engage_password': 'password123'
        }
        engage = EngageLogin(account)
        info = engage.login_and_goto(apply_url)
        if info and info.get('detail'):
            detail = info['detail']
            print(f"応募者名: {detail.get('name')}")
            print(f"性別: {detail.get('gender')}")
            print(f"年齢: {detail.get('age')}")
        engage.close()
    """
    
    def __init__(self, account: dict):
        """初期化
        
        Args:
            account: アカウント情報辞書
                - account_name: アカウント名（会社名）
                - engage_id: ログインID（メールアドレス）
                - engage_password: パスワード
        """
        self.account = account
        self.account_name = account.get('account_name', '')
        self.engage_id = account.get('engage_id', '')
        self.engage_password = account.get('engage_password', '')
        self.driver = None
        
        # WebDriverの初期化（エラーが発生してもクラス初期化は成功させる）
        try:
            options = webdriver.ChromeOptions()
            # ヘッドレスモードを使用する場合はコメントを外す
            # options.add_argument('--headless')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument('--log-level=3')  # Suppress DevTools listening message
            
            # print(f'[エンゲージRPA] Chromeブラウザを起動中...')
            self.driver = webdriver.Chrome(options=options)
            self.driver.implicitly_wait(10)
            # print(f'[エンゲージRPA] ✓ ブラウザ起動成功（アカウント: {self.account_name}）')
        except Exception as e:
            print(f'ブラウザ起動エラー: {e}')
            print('ChromeDriverが正しくインストールされているか確認してください。')
            raise  # 重新抛出异常，让上层捕获
    
    def _wait(self, cond, timeout=20):
        """WebDriverWaitのヘルパー"""
        if not self.driver:
            raise RuntimeError("Driver is not initialized")
        return WW(self.driver, timeout).until(cond)
    
    def _wait_css(self, css, timeout=20, clickable=False, visible=True):
        """CSS Selectorで要素を待機"""
        if not self.driver:
            raise RuntimeError("Driver is not initialized")
        by = (By.CSS_SELECTOR, css)
        if clickable:
            return self._wait(EC.element_to_be_clickable(by), timeout)
        if visible:
            return self._wait(EC.visibility_of_element_located(by), timeout)
        return self._wait(EC.presence_of_element_located(by), timeout)
    
    def _wait_xpath(self, xp, timeout=20, clickable=False, visible=True):
        """XPathで要素を待機"""
        if not self.driver:
            raise RuntimeError("Driver is not initialized")
        by = (By.XPATH, xp)
        if clickable:
            return self._wait(EC.element_to_be_clickable(by), timeout)
        if visible:
            return self._wait(EC.visibility_of_element_located(by), timeout)
        return self._wait(EC.presence_of_element_located(by), timeout)
    
    def _norm(self, s: str) -> str:
        """文字列の正規化（全角半角統一、空白除去）"""
        if not s:
            return ''
        s = unicodedata.normalize('NFKC', s)
        return re.sub(r'\s+', '', s)
    
    def login_and_goto(self, apply_url: str, email_job_title: str = '') -> Optional[dict]:
        """エンゲージにログインして応募者詳細ページにアクセス
        
        Args:
            apply_url: 応募者詳細ページのURL
            email_job_title: メールから取得した職種名（省略可）
        """
        try:
            if not self.driver:
                return None
                
            # print(f'[エンゲージRPA] 応募ページにアクセスします: {apply_url}')
            
            # 1. 応募URLにアクセス（未ログインの場合はログインページにリダイレクトされる）
            self.driver.get(apply_url)
            time.sleep(2)
            
            # 2. ログインが必要かチェック
            current_url = self.driver.current_url.lower()
            if 'login' in current_url or 'auth' in current_url:
                # print('[エンゲージRPA] ログインが必要です。ログイン処理を開始します...')
                
                # メールアドレス入力欄を探す
                try:
                    # 複数のセレクタを試す
                    email_field = None
                    email_selectors = [
                        'input[type="email"]',
                        'input[type="text"][placeholder*="メールアドレス"]',
                        'input[name="email"]',
                        'input[id*="email"]',
                        'input[placeholder*="メール"]'
                    ]
                    
                    for selector in email_selectors:
                        try:
                            email_field = self._wait_css(selector, timeout=5, visible=True)
                            if email_field:
                                # print(f'[エンゲージRPA] メール入力欄を検出: {selector}')
                                break
                        except TimeoutException:
                            continue
                    
                    if not email_field:
                        print('ログイン: メールアドレス入力欄が見つかりません')
                        return None
                    
                    # メールアドレスを入力
                    email_field.clear()
                    email_field.send_keys(self.engage_id)
                    # print(f'[エンゲージRPA] メールアドレスを入力しました: {self.engage_id}')
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f'メールアドレス入力エラー: {e}')
                    return None
                
                # パスワード入力欄を探す
                try:
                    password_field = None
                    password_selectors = [
                        'input[type="password"]',
                        'input[name="password"]',
                        'input[id*="password"]',
                        'input[placeholder*="パスワード"]'
                    ]
                    
                    for selector in password_selectors:
                        try:
                            password_field = self._wait_css(selector, timeout=5, visible=True)
                            if password_field:
                                # print(f'[エンゲージRPA] パスワード入力欄を検出: {selector}')
                                break
                        except TimeoutException:
                            continue
                    
                    if not password_field:
                        print('ログイン: パスワード入力欄が見つかりません')
                        return None
                    
                    # パスワードを入力
                    password_field.clear()
                    password_field.send_keys(self.engage_password)
                    # print('[エンゲージRPA] パスワードを入力しました')
                    time.sleep(0.5)
                    
                except Exception as e:
                    print(f'パスワード入力エラー: {e}')
                    return None
                
                # ログインボタンをクリック
                try:
                    login_button = None
                    login_selectors = [
                        'button[type="submit"]',
                        'button:contains("ログイン")',
                        'input[type="submit"]',
                        'button.login',
                        'a.login-button'
                    ]
                    
                    # XPathも試す
                    login_xpaths = [
                        "//button[contains(text(), 'ログイン')]",
                        "//button[contains(., 'ログイン')]",
                        "//input[@type='submit' and contains(@value, 'ログイン')]",
                        "//a[contains(text(), 'ログイン')]"
                    ]
                    
                    for selector in login_selectors:
                        try:
                            login_button = self._wait_css(selector, timeout=3, clickable=True)
                            if login_button:
                                # print(f'[エンゲージRPA] ログインボタンを検出(CSS): {selector}')
                                break
                        except TimeoutException:
                            continue
                    
                    if not login_button:
                        for xpath in login_xpaths:
                            try:
                                login_button = self._wait_xpath(xpath, timeout=3, clickable=True)
                                if login_button:
                                    # print(f'[エンゲージRPA] ログインボタンを検出(XPath): {xpath}')
                                    break
                            except TimeoutException:
                                continue
                    
                    if not login_button:
                        print('ログイン: ログインボタンが見つかりません')
                        return None
                    
                    # ボタンをクリック
                    login_button.click()
                    # print('[エンゲージRPA] ログインボタンをクリックしました')
                    time.sleep(3)
                    
                    # ログイン成功を確認
                    if 'login' not in self.driver.current_url.lower():
                        pass # print('[エンゲージRPA] ✅ ログインに成功しました')
                    else:
                        print('⚠️  ログイン後もログインページにいます。認証情報を確認してください。')
                        return None
                    
                except Exception as e:
                    print(f'ログインボタンクリックエラー: {e}')
                    return None
                
                # ログイン後、元のURLに再度アクセス
                if apply_url not in self.driver.current_url:
                    # print(f'[エンゲージRPA] 応募ページに移動します: {apply_url}')
                    self.driver.get(apply_url)
                    time.sleep(2)
            
            else:
                pass # print('[エンゲージRPA] すでにログイン済みです')
            
            # 3. ページ状態を判断して適切な処理を実行
            # print('[エンゲージRPA] ページ状態を確認中...')
            page_state = self._detect_page_state()
            # print(f'[エンゲージRPA] 検出されたページ状態: {page_state}')
            
            # 状態に応じた処理
            if page_state == 'profile_tabs':
                # 情況1: 【メッセージ】/【プロフィール】タブがある主従ページ
                # → 【プロフィール】タブをクリック
                # print('[エンゲージRPA] 情況1: プロフィールタブページを検出')
                # print('[エンゲージRPA] 【プロフィール】タブをクリックします...')
                if not self._click_profile_tab():
                    print('❌ プロフィールタブのクリックに失敗しました')
                    return None
                # print('[エンゲージRPA] ✓ プロフィールタブに切り替えました')
                time.sleep(2)
            elif page_state == 'new_application':
                # 情況2: 新着状態（【選考へ進める】ボタンがある）
                # print('[エンゲージRPA] 情況2: 新着応募ページを検出')
                
                # ページが完全に読み込まれるまで待機
                # print('[エンゲージRPA] ページの読み込みを待機中...')
                time.sleep(3)
                
                # ページのHTMLを確認（デバッグ用）
                # try:
                #     page_text = self.driver.page_source
                #     if '選考へ進める' in page_text:
                #         print('[エンゲージRPA] ✓ ページ内に「選考へ進める」テキストを確認')
                #     else:
                #         print('[エンゲージRPA] ⚠️ ページ内に「選考へ進める」テキストが見つかりません')
                #         # ページの主要なボタンテキストを表示
                #         from bs4 import BeautifulSoup
                #         soup = BeautifulSoup(page_text, 'html.parser')
                #         buttons = soup.find_all(['button', 'a'], limit=10)
                #         print(f'[エンゲージRPA] ページ内のボタン（最大10個）:')
                #         for btn in buttons:
                #             btn_text = btn.get_text(strip=True)
                #             if btn_text:
                #                 print(f'  - "{btn_text[:50]}"')
                # except Exception as e:
                #     print(f'[エンゲージRPA] ページ確認エラー: {e}')
                
                # print('[エンゲージRPA] 【選考へ進める】ボタンをクリックします...')
                button_clicked = self._click_proceed_button()
                
                if button_clicked:
                    pass # print('[エンゲージRPA] ✓ 【選考へ進める】ボタンをクリックしました')
                    # ボタンクリック後、ページ遷移を待つ
                    time.sleep(3)
                else:
                    pass # print('[エンゲージRPA] ⚠️ 【選考へ進める】ボタンが見つかりませんでした')
                
                # 元のURLで再度アクセスして第一種情況に移行
                # print(f'[エンゲージRPA] 元のURLで再度アクセスします...')
                self.driver.get(apply_url)
                time.sleep(3)
                
                # 再度ページ状態を確認（第一種情況になっているはず）
                page_state_after = self._detect_page_state()
                # print(f'[エンゲージRPA] リフレッシュ後のページ状態: {page_state_after}')
                
                if page_state_after == 'profile_tabs':
                    # 第一種情況に移行したので、プロフィールタブをクリック
                    if not self._click_profile_tab():
                        print('❌ プロフィールタブのクリックに失敗しました')
                        return None
                    # print('[エンゲージRPA] ✓ プロフィールタブに切り替えました')
                    time.sleep(2)
                else:
                    print('⚠️  リフレッシュ後も想定外のページ状態です')
            else:
                print('⚠️  不明なページ状態です')
            
            # 4. 応募者情報を抽出
            # print('[エンゲージRPA] 応募者情報を抽出します...')
            detail = self._extract_applicant_detail()
            
            if not detail:
                print('❌ 応募者情報の抽出に失敗しました')
                return None
            
            # 4. 求人タイトルを抽出（メールから取得した職種名を優先）
            job_title = email_job_title if email_job_title else self._extract_job_title()
            
            # Jobboxスタイルで出力
            print("\n=== 応募者情报 ===")
            print(f"氏名: {detail.get('name', '')}")
            if detail.get('furigana'):
                print(f"フリガナ: {detail.get('furigana', '')}")
            print(f"性別: {detail.get('gender', '')}")
            print(f"生年月日: {detail.get('birth', '')}")
            print(f"メールアドレス: {detail.get('email', '')}")
            print(f"電話番号: {detail.get('tel', '')}")
            print(f"住所: {detail.get('addr', '')}")
            print(f"学校名: {detail.get('school', '')}")
            # エンゲージには応募日時や応募Noが画面上にない場合が多いが、あれば表示
            if detail.get('oubo_no'):
                print(f"応募No.: {detail.get('oubo_no', '')}")
            print(f"応募求人: {job_title}")
            print("==================\n")
            
            return {
                'detail': detail,
                'title': job_title,
                'url': apply_url
            }
            
        except Exception as e:
            print(f'❌ エラーが発生しました: {e}')
            import traceback
            traceback.print_exc()
            return None
    
    def _detect_page_state(self) -> str:
        """ページの状態を検出
        
        Returns:
            'profile_tabs': 【メッセージ】/【プロフィール】タブがある主従ページ（情況1）
            'new_application': 新着応募ページ（【選考へ進める】ボタンがある）（情況2）
            'unknown': 不明な状態
        """
        if not self.driver:
            return 'unknown'
        try:
            # 重要: 情況2を先に判定（より具体的な条件）
            # 情況2の判定: 【選考へ進める】ボタンの存在をチェック
            proceed_button_selectors = [
                "//button[contains(text(), '選考へ進める')]",
                "//a[contains(text(), '選考へ進める')]",
                "//*[contains(@class, 'proceed') and contains(text(), '進める')]",
                "//button[contains(., '選考') and contains(., '進める')]"
            ]
            
            # print('[エンゲージRPA] 情況2（選考へ進める）を確認中...')
            for selector in proceed_button_selectors:
                try:
                    elem = self.driver.find_element(By.XPATH, selector)
                    if elem and elem.is_displayed():
                        # print(f'[エンゲージRPA] ✓ 【選考へ進める】ボタンを検出: {selector}')
                        return 'new_application'
                except:
                    continue
            # print('[エンゲージRPA] 【選考へ進める】ボタンは見つかりませんでした')
            
            # 情況1の判定: 【プロフィール】タブの存在をチェック
            profile_tab_selectors = [
                "//a[contains(text(), 'プロフィール')]",
                "//button[contains(text(), 'プロフィール')]",
                "//li[contains(text(), 'プロフィール')]",
                "//*[@role='tab' and contains(text(), 'プロフィール')]",
                "//a[contains(@href, 'profile')]"
            ]
            
            # print('[エンゲージRPA] 情況1（プロフィールタブ）を確認中...')
            for selector in profile_tab_selectors:
                try:
                    elem = self.driver.find_element(By.XPATH, selector)
                    if elem and elem.is_displayed():
                        # print(f'[エンゲージRPA] ✓ プロフィールタブを検出: {selector}')
                        return 'profile_tabs'
                except:
                    continue
            # print('[エンゲージRPA] プロフィールタブも見つかりませんでした')
            
            # print('[エンゲージRPA] ⚠️  既知のページ状態を検出できませんでした')
            return 'unknown'
            
        except Exception as e:
            print(f'[エンゲージRPA] ページ状態検出エラー: {e}')
            return 'unknown'
    
    def _click_profile_tab(self) -> bool:
        """【プロフィール】タブをクリック（情況1）"""
        try:
            # 複数のセレクタを試行
            profile_tab_selectors = [
                "//a[contains(text(), 'プロフィール')]",
                "//button[contains(text(), 'プロフィール')]",
                "//li[contains(text(), 'プロフィール')]//a",
                "//*[@role='tab' and contains(text(), 'プロフィール')]",
                "//a[contains(@href, 'profile')]",
                "//div[contains(@class, 'tab')]//a[contains(text(), 'プロフィール')]"
            ]
            
            for selector in profile_tab_selectors:
                try:
                    # print(f'[エンゲージRPA] タブクリック試行: {selector}')
                    elem = self._wait_xpath(selector, timeout=5, clickable=True)
                    if elem:
                        elem.click()
                        # print(f'[エンゲージRPA] ✓ プロフィールタブをクリックしました')
                        return True
                except TimeoutException:
                    continue
                except Exception as e:
                    # print(f'[エンゲージRPA] クリック試行エラー: {e}')
                    continue
            
            # すべての試行が失敗
            # print('プロフィールタブが見つかりません')
            return False
            
        except Exception as e:
            # print(f'プロフィールタブクリックエラー: {e}')
            return False
    
    def _click_proceed_button(self) -> bool:
        """【選考へ進める】ボタンをクリック（情況2）"""
        try:
            # 複数のセレクタを試行（XPathとCSSセレクタの両方）
            proceed_button_selectors = [
                # XPath - テキストベース
                ("xpath", "//button[contains(text(), '選考へ進める')]"),
                ("xpath", "//a[contains(text(), '選考へ進める')]"),
                ("xpath", "//button[contains(., '選考へ進める')]"),
                ("xpath", "//*[contains(text(), '選考') and contains(text(), '進める')]"),
                # CSS - クラスベース
                ("css", "button[class*='proceed']"),
                ("css", "a[class*='proceed']"),
                ("css", "button[class*='selection']"),
                ("css", "button[class*='advance']"),
            ]
            
            for selector_type, selector in proceed_button_selectors:
                try:
                    print(f'[エンゲージRPA]   試行中: {selector_type} -> {selector[:50]}...')
                    if selector_type == "xpath":
                        elem = self._wait_xpath(selector, timeout=5, clickable=True)
                    else:
                        elem = self._wait_css(selector, timeout=5, clickable=True)
                    
                    if elem and elem.is_displayed():
                        # ボタンのテキストを確認
                        button_text = elem.text.strip()
                        print(f'[エンゲージRPA]   ✓ ボタン検出: "{button_text}"')
                        
                        # JavaScriptクリックも試行（通常クリックが失敗する場合がある）
                        try:
                            elem.click()
                        except Exception:
                            # JavaScriptでクリック
                            if self.driver:
                                self.driver.execute_script("arguments[0].click();", elem)
                        
                        print(f'[エンゲージRPA]   ✓ クリック成功')
                        return True
                        
                except TimeoutException:
                    continue
                except Exception as e:
                    print(f'[エンゲージRPA]   ✗ エラー: {str(e)[:100]}')
                    continue
            
            print('[エンゲージRPA]   ✗ すべてのセレクタで失敗')
            return False
            
        except Exception as e:
            print(f'[エンゲージRPA] ボタンクリック例外: {e}')
            return False
    
    def _extract_applicant_detail(self) -> Optional[dict]:
        """応募者詳細情報を抽出（プロフィールページから）"""
        if not self.driver:
            return None
            
        detail = {}
        
        try:
            # print('[エンゲージRPA] プロフィール情報を取得中...')
            
            # 高速化のため、BeautifulSoupで一括解析する
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            # ヘルパー関数: BS4を使ったフィールド抽出
            def get_text_bs4(soup, keywords):
                if isinstance(keywords, str):
                    keywords = [keywords]
                regexes = [re.compile(kw) for kw in keywords]
                
                # Priority 1: dt/dd pairs (most reliable structure)
                for dt in soup.find_all('dt'):
                    label_text = dt.get_text(' ', strip=True)
                    if any(r.search(label_text) for r in regexes):
                        dd = dt.find_next_sibling('dd')
                        if dd:
                            txt = dd.get_text(' ', strip=True)
                            if txt and len(txt) < 200 and not any(skip in txt for skip in ['求人を選択', '選択してください', 'IDで検索', 'プロフィール', 'メッセージ']):
                                return txt
                
                # Priority 2: th/td pairs
                for th in soup.find_all('th'):
                    label_text = th.get_text(' ', strip=True)
                    if any(r.search(label_text) for r in regexes):
                        td = th.find_next_sibling('td')
                        if td:
                            txt = td.get_text(' ', strip=True)
                            if txt and len(txt) < 200 and not any(skip in txt for skip in ['求人を選択', '選択してください', 'IDで検索', 'プロフィール', 'メッセージ']):
                                return txt
                
                # Priority 3: label elements (within .list or similar containers)
                for label in soup.find_all(['label', 'div'], class_=re.compile(r'label', re.I)):
                    label_text = label.get_text(' ', strip=True)
                    if any(r.search(label_text) for r in regexes):
                        # Look for adjacent .data or similar
                        parent = label.parent
                        if parent:
                            data_elem = parent.find(['div', 'span'], class_=re.compile(r'data', re.I))
                            if data_elem:
                                txt = data_elem.get_text(' ', strip=True)
                                if txt and len(txt) < 200 and not any(skip in txt for skip in ['求人を選択', '選択してください', 'IDで検索', 'プロフィール', 'メッセージ']):
                                    return txt
                
                # Priority 4: label: value in same element
                for tag in soup.find_all(['div', 'span', 'p']):
                    full_text = tag.get_text(' ', strip=True)
                    if any(r.search(full_text) for r in regexes):
                        parts = re.split(r'[：:]', full_text, maxsplit=1)
                        if len(parts) == 2 and len(parts[1].strip()) < 100:
                            txt = parts[1].strip()
                            if not any(skip in txt for skip in ['求人を選択', '選択してください', 'IDで検索']):
                                return txt

                return None

            def sanitize_name(text: str) -> str:
                if not text:
                    return ''
                txt = text.strip()
                # remove anything inside parentheses (age/gender/location)
                txt = re.split(r'[（(]', txt)[0].strip()
                # remove age pattern (e.g., "26 歳", "26歳")
                txt = re.sub(r'\d+\s*歳', '', txt).strip()
                parts = re.split(r'[\s　]+', txt)
                clean_parts = []
                for p in parts:
                    if not p:
                        continue
                    # skip if it's just a number (age)
                    if p.isdigit():
                        continue
                    if p in ['男性', '女性', 'その他']:
                        break
                    if any(p.endswith(suffix) for suffix in ['道', '府', '県', '都', '市', '区']):
                        break
                    clean_parts.append(p)
                return ' '.join(clean_parts) if clean_parts else txt

            header_used = None

            # 1. 氏名の取得
            # まずはテーブル内の「氏名」「名前」を探す
            name_text = get_text_bs4(
                soup,
                ['氏名', 'お名前', '氏名（漢字）', r'氏名\s*\(漢字\)', '氏名（カナ）']
            )
            
            # 見つからない場合、ヘッダー領域を探す
            header_name_info = None
            if not name_text:
                header_name_info = self._extract_name_from_header(soup)
                if header_name_info:
                    header_node, header_name, header_kana = header_name_info
                    if header_name and not name_text:
                        name_text = header_name
                    if header_node:
                        header_used = header_node
                    if header_kana:
                        detail['furigana'] = header_kana
            
            if name_text:
                detail['name'] = sanitize_name(name_text)
            
            # 2. フリガナ
            furigana_text = get_text_bs4(
                soup,
                ['フリガナ', 'ふりがな', 'カナ', 'かな', '氏名（カナ）', r'氏名\s*\(カナ\)']
            )
            if furigana_text:
                detail['furigana'] = furigana_text
                print(f'[DEBUG] フリガナ取得(table): {furigana_text}')
            elif not detail.get('furigana') and header_used:
                kana_from_header = self._extract_furigana_near_node(header_used)
                if kana_from_header:
                    detail['furigana'] = kana_from_header
                    print(f'[DEBUG] フリガナ取得(header_node): {kana_from_header}')
            if not detail.get('furigana') and detail.get('name'):
                kana_from_doc = self._find_furigana_in_document(soup, detail.get('name'))
                if kana_from_doc:
                    detail['furigana'] = kana_from_doc
                    print(f'[DEBUG] フリガナ取得(document): {kana_from_doc}')

            # 3. 性別
            gender_text = get_text_bs4(soup, ['性別'])
            if gender_text:
                detail['gender'] = self._normalize_gender(gender_text)
            
            # 4. 年齢・生年月日
            age_text = get_text_bs4(soup, ['年齢', '生年月日'])
            if age_text:
                detail['birth'] = age_text
                # 年齢を抽出（括弧内の数字）
                age_match = re.search(r'（(\d+)歳）', age_text)
                if age_match:
                    detail['age'] = int(age_match.group(1))
                elif '歳' in age_text:
                     m = re.search(r'(\d+)歳', age_text)
                     if m: detail['age'] = int(m.group(1))

                # 生年月日も抽出
                birth_match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', age_text)
                if birth_match:
                    detail['birth_date'] = f"{birth_match.group(1)}/{birth_match.group(2)}/{birth_match.group(3)}"
            
            # 5. 現住所
            addr_text = get_text_bs4(soup, ['現住所', '住所', '居住地'])
            if addr_text:
                detail['addr'] = addr_text
                detail['住所'] = addr_text
            
            # 6. 電話番号
            tel_text = get_text_bs4(soup, ['電話番号', '携帯電話', '連絡先'])
            if tel_text:
                detail['tel'] = tel_text
                detail['電話番号'] = tel_text
            
            # 7. メールアドレス
            email_text = get_text_bs4(soup, ['メールアドレス', 'Email', 'E-mail'])
            if email_text:
                detail['email'] = email_text
            
            # 8. 最終学歴
            school_text = get_text_bs4(soup, ['最終学歴', '学歴'])
            if school_text:
                detail['school'] = school_text
                detail['最終学歴'] = school_text
            
            # 氏名が取得できていれば成功とみなす。
            # ただし、氏名が取れなくてもメールや電話番号が取れていれば「氏名不明」として続行する
            if not detail.get('name'):
                if detail.get('email') or detail.get('tel'):
                    print('⚠️  氏名は取得できませんでしたが、連絡先があるため続行します')
                    detail['name'] = '氏名不明'
                else:
                    print('❌ 氏名も連絡先も取得できませんでした')
                    return None

            # エンゲージの記録であることを示すマーカーを追加
            detail['source'] = 'engage'
            detail['平台'] = 'エンゲージ'
            return detail
                
        except Exception as e:
            print(f'応募者情報抽出エラー: {e}')
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_job_title(self) -> str:
        """求人タイトルを抽出"""
        if not self.driver:
            return ''
        try:
            # BS4で高速化
            html = self.driver.page_source
            soup = BeautifulSoup(html, 'html.parser')
            
            # 1. Look for text pattern "【...】へ応募しました" which contains the job title
            apply_pattern = soup.find(string=re.compile(r'【[^】]+】へ応募しました'))
            if apply_pattern:
                match = re.search(r'【([^】]+)】へ応募しました', str(apply_pattern))
                if match:
                    job_title = match.group(1).strip()
                    if job_title and len(job_title) < 200:
                        return job_title
            
            # 2. テーブル内の「応募職種」「求人」を探す
            keywords = ['応募職種', '求人', '職種', '応募求人']
            for kw in keywords:
                targets = soup.find_all(['th', 'dt', 'label'], string=re.compile(kw))
                for t in targets:
                    sibling = t.find_next_sibling(['td', 'dd', 'div'])
                    if sibling:
                        txt = sibling.get_text(strip=True)
                        if txt and len(txt) < 200: return txt
            
            # 2. ヘッダーのタイトルを探す
            # h1, h2 のクラス名に 'job' が含まれるものを探す
            headers = soup.find_all(['h1', 'h2', 'div'], class_=re.compile(r'job|title', re.I))
            for h in headers:
                txt = h.get_text(strip=True)
                if txt and len(txt) > 2:
                    return txt
            
            # 3. 単純にh1を探す（ただし、管理画面のタイトルは除外）
            h1 = soup.find('h1')
            if h1:
                h1_text = h1.get_text(strip=True)
                # 管理画面のタイトルを除外
                if h1_text and '候補者管理' not in h1_text and 'エンゲージ' not in h1_text:
                    return h1_text

            # 4. パターン: 文字列内に【...】が含まれる要素
            bracket_node = soup.find(string=re.compile(r'【[^】]+】'))
            if bracket_node:
                if isinstance(bracket_node, NavigableString):
                    txt = str(bracket_node).strip()
                else:
                    txt = bracket_node.get_text(strip=True) if hasattr(bracket_node, 'get_text') else str(bracket_node).strip()
                return re.sub(r'\s+', ' ', txt)
            # 5. fallback: use detail title from header area (same as name banner)
            header_banner = soup.select_one('.profile-header, .candidate-header, .applicant-header, .c-profile__info')
            if header_banner:
                txt = header_banner.get_text(" ", strip=True)
                if txt:
                    m = re.search(r'【[^】]+】[^\n]+', txt)
                    if m:
                        return re.sub(r'\s+', ' ', m.group(0))
            # 6. fallback to candidate listing card section title
            listing_card = soup.select_one('.applicant-card__title, .candidate-card__title, .applicant-info__job')
            if listing_card:
                txt = listing_card.get_text(" ", strip=True)
                if txt:
                    return txt
                
        except Exception:
            pass
        return ''

    def _extract_name_from_header(self, soup) -> Optional[Tuple[Optional[Tag], Optional[str], Optional[str]]]:
        """Attempt to pull applicant name and kana from the avatar/header region."""
        if not soup:
            return None

        # 1. Try specific structure from screenshot: .txtSet > .name / .kana
        txt_set = soup.select_one('.txtSet')
        if txt_set:
            name_node = txt_set.select_one('.name')
            kana_node = txt_set.select_one('.kana')
            
            if name_node:
                raw_name = name_node.get_text(" ", strip=True)
                # Remove quotes if present (screenshot shows "山田 太郎 ")
                raw_name = raw_name.replace('"', '').replace("'", "").strip()
                
                kana_text = None
                if kana_node:
                    kana_text = kana_node.get_text(" ", strip=True)
                
                if self._looks_like_candidate_name(raw_name):
                    return name_node, raw_name, kana_text

        header_selectors = [
            '.c-profile__head', '.c-profile__info', '.profile-header', '.profile__header', '.profile-head',
            '.profileSummary', '.candidate-header', '.candidateProfileHeader', '.applicant-header',
            '.applicant-profile__head', '.applicant-card__header', '.applicant-card__head', '.c-applicant__head',
            '.detail-header', '.profile-main__head', '.profileMainHeader'
        ]

        checked_nodes = set()
        for selector in header_selectors:
            headers = soup.select(selector)
            for header in headers:
                if not isinstance(header, Tag):
                    continue
                if id(header) in checked_nodes:
                    continue
                checked_nodes.add(id(header))

                name_nodes = header.select('[class*="name" i]')
                if not name_nodes:
                    name_nodes = header.find_all(['h1', 'h2', 'h3', 'strong'])
                if not name_nodes:
                    name_nodes = header.find_all(['p', 'span'], limit=4)

                for node in name_nodes:
                    if not isinstance(node, Tag):
                        continue
                    raw_text = node.get_text(" ", strip=True)
                    if not raw_text:
                        continue
                    candidate_text = re.sub(r'\s+', ' ', raw_text)
                    if not self._looks_like_candidate_name(candidate_text):
                        continue
                    kana = self._extract_furigana_near_node(node)
                    return node, candidate_text.strip(), kana

        return None

    def _extract_furigana_near_node(self, node) -> Optional[str]:
        """Attempt to extract furigana text located near the provided header node."""
        if not node:
            return None

        # 1. rubyタグ内のrt
        candidate_list = []
        if isinstance(node, Tag):
            candidate_list.append(node)
        parent = getattr(node, 'parent', None)
        if isinstance(parent, Tag):
            candidate_list.append(parent)
        for candidate in candidate_list:
            ruby = candidate.find('ruby')
            if ruby and isinstance(ruby, Tag):
                rt = ruby.find('rt')
                if rt:
                    txt = rt.get_text(strip=True)
                    if txt:
                        return txt

        # 2. 直前の兄弟要素にカナがあればそれを採用
        prev = getattr(node, 'previous_sibling', None)
        while prev:
            if isinstance(prev, NavigableString):
                txt = str(prev).strip()
            elif isinstance(prev, Tag):
                txt = prev.get_text(strip=True)
            else:
                txt = ''
            if self._looks_like_kana(txt):
                return txt
            prev = getattr(prev, 'previous_sibling', None)

        # 3. 親要素の中で kana/furi が含まれるクラス名を探す
        parent = getattr(node, 'parent', None)
        if isinstance(parent, Tag):
            candidates = parent.find_all(['span', 'div', 'p'], class_=re.compile(r'(kana|ruby|furi)', re.I))
            for cand in candidates:
                txt = cand.get_text(strip=True)
                if self._looks_like_kana(txt):
                    return txt

        # 4. 最後の手段: 直近のテキストノードからカナパターンを抽出
        if isinstance(parent, Tag):
            for cand in parent.stripped_strings:
                if self._looks_like_kana(cand):
                    return cand

        return None

    def _find_furigana_in_document(self, soup, name_text: Optional[str]) -> Optional[str]:
        """Fallback: search entire document for kana string located immediately before the name."""
        if not soup or not name_text:
            return None
        target_norm = self._norm(re.split(r'[（(]', name_text)[0])
        if not target_norm:
            return None
        strings = list(soup.stripped_strings)
        for idx, raw in enumerate(strings):
            raw_text = str(raw).strip()
            if not raw_text:
                continue
            candidate_norm = self._norm(re.split(r'[（(]', raw_text)[0])
            if not candidate_norm:
                continue
            if candidate_norm == target_norm or target_norm in candidate_norm or candidate_norm in target_norm:
                for back in range(idx - 1, max(-1, idx - 6), -1):
                    prev_text = str(strings[back]).strip()
                    if self._looks_like_kana(prev_text):
                        return prev_text
        return None

    def _looks_like_kana(self, text: Optional[str]) -> bool:
        if not text:
            return False
        return bool(re.fullmatch(r'[\u30A0-\u30FF\u3040-\u309Fー・\s]+', text.strip()))

    def _looks_like_candidate_name(self, text: Optional[str]) -> bool:
        if not text:
            return False
        cleaned = text.strip()
        if len(cleaned) < 2 or len(cleaned) > 30:
            return False
        banned_keywords = ['エンゲージ', 'プレミアム', '候補者管理', '応募', '求人', 'メッセージ', 'プロフィール']
        if any(word in cleaned for word in banned_keywords):
            return False
        if '【' in cleaned and '】' in cleaned:
            return False
        if '@' in cleaned or 'http' in cleaned:
            return False
        return True
    
    def _calc_age_from_birth(self, birth_str: str) -> Optional[int]:
        """生年月日から年齢を計算
        
        対応フォーマット:
        - "1999年11月12日 (26歳)" - エンゲージの形式
        - "1999年11月12日"
        - "1999-11-12" / "1999/11/12"
        - "26歳"
        """
        if not birth_str:
            return None
        
        try:
            s = str(birth_str).strip()
            
            # まず括弧内の年齢を直接抽出を試みる (例: "1999年11月12日 (26歳)")
            m_age = re.search(r'\((\d{1,3})\s*歳\)', s)
            if m_age:
                return int(m_age.group(1))
            
            # YYYY年MM月DD日 形式
            m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
            if m:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                birth = datetime.datetime(y, mo, d)
                today = datetime.datetime.now()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
                return age
            
            # YYYY-MM-DD または YYYY/MM/DD 形式
            m2 = re.search(r"(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})", s)
            if m2:
                y, mo, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
                birth = datetime.datetime(y, mo, d)
                today = datetime.datetime.now()
                age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
                return age
            
            # 年齢が直接書いてある場合 (例: "26歳" または "26")
            m3 = re.search(r"(\d{1,3})\s*歳", s)
            if m3:
                return int(m3.group(1))
            
        except Exception:
            pass
        
        return None
    
    def _extract_profile_field(self, field_name: str) -> Optional[str]:
        """プロフィールページから特定のフィールド値を抽出
        
        プロフィールページの構造:
        <dt>性別</dt>
        <dd>その他</dd>
        
        Args:
            field_name: フィールド名（例: "性別", "年齢", "電話番号"）
        
        Returns:
            フィールドの値、見つからない場合はNone
        """
        if not self.driver:
            return None
        try:
            # 複数のパターンを試行
            patterns = [
                # パターン1: dt/dd構造
                f"//dt[contains(text(), '{field_name}')]/following-sibling::dd[1]",
                # パターン2: th/td構造
                f"//th[contains(text(), '{field_name}')]/following-sibling::td[1]",
                # パターン3: divベース
                f"//div[contains(text(), '{field_name}')]/following-sibling::div[1]",
                # パターン4: labelベース
                f"//label[contains(text(), '{field_name}')]/following-sibling::*[1]",
            ]
            
            for pattern in patterns:
                try:
                    elem = self.driver.find_element(By.XPATH, pattern)
                    if elem and elem.text.strip():
                        return elem.text.strip()
                except:
                    continue
            
            return None
        except Exception as e:
            # print(f'[エンゲージRPA] {field_name}の取得エラー: {e}')
            return None
    
    def _normalize_gender(self, raw: str) -> str:
        """性別の正規化
        
        Args:
            raw: 生の性別テキスト (例: "その他", "男性", "女性")
        
        Returns:
            '男性', '女性', 'その他', または '不明'
        """
        if not raw:
            return '不明'
        s = re.sub(r"\s+", '', str(raw)).lower()
        
        # エンゲージは「その他」という選択肢がある
        if 'その他' in s or 'other' in s:
            return 'その他'
        
        if any(x in s for x in ('男性', '男')):
            return '男性'
        if any(x in s for x in ('女性', '女')):
            return '女性'
        
        # 英語の略語にも対応
        if s in ('male', 'm', 'man'):
            return '男性'
        if s in ('female', 'f', 'woman'):
            return '女性'
        
        return '不明'
    
    def close(self):
        """ブラウザを閉じる（エラーでも続行）"""
        try:
            if hasattr(self, 'driver') and self.driver:
                self.driver.quit()
                # print('[エンゲージRPA] ✓ ブラウザを閉じました')
            else:
                pass
                # print('[エンゲージRPA] ⚠️  ブラウザは初期化されていません')
        except Exception as e:
            pass
            # print(f'[エンゲージRPA] ⚠️  ブラウザ終了エラー（無視して続行）: {e}')
    
    def __del__(self):
        """デストラクタ - ブラウザが残らないように"""
        try:
            self.close()
        except:
            pass  # デストラクタでは例外を無視


# テスト用のmain関数
if __name__ == '__main__':
    print('エンゲージログインモジュールのテスト')
    print('=' * 50)
    print('⚠️  このモジュールはまだ実装されていません')
    print('実装が必要な機能:')
    print('  1. エンゲージのログイン処理')
    print('  2. 応募者詳細ページへのアクセス')
    print('  3. 応募者情報の抽出（氏名、性別、年齢、連絡先など）')
    print('  4. エラーハンドリングとリトライロジック')
    print('')
    print('参考: src/jobbox_login.py を見て同様の構造で実装してください')
    print('=' * 50)
