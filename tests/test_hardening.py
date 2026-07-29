import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.app import Handler
from backend.db import LibraryDatabase
from backend.scanner import ScanManager
from backend.sources.jphoo import api_candidates, classify_magnet_candidate


class BtihNormalizationTests(unittest.TestCase):
    def test_hex_and_base32_normalize_to_one_infohash_and_invalid_is_rejected(self):
        from backend.db import extract_btih
        import base64
        hex_hash = "0123456789ABCDEF0123456789ABCDEF01234567"
        base32_hash = base64.b32encode(bytes.fromhex(hex_hash)).decode("ascii")
        self.assertEqual(extract_btih(f"magnet:?xt=urn:btih:{hex_hash.lower()}"), hex_hash)
        self.assertEqual(extract_btih(f"magnet:?xt=urn:btih:{base32_hash}"), hex_hash)
        for value in ("123", "INVALIDHASH", "A" * 39, "A" * 33):
            with self.assertRaises(ValueError):
                extract_btih(f"magnet:?xt=urn:btih:{value}")
class HardeningDataTests(unittest.TestCase):
    def test_metadata_and_magnet_result_rules(self):
        with tempfile.TemporaryDirectory() as folder:
            db = LibraryDatabase(Path(folder) / "library.db")
            movie = db.add_or_update_movie("ABP-001", studio="首页", actresses=["A"], source="javdb", source_url="https://x/j")
            db.add_or_update_movie("ABP-001", studio="Valid Studio", actresses=["B"], source="jphoo", source_url="https://x/p")
            self.assertEqual(db.get_movie(movie)["studio"], "Valid Studio")
            self.assertEqual(set(db.get_movie(movie)["actresses"]), {"A", "B"})
            db.update_movie(movie, {"studio": "Manual Studio", "actresses": ["C"]})
            db.add_or_update_movie("ABP-001", studio="Other Studio", actresses=["A", "D"], source="javdb", source_url="https://x/j")
            self.assertEqual(db.get_movie(movie)["studio"], "Manual Studio")
            self.assertEqual(db.get_movie(movie)["actresses"], ["C"])
            one = db.add_magnet(movie, "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "javdb", "https://x/j", None)
            two = db.add_magnet(movie, "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "jphoo", "https://x/p", 200)
            three = db.add_magnet(movie, "magnet:?xt=urn:btih:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "jphoo", "https://x/p", None)
            self.assertEqual((one.created, one.source_added, one.size_updated), (True, True, False))
            self.assertEqual((two.created, two.source_added, two.size_updated), (False, True, True))
            self.assertEqual((three.created, three.source_added, three.size_updated), (False, False, False))

    def test_jphoo_candidate_uses_explicit_title_only(self):
        rows = api_candidates({"rows": [{"infoHash": "A" * 40, "name": "ABP-123 Clear Name", "length": "2 GB", "status": "ready"}, {"infoHash": "B" * 40, "length": "3 GB", "id": "999"}]})
        self.assertEqual(rows[0].title, "ABP-123 Clear Name")
        self.assertEqual(rows[1].title, "")
        self.assertEqual(classify_magnet_candidate("ABP-123 Clear Name", rows[1].title), "unknown")
        self.assertEqual(classify_magnet_candidate("ABP-123 Clear Name", "Clear 1080p"), "unknown")
        self.assertEqual(classify_magnet_candidate("ABP-123 Clear Name", "ABP-123 Another Name"), "current")


class ShutdownFrontendTests(unittest.TestCase):
    def test_shutdown_ui_contract(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "backend" / "static" / "index.html").read_text(encoding="utf-8")
        script = (root / "backend" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="shutdownApp"', html)
        self.assertIn('aria-label="安全退出 Yav"', html)
        self.assertIn("/api/app/shutdown", script)
        self.assertIn("method: 'POST'", script)
        self.assertIn("JSON.stringify", script)
        self.assertIn("confirm(", script)
        self.assertIn("button.disabled = true", script)
        self.assertIn("waitForYavShutdown", script)
        self.assertIn("/api/app/status", script)
        self.assertIn("return true; // 本地服务已断开", script)
        self.assertNotIn("shutdownToken=", script)

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = LibraryDatabase(Path(self.folder.name) / "library.db")
        self.movie = self.db.add_or_update_movie("API-001", source="javdb", source_url="https://x/movie")
        Handler.database = self.db
        Handler.scans = ScanManager(self.db)
        Handler.jphoo_scans = ScanManager(self.db)
        Handler.jphoo_scans.source_name = "jphoo"
        Handler.jphoo_login = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.folder.cleanup()

    def request(self, method, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(self.base + path, data=body, method=method, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    def test_source_edit_delete_and_favorite_validation(self):
        status, javdb = self.request("POST", "/api/sources/javdb", {"name":"J","url":"https://x/j","enabled":True,"scan_status":"bad"})
        self.assertEqual(status, 201)
        self.assertEqual(self.request("POST", "/api/sources/javdb", {"name":"J-copy","url":"https://x/j","enabled":True})[0], 409)
        other = self.request("POST", "/api/sources/javdb", {"name":"Other","url":"https://x/other","enabled":True})[1]
        Handler.scans.series_id = javdb["id"]
        self.assertEqual(self.request("POST", f'/api/sources/javdb/{other["id"]}/stop', {})[0], 409)
        Handler.scans.is_running_series = lambda series_id: int(series_id) == javdb["id"]
        self.assertEqual(self.request("POST", "/api/sources/javdb", {"series_id":javdb["id"],"name":"Blocked","url":"https://x/blocked","enabled":False})[0], 409)
        Handler.scans.is_running_series = lambda _series_id: False
        status, _ = self.request("POST", "/api/sources/javdb", {"series_id":javdb["id"],"name":"J2","url":"https://x/j2","enabled":False,"new_magnets":99})
        self.assertEqual(status, 201)
        self.assertEqual(self.db.get_source_series(javdb["id"], "javdb")["name"], "J2")
        status, jphoo = self.request("POST", "/api/sources/jphoo", {"name":"P","url":"https://x/p","enabled":True,"profile_dir":"C:/tmp/p"})
        self.assertEqual(status, 201)
        self.assertEqual(self.db.get_source_series(jphoo["id"], "jphoo")["profile_dir"], "C:/tmp/p")
        self.assertEqual(self.request("DELETE", f"/api/sources/javdb/{jphoo['id']}")[0], 404)
        self.assertEqual(self.request("DELETE", f"/api/sources/jphoo/{jphoo['id']}")[0], 200)
        self.assertEqual(self.request("POST", f"/api/movies/{self.movie}/favorite", {"favorite":True})[0], 200)
        self.assertEqual(self.request("POST", f"/api/movies/{self.movie}/favorite", {"favorite":False})[0], 200)
        for value in ("false", 0, None):
            self.assertEqual(self.request("POST", f"/api/movies/{self.movie}/favorite", {"favorite":value})[0], 400)

    def test_edit_validation_and_active_delete_and_status(self):
        status, config = self.request("POST", "/api/sources/javdb", {"name":"J","url":"https://x/j","enabled":True})
        self.assertEqual(status, 201)
        with self.db.connect() as db:
            db.execute("INSERT INTO scan_runs(series_id,status,current_page,discovered,processed_count,new_movies,new_magnets,failures,started_at) VALUES(?,?,?,?,?,?,?,?,?)", (config["id"], "running", 2, 4, 3, 1, 2, 0, self.db.now()))
        status, scan = self.request("GET", "/api/sources/javdb/scan")
        self.assertEqual(status, 200)
        self.assertEqual((scan["series_id"], scan["current_page"], scan["discovered"], scan["new_magnets"]), (config["id"], 2, 4, 2))
        self.assertEqual(self.request("DELETE", f"/api/sources/javdb/{config['id']}")[0], 409)
        for payload in ({"release_date":"not-a-date"}, {"duration_minutes":1441}, {"cover_url":"ftp://bad"}, {"title":""}):
            self.assertEqual(self.request("PATCH", f"/api/movies/{self.movie}", payload)[0], 400)


class FrontendStaticTests(unittest.TestCase):
    def test_source_panel_safety_contracts(self):
        app = (Path(__file__).parents[1] / "backend" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("sourceRefreshInFlight", app)
        self.assertIn("sourceStatusFailures", app)
        self.assertIn("连续失败，显示的进度可能已过期", app)
        self.assertIn("Promise.allSettled", app)
        self.assertIn("ensureSourcePolling", app)
        self.assertIn("将从第一页重新扫描该系列", app)
        self.assertIn("request(`/api/sources/${source}/${id}/${action}`", app)
        self.assertIn("window.confirm", app)
        self.assertIn("if (!$(\x27#sourceOverlay\x27).hidden) closeSources()", app)
        self.assertIn("aria-current", app)
        self.assertNotIn("JSON.stringify({...item", app)


    def test_scan_refresh_contract(self):
        root = Path(__file__).parents[1]
        app = (root / "backend" / "static" / "app.js").read_text(encoding="utf-8")
        html = (root / "backend" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("const sourceScanStates = { javdb: false, jphoo: false };", app)
        self.assertIn("reconcileScanStates(sourceScanStates, scans)", app)
        self.assertIn("transition.stoppedSources.length", app)
        self.assertIn("Promise.all([loadFilters(), loadMovies()])", app)
        self.assertIn('type="module" src="/assets/app.js"', html)

if __name__ == "__main__":
    unittest.main()
