"""Yav 打包版运行时辅助：数据目录、日志、单实例和端口。"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.request import urlopen

APP_VERSION = "2.0.0-rc3"


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


def choose_port(requested: int | None) -> int:
    if requested is not None:
        if port_is_open(requested):
            raise RuntimeError(f"端口 {requested} 已被占用；请使用 --port 指定其他端口。")
        return requested
    for port in range(8765, 8770):
        if not port_is_open(port):
            return port
    raise RuntimeError("默认本地端口 8765–8769 均被占用；请使用 --port 指定端口。")


class InstanceLock:
    def __init__(self, data_dir: str | Path, port: int):
        self.path = Path(data_dir) / "yav.lock"
        self.port = port
        self.acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                pid = int(payload.get("pid", 0))
                os.kill(pid, 0)
                return False
            except (OSError, ValueError, json.JSONDecodeError):
                self.path.unlink(missing_ok=True)
        try:
            with self.path.open("x", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "port": self.port}, handle)
            self.acquired = True
            return True
        except FileExistsError:
            return False

    def release(self) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def open_existing_page(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=0.6) as response:
            return response.status == 200
    except OSError:
        return False