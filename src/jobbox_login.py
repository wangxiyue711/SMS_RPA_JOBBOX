from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait as WW
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import json, time, os, re, unicodedata, datetime
from selenium.webdriver.common.keys import Keys
from typing import Optional

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

    def _find_detail_panel(self, timeout=3):
        """Locate the right-side applicant detail panel (not the main table).

        Strategy:
        - Look for elements containing '氏名' or '応募No' that are not inside a table element.
        - Prefer visible elements.
        Returns the WebElement of the panel or None.
        """
        try:
            # XPath: element that contains '氏名' but has no ancestor table
            xp = "//*[contains(normalize-space(.),'氏名') and not(ancestor::table)]"
            el = WW(self.driver, timeout).until(EC.visibility_of_element_located((By.XPATH, xp)))
            # climb up to a reasonable container (e.g. nearest ancestor div)
            try:
                panel = el.find_element(By.XPATH, "ancestor::div[1]")
                return panel
            except Exception:
                return el
        except Exception:
            # fallback: try other common detail panel classes
            tries = [
                "//div[contains(@class,'detail') or contains(@class,'profile') or contains(@class,'drawer') or contains(@class,'side')][1]",
            ]
            for xp in tries:
                try:
                    el = WW(self.driver, timeout).until(EC.visibility_of_element_located((By.XPATH, xp)))
                    return el
                except Exception:
                    continue
        return None

    def _normalize_gender(self, raw: str) -> str:
        """Normalize gender text to '男性'/'女性'/'不明'."""
        if not raw:
            return '不明'
        s = re.sub(r"\s+", '', str(raw)).lower()
        # common Japanese words
        if any(x in s for x in ('男性', '男')):
            return '男性'
        if any(x in s for x in ('女性', '女')):
            return '女性'
        # latin abbreviations
        if re.match(r'^[mf]$', s):
            return '男性' if s == 'm' else '女性'
        if s in ('male', 'm', 'man'):
            return '男性'
        if s in ('female', 'f', 'woman'):
            return '女性'
        return '不明'

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
                        # Ensure document ready
                        self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 20)
                        panel_ok = False
                        for _ in range(16):
                            try:
                                # use integer timeout for the helper
                                if self._find_detail_panel(timeout=1):
                                    panel_ok = True
                                    break
                            except Exception:
                                pass
                            time.sleep(0.5)
                        if not panel_ok:
                            print("(warning) 右側の詳細パネルが指定時間内に見つかりませんでした。global fallback を使います。")
                        detail = self._collect_and_check_detail(oubo_no_norm, kyujin_title_exact)

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

                        try: self.driver.switch_to.default_content()
                        except: pass
                        continue

            # XPath 没命中 → 尝试 JS 兜底（结构变化时很好用）
            if self.click_name_by_title_js(kyujin_title_exact):
                self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 20)
                # Wait for detail panel to appear before collecting
                panel_ok = False
                for _ in range(16):
                    try:
                        if self._find_detail_panel(timeout=1):
                            panel_ok = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                if not panel_ok:
                    print("(warning) 右側の詳細パネルが指定時間内に見つかりませんでした。global fallback を使います。")
                detail = self._collect_and_check_detail(oubo_no_norm, kyujin_title_exact)
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
    def _collect_and_check_detail(self, oubo_no_norm: str, expected_kyujin: Optional[str] = None):
        def pick(xps):
            """
            Try to extract text for the given xpaths from the right-side detail panel first.
            If the panel isn't present or yields no results, fall back to the global
            _wait_xpath-based search. Returns first non-empty extracted string.
            """
            def _extract_text_from_el(el):
                if not el:
                    return ''
                try:
                    txt = el.text.strip() if el.text else ''
                except:
                    txt = ''
                if not txt:
                    try:
                        txt = (el.get_attribute('value') or '').strip()
                    except:
                        txt = ''
                if not txt:
                    try:
                        txt = self.driver.execute_script("return arguments[0].innerText || arguments[0].textContent || '';", el) or ''
                        txt = txt.strip()
                    except:
                        txt = ''
                return txt

            # Attempt: prefer the right-side detail panel
            panel = None
            try:
                panel = self._find_detail_panel(timeout=4)
            except Exception:
                panel = None

            if panel:
                for xp in xps:
                    try:
                        # Always convert to a relative xpath when searching inside panel
                        # to avoid matching the document root (主ページ) by absolute xpaths
                        if xp.startswith('.'):
                            rel_xp = xp
                        elif xp.startswith('//') or xp.startswith('/'):
                            rel_xp = '.' + xp
                        else:
                            # not starting with /, treat as descendant
                            rel_xp = './/' + xp.lstrip('./')

                        try:
                            el = panel.find_element(By.XPATH, rel_xp)
                        except Exception:
                            el = None

                        txt = _extract_text_from_el(el)
                        if txt:
                            return txt
                    except Exception:
                        continue

            # Fallback: global search
            for xp in xps:
                try:
                    el = self._wait_xpath(xp, 3, visible=True)
                    if not el:
                        continue
                    txt = _extract_text_from_el(el)
                    if txt:
                        return txt
                except Exception:
                    continue
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
        # Prefer strict selectors for 性別 first (th/td, dt/dd, sibling) and prefer short text nodes
        gender = pick([
            "//th[normalize-space(.)='性別']/following-sibling::td[1][string-length(normalize-space(.))<30]",
            "//dt[normalize-space(.)='性別']/following-sibling::dd[1][string-length(normalize-space(.))<30]",
            "//*[normalize-space(text())='性別']/following-sibling::*[normalize-space(.)!='' and string-length(normalize-space(.))<30][1]",
            # general fallback but prefer short nodes to avoid memo blocks
            "//*[contains(normalize-space(.),'性別')]/following::*[normalize-space(.)!='' and string-length(normalize-space(.))<30][1]",
        ])

        raw_gender = gender or ''
        try:
            # First try normalize on the primary extraction
            gender_norm = self._normalize_gender(raw_gender)
            if gender_norm != '不明':
                gender = gender_norm
            else:
                # If initial extraction returned a very long value (likely a memos block),
                # try a panel-local short-node search directly to pick tokens like '男性'/'女性'.
                panel = None
                try:
                    panel = self._find_detail_panel(timeout=1)
                except Exception:
                    panel = None

                # Attempt a targeted short-node search inside the panel for small values
                if panel and (not raw_gender or len(raw_gender) > 40 or raw_gender.count('\n') > 2):
                    try:
                        el = panel.find_element(By.XPATH, ".//*[contains(normalize-space(.),'性別')]/following::*[normalize-space(.)!='' and string-length(normalize-space(.))<20][1]")
                        if el:
                            candidate = (el.text or '').strip()
                            if candidate:
                                found = candidate
                            else:
                                found = ''
                        else:
                            found = ''
                    except Exception:
                        found = ''
                else:
                    found = ''
                # Fallback: search inside the detail panel for short exact tokens like '男性'/'女性' etc.
                panel = None
                try:
                    panel = self._find_detail_panel(timeout=1)
                except Exception:
                    panel = None

                found = ''
                if panel:
                    tokens = ['男性','女性','男','女','M','F','m','f','male','female']
                    for t in tokens:
                        try:
                            # use a relative xpath inside panel to find exact-token nodes
                            els = panel.find_elements(By.XPATH, f".//*[normalize-space(.)={self._xpath_literal(t)}]")
                            for el in els:
                                try:
                                    if not el.is_displayed():
                                        continue
                                    txt = (el.text or '').strip()
                                    if txt:
                                        found = txt
                                        break
                                except:
                                    continue
                            if found:
                                break
                        except:
                            continue

                if found:
                    gender = self._normalize_gender(found)
                else:
                    gender = '不明'
                    print(f"(warning) 性別未能从 panel 明确解析，初始 raw='{(raw_gender or '')[:160].replace('\n',' ')}' -> '{gender}'")
        except Exception:
            gender = '不明'
        birth  = pick(["//*[contains(.,'生年月日')]/following::*[1]"])
        email  = pick(["//*[contains(.,'メールアドレス')]/following::*[1]"])
        tel    = pick(["//*[contains(.,'電話')]/following::*[1]"])
        addr   = pick(["//*[contains(.,'住所')]/following::*[1]"])
        # 学校名の抽出をより厳密に（"学校" だけの部分一致は "専門学校生" 等にもマッチするため禁止し、必ず "学校名" ラベルに限定）
        def _xp_eq_school_label(tag):
            # normalize punctuation and spaces, then exact or prefix match for 学校名[:：]?
            return (
                f"//{tag}[normalize-space(translate(., '：:　', '   '))='学校名' ]"
                f" | //{tag}[starts-with(normalize-space(translate(., '：:　', '   ')), '学校名')]"
            )

        school = pick([
            # th/td, dt/dd の厳密ラベル
            _xp_eq_school_label('th') + "/following-sibling::td[1]",
            _xp_eq_school_label('dt') + "/following-sibling::dd[1]",
            # 行（tr/dl）スコープ内でラベル=学校名の最後セルを拾う
            "(//*[normalize-space(translate(., '：:　', '   '))='学校名' or starts-with(normalize-space(translate(., '：:　', '   ')), '学校名')]/ancestor::*[self::tr or self::dl][1]//*[self::td or self::dd])[last()]",
        ])
        # フォールバック（どうしても取れない場合のみ、広い following で拾う）
        if not school:
            # 広いフォールバック：ただしラベルは必ず 学校名
            school = pick(["(//*[normalize-space(translate(., '：:　', '   '))='学校名' or starts-with(normalize-space(translate(., '：:　', '   ')), '学校名')]/following::*[normalize-space(.)!=''])[1]"])

        # 誤抽出ガード：学校名にメールが入ってしまうケースを除外
        try:
            # 明らかな誤抽出（メール/電話ラベルや電話番号パターンを含む）をガード
            if school and (
                ("@" in school or re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", school))
                or ('電話' in school) or re.search(r"\b0\d{9,10}\b", school)
            ):
                # 既に取得済みの email と同一/包含なら誤検出とみなして再トライ or 空にする
                if email and (school.strip() == email.strip() or email.strip() in school.strip()):
                    # もう一段厳しい候補で試す（パネル内の短い値や td/dd のみ、かつ 学校名 ラベル限定）
                    school_retry = pick([
                        ".//th[normalize-space(translate(., '：:　', '   '))='学校名' or starts-with(normalize-space(translate(., '：:　', '   ')), '学校名')]/following-sibling::td[1]",
                        ".//dt[normalize-space(translate(., '：:　', '   '))='学校名' or starts-with(normalize-space(translate(., '：:　', '   ')), '学校名')]/following-sibling::dd[1]",
                        ".//*[normalize-space(translate(., '：:　', '   '))='学校名' or starts-with(normalize-space(translate(., '：:　', '   ')), '学校名')]/following-sibling::*[string-length(normalize-space(.))>0 and string-length(normalize-space(.))<80][1]",
                    ])
                    if school_retry and not ("@" in school_retry) and ('電話' not in school_retry) and (not re.search(r"\b0\d{9,10}\b", school_retry)):
                        school = school_retry
                    else:
                        # どうしても学校名が判別できない場合は空にする（CSV 列ずれ回避のため）
                        school = ''
        except Exception:
            pass
        oubo_dt= pick(["//*[contains(.,'応募日') or contains(.,'応募日時')]/following::*[1]"])
        kyujin = pick(["//*[contains(.,'応募求人')]/following::*[1]"])
        # 如果调用者传入了预期的求人标题，优先使用它以提高匹配准确性
        if expected_kyujin:
            kyujin = expected_kyujin
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
        
        # 新增：获取勤務先名（会社名）
        employer_name = ''
        current_url = self.driver.current_url  # 保存当前页面URL以便返回
        
        try:
            print("=== 勤務先名を取得中 ===")
            
            # 直接查找応募求人字段中的职位链接（针对截图中粉色圆圈标记的位置）
            job_link = None
            exclude_keywords = ['求人ボックス', '採用ボード', '採用ボードへ', '公開中のページ']
            
            # 关键改进：先确定当前求职者的主要信息容器（包含氏名的区域），只在该区域内查找応募求人链接
            main_container = None
            try:
                # 尝试定位包含当前求职者氏名信息的主容器
                # 优先查找包含"氏名"标签的最近祖先容器（通常是 div、section、main 等）
                name_labels = self.driver.find_elements(By.XPATH, "//th[normalize-space(.)='氏名'] | //dt[normalize-space(.)='氏名'] | //label[contains(., '氏名')]")
                for nl in name_labels:
                    try:
                        # 查找最近的有意义的容器（div/section/main/article）
                        for tag in ('main', 'section', 'article', 'div'):
                            try:
                                container = nl.find_element(By.XPATH, f"./ancestor::{tag}[contains(@class, 'detail') or contains(@class, 'profile') or contains(@class, 'info') or contains(@class, 'content')][1]")
                                if container:
                                    main_container = container
                                    break
                            except: pass
                        
                        # 如果没有找到带特定class的容器，尝试更通用的祖先容器
                        if not main_container:
                            try:
                                for tag in ('main', 'section', 'article'):
                                    try:
                                        container = nl.find_element(By.XPATH, f"./ancestor::{tag}[1]")
                                        if container:
                                            main_container = container
                                            break
                                    except: pass
                            except: pass
                        
                        if main_container:
                            break
                    except: continue
            except Exception as e:
                print(f"主要コンテナ検出エラー: {e}")
            
            # 如果找到主容器，只在该容器内查找；否则使用全局选择器但更严格
            search_prefix = ".//" if main_container else "//"
            
            # 专门查找応募求人标签右侧的职位内容区域
            try:
                # 方法1: 查找応募求人标签，然后在其后的内容中查找链接
                oubo_kyujin_selectors = [
                    # 查找応募求人标签后的内容区域中的链接（优先使用dt/dd结构）
                    f"{search_prefix}dt[contains(normalize-space(.), '応募求人')]/following-sibling::dd[1]//a[@href]",
                    f"{search_prefix}th[contains(normalize-space(.), '応募求人')]/following-sibling::td[1]//a[@href]",
                    f"{search_prefix}td[contains(normalize-space(.), '応募求人')]/following-sibling::td[1]//a[@href]",
                    # 更宽泛的查找，在応募求人后的元素中查找
                    f"{search_prefix}*[contains(normalize-space(.), '応募求人')]/following-sibling::*[1]//a[@href]",
                ]
                
                for selector in oubo_kyujin_selectors:
                    try:
                        # 如果有主容器，在容器内查找；否则全局查找
                        if main_container:
                            links = main_container.find_elements(By.XPATH, selector)
                        else:
                            links = self.driver.find_elements(By.XPATH, selector)
                        
                        for link in links:
                            if not link.is_displayed() or not link.is_enabled():
                                continue
                            
                            link_text = (link.text or '').strip()
                            href = (link.get_attribute('href') or '')
                            
                            # 跳过黑名单关键词
                            if any(k in link_text for k in exclude_keywords):
                                print(f"スキップ(黒名单): {link_text[:50]}")
                                continue
                            
                            # 跳过空链接或无效链接
                            if not link_text or len(link_text) < 3:
                                continue
                            
                            # 额外验证：确保链接在当前可见区域内（避免点到隐藏的或页面外的链接）
                            try:
                                location = link.location
                                size = link.size
                                if location['y'] < 0 or size['height'] == 0:
                                    print(f"スキップ(非表示): {link_text[:50]}")
                                    continue
                            except: pass
                            
                            # 【关键改进】如果有kyujin参数，必须完全匹配或高度相似才接受
                            if kyujin:
                                # 归一化比较（移除空白）
                                kyujin_norm = self._norm(kyujin)
                                link_norm = self._norm(link_text)
                                
                                # 完全匹配
                                if kyujin_norm == link_norm:
                                    job_link = link
                                    print(f"✓ 応募求人リンクが見つかりました (完全一致): {link_text[:50]}")
                                    break
                                
                                # 高相似度匹配：kyujin包含在link中或link包含在kyujin中
                                elif kyujin_norm in link_norm or link_norm in kyujin_norm:
                                    # 进一步验证：相似度要足够高（长度差不超过20%）
                                    len_diff = abs(len(kyujin_norm) - len(link_norm))
                                    max_len = max(len(kyujin_norm), len(link_norm))
                                    if max_len > 0 and len_diff / max_len <= 0.2:
                                        job_link = link
                                        print(f"✓ 応募求人リンクが見つかりました (高相似): {link_text[:50]}")
                                        break
                                    else:
                                        continue
                                else:
                                    # 不匹配，跳过
                                    continue
                            else:
                                # 没有kyujin参数时才使用宽松匹配
                                if '/job' in href or '/jobs' in href or '求人' in href:
                                    job_link = link
                                    print(f"応募求人リンクが見つかりました (URL匹配): {link_text[:50]}")
                                    break
                                elif len(link_text) > 10 and href and 'http' in href:
                                    if '一覧' not in link_text and 'メニュー' not in link_text and 'ナビ' not in link_text:
                                        job_link = link
                                        print(f"応募求人リンクが見つかりました (一般链接): {link_text[:50]}")
                                        break
                        
                        if job_link:
                            break
                    except Exception as e:
                        print(f"応募求人セレクター試行エラー: {selector} - {e}")
                        continue
                
                # 方法2: 如果上述方法没找到，尝试在主容器范围内查找包含応募求人的局部容器
                if not job_link and main_container:
                    try:
                        # 在主容器内查找包含応募求人文本的元素
                        oubo_elements = main_container.find_elements(By.XPATH, ".//*[contains(normalize-space(.), '応募求人')]")
                        for oubo_elem in oubo_elements:
                            try:
                                # 在该元素的父级或兄弟元素中查找链接
                                parent = oubo_elem.find_element(By.XPATH, "./parent::*")
                                links = parent.find_elements(By.XPATH, ".//a[@href]")
                                
                                for link in links:
                                    if not link.is_displayed() or not link.is_enabled():
                                        continue
                                    
                                    link_text = (link.text or '').strip()
                                    href = (link.get_attribute('href') or '')
                                    
                                    # 跳过黑名单关键词和応募求人自身的链接
                                    if any(k in link_text for k in exclude_keywords):
                                        continue
                                    if '応募求人' in link_text:
                                        continue
                                    
                                    # 查找实际的职位内容链接
                                    if link_text and len(link_text) > 5:
                                        # 【严格匹配kyujin】
                                        if kyujin:
                                            kyujin_norm = self._norm(kyujin)
                                            link_norm = self._norm(link_text)
                                            
                                            # 完全匹配
                                            if kyujin_norm == link_norm:
                                                job_link = link
                                                print(f"✓ 応募求人リンクが見つかりました (コンテナ内完全一致): {link_text[:50]}")
                                                break
                                            # 高相似度匹配
                                            elif kyujin_norm in link_norm or link_norm in kyujin_norm:
                                                len_diff = abs(len(kyujin_norm) - len(link_norm))
                                                max_len = max(len(kyujin_norm), len(link_norm))
                                                if max_len > 0 and len_diff / max_len <= 0.2:
                                                    job_link = link
                                                    print(f"✓ 応募求人リンクが見つかりました (コンテナ内高相似): {link_text[:50]}")
                                                    break
                                        else:
                                            # 没有kyujin时才使用宽松匹配
                                            if len(link_text) > 15 and href and 'http' in href:
                                                if '一覧' not in link_text:
                                                    job_link = link
                                                    print(f"応募求人リンクが見つかりました (コンテナ内一般): {link_text[:50]}")
                                                    break
                                
                                if job_link:
                                    break
                            except: continue
                    except Exception as e:
                        print(f"コンテナ内検索エラー: {e}")
                
                # 方法3: 如果仍未找到且没有主容器限制，作为最后手段全局搜索（但更严格过滤）
                if not job_link and not main_container:
                    try:
                        # 查找包含応募求人文本的容器元素
                        containers = self.driver.find_elements(By.XPATH, "//*[contains(normalize-space(.), '応募求人')]")
                        for container in containers:
                            try:
                                # 在该容器的父级或兄弟元素中查找链接
                                parent = container.find_element(By.XPATH, "./parent::*")
                                links = parent.find_elements(By.XPATH, ".//a[@href]")
                                
                                for link in links:
                                    if not link.is_displayed() or not link.is_enabled():
                                        continue
                                    
                                    link_text = (link.text or '').strip()
                                    href = (link.get_attribute('href') or '')
                                    
                                    # 跳过黑名单关键词和応募求人自身的链接
                                    if any(k in link_text for k in exclude_keywords):
                                        continue
                                    if '応募求人' in link_text:
                                        continue
                                    
                                    # 查找实际的职位内容链接
                                    if link_text and len(link_text) > 5:
                                        # 【严格匹配kyujin】
                                        if kyujin:
                                            kyujin_norm = self._norm(kyujin)
                                            link_norm = self._norm(link_text)
                                            
                                            # 完全匹配
                                            if kyujin_norm == link_norm:
                                                job_link = link
                                                print(f"✓ 応募求人リンクが見つかりました (全局完全一致): {link_text[:50]}")
                                                break
                                            # 高相似度匹配
                                            elif kyujin_norm in link_norm or link_norm in kyujin_norm:
                                                len_diff = abs(len(kyujin_norm) - len(link_norm))
                                                max_len = max(len(kyujin_norm), len(link_norm))
                                                if max_len > 0 and len_diff / max_len <= 0.2:
                                                    job_link = link
                                                    print(f"✓ 応募求人リンクが見つかりました (全局高相似): {link_text[:50]}")
                                                    break
                                        else:
                                            # 没有kyujin时才使用宽松匹配
                                            if len(link_text) > 15 and href and 'http' in href:
                                                if '一覧' not in link_text:
                                                    job_link = link
                                                    print(f"応募求人リンクが見つかりました (全局一般): {link_text[:50]}")
                                                    break
                                
                                if job_link:
                                    break
                            except: continue
                    except: pass
            except Exception as e:
                print(f"応募求人リンク検索エラー: {e}")
            
            if job_link:
                # 点击链接进入职位详细页面
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", job_link)
                try:
                    job_link.click()
                except:
                    self.driver.execute_script("arguments[0].click();", job_link)
                
                # ページロードを待機
                time.sleep(2)
                self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 15)
                
                # 職位詳細ページで勤務先名を検索
                # 成功実績のあるセレクターを先頭に配置
                employer_selectors = [
                    # 成功したパターンを最初に試行
                    "//*[contains(.,'勤務先名')]/following-sibling::*[1][not(contains(.,'必須'))]",
                    "//*[contains(.,'勤務先名')]/following::*[1][not(contains(.,'必須'))][text()]",
                    # バックアップセレクター
                    "//dt[contains(.,'勤務先名')]/following-sibling::dd[1]",
                    "//th[normalize-space(.)='勤務先名']/following-sibling::td[1]",
                    "//td[normalize-space(.)='勤務先名']/following-sibling::td[1]",
                    # 入力フィールド向けセレクター
                    "//label[contains(.,'勤務先名')]/following-sibling::input[1]/@value",
                    "//label[contains(.,'勤務先名')]/following-sibling::*[1]/input[1]/@value", 
                    "//label[contains(.,'勤務先名')]/following-sibling::*[1]//input[1]/@value",
                    "//*[contains(.,'勤務先名')]/ancestor::*[1]//input[@value and @value!='']/@value",
                    "//*[contains(.,'勤務先名')]/parent::*//input[@value and @value!='']/@value",
                    # 企業名・会社名の別名も対応
                    "//th[contains(.,'企業名')]/following-sibling::td[1]", 
                    "//th[contains(.,'会社名')]/following-sibling::td[1]",
                    "//*[contains(.,'企業名')]/following::*[1][not(contains(.,'必須'))]",
                    "//*[contains(.,'会社名')]/following::*[1][not(contains(.,'必須'))]"
                ]
                
                for selector in employer_selectors:
                    try:
                        # 判断是否是属性选择器
                        if selector.endswith('/@value'):
                            # 属性选择器，需要使用不同的方法获取值
                            element_selector = selector.replace('/@value', '')
                            el = self._wait_xpath(element_selector, 3, visible=True)
                            if el:
                                employer_name = el.get_attribute('value') or ''
                                employer_name = employer_name.strip()
                                if employer_name and employer_name != '必須' and len(employer_name) > 1:
                                    print(f"勤務先名 (属性から取得): {employer_name}")
                                    break
                        else:
                            # 文本选择器
                            el = self._wait_xpath(selector, 3, visible=True)
                            if el:
                                # 尝试多种方式获取文本
                                employer_name = el.text.strip() if el.text else ''
                                # 如果没有文本，尝试获取value属性
                                if not employer_name:
                                    employer_name = (el.get_attribute('value') or '').strip()
                                # 如果还是空，尝试获取innerText
                                if not employer_name:
                                    try:
                                        employer_name = self.driver.execute_script("return arguments[0].innerText || arguments[0].textContent || '';", el).strip()
                                    except:
                                        pass
                                
                                # 取得した内容が有効かどうかを検証
                                if employer_name and employer_name != '必須' and len(employer_name) > 1:
                                    print(f"勤務先名 (テキストから取得): {employer_name}")
                                    break
                    except Exception as e:
                        print(f"セレクター試行エラー: {selector} - {e}")
                        continue
                
                if not employer_name:
                    print("職位詳細ページで勤務先名が見つかりませんでした")

                
                # 個人情報ページに戻る
                print("個人情報ページに戻ります...")
                self.driver.get(current_url)
                time.sleep(1.5)
                self._wait(lambda d: d.execute_script('return document.readyState')=='complete', 15)
                
            else:
                print("応募求人のリンクが見つかりませんでした")
                
        except Exception as e:
            print(f"勤務先名取得エラー: {e}")
            # エラー時は元のページに戻る
            try:
                self.driver.get(current_url)
                time.sleep(1)
            except:
                pass
        
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
            "oubo_no": oubo_no_val, "oubo_no_extracted": oubo_no_extracted, "oubo_no_ok": oubo_no_ok,
            "employer_name": employer_name  # 新增勤務先名
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
        if detail.get('employer_name'):
            print(f"勤務先名: {detail.get('employer_name','')}")
        print("==================\n")

    def close(self):
        self.driver.quit()

