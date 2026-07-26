"""Yav V2 Windows 统一入口：服务、备份、恢复和 V1 迁移。"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from backend.app import main as serve_app
from backend.backup import backup_data_dir
from backend.db import LibraryDatabase
from backend.migrate_v1 import migrate, v2_counts
from backend.restore import RestoreError, restore_data_dir
from backend.runtime import APP_VERSION, InstanceLock, choose_port, configure_logging, default_data_dir, open_existing_page, safe_text


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Yav V2 本地图书馆")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--restore", type=Path, metavar="备份目录")
    parser.add_argument("--migrate-v1", type=Path, metavar="V1数据库")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def _message(text: str, title: str = "Yav V2") -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        print(text, file=sys.stderr)


def _run_command(args, logger) -> int:
    data_dir = args.data_dir.expanduser().resolve()
    if args.backup:
        report = backup_data_dir(data_dir)
        logger.info("备份完成 path=%s covers=%s", report["backup_dir"], report["copied_covers"])
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if args.restore:
        report = restore_data_dir(data_dir, args.restore, args.dry_run)
        logger.info("恢复结果 mode=%s backup=%s", report["mode"], report["backup_dir"])
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if args.migrate_v1:
        new_db = data_dir / "library.db"
        apply = not args.dry_run
        before = v2_counts(new_db)
        pre_backup = None
        if apply and sum(before.values()) and new_db.is_file():
            pre_backup = backup_data_dir(data_dir)
            logger.info("V1 迁移前备份 path=%s", pre_backup["backup_dir"])
        report = migrate(args.migrate_v1, new_db, apply=apply)
        report["pre_migration_backup"] = pre_backup["backup_dir"] if pre_backup else ""
        logger.info("V1 迁移完成 mode=%s before=%s after=%s", report["mode"], report["before"], report["after"])
        print(json.dumps(report, ensure_ascii=False))
        return 0
    return -1


def run(argv=None) -> int:
    args = parse_args(argv)
    data_dir = args.data_dir.expanduser().resolve()
    logger = configure_logging(data_dir)
    logger.info("启动入口 version=%s data_dir=%s", APP_VERSION, data_dir)
    try:
        command = _run_command(args, logger)
        if command >= 0:
            return command
        port = choose_port(args.port)
        lock = InstanceLock(data_dir, port)
        if not lock.acquire():
            existing_port = port
            try:
                existing_port = int(json.loads(lock.path.read_text(encoding="utf-8")).get("port", port))
            except Exception:
                pass
            if open_existing_page(existing_port) and not args.no_browser:
                webbrowser.open(f"http://127.0.0.1:{existing_port}")
            _message("Yav 已在运行，已保留现有资料库。", "Yav 已在运行")
            return 0
        try:
            sys.argv = [sys.argv[0], "--data-dir", str(data_dir), "--port", str(port)]
            if not args.no_browser:
                sys.argv.append("--open-browser")
            serve_app()
        finally:
            lock.release()
        logger.info("服务正常退出")
        return 0
    except (OSError, RuntimeError, RestoreError, ValueError, FileNotFoundError) as exc:
        logger.error("启动或命令失败：%s", safe_text(exc))
        _message(f"Yav 无法完成操作：{safe_text(exc)}\n\n日志：{data_dir / 'logs' / 'yav.log'}", "Yav V2")
        return 2
    except Exception as exc:
        logger.exception("未预期异常：%s", safe_text(exc))
        _message(f"Yav 发生异常，请查看日志：{data_dir / 'logs' / 'yav.log'}", "Yav V2")
        return 3


if __name__ == "__main__":
    raise SystemExit(run())