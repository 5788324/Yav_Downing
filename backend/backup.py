"""Yav V2 本地数据库与封面备份命令。"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _backup_sqlite(source: Path, destination: Path) -> None:
    with closing(sqlite3.connect(source)) as source_db, closing(sqlite3.connect(destination)) as target_db:
        source_db.backup(target_db)


def backup_data_dir(data_dir: str | Path, output_dir: str | Path | None = None) -> dict:
    """创建不可覆盖的 V2 快照；只读取原库和封面文件。"""
    data_dir = Path(data_dir).expanduser().resolve()
    database_path = data_dir / "library.db"
    if not database_path.is_file():
        raise ValueError(f"找不到 V2 数据库：{database_path}")
    backup_root = Path(output_dir).expanduser().resolve() if output_dir else data_dir / "backups"
    backup_dir = backup_root / f"yav-v2-backup-{_timestamp()}"
    suffix = 1
    while backup_dir.exists():
        backup_dir = backup_root / f"yav-v2-backup-{_timestamp()}-{suffix}"
        suffix += 1
    backup_dir.mkdir(parents=True)
    copied, missing = [], []
    try:
        snapshot = backup_dir / "library.db"
        _backup_sqlite(database_path, snapshot)
        covers_dir = backup_dir / "covers"
        with closing(sqlite3.connect(database_path)) as db:
            rows = db.execute("SELECT id, cover_path FROM movies WHERE cover_path <> '' ORDER BY id").fetchall()
        for movie_id, raw_path in rows:
            cover = Path(raw_path)
            if not cover.is_file():
                missing.append(int(movie_id))
                continue
            extension = cover.suffix.lower() if cover.suffix else ".img"
            destination = covers_dir / f"{int(movie_id)}{extension}"
            covers_dir.mkdir(exist_ok=True)
            shutil.copy2(cover, destination)
            copied.append({"movie_id": int(movie_id), "file": destination.name})
        manifest = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "database": "library.db",
            "local_covers": copied,
            "missing_cover_movie_ids": missing,
        }
        (backup_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"backup_dir": str(backup_dir), "database": str(snapshot), "copied_covers": len(copied), "missing_covers": len(missing)}
    except Exception:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="备份 Yav V2 数据库和本地封面（只读原数据）")
    parser.add_argument("--data-dir", type=Path, required=True, help="包含 library.db 的 V2 数据目录")
    parser.add_argument("--output-dir", type=Path, help="备份根目录，默认保存到数据目录 backups")
    args = parser.parse_args()
    report = backup_data_dir(args.data_dir, args.output_dir)
    print("备份完成：", report["backup_dir"])
    print("数据库：", report["database"])
    print("已复制本地封面：", report["copied_covers"])
    print("缺失本地封面：", report["missing_covers"])


if __name__ == "__main__":
    main()