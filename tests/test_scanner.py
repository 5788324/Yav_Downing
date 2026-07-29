import tempfile, unittest
from threading import Event
from pathlib import Path
from unittest.mock import patch
from backend.db import LibraryDatabase
from backend.scanner import JavdbScanner
from backend.sources.javdb import SourceMovie, SourceMagnet
class FakeSource:
 def scan_series(self,url,**kwargs): yield 1,['https://x/v/1']
 def fetch_movie(self,url): return SourceMovie('ABC-001',url,studio='Studio',series='Series',actresses=['Alice'])
 def fetch_magnets(self,url): return [SourceMagnet('magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',123)]
class ScannerTests(unittest.TestCase):
 def test_repeat_does_not_duplicate_and_manual_is_kept(self):
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); sid=db.save_source_series('Series','https://x/series')
   with patch('backend.scanner.JavdbSource',return_value=FakeSource()): JavdbScanner(db).run(sid,True)
   movie=db.list_movies(query='ABC-001')['items'][0]; db.update_movie(movie['id'],{'studio':'Manual'})
   with patch('backend.scanner.JavdbSource',return_value=FakeSource()): JavdbScanner(db).run(sid,True)
   with db.connect() as c:
    self.assertEqual(c.execute('select count(*) from movies').fetchone()[0],1); self.assertEqual(c.execute('select count(*) from source_entries').fetchone()[0],1); self.assertEqual(c.execute('select count(*) from magnets').fetchone()[0],1)
   self.assertEqual(db.get_movie(movie['id'])['studio'],'Manual')

 def test_unknown_size_is_filled_without_downgrading(self):
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); movie=db.add_or_update_movie('Size',source='javdb',source_url='https://x/v/size')
   db.add_magnet(movie,'magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB','javdb','https://x/v/size',None)
   db.add_magnet(movie,'magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB','javdb','https://x/v/size',200)
   db.add_magnet(movie,'magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB','javdb','https://x/v/size',100)
   self.assertEqual(db.get_movie(movie)['magnets'][0]['size_bytes'],200)

class DataProtectionTests(unittest.TestCase):
 def test_manual_actresses_are_not_appended_by_a_later_scan(self):
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); movie=db.add_or_update_movie('ABP-001',actresses=['Source A'],source='javdb',source_url='https://x/v/1')
   db.update_movie(movie,{'actresses':['Manual A']})
   db.add_or_update_movie('ABP-001',actresses=['Source A','Source B'],source='jphoo',source_url='https://x/v/1')
   self.assertEqual(db.get_movie(movie)['actresses'],['Manual A'])
 def test_disabled_series_cannot_run(self):
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); sid=db.save_source_series('Disabled','https://x/series',False)
   with self.assertRaisesRegex(ValueError,'已停用'): JavdbScanner(db).run(sid,True)
if __name__=='__main__': unittest.main()




class SeriesConfigTests(unittest.TestCase):
 def test_series_configuration_is_persistent(self):
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); sid=db.save_source_series('Small','https://x/series')
   item=db.list_source_series()[0]; self.assertEqual((item['id'],item['name'],item['enabled']),(sid,'Small',1))
   db.save_source_series('Renamed','https://x/new',False,sid)
   item=db.list_source_series()[0]; self.assertEqual((item['name'],item['url'],item['enabled']),('Renamed','https://x/new',0))

class ScanManagerTests(unittest.TestCase):
 def test_stop_forwards_signal(self):
  from backend.scanner import ScanManager
  with tempfile.TemporaryDirectory() as d:
   manager=ScanManager(LibraryDatabase(Path(d)/'library.db'))
   self.assertFalse(manager.status()['running']); self.assertEqual(manager.stop()['status'],'idle'); self.assertTrue(manager.shutdown(timeout=0.01))

