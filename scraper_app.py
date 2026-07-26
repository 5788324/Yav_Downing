import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import urllib.parse
import os
import sys
import re
import json
import csv
import time
import requests
from bs4 import BeautifulSoup
from library_store import LibraryStore, WorkMetadata, parse_public_metadata
from library_ui import LibraryWindow

# Playwright only needed for jphoo.net
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ms-playwright"
)

PROJECT_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = os.path.join(PROJECT_DIR, "目录")
CONFIG_FILE = os.path.join(PROJECT_DIR, "scraper_config.json")

# ─── Config ───────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "sources": [],
    "browser_mode": True,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "sources" not in cfg:
                cfg["sources"] = []
            if "browser_mode" not in cfg:
                cfg["browser_mode"] = True
            return cfg
        except:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except:
        pass

# ─── File helpers ─────────────────────────────────────────────────────────

def load_history(save_dir):
    history = set()
    hfile = os.path.join(save_dir, "_抓取历史记录.txt")
    if os.path.exists(hfile):
        with open(hfile, "r", encoding="utf-8") as f:
            for line in f:
                history.add(line.strip())
    return history

def append_history(save_dir, url):
    hfile = os.path.join(save_dir, "_抓取历史记录.txt")
    with open(hfile, "a", encoding="utf-8") as f:
        f.write(url + "\n")

def init_csv(save_dir):
    cfile = os.path.join(save_dir, "_全部磁力汇总表.csv")
    if not os.path.exists(cfile):
        with open(cfile, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["番号/ID", "影片名", "文件大小(GB)", "磁力链接", "网页地址"])

def append_csv(save_dir, vid_id, vid_name, size_gb, magnet, url):
    cfile = os.path.join(save_dir, "_全部磁力汇总表.csv")
    with open(cfile, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([vid_id, vid_name, f"{size_gb:.2f}", magnet, url])

def append_csv_placeholder(save_dir, url):
    """为尚无磁力的作品写入 CSV；已存在则不重复。"""
    if url in load_csv_map(save_dir):
        return
    append_csv(save_dir, "", "（暂无磁力，待手动填写）", 0, "", url)

def load_csv_map(save_dir):
    """返回 {url: (vid_id, vid_name, size_gb, magnet)} 的字典"""
    result = {}
    cfile = os.path.join(save_dir, "_全部磁力汇总表.csv")
    if not os.path.exists(cfile):
        return result
    with open(cfile, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 5:
                url = row[4].strip()
                result[url] = {
                    "vid_id": row[0],
                    "vid_name": row[1],
                    "size_gb": float(row[2]) if row[2] else 0,
                    "magnet": row[3],
                }
    return result

def save_magnet_file(save_dir, file_name, magnet):
    safe = "".join([c for c in file_name if c.isalpha() or c.isdigit() or c in " -_[]()"]).rstrip()
    if not safe:
        safe = "unknown"
    path = os.path.join(save_dir, f"{safe}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(magnet)

def rewrite_csv(save_dir, rows):
    cfile = os.path.join(save_dir, "_全部磁力汇总表.csv")
    with open(cfile, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["番号/ID", "影片名", "文件大小(GB)", "磁力链接", "网页地址"])
        for r in rows:
            writer.writerow(r)

def magnet_identity(magnet):
    """返回磁力链接的稳定身份（优先 BTIH 哈希）。"""
    magnet = (magnet or "").strip()
    try:
        for xt in urllib.parse.parse_qs(urllib.parse.urlparse(magnet).query).get("xt", []):
            if xt.lower().startswith("urn:btih:"):
                return xt.lower()
    except Exception:
        pass
    return magnet

def append_update_log(save_dir, source_name, video_url, old_entry, info, reason):
    """记录磁力更新，供 Excel 导出与人工回看。"""
    path = os.path.join(save_dir, "_磁力更新记录.csv")
    is_new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["更新时间", "来源", "影片名", "网页地址", "更新原因", "旧磁力", "新磁力"])
        title = f"{info.vid_id} - {info.vid_name}" if info.vid_id != info.vid_name else info.vid_id
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), source_name, title, video_url, reason,
                         old_entry["magnet"] if old_entry else "", info.magnet])
MASTER_LEDGER_FILE = os.path.join(PROJECT_DIR, "Yav_磁力台账.xlsx")
MASTER_LEDGER_HEADERS = [
    "序号", "站点", "系列", "番号/ID", "影片名", "当前大小(GB)", "网页地址", "状态", "初始磁力",
]


def _safe_sheet_name(source_name):
    """Excel 工作表按系列命名；清理 Excel 不允许的字符，并限制在 31 字符内。"""
    name = re.sub(r'[\\/*?:\[\]]', '_', str(source_name or '未命名系列')).strip()
    return (name or '未命名系列')[:31]


def _ledger_sheet_name(site, source_name):
    # 工作表按“系列”而不是站点分组，便于未来加入任意站点。
    return _safe_sheet_name(source_name or site)


def _ledger_style(sheet):
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    header_fill = PatternFill("solid", fgColor="1D4ED8")
    for cell in sheet[1]:
        cell.fill = header_fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = [8, 12, 18, 28, 34, 14, 42, 16, 58]
    for column, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width
    for column in range(10, sheet.max_column + 1):
        sheet.column_dimensions[get_column_letter(column)].width = 58
    for row in sheet.iter_rows(min_row=2):
        row[0].alignment = Alignment(horizontal="center")
        row[5].alignment = Alignment(horizontal="right")
        row[7].alignment = Alignment(horizontal="center")
        for cell in row:
            cell.alignment = Alignment(vertical="top")


def _open_master_ledger():
    from openpyxl import Workbook, load_workbook
    if os.path.exists(MASTER_LEDGER_FILE):
        return load_workbook(MASTER_LEDGER_FILE)
    workbook = Workbook()
    workbook.remove(workbook.active)
    return workbook


def _get_ledger_sheet(workbook, site, source_name):
    name = _ledger_sheet_name(site, source_name)
    if name not in workbook.sheetnames:
        sheet = workbook.create_sheet(name)
        sheet.append(MASTER_LEDGER_HEADERS)
    sheet = workbook[name]
    # 迁移旧版 8 列格式：在“初始磁力”左侧插入状态列，保留所有既有更新列。
    if sheet.cell(1, 8).value != "状态":
        sheet.insert_cols(8, 1)
        sheet.cell(1, 8).value = "状态"
        for row_number in range(2, sheet.max_row + 1):
            sheet.cell(row_number, 8).value = "已收录"
    _ledger_style(sheet)
    return sheet


def _find_ledger_row(sheet, source_name, video_url):
    for row_number in range(2, sheet.max_row + 1):
        if sheet.cell(row_number, 3).value == source_name and sheet.cell(row_number, 7).value == video_url:
            return row_number
    return None


def _renumber_sheet(sheet):
    for row_number in range(2, sheet.max_row + 1):
        sheet.cell(row_number, 1).value = row_number - 1
    _ledger_style(sheet)


def _sheet_url_index(sheet):
    return {
        sheet.cell(row_number, 7).value: row_number
        for row_number in range(2, sheet.max_row + 1)
        if sheet.cell(row_number, 7).value
    }


def migrate_legacy_site_sheets(workbook):
    """把旧的 JavDB/JPHOO 汇总页拆分成每个系列一个页，保留磁力更新列。"""
    migrated = 0
    target_cache, indexes = {}, {}

    def target_for(site, source_name):
        key = _ledger_sheet_name(site, source_name)
        if key not in target_cache:
            if key not in workbook.sheetnames:
                sheet = workbook.create_sheet(key)
                sheet.append(MASTER_LEDGER_HEADERS)
            else:
                sheet = workbook[key]
            target_cache[key] = sheet
            indexes[key] = _sheet_url_index(sheet)
        return target_cache[key], indexes[key]

    for legacy_name in ("JavDB", "JPHOO"):
        if legacy_name not in workbook.sheetnames:
            continue
        legacy = workbook[legacy_name]
        for values in legacy.iter_rows(min_row=2, values_only=True):
            values = list(values)
            if len(values) < 7 or not values[6]:
                continue
            site = values[1] or legacy_name.lower()
            source_name = values[2] or legacy_name
            target, url_index = target_for(site, source_name)
            existing = url_index.get(values[6])
            if existing is None:
                target.append(values)
                url_index[values[6]] = target.max_row
                migrated += 1
            else:
                for column, value in enumerate(values, start=1):
                    if value not in (None, "") and target.cell(existing, column).value in (None, ""):
                        target.cell(existing, column).value = value
        workbook.remove(legacy)
    for sheet in workbook.worksheets:
        _renumber_sheet(sheet)
    return migrated


