"""Yav 打包版运行时辅助：数据目录、日志、单实例和端口。"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import socket
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

APP_VERSION = "2.0.0-rc4"


def default_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Yav" / "v2"


def safe_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"magnet:\?[^\s]+", "[磁链已隐藏]", text, flags=re.I)
    text = re.sub(r"(?i)(token|cookie|authorization)=[^\s,&]+", r"\1=[已隐藏]", text)
    return text[:400]


def configure_logging(data_dir: str | Path) -> logging.Logger:
    root = Path(data_dir)
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("yav")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    expected = (log_dir / "yav.log").resolve()
    if not any(isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename).resolve() == expected for handler in logger.handlers):
        handler = RotatingFileHandler(expected, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def port_is_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) 在 Windows 上并不能可靠查询其他进程。
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            try:
                return bool(ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value == 259)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def choose_port(requested: int | None) -> int:
    if requested is not None:
        if port_is_open(requested):
            raise RuntimeError(f"端口 {requested} 已被占用；请使用 --port 指定其他端口。")
        return requested
    for port in range(8765, 8770):
        if not port_is_open(port):
            return port
    raise RuntimeError("默认本地端口 8765–8769 均被占用；请使用 --port 指定端口。")


def runtime_dir(data_dir: str | Path) -> Path:
    return Path(data_dir).expanduser().resolve() / "runtime"


def instance_path(data_dir: str | Path) -> Path:
    return runtime_dir(data_dir) / "instance.json"


def secret_path(data_dir: str | Path) -> Path:
    return runtime_dir(data_dir) / "shutdown.secret"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_runtime_state(data_dir: str | Path, *, pid: int, port: int, instance_id: str, token: str | None = None) -> None:
    payload = {"pid": int(pid), "port": int(port), "instance_id": str(instance_id), "version": APP_VERSION}
    _atomic_write(instance_path(data_dir), json.dumps(payload, ensure_ascii=False))
    if token is not None:
        _atomic_write(secret_path(data_dir), str(token))


def read_runtime_state(data_dir: str | Path) -> tuple[dict | None, str | None]:
    try:
        info = json.loads(instance_path(data_dir).read_text(encoding="utf-8"))
        if not isinstance(info, dict):
            return None, None
        token = secret_path(data_dir).read_text(encoding="utf-8").strip()
        if not token:
            return None, None
        return info, token
    except (OSError, ValueError, json.JSONDecodeError):
        return None, None


def clear_runtime_state(data_dir: str | Path) -> None:
    for path in (secret_path(data_dir), instance_path(data_dir)):
        path.unlink(missing_ok=True)
    directory = runtime_dir(data_dir)
    try:
        directory.rmdir()
    except OSError:
        pass


def _is_expected_yav(port: int, instance_id: str) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{int(port)}/api/app/status", timeout=0.6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("app") == "Yav" and payload.get("instance_id") == instance_id
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


class InstanceLock:
    """数据目录级单实例锁；只认同端口上的同一 Yav 实例，避免 PID 复用误判。"""

    def __init__(self, data_dir: str | Path, port: int):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.path = instance_path(self.data_dir)
        self.lock_path = runtime_dir(self.data_dir) / "instance.lock"
        self.port = int(port)
        self.instance_id = secrets.token_urlsafe(12)
        self.acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 用独占哨兵解决两个启动器同时观察到旧状态的竞争；JSON 仍通过原子替换写入。
        for attempt in range(2):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(str(os.getpid()))
                break
            except FileExistsError:
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                    old_port = int(payload.get("port", 0))
                    old_id = str(payload.get("instance_id", ""))
                    old_pid = int(payload.get("pid", 0))
                    if pid_is_alive(old_pid) and old_id and _is_expected_yav(old_port, old_id):
                        return False
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
                # 不是同一 Yav 的陈旧锁（包括 PID 复用）才可移除后重试。
                self.lock_path.unlink(missing_ok=True)
                clear_runtime_state(self.data_dir)
        else:
            return False
        write_runtime_state(self.data_dir, pid=os.getpid(), port=self.port, instance_id=self.instance_id)
        self.acquired = True
        return True

    def release(self) -> None:
        if self.acquired:
            clear_runtime_state(self.data_dir)
            self.lock_path.unlink(missing_ok=True)
            try:
                runtime_dir(self.data_dir).rmdir()
            except OSError:
                pass
            self.acquired = False


def open_existing_page(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/app/status", timeout=0.6) as response:
            return response.status == 200 and json.loads(response.read().decode("utf-8")).get("app") == "Yav"
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def wait_for_exit(pid: int, port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not pid_is_alive(pid) and not port_is_open(port):
            return True
        time.sleep(0.1)
    return not pid_is_alive(pid) and not port_is_open(port)