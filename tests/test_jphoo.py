import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.db import LibraryDatabase
from backend.scanner import JphooScanner
from backend.sources.javdb import SourceMovie
from backend.sources.jphoo import (
    JphooCandidate, JphooSource, LoginRequired, api_candidates,
    classify_magnet_candidate, parse_movie_html, persist_candidates,
    series_links_from_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


class JphooParserTests(unittest.TestCase):
    def test_series_links_are_deduplicated(self):
        html = (FIXTURES / "jphoo_series.html").read_text(encoding="utf-8")
        self.assertEqual(series_links_from_html(html, "https://www.jphoo.net/series"), ["https://www.jphoo.net/works/13259452493727751", "https://www.jphoo.net/works/13259452493727752"])

    def test_movie_metadata(self):
        movie = parse_movie_html((FIXTURES / "jphoo_movie.html").read_text(encoding="utf-8"), "https://www.jphoo.net/works/1")
        self.assertEqual(movie.title, "ABP-123 Example Movie")
        self.assertEqual((movie.studio, movie.series, movie.release_date, movie.duration_minutes), ("Studio One", "Series One", "2025-01-02", 120))
        self.assertEqual(movie.actresses, ["Alice", "Beth"])
        self.assertEqual(movie.cover_url, "https://www.jphoo.net/covers/abp.jpg")

    def test_initial_state_fills_metadata_missing_from_visible_html(self):
        state = {"works": {"worksData": {
            "data": {"pubTime": "2026-08-13", "duration": "0", "picBig": "https://img.example/cover.webp"},
            "maker": [{"name": "Brazzers"}],
            "series": [{"name": "Brazzers Exxtra"}],
            "performer": [{"name": "Nina White"}, {"name": "Alexa Chains"}],
        }}}
        html = f'<html><head><title>Hookah Hook Up - JPHOO</title><script>window.__INITIAL_STATE__={json.dumps(state)};document.currentScript.remove()</script></head><body><a href="/performer/a">查看Nina White全部作品</a></body></html>'
        movie = parse_movie_html(html, "https://www.jphoo.net/works/1")
        self.assertEqual((movie.studio, movie.series, movie.release_date), ("Brazzers", "Brazzers Exxtra", "2026-08-13"))
        self.assertEqual(movie.actresses, ["Nina White", "Alexa Chains"])
        self.assertEqual(movie.cover_url, "https://img.example/cover.webp")
        self.assertIsNone(movie.duration_minutes)
        live_dom = parse_movie_html("<html><head><title>Hookah Hook Up - JPHOO</title></head></html>", "https://www.jphoo.net/works/1", state["works"]["worksData"])
        self.assertEqual((live_dom.studio, live_dom.release_date, live_dom.actresses), ("Brazzers", "2026-08-13", ["Nina White", "Alexa Chains"]))
    def test_qitem_metadata_ignores_navigation_and_zero_duration_is_unknown(self):
        html = """<html><head><title>XYZ-001 Test - JPHOO</title></head><body><nav><a href="/tag/all">tag 番号分类</a><a href="/publisher/all">厂商大全</a></nav><div class="q-item__label">时长：0分钟</div><div class="q-item__label">系列：<a href="/series/x">Series One</a></div><div class="q-item__label">演员：<a href="/performer/a">Alice</a><span>、</span><a href="/performer/b">Bob</a></div></body></html>"""
        movie = parse_movie_html(html, "https://www.jphoo.net/works/xyz")
        self.assertIsNone(movie.duration_minutes)
        self.assertEqual(movie.series, "Series One")
        self.assertEqual(movie.studio, "")
        self.assertEqual(movie.actresses, ["Alice", "Bob"])

    def test_api_candidates_keep_all_btih_and_best_size(self):
        payload = {"rows": [{"name": "ABP-123 1.5 GB", "magnet": "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}, {"name": "ABP-123 2 GB", "magnet": "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}, {"name": "XYZ-999 700 MB", "magnet": "magnet:?xt=urn:btih:BBB"}]}
        rows = api_candidates(payload)
        self.assertEqual(len(rows), 2)
        self.assertEqual(next(row for row in rows if row.magnet.endswith("AAA")).size_bytes, 2 * 1024**3)
        hash_rows = api_candidates({"rows": [{"infoHash": "A" * 40, "name": "ABP-123 Test", "length": "3 GB"}]})
        self.assertEqual((len(hash_rows), hash_rows[0].magnet.startswith("magnet:?xt=urn:btih:"), hash_rows[0].size_bytes), (1, True, 3 * 1024**3))

    def test_title_classification_is_conservative(self):
        self.assertEqual(classify_magnet_candidate("Wifey 26.07.01 Happy Day", "wifey_26.07.01.happy-day.1080p.mp4"), "current")
        self.assertEqual(classify_magnet_candidate("Wifey 26.07.01 Happy Day", "XYZ-999 Another Show 1080p"), "other")
        self.assertEqual(classify_magnet_candidate("Wifey 26.07.01 Happy Day", "1080p MP4 2 GB"), "unknown")

    def test_date_style_numbers_do_not_merge_other_western_movies(self):
        current = "BrazzersExxtra.26.08.07 Journalistic Carnality BrazzersExxtra.26.08.07"
        self.assertEqual(classify_magnet_candidate(current, "BrazzersExxtra.26.08.07.Octavia.Red.Journalistic.Carnality.1080p"), "current")
        self.assertEqual(classify_magnet_candidate(current, "BrazzersExxtra.26.08.07.Getting.Off.On.Myself.1080p"), "unknown")
        self.assertEqual(classify_magnet_candidate(current, "BrazzersExxtra.26.07.07.Cheeky.Anal.Stress.Buster.1080p"), "unknown")

class JphooAuthenticatedApiTests(unittest.TestCase):
    class Page:
        url = "https://www.jphoo.net/works/13401596825310214"
        def evaluate(self, _script):
            return {"id": "13401596825310214", "number": "BrazzersExxtra.26.08.13", "modId": 3}

    def test_query_matches_public_frontend_contract(self):
        query = JphooSource._magnet_query(self.Page())
        self.assertEqual(query, {
            "pageNum": 1, "pageSize": 12,
            "dataId": "13401596825310214",
            "keyword": "BrazzersExxtra.26.08.13",
            "modId": 3, "order": "dht", "date": 0,
            "sort": "", "category": "video",
        })

    def test_authenticated_context_reuses_headers_without_persisting_cookie(self):
        class CapturedRequest:
            url = "https://www.jphoo.net/prod-api/v2/dht/list"
            def all_headers(self):
                return {"authorization": "Bearer memory-only", "cookie": "secret", "content-length": "0"}
        calls = []
        class ApiRequest:
            def get(self, url, **kwargs):
                calls.append((url, kwargs))
                return SimpleNamespace(ok=True, json=lambda: {"code": 200, "rows": [{
                    "infoHash": "A" * 40,
                    "name": "BrazzersExxtra.26.08.13 2 GB",
                    "length": str(2 * 1024**3),
                }]})
        source = JphooSource(browser=SimpleNamespace(context=SimpleNamespace(request=ApiRequest())))
        source._remember_magnet_request(CapturedRequest())
        self.assertNotIn("cookie", source._magnet_api_headers)
        rows = source._api_candidates_from_context(self.Page())
        self.assertEqual((len(rows), rows[0].size_bytes), (1, 2 * 1024**3))
        self.assertEqual(calls[0][0], "https://www.jphoo.net/prod-api/v2/dht/list")
        self.assertEqual(calls[0][1]["params"]["dataId"], "13401596825310214")
        self.assertEqual(calls[0][1]["headers"]["authorization"], "Bearer memory-only")

    def test_rejected_api_clears_headers_and_requests_modal_fallback(self):
        class ApiRequest:
            def get(self, *_args, **_kwargs):
                return SimpleNamespace(ok=True, json=lambda: {"code": 401, "msg": "login required"})
        source = JphooSource(browser=SimpleNamespace(context=SimpleNamespace(request=ApiRequest())))
        source._magnet_api_headers = {"authorization": "expired"}
        self.assertIsNone(source._api_candidates_from_context(self.Page()))
        self.assertIsNone(source._magnet_api_headers)

class JphooPersistenceTests(unittest.TestCase):
    def make_db(self):
        folder = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        return folder, LibraryDatabase(Path(folder.name) / "library.db")

    def test_candidates_partition_and_repeat_without_duplicates(self):
        folder, db = self.make_db()
        with folder:
            movie = db.add_or_update_movie("ABP-123 Main Title", source="jphoo", source_url="https://www.jphoo.net/works/1")
            result = persist_candidates(db, movie, "ABP-123 Main Title", "https://www.jphoo.net/works/1", [
                JphooCandidate("magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 2 * 1024**3, "ABP-123 Main Title 1080p"),
                JphooCandidate("magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", 1024**3, "XYZ-999 Other Title 720p"),
                JphooCandidate("magnet:?xt=urn:btih:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", None, "1080p mp4"),
            ])
            self.assertEqual((result["matched_current"], result["attached_other"], result["unmatched"]), (1, 1, 1))
            self.assertEqual(db.list_movies(page_size=20)["total"], 2)
            again = persist_candidates(db, movie, "ABP-123 Main Title", "https://www.jphoo.net/works/1", [JphooCandidate("magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 2 * 1024**3, "ABP-123 Main Title")])
            self.assertEqual(again["new_magnets"], 0)

    def test_javdb_btih_gets_jphoo_source_association(self):
        folder, db = self.make_db()
        with folder:
            movie = db.add_or_update_movie("ABP-123 Main", source="javdb", source_url="https://javdb.com/v/a")
            db.add_magnet(movie, "magnet:?xt=urn:btih:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", "javdb", "https://javdb.com/v/a", None)
            db.add_or_update_movie("ABP-123 Main", source="jphoo", source_url="https://www.jphoo.net/works/1")
            persist_candidates(db, movie, "ABP-123 Main", "https://www.jphoo.net/works/1", [JphooCandidate("magnet:?xt=urn:btih:CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", 100, "ABP-123 Main")])
            detail = db.get_movie(movie)
            self.assertEqual(len(detail["magnets"]), 1)
            self.assertEqual({item["source"] for item in detail["magnets"][0]["sources"]}, {"javdb", "jphoo"})
            self.assertEqual(detail["magnets"][0]["size_bytes"], 100)

    def test_manual_fields_and_valid_size_are_preserved(self):
        folder, db = self.make_db()
        with folder:
            movie = db.add_or_update_movie("ABP-123", studio="Old", source="jphoo", source_url="https://www.jphoo.net/works/1")
            db.update_movie(movie, {"studio": "Manual"})
            db.add_or_update_movie("ABP-123", studio="New", source="jphoo", source_url="https://www.jphoo.net/works/1")
            self.assertEqual(db.get_movie(movie)["studio"], "Manual")


class JphooScanTests(unittest.TestCase):
    def test_login_required_is_reported_without_counting_hundreds_of_failures(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            db = LibraryDatabase(Path(folder) / "library.db")
            sid = db.save_source_series("Small", "https://www.jphoo.net/series", source="jphoo")
            class Source:
                def open_browser(self, _): pass
                def close(self): pass
                def scan_series(self, *_args, **_kwargs): raise LoginRequired("JPHOO 需要重新登录")
            with patch("backend.sources.jphoo.JphooSource", return_value=Source()):
                result = JphooScanner(db, Path(folder) / "profile").run(sid, True)
            self.assertEqual((result["status"], result["failures"]), ("login_required", 0))

    def test_fetch_movie_uses_raw_response_after_initial_script_is_removed(self):
        state = {"works": {"worksData": {
            "data": {"pubTime": "2026-08-13", "duration": "0", "picBig": "https://img.example/cover.webp"},
            "maker": [{"name": "Brazzers"}], "series": [{"name": "Brazzers Exxtra"}],
            "performer": [{"name": "Nina White"}],
        }}}
        raw = f'<html><head><title>Hookah Hook Up - JPHOO</title><script>window.__INITIAL_STATE__={json.dumps(state)};document.currentScript.remove()</script></head></html>'
        class Page:
            def goto(self, *_args, **_kwargs): return SimpleNamespace(text=lambda: raw)
            def wait_for_timeout(self, _milliseconds): pass
            def evaluate(self, _script): return None
            def content(self): return '<html><head><title>Hookah Hook Up - JPHOO</title></head></html>'
        browser = SimpleNamespace(page=Page(), login_required=lambda: False)
        movie = JphooSource(browser=browser).fetch_movie("https://www.jphoo.net/works/1")
        self.assertEqual((movie.studio, movie.release_date, movie.actresses), ("Brazzers", "2026-08-13", ["Nina White"]))
    def test_http_listing_is_used_before_browser(self):
        source = JphooSource(delay=0)
        with patch.object(source, "_http_links", return_value=["https://www.jphoo.net/works/1"]):
            page, links = next(source.scan_series("https://www.jphoo.net/series"))
        self.assertEqual((page, links), (1, ["https://www.jphoo.net/works/1"]))


    def test_authenticated_listing_uses_page_fetch_without_navigation(self):
        html = '<a href="/works/1">one</a><a href="/works/1">duplicate</a>'
        calls = []
        class Page:
            def evaluate(self, script, url):
                calls.append((script, url))
                return {"ok": True, "url": url, "html": html}
        browser = SimpleNamespace(context=object(), page=Page())
        source = JphooSource(browser=browser, delay=0)
        page, links = next(source.scan_series("https://www.jphoo.net/series", start_page=2))
        self.assertEqual((page, links), (2, ["https://www.jphoo.net/works/1"]))
        self.assertEqual(calls[0][1], "https://www.jphoo.net/series?pageNum=2")
    def test_authenticated_listing_reports_login_html(self):
        class Page:
            def evaluate(self, _script, _url):
                return {"ok": True, "url": "https://www.jphoo.net/login", "html": '<form><input type="password"></form>'}
        source = JphooSource(browser=SimpleNamespace(context=object(), page=Page()), delay=0)
        with self.assertRaises(LoginRequired):
            next(source.scan_series("https://www.jphoo.net/series"))

if __name__ == "__main__":
    unittest.main()