def sync_master_ledger(cfg):
    """将各系列 CSV 中尚未出现的影片同步到按系列分表的 Excel 主台账。"""
    workbook = _open_master_ledger()
    migrated = migrate_legacy_site_sheets(workbook)
    added = 0
    for source in cfg.get("sources", []):
        save_dir = source.get("dir", "")
        if not save_dir:
            continue
        os.makedirs(save_dir, exist_ok=True)
        init_csv(save_dir)
        csv_path = os.path.join(save_dir, "_全部磁力汇总表.csv")
        # 每个已配置系列始终保留自己的空表，未来加入任意站点也无需调整总台账结构。
        sheet = _get_ledger_sheet(workbook, source.get("site", ""), source.get("name", ""))
        url_index = _sheet_url_index(sheet)
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as file:
            for row in csv.reader(file):
                if len(row) < 5 or row[0] == "番号/ID":
                    continue
                vid_id, title, size_gb, magnet, video_url = row[:5]
                row_number = url_index.get(video_url)
                status = "已收录" if magnet else "暂无磁力（可手填）"
                if row_number:
                    if magnet and not sheet.cell(row_number, 9).value:
                        sheet.cell(row_number, 4).value = vid_id
                        sheet.cell(row_number, 5).value = title
                        sheet.cell(row_number, 6).value = float(size_gb) if size_gb else 0
                        sheet.cell(row_number, 8).value = "已收录"
                        sheet.cell(row_number, 9).value = magnet
                    continue
                sheet.append([sheet.max_row, source.get("site", ""), source.get("name", ""), vid_id, title,
                              float(size_gb) if size_gb else 0, video_url, status, magnet])
                url_index[video_url] = sheet.max_row
                added += 1
        _renumber_sheet(sheet)
    for sheet in workbook.worksheets:
        _renumber_sheet(sheet)
    workbook.save(MASTER_LEDGER_FILE)
    placeholder_added = sync_csv_placeholders_from_ledger(cfg)
    return MASTER_LEDGER_FILE, added + migrated + placeholder_added


def sync_csv_placeholders_from_ledger(cfg):
    """把台账中已有的无磁力行补回对应系列 CSV，保持小表与总台账一致。"""
    if not os.path.exists(MASTER_LEDGER_FILE):
        return 0
    from openpyxl import load_workbook
    workbook = load_workbook(MASTER_LEDGER_FILE, read_only=True, data_only=True)
    added = 0
    for source in cfg.get("sources", []):
        sheet_name = _ledger_sheet_name(source.get("site", ""), source.get("name", ""))
        if sheet_name not in workbook.sheetnames:
            continue
        sheet = workbook[sheet_name]
        existing = load_csv_map(source.get("dir", ""))
        for row in sheet.iter_rows(min_row=2, values_only=True):
            status = str(row[7] or "") if len(row) > 7 else ""
            video_url = row[6] if len(row) > 6 else ""
            if status.startswith("暂无磁力") and video_url and video_url not in existing:
                append_csv_placeholder(source.get("dir", ""), video_url)
                existing[video_url] = {"magnet": ""}
                added += 1
    return added


def append_no_magnet_record(site, source_name, video_url):
    """记录没有磁力的作品，后续仍会重试；一旦成功会更新同一行。"""
    workbook = _open_master_ledger()
    migrate_legacy_site_sheets(workbook)
    sheet = _get_ledger_sheet(workbook, site, source_name)
    if _find_ledger_row(sheet, source_name, video_url) is None:
        sheet.append([sheet.max_row, site, source_name, "", "（暂无磁力，待手动填写）", 0, video_url, "暂无磁力（可手填）", ""])
        _renumber_sheet(sheet)
        workbook.save(MASTER_LEDGER_FILE)


def append_missing_no_magnet_records(entries):
    """一次性将系列页发现但尚未入账的作品标为可手填，避免频繁保存 Excel。"""
    workbook = _open_master_ledger()
    migrate_legacy_site_sheets(workbook)
    added = 0
    for site, source_name, video_url in entries:
        sheet = _get_ledger_sheet(workbook, site, source_name)
        if _find_ledger_row(sheet, source_name, video_url) is not None:
            continue
        sheet.append([sheet.max_row, site, source_name, "", "（暂无磁力，待手动填写）", 0,
                      video_url, "暂无磁力（可手填）", ""])
        added += 1
    for sheet in workbook.worksheets:
        _renumber_sheet(sheet)
    workbook.save(MASTER_LEDGER_FILE)
    return added


def append_master_update(site, source_name, video_url, old_entry, info):
    """首次取得磁力填入初始磁力；已有初始磁力才在右侧追加“磁力更新 N”。"""
    workbook = _open_master_ledger()
    migrate_legacy_site_sheets(workbook)
    sheet = _get_ledger_sheet(workbook, site, source_name)
    row_number = _find_ledger_row(sheet, source_name, video_url)
    if row_number is None:
        old_entry = old_entry or {}
        sheet.append([sheet.max_row, site, source_name, old_entry.get("vid_id", info.vid_id),
                      old_entry.get("vid_name", info.vid_name), old_entry.get("size_gb", info.size_gb),
                      video_url, "已收录", old_entry.get("magnet", "")])
        row_number = sheet.max_row
    sheet.cell(row_number, 4).value = info.vid_id
    sheet.cell(row_number, 5).value = info.vid_name
    sheet.cell(row_number, 6).value = round(info.size_gb, 2)
    sheet.cell(row_number, 8).value = "已收录"
    if not sheet.cell(row_number, 9).value:
        sheet.cell(row_number, 9).value = info.magnet
    else:
        column = 10
        while sheet.cell(row_number, column).value:
            column += 1
        if not sheet.cell(1, column).value:
            sheet.cell(1, column).value = f"磁力更新 {column - 9}"
        sheet.cell(row_number, column).value = info.magnet
    _renumber_sheet(sheet)
    workbook.save(MASTER_LEDGER_FILE)
    return MASTER_LEDGER_FILE

# ─── MagnetInfo ──────────────────────────────────────────────────────────

class MagnetInfo:
    __slots__ = ("vid_id", "vid_name", "magnet", "size_bytes", "source_url", "extra_magnets")
    def __init__(self, vid_id="", vid_name="", magnet="", size_bytes=0, source_url="", extra_magnets=None):
        self.vid_id = vid_id
        self.vid_name = vid_name
        self.magnet = magnet
        self.size_bytes = size_bytes
        self.source_url = source_url
        self.extra_magnets = extra_magnets or []

    @property
    def size_gb(self):
        return self.size_bytes / (1024 ** 3)

# ─── JavdbScraper (纯HTTP) ──────────────────────────────────────────────

