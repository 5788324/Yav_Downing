"""本地单线程来源扫描器：JavDB 与 JPHOO 共用简单进度模型。"""
from __future__ import annotations
import json
from threading import Event, Thread
from .sources.javdb import JavdbSource

class BaseScanner:
    source_name = ""
    def __init__(self, database): self.db=database; self.stop_event=Event()
    def stop(self): self.stop_event.set()
    def _begin(self, series_id, from_start):
        with self.db.connect() as db:
            series=db.execute("SELECT * FROM source_series WHERE id=? AND source=?",(series_id,self.source_name)).fetchone()
            if not series: raise ValueError(f"{self.source_name} 系列不存在")
            page=1 if from_start else max(1,series["last_completed_page"]+1)
            run_id=db.execute("INSERT INTO scan_runs(series_id,status,started_at) VALUES(?,?,?)",(series_id,"running",self.db.now())).lastrowid
        return series,page,run_id
    def _save_progress(self, series_id,run_id,page,stats,last_error=""):
        with self.db.connect() as db:
            db.execute("UPDATE source_series SET last_completed_page=? WHERE id=?",(page,series_id))
            db.execute("""UPDATE scan_runs SET current_page=?,discovered=?,processed_count=?,new_movies=?,new_magnets=?,failures=?,matched_current=?,attached_other_movies=?,unmatched_candidates=?,last_error=?,message=? WHERE id=?""",(page,stats["discovered"],stats["processed"],stats["new_movies"],stats["new_magnets"],stats["failures"],stats["matched_current"],stats["attached_other_movies"],stats["unmatched_candidates"],last_error[:200],json.dumps({k:stats[k] for k in ("matched_current","attached_other_movies","unmatched_candidates")},ensure_ascii=False),run_id))
    def _finish(self,series_id,run_id,page,stats,status,error=""):
        with self.db.connect() as db:
            db.execute("""UPDATE scan_runs SET status=?,current_page=?,discovered=?,processed_count=?,new_movies=?,new_magnets=?,failures=?,matched_current=?,attached_other_movies=?,unmatched_candidates=?,last_error=?,message=?,finished_at=? WHERE id=?""",(status,page,stats["discovered"],stats["processed"],stats["new_movies"],stats["new_magnets"],stats["failures"],stats["matched_current"],stats["attached_other_movies"],stats["unmatched_candidates"],error[:200],error[:200],self.db.now(),run_id))
            if status=="completed": db.execute("UPDATE source_series SET last_scanned_at=? WHERE id=?",(self.db.now(),series_id))

class JavdbScanner(BaseScanner):
    source_name="javdb"
    def run(self,series_id,from_start=False):
        series,page,run_id=self._begin(series_id,from_start); stats={k:0 for k in ("discovered","processed","new_movies","new_magnets","failures","matched_current","attached_other_movies","unmatched_candidates")}; source=JavdbSource(); error=""
        try:
            for page,urls in source.scan_series(series["url"],start_page=page,stop_event=self.stop_event):
                for url in urls:
                    if self.stop_event.is_set(): break
                    stats["discovered"]+=1
                    try:
                        data=source.fetch_movie(url); existed=self.db.movie_import_exists(data.title,"javdb",url)
                        movie=self.db.add_or_update_movie(data.title,studio=data.studio,series=data.series or series["name"],release_date=data.release_date,duration_minutes=data.duration_minutes,cover_url=data.cover_url,actresses=data.actresses,source="javdb",source_url=url); stats["new_movies"]+=int(not existed)
                        for item in source.fetch_magnets(url):
                            from .db import extract_btih
                            old={row["btih"] for row in (self.db.get_movie(movie) or {}).get("magnets",[])}; self.db.add_magnet(movie,item.magnet,"javdb",url,item.size_bytes); stats["new_magnets"]+=int(extract_btih(item.magnet) not in old)
                        stats["processed"]+=1
                    except Exception as exc: stats["failures"]+=1; error=str(exc)
                self._save_progress(series_id,run_id,page,stats,error)
                if self.stop_event.is_set(): break
            status="stopped" if self.stop_event.is_set() else "completed"
        except Exception as exc: status="failed"; stats["failures"]+=1; error=str(exc)
        self._finish(series_id,run_id,page,stats,status,error); return {"status":status,"page":page,"message":error,**stats}

