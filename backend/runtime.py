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

APP_VERSION = "2.0.1"


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


def clear_runtime_state(data_dir: str | Path, expected_instance_id: str | None = None) -> bool:
    """删除临时实例信息；指定实例 ID 时不会误删其他实例的状态。"""
    if expected_instance_id is not None:
        try:
            payload = json.loads(instance_path(data_dir).read_text(encoding="utf-8"))
        except FileNotFoundError:
            payload = None
        except (OSError, ValueError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            current_id = str(payload.get("instance_id", ""))
            if current_id and current_id != str(expected_instance_id):
                return False
    for path in (secret_path(data_dir), instance_path(data_dir)):
        path.unlink(missing_ok=True)
    directory = runtime_dir(data_dir)
    try:
        directory.rmdir()
    except OSError:
        pass
    return True


def _is_expected_yav(port: int, instance_id: str) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{int(port)}/api/app/status", timeout=0.6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("app") == "Yav" and payload.get("instance_id") == instance_id
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def _try_lock_file(handle) -> bool:
    """非阻塞取得进程生命周期文件锁；成功后必须保持 handle 打开。"""
    if os.name == "nt":
        import msvcrt
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock_file(handle) -> None:
    if os.name == "nt":
        import msvcrt
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class InstanceLock:
    """数据目录级单实例锁；锁句柄在整个 Yav 生命周期内保持打开。"""

    def __init__(self, data_dir: str | Path, port: int):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.path = instance_path(self.data_dir)
        self.lock_path = runtime_dir(self.data_dir) / "instance.lock"
        self.port = int(port)
        self.instance_id = secrets.token_urlsafe(12)
        self.acquired = False
        self._lock_handle = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        if not _try_lock_file(handle):
            handle.close()
            return False
        try:
            # 只有真正取得 OS 锁的进程才有权清理上次异常退出留下的状态。
            clear_runtime_state(self.data_dir)
            write_runtime_state(self.data_dir, pid=os.getpid(), port=self.port, instance_id=self.instance_id)
        except Exception:
            try:
                _unlock_file(handle)
            finally:
                handle.close()
            raise
        self._lock_handle = handle
        self.acquired = True
        return True

    def release(self) -> None:
        if not self.acquired:
            return
        clear_runtime_state(self.data_dir, expected_instance_id=self.instance_id)
        handle, self._lock_handle = self._lock_handle, None
        try:
            if handle is not None:
                _unlock_file(handle)
        finally:
            if handle is not None:
                handle.close()
        # Windows 关闭句柄后可安全清理锁载体；若新实例已打开它，删除会失败并保留文件。
        if os.name == "nt":
            try:
                self.lock_path.unlink(missing_ok=True)
                runtime_dir(self.data_dir).rmdir()
            except OSError:
                pass
        self.acquired = False


def open_existing_page(port: int, timeout: float = 0.6) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while True:
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/app/status", timeout=0.6) as response:
                return response.status == 200 and json.loads(response.read().decode("utf-8")).get("app") == "Yav"
        except (OSError, ValueError, json.JSONDecodeError):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)


def wait_for_exit(pid: int, port: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not pid_is_alive(pid) and not port_is_open(port):
            return True
        time.sleep(0.1)
    return not pid_is_alive(pid) and not port_is_open(port)
