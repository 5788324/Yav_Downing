"""JPHOO 来源适配器：单一 Edge 会话、严格候选归属和磁链提取。"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .javdb import SourceMovie, size_bytes

NOISE = {"mp4", "mkv", "avi", "mov", "hevc", "x264", "x265", "h264", "h265", "web", "xxx", "gb", "mb", "kb", "480p", "720p", "1080p", "2160p", "磁力下载链接"}

@dataclass
class JphooCandidate:
    magnet: str
    size_bytes: int | None = None
    title: str = ""

class LoginRequired(RuntimeError):
    pass

def normalize_jphoo_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"\s*-\s*磁力下载链接.*$", "", text)
    text = re.sub(r"\b(?:480p|720p|1080p|2160p|x264|x265|h264|h265|hevc|mp4|mkv|avi|mov)\b", "", text)
    return re.sub(r"[^\w]+", " ", text).strip()

def title_tokens(value: str) -> set[str]:
    return {item for item in normalize_jphoo_title(value).split() if len(item) > 1 and item not in NOISE and not item.isdigit()}

def classify_magnet_candidate(current_title: str, candidate_title: str) -> str:
    """只把明确匹配的候选归当前片；其余有可靠标题的候选单独入库。"""
    current, candidate = title_tokens(current_title), title_tokens(candidate_title)
    if not candidate:
        return "unknown"
    overlap = len(current & candidate)
    if overlap >= (2 if len(current) >= 2 else 1):
        return "current"
    # 影片番号通常含数字；没有与当前片重叠、且无番号的普通文件名不能安全归属。
    has_identifier = bool(re.search(r"[a-z]+[-_ ]?\d{2,}", normalize_jphoo_title(candidate_title), re.I))
    return "other" if has_identifier else "unknown"

def api_candidates(payload) -> list[JphooCandidate]:
    found: list[JphooCandidate] = []
    def walk(value):
        if isinstance(value, dict):
            values = [str(item) for item in value.values() if isinstance(item, (str, int, float))]
            label = " ".join(values)
            found.extend(JphooCandidate(item, max((size_bytes(v) or 0 for v in values), default=0) or None, label) for item in values if item.startswith("magnet:"))
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(payload)
    unique: dict[str, JphooCandidate] = {}
    for item in found:
        if item.magnet not in unique or (item.size_bytes or 0) > (unique[item.magnet].size_bytes or 0): unique[item.magnet] = item
    return list(unique.values())

def series_links_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    return list(dict.fromkeys(urljoin(base_url, item.get("href", "").split("?")[0]) for item in soup.select('a[href^="/works/"]') if item.get("href")))

class JphooBrowser:
    def __init__(self, profile_dir: str | Path):
        self.profile_dir = str(profile_dir); self.playwright = self.context = self.page = None
    def open(self):
        from playwright.sync_api import sync_playwright
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(self.profile_dir, channel="msedge", headless=False)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page
    def close(self):
        if self.context: self.context.close()
        if self.playwright: self.playwright.stop()
        self.playwright = self.context = self.page = None
    def login_required(self):
        return bool(self.page and (self.page.locator('input[type="password"]').count() or "login" in (self.page.url or "").lower()))

class JphooSource:
    name = "jphoo"
    def __init__(self, browser: JphooBrowser | None = None): self.browser = browser
    def open_browser(self, profile_dir):
        self.browser = JphooBrowser(profile_dir); return self.browser.open()
    def close(self):
        if self.browser: self.browser.close()
    def scan_series(self, url, *, start_page=1, stop_event: Event | None = None):
        if not self.browser or not self.browser.page: raise LoginRequired("请先打开 JPHOO 登录窗口")
        number, empty = start_page, 0
        while not (stop_event and stop_event.is_set()) and empty < 2:
            target = url + ("&" if "?" in url else "?") + f"pageNum={number}" if number > 1 else url
            self.browser.page.goto(target, wait_until="domcontentloaded", timeout=45000); self.browser.page.wait_for_timeout(1200)
            if self.browser.login_required(): raise LoginRequired("JPHOO 需要手动登录")
            links = series_links_from_html(self.browser.page.content(), target)
            empty = empty + 1 if not links else 0
            if links: yield number, links
            number += 1
    def fetch_movie(self, url):
        if not self.browser or not self.browser.page: raise LoginRequired("JPHOO 浏览器尚未打开")
        page = self.browser.page; page.goto(url, wait_until="domcontentloaded", timeout=45000); page.wait_for_timeout(1000)
        if self.browser.login_required(): raise LoginRequired("JPHOO 需要手动登录")
        soup = BeautifulSoup(page.content(), "lxml")
        title = (soup.select_one('meta[property="og:title"]') or soup.title)
        title = (title.get("content") if title and title.has_attr("content") else title.get_text(" ", strip=True) if title else "")
        title = re.split(r"\s*-\s*(?:JPHOO|磁力下载链接).*$", title, flags=re.I)[0].strip()
        cover = soup.select_one('meta[property="og:image"], .video-cover img, .cover img, main img[src]')
        cover_url = urljoin(url, (cover.get("content") or cover.get("src", ""))) if cover else ""
        text = " ".join(soup.stripped_strings)
        date = re.search(r"(?:發行日期|发行日期|日期)\s*[:：]?\s*(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text)
        duration = re.search(r"(?:長度|长度|時長|时长)\s*[:：]?\s*(\d+)", text)
        actresses = [item.get_text(" ", strip=True) for item in soup.select('a[href*="actor"],a[href*="actress"]') if item.get_text(strip=True)]
        return SourceMovie(title=title, source_url=url, cover_url=cover_url, release_date=date.group(1).replace("/", "-").replace(".", "-") if date else "", duration_minutes=int(duration.group(1)) if duration else None, actresses=list(dict.fromkeys(actresses)))
    def fetch_magnet_candidates(self):
        if not self.browser or not self.browser.page: return []
        page = self.browser.page
        direct = [JphooCandidate(item.get_attribute("href") or "", size_bytes(item.inner_text()), item.inner_text()) for item in page.locator('a[href^="magnet:"]').all()]
        if direct: return direct
        captured = []
        def receive(response):
            if "/prod-api/v2/dht/list" in response.url:
                try: captured.extend(api_candidates(response.json()))
                except Exception: pass
        page.on("response", receive)
        try:
            button = page.get_by_role("button", name=re.compile("磁力下载链接"))
            if not button.count(): return []
            button.first.click(); page.wait_for_timeout(1200)
            if self.browser.login_required():
                # 只使用本应用专用持久资料目录；给用户手动登录机会，不读取 Cookie。
                page.bring_to_front()
                for _ in range(120):
                    page.wait_for_timeout(1000)
                    if not self.browser.login_required(): break
                if self.browser.login_required(): raise LoginRequired("JPHOO 登录未完成")
                button = page.get_by_role("button", name=re.compile("磁力下载链接"))
                if not button.count(): raise LoginRequired("登录后未找到磁力下载入口")
                button.first.click(); page.wait_for_timeout(1200)
            if captured: return captured
            return [JphooCandidate(item.get_attribute("href") or "", size_bytes(item.inner_text()), item.inner_text()) for item in page.locator('a[href^="magnet:"]').all()]
        finally:
            page.remove_listener("response", receive)

def persist_candidates(database, current_movie_id: int, current_title: str, source_url: str, candidates: list[JphooCandidate]) -> dict[str, int]:
    """保存候选：当前片可归属，其他片独立建立来源记录，未知绝不挂接。"""
    from . import __name__ as _unused  # 保持此模块无数据库循环依赖
    from backend.db import extract_btih
    result = {"matched_current": 0, "attached_other": 0, "unmatched": 0, "new_magnets": 0}
    seen: set[str] = set()
    for candidate in candidates:
        try: identity = extract_btih(candidate.magnet)
        except ValueError: result["unmatched"] += 1; continue
        if identity in seen: continue
        seen.add(identity); kind = classify_magnet_candidate(current_title, candidate.title)
        if kind == "unknown": result["unmatched"] += 1; continue
        movie_id, entry_url = current_movie_id, source_url
        if kind == "other":
            title = re.sub(r"\s+", " ", candidate.title or "").strip()[:300]
            if not title: result["unmatched"] += 1; continue
            entry_url = f"{source_url}#magnet-{identity}"
            movie_id = database.add_or_update_movie(title, source="jphoo", source_url=entry_url, source_movie_id=identity)
            result["attached_other"] += 1
        else: result["matched_current"] += 1
        before = database.get_movie(movie_id) or {}; old = {item["btih"] for item in before.get("magnets", [])}
        database.add_magnet(movie_id, candidate.magnet, "jphoo", entry_url, candidate.size_bytes)
        result["new_magnets"] += int(identity not in old)
    return result
