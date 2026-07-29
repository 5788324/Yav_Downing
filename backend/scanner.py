"""本地单线程来源扫描器：JavDB 与 JPHOO 共用简单进度模型。"""
from __future__ import annotations
import json
from pathlib import Path
from queue import Queue
from threading import Event, Thread, Lock, RLock
from urllib.parse import urlparse
from .sources.javdb import JavdbSource

_STAT_KEYS = ("discovered", "processed", "new_movies", "new_magnets", "failures", "matched_current", "attached_other_movies", "unmatched_candidates", "retried_failures", "resolved_failures")

class BaseScanner:
    source_name = ""
    def __init__(self, database): self.db = database; self.stop_event = Event()
    def stop(self): self.stop_event.set()
    def _begin(self, series_id, from_start):
        with self.db.connect() as db:
            series = db.execute("SELECT * FROM source_series WHERE id=? AND source=?", (series_id, self.source_name)).fetchone()
            if not series: raise ValueError(f"{self.source_name} 系列不存在")
            if not series["enabled"]: raise ValueError("该系列已停用，不能启动扫描")
            if from_start:
                # 全量扫描的断点从确认启动时清零；若马上停止，继续仍会回到第 1 页。
                db.execute("UPDATE source_series SET last_completed_page=0 WHERE id=?", (series_id,))
                page = 1
            else:
                page = max(1, series["last_completed_page"] + 1)
            run_id = db.execute("INSERT INTO scan_runs(series_id,status,started_at) VALUES(?,?,?)", (series_id, "running", self.db.now())).lastrowid
        return series, page, run_id
    def _save_progress(self, series_id, run_id, page, stats, last_error="", page_completed=False):
        with self.db.connect() as db:
            # 只在一整页全部处理完后推进断点；中途停止会从本页重新进入。
            if page_completed:
                db.execute("UPDATE source_series SET last_completed_page=? WHERE id=?", (page, series_id))
            db.execute("""UPDATE scan_runs SET current_page=?,discovered=?,processed_count=?,new_movies=?,new_magnets=?,failures=?,matched_current=?,attached_other_movies=?,unmatched_candidates=?,last_error=?,message=? WHERE id=?""", (page, stats["discovered"], stats["processed"], stats["new_movies"], stats["new_magnets"], stats["failures"], stats["matched_current"], stats["attached_other_movies"], stats["unmatched_candidates"], last_error[:200], json.dumps({k: stats[k] for k in ("matched_current", "attached_other_movies", "unmatched_candidates", "retried_failures", "resolved_failures")}, ensure_ascii=False), run_id))
    def _finish(self, series_id, run_id, page, stats, status, error=""):
        with self.db.connect() as db:
            db.execute("""UPDATE scan_runs SET status=?,current_page=?,discovered=?,processed_count=?,new_movies=?,new_magnets=?,failures=?,matched_current=?,attached_other_movies=?,unmatched_candidates=?,last_error=?,message=?,finished_at=? WHERE id=?""", (status, page, stats["discovered"], stats["processed"], stats["new_movies"], stats["new_magnets"], stats["failures"], stats["matched_current"], stats["attached_other_movies"], stats["unmatched_candidates"], error[:200], error[:200], self.db.now(), run_id))
            if status == "completed": db.execute("UPDATE source_series SET last_scanned_at=? WHERE id=?", (self.db.now(), series_id))
    def _stats(self): return {key: 0 for key in _STAT_KEYS}
    def _record_failure(self, series_id, url, page, exc):
        self.db.record_scan_failure(self.source_name, series_id, url, page, str(exc))
    def _retry_unresolved(self, series_id, process):
        for failure in self.db.list_unresolved_scan_failures(self.source_name, series_id):
            if self.stop_event.is_set(): break
            yield failure

