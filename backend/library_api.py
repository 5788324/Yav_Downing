"""图书馆便捷操作的本机 HTTP 入口。"""
import json
import os
import re
from .backup import backup_data_dir
from .library_actions import export_movies, failure_kind, save_cover


FILTER_KEYS = ('sort','date_from','date_to','duration','missing','run_id','update_kind')


def extra_filters(query):
    return {k:query[k][0] for k in FILTER_KEYS if query.get(k)}


def _idle(handler):
    if handler.updates and handler.updates.running(): raise ValueError('请先停止更新队列')
    for manager in (handler.scans,handler.jphoo_scans,handler.avfan_session):
        if manager and manager.status().get('running'): raise ValueError('请先停止当前扫描')


def get(handler,path,query):
    if not path.startswith('/api/library/'): return False
    db=handler.database
    try:
        if path=='/api/library/queue': handler._json(handler.updates.status() if handler.updates else {'status':'idle','items':[],'running':False})
        elif path=='/api/library/scans': handler._json(db.scan_history())
        elif path=='/api/library/failures':
            with db.connect() as c:
                rows=[dict(r) for r in c.execute("SELECT f.*,s.name FROM scan_failures f JOIN source_series s ON s.id=f.series_id WHERE f.resolved_at='' ORDER BY f.series_id,f.page,f.id")]
            for row in rows: row['kind']=failure_kind(row['last_error'])
            handler._json(rows)
        elif path=='/api/library/backups':
            directory=db.path.parent/'backups'
            folders=sorted([p for p in directory.glob('yav-v2-backup-*') if (p/'manifest.json').is_file()],reverse=True)
            latest=folders[0] if folders else None
            handler._json({'directory':str(directory),'latest':str(latest) if latest else '', 'created_at':json.loads((latest/'manifest.json').read_text(encoding='utf-8')).get('created_at','') if latest else ''})
        elif path=='/api/library/export':
            filters={k:query[k][0] for k in ('studio','series','actress','source') if query.get(k)}
            filters.update(extra_filters(query));filters['query']=query.get('q',[''])[0]
            for key in ('favorite','has_magnet'): filters[key]=handler._optional_bool(query.get(key,[''])[0])
            ids=[int(i) for i in query.get('ids',[''])[0].split(',') if i]
            if len(ids)>100: raise ValueError('一次最多导出 100 部选中影片')
            magnets=query.get('format',['csv'])[0]=='txt'
            content=export_movies(db,filters,ids=ids,magnets=magnets)
            handler.send_response(200)
            handler.send_header('Content-Type','text/plain; charset=utf-8' if magnets else 'text/csv; charset=utf-8')
            handler.send_header('Content-Disposition','attachment; filename="yav-library.'+('txt' if magnets else 'csv')+'"')
            handler.send_header('Content-Length',str(len(content)));handler.send_header('Cache-Control','no-store')
            handler.end_headers();handler.wfile.write(content)
        else: handler._json({'error':'未知图书馆操作'},404)
    except (ValueError,TypeError,OSError) as exc: handler._json({'error':str(exc)},400)
    return True


def post(handler,path):
    match=re.fullmatch(r'/api/movies/(\d+)/cover',path)
    if not match and not path.startswith('/api/library/'): return False
    try:
        payload=handler._read_json()
        if not isinstance(payload,dict): raise ValueError('请求内容必须是对象')
        if match: handler._json(save_cover(handler.database,int(match[1]),payload))
        elif path=='/api/library/favorites': handler._json(handler.database.batch_favorite(payload.get('ids'),payload.get('favorite')))
        elif path=='/api/library/backup':
            _idle(handler);handler._json(backup_data_dir(handler.database.path.parent),201)
        elif path=='/api/library/open-backups':
            directory=handler.database.path.parent/'backups';directory.mkdir(exist_ok=True)
            if not hasattr(os,'startfile'): raise ValueError('打开目录功能仅适用于 Windows')
            os.startfile(str(directory));handler._json({'opened':True})
        elif path in ('/api/library/queue/start','/api/library/queue/resume','/api/library/queue/stop'):
            if not handler.updates: raise ValueError('更新队列尚未初始化')
            action=path.rsplit('/',1)[1]
            if action=='stop': result=handler.updates.stop()
            else: result=handler.updates.start(payload.get('ids'),payload.get('mode','scan'),resume=action=='resume')
            handler._json(result,202)
        else: handler._json({'error':'未知图书馆操作'},404)
    except (ValueError,TypeError,OSError) as exc:
        handler._json({'error':str(exc)},400)
    return True