class JavdbScraper:
    """使用 requests + BeautifulSoup 爬取 javdb.com"""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    @classmethod
    def _request(cls, url, log=None):
        """有限重试，避免单次断连造成整系列扫描被静默截断。"""
        for attempt in range(1, 4):
            try:
                response = requests.get(url, headers=cls.HEADERS, timeout=20)
                response.encoding = "utf-8"
                if response.status_code == 200:
                    return response
                raise requests.RequestException(f"HTTP {response.status_code}")
            except Exception as exc:
                if log:
                    log(f"  [警告] 请求失败（{attempt}/3）: {exc}")
                if attempt < 3:
                    time.sleep(attempt)
        return None
    @classmethod
    def _resume_state_path(cls):
        return os.path.join(PROJECT_DIR, "javdb_scan_resume.json")

    @classmethod
    def _load_resume(cls, series_url):
        try:
            with open(cls._resume_state_path(), "r", encoding="utf-8") as file:
                return json.load(file).get(series_url)
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def _save_resume(cls, series_url, next_url, page_num):
        path = cls._resume_state_path()
        state = {}
        try:
            with open(path, "r", encoding="utf-8") as file:
                state = json.load(file)
        except (OSError, json.JSONDecodeError):
            pass
        state[series_url] = {"next_url": next_url, "page_num": page_num, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(path, "w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=False, indent=2)

    @classmethod
    def _clear_resume(cls, series_url):
        path = cls._resume_state_path()
        try:
            with open(path, "r", encoding="utf-8") as file:
                state = json.load(file)
            if series_url in state:
                state.pop(series_url)
                with open(path, "w", encoding="utf-8") as file:
                    json.dump(state, file, ensure_ascii=False, indent=2)
        except (OSError, json.JSONDecodeError):
            pass
    @classmethod
    def scan_series(cls, series_url, log_func=None):
        """扫描整个系列的所有分页，返回 [video_url, ...]"""
        parsed = urllib.parse.urlparse(series_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        all_urls = []
        current = series_url
        page_num = 1
        resume = cls._load_resume(series_url)
        if resume:
            current = resume.get("next_url") or series_url
            page_num = resume.get("page_num") or 1
            log_prefix = f"  [信息] 从第 {page_num} 页继续扫描"
        else:
            log_prefix = ""

        def log(msg):
            if log_func:
                log_func(msg)

        if log_prefix:
            log(log_prefix)
        while current:
            log(f"  扫描第 {page_num} 页: {current}")
            r = cls._request(current, log)
            if r is None:
                cls._save_resume(series_url, current, page_num)
                log("  [错误] 当前页连续重试失败；已保存断点，下次会从该页继续。")
                break

            soup = BeautifulSoup(r.text, "lxml")
            links = soup.select('a[href^="/v/"]')
            found = 0
            for a in links:
                href = a.get("href", "")
                if href.startswith("/v/") and "?" not in href and "#" not in href:
                    full = base_url + href
                    if full not in all_urls:
                        all_urls.append(full)
                        found += 1
            log(f"    本页找到 {found} 个影片链接")

            next_el = soup.select_one('a.pagination-next[rel="next"]')
            if next_el:
                next_href = next_el.get("href", "")
                if next_href:
                    current = urllib.parse.urljoin(base_url, next_href)
                    page_num += 1
                else:
                    break
            else:
                cls._clear_resume(series_url)
                break

        log(f"  共找到 {len(all_urls)} 个影片")
        return all_urls

    @classmethod
    def get_metadata(cls, video_url, series, log_func=None):
        response = cls._request(video_url, log_func)
        if response is None:
            return WorkMetadata(site="javdb", series=series, source_url=video_url, title="（资料待补全）")
        return parse_public_metadata(response.text, video_url, "javdb", series)

    @classmethod
    def get_magnet(cls, video_url, log_func=None):
        """访问详情页，提取最大磁力链接"""
        def log(msg):
            if log_func:
                log_func(f"    {msg}")

        r = cls._request(video_url, log)
        if r is None:
            log("[错误] 作品页连续重试失败")
            return None

        soup = BeautifulSoup(r.text, "lxml")

        # 提取页面标题
        title_tag = soup.title
        page_title = title_tag.string.strip() if title_tag else ""
        clean_title = page_title.split("|")[0].strip() if "|" in page_title else page_title.strip()

        # 找到所有磁力链接
        magnet_els = soup.select('a[href^="magnet:"]')
        if not magnet_els:
            log("[警告] 未找到磁力链接")
            return None

        best = None
        max_bytes = -1

        for el in magnet_els:
            href = el.get("href", "")
            name_el = el.select_one("span.name")
            meta_el = el.select_one("span.meta")
            name = name_el.get_text(strip=True) if name_el else ""
            meta = meta_el.get_text(strip=True) if meta_el else ""

            size_bytes = 0
            size_match = re.search(r"([\d.]+)\s*(GB|MB|KB)", meta, re.IGNORECASE)
            if size_match:
                val = float(size_match.group(1))
                unit = size_match.group(2).upper()
                if unit == "GB":
                    size_bytes = val * 1024 ** 3
                elif unit == "MB":
                    size_bytes = val * 1024 ** 2
                elif unit == "KB":
                    size_bytes = val * 1024

            if size_bytes > max_bytes:
                max_bytes = size_bytes
                best = (href, name, size_bytes)

        if not best:
            log("[警告] 无法解析磁力大小")
            return None

        href, name, size_bytes = best

        # 提取番号和片名
        match = re.match(r"^\[?([a-zA-Z0-9\-]+)\]?\s+(.*)$", clean_title)
        if match:
            vid_id = match.group(1).upper()
            vid_name = match.group(2).strip()
        else:
            vid_id = clean_title
            vid_name = clean_title

        log(f"[成功] {vid_id} - {vid_name[:40]} ({max_bytes / 1024**3:.2f} GB)")

        return MagnetInfo(
            vid_id=vid_id,
            vid_name=vid_name,
            magnet=href,
            size_bytes=size_bytes,
            source_url=video_url,
        )

# ─── JphooListing (纯HTTP系列列表) ──────────────────────────────────────

class JphooListing:
    """从 jphoo.net 系列页提取作品列表"""

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    @classmethod
    def scan_series_http(cls, series_url, log_func=None):
        """使用纯HTTP扫描（可能被Cloudflare拦截）"""
        import json as _json
        all_urls = []
        page_num = 1

        def log(msg):
            if log_func:
                log_func(msg)

        # 尝试 cloudscraper 作为备用
        try:
            import cloudscraper
            http = cloudscraper.create_scraper()
        except:
            import requests as http

        parsed = urllib.parse.urlparse(series_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        while True:
            url = series_url
            sep = "&" if "?" in series_url else "?"
            if page_num > 1:
                # JPHOO 的路由参数是 pageNum；使用 page 会被站点忽略并反复返回第一页。
                url = f"{series_url}{sep}pageNum={page_num}"

            log(f"  HTTP扫描第 {page_num} 页...")
            try:
                r = http.get(url, headers=cls.HEADERS, timeout=20)
                r.encoding = "utf-8"
            except Exception as e:
                log(f"  [错误] 请求失败: {e}")
                break

            match = re.search(r"__INITIAL_STATE__\s*=\s*({.+?});", r.text, re.DOTALL)
            if not match:
                if "cf-browser-request" in r.text or "Cloudflare" in r.text:
                    log("  [提示] 被Cloudflare拦截，将使用浏览器模式")
                else:
                    log("  [错误] 未找到页面数据")
                return None  # 返回None表示需要浏览器模式

            data = _json.loads(match.group(1))
            rows = data.get("all", {}).get("tagIdArrayList", {}).get("rows", [])
            total = data.get("all", {}).get("tagIdArrayList", {}).get("total", 0)

            for row in rows:
                wid = row.get("id")
                if wid:
                    u = f"{base_url}/works/{wid}"
                    if u not in all_urls:
                        all_urls.append(u)

            log(f"    本页 {len(rows)} 个")

            if len(all_urls) >= total:
                break
            page_num += 1

        log(f"  共找到 {len(all_urls)} 个作品")
        return all_urls

    @classmethod
    def scan_series(cls, series_url, browser_context=None, page=None, log_func=None):
        """使用Playwright浏览器扫描（推荐，可绕过Cloudflare）"""
        def log(msg):
            if log_func:
                log_func(msg)

        parsed = urllib.parse.urlparse(series_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        seen_ids = set()
        all_urls = []
        page_num = 1
        empty_pages = 0  # 连续空页计数

        if browser_context is None:
            log("  [错误] 需要浏览器上下文")
            return []

        try:
            owns_page = page is None
            if owns_page:
                page = browser_context.new_page()
                page.route("**/*", lambda route: route.abort()
                           if route.request.resource_type == "media" else route.continue_())

            while empty_pages < 2:  # 连续2页无新内容则停止
                url = series_url
                sep = "&" if "?" in series_url else "?"
                if page_num > 1:
                    # 与 SSR/前端一致：?pageNum=N 才会加载第 N 页。
                    url = f"{series_url}{sep}pageNum={page_num}"

                log(f"  扫描第 {page_num} 页: {url}")
                try:
                    page.goto(url, timeout=45000, wait_until="networkidle")
                except:
                    log(f"  [警告] 第 {page_num} 页超时，重试...")
                    try:
                        page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    except:
                        break
                page.wait_for_timeout(2000)

                # 从 DOM 提取作品链接
                links = page.query_selector_all('a[href^="/works/"]')
                found_new = 0
                for a in links:
                    href = a.get_attribute("href") or ""
                    if href.startswith("/works/") and href not in seen_ids:
                        seen_ids.add(href)
                        full = base_url + href.split("?")[0]
                        all_urls.append(full)
                        found_new += 1

                log(f"    本页新作品: {found_new}")

                if found_new == 0:
                    empty_pages += 1
                else:
                    empty_pages = 0

                page_num += 1

            if owns_page:
                page.close()
            log(f"  共找到 {len(all_urls)} 个作品")
            return all_urls

        except Exception as e:
            log(f"  [错误] 扫描失败: {e}")
            return []

# ─── JphooScraper (Playwright磁力提取) ─────────────────────────────────

class JphooScraper:
    """优先使用已登录会话 API；失败时回退到 Playwright 弹窗点击。"""

    API_CACHE_FILE = os.path.join(PROJECT_DIR, "jphoo_api_cache.json")
    API_PATH = "/prod-api/v2/dht/list"

    @classmethod
    def _load_cached_api_url(cls, work_url):
        try:
            with open(cls.API_CACHE_FILE, "r", encoding="utf-8") as file:
                return json.load(file).get(work_url)
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def _cache_api_url(cls, work_url, api_url):
        """只缓存公开请求 URL/参数，绝不缓存 Cookie、令牌或响应内容。"""
        if not api_url or cls.API_PATH not in api_url:
            return
        data = {}
        try:
            with open(cls.API_CACHE_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, json.JSONDecodeError):
            pass
        data[work_url] = api_url
        with open(cls.API_CACHE_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    @staticmethod
    def _size_bytes(value):
        match = re.search(r"([\d.]+)\s*(GB|MB|KB)", str(value or ""), re.IGNORECASE)
        if not match:
            return 0
        number, unit = float(match.group(1)), match.group(2).upper()
        return number * {"GB": 1024 ** 3, "MB": 1024 ** 2, "KB": 1024}[unit]

    @classmethod
    def _api_candidates(cls, payload):
        """提取 (磁力, 大小, 文件名/同记录文本)，不可丢失条目归属。"""
        found = []

        def visit(node):
            if isinstance(node, dict):
                values = [str(value) for value in node.values() if isinstance(value, (str, int, float))]
                size = max((cls._size_bytes(value) for value in values), default=0)
                label = " ".join(values)
                for value in values:
                    if value.startswith("magnet:"):
                        found.append((value, size, label))
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(payload)
        unique = {}
        for magnet, size, label in found:
            previous = unique.get(magnet)
            if previous is None or size > previous[0]:
                unique[magnet] = (size, label)
        return [(magnet, size, label) for magnet, (size, label) in unique.items()]

    @classmethod
    def get_metadata(cls, work_url, series, browser_context=None, page=None, log_func=None):
        if browser_context is None:
            return WorkMetadata(site="jphoo", series=series, source_url=work_url, title="（资料待补全）")
        owns_page = page is None
        page = page or browser_context.new_page()
        try:
            page.goto(work_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            return parse_public_metadata(page.content(), work_url, "jphoo", series)
        except Exception:
            return WorkMetadata(site="jphoo", series=series, source_url=work_url, title="（资料待补全）")
        finally:
            if owns_page:
                page.close()

    @classmethod
    def get_magnet(cls, work_url, browser_context=None, page=None, log_func=None):
        """同一标签页内：会话 API → 点击弹窗 API → DOM 磁力链接。"""
        def log(msg):
            if log_func:
                log_func(f"    {msg}")

        if browser_context is None:
            log("[错误] 需要已登录的浏览器上下文")
            return None

        owns_page = page is None
        page = page or browser_context.new_page()

        def work_tokens(value):
            ignored = {"mp4", "mkv", "avi", "mov", "hevc", "x264", "x265", "h264", "h265", "xxx", "web", "gb", "mb", "480p", "720p", "1080p", "2160p"}
            return {token for token in re.findall(r"[a-z0-9]{3,}", str(value or "").lower()) if token not in ignored and not token.isdigit()}

        # 页面会被复用；标题必须在本次导航完成后再读取，避免沿用上一部影片。
        title = ""
        clean_title = ""
        target_tokens = set()

        def build_info(candidates):
            """只在文件名与当前影片标题足够匹配时，才从同一弹窗的多个磁力中选最大版本。"""
            scored = []
            for candidate in candidates:
                magnet, size_bytes = candidate[0], candidate[1]
                label = candidate[2] if len(candidate) > 2 else ""
                score = len(target_tokens & work_tokens(label))
                scored.append((score, size_bytes, magnet, label))
            if not scored:
                return None
            best_score = max(item[0] for item in scored)
            required_score = 2 if len(target_tokens) >= 2 else 1
            if best_score < required_score:
                log("[警告] 弹窗磁力无法与当前影片标题可靠匹配，已跳过以避免写入同日另一部影片")
                return None
            matches = [item for item in scored if item[0] == best_score]
            _, max_bytes, best, _ = max(matches, key=lambda item: item[1])
            match = re.match(r"^\[?([a-zA-Z0-9\-]+)\]?\s+(.*)$", clean_title)
            vid_id, vid_name = (match.group(1).upper(), match.group(2).strip()) if match else (clean_title, clean_title)

            # 同一弹窗可能混入同日另一部影片。保留这些资源，但按文件名分组，只取每部的最大版本。
            extra_groups = {}
            current_group_score = max(required_score, (best_score * 3 + 3) // 4)
            for score, size_bytes, magnet, label in scored:
                # 与最佳标题高度相近的是同一影片的不同清晰度；其余才是附带影片。
                if score >= current_group_score:
                    continue
                group_tokens = work_tokens(label)
                group_key = " ".join(sorted(group_tokens)) or magnet_identity(magnet)
                previous = extra_groups.get(group_key)
                if previous is None or size_bytes > previous[0]:
                    extra_groups[group_key] = (size_bytes, magnet, label)
            extras = []
            for size_bytes, magnet, label in extra_groups.values():
                label_text = re.sub(r"\s+", " ", str(label or "弹窗附带资源")).strip()[:180]
                identity = magnet_identity(magnet).replace("urn:btih:", "") or str(len(extras) + 1)
                extras.append(MagnetInfo(
                    vid_id="弹窗附带资源", vid_name=label_text, magnet=magnet, size_bytes=size_bytes,
                    source_url=f"{work_url}#magnet-{identity}",
                ))
            if extras:
                log(f"[信息] 弹窗另含 {len(extras)} 部同日附带影片，已准备新增独立记录")
            log(f"[成功] {vid_id} - {vid_name[:40]} ({max_bytes / 1024 ** 3:.2f} GB，标题匹配 {best_score})")
            return MagnetInfo(vid_id=vid_id, vid_name=vid_name, magnet=best,
                              size_bytes=max_bytes, source_url=work_url, extra_magnets=extras)

        def dom_candidates(target_page=None):
            target_page = target_page or page
            candidates = []
            for element in target_page.query_selector_all('a[href^="magnet:"]'):
                try:
                    label = element.evaluate("el => (el.closest('li, .q-card, .q-item') || el.parentElement || el).innerText || ''")
                except Exception:
                    label = element.inner_text()
                candidates.append((element.get_attribute("href") or "", cls._size_bytes(label), label))
            return candidates

        def try_session_api():
            cached_url = cls._load_cached_api_url(work_url)
            if not cached_url:
                return None
            try:
                response = browser_context.request.get(cached_url, headers={"isToken": "true"}, timeout=15000)
                if not response.ok:
                    log(f"  [提示] 会话 API 返回 HTTP {response.status}")
                    return None
                info = build_info(cls._api_candidates(response.json()))
                if info:
                    log("  [信息] 已通过会话 API 获取磁力")
                return info
            except Exception as exc:
                log(f"  [提示] 会话 API 失败，回退弹窗：{exc}")
                return None

        try:
            # JPHOO 的“复制磁力”按钮可能只把原始链接传给浏览器剪贴板，
            # 因此在本页导航前拦截 writeText；只保存磁力到页面内存，不改系统剪贴板。
            clipboard_hook = """
                (() => {
                    window.__yav_copied_magnets = [];
                    try {
                        const clipboard = navigator.clipboard;
                        const originalWriteText = clipboard && clipboard.writeText && clipboard.writeText.bind(clipboard);
                        if (clipboard && originalWriteText) {
                            Object.defineProperty(clipboard, 'writeText', {
                                configurable: true,
                                value: async (value) => {
                                    if (typeof value === 'string' && value.startsWith('magnet:')) {
                                        window.__yav_copied_magnets.push(value);
                                    }
                                    return undefined;
                                },
                            });
                        }
                    } catch (_) {}
                })();
            """
            # 当前作品页与可能由按钮打开的子标签页都需要拦截复制动作。
            browser_context.add_init_script(clipboard_hook)
            page.add_init_script(clipboard_hook)
            # JPHOO 偶发资源长加载；页面提交即可继续等待按钮，避免因图片/脚本拖慢 DOM 事件而跳过。
            page.goto(work_url, timeout=45000, wait_until="commit")
            page.wait_for_timeout(2500)
            title = page.title()
            clean_title = re.split(r"\s*-\s*磁力下载链接", title, maxsplit=1)[0].strip()
            target_tokens = work_tokens(clean_title)
            log(f"  当前作品：{clean_title or title}")

            info = build_info(dom_candidates())
            if info:
                return info
            info = try_session_api()
            if info:
                return info

            captured = []
            popup_pages = []
            def on_response(response):
                if cls.API_PATH in response.url:
                    captured.append(response)

            def on_popup(popup):
                # JPHOO 的某些版本会把磁力结果放入临时子标签页/窗口。
                # 本轮只追踪按钮产生的页面，并在读取后关闭，避免积累大量标签页。
                popup_pages.append(popup)
                popup.on("response", on_response)
                log("  [信息] 已捕获磁力子标签页")

            page.on("response", on_response)
            browser_context.on("page", on_popup)
            try:
                # JPHOO 会在首屏提交后异步渲染 Quasar 按钮。不能只检查一次，
                # 否则页面标题已到位而按钮尚未挂入 DOM 时会被误判为“没有磁力”。
                # 先用无障碍名称，再回退到实际的 button / q-btn 文本选择器。
                button = None
                button_description = ""
                for _ in range(24):  # 最多等待 12 秒，避免网络慢时漏掉弹窗入口
                    role_buttons = page.get_by_role("button", name=re.compile("磁力下载链接", re.I))
                    if role_buttons.count():
                        button = role_buttons.first
                        button_description = "role=button[name*=磁力下载链接]"
                        break
                    css_buttons = page.locator('button:has-text("磁力下载链接"), .q-btn:has-text("磁力下载链接"), [role="button"]:has-text("磁力下载链接")')
                    if css_buttons.count():
                        button = css_buttons.first
                        button_description = "text=磁力下载链接"
                        break
                    page.wait_for_timeout(500)
                if button is not None:
                    log(f"  尝试点击: {button_description}")
                    button.click()
                    page.wait_for_timeout(500)
                    # 未登录时，该按钮会先打开“登陆账号 / 登录密码”对话框。
                    # 给用户一次明确的手动登录机会；登录成功后自动重试当前影片。
                    login_dialog = page.query_selector('input[type="password"]')
                    if login_dialog:
                        # 让专用 Edge 到最前面，避免登录框被主程序或其他窗口遮住。
                        page.bring_to_front()
                        log("[需要登录] JPHOO 登录对话框已置于最前，请在专用 Edge 窗口手动登录")
                        log("[提示] 程序将等待 120 秒，登录成功后自动继续当前影片")
                        for _ in range(120):
                            page.wait_for_timeout(1000)
                            if not page.query_selector('input[type="password"]'):
                                log("[信息] 检测到登录对话框已关闭，正在重新读取磁力")
                                break
                        else:
                            log("[提示] 尚未完成登录，已跳过当前影片；登录后请重新执行更新")
                            return None
                        button = page.get_by_role("button", name=re.compile("磁力下载链接", re.I))
                        if not button.count():
                            log("[提示] 登录后未找到磁力按钮，请重新执行更新")
                            return None
                        button.first.click()
                    processed = set()
                    # 接口实际会在弹窗出现后异步返回；最多等 8 秒，每 0.4 秒检查一次。
                    for _ in range(20):
                        page.wait_for_timeout(400)
                        for response in captured:
                            if response.url in processed:
                                continue
                            processed.add(response.url)
                            cls._cache_api_url(work_url, response.url)
                            try:
                                info = build_info(cls._api_candidates(response.json()))
                                if info:
                                    log("  [信息] 已从弹窗 API 响应获取磁力")
                                    return info
                            except Exception as exc:
                                log(f"  [提示] 已捕获磁力接口，但解析失败: {exc}")
                        for magnet_page in [page] + [item for item in popup_pages if not item.is_closed()]:
                            info = build_info(dom_candidates(magnet_page))
                            if info:
                                log("  [信息] 已从弹窗页面 DOM 获取磁力")
                                return info
                    # 接口被页面内部封装时，逐个触发“复制磁力”，并从页面内存读取链接。
                    # 子标签页也会被检查；每部影片结束后由 finally 统一关闭，避免标签页累积。
                    for magnet_page in [page] + [item for item in popup_pages if not item.is_closed()]:
                        body_text = magnet_page.inner_text("body")
                        copied_count = body_text.count("复制磁力")
                        if not copied_count:
                            continue
                        copy_buttons = magnet_page.query_selector_all('.q-chip:has-text("复制磁力")')
                        copy_labels = []
                        for copy_button in copy_buttons:
                            try:
                                copy_labels.append(copy_button.evaluate("el => (el.closest('li, .q-card, .q-item') || el.parentElement || el).innerText || ''"))
                                copy_button.click(force=True)
                            except Exception:
                                copy_labels.append("")
                        magnet_page.wait_for_timeout(300)
                        copied_magnets = magnet_page.evaluate("window.__yav_copied_magnets || []") or []
                        clipboard_candidates = [(magnet, cls._size_bytes(copy_labels[index] if index < len(copy_labels) else ''), copy_labels[index] if index < len(copy_labels) else '') for index, magnet in enumerate(copied_magnets) if str(magnet).startswith('magnet:')]
                        info = build_info(clipboard_candidates)
                        if info:
                            log(f"  [信息] 已从 {len(clipboard_candidates)} 条复制磁力中获取原始链接")
                            return info
                        log(f"  [警告] 磁力弹窗已打开，显示 {copied_count} 条复制磁力，但接口与复制链接均未捕获")
                else:
                    log("  [提示] 未找到磁力下载按钮")
            finally:
                page.remove_listener("response", on_response)
                browser_context.remove_listener("page", on_popup)
                # 只关闭本作品点击后产生的临时页面，主标签页始终复用。
                for popup in popup_pages:
                    try:
                        if not popup.is_closed():
                            popup.close()
                    except Exception:
                        pass

            body_text = page.inner_text("body")
            if "login" in body_text.lower() or "登录" in body_text:
                log("[警告] 未登录或需要登录才能查看磁力")
                log("[提示] 请在打开的浏览器中完成登录，程序会在 30 秒后自动继续。")
                page.wait_for_timeout(30000)
                page.goto(work_url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                info = try_session_api() or build_info(dom_candidates())
                if info:
                    return info
            log("[提示] 当前作品未找到可用磁力链接")
            return None
        except Exception as exc:
            log(f"[错误] 提取磁力失败: {exc}")
            return None
        finally:
            if owns_page:
                page.close()
# ─── 主应用 ──────────────────────────────────────────────────────────────

class JavdbJphooApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Yav · 私人影视资料馆")
        self.root.geometry("750x620")

        self.cfg = load_config()
        self.library = LibraryStore(RESOURCE_DIR)
        self.library.migrate_csv(self.cfg.get("sources", []))
        self.is_running = False
        self.cancel_event = threading.Event()
        self._worker = None
        self._closing = False
        self._playwright_browser = None  # jphoo缓存
        self.root.protocol("WM_DELETE_WINDOW", self.request_close)

        self._build_ui()
        self._refresh_list()
        self.root.after(250, getattr(self, "open_library", lambda: None))

    # ── UI 构建 ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # ─── 工具栏：添加/编辑/删除 ───
        toolbar = ttk.Frame(self.root)
        toolbar.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 0), sticky="ew")

        ttk.Button(toolbar, text="添加网址", command=self.add_source).pack(side="left", padx=(0, 5))
        ttk.Button(toolbar, text="编辑", command=self.edit_source).pack(side="left", padx=5)
        ttk.Button(toolbar, text="删除", command=self.delete_source).pack(side="left", padx=5)

        # ─── 列表 ───
        columns = ("site", "name", "url", "dir")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=6)
        self.tree.heading("site", text="站点")
        self.tree.heading("name", text="系列名")
        self.tree.heading("url", text="URL")
        self.tree.heading("dir", text="保存目录")
        self.tree.column("site", width=60, anchor="center")
        self.tree.column("name", width=150)
        self.tree.column("url", width=300)
        self.tree.column("dir", width=200)
        self.tree.grid(row=1, column=0, columnspan=2, padx=10, pady=(5, 0), sticky="nsew")

        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=1, column=2, sticky="ns", pady=(5, 0))
        self.tree.configure(yscrollcommand=scrollbar.set)

        # ─── 选项 ───
        opt_frame = ttk.Frame(self.root)
        opt_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=(5, 0), sticky="w")

        self.browser_var = tk.BooleanVar(value=self.cfg.get("browser_mode", True))
        ttk.Checkbutton(
            opt_frame, text="浏览器模式 (jphoo.net需要登录Edge/Chrome)",
            variable=self.browser_var
        ).pack(side="left")

        # ─── 操作按钮 ───
        btn_frame = ttk.Frame(self.root)
        btn_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=(5, 0), sticky="w")

        self.scan_btn = ttk.Button(btn_frame, text="扫描新影片", command=self.start_scan)
        self.scan_btn.pack(side="left", padx=(0, 5))

        self.update_btn = ttk.Button(btn_frame, text="更新旧磁力", command=self.start_update)
        self.update_btn.pack(side="left", padx=5)

        self.merge_btn = ttk.Button(btn_frame, text="合并本目录TXT", command=self.merge_txts)
        self.merge_btn.pack(side="left", padx=5)

        # ─── 进度条 ───
        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=500, mode="determinate")
        self.progress.grid(row=4, column=0, columnspan=2, padx=10, pady=(5, 5))

        self.status_label = ttk.Label(self.root, text="就绪")
        self.status_label.grid(row=4, column=0, columnspan=2, pady=(25, 0))

        # ─── 日志 ───
        self.log_area = scrolledtext.ScrolledText(self.root, width=85, height=15, state="disabled")
        self.log_area.grid(row=5, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="nsew")

        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(5, weight=1)

    # ── 列表操作 ──────────────────────────────────────────────────────────

    def _refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for src in self.cfg.get("sources", []):
            self.tree.insert("", "end", values=(
                src.get("site", ""),
                src.get("name", ""),
                src.get("url", ""),
                src.get("dir", ""),
            ))

    def add_source(self):
        dlg = SourceDialog(self.root, title="添加网址")
        if dlg.result:
            self.cfg["sources"].append(dlg.result)
            save_config(self.cfg)
            self._refresh_list()

    def edit_source(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个系列")
            return
        idx = self.tree.index(sel[0])
        old = self.cfg["sources"][idx]
        dlg = SourceDialog(self.root, title="编辑网址", data=old)
        if dlg.result:
            self.cfg["sources"][idx] = dlg.result
            save_config(self.cfg)
            self._refresh_list()

    def delete_source(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个系列")
            return
        if messagebox.askyesno("确认", "确定删除该系列？"):
            idxs = [self.tree.index(item) for item in sel]
            for idx in reversed(sorted(idxs)):
                self.cfg["sources"].pop(idx)
            save_config(self.cfg)
            self._refresh_list()

    def merge_txts(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("选择目录")
        dlg.geometry("400x120")
        ttk.Label(dlg, text="要合并的目录:").pack(pady=(10, 5))
        dir_var = tk.StringVar()
        entry = ttk.Entry(dlg, textvariable=dir_var, width=50)
        entry.pack(padx=10)
        def browse():
            d = filedialog.askdirectory()
            if d:
                dir_var.set(d)
        ttk.Button(dlg, text="浏览", command=browse).pack(pady=5)
        def do_merge():
            sd = dir_var.get().strip()
            if not os.path.isdir(sd):
                messagebox.showerror("错误", "目录不存在")
                return
            merged_path = os.path.join(sd, "_全部磁力合并.txt")
            count = 0
            try:
                with open(merged_path, "w", encoding="utf-8") as out:
                    for fn in os.listdir(sd):
                        if fn.endswith(".txt") and fn != "_全部磁力合并.txt" and not fn.startswith("_"):
                            fp = os.path.join(sd, fn)
                            with open(fp, "r", encoding="utf-8") as f:
                                c = f.read().strip()
                                if c:
                                    out.write(c + "\n")
                                    count += 1
                self.log(f"[成功] 已合并 {count} 个磁力到 _全部磁力合并.txt")
                messagebox.showinfo("成功", f"合并完成，共 {count} 条")
            except Exception as e:
                messagebox.showerror("错误", str(e))
            dlg.destroy()
        ttk.Button(dlg, text="开始合并", command=do_merge).pack(pady=5)

    def request_close(self):
        """窗口关闭时先让工作线程完成清理，避免残留 Edge/Playwright 后台进程。"""
        if not self.is_running:
            self._final_destroy()
            return
        if not messagebox.askyesno("正在运行", "任务仍在运行。停止任务并安全退出吗？", parent=self.root):
            return
        self._closing = True
        self.cancel_event.set()
        self.log("[信息] 已请求停止任务，正在关闭浏览器和网络请求...")
        self._wait_for_worker_then_destroy()

    def _wait_for_worker_then_destroy(self):
        worker = getattr(self, "_worker", None)
        if worker and worker.is_alive():
            self.root.after(150, self._wait_for_worker_then_destroy)
            return
        self._final_destroy()

    def _final_destroy(self):
        try:
            if not self.is_running:
                self._close_playwright()
        finally:
            self.root.destroy()
    # ── 日志 ─────────────────────────────────────────────────────────────

    def log(self, message):
        self.root.after(0, self._do_log, message)

    def _do_log(self, message):
        self.log_area.config(state="normal")
        self.log_area.insert(tk.END, message + "\n")
        self.log_area.see(tk.END)
        self.log_area.config(state="disabled")

    def set_status(self, text):
        self.root.after(0, self._do_status, text)

    def _do_status(self, text):
        self.status_label.config(text=text)
        self.root.update_idletasks()

    def set_progress(self, value, maximum=100):
        self.root.after(0, self._do_progress, value, maximum)

    def _do_progress(self, value, maximum):
        self.progress["maximum"] = maximum if maximum > 0 else 1
        self.progress["value"] = value
        self.root.update_idletasks()

    def enable_buttons(self, enabled=True):
        state = "normal" if enabled else "disabled"
        self.root.after(0, lambda: [self.scan_btn.config(state=state),
                                    self.update_btn.config(state=state),
                                    self.merge_btn.config(state=state)])

    # ── 启动后台任务 ─────────────────────────────────────────────────────

    def start_scan(self):
        if self.is_running:
            return
        self.is_running = True
        self.enable_buttons(False)
        self.log_area.config(state="normal")
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state="disabled")
        threading.Thread(target=self._run_scan, daemon=True).start()

    def start_update(self):
        if self.is_running:
            return
        self.is_running = True
        self.enable_buttons(False)
        self.log_area.config(state="normal")
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state="disabled")
        threading.Thread(target=self._run_update, daemon=True).start()

    # ── 扫描新影片 ───────────────────────────────────────────────────────

    def _init_playwright(self):
        if self._playwright_browser is not None:
            return self._playwright_browser
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        # 使用 Yav 独立的持久化 Edge 配置目录保存 Cookie、localStorage 和站点状态。
        # 它不会影响用户平时正在使用的 Edge，也不会在每次扫描时丢失登录态。
        profile_dir = os.path.join(RESOURCE_DIR, "_Yav资源库", "jphoo_edge_profile")
        os.makedirs(profile_dir, exist_ok=True)
        context_options = {
            "viewport": {"width": 1280, "height": 720},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        context = p.chromium.launch_persistent_context(
            profile_dir, channel="msedge", headless=False, **context_options
        )
        self.log("[信息] 已打开 Yav 专用 JPHOO 浏览器配置，登录状态会自动保留")
        self._jphoo_profile_dir = profile_dir
        self._jphoo_context = context
        self._playwright_browser = context  # 供外部使用
        self._playwright = p

        # 整个任务复用同一张标签页，扫描与逐部检查只在此页导航。
        page = context.new_page()
        page.route("**/*", lambda route: route.abort()
                   if route.request.resource_type in ["image", "media", "font"]
                   else route.continue_())
        self._jphoo_page = page
        page.goto("https://www.jphoo.net", timeout=15000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        # JPHOO 首页不会可靠暴露登录状态；实际在点击磁力按钮时再准确判断。
        self.log("[信息] JPHOO 专用 Edge 已打开，将在获取磁力时确认登录状态")
        return context

    def _close_playwright(self):
        # 持久化配置目录由 Edge 自行写入，正常关闭上下文即可保存登录态。
        try:
            if self._playwright_browser:
                self._playwright_browser.close()
        except:
            pass
        try:
            if hasattr(self, "_playwright"):
                self._playwright.stop()
        except:
            pass
        self._playwright_browser = None
        self._jphoo_context = None
        self._jphoo_page = None

    def _store_library_work(self, site, series, video_url, info=None, browser_context=None):
        """资料库优先：无论是否有磁力，都建立影片记录。"""
        try:
            if site == "javdb":
                metadata = JavdbScraper.get_metadata(video_url, series)
            elif site == "jphoo":
                metadata = JphooScraper.get_metadata(video_url, series, browser_context, getattr(self, "_jphoo_page", None))
            else:
                metadata = WorkMetadata(site=site, series=series, source_url=video_url)
            if info:
                metadata.code = info.vid_id
                metadata.title = info.vid_name or metadata.title
                metadata.magnet = info.magnet
                metadata.size_gb = info.size_gb
            work_id = self.library.upsert_work(metadata, cache_cover=False)
            if info:
                for extra in info.extra_magnets:
                    self.library.upsert_work(WorkMetadata(site=site, series=series, source_url=extra.source_url,
                        title=extra.vid_name, code=extra.vid_id, magnet=extra.magnet, size_gb=extra.size_gb), cache_cover=False)
            return work_id
        except Exception as exc:
            self.log(f"  [资料库] 写入失败: {exc}")
            return None

    def _run_scan(self):
        try:
            browser_mode = self.browser_var.get()
            self.cfg["browser_mode"] = browser_mode
            save_config(self.cfg)

            sources = getattr(self, "_run_sources", self.cfg.get("sources", []))
            if not sources:
                self.log("[错误] 没有配置任何系列网址")
                return

            # 统计需要处理的视频总数
            self.log("=" * 50)
            self.log("开始扫描新影片...")
            self.log(f"共 {len(sources)} 个系列")

            # 如果需要 jphoo，初始化 Playwright
            need_playwright = browser_mode and any(s.get("site") == "jphoo" for s in sources)
            ctx = None
            if need_playwright:
                self.log("[信息] 正在启动 Edge 浏览器 (jphoo.net需要登录态)...")
                try:
                    ctx = self._init_playwright()
                except Exception as e:
                    self.log(f"[错误] 启动浏览器失败: {e}")
                    self.log("[提示] jphoo.net 系列将被跳过")

            total_new = 0
            total_skipped = 0

            for src_idx, src in enumerate(sources):
                if self.cancel_event.is_set():
                    self.log("[信息] 扫描已取消")
                    return
                site = src.get("site", "")
                name = src.get("name", "")
                url = src.get("url", "")
                save_dir = src.get("dir", "")

                self.log("-" * 50)
                self.log(f"[{src_idx + 1}/{len(sources)}] {name} ({site})")
                self.log(f"  URL: {url}")
                self.log(f"  保存: {save_dir}")

                if not url or not save_dir:
                    self.log("  [跳过] URL或目录为空")
                    continue

                if not os.path.exists(save_dir):
                    try:
                        os.makedirs(save_dir)
                        self.log(f"  创建目录: {save_dir}")
                    except Exception as e:
                        self.log(f"  [错误] 创建目录失败: {e}")
                        continue

                init_csv(save_dir)
                history = load_history(save_dir)

                # 阶段一：扫描系列列表
                self.log("  --- 扫描系列列表 ---")
                try:
                    if site == "javdb":
                        all_urls = JavdbScraper.scan_series(url, log_func=self.log)
                    elif site == "jphoo":
                        # 列表页是公开 SSR 数据，优先 HTTP：速度更快、不会创建标签页，
                        # 也不会受登录弹窗影响。只有被拦截时才回退到已登录浏览器。
                        all_urls = JphooListing.scan_series_http(url, log_func=self.log)
                        if all_urls is None:
                            if ctx:
                                self.log("  [提示] HTTP 被拦截，回退到 Edge 浏览器分页扫描")
                                all_urls = JphooListing.scan_series(
                                    url, browser_context=ctx,
                                    page=getattr(self, "_jphoo_page", None),
                                    log_func=self.log,
                                )
                            else:
                                self.log("  [错误] HTTP 被拦截，需要浏览器模式")
                                continue
                    else:
                        self.log(f"  [错误] 未知站点类型: {site}")
                        continue
                except Exception as e:
                    self.log(f"  [错误] 扫描失败: {e}")
                    continue

                # 过滤历史
                new_urls = [u for u in all_urls if u not in history]
                skipped = len(all_urls) - len(new_urls)
                total_skipped += skipped

                self.log(f"  全部: {len(all_urls)}, 已下载: {skipped}, 待下载: {len(new_urls)}")

                if not new_urls:
                    self.log("  没有新影片，跳过")
                    continue

                # 阶段二：提取磁力
                self.log("  --- 提取磁力 ---")
                self.set_progress(0, len(new_urls))

                for idx, video_url in enumerate(new_urls):
                    if self.cancel_event.is_set():
                        self.log("[信息] 扫描已取消")
                        return
                    self.set_progress(idx, len(new_urls))
                    self.set_status(f"[{name}] {idx + 1}/{len(new_urls)}")
                    self.log(f"  ({idx + 1}/{len(new_urls)})")

                    try:
                        if site == "javdb":
                            info = JavdbScraper.get_magnet(video_url, log_func=self.log)
                        elif site == "jphoo":
                            # 资料库扫描只收录作品、资料与封面；磁力由“更新所选系列”分批补充。
                            # 避免首次 3591 部入库时连续触发数千个登录态弹窗请求。
                            self.log("    [资料库] 已建立影片资料；磁力留待后续更新")
                            info = None
                        else:
                            info = None
                    except Exception as e:
                        self.log(f"  [错误] {e}")
                        info = None

                    self._store_library_work(site, name, video_url, info, ctx)
                    if info:
                        append_history(save_dir, video_url)
                        append_csv(save_dir, info.vid_id, info.vid_name, info.size_gb, info.magnet, video_url)
                        for extra in info.extra_magnets:
                            append_csv(save_dir, extra.vid_id, extra.vid_name, extra.size_gb, extra.magnet, extra.source_url)
                            total_new += 1
                        total_new += 1
                    elif site in ("javdb", "jphoo"):
                        append_history(save_dir, video_url)
                        append_csv_placeholder(save_dir, video_url)
                        append_no_magnet_record(site, name, video_url)

                    # 小延迟缓解服务器压力
                    time.sleep(1)

            ledger_path, ledger_added = sync_master_ledger(self.cfg)
            self.log(f"[Excel] 已同步主台账：新增 {ledger_added} 行")
            self.set_progress(0)
            self.log("=" * 50)
            self.log(f"扫描完成！新增 {total_new} 部，跳过 {total_skipped} 部")
            self.root.after(0, lambda: messagebox.showinfo("完成", f"扫描完成！\n新增: {total_new} 部\n跳过: {total_skipped} 部"))

        except Exception as e:
            self.log(f"[致命错误] {e}")
        finally:
            self._close_playwright()
            self.is_running = False
            self.enable_buttons(True)
            self.set_status("就绪")

    # ── 更新旧磁力 ───────────────────────────────────────────────────────

    def _run_update(self):
        try:
            browser_mode = self.browser_var.get()
            sources = getattr(self, "_run_sources", self.cfg.get("sources", []))

            self.log("=" * 50)
            self.log("开始更新旧磁力...")
            self.log("将重新检查每个已下载影片是否有更大的新磁力")

            need_playwright = browser_mode and any(s.get("site") == "jphoo" for s in sources)
            ctx = None
            if need_playwright:
                self.log("[信息] 正在启动 Edge 浏览器 (jphoo.net需要登录态)...")
                try:
                    ctx = self._init_playwright()
                except Exception as e:
                    self.log(f"[错误] 启动浏览器失败: {e}")

            total_updated = 0
            total_checked = 0

            for src_idx, src in enumerate(sources):
                if self.cancel_event.is_set():
                    self.log("[信息] 更新已取消")
                    return
                site = src.get("site", "")
                name = src.get("name", "")
                url = src.get("url", "")
                save_dir = src.get("dir", "")

                self.log("-" * 50)
                self.log(f"[{src_idx + 1}/{len(sources)}] {name} ({site})")

                if not url or not save_dir or not os.path.isdir(save_dir):
                    self.log("  [跳过] 目录不存在")
                    continue

                history = load_history(save_dir)
                csv_map = load_csv_map(save_dir)

                if not history:
                    self.log("  没有历史记录，跳过")
                    continue

                old_urls = list(history)
                self.log(f"  共 {len(old_urls)} 部旧影片需要检查")

                self.set_progress(0, len(old_urls))

                for idx, video_url in enumerate(old_urls):
                    if self.cancel_event.is_set():
                        self.log("[信息] 更新已取消")
                        return
                    self.set_progress(idx, len(old_urls))
                    self.set_status(f"[{name}] 检查 {idx + 1}/{len(old_urls)}")
                    self.log(f"  ({idx + 1}/{len(old_urls)}) {video_url[:80]}...")

                    try:
                        if site == "javdb":
                            info = JavdbScraper.get_magnet(video_url, log_func=self.log)
                        elif site == "jphoo":
                            if ctx:
                                info = JphooScraper.get_magnet(video_url, browser_context=ctx, page=getattr(self, "_jphoo_page", None), log_func=self.log)
                            else:
                                info = None
                        else:
                            info = None
                    except Exception as e:
                        self.log(f"  [错误] {e}")
                        info = None

                    self._store_library_work(site, name, video_url, info, ctx)
                    if info:
                        total_checked += 1
                        old_entry = csv_map.get(video_url)
                        old_size_gb = old_entry["size_gb"] if old_entry else 0
                        new_size_gb = info.size_gb

                        if (not old_entry or magnet_identity(info.magnet) != magnet_identity(old_entry["magnet"]) or new_size_gb > old_size_gb + 0.01):
                            self.log(f"    ↑ 发现更大磁力! {old_size_gb:.2f}GB → {new_size_gb:.2f}GB")
                            # Excel 主台账：把新磁力追加到本行右侧，不覆盖初始磁力
                            append_master_update(site, name, video_url, old_entry, info)
                            # 更新CSV
                            rows = []
                            cfile = os.path.join(save_dir, "_全部磁力汇总表.csv")
                            if os.path.exists(cfile):
                                with open(cfile, "r", encoding="utf-8-sig") as f:
                                    reader = csv.reader(f)
                                    header = next(reader)
                                    for row in reader:
                                        if len(row) >= 5 and row[4].strip() == video_url:
                                            rows.append([info.vid_id, info.vid_name, f"{new_size_gb:.2f}",
                                                         info.magnet, video_url])
                                        else:
                                            rows.append(row)
                                with open(cfile, "w", newline="", encoding="utf-8-sig") as f:
                                    writer = csv.writer(f)
                                    writer.writerow(header)
                                    writer.writerows(rows)
                            append_update_log(save_dir, name, video_url, old_entry, info, "磁力哈希变化或文件大小增加")
                            total_updated += 1

                    if site == "jphoo" and info and info.extra_magnets:
                        for extra in info.extra_magnets:
                            if extra.source_url in csv_map:
                                continue
                            append_csv(save_dir, extra.vid_id, extra.vid_name, extra.size_gb, extra.magnet, extra.source_url)
                            append_master_update(site, name, extra.source_url, None, extra)
                            csv_map[extra.source_url] = {"magnet": extra.magnet, "size_gb": extra.size_gb}
                            total_updated += 1
                            self.log("    + 已新增弹窗附带影片资源")

                    time.sleep(1)

            self.set_progress(0)
            self.log("=" * 50)
            self.log(f"检查完成！共检查 {total_checked} 部，更新 {total_updated} 部")
            self.root.after(0, lambda: messagebox.showinfo("完成", f"更新完成！\n检查: {total_checked} 部\n更新: {total_updated} 部"))

        except Exception as e:
            self.log(f"[致命错误] {e}")
        finally:
            self._close_playwright()
            self.is_running = False
            self.enable_buttons(True)
            self.set_status("就绪")

# ─── 添加/编辑对话框 ─────────────────────────────────────────────────────

class SourceDialog:
    def __init__(self, parent, title="添加网址", data=None):
        self.result = None
        dlg = tk.Toplevel(parent)
        dlg.title(title)
        dlg.geometry("520x280")
        dlg.transient(parent)
        dlg.grab_set()

        ttk.Label(dlg, text="站点类型:").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        self.site_var = tk.StringVar(value=data.get("site", "javdb") if data else "javdb")
        site_combo = ttk.Combobox(dlg, textvariable=self.site_var, values=["javdb", "jphoo"], state="readonly", width=10)
        site_combo.grid(row=0, column=1, padx=10, pady=10, sticky="w")

        ttk.Label(dlg, text="系列名称:").grid(row=1, column=0, padx=10, pady=5, sticky="e")
        self.name_var = tk.StringVar(value=data.get("name", "") if data else "")
        ttk.Entry(dlg, textvariable=self.name_var, width=50).grid(row=1, column=1, padx=10, pady=5, sticky="w")

        ttk.Label(dlg, text="系列URL:").grid(row=2, column=0, padx=10, pady=5, sticky="e")
        self.url_var = tk.StringVar(value=data.get("url", "") if data else "")
        ttk.Entry(dlg, textvariable=self.url_var, width=50).grid(row=2, column=1, padx=10, pady=5, sticky="w")

        ttk.Label(dlg, text="保存目录:").grid(row=3, column=0, padx=10, pady=5, sticky="e")
        dir_frame = ttk.Frame(dlg)
        dir_frame.grid(row=3, column=1, padx=10, pady=5, sticky="w")
        self.dir_var = tk.StringVar(value=data.get("dir", RESOURCE_DIR) if data else RESOURCE_DIR)
        ttk.Entry(dir_frame, textvariable=self.dir_var, width=40).pack(side="left")
        ttk.Button(dir_frame, text="浏览", command=lambda: self.dir_var.set(
            filedialog.askdirectory() or self.dir_var.get()
        )).pack(side="left", padx=(5, 0))

        btn_frame = ttk.Frame(dlg)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=20)

        def ok():
            site = self.site_var.get().strip()
            name = self.name_var.get().strip()
            url = self.url_var.get().strip()
            d = self.dir_var.get().strip()
            if not name or not url or not d:
                messagebox.showwarning("提示", "请填写完整信息", parent=dlg)
                return
            self.result = {"site": site, "name": name, "url": url, "dir": d}
            dlg.destroy()

        ttk.Button(btn_frame, text="确定", command=ok).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="取消", command=dlg.destroy).pack(side="left", padx=10)

        parent.wait_window(dlg)


class YavApp(JavdbJphooApp):
    """按站点分组的 Yav 桌面界面。"""

    def _build_ui(self):
        self.root.title("Yav · 磁力管理器")
        self.root.geometry("980x720")
        self.root.minsize(820, 580)
        self.root.configure(bg="#f6f8fc")

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f6f8fc")
        style.configure("Title.TLabel", background="#f6f8fc", foreground="#172554",
                        font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Subtle.TLabel", background="#f6f8fc", foreground="#64748b",
                        font=("Microsoft YaHei UI", 10))
        style.configure("Status.TLabel", background="#f6f8fc", foreground="#475569",
                        font=("Microsoft YaHei UI", 9))
        style.configure("Accent.TButton", background="#2563eb", foreground="white",
                        font=("Microsoft YaHei UI", 10, "bold"), padding=(12, 7), relief="flat")
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#cbd5e1")])
        style.configure("Treeview", rowheight=31, font=("Microsoft YaHei UI", 10),
                        background="white", fieldbackground="white", foreground="#1e293b")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"),
                        background="#eaf0fb", foreground="#334155", relief="flat")
        style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#172554")])
        style.configure("TNotebook", background="#f6f8fc", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", "#1d4ed8")])

        header = ttk.Frame(self.root, padding=(20, 16, 20, 10))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Yav", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="私人影视资料馆 · 封面浏览、资料维护与磁力补充", style="Subtle.TLabel").pack(anchor="w", pady=(2, 0))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="nsew")
        self.site_trees = {}
        for site, label in (("javdb", "JavDB"), ("jphoo", "JPHOO")):
            tab = ttk.Frame(self.notebook, padding=10)
            self.notebook.add(tab, text=label)
            tree = ttk.Treeview(tab, columns=("name", "url", "dir"), show="headings", height=7)
            for col, title, width in (("name", "系列名称", 160), ("url", "系列网址", 430), ("dir", "资源保存目录", 290)):
                tree.heading(col, text=title)
                tree.column(col, width=width, anchor="w")
            tree.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=tree.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            tree.configure(yscrollcommand=scrollbar.set)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            self.site_trees[site] = tree

        tools = ttk.Frame(self.root, padding=(20, 0))
        tools.grid(row=2, column=0, sticky="ew")
        ttk.Button(tools, text="打开私人资料馆", command=self.open_library, style="Accent.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="＋ 添加网址", command=self.add_source).pack(side="left", padx=(0, 8))
        ttk.Button(tools, text="编辑", command=self.edit_source).pack(side="left", padx=(0, 5))
        ttk.Button(tools, text="删除", command=self.delete_source).pack(side="left")

        self.browser_var = tk.BooleanVar(value=self.cfg.get("browser_mode", True))
        ttk.Checkbutton(self.root, text="JPHOO 使用浏览器模式（需在 Edge 中登录）", variable=self.browser_var).grid(
            row=3, column=0, padx=20, pady=(9, 3), sticky="w"
        )

        actions = ttk.Frame(self.root, padding=(20, 0))
        actions.grid(row=4, column=0, sticky="ew")
        self.scan_btn = ttk.Button(actions, text="扫描所选系列", command=self.start_scan, style="Accent.TButton")
        self.update_btn = ttk.Button(actions, text="更新所选系列", command=self.start_update, style="Accent.TButton")
        self.export_btn = ttk.Button(actions, text="同步 Excel 台账", command=self.export_updates, style="Accent.TButton")
        for button in (self.scan_btn, self.update_btn, self.export_btn):
            button.pack(side="left", padx=(0, 7))
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.grid(row=5, column=0, padx=20, pady=(12, 0), sticky="ew")
        self.status_label = ttk.Label(self.root, text="就绪", style="Status.TLabel")
        self.status_label.grid(row=6, column=0, padx=20, pady=(4, 7), sticky="w")
        self.log_area = scrolledtext.ScrolledText(self.root, height=13, state="disabled",
                                                  font=("Cascadia Mono", 9), relief="flat", borderwidth=1)
        self.log_area.grid(row=7, column=0, padx=20, pady=(0, 18), sticky="nsew")
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_rowconfigure(7, weight=1)
    def active_site(self):
        return self.notebook.tab(self.notebook.select(), "text").lower()

    def _refresh_list(self):
        for tree in self.site_trees.values():
            for item in tree.get_children():
                tree.delete(item)
        for index, source in enumerate(self.cfg.get("sources", [])):
            tree = self.site_trees.get(source.get("site"))
            if tree:
                tree.insert("", "end", iid=str(index), values=(source.get("name", ""), source.get("url", ""), source.get("dir", "")))

    def _selected_index(self):
        selected = self.site_trees[self.active_site()].selection()
        if not selected:
            messagebox.showwarning("提示", "请先选择一个系列")
            return None
        return int(selected[0])

    def add_source(self):
        dialog = SourceDialog(self.root, title="添加网址", data={"site": self.active_site()})
        if dialog.result:
            self.cfg["sources"].append(dialog.result)
            save_config(self.cfg)
            self._refresh_list()

    def edit_source(self):
        index = self._selected_index()
        if index is None:
            return
        dialog = SourceDialog(self.root, title="编辑网址", data=self.cfg["sources"][index])
        if dialog.result:
            self.cfg["sources"][index] = dialog.result
            save_config(self.cfg)
            self._refresh_list()

    def delete_source(self):
        index = self._selected_index()
        if index is not None and messagebox.askyesno("确认", "确定删除所选系列？"):
            self.cfg["sources"].pop(index)
            save_config(self.cfg)
            self._refresh_list()

    def enable_buttons(self, enabled=True):
        state = "normal" if enabled else "disabled"
        self.root.after(0, lambda: [button.config(state=state) for button in (self.scan_btn, self.update_btn, self.export_btn)])

    def _run_selected_source(self, source_index, runner):
        # 任务只使用用户当前选中的一条来源，避免误跑整个站点标签页。
        self._run_sources = [self.cfg["sources"][source_index]]
        try:
            runner(self)
        finally:
            self._run_sources = None
    def start_scan(self):
        source_index = self._selected_index()
        if source_index is None or self.is_running:
            return
        self.is_running = True
        self.cancel_event.clear()
        self.enable_buttons(False)
        self.log_area.config(state="normal")
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state="disabled")
        self._worker = threading.Thread(
            target=lambda: self._run_selected_source(source_index, JavdbJphooApp._run_scan), daemon=True
        )
        self._worker.start()

    def start_update(self):
        source_index = self._selected_index()
        if source_index is None or self.is_running:
            return
        self.is_running = True
        self.cancel_event.clear()
        self.enable_buttons(False)
        self.log_area.config(state="normal")
        self.log_area.delete(1.0, tk.END)
        self.log_area.config(state="disabled")
        self._worker = threading.Thread(
            target=lambda: self._run_selected_source(source_index, JavdbJphooApp._run_update), daemon=True
        )
        self._worker.start()
    def open_library(self):
        window = getattr(self, "_library_window", None)
        if window and window.winfo_exists():
            window.deiconify(); window.lift(); window.refresh(); return
        self._library_window = LibraryWindow(self.root, self.library, self.enrich_series)

    def enrich_series(self, series, done_callback=None):
        if self.is_running:
            messagebox.showwarning("任务进行中", "请等待当前扫描或更新任务结束后，再补全资料。")
            return
        source = next((item for item in self.cfg.get("sources", []) if item.get("name") == series), None)
        if not source:
            messagebox.showwarning("未找到系列", f"没有找到 {series} 的来源配置。")
            return
        records = self.library.pending_metadata(series)
        if not records:
            messagebox.showinfo("资料已完整", f"{series} 当前没有待补全封面或资料的影片。")
            return
        self.is_running = True
        self.cancel_event.clear()
        self.enable_buttons(False)
        def worker():
            ctx = None
            try:
                if source.get("site") == "jphoo":
                    ctx = self._init_playwright()
                total = len(records)
                self.log(f"[资料库] 开始补全 {series}：{total} 部影片")
                for index, record in enumerate(records, 1):
                    if self.cancel_event.is_set(): break
                    self.set_progress(index - 1, total)
                    self.set_status(f"[资料库] {series} {index}/{total}")
                    if source.get("site") == "javdb":
                        metadata = JavdbScraper.get_metadata(record["source_url"], series, self.log)
                    elif source.get("site") == "jphoo":
                        metadata = JphooScraper.get_metadata(record["source_url"], series, ctx, getattr(self, "_jphoo_page", None), self.log)
                    else:
                        metadata = WorkMetadata(site=source.get("site", ""), series=series, source_url=record["source_url"])
                    work_id = self.library.upsert_work(metadata, cache_cover=True)
                    self.log(f"  [资料库] {index}/{total} 封面：{metadata.title[:40] or '待补全'}")
                self.root.after(0, lambda: messagebox.showinfo("资料补全完成", f"{series} 已完成资料与封面补全任务。"))
            except Exception as exc:
                self.log(f"[资料库] 补全失败: {exc}")
            finally:
                self._close_playwright()
                self.is_running = False
                self.enable_buttons(True)
                self.set_progress(0)
                self.set_status("就绪")
                if done_callback: self.root.after(0, done_callback)
        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def export_updates(self):
        try:
            path, added = sync_master_ledger(self.cfg)
            self.log(f"[Excel] 已同步主台账，新增 {added} 行：{path}")
            messagebox.showinfo("Excel 台账已同步", f"新增 {added} 行\n{path}")
        except ImportError:
            messagebox.showerror("缺少依赖", "请先运行：pip install -r requirements.txt")
        except Exception as exc:
            messagebox.showerror("同步失败", str(exc))
# ─── 入口 ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    root = tk.Tk()
    app = YavApp(root)
    root.mainloop()




















