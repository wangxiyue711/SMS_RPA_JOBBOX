"""
対話式の求人サイト抽出スクリプト。

処理の流れ:
1. 指定した URL を開く。
2. キーワードを自動入力してサイト内検索を実行する。
3. 検索結果から求人タイトルと企業名を抽出する。
4. 採用企業が見つからない場合は掲載企業を使う。
5. キーワード + タイトル + 企業名 + 企業種別 を出力し、CSV に保存する。
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


DEFAULT_TARGET_URL = "https://xn--pckua2a7gp15o89zb.com/93187E31781E495BAB"


SEARCH_INPUT_SELECTORS = [
    "input[name='q']",
    "input[name='kw']",
    "input[type='search']",
    "input[name='keyword']",
    "input[name='keywords']",
    "input[name*='search']",
    "input[id*='search']",
    "input[aria-label*='求人']",
    "input[aria-label*='検索']",
    "input[placeholder*='仕事']",
    "input[placeholder*='求人']",
    "input[placeholder*='キーワード']",
    "input[placeholder*='検索']",
    "textarea[name*='keyword']",
]

SEARCH_BUTTON_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button[aria-label*='検索']",
    "button[class*='search']",
    "a[class*='search']",
]

RESULT_CONTAINER_SELECTORS = [
    "article",
    "li",
    "div[class*='job']",
    "div[class*='result']",
    "section[class*='job']",
]

TITLE_SELECTORS = [
    "h1",
    "h2",
    "h3",
    "a[href*='/job']",
    "a[href*='/jobs']",
    "a[href*='/work']",
    "a[href*='detail']",
    "a",
]

COMPANY_SELECTORS = [
    ".company",
    "[class*='company']",
    "[data-testid*='company']",
    ".companyName",
    ".employer",
    "[class*='employer']",
    ".client",
    "[class*='corp']",
    "[class*='publisher']",
    "[data-testid*='publisher']",
]

RECRUITER_LABELS = ["企業名", "会社名", "勤務先", "採用企業", "雇用主"]
PUBLISHER_LABELS = ["掲載元", "掲載企業", "情報提供元", "投稿元", "配信元", "求人媒体"]
SKIP_TITLE_TERMS = ["保存", "お気に入り", "次へ", "前へ", "詳細条件", "並び替え"]
JOBBOX_COMPANY_STOP_WORDS = [
    "円",
    "時給",
    "月給",
    "年収",
    "正社員",
    "アルバイト",
    "パート",
    "派遣",
    "業務委託",
    "未経験",
    "徒歩",
    "勤務",
    "神奈川",
    "東京",
    "埼玉",
    "千葉",
    "大阪",
    "福岡",
    "掲載",
    "応募画面へ進む",
]
JOBBOX_METADATA_MARKERS = [
    "時給",
    "日給",
    "月給",
    "年収",
    "固定報酬",
    "交通費",
    "アルバイト",
    "パート",
    "派遣社員",
    "正社員",
    "契約社員",
    "業務委託",
    "徒歩",
    "車",
    "駅",
    "県",
    "都",
    "府",
]
JOBBOX_IGNORED_LINES = [
    "かんたん応募",
    "人気",
    "新着メール",
    "条件を保存",
    "アプリでもっと便利に",
    "関連検索",
    "詳細表示",
]


@dataclass
class JobRecord:
    keyword: str
    title: str
    company_name: str
    company_type: str
    source_url: str


def prompt_if_empty(value: Optional[str], label: str) -> str:
    if value:
        return value.strip()
    return input(f"{label}: ").strip()


def normalize_company_type(value: str) -> str:
    if value == "发布企业":
        return "掲載企業"
    return ""


def normalize_match_text(value: str) -> str:
    return clean_text(unicodedata.normalize("NFKC", value or ""))


def seems_detail_company_text(text: str) -> bool:
    if not text:
        return False
    if len(text) > 100:
        return False
    normalized = clean_text(text.rstrip("-").rstrip("|"))
    return any(token in normalized for token in ["株式会社", "有限会社", "合同会社", "Inc", "LLC", "Corp", "Group", "センター", "店"]) 


def normalize_search_keyword(raw_keyword: str) -> str:
    keyword = clean_text(raw_keyword)
    if not keyword:
        return ""

    # 求人ボックスの入力例に合わせて、複数キーワードは OR 形式へ統一する。
    if re.search(r"\s+or\s+", keyword, flags=re.IGNORECASE):
        parts = [clean_text(part) for part in re.split(r"\s+or\s+", keyword, flags=re.IGNORECASE)]
    elif any(separator in keyword for separator in [",", "，", "、", "\n", "\r", ";", "；"]):
        parts = [clean_text(part) for part in re.split(r"[，,、;；\r\n]+", keyword)]
    else:
        return keyword

    parts = [part for part in parts if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return " or ".join(parts)


def build_driver(headless: bool) -> Chrome:
    options = webdriver.ChromeOptions()
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    if headless:
        options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(3)
    return driver


def wait_ready(driver: Chrome, timeout: int = 20) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )


def first_visible(driver: Chrome, selectors: Iterable[str], timeout: int = 5) -> Optional[WebElement]:
    end_at = time.time() + timeout
    while time.time() < end_at:
        for selector in selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
            except Exception:
                continue
            for element in elements:
                try:
                    if element.is_displayed() and element.is_enabled():
                        return element
                except Exception:
                    continue
        time.sleep(0.2)
    return None


def is_jobbox_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "xn--pckua2a7gp15o89zb.com" in host or "求人ボックス.com" in host


def perform_keyword_search(driver: Chrome, keyword: str) -> bool:
    normalized_keyword = normalize_search_keyword(keyword)
    search_input = first_visible(driver, SEARCH_INPUT_SELECTORS, timeout=6)
    if not search_input:
        return False

    try:
        search_input.clear()
    except Exception:
        pass

    search_input.send_keys(normalized_keyword)
    time.sleep(0.3)

    button = first_visible(driver, SEARCH_BUTTON_SELECTORS, timeout=2)
    if button:
        try:
            driver.execute_script("arguments[0].click();", button)
            wait_ready(driver, timeout=20)
            return True
        except Exception:
            pass

    search_input.send_keys(Keys.ENTER)
    wait_ready(driver, timeout=20)
    return True


def wait_for_results(driver: Chrome, timeout: int = 20) -> None:
    WebDriverWait(driver, timeout).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "a[href*='/jbi/'], h2, h3")) > 3
    )


def page_has_jobbox_results(driver: Chrome) -> bool:
    try:
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/jb/'], a[href*='/rd/?']")
    except Exception:
        return False
    visible_links = 0
    for link in links:
        try:
            if link.is_displayed():
                visible_links += 1
        except Exception:
            continue
        if visible_links >= 5:
            return True
    return False


def manual_continue_if_needed(driver: Chrome, reason: str) -> None:
    print(reason)
    print("開いたブラウザでログイン、認証、またはサイト内検索を手動で完了してください。完了後に Enter を押してください。")
    input("続行するには Enter を押してください... ")
    wait_ready(driver, timeout=20)


def clean_text(value: str) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def text_matches_noise(text: str) -> bool:
    if len(text) < 2:
        return True
    return any(term in text for term in SKIP_TITLE_TERMS)


def seems_company_text(text: str) -> bool:
    if not text:
        return False
    if len(text) > 80:
        return False
    if any(term in text for term in JOBBOX_COMPANY_STOP_WORDS):
        return False
    digits = sum(ch.isdigit() for ch in text)
    if digits >= 3:
        return False
    return any(token in text for token in ["株式会社", "有限会社", "合同会社", "Inc", "LLC", "Corp", "Group", "店", "会", "社"])


def same_domain(base_url: str, target_href: str) -> bool:
    if not target_href:
        return False
    base = urlparse(base_url)
    target = urlparse(target_href)
    if not target.netloc:
        return True
    return target.netloc == base.netloc


def extract_label_value(container: Tag, labels: List[str]) -> Optional[str]:
    for label in labels:
        label_node = container.find(string=lambda s: s and label in clean_text(str(s)))
        if not label_node:
            continue
        parent = label_node.parent if isinstance(label_node.parent, Tag) else None
        if not parent:
            continue
        sibling_texts = []
        for sibling in parent.next_siblings:
            if isinstance(sibling, Tag):
                text = clean_text(sibling.get_text(" ", strip=True))
            else:
                text = clean_text(str(sibling))
            if text:
                sibling_texts.append(text)
            if sibling_texts:
                break
        if sibling_texts:
            return sibling_texts[0]

        parent_text = clean_text(parent.get_text(" ", strip=True))
        for prefix in (f"{label}:", f"{label}：", label):
            if prefix in parent_text:
                value = clean_text(parent_text.split(prefix, 1)[-1])
                if value and value != label:
                    return value
    return None


def extract_company(container: Tag) -> tuple[str, str]:
    for selector in COMPANY_SELECTORS:
        node = container.select_one(selector)
        if not node:
            continue
        text = clean_text(node.get_text(" ", strip=True))
        if not text:
            continue
        if "publisher" in selector or "掲載" in text or "投稿" in text:
            return text, "发布企业"
        return text, "招聘企业"

    recruiter = extract_label_value(container, RECRUITER_LABELS)
    if recruiter:
        return recruiter, "招聘企业"

    publisher = extract_label_value(container, PUBLISHER_LABELS)
    if publisher:
        return publisher, "发布企业"

    text = clean_text(container.get_text(" ", strip=True))
    for label in RECRUITER_LABELS:
        if label in text:
            remainder = clean_text(text.split(label, 1)[-1].lstrip(":："))
            if remainder:
                return remainder.split(" ")[0], "招聘企业"
    for label in PUBLISHER_LABELS:
        if label in text:
            remainder = clean_text(text.split(label, 1)[-1].lstrip(":："))
            if remainder:
                return remainder.split(" ")[0], "发布企业"
    return "", ""


def split_jobbox_title(raw_title: str) -> tuple[str, str]:
    parts = [clean_text(part) for part in raw_title.split("｜") if clean_text(part)]
    if len(parts) >= 2:
        return parts[-1], parts[0]
    return raw_title, ""


def normalize_jobbox_title(title: str) -> str:
    normalized = clean_text(title)
    normalized = normalized.removesuffix(" 新着")
    normalized = normalized.removesuffix("新着")
    return clean_text(normalized)


def is_jobbox_job_link(tag: Tag) -> bool:
    if tag.name != "a":
        return False
    href = tag.get("href", "")
    if not href:
        return False
    return "/jb/" in href or "/rd/?" in href


def looks_like_jobbox_metadata(line: str) -> bool:
    if not line:
        return False
    return any(marker in line for marker in JOBBOX_METADATA_MARKERS)


def should_ignore_jobbox_line(line: str) -> bool:
    if not line:
        return True
    if any(marker in line for marker in JOBBOX_IGNORED_LINES):
        return True
    if line.startswith("-") and any(ch.isdigit() for ch in line):
        return True
    return False


def collect_jobbox_following_lines(link: Tag) -> List[str]:
    lines: List[str] = []
    for element in link.next_elements:
        if isinstance(element, Tag) and element is not link and is_jobbox_job_link(element):
            break
        if isinstance(element, Tag):
            continue
        text = clean_text(str(element))
        if not text:
            continue
        if lines and lines[-1] == text:
            continue
        lines.append(text)
        if len(lines) >= 20:
            break
    return lines


def has_jobbox_card_metadata(lines: List[str]) -> bool:
    return any(looks_like_jobbox_metadata(line) for line in lines[:10])


def extract_jobbox_company_from_lines(lines: List[str], title: str) -> tuple[str, str]:
    for line in lines[:8]:
        if should_ignore_jobbox_line(line):
            continue
        if clean_text(line) == clean_text(title):
            continue
        if line.startswith("掲載元"):
            return line.replace("掲載元", "").lstrip(":： "), "发布企业"
        if line.startswith("掲載企業"):
            return line.replace("掲載企業", "").lstrip(":： "), "发布企业"
        if looks_like_jobbox_metadata(line):
            continue
        if seems_company_text(line):
            return line, "招聘企业"

    for line in lines[:12]:
        for label in PUBLISHER_LABELS:
            if line.startswith(label):
                return line.replace(label, "", 1).lstrip(":： "), "发布企业"
    return "", ""


def parse_jobbox_detail_company(page_html: str) -> tuple[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    lines = [clean_text(line) for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]

    section_indices = [index for index, line in enumerate(lines) if "掲載企業情報" in line]
    stop_markers = ["本社所在地", "事業内容・業種", "企業ホームページ", "応募資格", "仕事内容"]

    for start_index in section_indices:
        for line in lines[start_index + 1 : start_index + 12]:
            if should_ignore_jobbox_line(line):
                continue
            if line == "非公開":
                continue
            if any(marker in line for marker in stop_markers):
                break
            if looks_like_jobbox_metadata(line):
                continue
            if len(line) <= 80:
                return line, "掲載企業"

    return "", ""


def parse_jobbox_detail_recruiter(page_html: str, job_title: str) -> tuple[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")
    lines = [clean_text(line) for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    normalized_title = normalize_match_text(normalize_jobbox_title(job_title))
    title_hint = normalized_title[:20]

    for index, line in enumerate(lines[:80]):
        if not title_hint:
            break
        if title_hint not in normalize_match_text(normalize_jobbox_title(line)):
            continue
        for candidate in reversed(lines[max(0, index - 3) : index]):
            normalized_candidate = clean_text(candidate.rstrip("-").rstrip("|"))
            if not normalized_candidate:
                continue
            if should_ignore_jobbox_line(normalized_candidate):
                continue
            if normalize_match_text(normalized_candidate) == normalized_title:
                continue
            if seems_detail_company_text(normalized_candidate):
                return normalized_candidate, ""

    page_title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    normalized_page_title = normalize_match_text(page_title)
    if page_title and normalized_title and normalized_title in normalized_page_title:
        candidate = clean_text(page_title[: normalized_page_title.index(normalized_title)].rstrip("-｜|"))
        if candidate and seems_detail_company_text(candidate):
            return candidate, ""

    return "", ""


def should_lookup_detail_company(record: JobRecord) -> bool:
    return not record.company_name and bool(record.source_url)


def enrich_jobbox_records_with_detail(driver: Chrome, records: List[JobRecord], wait_seconds: int) -> List[JobRecord]:
    for record in records:
        if not should_lookup_detail_company(record):
            continue
        try:
            driver.get(record.source_url)
            wait_ready(driver, timeout=20)
            time.sleep(max(wait_seconds, 0))
            company_name, company_type = parse_jobbox_detail_recruiter(driver.page_source, record.title)
            if not company_name:
                company_name, company_type = parse_jobbox_detail_company(driver.page_source)
            # 一覧で取得した求人企業を詳細ページの掲載企業で上書きしない。
            if company_name and not record.company_name:
                record.company_name = company_name
                record.company_type = company_type
        except Exception:
            continue
    return records


def extract_jobbox_records(page_html: str, keyword: str, source_url: str) -> List[JobRecord]:
    soup = BeautifulSoup(page_html, "html.parser")
    records: List[JobRecord] = []
    seen_keys = set()

    for link in soup.find_all(is_jobbox_job_link):
        raw_title = clean_text(link.get_text(" ", strip=True))
        if not raw_title or text_matches_noise(raw_title):
            continue

        detail_url = urljoin(source_url, link.get("href", ""))

        following_lines = collect_jobbox_following_lines(link)
        if not has_jobbox_card_metadata(following_lines):
            continue

        normalized_title, title_company = split_jobbox_title(normalize_jobbox_title(raw_title))
        company_name = ""
        company_type = ""

        if title_company:
            company_name = title_company
            company_type = ""
        else:
            company_name, company_type = extract_jobbox_company_from_lines(following_lines, normalized_title)

        record_key = detail_url or normalized_title
        if record_key in seen_keys:
            continue
        seen_keys.add(record_key)
        records.append(
            JobRecord(
                keyword=keyword,
                title=normalized_title,
                company_name=company_name,
                company_type=normalize_company_type(company_type),
                source_url=detail_url,
            )
        )

    return records


def extract_title(container: Tag, base_url: str) -> Optional[str]:
    for selector in TITLE_SELECTORS:
        for node in container.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if not text or text_matches_noise(text):
                continue
            if node.name == "a":
                href = node.get("href", "")
                if href and not same_domain(base_url, href):
                    continue
            return text
    return None


def iter_candidate_containers(soup: BeautifulSoup) -> Iterable[Tag]:
    seen = set()
    for selector in RESULT_CONTAINER_SELECTORS:
        for node in soup.select(selector):
            if not isinstance(node, Tag):
                continue
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            yield node


def extract_records(page_html: str, keyword: str, source_url: str) -> List[JobRecord]:
    if is_jobbox_url(source_url):
        return extract_jobbox_records(page_html, keyword, source_url)

    soup = BeautifulSoup(page_html, "html.parser")
    records: List[JobRecord] = []
    seen_keys = set()

    for container in iter_candidate_containers(soup):
        title = extract_title(container, source_url)
        if not title:
            continue
        company_name, company_type = extract_company(container)
        if not company_name:
            continue
        record_key = (title, company_name, company_type)
        if record_key in seen_keys:
            continue
        seen_keys.add(record_key)
        records.append(
            JobRecord(
                keyword=keyword,
                title=title,
                company_name=company_name,
                company_type=normalize_company_type(company_type),
                source_url=source_url,
            )
        )

    return records


def merge_records(records: List[JobRecord], new_records: List[JobRecord]) -> List[JobRecord]:
    merged = list(records)
    seen = {record.source_url or record.title for record in merged}
    for record in new_records:
        key = record.source_url or record.title
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)
    return merged


def limit_records(records: List[JobRecord], max_results: int) -> List[JobRecord]:
    if max_results <= 0:
        return records
    return records[:max_results]


def record_identity(record: JobRecord) -> str:
    return record.source_url or record.title


def click_next_page(driver: Chrome) -> bool:
    try:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for link in soup.find_all("a", href=True):
            text = clean_text(link.get_text(" ", strip=True))
            href = link.get("href", "")
            if "次のページへ" in text or "次へ" in text:
                driver.get(urljoin(driver.current_url, href))
                wait_ready(driver, timeout=20)
                return True
            if href and "pg=" in href and ("前のページ" not in text):
                driver.get(urljoin(driver.current_url, href))
                wait_ready(driver, timeout=20)
                return True
    except Exception:
        pass

    candidates = [
        "//a[contains(normalize-space(.), '次のページへ')]",
        "//a[contains(., '次へ')]",
        "//a[@rel='next']",
        "//a[contains(@href, 'pg=')]",
        "//button[contains(., '次へ')]",
    ]
    for xpath in candidates:
        try:
            button = WebDriverWait(driver, 3).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
            href = button.get_attribute("href")
            if href:
                driver.get(urljoin(driver.current_url, href))
            else:
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                driver.execute_script("arguments[0].click();", button)
            wait_ready(driver, timeout=20)
            return True
        except Exception:
            continue
    return False


def print_records(records: List[JobRecord]) -> None:
    if not records:
        print("抽出結果がありません。このサイトは追加の専用調整が必要な可能性があります。")
        return

    print("\n抽出結果:")
    for index, record in enumerate(records, start=1):
        print_record(index, record)


def print_record(index: int, record: JobRecord) -> None:
    suffix = f" | 種別={record.company_type}" if record.company_type else ""
    print(f"{index}. キーワード={record.keyword} | タイトル={record.title} | 企業名={record.company_name}{suffix}", flush=True)


def write_csv(records: List[JobRecord], output_path: str) -> None:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["キーワード", "タイトル", "企業名", "企業種別", "URL"],
        )
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "キーワード": record.keyword,
                    "タイトル": record.title,
                    "企業名": record.company_name,
                    "企業種別": record.company_type,
                    "URL": record.source_url,
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="対話式の求人サイト抽出")
    parser.add_argument("--url", help="求人サイトの URL")
    parser.add_argument("--keyword", help="サイト内検索キーワード（複数入力時は , / 、 / or に対応）")
    parser.add_argument("--wait-seconds", type=int, default=2, help="検索後の追加待機秒数")
    parser.add_argument("--max-pages", type=int, default=0, help="取得する最大ページ数（0 は無制限）")
    parser.add_argument("--max-results", type=int, default=0, help="取得する最大件数（0 は無制限）")
    parser.add_argument("--headless", action="store_true", help="ヘッドレスモードを使用する")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    url = (args.url or DEFAULT_TARGET_URL).strip()
    keyword = prompt_if_empty(args.keyword, "サイト内検索キーワードを入力してください（複数指定は , / 、 / or）")
    if not url or not keyword:
        print("URL とキーワードは必須です。")
        return 1

    keyword = normalize_search_keyword(keyword)

    driver = build_driver(headless=args.headless)
    detail_driver = build_driver(headless=True) if is_jobbox_url(url) else None
    try:
        print(f"ページを開いています: {url}")
        driver.get(url)
        wait_ready(driver, timeout=20)

        search_done = False
        try:
            search_done = perform_keyword_search(driver, keyword)
        except TimeoutException:
            search_done = False

        if not search_done:
            if is_jobbox_url(driver.current_url) and page_has_jobbox_results(driver):
                pass
            else:
                manual_continue_if_needed(driver, "検索入力欄を自動で特定できませんでした。")
        else:
            time.sleep(max(args.wait_seconds, 0))
            if is_jobbox_url(driver.current_url):
                wait_for_results(driver, timeout=20)

        records: List[JobRecord] = []
        printed_record_keys = set()
        has_printed_results = False
        pages_done = 0
        target_count = max(args.max_results, 0)
        page_limit = max(args.max_pages, 0)
        while True:
            page_html = driver.page_source
            current_url = driver.current_url
            page_records = extract_records(page_html, keyword, current_url)
            if page_records and detail_driver and is_jobbox_url(current_url):
                page_records = enrich_jobbox_records_with_detail(detail_driver, page_records, args.wait_seconds)

            merged_records = merge_records(records, page_records)
            if target_count:
                merged_records = limit_records(merged_records, target_count)

            new_records_to_print = [
                record for record in merged_records if record_identity(record) not in printed_record_keys
            ]
            if new_records_to_print and not has_printed_results:
                print("\n抽出結果:")
                has_printed_results = True
            for record in new_records_to_print:
                printed_record_keys.add(record_identity(record))
                print_record(len(printed_record_keys), record)

            records = merged_records
            pages_done += 1
            if target_count and len(records) >= target_count:
                break
            if page_limit and pages_done >= page_limit:
                break
            if not click_next_page(driver):
                break
            time.sleep(max(args.wait_seconds, 0))

        if not records:
            print_records(records)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "logs",
            f"job_search_{timestamp}.csv",
        )
        write_csv(records, os.path.abspath(output_path))
        print(f"\nCSV を出力しました: {os.path.abspath(output_path)}")

        if not records:
            print("\n対象サイトが分かれば、専用セレクタに寄せて精度をさらに上げられます。")
        return 0
    finally:
        driver.quit()
        if detail_driver:
            detail_driver.quit()


if __name__ == "__main__":
    sys.exit(main())