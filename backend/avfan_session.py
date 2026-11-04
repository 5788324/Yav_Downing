"""AVFan 浏览器与扫描在同一工作线程中运行。"""
from queue import Queue
from threading import Thread, RLock, Event
from .scan_avfan import AvfanScanner
from .sources.avfan import AvfanSource, checked_soup, validate_url


class AvfanSession:
    def __init__(self, database, profile):
        self.db, self.profile = database, str(profile)
        self.lock, self.queue, self.cancel = RLock(), Queue(), Event()
        self.state = {'status':'closed', 'login':'closed', 'window_open':False}
        self.result = {'status':'idle', 'source':'avfan', 'running':False}
        self.scanner = None
        self.thread = Thread(target=self._worker, daemon=True)
        self.thread.start()

    def session_status(self):
        with self.lock: return dict(self.state)

    def status(self):
        with self.lock:
            result = dict(self.result)
        if result.get('running'):
            latest = self.db.latest_scan_status('avfan')
            if latest and latest['series_id'] == result.get('series_id'):
                return {**latest, 'running':True}
        return result

    def is_running_series(self, sid):
        with self.lock: return self.result.get('running') and self.result.get('series_id') == int(sid)

    def action(self, action, sid=None):
        with self.lock:
            if self.result.get('running'): raise ValueError('请先停止 AVFan 扫描')
            if self.state['status'] in {'opening','checking','closing'}: raise ValueError('会话操作正在进行')
            url = None
            if action == 'open':
                row = self.db.get_source_series(int(sid or 0), 'avfan')
                if not row: raise ValueError('请先选择 AVFan 来源')
                url = validate_url(row['url'])
            self.state['status'] = {'open':'opening','check':'checking','close':'closing'}[action]
            self.queue.put((action, url))
            return dict(self.state)

    def start(self, sid, from_start=False):
        with self.lock:
            if self.result.get('running'): raise ValueError('AVFan 已有扫描正在运行')
            if self.state['status'] != 'ready' or not self.state['window_open']: raise ValueError('请先打开 AVFan 会话并验证页面')
            row = self.db.get_source_series(sid, 'avfan')
            if not row or not row['enabled']: raise ValueError('来源不存在或已停用')
            self.cancel.clear()
            self.result = {'status':'starting','source':'avfan','series_id':sid,'series_name':row['name'],'running':True}
            self.queue.put(('scan',(sid, from_start)))
            return dict(self.result)

    def stop(self, sid=None):
        with self.lock:
            if not self.result.get('running'): return dict(self.result)
            if sid is not None and int(sid) != self.result['series_id']: raise ValueError('请求的系列不是当前正在扫描的系列')
            self.cancel.set()
            if self.scanner: self.scanner.stop()
            self.result['status'] = 'stopping'
            return dict(self.result)

    def shutdown(self, timeout=15):
        self.stop(); self.queue.put(('shutdown',None)); self.thread.join(timeout)
        return not self.thread.is_alive()

    def _worker(self):
        context = pw = page = None
        try:
            while True:
                action, data = self.queue.get()
                try:
                    if action in {'close','shutdown'}:
                        if context: context.close()
                        if pw: pw.stop()
                        context = pw = page = None
                        with self.lock: self.state = {'status':'closed','login':'closed','window_open':False}
                        if action == 'shutdown': return
                    elif action == 'open':
                        if not context:
                            from playwright.sync_api import sync_playwright
                            pw = sync_playwright().start()
                            context = pw.chromium.launch_persistent_context(self.profile, channel='msedge', headless=False)
                            page = context.pages[0] if context.pages else context.new_page()
                        page.goto(data, wait_until='domcontentloaded', timeout=30000)
                        with self.lock: self.state = {'status':'window_open','login':'unknown','window_open':True}
                    elif action == 'check':
                        if not page or page.is_closed(): raise ValueError('AVFan 浏览器已关闭')
                        validate_url(page.url); soup = checked_soup(page.content())
                        if not soup.select_one('h1, h2'): raise ValueError('请打开正常的系列或影片页面')
                        with self.lock: self.state = {'status':'ready','login':'ready','window_open':True}
                    elif action == 'scan':
                        sid, full = data
                        scanner = AvfanScanner(self.db)
                        def load(url):
                            if self.cancel.is_set(): scanner.stop(); raise RuntimeError('扫描已停止')
                            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                            html = page.content()
                            try:
                                checked_soup(html)
                                if response and response.status in {401,403,429}: raise RuntimeError(f'AVFan HTTP {response.status}，请检查验证或限流状态')
                            except RuntimeError:
                                scanner.stop()
                                with self.lock: self.state = {'status':'login_required','login':'unknown','window_open':True}
                                raise
                            if response and response.status >= 400: raise RuntimeError(f'AVFan HTTP {response.status}')
                            return html
                        scanner.source_factory = lambda: AvfanSource(loader=load)
                        with self.lock:
                            self.scanner = scanner
                            if self.cancel.is_set(): scanner.stop()
                        if self.cancel.is_set(): result = {'status':'stopped'}
                        else: result = scanner.run(sid, full)
                        with self.lock: self.result = {**self.result, **result, 'running':False}; self.scanner = None
                        self.cancel.clear()
                except Exception as exc:
                    with self.lock:
                        if action == 'scan': self.result = {**self.result,'status':'failed','running':False,'message':str(exc)[:200]}; self.scanner = None
                        else: self.state = {'status':'failed','login':'unknown','window_open':bool(page and not page.is_closed()),'error':str(exc)[:200]}
                    self.cancel.clear()
        finally:
            if context: context.close()
            if pw: pw.stop()
