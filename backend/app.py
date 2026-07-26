from __future__ import annotations
import argparse,json,os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlparse
from .db import LibraryDatabase
PAGE="""<!doctype html><meta charset=utf-8><title>Yav V2</title><body style='font-family:Microsoft YaHei UI;margin:40px'><h1>Yav V2 图书馆</h1><p>本地资料库已就绪；来源抓取将在后续阶段迁移。</p><input id=q placeholder='搜索影片名'><button onclick='go()'>搜索</button><ul id=r></ul><script>async function go(){let x=await fetch('/api/movies?query='+encodeURIComponent(q.value));let a=await x.json();r.innerHTML=a.length?a.map(m=>`<li>${m.favorite?'★ ':''}${m.title} · 磁链 ${m.magnet_count}</li>`).join(''):'<li>暂无影片</li>'}go()</script></body>"""
class Handler(BaseHTTPRequestHandler):
    database=None
    def do_GET(self):
        if self.path.startswith('/api/movies'):
            q=parse_qs(urlparse(self.path).query).get('query',[''])[0]; data=json.dumps(self.database.list_movies(q),ensure_ascii=False).encode(); self.send_response(200); self.send_header('Content-Type','application/json; charset=utf-8'); self.end_headers(); self.wfile.write(data)
        elif self.path=='/': self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(PAGE.encode())
        else: self.send_error(404)
    def log_message(self,*args): pass
def main():
    p=argparse.ArgumentParser(); p.add_argument('--data-dir',type=Path,default=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Yav'/'v2'); p.add_argument('--port',type=int,default=8765); a=p.parse_args(); Handler.database=LibraryDatabase(a.data_dir/'library.db'); print(f'Yav V2 已启动：http://127.0.0.1:{a.port}'); ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
if __name__=='__main__': main()
