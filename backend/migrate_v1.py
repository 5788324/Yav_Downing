"""从 V1 SQLite 导入 V2；默认只演练，不修改任何数据库。"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from .db import LibraryDatabase, extract_btih


class MigrationError(RuntimeError):
    pass


V2_TABLES = ("movies", "actresses", "movie_actresses", "source_entries", "magnets", "magnet_sources")


def v2_counts(path: str | Path) -> dict:
    target = Path(path)
    result = {name: 0 for name in V2_TABLES}
    if not target.is_file():
        return result
    with closing(sqlite3.connect(target)) as db:
        existing = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in V2_TABLES:
            if name in existing:
                result[name] = db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    return result


def legacy_rows(path):
    """完整读取 V1 后立即关闭只读连接，避免 Windows 文件锁阻塞恢复或迁移。"""
    try:
        with closing(sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)) as source:
            source.row_factory = sqlite3.Row
            rows = []
            for work in source.execute("SELECT * FROM works ORDER BY id").fetchall():
                actors = [row["name"] for row in source.execute("SELECT a.name FROM actors a JOIN work_actors wa ON wa.actor_id=a.id WHERE wa.work_id=?", (work["id"],)).fetchall()]
                magnets = source.execute("SELECT * FROM magnets WHERE work_id=?", (work["id"],)).fetchall()
                rows.append((work, actors, magnets))
            return rows
    except sqlite3.Error as exc:
        raise MigrationError(f"读取 V1 数据阶段失败：{type(exc).__name__}") from exc

def _source_stats(old_db: Path) -> dict:
    seen, sources, unique_btih, actresses = Counter(), Counter(), set(), set()
    for work, actors, magnets in legacy_rows(old_db):
        seen["movies"] += 1
        seen["source_entries"] += 1
        seen["movie_actresses"] += len(actors)
        actresses.update(actor for actor in actors if actor)
        sources[work["site"]] += 1
        for magnet in magnets:
            seen["magnet_sources"] += 1
            try:
                unique_btih.add(extract_btih(magnet["magnet"]))
            except ValueError:
                seen["invalid_magnets"] += 1
    seen["actresses"] = len(actresses)
    seen["magnets"] = len(unique_btih)
    seen["conflicts"] = 0
    return {"scanned": dict(seen), "sources": dict(sources)}


def migrate(old_db, new_db, apply=False):
    old_db, new_db = Path(old_db), Path(new_db)
    if not old_db.is_file():
        raise FileNotFoundError(f"旧数据库不存在：{old_db}")
    before = v2_counts(new_db)
    inspected = _source_stats(old_db)
    if not apply:
        return {"mode": "dry-run", "old_db": str(old_db.resolve()), "new_db": str(new_db.resolve()), "before": before, "after": before, **inspected}
    try:
        target = LibraryDatabase(new_db)
        for work, actors, magnets in legacy_rows(old_db):
            title = work["title_manual"] or work["title_auto"] or work["code_manual"] or work["code_auto"] or "（资料待补全）"
            movie_id = target.add_or_update_movie(title, studio=work["publisher_manual"] or work["publisher_auto"] or "", series=work["series"] or "", release_date=work["release_date_manual"] or work["release_date_auto"] or "", cover_url=work["cover_url_manual"] or work["cover_url_auto"] or "", actresses=actors, source=work["site"], source_url=work["source_url"])
            target.set_favorite(movie_id, bool(work["favorite"]))
            for magnet in magnets:
                try:
                    target.add_magnet(movie_id, magnet["magnet"], magnet["source_site"] or work["site"], work["source_url"], size_bytes=round(float(magnet["size_gb"] or 0) * 1024**3))
                except ValueError:
                    continue
        after = v2_counts(new_db)
    except MigrationError:
        raise
    except Exception as exc:
        raise MigrationError(f"写入 V2 数据阶段失败：{type(exc).__name__}") from exc
    return {"mode": "apply", "old_db": str(old_db.resolve()), "new_db": str(new_db.resolve()), "before": before, "after": after, **inspected}


def main():
    parser = argparse.ArgumentParser(description="V1 到 V2 SQLite 迁移（默认 dry-run）")
    parser.add_argument("--old-db", type=Path, required=True, help="V1 library.db 路径（只读）")
    parser.add_argument("--new-db", type=Path, required=True, help="V2 library.db 路径")
    parser.add_argument("--apply", action="store_true", help="实际写入 V2；省略时只统计")
    args = parser.parse_args()
    report = migrate(args.old_db, args.new_db, args.apply)
    print("模式：", report["mode"])
    print("旧库：", report["old_db"])
    print("新库：", report["new_db"])
    print("迁移前：", report["before"])
    print("V1 统计：", report["scanned"])
    print("按来源：", report["sources"])
    print("迁移后：", report["after"])


if __name__ == "__main__":
    main()