class RecoveryTests(unittest.TestCase):
 def test_stale_running_scan_is_interrupted_on_open(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'library.db'; db=LibraryDatabase(path); sid=db.save_source_series('s','https://x/s')
   with db.connect() as c: c.execute("INSERT INTO scan_runs(series_id,status,started_at) VALUES(?,?,?)",(sid,'running','old'))
   reopened=LibraryDatabase(path)
   with reopened.connect() as c: self.assertEqual(c.execute('SELECT status FROM scan_runs').fetchone()[0],'interrupted')

class ResumeAndFailureQueueTests(unittest.TestCase):
 def test_stop_mid_page_keeps_page_for_resume(self):
  class Source:
   def __init__(self, stop_after_first=False): self.stop_after_first=stop_after_first; self.scanner=None; self.calls=0
   def scan_series(self,url,start_page=1,**kwargs):
    if start_page <= 1: yield 1,['https://x/v/1','https://x/v/2','https://x/v/3']
   def fetch_movie(self,url): return SourceMovie(url.rsplit('/',1)[-1],url)
   def fetch_magnets(self,url):
    self.calls += 1
    if self.stop_after_first and self.calls == 1: self.scanner.stop()
    return []
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); sid=db.save_source_series('Series','https://x/series')
   stopped=Source(True); scanner=JavdbScanner(db); stopped.scanner=scanner
   with patch('backend.scanner.JavdbSource',return_value=stopped): result=scanner.run(sid,True)
   self.assertEqual(result['status'],'stopped'); self.assertEqual(db.get_source_series(sid,'javdb')['last_completed_page'],0)
   with patch('backend.scanner.JavdbSource',return_value=Source()): resumed=JavdbScanner(db).run(sid,False)
   self.assertEqual(resumed['status'],'completed'); self.assertEqual(db.get_source_series(sid,'javdb')['last_completed_page'],1)
   with db.connect() as c: self.assertEqual(c.execute('select count(*) from source_entries').fetchone()[0],3)

 def test_unresolved_failure_is_retried_before_next_page(self):
  class FailingSource:
   def scan_series(self,url,start_page=1,**kwargs):
    if start_page <= 1: yield 1,['https://x/v/fail']
   def fetch_movie(self,url): raise ValueError('temporary parse error')
   def fetch_magnets(self,url): return []
  class RecoveredSource:
   def scan_series(self,url,start_page=1,**kwargs):
    if start_page <= 1: yield 1,['https://x/v/fail']
   def fetch_movie(self,url): return SourceMovie('RECOVER-001',url)
   def fetch_magnets(self,url): return []
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); sid=db.save_source_series('Series','https://x/series')
   with patch('backend.scanner.JavdbSource',return_value=FailingSource()): first=JavdbScanner(db).run(sid,True)
   self.assertEqual(first['failures'],1); self.assertEqual(len(db.list_unresolved_scan_failures('javdb',sid)),1)
   with patch('backend.scanner.JavdbSource',return_value=RecoveredSource()): retry=JavdbScanner(db).run(sid,False)
   self.assertEqual((retry['retried_failures'],retry['resolved_failures'],retry['failures']),(1,1,0))
   self.assertEqual(db.list_unresolved_scan_failures('javdb',sid),[])

class ManualFieldPrecisionTests(unittest.TestCase):
 def test_only_changed_duration_becomes_manual_and_empty_fields_remain_fillable(self):
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); movie=db.add_or_update_movie('MANUAL-001',actresses=['Source A'],source='javdb',source_url='https://x/v/1')
   db.update_movie(movie,{'title':'MANUAL-001','cover_url':'','studio':'','series':'','release_date':'','duration_minutes':120,'actresses':['Source A']})
   current=db.get_movie(movie)
   self.assertEqual(current['manual_fields'],['duration_minutes'])
   db.add_or_update_movie('MANUAL-001',studio='Source Studio',series='Source Series',cover_url='https://x/cover.jpg',actresses=['Source A','Source B'],source='jphoo',source_url='https://x/v/2')
   current=db.get_movie(movie)
   self.assertEqual((current['studio'],current['series'],current['cover_url']),('Source Studio','Source Series','https://x/cover.jpg'))
   self.assertEqual(set(current['actresses']),{'Source A','Source B'})
class ScanManagerSafetyTests(unittest.TestCase):
 def test_starting_manager_rejects_second_start_and_wrong_stop(self):
  from backend.scanner import ScanManager
  with tempfile.TemporaryDirectory() as d:
   db=LibraryDatabase(Path(d)/'library.db'); one=db.save_source_series('One','https://x/one'); two=db.save_source_series('Two','https://x/two')
   manager=ScanManager(db)
   class BlockingScanner:
    def __init__(self,_db): self.started=Event(); self.release=Event(); self.stop_event=Event()
    def run(self,*_args): self.started.set(); self.release.wait(2); return {'status':'completed'}
    def stop(self): self.stop_event.set(); self.release.set()
   scanner=BlockingScanner(db); manager.make_scanner=lambda: scanner
   manager.start(one)
   self.assertTrue(scanner.started.wait(1))
   with self.assertRaisesRegex(ValueError,'已有扫描'): manager.start(two)
   with self.assertRaisesRegex(ValueError,'不是当前'): manager.stop(two)
   manager.stop(one); self.assertTrue(manager.shutdown(1))