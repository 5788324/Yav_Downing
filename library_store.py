"""Yav 私人影视资料馆的本地 SQLite 数据层。"""
from __future__ import annotations

import csv
import hashlib
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass
class WorkMetadata:
    site: str
    series: str
    source_url: str
    title: str = ""
    code: str = ""
    publisher: str = ""
    release_date: str = ""
    cover_url: str = ""
    actors: list[str] = field(default_factory=list)
    magnet: str = ""
    size_gb: float = 0.0


def _text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _pick_meta(soup: BeautifulSoup, *keys: str) -> str:
    for key in keys:
        element = soup.select_one(f'meta[property="{key}"], meta[name="{key}"]')
        if element and element.get("content"):
            return _text(element["content"])
    return ""


def parse_public_metadata(html: str, page_url: str, site: str, series: str) -> WorkMetadata:
    """用容错规则解析公开详情页；站点变化时可以单独新增专用解析器。"""
    soup = BeautifulSoup(html or "", "lxml")
    title = _pick_meta(soup, "og:title", "twitter:title")
    if not title and soup.title:
        title = _text(soup.title.get_text(" "))
    title = re.split(r"\s*[|\-]\s*(?:JavDB|JPHOO|磁力链接).*$", title, flags=re.I)[0].strip()
    cover = _pick_meta(soup, "og:image", "twitter:image")
    if not cover:
        image = soup.select_one(".video-cover img, .cover img, main img[src]")
        cover = image.get("src", "") if image else ""
    cover = urljoin(page_url, cover) if cover else ""

    page_text = _text(soup.get_text(" "))
    code = ""
    release_date = ""
    publisher = ""
    date_match = re.search(r"(?:發行日期|发行日期|發行時間|发行时间|日期)\s*[:：]?\s*(\d{4}[./-]\d{1,2}[./-]\d{1,2})", page_text, re.I)
    if date_match:
        release_date = date_match.group(1).replace("/", "-").replace(".", "-")
    code_match = re.search(r"(?:識別碼|识别码|番號|番号|ID)\s*[:：]?\s*([A-Za-z0-9_-]{3,})", page_text, re.I)
    if code_match:
        code = code_match.group(1).upper()

    actors, publishers = [], []
    for link in soup.select("a[href]"):
        href, label = link.get("href", ""), _text(link.get_text(" "))
        if not label:
            continue
        lowered = href.lower()
        if any(part in lowered for part in ("/actor", "/performer")):
            actors.append(label)
        elif any(part in lowered for part in ("/maker", "/publisher", "/studio")):
            publishers.append(label)
    if publishers:
        publisher = publishers[0]
    return WorkMetadata(site=site, series=series, source_url=page_url, title=title,
                        code=code, publisher=publisher, release_date=release_date,
                        cover_url=cover, actors=list(dict.fromkeys(actors)))


