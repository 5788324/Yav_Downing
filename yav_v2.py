"""Yav V2 Windows 启动器：启动本地服务并打开默认浏览器。"""
from __future__ import annotations

import sys

from backend.app import main


if __name__ == "__main__":
    no_browser = "--no-browser" in sys.argv
    if no_browser:
        sys.argv.remove("--no-browser")
    elif "--open-browser" not in sys.argv:
        sys.argv.append("--open-browser")
    main()