class JavdbScanner(BaseScanner):
    source_name = "javdb"
    def _process_url(self, source, series, series_id, url, page, stats):
        stats["discovered"] += 1
        data = source.fetch_movie(url)
        existed = self.db.movie_import_exists(data.title, "javdb", url)
        movie = self.db.add_or_update_movie(data.title, studio=data.studio, series=data.series or series["name"], release_date=data.release_date, duration_minutes=data.duration_minutes, cover_url=data.cover_url, actresses=data.actresses, source="javdb", source_url=url)
        stats["new_movies"] += int(not existed)
        for item in source.fetch_magnets(url):
            saved = self.db.add_magnet(movie, item.magnet, "javdb", url, item.size_bytes)
            stats["new_magnets"] += int(saved.created)
        stats["processed"] += 1
        self.db.resolve_scan_failure(self.source_name, series_id, url)
    def run(self, series_id, from_start=False):
        series, page, run_id = self._begin(series_id, from_start); stats = self._stats(); source = JavdbSource(); error = ""
        try:
            for failure in self._retry_unresolved(series_id, self._process_url):
                if self.stop_event.is_set(): break
                stats["retried_failures"] += 1
                try:
                    self._process_url(source, series, series_id, failure["source_url"], failure["page"], stats)
                    stats["resolved_failures"] += 1
                except Exception as exc:
                    stats["failures"] += 1; error = str(exc); self._record_failure(series_id, failure["source_url"], failure["page"], exc)
            if not self.stop_event.is_set():
                for page, urls in source.scan_series(series["url"], start_page=page, stop_event=self.stop_event):
                    page_completed = True
                    for url in urls:
                        if self.stop_event.is_set(): page_completed = False; break
                        try:
                            self._process_url(source, series, series_id, url, page, stats)
                        except Exception as exc:
                            stats["failures"] += 1; error = str(exc); self._record_failure(series_id, url, page, exc)
                    self._save_progress(series_id, run_id, page, stats, error, page_completed)
                    if not page_completed: break
            status = "stopped" if self.stop_event.is_set() else "completed"
        except Exception as exc:
            status = "failed"; stats["failures"] += 1; error = str(exc)
        self._finish(series_id, run_id, page, stats, status, error); return {"status": status, "page": page, "message": error, **stats}

class JphooScanner(BaseScanner):
    source_name = "jphoo"
    def __init__(self, database, profile_dir, source=None):
        super().__init__(database); self.profile_dir = str(profile_dir); self.source = source
    def _process_url(self, source, series, series_id, url, page, stats):
        from .sources.jphoo import persist_candidates
        data = source.fetch_movie(url)
        if not data.title: raise ValueError("JPHOO 页面未解析到影片名")
        stats["discovered"] += 1
        existed = self.db.movie_import_exists(data.title, "jphoo", url)
        movie = self.db.add_or_update_movie(data.title, studio=data.studio, series=data.series or series["name"], release_date=data.release_date, duration_minutes=data.duration_minutes, cover_url=data.cover_url, actresses=data.actresses, source="jphoo", source_url=url)
        stats["new_movies"] += int(not existed)
        outcome = persist_candidates(self.db, movie, data.title, url, source.fetch_magnet_candidates())
        for key, result_key in (("new_magnets", "new_magnets"), ("matched_current", "matched_current"), ("attached_other_movies", "attached_other"), ("unmatched_candidates", "unmatched")): stats[key] += outcome[result_key]
        stats["processed"] += 1; self.db.resolve_scan_failure(self.source_name, series_id, url)
    def run(self, series_id, from_start=False):
        from .sources.jphoo import JphooSource, LoginRequired
        series, page, run_id = self._begin(series_id, from_start); stats = self._stats(); error = ""; owns_browser = self.source is None; source = self.source or JphooSource()
        try:
            if owns_browser: source.open_browser(self.profile_dir)
            for failure in self._retry_unresolved(series_id, self._process_url):
                if self.stop_event.is_set(): break
                stats["retried_failures"] += 1
                try:
                    self._process_url(source, series, series_id, failure["source_url"], failure["page"], stats); stats["resolved_failures"] += 1
                except LoginRequired: raise
                except Exception as exc: stats["failures"] += 1; error = str(exc); self._record_failure(series_id, failure["source_url"], failure["page"], exc)
            if not self.stop_event.is_set():
                for page, urls in source.scan_series(series["url"], start_page=page, stop_event=self.stop_event):
                    page_completed = True
                    for url in urls:
                        if self.stop_event.is_set(): page_completed = False; break
                        try: self._process_url(source, series, series_id, url, page, stats)
                        except LoginRequired: raise
                        except Exception as exc: stats["failures"] += 1; error = str(exc); self._record_failure(series_id, url, page, exc)
                    self._save_progress(series_id, run_id, page, stats, error, page_completed)
                    if not page_completed: break
            status = "stopped" if self.stop_event.is_set() else "completed"
        except LoginRequired as exc: status, error = "login_required", str(exc)
        except Exception as exc: status, error = "failed", str(exc); stats["failures"] += 1
        finally:
            if owns_browser: source.close()
        self._finish(series_id, run_id, page, stats, status, error); return {"status": status, "page": page, "message": error, **stats}
