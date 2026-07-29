"""Yav V2 的 SQLite 数据层。"""
from __future__ import annotations

import base64
import binascii
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

UNKNOWN_VALUE = "__unknown__"


@dataclass(frozen=True)
class MagnetSaveResult:
    magnet_id: int
    created: bool
    source_added: bool
    size_updated: bool


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    text = re.sub(r"[‐‑‒–—―_]+", "-", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s*(?:\||[-–—])\s*(?:javdb|jphoo)\s*$", "", text).strip()


INVALID_METADATA_VALUES = frozenset({"首页", "上一页", "下一页", "登录", "注册", "查看更多", "影片信息", "演员列表", "磁力下载", "返回顶部", "查看全部作品", "推荐", "推薦", "有碼", "有码", "歐美", "欧美", "演員", "演员", "無碼", "无码"})

def is_invalid_metadata(value: str) -> bool:
    clean = re.sub(r"\s+", " ", value or "").strip()
    return not clean or clean in INVALID_METADATA_VALUES or (clean.startswith("查看") and clean.endswith("全部作品"))

def normalize_btih(value: str) -> str:
    token = (value or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{40}", token):
        return token.upper()
    if re.fullmatch(r"[A-Z2-7a-z]{32}", token):
        try:
            return base64.b32decode(token.upper()).hex().upper()
        except (binascii.Error, ValueError) as exc:
            raise ValueError("磁链 BTIH Base32 无效") from exc
    raise ValueError("磁链 BTIH 必须是 40 位十六进制或 32 位 Base32")

def extract_btih(magnet: str) -> str:
    for value in parse_qs(urlparse(magnet).query).get("xt", []):
        found = re.fullmatch(r"urn:btih:([^&/]+)", value, re.I)
        if found: return normalize_btih(found.group(1))
    found = re.search(r"urn:btih:([^&\s/]+)", magnet or "", re.I)
    if found: return normalize_btih(found.group(1))
    raise ValueError("磁链缺少有效 BTIH")

class LibraryDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def initialize(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_meta VALUES('schema_version','1');

                CREATE TABLE IF NOT EXISTS movies(
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    cover_url TEXT NOT NULL DEFAULT '',
                    cover_path TEXT NOT NULL DEFAULT '',
                    studio TEXT NOT NULL DEFAULT '',
                    series TEXT NOT NULL DEFAULT '',
                    release_date TEXT NOT NULL DEFAULT '',
                    duration_minutes INTEGER,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    manual_fields TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actresses(
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS movie_actresses(
                    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                    actress_id INTEGER NOT NULL REFERENCES actresses(id) ON DELETE CASCADE,
                    PRIMARY KEY(movie_id,actress_id)
                );
                CREATE TABLE IF NOT EXISTS source_entries(
                    id INTEGER PRIMARY KEY,
                    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_movie_id TEXT NOT NULL DEFAULT '',
                    source_title TEXT NOT NULL DEFAULT '',
                    cover_url TEXT NOT NULL DEFAULT '',
                    studio TEXT NOT NULL DEFAULT '',
                    series TEXT NOT NULL DEFAULT '',
                    release_date TEXT NOT NULL DEFAULT '',
                    duration_minutes INTEGER,
                    last_checked_at TEXT NOT NULL,
                    UNIQUE(source,source_url)
                );
                CREATE TABLE IF NOT EXISTS magnets(
                    id INTEGER PRIMARY KEY,
                    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                    magnet TEXT NOT NULL,
                    btih TEXT NOT NULL,
                    size_bytes INTEGER,
                    discovered_at TEXT NOT NULL,
                    UNIQUE(movie_id,btih)
                );
                CREATE TABLE IF NOT EXISTS magnet_sources(
                    magnet_id INTEGER NOT NULL REFERENCES magnets(id) ON DELETE CASCADE,
                    source_entry_id INTEGER NOT NULL REFERENCES source_entries(id) ON DELETE CASCADE,
                    PRIMARY KEY(magnet_id,source_entry_id)
                );

                CREATE INDEX IF NOT EXISTS idx_movies_title ON movies(normalized_title);
                CREATE INDEX IF NOT EXISTS idx_movies_studio ON movies(studio);
                CREATE INDEX IF NOT EXISTS idx_movies_series ON movies(series);
                CREATE INDEX IF NOT EXISTS idx_movies_favorite ON movies(favorite);
                CREATE INDEX IF NOT EXISTS idx_movie_actresses_actress ON movie_actresses(actress_id,movie_id);
                CREATE INDEX IF NOT EXISTS idx_source_entries_movie ON source_entries(movie_id,source);
                CREATE INDEX IF NOT EXISTS idx_magnets_movie ON magnets(movie_id);
                CREATE INDEX IF NOT EXISTS idx_magnet_sources_entry ON magnet_sources(source_entry_id,magnet_id);CREATE TABLE IF NOT EXISTS source_series(
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, name TEXT NOT NULL, url TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
 last_scanned_at TEXT NOT NULL DEFAULT '', last_completed_page INTEGER NOT NULL DEFAULT 0,
 UNIQUE(source,url));
CREATE TABLE IF NOT EXISTS scan_runs(
 id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES source_series(id) ON DELETE CASCADE,
 status TEXT NOT NULL, current_page INTEGER NOT NULL DEFAULT 0, discovered INTEGER NOT NULL DEFAULT 0,
 new_movies INTEGER NOT NULL DEFAULT 0, new_magnets INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
 message TEXT NOT NULL DEFAULT '', started_at TEXT NOT NULL, finished_at TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_source_series_source ON source_series(source,enabled);
CREATE TABLE IF NOT EXISTS scan_failures(
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, series_id INTEGER NOT NULL REFERENCES source_series(id) ON DELETE CASCADE,
 source_url TEXT NOT NULL, page INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
 last_error TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT NOT NULL DEFAULT '',
 UNIQUE(source,series_id,source_url));
CREATE INDEX IF NOT EXISTS idx_scan_failures_unresolved ON scan_failures(source,series_id,resolved_at,page,id);
                """
            )
            for statement in (
                "ALTER TABLE source_series ADD COLUMN profile_dir TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE scan_runs ADD COLUMN processed_count INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE scan_runs ADD COLUMN matched_current INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE scan_runs ADD COLUMN attached_other_movies INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE scan_runs ADD COLUMN unmatched_candidates INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE scan_runs ADD COLUMN last_error TEXT NOT NULL DEFAULT ''",
            ):
                try:
                    db.execute(statement)
                except sqlite3.OperationalError:
                    pass
            db.execute("UPDATE schema_meta SET value='4' WHERE key='schema_version'")
            db.execute("UPDATE scan_runs SET status='interrupted', finished_at=? WHERE status IN ('starting','running','stopping')", (self.now(),))
            invalid = tuple(sorted(INVALID_METADATA_VALUES))
            placeholders = ",".join("?" for _ in invalid)
            db.execute(f"DELETE FROM movie_actresses WHERE actress_id IN (SELECT id FROM actresses WHERE name IN ({placeholders})) AND movie_id IN (SELECT id FROM movies WHERE manual_fields NOT LIKE '%\"actresses\"%')", invalid)
            db.execute("DELETE FROM actresses WHERE NOT EXISTS (SELECT 1 FROM movie_actresses WHERE movie_actresses.actress_id=actresses.id)")

    @staticmethod
    def now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _manual_fields(row: sqlite3.Row | dict[str, Any]) -> set[str]:
        try:
            return set(json.loads(row["manual_fields"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return set()

    def movie_import_exists(self, title: str, source: str, source_url: str) -> bool:
        """来源页或同名聚合片已存在时，扫描统计不再误报为新增。"""
        with self.connect() as db:
            if source and source_url and db.execute("SELECT 1 FROM source_entries WHERE source=? AND source_url=?", (source, source_url)).fetchone():
                return True
            return bool(db.execute("SELECT 1 FROM movies WHERE normalized_title=?", (normalize_title(title),)).fetchone())
    def add_or_update_movie(
        self,
        title,
        studio="",
        series="",
        release_date="",
        duration_minutes=None,
        cover_url="",
        actresses=None,
        source="",
        source_url="",
        source_movie_id="",
    ):
        title = (title or "").strip()
        if not title:
            raise ValueError("影片名不能为空")
        normalized, now = normalize_title(title), self.now()
        fields = {
            "studio": "" if is_invalid_metadata(studio) else (studio or "").strip(),
            "series": "" if is_invalid_metadata(series) else (series or "").strip(),
            "release_date": (release_date or "").strip(),
            "cover_url": (cover_url or "").strip(),
            "duration_minutes": duration_minutes,
        }
        with self.connect() as db:
            source_movie = None
            if source and source_url:
                source_movie = db.execute(
                    "SELECT m.* FROM source_entries se JOIN movies m ON m.id=se.movie_id WHERE se.source=? AND se.source_url=?",
                    (source, source_url),
                ).fetchone()
            rows = db.execute(
                "SELECT * FROM movies WHERE normalized_title=?", (normalized,)
            ).fetchall()
            movie = source_movie or next(
                (
                    row
                    for row in rows
                    if not any(
                        row[key] and value not in (None, "") and row[key] != value
                        for key, value in fields.items()
                        if key in ("studio", "series", "release_date")
                    )
                ),
                None,
            )
            if movie:
                movie_id = movie["id"]
                manual = self._manual_fields(movie)
                # 已绑定来源页重新解析到更正标题时，只在没有人工标题、没有其他来源页且不与现有影片冲突时更新。
                if source_movie and title != movie["title"] and "title" not in manual:
                    source_count = db.execute("SELECT COUNT(*) FROM source_entries WHERE movie_id=?", (movie_id,)).fetchone()[0]
                    title_conflict = db.execute("SELECT 1 FROM movies WHERE normalized_title=? AND id<>?", (normalized, movie_id)).fetchone()
                    if source_count == 1 and not title_conflict:
                        db.execute("UPDATE movies SET title=?,normalized_title=?,updated_at=? WHERE id=?", (title, normalized, now, movie_id))
                updates = {
                    key: (
                        value
                        if (not movie[key] or (key in {"studio", "series", "cover_url"} and is_invalid_metadata(movie[key])))
                        and key not in manual
                        and value not in (None, "")
                        else movie[key]
                    )
                    for key, value in fields.items()
                }
                db.execute(
                    """UPDATE movies
                       SET cover_url=?,studio=?,series=?,release_date=?,duration_minutes=?,updated_at=?
                       WHERE id=?""",
                    (
                        updates["cover_url"],
                        updates["studio"],
                        updates["series"],
                        updates["release_date"],
                        updates["duration_minutes"],
                        now,
                        movie_id,
                    ),
                )
            else:
                movie_id = db.execute(
                    """INSERT INTO movies(
                           title,normalized_title,cover_url,studio,series,release_date,
                           duration_minutes,created_at,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        title,
                        normalized,
                        fields["cover_url"],
                        fields["studio"],
                        fields["series"],
                        fields["release_date"],
                        fields["duration_minutes"],
                        now,
                        now,
                    ),
                ).lastrowid
                manual = set()

            for name in ([] if "actresses" in manual else (actresses or [])):
                name = re.sub(r"\s+", " ", name or "").strip()
                if not name or is_invalid_metadata(name):
                    continue
                normalized_name = normalize_title(name)
                db.execute(
                    "INSERT OR IGNORE INTO actresses(name,normalized_name) VALUES(?,?)",
                    (name, normalized_name),
                )
                actress_id = db.execute(
                    "SELECT id FROM actresses WHERE normalized_name=?",
                    (normalized_name,),
                ).fetchone()["id"]
                db.execute(
                    "INSERT OR IGNORE INTO movie_actresses VALUES(?,?)",
                    (movie_id, actress_id),
                )

            if source and source_url:
                db.execute(
                    """INSERT INTO source_entries(
                           movie_id,source,source_url,source_movie_id,source_title,cover_url,
                           studio,series,release_date,duration_minutes,last_checked_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(source,source_url) DO UPDATE SET
                           movie_id=excluded.movie_id,
                           source_movie_id=excluded.source_movie_id,
                           source_title=excluded.source_title,
                           cover_url=excluded.cover_url,
                           studio=excluded.studio,
                           series=excluded.series,
                           release_date=excluded.release_date,
                           duration_minutes=excluded.duration_minutes,
                           last_checked_at=excluded.last_checked_at""",
                    (
                        movie_id,
                        source,
                        source_url,
                        source_movie_id,
                        title,
                        cover_url,
                        studio,
                        series,
                        release_date,
                        duration_minutes,
                        now,
                    ),
                )
        return movie_id

    def add_magnet(self, movie_id, magnet, source, source_url, size_bytes=None) -> MagnetSaveResult:
        with self.connect() as db:
            entry = db.execute("SELECT id FROM source_entries WHERE source=? AND source_url=?", (source, source_url)).fetchone()
            if not entry:
                raise ValueError("磁链必须关联已保存的来源页面")
            btih = extract_btih(magnet)
            existing = db.execute("SELECT id,size_bytes FROM magnets WHERE movie_id=? AND btih=?", (movie_id, btih)).fetchone()
            created = existing is None
            if created:
                magnet_id = db.execute("INSERT INTO magnets(movie_id,magnet,btih,size_bytes,discovered_at) VALUES(?,?,?,?,?)", (movie_id,magnet,btih,size_bytes,self.now())).lastrowid
                old_size = None
            else:
                magnet_id, old_size = existing["id"], existing["size_bytes"]
            size_updated = bool(not created and (not old_size or old_size <= 0) and size_bytes and size_bytes > 0)
            if size_updated:
                db.execute("UPDATE magnets SET size_bytes=? WHERE id=?", (size_bytes, magnet_id))
            cursor = db.execute("INSERT OR IGNORE INTO magnet_sources VALUES(?,?)", (magnet_id, entry["id"]))
            return MagnetSaveResult(magnet_id=magnet_id, created=created, source_added=bool(cursor.rowcount), size_updated=size_updated)
    def list_movies(
        self,
        query="",
        studio="",
        series="",
        actress="",
        favorite=None,
        has_magnet=None,
        source="",
        page=1,
        page_size=36,
    ) -> dict[str, Any]:
        page = max(1, int(page or 1))
        page_size = min(100, max(1, int(page_size or 36)))
        where: list[str] = []
        values: list[Any] = []

        if query:
            where.append("(m.title LIKE ? OR m.normalized_title LIKE ?)")
            values.extend((f"%{query.strip()}%", f"%{normalize_title(query)}%"))
        if studio:
            if studio == UNKNOWN_VALUE:
                where.append("m.studio=''")
            else:
                where.append("m.studio=?")
                values.append(studio)
        if series:
            if series == UNKNOWN_VALUE:
                where.append("m.series=''")
            else:
                where.append("m.series=?")
                values.append(series)
        if actress:
            if actress == UNKNOWN_VALUE:
                where.append(
                    "NOT EXISTS(SELECT 1 FROM movie_actresses uma WHERE uma.movie_id=m.id)"
                )
            else:
                where.append(
                    """EXISTS(
                           SELECT 1 FROM movie_actresses fma
                           JOIN actresses fa ON fa.id=fma.actress_id
                           WHERE fma.movie_id=m.id AND fa.name=?
                       )"""
                )
                values.append(actress)
        if favorite is not None:
            where.append("m.favorite=?")
            values.append(int(bool(favorite)))
        if has_magnet is True:
            where.append("EXISTS(SELECT 1 FROM magnets hm WHERE hm.movie_id=m.id)")
        elif has_magnet is False:
            where.append("NOT EXISTS(SELECT 1 FROM magnets hm WHERE hm.movie_id=m.id)")
        if source:
            where.append(
                """EXISTS(
                       SELECT 1 FROM magnets sm
                       JOIN magnet_sources sms ON sms.magnet_id=sm.id
                       JOIN source_entries sse ON sse.id=sms.source_entry_id
                       WHERE sm.movie_id=m.id AND sse.source=?
                   )"""
            )
            values.append(source)

        where_sql = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as db:
            total = db.execute(
                f"SELECT COUNT(*) FROM movies m{where_sql}", values
            ).fetchone()[0]
            rows = [
                dict(row)
                for row in db.execute(
                    f"""SELECT m.*,
                               (SELECT COUNT(*) FROM magnets x WHERE x.movie_id=m.id) magnet_count
                        FROM movies m{where_sql}
                        ORDER BY m.favorite DESC,
                                 CASE WHEN m.release_date='' THEN 1 ELSE 0 END,
                                 m.release_date DESC,
                                 m.updated_at DESC,
                                 m.id DESC
                        LIMIT ? OFFSET ?""",
                    values + [page_size, (page - 1) * page_size],
                )
            ]
            self._hydrate_movie_rows(db, rows)

        pages = max(1, (total + page_size - 1) // page_size)
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def _hydrate_movie_rows(self, db: sqlite3.Connection, rows: list[dict[str, Any]]):
        if not rows:
            return
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        actress_map: dict[int, list[str]] = {movie_id: [] for movie_id in ids}
        for row in db.execute(
            f"""SELECT ma.movie_id,a.name
                FROM movie_actresses ma
                JOIN actresses a ON a.id=ma.actress_id
                WHERE ma.movie_id IN ({placeholders})
                ORDER BY a.name""",
            ids,
        ):
            actress_map[row["movie_id"]].append(row["name"])

        source_map: dict[int, dict[str, int]] = {movie_id: {} for movie_id in ids}
        for row in db.execute(
            f"""SELECT mg.movie_id,se.source,COUNT(DISTINCT mg.id) amount
                FROM magnets mg
                JOIN magnet_sources ms ON ms.magnet_id=mg.id
                JOIN source_entries se ON se.id=ms.source_entry_id
                WHERE mg.movie_id IN ({placeholders})
                GROUP BY mg.movie_id,se.source""",
            ids,
        ):
            source_map[row["movie_id"]][row["source"]] = row["amount"]

        for row in rows:
            row["favorite"] = bool(row["favorite"])
            row["actresses"] = actress_map[row["id"]]
            row["source_counts"] = source_map[row["id"]]
            row["manual_fields"] = sorted(self._manual_fields(row))
            row["cover_src"] = (
                f"/api/movies/{row['id']}/cover"
                if row.get("cover_path") and Path(row["cover_path"]).is_file()
                else row.get("cover_url", "")
            )

    def get_movie(self, movie_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
            if not row:
                return None
            movie = dict(row)
            movie["favorite"] = bool(movie["favorite"])
            movie["manual_fields"] = sorted(self._manual_fields(movie))
            movie["actresses"] = [
                item["name"]
                for item in db.execute(
                    """SELECT a.name FROM actresses a
                       JOIN movie_actresses ma ON ma.actress_id=a.id
                       WHERE ma.movie_id=? ORDER BY a.name""",
                    (movie_id,),
                )
            ]
            movie["sources"] = [
                dict(item)
                for item in db.execute(
                    """SELECT id,source,source_url,source_movie_id,source_title,last_checked_at
                       FROM source_entries WHERE movie_id=? ORDER BY source,source_url""",
                    (movie_id,),
                )
            ]
            magnet_rows = db.execute(
                """SELECT mg.*,se.source,se.source_url
                   FROM magnets mg
                   LEFT JOIN magnet_sources ms ON ms.magnet_id=mg.id
                   LEFT JOIN source_entries se ON se.id=ms.source_entry_id
                   WHERE mg.movie_id=?
                   ORDER BY CASE WHEN mg.size_bytes IS NULL OR mg.size_bytes=0 THEN 1 ELSE 0 END,
                            mg.size_bytes DESC,mg.id DESC,se.source""",
                (movie_id,),
            ).fetchall()
            magnets: dict[int, dict[str, Any]] = {}
            for item in magnet_rows:
                magnet = magnets.setdefault(
                    item["id"],
                    {
                        "id": item["id"],
                        "magnet": item["magnet"],
                        "btih": item["btih"],
                        "size_bytes": item["size_bytes"],
                        "discovered_at": item["discovered_at"],
                        "sources": [],
                    },
                )
                if item["source"]:
                    source_item = {
                        "source": item["source"],
                        "source_url": item["source_url"],
                    }
                    if source_item not in magnet["sources"]:
                        magnet["sources"].append(source_item)
            movie["magnets"] = list(magnets.values())
            movie["cover_src"] = (
                f"/api/movies/{movie_id}/cover"
                if movie.get("cover_path") and Path(movie["cover_path"]).is_file()
                else movie.get("cover_url", "")
            )
            return movie

    def get_filters(self) -> dict[str, Any]:
        with self.connect() as db:
            studios = [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT studio FROM movies WHERE studio<>'' ORDER BY studio"
                )
            ]
            series = [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT series FROM movies WHERE series<>'' ORDER BY series"
                )
            ]
            actresses = [
                row[0]
                for row in db.execute("SELECT a.name FROM actresses a WHERE EXISTS(SELECT 1 FROM movie_actresses ma WHERE ma.actress_id=a.id) ORDER BY a.name")
            ]
            sources = [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT se.source FROM source_entries se JOIN magnet_sources ms ON ms.source_entry_id=se.id WHERE se.source<>'' ORDER BY se.source"
                )
            ]
            stats = dict(
                db.execute(
                    """SELECT COUNT(*) total,
                              SUM(CASE WHEN favorite=1 THEN 1 ELSE 0 END) favorites,
                              SUM(CASE WHEN EXISTS(SELECT 1 FROM magnets mg WHERE mg.movie_id=movies.id) THEN 1 ELSE 0 END) with_magnets
                       FROM movies"""
                ).fetchone()
            )
            stats = {key: int(value or 0) for key, value in stats.items()}
            stats["magnets"] = db.execute("SELECT COUNT(*) FROM magnets").fetchone()[0]
            return {
                "studios": studios,
                "series": series,
                "actresses": actresses,
                "sources": sources,
                "stats": stats,
                "unknown_value": UNKNOWN_VALUE,
            }

    def update_movie(self, movie_id: int, changes: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"title", "cover_url", "studio", "series", "release_date", "duration_minutes", "actresses", "favorite"}
        changes = {key: value for key, value in changes.items() if key in allowed}
        if not changes:
            return self.get_movie(movie_id)
        with self.connect() as db:
            movie = db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
            if not movie:
                return None
            manual = self._manual_fields(movie)
            updates: dict[str, Any] = {}
            for key in ("title", "cover_url", "studio", "series", "release_date", "duration_minutes"):
                if key not in changes:
                    continue
                value = changes[key]
                if key == "title":
                    value = str(value or "").strip()
                    if not value:
                        raise ValueError("影片名不能为空")
                elif key == "duration_minutes":
                    value = None if value in (None, "") else int(value)
                    if value is not None and not 0 <= value <= 1440:
                        raise ValueError("时长必须在 0 到 1440 分钟之间")
                else:
                    value = str(value or "").strip()
                    if key == "release_date" and value:
                        try: datetime.strptime(value, "%Y-%m-%d")
                        except ValueError as exc: raise ValueError("日期必须是 YYYY-MM-DD 格式") from exc
                    if key == "cover_url" and value and not value.startswith(("https://", "http://")):
                        raise ValueError("封面网址必须是 http 或 https 地址")
                # 编辑表单会提交整份资料：只有实际改变的字段才被手动保护。
                if movie[key] != value:
                    updates[key] = value
                    if key == "title": updates["normalized_title"] = normalize_title(value)
                    manual.add(key)
            if "favorite" in changes:
                favorite = int(bool(changes["favorite"]))
                if movie["favorite"] != favorite: updates["favorite"] = favorite
            clean: list[tuple[str, str]] = []
            actresses_changed = False
            if "actresses" in changes:
                raw = changes["actresses"]
                names = re.split(r"[,，、\n]+", raw) if isinstance(raw, str) else list(raw or [])
                seen: set[str] = set()
                for name in names:
                    name = re.sub(r"\s+", " ", str(name or "")).strip(); normalized = normalize_title(name)
                    if name and normalized not in seen: clean.append((name, normalized)); seen.add(normalized)
                current = {row["normalized_name"] for row in db.execute("SELECT a.normalized_name FROM actresses a JOIN movie_actresses ma ON ma.actress_id=a.id WHERE ma.movie_id=?", (movie_id,))}
                actresses_changed = current != {normalized for _, normalized in clean}
                if actresses_changed: manual.add("actresses")
            if updates or actresses_changed:
                updates["manual_fields"] = json.dumps(sorted(manual), ensure_ascii=False)
                updates["updated_at"] = self.now()
                assignment = ",".join(f"{key}=?" for key in updates)
                db.execute(f"UPDATE movies SET {assignment} WHERE id=?", list(updates.values()) + [movie_id])
            if actresses_changed:
                db.execute("DELETE FROM movie_actresses WHERE movie_id=?", (movie_id,))
                for name, normalized in clean:
                    db.execute("INSERT OR IGNORE INTO actresses(name,normalized_name) VALUES(?,?)", (name, normalized))
                    actress_id = db.execute("SELECT id FROM actresses WHERE normalized_name=?", (normalized,)).fetchone()["id"]
                    db.execute("INSERT OR IGNORE INTO movie_actresses VALUES(?,?)", (movie_id, actress_id))
        return self.get_movie(movie_id)
    def set_favorite(self, movie_id, favorite):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE movies SET favorite=?,updated_at=? WHERE id=?",
                (int(bool(favorite)), self.now(), movie_id),
            )
            return cursor.rowcount > 0

    def get_cover_path(self, movie_id: int) -> Path | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT cover_path FROM movies WHERE id=?", (movie_id,)
            ).fetchone()
        if not row or not row["cover_path"]:
            return None
        path = Path(row["cover_path"])
        return path if path.is_file() else None


    def record_scan_failure(self, source: str, series_id: int, source_url: str, page: int, error: str) -> None:
        now = self.now()
        with self.connect() as db:
            db.execute("""INSERT INTO scan_failures(source,series_id,source_url,page,attempts,last_error,created_at,updated_at,resolved_at)
                          VALUES(?,?,?,?,1,?,?,?, '')
                          ON CONFLICT(source,series_id,source_url) DO UPDATE SET page=excluded.page,attempts=scan_failures.attempts+1,last_error=excluded.last_error,updated_at=excluded.updated_at,resolved_at=''""", (source, series_id, source_url, int(page), str(error)[:500], now, now))

    def list_unresolved_scan_failures(self, source: str, series_id: int) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM scan_failures WHERE source=? AND series_id=? AND resolved_at='' ORDER BY page,id", (source, series_id)).fetchall()]

    def resolve_scan_failure(self, source: str, series_id: int, source_url: str) -> bool:
        now = self.now()
        with self.connect() as db:
            return db.execute("UPDATE scan_failures SET resolved_at=?,updated_at=? WHERE source=? AND series_id=? AND source_url=? AND resolved_at=''", (now, now, source, series_id, source_url)).rowcount > 0
    def list_source_series(self, source="javdb"):
        with self.connect() as db:
            rows = db.execute("""SELECT ss.*, sr.status AS scan_status, sr.current_page, sr.discovered, sr.processed_count, sr.new_movies, sr.new_magnets, sr.failures, sr.matched_current, sr.attached_other_movies, sr.unmatched_candidates, sr.last_error, sr.finished_at AS last_run_finished_at FROM source_series ss LEFT JOIN scan_runs sr ON sr.id=(SELECT id FROM scan_runs WHERE series_id=ss.id ORDER BY id DESC LIMIT 1) WHERE ss.source=? ORDER BY ss.name,ss.id""", (source,)).fetchall()
            return [dict(row) for row in rows]

    def latest_scan_status(self, source: str):
        with self.connect() as db:
            row = db.execute("""SELECT sr.id AS run_id,sr.series_id,ss.name AS series_name,ss.source,sr.status,sr.current_page,sr.discovered,sr.processed_count,sr.new_movies,sr.new_magnets,sr.failures,sr.matched_current,sr.attached_other_movies,sr.unmatched_candidates,sr.last_error,sr.started_at,sr.finished_at FROM scan_runs sr JOIN source_series ss ON ss.id=sr.series_id WHERE ss.source=? ORDER BY sr.id DESC LIMIT 1""", (source,)).fetchone()
            return dict(row) if row else None

    def is_source_series_scanning(self, series_id, source):
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM scan_runs sr JOIN source_series ss ON ss.id=sr.series_id WHERE sr.series_id=? AND ss.source=? AND sr.status IN ('starting','running','stopping') ORDER BY sr.id DESC LIMIT 1", (series_id, source)).fetchone()
            return bool(row)
    def set_scan_stopping(self, series_id, source):
        with self.connect() as db:
            return db.execute("UPDATE scan_runs SET status='stopping' WHERE id=(SELECT sr.id FROM scan_runs sr JOIN source_series ss ON ss.id=sr.series_id WHERE sr.series_id=? AND ss.source=? AND sr.status='running' ORDER BY sr.id DESC LIMIT 1)", (series_id, source)).rowcount > 0
    def get_source_series(self, series_id, source):
        with self.connect() as db:
            row = db.execute("SELECT * FROM source_series WHERE id=? AND source=?", (series_id, source)).fetchone()
            return dict(row) if row else None

    def save_source_series(self, name, url, enabled=True, series_id=None, source="javdb", profile_dir=None, **_ignored):
        name, url = str(name or "").strip(), str(url or "").strip()
        if source not in {"javdb", "jphoo"}: raise ValueError("不支持的来源")
        if not name or not url.startswith(("https://", "http://")): raise ValueError("请填写系列名称和有效网址")
        if not isinstance(enabled, bool): raise ValueError("启用状态必须是布尔值")
        profile_dir = None if profile_dir is None else str(profile_dir).strip()
        with self.connect() as db:
            if series_id:
                row = db.execute("SELECT * FROM source_series WHERE id=? AND source=?", (series_id, source)).fetchone()
                if not row: raise ValueError("来源系列不存在")
                if db.execute("SELECT 1 FROM scan_runs WHERE series_id=? AND status IN ('starting','running','stopping')", (series_id,)).fetchone():
                    raise ValueError("该系列正在扫描，不能修改网址或启用状态")
                url_changed = row["url"] != url
                checkpoint = 0 if url_changed else row["last_completed_page"]
                if profile_dir is None:
                    db.execute("UPDATE source_series SET name=?,url=?,enabled=?,last_completed_page=? WHERE id=? AND source=?", (name,url,int(enabled),checkpoint,series_id,source))
                else:
                    db.execute("UPDATE source_series SET name=?,url=?,enabled=?,profile_dir=?,last_completed_page=? WHERE id=? AND source=?", (name,url,int(enabled),profile_dir,checkpoint,series_id,source))
                if url_changed:
                    now = self.now()
                    db.execute("UPDATE scan_failures SET resolved_at=?,updated_at=?,last_error='superseded: source URL changed' WHERE source=? AND series_id=? AND resolved_at=''", (now, now, source, series_id))
                return int(series_id)
            try:
                return db.execute("INSERT INTO source_series(source,name,url,enabled,profile_dir) VALUES(?,?,?,?,?)", (source,name,url,int(enabled),profile_dir or "")).lastrowid
            except sqlite3.IntegrityError as exc:
                raise ValueError("该来源网址已经存在") from exc
    def delete_source_series(self, series_id, source):
        with self.connect() as db:
            return db.execute("DELETE FROM source_series WHERE id=? AND source=?", (series_id, source)).rowcount > 0
