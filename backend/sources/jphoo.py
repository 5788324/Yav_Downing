"""JPHOO 来源适配器：独立 Edge 资料目录、HTTP/浏览器分页与安全磁链归属。"""
from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .javdb import SourceMovie, size_bytes

_NOISE = {"mp4", "mkv", "avi", "mov", "hevc", "x264", "x265", "h264", "h265", "web", "xxx", "gb", "mb", "kb", "480p", "720p", "1080p", "2160p", "磁力下载链接"}


@dataclass(frozen=True)
class JphooCandidate:
    magnet: str
    size_bytes: int | None = None
    title: str = ""


class LoginRequired(RuntimeError):
    pass


def normalize_jphoo_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = re.sub(r"\s*-\s*(?:jphoo|磁力下载链接).*$", "", text)
    text = re.sub(r"\b(?:480p|720p|1080p|2160p|4320p|x264|x265|h264|h265|hevc|mp4|mkv|avi|mov)\b", "", text)
    return re.sub(r"[^\w]+", " ", text).strip()


def title_tokens(value: str) -> set[str]:
    return {item for item in normalize_jphoo_title(value).split() if len(item) > 1 and item not in _NOISE and not item.isdigit()}


def _video_code(value: str) -> str:
    hit = re.search(r"\b([a-z]{2,})\s*[-_. ]\s*(\d{2,})\b", normalize_jphoo_title(value), re.I)
    return f"{hit.group(1)}-{hit.group(2)}".upper() if hit else ""


def classify_magnet_candidate(current_title: str, candidate_title: str) -> str:
    """宁可 unknown，也不以短词或数字把同日资源归错。"""
    current_clean, candidate_clean = normalize_jphoo_title(current_title), normalize_jphoo_title(candidate_title)
    if not current_clean or not candidate_clean:
        return "unknown"
    current_code, candidate_code = _video_code(current_title), _video_code(candidate_title)
    if current_code and candidate_code:
        return "current" if current_code == candidate_code else "other"
    if current_clean == candidate_clean or (min(len(current_clean), len(candidate_clean)) >= 8 and (current_clean in candidate_clean or candidate_clean in current_clean)):
        return "current"
    current, candidate = title_tokens(current_title), title_tokens(candidate_title)
    if len(current & candidate) >= 2:
        return "current"
    return "other" if candidate_code else "unknown"


def api_candidates(payload) -> list[JphooCandidate]:
    """只从明确标题字段读取标题；infoHash 只用于构造 BTIH。"""
    found: list[JphooCandidate] = []
    title_keys = ("name", "title", "videoTitle", "workTitle", "fileName", "filename")
    def walk(value):
        if isinstance(value, dict):
            explicit_title = next((value[key] for key in title_keys if value.get(key)), "")
            title = BeautifulSoup(str(explicit_title), "lxml").get_text(" ", strip=True)
            numeric_length = value.get("length") or value.get("size_bytes") or value.get("size")
            raw_bytes = int(numeric_length) if str(numeric_length or "").isdigit() else 0
            record_size = raw_bytes or size_bytes(str(numeric_length or "")) or size_bytes(title)
            magnets = [str(item) for item in value.values() if isinstance(item, str) and item.startswith("magnet:")]
            found.extend(JphooCandidate(magnet, record_size, title) for magnet in magnets)
            info_hash = str(value.get("infoHash") or value.get("info_hash") or "").strip()
            if re.fullmatch(r"[A-Za-z0-9]{32,64}", info_hash) and not magnets:
                magnet = f"magnet:?xt=urn:btih:{info_hash.upper()}" + (f"&dn={quote(title)}" if title else "")
                found.append(JphooCandidate(magnet, record_size, title))
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(payload)
    best: dict[str, JphooCandidate] = {}
    for item in found:
        if item.magnet not in best or (item.size_bytes or 0) > (best[item.magnet].size_bytes or 0): best[item.magnet] = item
    return list(best.values())

