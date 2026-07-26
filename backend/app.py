from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .db import LibraryDatabase
from .scanner import ScanManager

STATIC_DIR = Path(__file__).with_name("static")


class Handler(BaseHTTPRequestHandler):
    database: LibraryDatabase | None = None
    scans: ScanManager | None = None

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
            self._serve_file(STATIC_DIR / "index.html", cache=False)
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
        match = re.fullmatch(r"/api/sources/javdb/(\d+)", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        self._json({"deleted": self.database.delete_source_series(int(match.group(1)))})


    def do_POST(self):
        assert self.database is not None
        action_match = re.fullmatch(r"/api/sources/javdb/(\d+)/(scan|continue|stop)", urlparse(self.path).path)
        if action_match:
            try:
                if not self.scans: raise ValueError("扫描器未初始化")
                action,series_id=action_match.group(2),int(action_match.group(1))
                result=self.scans.stop() if action == "stop" else self.scans.start(series_id, action == "scan")
                self._json(result, 202)
            except (ValueError, TypeError) as exc:
                self._json({"error":str(exc)},400)
            return

        if urlparse(self.path).path == "/api/sources/javdb":
            try:
                self._json({"id": self.database.save_source_series(**self._read_json())}, 201)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, 400)
            return

        match = re.fullmatch(r"/api/movies/(\d+)/favorite", urlparse(self.path).path)
        if not match:
            self.send_error(404)
            return
        try:
            payload = self._read_json()
            favorite = bool(payload.get("favorite"))
            if not self.database.set_favorite(int(match.group(1)), favorite):
                self._json({"error": "影片不存在"}, 404)
                return
            self._json({"id": int(match.group(1)), "favorite": favorite})
        except (ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 400)

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
    args = parser.parse_args()
    Handler.database = LibraryDatabase(args.data_dir / "library.db")
    Handler.scans = ScanManager(Handler.database)
    print(f"Yav V2 已启动：http://127.0.0.1:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
