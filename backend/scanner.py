"""本地、单线程的 JavDB 系列扫描器。"""
from __future__ import annotations
from threading import Event
from .sources.javdb import JavdbSource

class JavdbScanner:
 def __init__(self,database): self.db=database; self.stop_event=Event()
 def stop(self): self.stop_event.set()
 def run(self,series_id,from_start=False):
  with self.db.connect() as db:
   series=db.execute('SELECT * FROM source_series WHERE id=? AND source=?',(series_id,'javdb')).fetchone()
   if not series: raise ValueError('JavDB 系列不存在')
   page=1 if from_start else max(1,series['last_completed_page']+1); now=self.db.now()
   run_id=db.execute("INSERT INTO scan_runs(series_id,status,started_at) VALUES(?,?,?)",(series_id,'running',now)).lastrowid
  source=JavdbSource(); stats={'discovered':0,'new_movies':0,'new_magnets':0,'failures':0}
  try:
   for page,urls in source.scan_series(series['url'],start_page=page,stop_event=self.stop_event):
    for url in urls:
     if self.stop_event.is_set(): break
     stats['discovered']+=1
     try:
      data=source.fetch_movie(url); before=len(self.db.list_movies(query=data.title,page_size=1)['items']); movie=self.db.add_or_update_movie(data.title,studio=data.studio,series=data.series or series['name'],release_date=data.release_date,duration_minutes=data.duration_minutes,cover_url=data.cover_url,actresses=data.actresses,source='javdb',source_url=url)
      if not before: stats['new_movies']+=1
      for item in source.fetch_magnets(url):
       try: self.db.add_magnet(movie,item.magnet,'javdb',url,item.size_bytes); stats['new_magnets']+=1
       except ValueError: pass
     except Exception: stats['failures']+=1
    with self.db.connect() as db:
     db.execute('UPDATE source_series SET last_completed_page=? WHERE id=?',(page,series_id)); db.execute('UPDATE scan_runs SET current_page=?,discovered=?,new_movies=?,new_magnets=?,failures=? WHERE id=?',(page,*stats.values(),run_id))
    if self.stop_event.is_set(): break
   status='stopped' if self.stop_event.is_set() else 'completed'
  except Exception as exc: status='failed'; stats['failures']+=1
  with self.db.connect() as db:
   db.execute("UPDATE scan_runs SET status=?,discovered=?,new_movies=?,new_magnets=?,failures=?,finished_at=? WHERE id=?",(status,*stats.values(),self.db.now(),run_id));
   if status=='completed': db.execute('UPDATE source_series SET last_scanned_at=? WHERE id=?',(self.db.now(),series_id))
  return {'status':status,**stats,'page':page}

class ScanManager:
    """应用进程内只运行一个 JavDB 扫描，避免并发请求站点。"""
    def __init__(self, database):
        self.database=database; self.scanner=None; self.thread=None; self.result=None
    def start(self, series_id, from_start=False):
        from threading import Thread
        if self.thread and self.thread.is_alive(): raise ValueError('已有扫描正在运行')
        self.scanner=JavdbScanner(self.database); self.result={'status':'starting'}
        def worker(): self.result=self.scanner.run(series_id,from_start)
        self.thread=Thread(target=worker,daemon=True); self.thread.start(); return self.status()
    def stop(self):
        if self.scanner: self.scanner.stop()
        return self.status()
    def status(self):
        running=bool(self.thread and self.thread.is_alive())
        return {**(self.result or {'status':'idle'}),'running':running}