class LibraryStore:
    def __init__(self, resource_root: str):
        self.root = Path(resource_root) / "_Yav资源库"
        self.covers_dir = self.root / "covers"
        self.db_path = self.root / "library.db"
        self.root.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS works (
              id INTEGER PRIMARY KEY,
              site TEXT NOT NULL, series TEXT NOT NULL, source_url TEXT NOT NULL UNIQUE,
              code_auto TEXT DEFAULT '', title_auto TEXT DEFAULT '', publisher_auto TEXT DEFAULT '',
              release_date_auto TEXT DEFAULT '', cover_url_auto TEXT DEFAULT '', cover_path TEXT DEFAULT '',
              cover_status TEXT DEFAULT '待抓取', favorite INTEGER DEFAULT 0,
              code_manual TEXT DEFAULT '', title_manual TEXT DEFAULT '', publisher_manual TEXT DEFAULT '',
              release_date_manual TEXT DEFAULT '', cover_url_manual TEXT DEFAULT '',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actors (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS work_actors (
              work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
              actor_id INTEGER NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
              source TEXT NOT NULL DEFAULT 'auto', PRIMARY KEY(work_id, actor_id)
            );
            CREATE TABLE IF NOT EXISTS magnets (
              id INTEGER PRIMARY KEY, work_id INTEGER NOT NULL REFERENCES works(id) ON DELETE CASCADE,
              magnet TEXT NOT NULL, btih TEXT NOT NULL, size_gb REAL DEFAULT 0,
              discovered_at TEXT NOT NULL, source_site TEXT DEFAULT '', UNIQUE(work_id, btih)
            );
            CREATE INDEX IF NOT EXISTS idx_works_series ON works(series);
            CREATE INDEX IF NOT EXISTS idx_works_site ON works(site);
            CREATE INDEX IF NOT EXISTS idx_magnets_work ON magnets(work_id);
            """)

    @staticmethod
    def _now(): return time.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _btih(magnet: str) -> str:
        found = re.search(r"urn:btih:([a-zA-Z0-9]+)", magnet or "", re.I)
        return found.group(1).lower() if found else hashlib.sha1((magnet or "").encode()).hexdigest()

    def upsert_work(self, metadata: WorkMetadata, cache_cover: bool = False) -> int:
        now = self._now()
        with self._connect() as db:
            row = db.execute("SELECT id FROM works WHERE source_url=?", (metadata.source_url,)).fetchone()
            values = (metadata.site, metadata.series, metadata.code, metadata.title, metadata.publisher,
                      metadata.release_date, metadata.cover_url, now)
            if row:
                work_id = row["id"]
                db.execute("""UPDATE works SET site=?, series=?, code_auto=CASE WHEN ?<>'' THEN ? ELSE code_auto END,
                    title_auto=CASE WHEN ?<>'' THEN ? ELSE title_auto END,
                    publisher_auto=CASE WHEN ?<>'' THEN ? ELSE publisher_auto END,
                    release_date_auto=CASE WHEN ?<>'' THEN ? ELSE release_date_auto END,
                    cover_url_auto=CASE WHEN ?<>'' THEN ? ELSE cover_url_auto END, updated_at=? WHERE id=?""",
                    (metadata.site, metadata.series, metadata.code, metadata.code, metadata.title, metadata.title,
                     metadata.publisher, metadata.publisher, metadata.release_date, metadata.release_date,
                     metadata.cover_url, metadata.cover_url, now, work_id))
            else:
                cur = db.execute("""INSERT INTO works(site,series,source_url,code_auto,title_auto,publisher_auto,
                    release_date_auto,cover_url_auto,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (metadata.site, metadata.series, metadata.source_url, metadata.code, metadata.title,
                     metadata.publisher, metadata.release_date, metadata.cover_url, now, now))
                work_id = cur.lastrowid
            self._set_actors(db, work_id, metadata.actors, "auto")
            if metadata.magnet:
                self._add_magnet(db, work_id, metadata.magnet, metadata.size_gb, metadata.site)
        if cache_cover and metadata.cover_url:
            self.cache_cover(work_id)
        return work_id

    def _set_actors(self, db, work_id: int, actors: Iterable[str], source: str):
        clean = list(dict.fromkeys(_text(a) for a in actors if _text(a)))
        if not clean: return
        db.execute("DELETE FROM work_actors WHERE work_id=? AND source=?", (work_id, source))
        for actor in clean:
            db.execute("INSERT OR IGNORE INTO actors(name) VALUES(?)", (actor,))
            actor_id = db.execute("SELECT id FROM actors WHERE name=?", (actor,)).fetchone()["id"]
            db.execute("INSERT OR IGNORE INTO work_actors(work_id,actor_id,source) VALUES(?,?,?)", (work_id, actor_id, source))

    def _add_magnet(self, db, work_id, magnet, size_gb, source_site):
        db.execute("INSERT OR IGNORE INTO magnets(work_id,magnet,btih,size_gb,discovered_at,source_site) VALUES(?,?,?,?,?,?)",
                   (work_id, magnet, self._btih(magnet), float(size_gb or 0), self._now(), source_site))

    def add_magnet_by_url(self, source_url, magnet, size_gb=0, source_site=""):
        with self._connect() as db:
            row = db.execute("SELECT id FROM works WHERE source_url=?", (source_url,)).fetchone()
            if row: self._add_magnet(db, row["id"], magnet, size_gb, source_site)

    def migrate_csv(self, sources: list[dict]) -> int:
        """首次/增量导入旧 CSV；单个事务完成，避免启动时逐行打开数据库。"""
        count = 0
        now = self._now()
        with self._connect() as db:
            for source in sources:
                path = Path(source.get("dir", "")) / "_全部磁力汇总表.csv"
                if not path.exists(): continue
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.reader(f):
                        if len(row) < 5 or row[0] == "番号/ID": continue
                        code,title,size,magnet,url = row[:5]
                        if not url: continue
                        try: size = float(size or 0)
                        except ValueError: size = 0
                        db.execute("""INSERT INTO works(site,series,source_url,code_auto,title_auto,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_url) DO UPDATE SET
                            site=excluded.site,series=excluded.series,
                            code_auto=CASE WHEN excluded.code_auto<>'' THEN excluded.code_auto ELSE works.code_auto END,
                            title_auto=CASE WHEN excluded.title_auto<>'' THEN excluded.title_auto ELSE works.title_auto END,
                            updated_at=excluded.updated_at""",
                            (source.get("site", ""),source.get("name", ""),url,code,title,now,now))
                        if magnet:
                            work_id=db.execute("SELECT id FROM works WHERE source_url=?",(url,)).fetchone()["id"]
                            self._add_magnet(db,work_id,magnet,size,source.get("site", ""))
                        count += 1
        return count

    def cache_cover(self, work_id: int) -> bool:
        with self._connect() as db:
            work = db.execute("SELECT COALESCE(NULLIF(cover_url_manual,''),cover_url_auto) cover_url FROM works WHERE id=?", (work_id,)).fetchone()
        if not work or not work["cover_url"]:
            self._cover_status(work_id, "无封面网址"); return False
        try:
            response = requests.get(work["cover_url"], timeout=20, headers={"User-Agent":"Mozilla/5.0"})
            response.raise_for_status()
            suffix = ".jpg" if "jpeg" in response.headers.get("content-type", "") else ".png"
            target = self.covers_dir / f"{work_id}{suffix}"
            target.write_bytes(response.content)
            with self._connect() as db: db.execute("UPDATE works SET cover_path=?,cover_status='已缓存',updated_at=? WHERE id=?", (str(target), self._now(), work_id))
            return True
        except Exception as exc:
            self._cover_status(work_id, f"下载失败: {str(exc)[:80]}"); return False

    def _cover_status(self, work_id, status):
        with self._connect() as db: db.execute("UPDATE works SET cover_status=?,updated_at=? WHERE id=?", (status, self._now(), work_id))

    def query_works(self, keyword="", series="", site="", favorite=False, has_magnet=None, limit=60):
        sql = """SELECT w.*, COALESCE(NULLIF(w.title_manual,''),w.title_auto) title,
                 COALESCE(NULLIF(w.publisher_manual,''),w.publisher_auto) publisher,
                 COALESCE(NULLIF(w.release_date_manual,''),w.release_date_auto) release_date,
                 (SELECT COUNT(*) FROM magnets m WHERE m.work_id=w.id) magnet_count,
                 GROUP_CONCAT(a.name, '、') actors FROM works w
                 LEFT JOIN work_actors wa ON wa.work_id=w.id LEFT JOIN actors a ON a.id=wa.actor_id WHERE 1=1"""
        values=[]
        if keyword:
            sql += " AND (w.title_auto LIKE ? OR w.title_manual LIKE ? OR a.name LIKE ? OR w.publisher_auto LIKE ? OR w.series LIKE ?)"; values += [f"%{keyword}%"]*5
        if series: sql += " AND w.series=?"; values.append(series)
        if site: sql += " AND w.site=?"; values.append(site)
        if favorite: sql += " AND w.favorite=1"
        sql += " GROUP BY w.id"
        if has_magnet is True: sql += " HAVING magnet_count>0"
        if has_magnet is False: sql += " HAVING magnet_count=0"
        sql += " ORDER BY w.favorite DESC, w.release_date_auto DESC, w.id DESC LIMIT ?"; values.append(limit)
        with self._connect() as db: return [dict(row) for row in db.execute(sql, values)]

    def get_work(self, work_id):
        with self._connect() as db:
            row=db.execute("SELECT w.*,COALESCE(NULLIF(title_manual,''),title_auto) title,COALESCE(NULLIF(publisher_manual,''),publisher_auto) publisher,COALESCE(NULLIF(release_date_manual,''),release_date_auto) release_date FROM works w WHERE id=?",(work_id,)).fetchone()
            if not row:return None
            out=dict(row)
            out['actors']=[r['name'] for r in db.execute("SELECT a.name FROM actors a JOIN work_actors wa ON wa.actor_id=a.id WHERE wa.work_id=? ORDER BY a.name",(work_id,))]
            out['magnets']=[dict(r) for r in db.execute("SELECT * FROM magnets WHERE work_id=? ORDER BY size_gb DESC, id DESC",(work_id,))]
            return out

    def update_manual(self, work_id, title, actors, series, publisher, release_date, cover_url, favorite):
        with self._connect() as db:
            db.execute("UPDATE works SET title_manual=?,series=?,publisher_manual=?,release_date_manual=?,cover_url_manual=?,favorite=?,updated_at=? WHERE id=?",(title,series,publisher,release_date,cover_url,int(bool(favorite)),self._now(),work_id))
            self._set_actors(db, work_id, [x.strip() for x in actors.split(',')], "manual")
        if cover_url: self.cache_cover(work_id)

    def series_names(self):
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT DISTINCT series FROM works WHERE series<>'' ORDER BY series")]

    def pending_metadata(self, series, limit=0):
        sql = "SELECT * FROM works WHERE series=? AND (cover_status<>'已缓存' OR title_auto='' OR release_date_auto='') ORDER BY id"
        if limit: sql += " LIMIT ?"
        with self._connect() as db:
            rows=db.execute(sql, (series, limit) if limit else (series,)).fetchall()
            return [dict(row) for row in rows]

    def stats(self):
        with self._connect() as db:
            return dict(db.execute("SELECT COUNT(*) works, SUM(CASE WHEN cover_status='已缓存' THEN 1 ELSE 0 END) covers, SUM(CASE WHEN favorite=1 THEN 1 ELSE 0 END) favorites FROM works").fetchone())
