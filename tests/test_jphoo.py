import unittest
from pathlib import Path
from backend.sources.jphoo import *
class JphooTests(unittest.TestCase):
 def test_title_classification(self):
  self.assertEqual(classify_magnet_candidate('Wifey 26.07.01 Happy Day','wifey.26.07.01.happy.day.1080p.mp4'),'current')
  self.assertEqual(classify_magnet_candidate('Wifey 26.07.01 Happy Day','wifey.26.07.01 Another Show 1080p'),'other')
  self.assertEqual(classify_magnet_candidate('Wifey 26.07.01 Happy Day','1080p mp4'),'unknown')
 def test_api_candidates(self):
  rows=api_candidates({'rows':[{'name':'Wifey Happy Day 1.5 GB','magnet':'magnet:?xt=urn:btih:A'},{'name':'Wifey Happy Day 2 GB','magnet':'magnet:?xt=urn:btih:A'},{'name':'Other 700 MB','magnet':'magnet:?xt=urn:btih:B'}]})
  self.assertEqual(len(rows),2); self.assertEqual(next(x for x in rows if x.magnet.endswith('A')).size_bytes,2147483648)
if __name__=='__main__':unittest.main()

class JphooListingTests(unittest.TestCase):
 def test_series_link_parser(self):
  from backend.sources.jphoo import series_links_from_html
  html=(Path(__file__).parent/'fixtures'/'jphoo_series.html').read_text(encoding='utf-8')
  self.assertEqual(series_links_from_html(html,'https://www.jphoo.net/series'),['https://www.jphoo.net/works/13259452493727751','https://www.jphoo.net/works/13259452493727752'])

class JphooPersistenceTests(unittest.TestCase):
 def test_candidates_are_strictly_partitioned_and_repeatable(self):
  import tempfile
  from pathlib import Path
  from backend.db import LibraryDatabase
  from backend.sources.jphoo import JphooCandidate, persist_candidates
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
   db=LibraryDatabase(Path(folder)/'library.db')
   movie=db.add_or_update_movie('ABP-123 Main Title',source='jphoo',source_url='https://www.jphoo.net/works/1')
   result=persist_candidates(db,movie,'ABP-123 Main Title','https://www.jphoo.net/works/1',[
    JphooCandidate('magnet:?xt=urn:btih:AAAA',2*1024**3,'ABP-123 Main Title 1080p'),
    JphooCandidate('magnet:?xt=urn:btih:BBBB',1024**3,'XYZ-999 Other Title 720p'),
    JphooCandidate('magnet:?xt=urn:btih:CCCC',None,'1080p mp4'),])
   self.assertEqual((result['matched_current'],result['attached_other'],result['unmatched']),(1,1,1))
   self.assertEqual(db.list_movies(page_size=20)['total'],2)
   again=persist_candidates(db,movie,'ABP-123 Main Title','https://www.jphoo.net/works/1',[JphooCandidate('magnet:?xt=urn:btih:AAAA',2*1024**3,'ABP-123 Main Title')])
   self.assertEqual(again['new_magnets'],0)




