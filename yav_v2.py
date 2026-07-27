"""Yav V2 Windows 统一入口：服务、备份、恢复和 V1 迁移。"""
from __future__ import annotations

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import Request, urlopen

from backend.app import main as serve_app
from backend.backup import backup_data_dir
from backend.migrate_v1 import migrate, v2_counts
from backend.restore import RestoreError, restore_data_dir
from backend.runtime import (
    APP_VERSION, InstanceLock, choose_port, clear_runtime_state, configure_logging,
    default_data_dir, open_existing_page, pid_is_alive, port_is_open, read_runtime_state,
    safe_text, wait_for_exit,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Yav V2 本地图书馆")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--backup", action="store_true")
    parser.add_argument("--restore", type=Path, metavar="备份目录")
    parser.add_argument("--migrate-v1", type=Path, metavar="V1数据库")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--shutdown", action="store_true")
    return parser.parse_args(argv)


def _message(text: str, title: str = "Yav V2") -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        print(text, file=sys.stderr)


def _not_running(data_dir: Path) -> int:
    # 凭据缺失时不删除仍可能属于活跃实例的文件；下次启动会安全清理已验证陈旧状态。
    print(json.dumps({"status": "not_running"}, ensure_ascii=False))
    return 0


def _run_command(args, logger) -> int:
    data_dir = args.data_dir.expanduser().resolve()
    if args.shutdown:
        info, token = read_runtime_state(data_dir)
        if not info or not token:
            return _not_running(data_dir)
        try:
            pid, port = int(info["pid"]), int(info["port"])
            instance_id = str(info["instance_id"])
            if not pid_is_alive(pid):
                raise RuntimeError("运行实例不存在")
            with urlopen(f"http://127.0.0.1:{port}/api/app/status", timeout=2) as response:
                status = json.loads(response.read().decode("utf-8"))
            if (status.get("app") != "Yav" or status.get("instance_id") != instance_id
                    or int(status.get("pid", -1)) != pid):
                raise RuntimeError("目标不是当前 Yav 实例")
            body = json.dumps({"token": token, "instance_id": instance_id}).encode("utf-8")
            request = Request(f"http://127.0.0.1:{port}/api/app/shutdown", data=body,
                              headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(request, timeout=3) as response:
                if response.status != 202:
                    raise RuntimeError("关闭请求未接受")
            if wait_for_exit(pid, port, timeout=20):
                clear_runtime_state(data_dir, expected_instance_id=instance_id)
                print(json.dumps({"status": "stopped", "port": port}, ensure_ascii=False))
                return 0
            print(json.dumps({"status": "shutting_down", "port": port}, ensure_ascii=False))
            return 1
        except Exception as exc:
            # 仅清理由当前 data-dir 持有且已经失效的运行凭据；不会请求其他本地服务。
            try:
                stale = not pid_is_alive(int(info.get("pid", 0))) or not port_is_open(int(info.get("port", 0)))
            except (TypeError, ValueError):
                stale = True
            if stale:
                expected = str(info.get("instance_id", "")).strip() or None
                clear_runtime_state(data_dir, expected_instance_id=expected)
            logger.info("安全退出未执行：%s", safe_text(exc))
            print(json.dumps({"status": "not_running"}, ensure_ascii=False))
            return 0
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


def _wait_for_existing_instance(data_dir: Path, fallback_port: int, timeout: float = 5.0) -> tuple[int, bool]:
    """等待同一资料库的首个实例完成启动，不删除其运行状态。"""
    deadline = time.monotonic() + max(0.0, float(timeout))
    port = int(fallback_port)
    while True:
        try:
            payload = json.loads((data_dir / "runtime" / "instance.json").read_text(encoding="utf-8"))
            port = int(payload.get("port", port))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
        if open_existing_page(port, timeout=0.2):
            return port, True
        if time.monotonic() >= deadline:
            return port, False
        time.sleep(0.1)


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
            existing_port, ready = _wait_for_existing_instance(data_dir, port)
            if ready and not args.no_browser:
                webbrowser.open(f"http://127.0.0.1:{existing_port}")
            _message("Yav 已在运行，已打开现有资料库。" if ready else "Yav 正在启动，请稍后重新打开。",
                     "Yav 已在运行" if ready else "Yav 正在启动")
            return 0
        try:
            sys.argv = [sys.argv[0], "--data-dir", str(data_dir), "--port", str(port), "--instance-id", lock.instance_id]
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
