import unittest

from backend.sources.javdb import JavdbSource, size_bytes


LISTING = '''<a href="/v/a1">one</a><a href="/v/a2">two</a><a class="pagination-next" rel="next" href="/page/2">next</a>'''
LISTING_2 = '''<a href="/v/a3">three</a>'''
DETAIL = '''<html><head><title>ABC-001 Example | JavDB</title><meta property="og:image" content="/cover.jpg"></head><body>发行日期：2025/01/02 时长：120 <a href="/actors">推薦</a><a href="/actor/a">Alice</a><a href="/actor/b">Beth</a><a href="/studio/a">Studio</a><a href="magnet:?xt=urn:btih:AAA"><span class="meta">1.5 GB</span></a><a href="magnet:?xt=urn:btih:BBB">800 MB</a></body></html>'''


class Fake:
    def __init__(self):
        self.pages = {
            'https://x/series': LISTING,
            'https://x/page/2': LISTING_2,
            'https://x/v/a1': DETAIL,
        }

    def get(self, url, **kwargs):
        class R:
            def __init__(self, text):
                self.text = text
                self.encoding = 'utf8'

            def raise_for_status(self):
                pass
        return R(self.pages[url])


class JavdbTests(unittest.TestCase):
    def test_movie_and_magnets_share_one_cached_page_request(self):
        calls = []
        class Response:
            text = '<html><head><title>ABC-001 | JavDB</title></head><body><a href="magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA">1 GB</a></body></html>'
            def raise_for_status(self): pass
        class Session:
            def get(self, url, **_kwargs): calls.append(url); return Response()
        source = JavdbSource(session=Session(), delay=0)
        source.fetch_movie('https://x/v/1')
        source.fetch_magnets('https://x/v/1')
        self.assertEqual(calls, ['https://x/v/1'])
    def test_sizes(self):
        self.assertEqual(size_bytes('1.5 GB'), 1610612736)
        self.assertIsNone(size_bytes('unknown'))

    def test_listing_detail_and_resume_page(self):
        source = JavdbSource(Fake(), delay=0)
        page, urls = next(source.scan_series('https://x/series'))
        self.assertEqual((page, urls), (1, ['https://x/v/a1', 'https://x/v/a2']))
        # Resuming at page two must skip page one rather than relabel it as page two.
        page, urls = next(source.scan_series('https://x/series', start_page=2))
        self.assertEqual((page, urls), (2, ['https://x/v/a3']))
        movie = source.fetch_movie('https://x/v/a1')
        self.assertEqual(movie.title, 'ABC-001 Example')
        self.assertEqual(movie.release_date, '2025-01-02')
        self.assertEqual(movie.actresses, ['Alice', 'Beth'])
        magnets = source.fetch_magnets('https://x/v/a1')
        self.assertEqual(len(magnets), 2)
        self.assertEqual(magnets[0].size_bytes, 1610612736)


class MetadataFilterTests(unittest.TestCase):
    def test_navigation_text_is_not_stored_as_studio(self):
        import tempfile
        from pathlib import Path
        from backend.db import LibraryDatabase
        with tempfile.TemporaryDirectory() as directory:
            db = LibraryDatabase(Path(directory) / 'library.db')
            movie = db.add_or_update_movie('Clean', studio='首页', series='下一页', source='javdb', source_url='https://x/v/c')
            row = db.get_movie(movie)
            self.assertEqual(row['studio'], '')
            self.assertEqual(row['series'], '')

if __name__ == '__main__':
    unittest.main()
