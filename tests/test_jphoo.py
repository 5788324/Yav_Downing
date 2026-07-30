import json
import tempfile
import unittest
from pathlib import Path
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

    def test_http_listing_is_used_before_browser(self):
        source = JphooSource(delay=0)
        with patch.object(source, "_http_links", return_value=["https://www.jphoo.net/works/1"]):
            page, links = next(source.scan_series("https://www.jphoo.net/series"))
        self.assertEqual((page, links), (1, ["https://www.jphoo.net/works/1"]))


if __name__ == "__main__":
    unittest.main()

