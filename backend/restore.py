"""从 Yav V2 备份恢复数据库和本地封面。"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from .backup import backup_data_dir
from .runtime import InstanceLock


class RestoreError(RuntimeError):
    pass


def _load_manifest(backup_dir: Path) -> dict:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.is_file():
        raise RestoreError("恢复阶段：找不到 manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RestoreError(f"恢复阶段：manifest.json 无法读取：{type(exc).__name__}") from exc
    if manifest.get("backup_format") != 1:
        raise RestoreError("恢复阶段：不支持或缺少备份格式版本")
    if manifest.get("database") != "library.db":
        raise RestoreError("恢复阶段：manifest 数据库声明无效")
    files = manifest.get("files")
    if not isinstance(files, list):
        raise RestoreError("恢复阶段：manifest 文件清单无效")
    return manifest


def validate_backup(backup: str | Path) -> dict:
    backup_dir = Path(backup).expanduser().resolve()
    if not backup_dir.is_dir():
        raise RestoreError(f"恢复阶段：备份目录不存在：{backup_dir}")
    manifest = _load_manifest(backup_dir)
    for item in manifest["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not isinstance(item.get("size_bytes"), int):
            raise RestoreError("恢复阶段：manifest 文件条目无效")
        path = (backup_dir / item["path"]).resolve()
        if backup_dir not in path.parents or not path.is_file():
            raise RestoreError(f"恢复阶段：备份文件缺失：{item.get('path', '')}")
        if path.stat().st_size != item["size_bytes"]:
            raise RestoreError(f"恢复阶段：备份文件大小不匹配：{item['path']}")
    if not (backup_dir / "library.db").is_file():
        raise RestoreError("恢复阶段：数据库快照不存在")
    return {"backup_dir": backup_dir, "manifest": manifest}


def _database_idle(data_dir: Path) -> None:
    lock = InstanceLock(data_dir, 0)
    if lock.path.exists():
        try:
            payload = json.loads(lock.path.read_text(encoding="utf-8"))
            import os
            os.kill(int(payload.get("pid", 0)), 0)
            raise RestoreError("恢复阶段：Yav 正在运行，请先退出后再恢复")
        except RestoreError:
            raise
        except (OSError, ValueError, json.JSONDecodeError):
            lock.path.unlink(missing_ok=True)
    database = data_dir / "library.db"
    if database.exists():
        try:
            with closing(sqlite3.connect(database, timeout=0.2)) as db:
                db.execute("BEGIN EXCLUSIVE")
                db.rollback()
        except sqlite3.OperationalError as exc:
            raise RestoreError("恢复阶段：数据库正在使用，请先退出 Yav") from exc


def restore_data_dir(data_dir: str | Path, backup: str | Path, dry_run: bool = False) -> dict:
    data_dir = Path(data_dir).expanduser().resolve()
    checked = validate_backup(backup)
    manifest, backup_dir = checked["manifest"], checked["backup_dir"]
    report = {"mode": "dry-run" if dry_run else "apply", "backup_dir": str(backup_dir), "database": "library.db", "covers": len(manifest.get("local_covers", []))}
    if dry_run:
        return report
    _database_idle(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    pre_backup = backup_data_dir(data_dir) if (data_dir / "library.db").is_file() else None
    stage = data_dir / f".restore-stage-{uuid.uuid4().hex}"
    try:
        stage.mkdir()
        staged_db = stage / "library.db"
        shutil.copy2(backup_dir / "library.db", staged_db)
        restored_covers = data_dir / "covers" / f"restored-{uuid.uuid4().hex}"
        restored_covers.mkdir(parents=True, exist_ok=False)
        mapping = manifest.get("local_covers", [])
        for item in mapping:
            if not isinstance(item, dict) or not isinstance(item.get("movie_id"), int) or not isinstance(item.get("file"), str):
                raise RestoreError("恢复阶段：封面映射无效")
            source = (backup_dir / item["file"]).resolve()
            if backup_dir not in source.parents or not source.is_file():
                raise RestoreError("恢复阶段：封面文件缺失")
            target = restored_covers / Path(item["file"]).name
            shutil.copy2(source, target)
            with closing(sqlite3.connect(staged_db)) as db:
                db.execute("UPDATE movies SET cover_path=? WHERE id=?", (str(target), item["movie_id"]))
                db.commit()
        current_db = data_dir / "library.db"
        os_replace = __import__("os").replace
        os_replace(staged_db, current_db)
        report["pre_restore_backup"] = pre_backup["backup_dir"] if pre_backup else ""
        report["restored_cover_dir"] = str(restored_covers)
        return report
    except Exception as exc:
        if isinstance(exc, RestoreError):
            raise
        raise RestoreError(f"恢复阶段：复制或切换失败：{type(exc).__name__}") from exc
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Yav V2 备份恢复数据库和本地封面")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = restore_data_dir(args.data_dir, args.backup, args.dry_run)
    print("恢复模式：", report["mode"])
    print("备份目录：", report["backup_dir"])
    print("将恢复封面：", report["covers"])
    if report["mode"] == "apply":
        print("恢复前备份：", report.get("pre_restore_backup") or "无")


if __name__ == "__main__":
    main()