class ScanManager:
    scanner_class = JavdbScanner
    source_name = "javdb"
    def __init__(self, database):
        self.database, self.scanner, self.thread, self.result, self.series_id = database, None, None, None, None
        self.lock = Lock()
    def make_scanner(self): return self.scanner_class(self.database)
    def start(self, series_id, from_start=False):
        with self.lock:
            if self.thread and self.thread.is_alive(): raise ValueError("该来源已有扫描正在运行")
            series = self.database.get_source_series(series_id, self.source_name)
            if not series: raise ValueError("来源系列不存在")
            if not series["enabled"]: raise ValueError("该系列已停用，不能启动扫描")
            self.series_id, self.scanner = series_id, self.make_scanner()
            self.result = {"status":"starting", "series_id":series_id, "series_name":series["name"], "source":self.source_name}
            scanner = self.scanner
            def worker():
                try: result = scanner.run(series_id, from_start)
                except Exception as exc: result = {"status":"failed", "series_id":series_id, "source":self.source_name, "message":str(exc), "running":False}
                with self.lock: self.result = result
            self.thread = Thread(target=worker, daemon=True); self.thread.start()
            return dict(self.result, running=True)
    def stop(self, series_id=None):
        with self.lock:
            if series_id is not None and self.series_id is not None and int(series_id) != self.series_id:
                raise ValueError("请求的系列不是当前正在扫描的系列")
            scanner, current = self.scanner, self.series_id
        if scanner: scanner.stop()
        if current: self.database.set_scan_stopping(current, self.source_name)
        return self.status()
    def shutdown(self, timeout=10):
        self.stop(); thread = self.thread
        if thread and thread.is_alive(): thread.join(max(0.0, float(timeout)))
        return not bool(thread and thread.is_alive())
    def is_running_series(self, series_id):
        with self.lock: return bool(self.thread and self.thread.is_alive() and self.series_id == series_id)
    def status(self):
        with self.lock: running = bool(self.thread and self.thread.is_alive()); result = dict(self.result or {"status":"idle", "source":self.source_name})
        latest = self.database.latest_scan_status(self.source_name)
        if latest and (running or latest["status"] in {"running", "stopping"}): latest["running"] = running; return latest
        return {**result, "running":running}

