from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import webbrowser
import secrets
import threading
import time
from threading import Timer
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .db import LibraryDatabase
from .scanner import ScanManager, JphooSessionManager
from .runtime import APP_VERSION, clear_runtime_state, configure_logging, write_runtime_state


class ApplicationRuntime:
    """协调关闭顺序；HTTP 请求线程只负责确认请求并返回 202。"""

    def __init__(self, server, scans, jphoo_session, shutdown_token, instance_id=None, logger=None):
        self.server, self.scans, self.jphoo_session = server, scans, jphoo_session
        self.shutdown_token = shutdown_token
        self.instance_id = instance_id or secrets.token_urlsafe(12)
        self.logger = logger
        self.shutdown_pending = False
        self._controller_started = False
        self._lock = threading.Lock()

    @staticmethod
    def _running(component):
        try:
            return bool(component and component.status().get("running"))
        except Exception:
            return False

    def status(self):
        return {"app": "Yav", "version": APP_VERSION, "instance_id": self.instance_id,
                "pid": os.getpid(), "status": "shutting_down" if self.shutdown_pending else "running",
                "shutdown_pending": self.shutdown_pending, "javdb_running": self._running(self.scans),
                "jphoo_running": self._running(self.jphoo_session)}

    def request_shutdown(self, reason="api"):
        with self._lock:
            if self.shutdown_pending:
                return False
            self.shutdown_pending = True
            return True

    def start_shutdown(self, reason="api"):
        with self._lock:
            if self._controller_started:
                return False
            self._controller_started = True
        threading.Thread(target=self.graceful_shutdown, args=(reason,), daemon=False, name="yav-shutdown").start()
        return True

    def _shutdown_component(self, component, name, timeout):
        if not component:
            return True
        try:
            completed = component.shutdown(timeout=timeout)
        except TypeError:
            component.stop()
            completed = True
        except Exception as exc:
            completed = False
            if self.logger:
                self.logger.warning("关闭 %s 时发生 %s", name, type(exc).__name__)
        if completed is False and self.logger:
            self.logger.warning("等待 %s 退出超时 timeout=%ss", name, timeout)
        return completed is not False

    def graceful_shutdown(self, reason):
        try:
            self._shutdown_component(self.scans, "JavDB 扫描", 10)
            self._shutdown_component(self.jphoo_session, "JPHOO 会话", 15)
        finally:
            self.server.shutdown()


STATIC_DIR = Path(__file__).with_name("static")


