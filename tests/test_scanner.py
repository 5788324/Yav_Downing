import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from backend.db import LibraryDatabase
from backend.scanner import JavdbScanner
from backend.sources.javdb import SourceMovie, SourceMagnet
class FakeSource:
 def scan_series(self,url,**kwargs): yield 1,['https://x/v/1']
 def fetch_movie(self,url): return SourceMovie('ABC-001',url,studio='Studio',series='Series',actresses=['Alice'])
 def fetch_magnets(self,url): return [SourceMagnet('magnet:?xt=urn:btih:AAA',123)]
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
   db.add_magnet(movie,'magnet:?xt=urn:btih:SIZE','javdb','https://x/v/size',None)
   db.add_magnet(movie,'magnet:?xt=urn:btih:SIZE','javdb','https://x/v/size',200)
   db.add_magnet(movie,'magnet:?xt=urn:btih:SIZE','javdb','https://x/v/size',100)
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
