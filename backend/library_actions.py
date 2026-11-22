"""本地图书馆的更新排队、导出和封面操作。业务状态保存在 SQLite。"""
from __future__ import annotations

import base64
import csv
import io
import threading
import time
import uuid

import requests

from .backup import backup_data_dir


def failure_kind(message):
    text = (message or '').lower()
    if any(t in text for t in ('版权', 'copyright', 'not available in your country')):
        return '受版权地区限制'
    if any(t in text for t in ('locked', 'busy', '数据库忙')): return '数据库暂忙，可重试'
    if any(t in text for t in ('403', '401', '验证', '登录', 'login', 'challenge', 'just a moment')):
        return '需要人工验证或登录'
    if any(t in text for t in ('429', '限流')): return '请求过多，稍后重试'
    if any(t in text for t in ('timeout', 'connection', 'network', '超时', '网络')): return '网络连接失败'
    return '页面或资料异常'


class UpdateQueue:
    def __init__(self, database, managers):
        self.db, self.managers = database, managers
        self.lock, self.cancel = threading.RLock(), threading.Event()
        self.thread = None
        self.current = None
        with self.db.connect() as c:
            c.execute("UPDATE update_jobs SET status='interrupted' WHERE status IN ('running','stopping')")
            c.execute("UPDATE update_job_items SET status='interrupted' WHERE status='running'")

    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def reserved(self, series_id):
        if not self.running(): return False
        with self.db.connect() as c:
            return bool(c.execute("SELECT 1 FROM update_job_items i JOIN update_jobs j ON j.id=i.job_id WHERE i.series_id=? AND j.status IN ('running','stopping') AND i.status!='completed'", (series_id,)).fetchone())

    def status(self):
        with self.db.connect() as c:
            row = c.execute('SELECT * FROM update_jobs ORDER BY id DESC LIMIT 1').fetchone()
            if not row: return {'status':'idle','running':False,'items':[]}
            job = dict(row)
            job['items'] = [dict(r) for r in c.execute('''SELECT i.*,s.name,s.source,
                r.current_page,r.new_movies,r.new_magnets,r.processed_count,r.failures,r.last_error
                FROM update_job_items i JOIN source_series s ON s.id=i.series_id
                LEFT JOIN scan_runs r ON r.id=i.run_id WHERE i.job_id=? ORDER BY i.rowid''',(row['id'],))]
        job['running'] = self.running()
        return job

    def start(self, ids=None, mode='scan', resume=False):
        with self.lock:
            if self.running(): raise ValueError('已有更新队列正在运行')
            if any(m.status().get('running') for m in self.managers.values()): raise ValueError('请先结束当前单系列扫描')
            if mode not in {'scan','retry'}: raise ValueError('无效更新方式')
            with self.db.connect() as c:
                if c.execute("SELECT 1 FROM scan_runs WHERE status IN ('running','starting','stopping')").fetchone():
                    raise ValueError('已有扫描正在运行')
                if resume:
                    job = c.execute('SELECT * FROM update_jobs ORDER BY id DESC LIMIT 1').fetchone()
                    if not job or job['status'] == 'completed': raise ValueError('没有待继续的更新队列')
                    job_id = job['id']
                    c.execute("UPDATE update_jobs SET status='running',last_error='',finished_at='' WHERE id=?",(job_id,))
                else:
                    if not isinstance(ids,list) or not ids or len(ids)>100 or any(type(i) is not int for i in ids):
                        raise ValueError('请选择要更新的系列')
                    ids = list(dict.fromkeys(ids))
                    for sid in ids:
                        row = c.execute('SELECT * FROM source_series WHERE id=?',(sid,)).fetchone()
                        if not row or not row['enabled'] or row['source'] not in self.managers: raise ValueError('所选来源不存在或已停用')
                    job_id = c.execute("INSERT INTO update_jobs(status,created_at) VALUES('running',?)",(self.db.now(),)).lastrowid
                    c.executemany('INSERT INTO update_job_items(job_id,series_id,mode) VALUES(?,?,?)',[(job_id,sid,mode) for sid in ids])
            self.cancel.clear()
            self.thread = threading.Thread(target=self._worker,args=(job_id,),daemon=True,name='yav-update-queue')
            self.thread.start()
        return self.status()

    def stop(self):
        with self.lock:
            self.cancel.set()
            if self.running():
                with self.db.connect() as c:
                    c.execute("UPDATE update_jobs SET status='stopping' WHERE status='running'")
            if self.current:
                source, sid = self.current
                self.managers[source].stop(sid)
        return self.status()

    def shutdown(self, timeout=35):
        self.stop()
        if self.thread: self.thread.join(timeout)
        return not self.running()

    def _worker(self, job_id):
        status, error = 'completed', ''
        try:
            backup = backup_data_dir(self.db.path.parent)
            with self.db.connect() as c:
                c.execute('UPDATE update_jobs SET backup_path=? WHERE id=?',(str(backup['backup_dir']),job_id))
                items = [dict(r) for r in c.execute('''SELECT i.*,s.source,s.enabled FROM update_job_items i
                    JOIN source_series s ON s.id=i.series_id WHERE job_id=? ORDER BY i.rowid''',(job_id,))]
            for item in items:
                if item['status']=='completed': continue
                if self.cancel.is_set(): status='stopped'; break
                if not item['enabled']: raise ValueError('队列中的系列已停用，请重新选择')
                manager = self.managers[item['source']]
                with self.lock:
                    if self.cancel.is_set(): status='stopped'; break
                    if any(m.status().get('running') for m in self.managers.values()): raise ValueError('其他扫描已启动，队列已暂停')
                    self.current = (item['source'],item['series_id'])
                    with self.db.connect() as c:
                        previous = c.execute('SELECT COALESCE(MAX(id),0) FROM scan_runs').fetchone()[0]
                    manager.start(item['series_id'], item['status']=='pending' and item['mode']=='scan', retry_only=item['mode']=='retry')
                with self.db.connect() as c:
                    c.execute("UPDATE update_job_items SET status='running' WHERE job_id=? AND series_id=?",(job_id,item['series_id']))
                run_id = None
                while manager.status().get('running'):
                    if run_id is None:
                        with self.db.connect() as c:
                            run = c.execute('SELECT id FROM scan_runs WHERE id>? AND series_id=? ORDER BY id DESC LIMIT 1',(previous,item['series_id'])).fetchone()
                            if run:
                                run_id = run[0]
                                c.execute('UPDATE update_job_items SET run_id=? WHERE job_id=? AND series_id=?',(run_id,job_id,item['series_id']))
                    time.sleep(0.4)
                with self.db.connect() as c:
                    run = c.execute('SELECT * FROM scan_runs WHERE id>? AND series_id=? ORDER BY id DESC LIMIT 1',(previous,item['series_id'])).fetchone()
                    result = manager.status()
                    final = run['status'] if run else result.get('status','failed')
                    if self.cancel.is_set(): final='stopped'
                    c.execute('UPDATE update_job_items SET status=?,run_id=? WHERE job_id=? AND series_id=?',(final,run['id'] if run else None,job_id,item['series_id']))
                if final!='completed':
                    status = 'stopped' if self.cancel.is_set() else 'needs_attention'
                    error = (run['last_error'] if run else result.get('message') or result.get('error')) or '请检查来源会话，验证后继续队列'
                    break
        except Exception as exc:
            status,error = ('stopped' if self.cancel.is_set() else 'needs_attention'),str(exc)
        finally:
            with self.lock: self.current = None
            with self.db.connect() as c:
                c.execute('UPDATE update_jobs SET status=?,last_error=?,finished_at=? WHERE id=?',(status,error,self.db.now(),job_id))