class JphooSessionManager:
    """同一专用线程内复用一个 Playwright persistent context。"""
    source_name = "jphoo"

    def __init__(self, database, profile_dir, browser_factory=None):
        self.database = database
        self.profile_dir = str(Path(profile_dir).expanduser().resolve())
        self.browser_factory = browser_factory
        self.queue, self.thread, self.browser, self.scanner = Queue(), None, None, None
        self.lock, self.probe_pending = RLock(), Event()
        self.close_after_scan, self.shutdown_requested, self.scan_stop_requested = Event(), Event(), Event()
        self.series_id = None
        self.result = {"status": "closed", "login": "unknown", "session_state": "closed", "profile_dir": self.profile_dir, "window_open": False}

    def _set(self, **values):
        with self.lock:
            self.result.update(values)

    def _snapshot(self):
        with self.lock:
            return dict(self.result)

    def _ensure_worker(self):
        if not (self.thread and self.thread.is_alive()):
            self.thread = Thread(target=self._worker, name="yav-jphoo-session", daemon=True)
            self.thread.start()

    def _post(self, command, **payload):
        self._ensure_worker()
        self.queue.put((command, payload))

    def _series(self, series_id):
        series = self.database.get_source_series(series_id, self.source_name)
        if not series:
            raise ValueError("JPHOO 系列不存在")
        if not series["enabled"]:
            raise ValueError("该系列已停用，不能启动扫描")
        return series

    def _open_browser(self):
        from .sources.jphoo import JphooBrowser
        if self.browser and self.browser.is_open():
            return self.browser
        factory = self.browser_factory or JphooBrowser
        self.browser = factory(self.profile_dir)
        self.browser.open()
        return self.browser

    def _diagnose(self, target_url):
        diagnostic = self.browser.diagnose(target_url)
        self._set(**diagnostic, last_verified_at=self.database.now(), window_open=diagnostic.get("session_state") == "open")
        return diagnostic

    def open(self, series_id=None):
        if series_id is None:
            raise ValueError("请选择已配置的 JPHOO 系列作为登录目标")
        series = self._series(int(series_id))
        self.series_id = int(series_id)
        self._set(status="opening", login="checking", target_url=series["url"], target_origin=urlparse(series["url"]).netloc)
        self._post("open", series_id=self.series_id)
        return self.status()

    def check(self):
        if not self.series_id:
            raise ValueError("请先打开一个 JPHOO 系列会话")
        self._set(status="checking", login="checking", last_verified_at="")
        self._post("check", series_id=self.series_id)
        return self.status()

    def close(self):
        if not self.browser and not (self.thread and self.thread.is_alive()):
            return self.status()
        if self.scanner or self._snapshot().get("scanning"):
            self.close_after_scan.set()
            self._set(status="stopping", close_after_scan=True)
            self.stop()
            return self.status()
        self._set(status="closing")
        self._post("close")
        return self.status()

    def start(self, series_id, from_start=False):
        series_id = int(series_id)
        series = self._series(series_id)
        with self.lock:
            if self.scanner or self.result.get("scanning") or self.result.get("status") in {"starting", "running", "stopping"}:
                raise ValueError("JPHOO 扫描正在运行")
            if not self.result.get("window_open") or self.result.get("login") != "ready":
                raise ValueError("请先打开会话并验证 JPHOO 登录状态")
            # 先保留 starting 状态，再把命令交给会话线程，避免重复点击在 scanner 创建前排入两次。
            self.series_id = series_id
            self.scan_stop_requested.clear()
            self.result.update(status="starting", series_id=series_id, series_name=series["name"], source=self.source_name, scanning=True)
        self._post("scan", series_id=series_id, from_start=from_start)
        return self.status()
    def stop(self, series_id=None):
        if series_id is not None and self.series_id is not None and int(series_id) != self.series_id:
            raise ValueError("请求的系列不是当前正在扫描的系列")
        self.scan_stop_requested.set()
        scanner = self.scanner
        self._set(status="stopping", scanning=True)
        if self.series_id:
            self.database.set_scan_stopping(self.series_id, self.source_name)
        if scanner:
            scanner.stop()
        return self.status()
    def is_running_series(self, series_id):
        snapshot = self._snapshot()
        return bool(snapshot.get("scanning") and self.series_id == int(series_id))

    def status(self):
        # Playwright 对象只能由专用线程访问；轮询只投递一次轻量探测。
        if self._snapshot().get("window_open") and not self.scanner and not self.probe_pending.is_set():
            self.probe_pending.set()
            self._post("probe")
        data = self._snapshot()
        latest = self.database.latest_scan_status(self.source_name)
        if latest and self.scanner:
            for key, value in latest.items():
                if key not in {"status", "running", "series_id", "series_name", "source"}:
                    data[key] = value
        data["running"] = bool(data.get("scanning"))
        data["profile_dir"] = self.profile_dir
        return data

    def shutdown(self, timeout=15):
        """退出前先请求扫描安全停止，再由浏览器所属线程释放 Profile。"""
        self.shutdown_requested.set()
        if self.scanner or self._snapshot().get("scanning"):
            self._set(status="stopping", close_after_scan=True)
            self.stop()
        thread = self.thread
        if thread and thread.is_alive():
            self._post("shutdown")
            thread.join(max(0.0, float(timeout)))
        return not bool(thread and thread.is_alive())
    def _close_browser(self):
        """只能由会话专用线程调用。"""
        if self.browser:
            self.browser.close()
        self.browser = None
        self.scanner = None
        self._set(status="closed", login="unknown", session_state="closed", window_open=False, scanning=False, close_after_scan=False)
    def _worker(self):
        from .sources.jphoo import JphooSource
        while True:
            command, payload = self.queue.get()
            try:
                if command == "open":
                    series = self._series(payload["series_id"])
                    browser = self._open_browser()
                    browser.page.goto(series["url"], wait_until="domcontentloaded", timeout=45000)
                    self._diagnose(series["url"])
                    self._set(status="ready" if self._snapshot().get("login") == "ready" else "window_open", series_id=series["id"], series_name=series["name"], source=self.source_name)
                elif command == "check":
                    series = self._series(payload["series_id"])
                    browser = self._open_browser()
                    browser.page.goto(series["url"], wait_until="domcontentloaded", timeout=45000)
                    self._diagnose(series["url"])
                    self._set(status="ready" if self._snapshot().get("login") == "ready" else "window_open")
                elif command == "probe":
                    if not self.browser or not self.browser.is_open():
                        self.browser = None
                        self._set(status="closed", login="unknown", session_state="closed", window_open=False, scanning=False)
                elif command == "scan":
                    if self.scan_stop_requested.is_set():
                        self.scan_stop_requested.clear()
                        self._set(status="stopped", scanning=False)
                        continue
                    if self.close_after_scan.is_set() or self.shutdown_requested.is_set():
                        self._close_browser()
                        if self.shutdown_requested.is_set():
                            return
                        continue
                    series = self._series(payload["series_id"])
                    browser = self._open_browser()
                    browser.page.goto(series["url"], wait_until="domcontentloaded", timeout=45000)
                    diagnostic = self._diagnose(series["url"])
                    if diagnostic["login"] != "ready":
                        self._set(status="login_required" if diagnostic["login"] == "login_required" else "unknown", scanning=False)
                        continue
                    if self.scan_stop_requested.is_set():
                        self.scan_stop_requested.clear()
                        self._set(status="stopped", scanning=False)
                        continue
                    self.scanner = JphooScanner(self.database, self.profile_dir, source=JphooSource(browser=browser))
                    self._set(status="running", scanning=True, series_id=series["id"], series_name=series["name"], source=self.source_name)
                    result = self.scanner.run(series["id"], payload["from_start"])
                    self.scanner = None
                    if self.close_after_scan.is_set() or self.shutdown_requested.is_set():
                        self._close_browser()
                        if self.shutdown_requested.is_set():
                            return
                        self.close_after_scan.clear()
                        continue
                    self.scan_stop_requested.clear()
                    details = {key: value for key, value in result.items() if key != "status"}
                    self._set(**details, scanning=False, status=result["status"], login="login_required" if result["status"] == "login_required" else self._snapshot().get("login", "unknown"))
                elif command in {"close", "shutdown"}:
                    self._close_browser()
                    if command == "shutdown":
                        return
            except Exception as exc:
                self.scanner = None
                open_now = bool(self.browser and self.browser.is_open())
                self._set(status="failed" if open_now else "closed", login="unknown", message=str(exc)[:200], scanning=False, window_open=open_now, session_state="open" if open_now else "closed")
            finally:
                if command == "probe":
                    self.probe_pending.clear()
