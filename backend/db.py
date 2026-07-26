"""Yav V2 的 SQLite 数据层。"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

UNKNOWN_VALUE = "__unknown__"


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    text = re.sub(r"[‐‑‒–—―_]+", "-", text)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s*(?:\||[-–—])\s*(?:javdb|jphoo)\s*$", "", text).strip()


def extract_btih(magnet: str) -> str:
    for value in parse_qs(urlparse(magnet).query).get("xt", []):
        found = re.fullmatch(r"urn:btih:([A-Za-z0-9]+)", value, re.I)
        if found:
            return found.group(1).upper()
    found = re.search(r"urn:btih:([A-Za-z0-9]+)", magnet or "", re.I)
    if found:
        return found.group(1).upper()
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
                CREATE INDEX IF NOT EXISTS idx_magnet_sources_entry ON magnet_sources(source_entry_id,magnet_id);
                """
            )
            db.execute("UPDATE schema_meta SET value='2' WHERE key='schema_version'")

    @staticmethod
    def now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _manual_fields(row: sqlite3.Row | dict[str, Any]) -> set[str]:
        try:
            return set(json.loads(row["manual_fields"] or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return set()

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
            "studio": (studio or "").strip(),
            "series": (series or "").strip(),
            "release_date": (release_date or "").strip(),
            "cover_url": (cover_url or "").strip(),
            "duration_minutes": duration_minutes,
        }
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM movies WHERE normalized_title=?", (normalized,)
            ).fetchall()
            movie = next(
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
                updates = {
                    key: (
                        value
                        if not movie[key]
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
                        cover_url,
                        studio,
                        series,
                        release_date,
                        duration_minutes,
                        now,
                        now,
                    ),
                ).lastrowid

            for name in actresses or []:
                name = re.sub(r"\s+", " ", name or "").strip()
                if not name:
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

    def add_magnet(self, movie_id, magnet, source, source_url, size_bytes=None):
        with self.connect() as db:
            entry = db.execute(
                "SELECT id FROM source_entries WHERE source=? AND source_url=?",
                (source, source_url),
            ).fetchone()
            if not entry:
                raise ValueError("磁链必须关联已保存的来源页面")
            btih = extract_btih(magnet)
            db.execute(
                """INSERT OR IGNORE INTO magnets(
                       movie_id,magnet,btih,size_bytes,discovered_at
                   ) VALUES(?,?,?,?,?)""",
                (movie_id, magnet, btih, size_bytes, self.now()),
            )
            magnet_id = db.execute(
                "SELECT id FROM magnets WHERE movie_id=? AND btih=?",
                (movie_id, btih),
            ).fetchone()["id"]
            db.execute(
                "INSERT OR IGNORE INTO magnet_sources VALUES(?,?)",
                (magnet_id, entry["id"]),
            )
            return magnet_id

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
                for row in db.execute("SELECT name FROM actresses ORDER BY name")
            ]
            sources = [
                row[0]
                for row in db.execute(
                    "SELECT DISTINCT source FROM source_entries WHERE source<>'' ORDER BY source"
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
        allowed = {
            "title",
            "cover_url",
            "studio",
            "series",
            "release_date",
            "duration_minutes",
            "actresses",
            "favorite",
        }
        changes = {key: value for key, value in changes.items() if key in allowed}
        if not changes:
            return self.get_movie(movie_id)

        with self.connect() as db:
            movie = db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
            if not movie:
                return None
            manual = self._manual_fields(movie)
            updates: dict[str, Any] = {}
            for key in (
                "title",
                "cover_url",
                "studio",
                "series",
                "release_date",
                "duration_minutes",
            ):
                if key not in changes:
                    continue
                value = changes[key]
                if key == "title":
                    value = str(value or "").strip()
                    if not value:
                        raise ValueError("影片名不能为空")
                    updates["normalized_title"] = normalize_title(value)
                elif key == "duration_minutes":
                    if value in (None, ""):
                        value = None
                    else:
                        value = int(value)
                        if value < 0:
                            raise ValueError("时长不能为负数")
                else:
                    value = str(value or "").strip()
                updates[key] = value
                manual.add(key)

            if "favorite" in changes:
                updates["favorite"] = int(bool(changes["favorite"]))

            if updates:
                updates["manual_fields"] = json.dumps(
                    sorted(manual), ensure_ascii=False
                )
                updates["updated_at"] = self.now()
                assignment = ",".join(f"{key}=?" for key in updates)
                db.execute(
                    f"UPDATE movies SET {assignment} WHERE id=?",
                    list(updates.values()) + [movie_id],
                )

            if "actresses" in changes:
                raw = changes["actresses"]
                if isinstance(raw, str):
                    names = re.split(r"[,，、\n]+", raw)
                else:
                    names = list(raw or [])
                clean: list[tuple[str, str]] = []
                seen: set[str] = set()
                for name in names:
                    name = re.sub(r"\s+", " ", str(name or "")).strip()
                    normalized = normalize_title(name)
                    if name and normalized not in seen:
                        clean.append((name, normalized))
                        seen.add(normalized)
                db.execute("DELETE FROM movie_actresses WHERE movie_id=?", (movie_id,))
                for name, normalized in clean:
                    db.execute(
                        "INSERT OR IGNORE INTO actresses(name,normalized_name) VALUES(?,?)",
                        (name, normalized),
                    )
                    actress_id = db.execute(
                        "SELECT id FROM actresses WHERE normalized_name=?", (normalized,)
                    ).fetchone()["id"]
                    db.execute(
                        "INSERT OR IGNORE INTO movie_actresses VALUES(?,?)",
                        (movie_id, actress_id),
                    )
                manual.add("actresses")
                db.execute(
                    "UPDATE movies SET manual_fields=?,updated_at=? WHERE id=?",
                    (
                        json.dumps(sorted(manual), ensure_ascii=False),
                        self.now(),
                        movie_id,
                    ),
                )
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