def image_extension(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return '.png'
    if data.startswith(b'\xff\xd8\xff'): return '.jpg'
    if data[:6] in (b'GIF87a',b'GIF89a'): return '.gif'
    if data.startswith(b'RIFF') and data[8:12]==b'WEBP': return '.webp'
    raise ValueError('请选择 PNG、JPEG、GIF 或 WebP 图片')


def save_cover(db, movie_id, payload):
    movie = db.get_movie(movie_id)
    if not movie: raise ValueError('影片不存在')
    manual = payload.get('action') != 'refresh'
    if manual:
        try: data = base64.b64decode(payload.get('data',''),validate=True)
        except (ValueError,TypeError) as exc: raise ValueError('图片内容无效') from exc
    else:
        if movie.get('cover_path') and 'cover_url' in movie['manual_fields']:
            raise ValueError('已有手动封面，请使用更换本地封面')
        if not movie.get('cover_url','').startswith(('https://','http://')): raise ValueError('没有可重新获取的封面网址')
        with requests.get(movie['cover_url'],stream=True,timeout=(5,15)) as response:
            response.raise_for_status()
            chunks=[]; size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>8*1024*1024: raise ValueError('封面不能超过 8 MB')
                chunks.append(chunk)
            data=b''.join(chunks)
    if not data or len(data)>8*1024*1024: raise ValueError('封面不能为空且不能超过 8 MB')
    extension=image_extension(data)
    directory=db.path.parent/'covers'; directory.mkdir(exist_ok=True)
    path=directory/(uuid.uuid4().hex+extension)
    path.write_bytes(data)
    try: return db.set_local_cover(movie_id,path,manual=manual)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def export_movies(db, query, ids=None, magnets=False):
    rows=[]; page=1
    selected=set(ids) if ids else None
    while True:
        batch=db.list_movies(**query,page=page,page_size=100)
        rows.extend(r for r in batch['items'] if selected is None or r['id'] in selected)
        if page>=batch['pages']: break
        page+=1
    if magnets:
        links_by_movie={}
        ids=[r['id'] for r in rows]
        for offset in range(0,len(ids),400):
            group=ids[offset:offset+400];marks=','.join('?' for _ in group)
            with db.connect() as c:
                found=c.execute(f'SELECT movie_id,magnet,btih FROM magnets WHERE movie_id IN ({marks}) ORDER BY id',group).fetchall()
            for item in found: links_by_movie.setdefault(item['movie_id'],[]).append(item)
        lines=[];seen=set()
        for row in rows:
            links=[]
            for item in links_by_movie.get(row['id'],[]):
                if item['btih'] in seen: continue
                seen.add(item['btih']);links.append(item['magnet'])
            if links: lines.extend([row['title'],*links,''])
        return '\n'.join(lines).encode('utf-8-sig')
    output=io.StringIO(newline=''); writer=csv.writer(output)
    writer.writerow(['影片名','厂商','系列','女演员','日期','时长（分钟）','收藏','磁链数','封面网址','磁链来源'])
    for row in rows:
        cells=[row['title'],row['studio'],row['series'],'、'.join(row['actresses']),row['release_date'],row['duration_minutes'] if row['duration_minutes'] is not None else '', '是' if row['favorite'] else '否',row['magnet_count'],row['cover_url'],'、'.join(row.get('source_counts',{}))]
        writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v for v in cells])
    return output.getvalue().encode('utf-8-sig')
