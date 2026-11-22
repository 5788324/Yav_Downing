import tempfile
import unittest
from pathlib import Path
from backend.db import LibraryDatabase
from backend.scan_avfan import AvfanScanner
from backend.sources.avfan import AvfanSessionError, AvfanSource, parse_movie, parse_magnets, checked_soup, candidate_matches

HTML = '''<title>RKPrime.26.11.01 Example | AVFan</title><h1>Example</h1>
<dl class="movie-info"><dt>发行日期</dt><dd>2026-11-01</dd><dt>片长</dt><dd>45 分钟</dd>
<dt>制作商</dt><dd>RealityKings</dd><dt>系列</dt><dd>RK Prime</dd>
<dt>演员</dt><dd><a class="female">Alice</a><a class="male">Bob</a></dd></dl>
<a href="https://c1.avfan.com/covers/a.jpg">封面</a>
<a href="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&amp;dn=RKPrime.26.11.01.Example"><span>2026-11-03 · 500MB</span></a>'''


class AvfanTests(unittest.TestCase):
    def test_wrong_year_candidate_is_rejected(self):
        movie = parse_movie(HTML, 'https://avfan.com/zh-CN/movies/a')
        self.assertTrue(candidate_matches(movie, 'RKPrime.26.11.01.Example'))
        self.assertFalse(candidate_matches(movie, 'RKPrime.19.11.01.Example'))
        self.assertFalse(candidate_matches(movie, '[RKPrime] Other Title [10.26.19]'))
        self.assertFalse(candidate_matches(movie, ''))
    def test_metadata_and_magnets(self):
        movie = parse_movie(HTML, 'https://avfan.com/zh-CN/movies/a')
        self.assertEqual((movie.studio, movie.series, movie.release_date, movie.duration_minutes, movie.actresses), ('RealityKings', 'RK Prime', '2026-11-01', 45, ['Alice']))
        self.assertEqual(parse_magnets(HTML)[0].size_bytes, 500*1024**2)
        self.assertEqual(len(parse_magnets(HTML+HTML)), 1)
        with self.assertRaises(AvfanSessionError): parse_movie('<html/>', 'https://avfan.com/')
        with self.assertRaises(RuntimeError): checked_soup('<title>Just a moment...</title>')

    def test_pagination_and_idempotent_scan(self):
        listing = '<h2>RK Prime</h2><a href="/zh-CN/movies/a">A</a>'
        def loader(url):
            if '/movies/' in url: return HTML
            return listing + ('<a href="?page=2">Next</a>' if 'page=1' in url else '')
        source = AvfanSource(loader=loader, delay=0)
        self.assertEqual([p for p,_ in source.scan_series('https://avfan.com/zh-CN/series/a')], [1,2])
        with tempfile.TemporaryDirectory() as temp:
            db = LibraryDatabase(Path(temp)/'test.db')
            sid = db.save_source_series('RK Prime','https://avfan.com/zh-CN/series/a',source='avfan')
            scanner = AvfanScanner(db); scanner.source_factory = lambda: AvfanSource(loader=loader, delay=0)
            first = scanner.run(sid, True); second = scanner.run(sid, True)
            self.assertEqual(first['new_magnets'], 1)
            self.assertEqual(second['new_magnets'], 0)
            self.assertEqual(second['failures'], 0)
            with db.connect() as c:
                self.assertEqual(c.execute('select count(*) from movies').fetchone()[0], 1)
                self.assertEqual(c.execute('pragma integrity_check').fetchone()[0], 'ok')

    def test_session_failure_stops_before_next_movie_and_keeps_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LibraryDatabase(Path(temp)/'test.db')
            sid = db.save_source_series('Test','https://avfan.com/zh-CN/series/a',source='avfan')
            calls = []
            def load(url):
                calls.append(url)
                if '/movies/' in url: return '<title>Just a moment...</title>'
                return '<h1>Test</h1><a href="/movies/a">A</a><a href="/movies/b">B</a>'
            scanner = AvfanScanner(db)
            scanner.source_factory = lambda: AvfanSource(loader=load, delay=0)
            result = scanner.run(sid)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(len(calls), 2)
            self.assertEqual(db.get_source_series(sid, 'avfan')['last_completed_page'], 0)

    def test_fatal_retry_keeps_failure_queue_and_does_not_fetch_listing(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LibraryDatabase(Path(temp)/'test.db')
            sid = db.save_source_series('Test','https://avfan.com/zh-CN/series/a',source='avfan')
            for name in ('a','b'):
                db.record_scan_failure('avfan',sid,'https://avfan.com/movies/'+name,2,'old')
            calls = []
            def load(url):
                calls.append(url)
                raise AvfanSessionError('closed')
            scanner = AvfanScanner(db)
            scanner.source_factory = lambda: AvfanSource(loader=load, delay=0)
            self.assertEqual(scanner.run(sid)['status'], 'failed')
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(db.list_unresolved_scan_failures('avfan',sid)), 2)
