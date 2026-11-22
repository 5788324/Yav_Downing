import base64
import csv
import io
import sqlite3
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import LibraryDatabase
from backend.library_actions import UpdateQueue, export_movies, failure_kind, save_cover
from backend.scanner import JavdbScanner
from backend.sources.javdb import JavdbSessionError, SourceMovie, SourceMagnet, checked_page


class Source:
    def scan_series(self, url, **kwargs):
        yield 1, [url.replace('/series/', '/v/')]

    def fetch_movie(self, url):
        return SourceMovie('Example '+url.rsplit('/',1)[1],url,studio='Studio',series='Series',actresses=['Alice'])

    def fetch_magnets(self, url):
        return [SourceMagnet('magnet:?xt=urn:btih:'+'A'*40,100)]


class LibraryActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=LibraryDatabase(Path(self.tmp.name)/'library.db')

    def tearDown(self):
        self.tmp.cleanup()

    def movie(self,title='Example',**kwargs):
        return self.db.add_or_update_movie(title,source='javdb',source_url='https://example.com/v/'+title,**kwargs)

    def test_filters_have_nonoverlapping_duration_bounds_and_stable_sort(self):
        a=self.movie('A',release_date='2025-01-01',duration_minutes=29)
        b=self.movie('B',release_date='2026-02-01',duration_minutes=30)
        self.movie('C',release_date='2026-03-01',duration_minutes=60)
        self.movie('D',duration_minutes=61)
        self.movie('E')
        self.assertEqual(self.db.list_movies(duration='medium')['total'],2)
        self.assertEqual(self.db.list_movies(duration='short')['items'][0]['id'],a)
        self.assertEqual(self.db.list_movies(duration='long')['total'],1)
        self.assertEqual(self.db.list_movies(duration='unknown')['total'],1)
        self.assertEqual(self.db.list_movies(date_from='2026-01-01',date_to='2026-02-28')['items'][0]['id'],b)
        self.assertEqual(self.db.list_movies(missing='date')['total'],2)
        self.assertEqual(self.db.get_filters()['years'],['2026','2025'])
        with self.assertRaises(ValueError): self.db.list_movies(sort='title; DELETE FROM movies')
        with self.assertRaises(ValueError): self.db.list_movies(date_from='2027-01-01',date_to='2026-01-01')

    def test_batch_favorite_is_atomic_and_does_not_change_manual_metadata(self):
        a=self.movie();self.db.update_movie(a,{'studio':'Manual'})
        with self.assertRaises(ValueError): self.db.batch_favorite([a,999999],True)
        self.assertFalse(self.db.get_movie(a)['favorite'])
        self.db.batch_favorite([a,a],True)
        item=self.db.get_movie(a)
        self.assertTrue(item['favorite']);self.assertEqual(item['studio'],'Manual')
        self.assertEqual(item['manual_fields'],['studio'])
        with self.assertRaises(ValueError): self.db.batch_favorite([a],'false')

    def test_transaction_rolls_back_on_exception(self):
        a=self.movie()
        with self.assertRaises(RuntimeError):
            with self.db.connect() as c:
                c.execute('UPDATE movies SET favorite=1 WHERE id=?',(a,));raise RuntimeError('cancel')
        self.assertFalse(self.db.get_movie(a)['favorite'])

    def test_source_comparison_exposes_original_values_without_changing_manual_fields(self):
        a=self.movie(studio='Original',release_date='2026-01-01',duration_minutes=45)
        self.db.update_movie(a,{'studio':'Manual'})
        row=self.db.get_movie(a)
        self.assertEqual(row['sources'][0]['studio'],'Original')
        self.assertEqual(row['sources'][0]['duration_minutes'],45)
        self.assertEqual(row['studio'],'Manual')

    def test_deleting_scanned_series_configuration_keeps_library_contents(self):
        sid=self.db.save_source_series('Example','https://example.com/series/a')
        scanner=JavdbScanner(self.db);scanner.source_factory=Source;scanner.run(sid,True)
        self.assertTrue(self.db.delete_source_series(sid,'javdb'))
        self.assertEqual(self.db.list_movies()['total'],1)
        with self.db.connect() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM magnets').fetchone()[0],1)
            self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_cover_upload_is_local_and_protected_without_replacing_old_metadata(self):
        a=self.movie(cover_url='https://example.com/cover.jpg')
        png=b'\x89PNG\r\n\x1a\n'+b'fixture'
        item=save_cover(self.db,a,{'data':base64.b64encode(png).decode()})
        self.assertTrue(Path(item['cover_path']).is_file())
        self.db.add_or_update_movie('Example',cover_url='https://example.com/new.jpg',source='javdb',source_url='https://example.com/v/Example')
        item=self.db.get_movie(a)
        self.assertEqual(item['cover_url'],'https://example.com/cover.jpg')
        self.assertIn('cover_url',item['manual_fields'])
        with self.assertRaises(ValueError): save_cover(self.db,a,{'action':'refresh'})
        with self.assertRaises(ValueError): save_cover(self.db,a,{'data':base64.b64encode(b'<svg/>').decode()})
        self.db.update_movie(a,{'cover_url':'https://example.com/manual.jpg'})
        self.assertEqual(self.db.get_movie(a)['cover_path'],'')

    def test_exports_filter_selection_and_neutralize_spreadsheet_formulas(self):
        a=self.movie('=1+1',series='A');self.movie('Other',series='B')
        self.db.add_magnet(a,'magnet:?xt=urn:btih:'+'B'*40,'javdb','https://example.com/v/=1+1',123)
        rows=list(csv.reader(io.StringIO(export_movies(self.db,{'series':'A'},ids=[a]).decode('utf-8-sig'))))
        self.assertEqual(len(rows),2);self.assertEqual(rows[1][0],"'=1+1")
        text=export_movies(self.db,{},ids=[a],magnets=True).decode('utf-8-sig')
        self.assertIn('magnet:?xt',text);self.assertNotIn('Other',text)

    def test_scan_results_separate_new_movies_and_new_magnets_on_old_movies(self):
        sid=self.db.save_source_series('Example','https://example.com/series/a')
        scanner=JavdbScanner(self.db);scanner.source_factory=Source
        first=scanner.run(sid,True)
        self.assertEqual(first['new_movies'],1)
        run=self.db.scan_history()[0]['id']
        self.assertEqual(self.db.list_movies(run_id=str(run),update_kind='movies')['total'],1)
        self.assertEqual(self.db.list_movies(run_id=str(run),update_kind='magnets')['total'],1)
        second=JavdbScanner(self.db);second.source_factory=Source;second.run(sid,True)
        run=self.db.scan_history()[0]['id']
        self.assertEqual(self.db.list_movies(run_id=str(run),update_kind='movies')['total'],0)
        self.assertEqual(self.db.list_movies(run_id=str(run),update_kind='magnets')['total'],0)
        class ExtraSource(Source):
            def fetch_magnets(self,url): return [SourceMagnet('magnet:?xt=urn:btih:'+'B'*40,200)]
        third=JavdbScanner(self.db);third.source_factory=ExtraSource;third.run(sid,True)
        run=self.db.scan_history()[0]['id']
        self.assertEqual(self.db.list_movies(run_id=str(run),update_kind='movies')['total'],0)
        self.assertEqual(self.db.list_movies(run_id=str(run),update_kind='old_magnets')['total'],1)

    def test_retry_only_does_not_visit_listing_or_advance_full_scan_date(self):
        sid=self.db.save_source_series('Example','https://example.com/series/a')
        self.db.record_scan_failure('javdb',sid,'https://example.com/v/a',2,'database is locked')
        class RetrySource(Source):
            def scan_series(self,*args,**kwargs): raise AssertionError('不能访问列表')
        scanner=JavdbScanner(self.db);scanner.source_factory=RetrySource;scanner.retry_only=True
        result=scanner.run(sid)
        self.assertEqual(result['resolved_failures'],1);self.assertEqual(result['status'],'completed')
        row=self.db.get_source_series(sid,'javdb')
        self.assertEqual(row['last_completed_page'],0);self.assertEqual(row['last_scanned_at'],'')

    def test_busy_retry_does_not_double_count_or_recreate_magnets(self):
        sid=self.db.save_source_series('Example','https://example.com/series/a')
        original=self.db.add_magnet;calls=[]
        def busy(*args,**kwargs):
            calls.append(1)
            if len(calls)==1: raise sqlite3.OperationalError('database is locked')
            return original(*args,**kwargs)
        scanner=JavdbScanner(self.db);scanner.source_factory=Source
        with patch.object(self.db,'add_magnet',side_effect=busy): result=scanner.run(sid,True)
        self.assertEqual(result['new_movies'],1);self.assertEqual(result['new_magnets'],1)
        self.assertEqual(result['processed'],1);self.assertEqual(result['discovered'],1)

    def test_hidden_login_form_is_not_a_challenge_and_restricted_page_is_not_a_movie(self):
        checked_page('<title>Example | JavDB</title><div hidden><input type="password"></div>')
        with self.assertRaises(JavdbSessionError): checked_page('<title>Just a moment...</title>')
        with self.assertRaises(ValueError): checked_page('Due to copyright restrictions, this movie is not available in your country.')
        self.assertEqual(failure_kind('database is locked'),'数据库暂忙，可重试')

    def test_queue_is_serial_backs_up_and_preserves_excluded_series(self):
        ids=[self.db.save_source_series(name,'https://example.com/series/'+name) for name in ('a','b','excluded')]
        db=self.db;order=[]
        class Manager:
            def status(self): return {'running':False}
            def start(self,sid,full=False,retry_only=False):
                order.append(sid);scanner=JavdbScanner(db);scanner.source_factory=Source;scanner.retry_only=retry_only;scanner.run(sid,full)
            def stop(self,*args): pass
        queue=UpdateQueue(db,{'javdb':Manager()})
        queue.start(ids[:2]);queue.thread.join(10)
        status=queue.status()
        self.assertEqual(status['status'],'completed',status)
        self.assertEqual(order,ids[:2]);self.assertTrue(Path(status['backup_path'],'library.db').is_file())
        self.assertEqual(db.get_source_series(ids[2],'javdb')['last_scanned_at'],'')

    def test_fatal_session_error_stops_queue_and_resume_keeps_completed_items(self):
        ids=[self.db.save_source_series(name,'https://example.com/series/'+name) for name in ('a','b')]
        db=self.db;bad=[True];order=[]
        class BadSource(Source):
            def fetch_movie(self,url):
                if bad[0]: raise JavdbSessionError('需要人工验证')
                return super().fetch_movie(url)
        class Manager:
            def status(self): return {'running':False}
            def start(self,sid,full=False,retry_only=False):
                order.append(sid);scanner=JavdbScanner(db);scanner.source_factory=BadSource;scanner.run(sid,full)
            def stop(self,*args): pass
        queue=UpdateQueue(db,{'javdb':Manager()});queue.start(ids);queue.thread.join(10)
        self.assertEqual(queue.status()['status'],'needs_attention');self.assertEqual(order,[ids[0]])
        bad[0]=False;queue.start(resume=True);queue.thread.join(10)
        self.assertEqual(queue.status()['status'],'completed');self.assertEqual(order,[ids[0],*ids])

    def test_stopping_queue_does_not_start_next_series_and_can_resume(self):
        ids=[self.db.save_source_series(name,'https://example.com/series/'+name) for name in ('a','b')]
        db=self.db;entered=threading.Event();release=threading.Event();order=[]
        class SlowSource(Source):
            def fetch_movie(self,url):
                entered.set();release.wait(3);return super().fetch_movie(url)
        class Manager:
            thread=None
            scanner=None
            result={}
            def status(self): return {**self.result,'running':bool(self.thread and self.thread.is_alive())}
            def start(self,sid,full=False,retry_only=False):
                order.append(sid);self.scanner=JavdbScanner(db);self.scanner.source_factory=SlowSource;self.scanner.retry_only=retry_only
                def work(): self.result=self.scanner.run(sid,full)
                self.thread=threading.Thread(target=work);self.thread.start()
            def stop(self,*args):
                self.scanner.stop();release.set()
        queue=UpdateQueue(db,{'javdb':Manager()});queue.start(ids)
        self.assertTrue(entered.wait(5));queue.stop();queue.thread.join(10)
        self.assertEqual(order,[ids[0]]);self.assertEqual(queue.status()['status'],'stopped')
        queue.start(resume=True);queue.thread.join(10)
        self.assertEqual(queue.status()['status'],'completed');self.assertEqual(order,[ids[0],*ids])

    def test_schema_version_upgrades_to_5_idempotently(self):
        with self.db.connect() as conn:
            ver = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        self.assertEqual(ver, '5')
        reopened = LibraryDatabase(self.db.path)
        with reopened.connect() as conn:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            ver2 = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0]
        self.assertEqual(ver2, '5')


if __name__=='__main__': unittest.main()