class JphooScanner(BaseScanner):
    source_name="jphoo"
    def __init__(self,database,profile_dir): super().__init__(database); self.profile_dir=profile_dir; self.source=None
    def run(self,series_id,from_start=False):
        from .sources.jphoo import JphooSource,LoginRequired,persist_candidates
        series,page,run_id=self._begin(series_id,from_start); stats={k:0 for k in ("discovered","processed","new_movies","new_magnets","failures","matched_current","attached_other_movies","unmatched_candidates")}; error=""; self.source=JphooSource()
        try:
            self.source.open_browser(series["profile_dir"] or self.profile_dir)
            for page,urls in self.source.scan_series(series["url"],start_page=page,stop_event=self.stop_event):
                for url in urls:
                    if self.stop_event.is_set(): break
                    stats["discovered"]+=1
                    try:
                        data=self.source.fetch_movie(url)
                        if not data.title: raise ValueError("JPHOO 页面未解析到影片名")
                        existed=self.db.movie_import_exists(data.title,"jphoo",url)
                        movie=self.db.add_or_update_movie(data.title,studio=data.studio,series=data.series or series["name"],release_date=data.release_date,duration_minutes=data.duration_minutes,cover_url=data.cover_url,actresses=data.actresses,source="jphoo",source_url=url); stats["new_movies"]+=int(not existed)
                        outcome=persist_candidates(self.db,movie,data.title,url,self.source.fetch_magnet_candidates())
                        stats["new_magnets"]+=outcome["new_magnets"]; stats["matched_current"]+=outcome["matched_current"]; stats["attached_other_movies"]+=outcome["attached_other"]; stats["unmatched_candidates"]+=outcome["unmatched"]; stats["processed"]+=1
                    except LoginRequired: raise
                    except Exception as exc: stats["failures"]+=1; error=str(exc)
                self._save_progress(series_id,run_id,page,stats,error)
                if self.stop_event.is_set(): break
            status="stopped" if self.stop_event.is_set() else "completed"
        except LoginRequired as exc: status="login_required"; error=str(exc)
        except Exception as exc: status="failed"; stats["failures"]+=1; error=str(exc)
        finally:
            if self.source: self.source.close()
        self._finish(series_id,run_id,page,stats,status,error); return {"status":status,"page":page,"message":error,**stats}

class ScanManager:
    scanner_class=JavdbScanner
    def __init__(self,database): self.database=database; self.scanner=None; self.thread=None; self.result=None
    def make_scanner(self): return self.scanner_class(self.database)
    def start(self,series_id,from_start=False):
        if self.thread and self.thread.is_alive(): raise ValueError("该来源已有扫描正在运行")
        self.scanner=self.make_scanner(); self.result={"status":"starting"}; self.thread=Thread(target=lambda:setattr(self,"result",self.scanner.run(series_id,from_start)),daemon=True); self.thread.start(); return self.status()
    def stop(self):
        if self.scanner: self.scanner.stop()
        return self.status()
    def status(self): return {**(self.result or {"status":"idle"}),"running":bool(self.thread and self.thread.is_alive())}

class JphooScanManager(ScanManager):
    scanner_class=JphooScanner
    def __init__(self,database,profile_dir): super().__init__(database); self.profile_dir=profile_dir
    def make_scanner(self): return JphooScanner(self.database,self.profile_dir)

class JphooLoginManager:
    def __init__(self,profile_dir): self.profile_dir=profile_dir; self.thread=None; self._close=Event(); self._check=Event(); self.result={"status":"idle","profile_dir":str(profile_dir)}
    def open(self):
        if self.thread and self.thread.is_alive(): return self.status()
        self._close.clear(); self.result={"status":"opening","profile_dir":str(self.profile_dir)}
        def worker():
            from .sources.jphoo import JphooSource
            source=JphooSource()
            try:
                page=source.open_browser(self.profile_dir); page.goto("https://www.jphoo.net",wait_until="domcontentloaded",timeout=45000); self.result={"status":"window_open","profile_dir":str(self.profile_dir),"login":"unchecked"}
                while not self._close.wait(.25):
                    if self._check.is_set(): self._check.clear(); self.result={"status":"window_open","profile_dir":str(self.profile_dir),"login":"login_required" if source.browser.login_required() else "ready"}
            except Exception as exc: self.result={"status":"failed","profile_dir":str(self.profile_dir),"message":str(exc)[:200]}
            finally: source.close()
        self.thread=Thread(target=worker,daemon=True); self.thread.start(); return self.status()
    def check(self):
        if not self.thread or not self.thread.is_alive(): return {"status":"idle","profile_dir":str(self.profile_dir),"login":"unknown"}
        self._check.set(); return self.status()
    def close(self): self._close.set(); return self.status()
    def status(self): return {**self.result,"window_open":bool(self.thread and self.thread.is_alive())}