class Handler(BaseHTTPRequestHandler):
    database: LibraryDatabase | None = None
    scans: ScanManager | None = None
    jphoo_scans: JphooSessionManager | None = None
    jphoo_login: JphooSessionManager | None = None
    runtime: ApplicationRuntime | None = None

    def _json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求内容不是有效 JSON") from exc

    def _serve_file(self, path: Path, cache=True):
        if not path.is_file():
            self.send_error(404)
            return
        content = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        assert self.database is not None
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        if path == "/api/app/status":
            self._json(self.runtime.status() if self.runtime else {"status":"starting"})
            return

        if path == "/api/movies":
            try:
                favorite = self._optional_bool(query.get("favorite", [""])[0])
                has_magnet = self._optional_bool(query.get("has_magnet", [""])[0])
                result = self.database.list_movies(
                    query=query.get("q", query.get("query", [""]))[0],
                    studio=query.get("studio", [""])[0],
                    series=query.get("series", [""])[0],
                    actress=query.get("actress", [""])[0],
                    favorite=favorite,
                    has_magnet=has_magnet,
                    source=query.get("source", [""])[0],
                    page=query.get("page", [1])[0],
                    page_size=query.get("page_size", [36])[0],
                )
                self._json(result)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, 400)
            return

        if path == "/api/sources/javdb/scan":
            self._json(self.scans.status() if self.scans else {"status":"idle","running":False})
            return

        if path == "/api/sources/javdb":
            self._json(self.database.list_source_series())
            return

        if path == "/api/sources/jphoo/login":
            self._json(self.jphoo_login.status() if self.jphoo_login else {"status":"idle","login":"unknown"})
            return

        if path == "/api/sources/jphoo/scan":
            self._json(self.jphoo_scans.status() if self.jphoo_scans else {"status":"idle","running":False})
            return

        if path == "/api/sources/jphoo":
            self._json(self.database.list_source_series("jphoo"))
            return

        if path == "/api/filters":
            self._json(self.database.get_filters())
            return

        detail_match = re.fullmatch(r"/api/movies/(\d+)", path)
        if detail_match:
            movie = self.database.get_movie(int(detail_match.group(1)))
            self._json(movie or {"error": "影片不存在"}, 200 if movie else 404)
            return

        cover_match = re.fullmatch(r"/api/movies/(\d+)/cover", path)
        if cover_match:
            cover = self.database.get_cover_path(int(cover_match.group(1)))
            if cover:
                self._serve_file(cover)
            else:
                self.send_error(404)
            return

        if path == "/":
            bootstrap = json.dumps({"instanceId": self.runtime.instance_id, "shutdownToken": self.runtime.shutdown_token}, ensure_ascii=False)
            content = (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace("</body>", f"<script>window.__YAV_BOOTSTRAP__ = {bootstrap};</script></body>")
            payload = content.encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(payload))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(payload)
            return
        if path.startswith("/assets/"):
            filename = Path(path.removeprefix("/assets/")).name
            self._serve_file(STATIC_DIR / filename)
            return
        self.send_error(404)

    def do_PATCH(self):
        assert self.database is not None
        match = re.fullmatch(r"/api/movies/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        try:
            movie = self.database.update_movie(int(match.group(1)), self._read_json())
            self._json(movie or {"error": "影片不存在"}, 200 if movie else 404)
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)

    def do_DELETE(self):
        assert self.database is not None
        match = re.fullmatch(r"/api/sources/(?:javdb|jphoo)/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        source = urlparse(self.path).path.split("/")[3]
        series_id = int(match.group(1))
        manager = self.scans if source == "javdb" else self.jphoo_scans
        if (manager and manager.is_running_series(series_id)) or self.database.is_source_series_scanning(series_id, source):
            self._json({"error": "该系列正在扫描，请先停止扫描。"}, 409)
            return
        if not self.database.delete_source_series(series_id, source):
            self._json({"error": "来源系列不存在或来源不匹配"}, 404)
            return
        self._json({"deleted": True})


    def do_POST(self):
        assert self.database is not None
        if urlparse(self.path).path == "/api/app/shutdown":
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self._json({"error": "请求必须使用 JSON"}, 415); return
            try:
                payload = self._read_json()
            except ValueError:
                self._json({"error": "请求内容不是有效 JSON"}, 400); return
            token = payload.get("token") if isinstance(payload, dict) else None
            instance_id = payload.get("instance_id") if isinstance(payload, dict) else None
            origin, host = self.headers.get("Origin", ""), self.headers.get("Host", "")
            expected_host = f"127.0.0.1:{self.server.server_port}"
            local = host == expected_host and (not origin or origin == f"http://{expected_host}")
            if not (self.runtime and isinstance(token, str) and isinstance(instance_id, str) and local
                    and secrets.compare_digest(token, self.runtime.shutdown_token)
                    and secrets.compare_digest(instance_id, self.runtime.instance_id)):
                self._json({"error": "无权关闭 Yav"}, 403); return
            already = not self.runtime.request_shutdown()
            self._json({"status": "shutting_down", "already_pending": already}, 202)
            if not already:
                self.runtime.start_shutdown("api")
            return
        action_match = re.fullmatch(r"/api/sources/javdb/(\d+)/(scan|continue|stop)", urlparse(self.path).path)
        if action_match:
            try:
                if not self.scans: raise ValueError("扫描器未初始化")
                action,series_id=action_match.group(2),int(action_match.group(1))
                result=self.scans.stop(series_id) if action == "stop" else self.scans.start(series_id, action == "scan")
                self._json(result, 202)
            except (ValueError, TypeError) as exc:
                self._json({"error":str(exc)},400)
            return

        login_action = re.fullmatch(r"/api/sources/jphoo/login/(open|check|close)", urlparse(self.path).path)
        if login_action:
            try:
                if not self.jphoo_login: raise ValueError("JPHOO 登录窗口未初始化")
                action = login_action.group(1)
                payload = self._read_json()
                self._json(self.jphoo_login.open(payload.get("series_id")) if action == "open" else getattr(self.jphoo_login, action)(), 202)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, 400)
            return

        jphoo_action = re.fullmatch(r"/api/sources/jphoo/(\d+)/(scan|continue|stop)", urlparse(self.path).path)
        if jphoo_action:
            try:
                if not self.jphoo_scans: raise ValueError("JPHOO 扫描器未初始化")
                action,series_id=jphoo_action.group(2),int(jphoo_action.group(1))
                self._json(self.jphoo_scans.stop(series_id) if action == "stop" else self.jphoo_scans.start(series_id, action == "scan"), 202)
            except (ValueError, TypeError) as exc:
                self._json({"error":str(exc)},400)
            return

        if urlparse(self.path).path == "/api/sources/jphoo":
            try:
                payload=self._source_payload(self._read_json(), "jphoo"); self._json({"id": self.database.save_source_series(**payload)}, 201)
            except (ValueError, TypeError) as exc:
                self._json({"error":str(exc)}, 400)
            return

        if urlparse(self.path).path == "/api/sources/javdb":
            try:
                self._json({"id": self.database.save_source_series(**self._source_payload(self._read_json(), "javdb"))}, 201)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, 400)
            return

        match = re.fullmatch(r"/api/movies/(\d+)/favorite", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        try:
            payload = self._read_json()
            if type(payload.get("favorite")) is not bool: raise ValueError("favorite 必须是 JSON 布尔值")
            favorite = payload["favorite"]
            if not self.database.set_favorite(int(match.group(1)), favorite):
                self._json({"error": "影片不存在"}, 404)
                return
            self._json({"id": int(match.group(1)), "favorite": favorite})
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)

    @staticmethod
    def _source_payload(payload, source):
        if not isinstance(payload, dict):
            raise ValueError("来源配置必须是对象")
        allowed = {"series_id", "name", "url", "enabled", "profile_dir"}
        clean = {key: payload[key] for key in allowed if key in payload}
        clean["source"] = source
        return clean
    @staticmethod
    def _optional_bool(value):
        if value in (None, ""):
            return None
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("布尔筛选参数只能是 true 或 false")

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Yav" / "v2",
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="服务启动后打开本地界面")
    parser.add_argument("--instance-id", default="")
    args = parser.parse_args()
    args.data_dir = args.data_dir.expanduser().resolve()
    logger = configure_logging(args.data_dir)
    Handler.database = LibraryDatabase(args.data_dir / "library.db")
    Handler.scans = ScanManager(Handler.database)
    jphoo_session = JphooSessionManager(Handler.database, args.data_dir / "browser-profile" / "jphoo")
    Handler.jphoo_scans = Handler.jphoo_login = jphoo_session
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    Handler.runtime = ApplicationRuntime(server, Handler.scans, jphoo_session, secrets.token_urlsafe(32), args.instance_id or None, logger)
    write_runtime_state(args.data_dir, pid=os.getpid(), port=args.port, instance_id=Handler.runtime.instance_id, token=Handler.runtime.shutdown_token)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Yav V2 已启动：{url}")
    if args.open_browser:
        Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        jphoo_session.shutdown(timeout=15)
        server.server_close()
        clear_runtime_state(args.data_dir)

if __name__ == "__main__":
    main()
