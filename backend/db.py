"""Yav V2 的最小 SQLite 数据层。"""
from __future__ import annotations
import json, re, sqlite3, unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    text = re.sub(r"[‐‑‒–—―_]+", "-", text); text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s*(?:\||[-–—])\s*(?:javdb|jphoo)\s*$", "", text).strip()

def extract_btih(magnet: str) -> str:
    for value in parse_qs(urlparse(magnet).query).get("xt", []):
        found = re.fullmatch(r"urn:btih:([A-Za-z0-9]+)", value, re.I)
        if found: return found.group(1).upper()
    found = re.search(r"urn:btih:([A-Za-z0-9]+)", magnet or "", re.I)
    if found: return found.group(1).upper()
    raise ValueError("磁链缺少有效 BTIH")

class LibraryDatabase:
    def __init__(self, path): self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self.initialize()
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path); db.row_factory=sqlite3.Row; db.execute("PRAGMA foreign_keys=ON")
        try: yield db; db.commit()
        finally: db.close()
    def initialize(self):
        with self.connect() as db: db.executescript("""
CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL); INSERT OR IGNORE INTO schema_meta VALUES('schema_version','1');
CREATE TABLE IF NOT EXISTS movies(id INTEGER PRIMARY KEY,title TEXT NOT NULL,normalized_title TEXT NOT NULL,cover_url TEXT NOT NULL DEFAULT '',cover_path TEXT NOT NULL DEFAULT '',studio TEXT NOT NULL DEFAULT '',series TEXT NOT NULL DEFAULT '',release_date TEXT NOT NULL DEFAULT '',duration_minutes INTEGER,favorite INTEGER NOT NULL DEFAULT 0,manual_fields TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actresses(id INTEGER PRIMARY KEY,name TEXT NOT NULL,normalized_name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS movie_actresses(movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,actress_id INTEGER NOT NULL REFERENCES actresses(id) ON DELETE CASCADE,PRIMARY KEY(movie_id,actress_id));
CREATE TABLE IF NOT EXISTS source_entries(id INTEGER PRIMARY KEY,movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,source TEXT NOT NULL,source_url TEXT NOT NULL,source_movie_id TEXT NOT NULL DEFAULT '',source_title TEXT NOT NULL DEFAULT '',cover_url TEXT NOT NULL DEFAULT '',studio TEXT NOT NULL DEFAULT '',series TEXT NOT NULL DEFAULT '',release_date TEXT NOT NULL DEFAULT '',duration_minutes INTEGER,last_checked_at TEXT NOT NULL,UNIQUE(source,source_url));
CREATE TABLE IF NOT EXISTS magnets(id INTEGER PRIMARY KEY,movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,magnet TEXT NOT NULL,btih TEXT NOT NULL,size_bytes INTEGER,discovered_at TEXT NOT NULL,UNIQUE(movie_id,btih));
CREATE TABLE IF NOT EXISTS magnet_sources(magnet_id INTEGER NOT NULL REFERENCES magnets(id) ON DELETE CASCADE,source_entry_id INTEGER NOT NULL REFERENCES source_entries(id) ON DELETE CASCADE,PRIMARY KEY(magnet_id,source_entry_id));
CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(normalized_title); CREATE INDEX IF NOT EXISTS idx_magnets_movie ON magnets(movie_id);
""")
    def now(self): return datetime.now().astimezone().isoformat(timespec="seconds")
    def add_or_update_movie(self,title,studio="",series="",release_date="",duration_minutes=None,cover_url="",actresses=None,source="",source_url="",source_movie_id=""):
        title=(title or "").strip()
        if not title: raise ValueError("影片名不能为空")
        normalized,now=normalize_title(title),self.now(); fields={"studio":studio.strip(),"series":series.strip(),"release_date":release_date.strip(),"cover_url":cover_url.strip(),"duration_minutes":duration_minutes}
        with self.connect() as db:
            rows=db.execute("SELECT * FROM movies WHERE normalized_title=?",(normalized,)).fetchall()
            movie=next((r for r in rows if not any(r[k] and v not in (None,'') and r[k]!=v for k,v in fields.items() if k in ('studio','series','release_date'))),None)
            if movie: movie_id=movie['id']; manual=set(json.loads(movie['manual_fields'])); updates={k:(v if not movie[k] and k not in manual and v not in (None,'') else movie[k]) for k,v in fields.items()}; db.execute("UPDATE movies SET cover_url=?,studio=?,series=?,release_date=?,duration_minutes=?,updated_at=? WHERE id=?",(updates['cover_url'],updates['studio'],updates['series'],updates['release_date'],updates['duration_minutes'],now,movie_id))
            else: movie_id=db.execute("INSERT INTO movies(title,normalized_title,cover_url,studio,series,release_date,duration_minutes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(title,normalized,cover_url,studio,series,release_date,duration_minutes,now,now)).lastrowid
            for name in actresses or []:
                name=re.sub(r'\s+',' ',name or '').strip()
                if name: db.execute("INSERT OR IGNORE INTO actresses(name,normalized_name) VALUES(?,?)",(name,normalize_title(name))); aid=db.execute("SELECT id FROM actresses WHERE normalized_name=?",(normalize_title(name),)).fetchone()['id']; db.execute("INSERT OR IGNORE INTO movie_actresses VALUES(?,?)",(movie_id,aid))
            if source and source_url: db.execute("INSERT INTO source_entries(movie_id,source,source_url,source_movie_id,source_title,cover_url,studio,series,release_date,duration_minutes,last_checked_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,source_url) DO UPDATE SET movie_id=excluded.movie_id,last_checked_at=excluded.last_checked_at",(movie_id,source,source_url,source_movie_id,title,cover_url,studio,series,release_date,duration_minutes,now))
        return movie_id
    def add_magnet(self,movie_id,magnet,source,source_url,size_bytes=None):
        with self.connect() as db:
            entry=db.execute("SELECT id FROM source_entries WHERE source=? AND source_url=?",(source,source_url)).fetchone()
            if not entry: raise ValueError("磁链必须关联已保存的来源页面")
            btih=extract_btih(magnet); db.execute("INSERT OR IGNORE INTO magnets(movie_id,magnet,btih,size_bytes,discovered_at) VALUES(?,?,?,?,?)",(movie_id,magnet,btih,size_bytes,self.now())); mid=db.execute("SELECT id FROM magnets WHERE movie_id=? AND btih=?",(movie_id,btih)).fetchone()['id']; db.execute("INSERT OR IGNORE INTO magnet_sources VALUES(?,?)",(mid,entry['id'])); return mid
    def list_movies(self,query="",limit=60):
        with self.connect() as db: return [dict(r) for r in db.execute("SELECT m.*,(SELECT COUNT(*) FROM magnets x WHERE x.movie_id=m.id) magnet_count FROM movies m WHERE m.title LIKE ? OR m.normalized_title LIKE ? ORDER BY favorite DESC,updated_at DESC LIMIT ?",(f'%{query}%',f'%{normalize_title(query)}%',limit))]
