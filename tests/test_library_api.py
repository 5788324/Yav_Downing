import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from backend.app import Handler
from backend.db import LibraryDatabase
from backend.library_actions import UpdateQueue
from backend.scanner import ScanManager


class LibraryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=LibraryDatabase(Path(self.tmp.name)/'library.db')
        self.movie=self.db.add_or_update_movie('Example',release_date='2026-01-10',duration_minutes=45)
        db=self.db
        class TestHandler(Handler):
            database=db
            scans=ScanManager(db)
            updates=None
            avfan_session=None
            jphoo_scans=None
        self.handler=TestHandler
        self.server=ThreadingHTTPServer(('127.0.0.1',0),TestHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def call(self,path,payload=None):
        req=Request(self.base+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=10) as response:
            return response,json.loads(response.read())

    def test_filters_export_and_atomic_favorites_routes(self):
        _,data=self.call('/api/movies?date_from=2026-01-01&duration=medium&sort=added')
        self.assertEqual(data['total'],1)
        self.call('/api/library/favorites',{'ids':[self.movie],'favorite':True})
        self.assertTrue(self.db.get_movie(self.movie)['favorite'])
        with self.assertRaises(HTTPError) as e:self.call('/api/library/favorites',{'ids':[self.movie,999],'favorite':False})
        self.assertEqual(e.exception.code,400);self.assertTrue(self.db.get_movie(self.movie)['favorite'])
        with urlopen(self.base+'/api/library/export?format=csv') as response:
            self.assertIn('attachment',response.headers['Content-Disposition'])
            self.assertIn('Example',response.read().decode('utf-8-sig'))

    def test_backup_and_unknown_apis_have_reviewable_responses(self):
        _,before=self.call('/api/library/backups');self.assertEqual(before['latest'],'')
        _,backup=self.call('/api/library/backup',{})
        self.assertTrue(Path(backup['backup_dir'],'library.db').is_file())
        _,after=self.call('/api/library/backups');self.assertTrue(after['created_at'])
        _,failures=self.call('/api/library/failures');self.assertEqual(failures,[])
        with self.assertRaises(HTTPError) as e:self.call('/api/library/not-found')
        self.assertEqual(e.exception.code,404)

    def test_invalid_cover_does_not_write_movie(self):
        with self.assertRaises(HTTPError) as e:self.call(f'/api/movies/{self.movie}/cover',{'data':'not-base64'})
        self.assertEqual(e.exception.code,400)
        self.assertEqual(self.db.get_movie(self.movie)['cover_path'],'')


if __name__=='__main__':unittest.main()