def series_links_from_html(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    return list(dict.fromkeys(urljoin(base_url, node.get("href", "").split("?")[0]) for node in soup.select('a[href^="/works/"]') if node.get("href")))


def parse_movie_html(html: str, url: str) -> SourceMovie:
    soup = BeautifulSoup(html or "", "lxml")
    title_node = soup.select_one('meta[property="og:title"]') or soup.title
    title = title_node.get("content", "") if title_node and title_node.has_attr("content") else title_node.get_text(" ", strip=True) if title_node else ""
    title = re.split(r"\s*-\s*(?:JPHOO|磁力下载链接).*$", title, flags=re.I)[0].strip()
    cover = soup.select_one('meta[property="og:image"], .video-cover img, .cover img, main img[src]')
    cover_url = urljoin(url, (cover.get("content") or cover.get("src", ""))) if cover else ""
    text = " ".join(soup.stripped_strings)
    def first(selector):
        node = soup.select_one(selector); return node.get_text(" ", strip=True) if node else ""
    date = re.search(r"(?:發行日期|发行日期|日期)\s*[:：]?\s*(\d{4}[./-]\d{1,2}[./-]\d{1,2})", text)
    duration = re.search(r"(?:長度|长度|時長|时长)\s*[:：]?\s*(\d+)", text)
    actresses = [node.get_text(" ", strip=True) for node in soup.select('a[href*="actor"],a[href*="actress"]') if node.get_text(strip=True)]
    return SourceMovie(title=title, source_url=url, cover_url=cover_url, studio=first('a[href*="studio"],a[href*="maker"],a[href*="publisher"]'), series=first('a[href*="series"],a[href*="tag"]'), release_date=date.group(1).replace("/", "-").replace(".", "-") if date else "", duration_minutes=int(duration.group(1)) if duration else None, actresses=list(dict.fromkeys(actresses)))


class JphooBrowser:
    def __init__(self, profile_dir: str | Path):
        self.profile_dir = str(profile_dir); self.playwright = self.context = self.page = None
    def open(self):
        from playwright.sync_api import sync_playwright
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(self.profile_dir, channel="msedge", headless=False)
        # 必须在作品页导航前安装，页面脚本会缓存 clipboard.writeText 引用。
        self.context.add_init_script("""(() => { window.__yavCopiedMagnets=[]; try { const c=navigator.clipboard; if(c&&c.writeText){Object.defineProperty(c, "writeText", {configurable:true, value: async value => {if(typeof value==="string"&&value.startsWith("magnet:")) window.__yavCopiedMagnets.push(value); return undefined;}});} } catch (_) {} })();""")
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self.page
    def close(self):
        try:
            if self.context: self.context.close()
        finally:
            if self.playwright: self.playwright.stop()
            self.playwright = self.context = self.page = None
    def login_required(self):
        return bool(self.page and (self.page.locator('input[type="password"]').count() or "/login" in (self.page.url or "").lower()))


class JphooSource:
    name = "jphoo"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

    def __init__(self, browser: JphooBrowser | None = None, session=None, delay=0.7):
        self.browser, self.session, self.delay = browser, session or requests.Session(), delay
    def open_browser(self, profile_dir):
        self.browser = JphooBrowser(profile_dir); return self.browser.open()
    def close(self):
        if self.browser: self.browser.close()
    def _http_links(self, url):
        try:
            response = self.session.get(url, headers=self.headers, timeout=20); response.raise_for_status()
            return series_links_from_html(response.text, url)
        except requests.RequestException:
            return None
    def scan_series(self, url, *, start_page=1, stop_event: Event | None = None):
        number, empty = start_page, 0
        while not (stop_event and stop_event.is_set()) and empty < 2:
            target = url if number == 1 else url + ("&" if "?" in url else "?") + f"pageNum={number}"
            links = self._http_links(target)
            if links is None:
                if not self.browser or not self.browser.page: raise LoginRequired("JPHOO 列表需要打开浏览器")
                self.browser.page.goto(target, wait_until="domcontentloaded", timeout=45000); self.browser.page.wait_for_timeout(1200)
                if self.browser.login_required(): raise LoginRequired("JPHOO 需要重新登录")
                links = series_links_from_html(self.browser.page.content(), target)
            empty = empty + 1 if not links else 0
            if links: yield number, links
            number += 1
            if self.delay: time.sleep(self.delay)
    def fetch_movie(self, url):
        if not self.browser or not self.browser.page: raise LoginRequired("JPHOO 浏览器尚未打开")
        page = self.browser.page; page.goto(url, wait_until="domcontentloaded", timeout=45000); page.wait_for_timeout(1000)
        if self.browser.login_required(): raise LoginRequired("JPHOO 需要重新登录")
        return parse_movie_html(page.content(), url)
    @staticmethod
    def _dom_candidates(page):
        items = []
        for node in page.locator('a[href^="magnet:"]').all():
            label = node.inner_text()
            try: label = node.evaluate("el => (el.closest('li,.q-card,.q-item') || el.parentElement || el).innerText || ''")
            except Exception: pass
            items.append(JphooCandidate(node.get_attribute("href") or "", size_bytes(label), label))
        return items
    def fetch_magnet_candidates(self):
        """同一作品页中：接口响应、弹窗 DOM、复制按钮三层回退。"""
        if not self.browser or not self.browser.page: return []
        page = self.browser.page
        direct = self._dom_candidates(page)
        if direct: return direct
        captured: list[JphooCandidate] = []
        def receive(response):
            if "/prod-api/v2/dht/list" in response.url:
                try: captured.extend(api_candidates(response.json()))
                except Exception: pass
        page.evaluate("""(() => { window.__yavCopiedMagnets=[]; const c=navigator.clipboard; if(c&&c.writeText&&!c.__yavHooked){c.writeText=async v=>{if(typeof v==='string'&&v.startsWith('magnet:'))window.__yavCopiedMagnets.push(v); return undefined;}; c.__yavHooked=true;}})();""")
        page.on("response", receive)
        try:
            button = None
            for _ in range(24):
                role = page.get_by_role("button", name=re.compile("磁力下载链接"))
                css = page.locator('button:has-text("磁力下载链接"), .q-btn:has-text("磁力下载链接"), [role="button"]:has-text("磁力下载链接")')
                if role.count(): button = role.first; break
                if css.count(): button = css.first; break
                page.wait_for_timeout(500)
            if button is None: return []
            button.click(); page.wait_for_timeout(500)
            if self.browser.login_required(): raise LoginRequired("JPHOO 需要重新登录")
            for _ in range(20):
                page.wait_for_timeout(400)
                if captured:
                    unique = {item.magnet: item for item in captured}
                    return list(unique.values())
                dom = self._dom_candidates(page)
                if dom: return dom
            labels = []
            for node in page.locator('.q-chip:has-text("复制磁力"), button:has-text("复制磁力")').all():
                try:
                    labels.append(node.evaluate("el => (el.closest('li,.q-card,.q-item') || el.parentElement || el).innerText || ''")); node.click(force=True)
                except Exception: labels.append("")
            page.wait_for_timeout(300)
            copied = page.evaluate("window.__yavCopiedMagnets || []") or []
            return [JphooCandidate(value, size_bytes(labels[index] if index < len(labels) else ""), labels[index] if index < len(labels) else "") for index, value in enumerate(copied) if str(value).startswith("magnet:")]
        finally:
            page.remove_listener("response", receive)

def persist_candidates(database, current_movie_id: int, current_title: str, source_url: str, candidates: list[JphooCandidate]) -> dict[str, int]:
    from backend.db import extract_btih, is_invalid_metadata
    result = {"matched_current": 0, "attached_other": 0, "unmatched": 0, "new_magnets": 0, "new_source_links": 0}
    seen: set[str] = set()
    for candidate in candidates:
        try: identity = extract_btih(candidate.magnet)
        except ValueError: result["unmatched"] += 1; continue
        if identity in seen: continue
        seen.add(identity); kind = classify_magnet_candidate(current_title, candidate.title)
        if kind == "unknown": result["unmatched"] += 1; continue
        movie_id, entry_url = current_movie_id, source_url
        if kind == "other":
            raw_title = re.sub(r"\s+", " ", candidate.title or "").strip()[:300]
            if not raw_title or raw_title.startswith("magnet:") or is_invalid_metadata(raw_title): result["unmatched"] += 1; continue
            entry_url = f"{source_url}#magnet-{identity}"
            movie_id = database.add_or_update_movie(raw_title, source="jphoo", source_url=entry_url, source_movie_id=identity)
            result["attached_other"] += 1
        else:
            result["matched_current"] += 1
        saved = database.add_magnet(movie_id, candidate.magnet, "jphoo", entry_url, candidate.size_bytes)
        result["new_magnets"] += int(saved.created)
        result["new_source_links"] += int(saved.source_added)
    return result
