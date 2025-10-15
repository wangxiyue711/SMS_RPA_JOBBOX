from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as WW
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import json, time, os, re, unicodedata, datetime
from selenium.webdriver.common.keys import Keys

CONFIG_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'config', 'accounts.json'))

class JobboxLogin:
    # ---------- 小工具 ----------
    def _wait(self, cond, timeout=20):
        return WW(self.driver, timeout).until(cond)

    def _wait_css(self, css, timeout=20, clickable=False, visible=True):
        by = (By.CSS_SELECTOR, css)
        if clickable: return self._wait(EC.element_to_be_clickable(by), timeout)
        if visible:   return self._wait(EC.visibility_of_element_located(by), timeout)
        return self._wait(EC.presence_of_element_located(by), timeout)

    def _wait_xpath(self, xp, timeout=20, clickable=False, visible=True):
        by = (By.XPATH, xp)
        if clickable: return self._wait(EC.element_to_be_clickable(by), timeout)
        if visible:   return self._wait(EC.visibility_of_element_located(by), timeout)
        return self._wait(EC.presence_of_element_located(by), timeout)

    def _norm(self, s: str) -> str:
        if not s: return ''
        s = unicodedata.normalize('NFKC', s)
        return re.sub(r'\s+', '', s)

    def _xpath_literal(self, s: str) -> str:
        # 把任意字符串安全拼到 XPath 字面量
        if "'" not in s:  return f"'{s}'"
        if '"' not in s:  return f'"{s}"'
        parts = s.split("'")
        return "concat(" + ",\"'\",".join([f"'{p}'" for p in parts]) + ")"

    def _is_driver_alive(self) -> bool:
        """检查 WebDriver 会话是否仍然活跃"""
        try:
            # 尝试获取当前窗口句柄，这是一个简单的操作来测试连接
            self.driver.current_window_handle
            return True
        except Exception:
            return False

    def _maybe_switch_iframe(self) -> bool:
        frames = self.driver.find_elements(By.CSS_SELECTOR, "iframe")
        for f in frames:
            try:
                self.driver.switch_to.frame(f)
                if self.driver.find_elements(By.XPATH, "//table//th[contains(., '氏名') or contains(., '応募求人')]"):
                    return True
                self.driver.switch_to.default_content()
            except Exception:
                try: self.driver.switch_to.default_content()
                except: pass
        return False

    def _find_main_table(self):
        tables = self.driver.find_elements(By.XPATH, "//table[.//th]")
        for t in tables:
            try:
                th_text = ''.join([th.text for th in t.find_elements(By.XPATH, ".//th")])
                if ('氏名' in th_text) or ('応募求人' in th_text):
                    return t
            except: pass
        return None

    def _paginate_next(self) -> bool:
        try:
            nxt = self.driver.find_element(
                By.XPATH,
                "//a[contains(., '次へ') or contains(., '次') or contains(., 'Next')] | //button[contains(., '次へ') or contains(., 'Next')]"
            )
            if nxt.is_displayed() and nxt.is_enabled():
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", nxt)
                nxt.click()
                time.sleep(1.2)
                return True
        except: pass
        return False

    def click_name_by_title_js(self, kyujin_title: str) -> bool:
        # 容错兜底：直接在前端用 innerText 折叠空白做匹配
        script = r"""
const target = (arguments[0] || '').replace(/\s+/g,'');
const norm = s => (s||'').replace(/\s+/g,'');
const tables = Array.from(document.querySelectorAll('table')).filter(t => t.querySelector('th'));
const hasHeader = t => {
  const all = Array.from(t.querySelectorAll('th')).map(th=>th.textContent).join('');
  return all.includes('氏名') || all.includes('応募求人');
};
const table = tables.find(hasHeader);
if(!table) return 'NO_TABLE';
const ths = Array.from(table.querySelectorAll('th')).map(th=>th.textContent);
const nameIdx = ths.findIndex(x=>x.includes('氏名'));
const occIdx  = ths.findIndex(x=>x.includes('応募求人'));
if(nameIdx<0 || occIdx<0) return 'NO_INDEX';
for(const tr of table.querySelectorAll('tr')){
  const tds = Array.from(tr.querySelectorAll('td'));
  if(!tds.length) continue;
  const occ = tds[occIdx]?.innerText || '';
  if(norm(occ)===target || norm(occ).includes(target) || target.includes(norm(occ))){
    const a = (tds[nameIdx]||tr).querySelector('a');
    if(a){ a.scrollIntoView({block:'center'}); a.click(); return 'CLICKED'; }
  }
}
return 'NOT_FOUND';
"""
        res = self.driver.execute_script(script, kyujin_title)
        print("[JS_RESULT]", res)
        return res == 'CLICKED'

    # ---------- 弹窗 & 验证码 ----------
    def _close_ad_popup_buttons(self):
        try:
            btns = self.driver.find_elements(By.XPATH, "//button[contains(text(), 'キャンセル') or contains(text(), 'Cancel')]")
            for b in btns:
                if b.is_displayed() and b.is_enabled():
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", b)
                    b.click()
                    time.sleep(0.6)
                    return
        except: pass

    def close_popup_if_exists(self):
        try:
            for _ in range(2):
                close_btns = self.driver.find_elements(By.XPATH, "//button[contains(@class,'modal') and (contains(@class,'close') or contains(@class,'_close'))]")
                acted = False
                for btn in close_btns:
                    try:
                        if btn.is_displayed() and btn.is_enabled():
                            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                            self.driver.execute_script("arguments[0].click();", btn)
                            acted = True
                            time.sleep(0.3)
                    except: pass
                if not acted: break
        except: pass

    def wait_for_captcha_solve(self, timeout=300):
        try:
            start = time.time()
            def has_cap():
                try:
                    return bool(self.driver.find_elements(By.CSS_SELECTOR, "iframe[src*='recaptcha'], .g-recaptcha, div.recaptcha"))
                except: return False
            if not has_cap(): return
            print('キャプチャを検出しました。ブラウザで完了後、Enterキーを押すか自動で消えるのを待ってください...')
            while True:
                if not has_cap(): 
                    print('キャプチャ完了。'); return
                if time.time() - start > timeout:
                    print('キャプチャの待機がタイムアウトしました。処理を続行します。'); return
                time.sleep(1)
        except: return

    # ---------- 构造/登录/跳转 ----------
    def __init__(self, account_name):
        # 现在只支持直接传入 account 字典（来自 Firestore 的 jobbox_accounts 文档）
        if not isinstance(account_name, dict):
            raise Exception("Firestore の jobbox_accounts から取得")
        self.account = account_name

        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument('--window-size=1400,900')
        chrome_options.add_experimental_option('excludeSwitches', ['enable-logging','enable-automation'])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        self.driver = webdriver.Chrome(options=chrome_options)

    def login_and_goto(self, url, kyujin_title=None, oubo_no=None):
        import random
        d = self.driver
        d.get(url)
        self._wait(lambda x: x.execute_script("return document.readyState")=="complete", 30)
        self._maybe_switch_iframe()

        email_elem = self._wait_xpath("//*[@id='login_email' or @name='email' or contains(@placeholder,'メール')]", 20, visible=True)
        for c in self.account['jobbox_id'] or '':
            email_elem.send_keys(c); time.sleep(random.uniform(0.05,0.09))

        pwd_elem = self._wait_xpath("//*[@id='login_password' or @name='password' or @type='password']", 20, visible=True)
        for c in self.account['jobbox_password'] or '':
            pwd_elem.send_keys(c); time.sleep(random.uniform(0.05,0.09))

        self.wait_for_captcha_solve()

        btn = self._wait_xpath("//button[@type='submit' or contains(., 'ログイン')]", 20, clickable=True)
        time.sleep(random.uniform(0.2,0.8)); btn.click()
        self._wait(lambda x: 'login' not in x.current_url, 30)
        d.switch_to.default_content()

        # 关闭弹窗
        self._close_ad_popup_buttons()
        self.close_popup_if_exists()

        # 进入「応募者一覧」
        if not self.goto_applicants():
            print("応募者一覧ページへの自動遷移に失敗しました。"); return

        # 若给了筛选条件，直接查找并点击
        if kyujin_title and oubo_no:
            info = self.find_and_check_applicant(kyujin_title, oubo_no)
            if info:
                # 若 find_and_check_applicant 已返回 detail，直接打印一次；否则兼容旧行为再抓一次
                if isinstance(info, dict) and info.get("detail"):
                    self.print_applicant_info(info["detail"])
                else:
                    self.print_applicant_info()
                return info
            else:
                print("該当する応募者が見つかりませんでした。")
                return None

    def goto_applicants(self) -> bool:
        try:
            # 直接找可点击的按钮/链接
            btn = self._wait_xpath("//*[contains(., '応募者一覧')][self::a or self::button]", 10, clickable=True)
            btn.click(); time.sleep(1.2); return True
        except Exception:
            pass
        # 退而求其次：全量扫描
        try:
            links = self.driver.find_elements(By.XPATH, "//a | //button")
            for el in links:
                try:
                    if not el.is_displayed() or not el.is_enabled(): continue
                    text = el.text or ''
                    if not text:
                        spans = el.find_elements(By.XPATH, ".//span")
                        text = ''.join(s.text for s in spans)
                    if '応募者一覧' in text:
                        el.click(); time.sleep(1.2); return True
                except: continue
        except: pass
        return False

    # ---------- 关键：按“応募求人=邮件求人标题” 点同一行氏名链接 ----------
    def find_and_check_applicant(self, kyujin_title, oubo_no):
        kyujin_title_exact = ' '.join((kyujin_title or '').split())  # 折叠空白
        kyujin_title_lit   = self._xpath_literal(kyujin_title_exact)
        oubo_no_norm       = self._norm(oubo_no or '')

        seen_pairs = set()  # 去重： (title_norm, name_norm)

        while True:
            self.driver.switch_to.default_content()
            self._maybe_switch_iframe()
            table = self._find_main_table()
            if not table:
                print("『氏名/応募求人』のヘッダを含む表が見つかりませんでした。")
                return None

            # 计算列索引（1-based，便于 XPath）
            ths = table.find_elements(By.XPATH, ".//th")
            name_col_idx = occ_col_idx = None
            for idx, th in enumerate(ths, start=1):
                t = self._norm(th.text)
                if ('氏名' in t) and (name_col_idx is None): name_col_idx = idx
                if ('応募求人' in t or '求人' in t) and (occ_col_idx is None): occ_col_idx = idx
            if not name_col_idx or not occ_col_idx:
                print("表のヘッダに『氏名』または『応募求人』がありません。正確に位置づけできません。")
                return None

            # 先做“精确相等”的行匹配
            row_xpath_eq = f".//tr[td[{occ_col_idx}][normalize-space(.)={kyujin_title_lit}]]"
            # 如果没有，退一步“包含匹配”
            row_xpath_contains = f".//tr[contains(normalize-space(td[{occ_col_idx}]), {kyujin_title_lit})]"

            for row_xp in (row_xpath_eq, row_xpath_contains):
                rows = table.find_elements(By.XPATH, row_xp)
                for r in rows:
                    try:
                        name_td = r.find_element(By.XPATH, f"./td[{name_col_idx}]")
                        nm = name_td.text.strip()
                        key = (self._norm(kyujin_title_exact), self._norm(nm))
                        if key in seen_pairs:  # 避免来回返回重复点
                            continue

                        link = None
                        links = name_td.find_elements(By.XPATH, ".//a")
                        link = links[0] if links else name_td
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", link)
                        try: link.click()
                        except: self.driver.execute_script("arguments[0].click();", link)

                        # 进入详情页 → 采集 & 比对 応募No.
                        self.driver.switch_to.default_content()
                        self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 20)
                        time.sleep(0.5)
                        detail = self._collect_and_check_detail(oubo_no_norm)

                        if detail.get("oubo_no_ok"):
                            print(f"該当する応募No.を見つけました: {oubo_no}")
                            # NOTE: 不在这里立即写入メモ。
                            # メモ("RPA:送信済み" 等) は send の結果を確認してから外側で書き込むように変更しました。
                            # 返回 detail，避免外侧再重复去抓一次页面导致重复打印
                            return {"name": nm, "title": kyujin_title, "row_matched": True, "detail": detail}

                        # 不匹配则返回列表继续
                        self.driver.back()
                        self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 20)
                        time.sleep(0.6)
                        seen_pairs.add(key)
                    except Exception as e:
                        print(f"[DEBUG] 行処理で例外: {e}")
                        try: self.driver.switch_to.default_content()
                        except: pass
                        continue

            # XPath 没命中 → 尝试 JS 兜底（结构变化时很好用）
            if self.click_name_by_title_js(kyujin_title_exact):
                self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 20)
                detail = self._collect_and_check_detail(oubo_no_norm)
                if detail.get("oubo_no_ok"):
                    print(f"該当する応募No.を見つけました: {oubo_no}")
                    return {"name": detail.get("name",""), "title": kyujin_title, "row_matched": True, "detail": detail}
                self.driver.back()
                self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 20)
                time.sleep(0.6)

            # 当前页没找到 → 下一页
            if not self._paginate_next():
                print("該当する求人タイトル・応募No.の応募者が見つかりませんでした（最終ページに到達しました）。")
                return None

    # ---------- 详情页采集 ----------
    def _collect_and_check_detail(self, oubo_no_norm: str):
        def pick(xps):
            for xp in xps:
                try:
                    el = self._wait_xpath(xp, 5, visible=True)
                    txt = el.text.strip()
                    if txt: return txt
                except: pass
            return ''
    
        print("\n=== 応募者情报 ===")
        # 更精确的氏名定位：优先从表格的 th/td 标签后抓真实氏名，避免误取页面标题
        name = pick([
            "//th[normalize-space(.)='氏名']/following::td[1]",
            "//td[normalize-space(.)='氏名']/following-sibling::td[1]",
            "//div[contains(@class,'profile')]//*[contains(text(),'氏名')]/following::*[1]",
            "//h1[not(contains(., '応募者一覧'))]",
            "//h2[not(contains(., '応募者一覧'))]"
        ])
        gender = pick(["//*[contains(.,'性別')]/following::*[1]"])
        birth  = pick(["//*[contains(.,'生年月日')]/following::*[1]"])
        email  = pick(["//*[contains(.,'メールアドレス')]/following::*[1]"])
        tel    = pick(["//*[contains(.,'電話')]/following::*[1]"])
        addr   = pick(["//*[contains(.,'住所')]/following::*[1]"])
        school = pick(["//*[contains(.,'学校') or contains(.,'学歴')]/following::*[1]"])
        oubo_dt= pick(["//*[contains(.,'応募日') or contains(.,'応募日時')]/following::*[1]"])
        kyujin = pick(["//*[contains(.,'応募求人')]/following::*[1]"])
        oubo_no_val = pick([
            "//*[self::td or self::th][contains(.,'応募No')]/following-sibling::*[1]",
            "//*[contains(.,'応募No')]/following::*[1]",
            "//*[contains(text(),'応募No')]/ancestor::*[self::tr or self::dl][1]//*[self::td or self::dd][last()]",
        ])
    
        # 从可能包含日期/时间的字段中抽取真正的応募No.（例如 A2-7829-0762）
        oubo_no_extracted = ''
        try:
            m = re.search(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+', oubo_no_val or '')
            if m:
                oubo_no_extracted = m.group(0)
            else:
                # 备用：若文本多行，取最后一行作为候选
                parts = (oubo_no_val or '').splitlines()
                if parts:
                    last = parts[-1].strip()
                    if last and len(last) > 2:
                        oubo_no_extracted = last
        except:
            oubo_no_extracted = ''
    
        print(f"氏名: {name}")
        print(f"性別: {gender}")
        print(f"生年月日: {birth}")
        print(f"メールアドレス: {email}")
        print(f"電話番号: {tel}")
        print(f"住所: {addr}")
        print(f"学校名: {school}")
        print(f"応募日時: {oubo_dt}")
        print(f"応募No.: {oubo_no_val}")
        if oubo_no_extracted and oubo_no_extracted != oubo_no_val:
            print(f"応募No.(抽出): {oubo_no_extracted}")
        print(f"応募求人: {kyujin}")
        print("==================\n")
    
        # 更宽松的匹配逻辑：比较原始字段归一化、抽取出的No.归一化，或包含关系
        oubo_no_ok = False
        try:
            if oubo_no_norm:
                if self._norm(oubo_no_val) == oubo_no_norm:
                    oubo_no_ok = True
                elif oubo_no_extracted and self._norm(oubo_no_extracted) == oubo_no_norm:
                    oubo_no_ok = True
                elif oubo_no_norm in self._norm(oubo_no_val):
                    oubo_no_ok = True
        except:
            oubo_no_ok = False
    
        return {
            "name": name, "gender": gender, "birth": birth, "email": email, "tel": tel,
            "addr": addr, "school": school, "oubo_dt": oubo_dt, "kyujin": kyujin,
            "oubo_no": oubo_no_val, "oubo_no_extracted": oubo_no_extracted, "oubo_no_ok": oubo_no_ok
        }

    def set_memo_and_save(self, memo_text: str = '送信済み'):
        # 检查 WebDriver 是否仍然活跃
        if not self._is_driver_alive():
            raise Exception('WebDriver セッションが無効です。ブラウザが閉じられた可能性があります。')
        
        # 尝试找到メモ（textarea/input）并填写，然后点击「選考情報を更新する」按钮保存
        try:
            # 优先找 textarea 或可编辑 div，兼容多种页面结构
            textarea_xps = [
                "//label[contains(., 'メモ')]/following::textarea[1]",
                "//textarea[contains(@placeholder, 'メモ') or contains(@name, 'memo') or contains(@id, 'memo')]",
                "//label[contains(., 'メモ')]/following::input[1]",
            ]
            el = None
            for xp in textarea_xps:
                try:
                    el = self._wait_xpath(xp, 3, visible=True)
                    if el:
                        break
                except: pass

            if not el:
                # 兜底：尝试按关键字搜索任何可编辑元素
                candidates = self.driver.find_elements(By.XPATH, "//textarea | //input[@type='text'] | //*[@contenteditable='true']")
                for c in candidates:
                    try:
                        txt = c.get_attribute('placeholder') or c.get_attribute('name') or c.get_attribute('id') or ''
                        if 'メモ' in (txt or '') or 'memo' in (txt or '').lower():
                            el = c; break
                    except: pass

            if not el:
                raise Exception('未能定位到メモ入力欄')

            # Read existing content (support textarea/input/value and contenteditable)
            existing = ''
            try:
                tag = el.tag_name.lower()
                if tag in ('textarea', 'input'):
                    try:
                        existing = el.get_attribute('value') or ''
                    except Exception:
                        existing = ''
                else:
                    try:
                        existing = el.get_attribute('textContent') or el.text or ''
                    except Exception:
                        existing = el.text or ''
            except Exception:
                existing = ''

            # Normalize and decide whether to append
            new_entry = memo_text.strip()
            # Append a timestamp to the entry, format: （YYYY/MM/DD，HH：MM） with full-width punctuation
            try:
                now = datetime.datetime.now()
                date_part = now.strftime('%Y/%m/%d')
                time_part = now.strftime('%H:%M').replace(':', '：')
                ts_suffix = f'（{date_part}，{time_part}）'
            except Exception:
                ts_suffix = ''
            new_entry_ts = f"{new_entry}{ts_suffix}" if ts_suffix else new_entry
            sep = '\n'
            combined = ''
            # If the bare entry (without timestamp) already exists in the memo, avoid duplicate appending
            if existing and new_entry in existing:
                combined = existing
            else:
                if existing:
                    combined = existing.rstrip() + sep + new_entry_ts
                else:
                    combined = new_entry_ts

            # Attempt to set combined content
            try:
                # Clear and send combined content for inputs/textarea
                try:
                    el.clear()
                except Exception:
                    pass
                el.click()
                # Use send_keys for robustness; if contenteditable, we can set via JS as fallback
                try:
                    el.send_keys(combined)
                except Exception:
                    try:
                        self.driver.execute_script("arguments[0].innerText = arguments[1];", el, combined)
                    except Exception:
                        try:
                            self.driver.execute_script("arguments[0].value = arguments[1];", el, combined)
                        except Exception:
                            pass
            except Exception:
                pass

            # 查找并点击「選考情報を更新する」按钮（支持按钮、input[type=submit]、a）
            btn_xps = [
                "//button[contains(., '選考情報を更新する') or contains(., '選考情報を更新')]",
                "//input[@type='submit' and (contains(@value,'選考情報を更新する') or contains(@value,'更新'))]",
                "//a[contains(., '選考情報を更新する') or contains(., '選考情報を更新')]",
            ]
            btn = None
            for xp in btn_xps:
                try:
                    btn = self._wait_xpath(xp, 3, clickable=True)
                    if btn:
                        break
                except: pass

            if not btn:
                # 进一步兜底：在页面寻找包含关键字的可点击元素
                elems = self.driver.find_elements(By.XPATH, "//button | //a | //input[@type='button' or @type='submit']")
                for e in elems:
                    try:
                        t = e.text or e.get_attribute('value') or ''
                        if '選考情報' in t and ('更新' in t or '保存' in t):
                            btn = e; break
                    except: pass

            if not btn:
                raise Exception('未能定位到「選考情報を更新する」按钮')

            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            try:
                btn.click()
            except:
                self.driver.execute_script('arguments[0].click();', btn)

            # 等待可能的保存完成（短等待）
            # 等待短时间让确认对话出现，然后尝试点击对话内的「変更する」按钮
            time.sleep(0.8)
            try:
                # 常见的对话里按钮可能是 button 或 input[type=button]
                confirm_xps = [
                    "//button[contains(., '変更する') or contains(., '変更')]",
                    "//input[@type='button' and (contains(@value,'変更する') or contains(@value,'変更'))]",
                    "//button[contains(@class,'confirm') and (contains(., '変更') or contains(., '変更する'))]",
                ]
                conf = None
                for xp in confirm_xps:
                    try:
                        conf = self._wait_xpath(xp, 2, clickable=True)
                        if conf:
                            break
                    except: pass

                if not conf:
                    # 兜底：在可见按钮里搜索文本
                    elems = self.driver.find_elements(By.XPATH, "//button | //input[@type='button' or @type='submit'] | //a")
                    for e in elems:
                        try:
                            t = e.text or e.get_attribute('value') or ''
                            if '変更する' in t or (('変更' in t) and ('取消' not in t and 'キャンセル' not in t)):
                                conf = e; break
                        except: pass

                if conf:
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", conf)
                        try: conf.click()
                        except: self.driver.execute_script('arguments[0].click();', conf)
                        time.sleep(0.6)
                    except Exception:
                        pass
            except Exception:
                pass
            return True
        except Exception:
            raise

    def print_applicant_info(self, detail=None):
        # 若传入 detail（find_and_check_applicant 已采集），直接打印；否则回退到原有的采集并打印
        if detail is None:
            _ = self._collect_and_check_detail(oubo_no_norm='')
            return
        print("\n=== 応募者情报 ===")
        print(f"氏名: {detail.get('name','')}")
        print(f"性別: {detail.get('gender','')}")
        print(f"生年月日: {detail.get('birth','')}")
        print(f"メールアドレス: {detail.get('email','')}")
        print(f"電話番号: {detail.get('tel','')}")
        print(f"住所: {detail.get('addr','')}")
        print(f"学校名: {detail.get('school','')}")
        print(f"応募日時: {detail.get('oubo_dt','')}")
        print(f"応募No.: {detail.get('oubo_no','')}")
        if detail.get('oubo_no_extracted'):
            print(f"応募No.(抽出): {detail.get('oubo_no_extracted')}")
        print(f"応募求人: {detail.get('kyujin','')}")
        print("==================\n")

    def close(self):
        self.driver.quit()

