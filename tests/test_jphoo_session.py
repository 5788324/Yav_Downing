import tempfile
import time
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from backend.db import LibraryDatabase
from backend.scanner import JphooSessionManager
from backend.sources.jphoo import authentication_state


class FakePage:
    def __init__(self):
        self.urls = []
    def goto(self, url, **_kwargs):
        self.urls.append(url)


class FakeBrowser:
    instances = []
    def __init__(self, profile_dir):
        self.profile_dir = str(profile_dir)
        self.page = FakePage()
        self.opened = False
        self.closed = False
        type(self).instances.append(self)
    def open(self):
        self.opened = True
        return self.page
    def is_open(self):
        return self.opened and not self.closed
    def close(self):
        self.closed = True
    def diagnose(self, target_url):
        return {"profile_dir": self.profile_dir, "target_url": target_url, "target_origin": "https://mirror.example", "current_url": target_url, "password_visible": 0, "password_hidden": 1, "cookie_count": 2, "domain_cookie_count": 1, "local_storage_keys": 1, "session_storage_keys": 0, "protected_auth_marker": True, "signals": ["protected_auth_marker_present"], "login": "ready", "session_state": "open"}


class BlockingScanner:
    started = Event()
    instances = []
    def __init__(self, _database, _profile_dir, source=None):
        self.source = source
        self.stop_requested = Event()
        type(self).instances.append(self)
    def stop(self):
        self.stop_requested.set()
    def run(self, _series_id, _from_start=False):
        type(self).started.set()
        self.stop_requested.wait(2)
        return {"status": "stopped", "page": 1, "message": "", "discovered": 0, "processed": 0, "new_movies": 0, "new_magnets": 0, "failures": 0, "matched_current": 0, "attached_other_movies": 0, "unmatched_candidates": 0}


class ImmediateScanner:
    def __init__(self, _database, _profile_dir, source=None):
        self.source = source
    def stop(self):
        pass
    def run(self, _series_id, _from_start=False):
        return {"status": "stopped", "page": 1, "message": "", "discovered": 0, "processed": 0, "new_movies": 0, "new_magnets": 0, "failures": 0}

def wait_for(manager, predicate):
    deadline = time.time() + 3
    while time.time() < deadline:
        state = manager.status()
        if predicate(state):
            return state
        time.sleep(0.01)
    raise AssertionError(manager.status())


class JphooSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = LibraryDatabase(Path(self.temp.name) / "library.db")
        self.series_id = self.db.save_source_series("真实镜像", "https://mirror.example/series/one", source="jphoo", profile_dir="C:/legacy/profile")
        FakeBrowser.instances.clear()
        BlockingScanner.instances.clear()
        BlockingScanner.started.clear()
        self.manager = JphooSessionManager(self.db, Path(self.temp.name) / "app-profile", browser_factory=FakeBrowser)

    def tearDown(self):
        self.manager.shutdown()
        self.temp.cleanup()

    def ready_session(self):
        self.manager.open(self.series_id)
        wait_for(self.manager, lambda state: state["status"] == "ready")

    def test_authentication_state_requires_protected_marker(self):
        self.assertEqual(authentication_state("https://mirror.example/work/1", 0, 0, 0, 0)[0], "unknown")
        self.assertEqual(authentication_state("https://mirror.example/work/1", 1, 1, 0, 0)[0], "login_required")
        self.assertEqual(authentication_state("https://mirror.example/login", 0, 1, 0, 0, True)[0], "login_required")
        self.assertEqual(authentication_state("https://mirror.example/work/1", 0, 1, 1, 0)[0], "unknown")
        self.assertEqual(authentication_state("https://mirror.example/work/1", 0, 1, 1, 0, True)[0], "ready")

    def test_legacy_profile_is_preserved_when_series_is_edited(self):
        self.db.save_source_series("重命名", "https://mirror.example/series/two", True, self.series_id, source="jphoo")
        self.assertEqual(self.db.get_source_series(self.series_id, "jphoo")["profile_dir"], "C:/legacy/profile")

    def test_open_and_check_reuse_one_application_profile_and_series_origin(self):
        self.ready_session()
        self.manager.check()
        state = wait_for(self.manager, lambda state: state.get("last_verified_at"))
        self.assertEqual(len(FakeBrowser.instances), 1)
        self.assertEqual(FakeBrowser.instances[0].profile_dir, str((Path(self.temp.name) / "app-profile").resolve()))
        self.assertEqual(FakeBrowser.instances[0].page.urls, ["https://mirror.example/series/one", "https://mirror.example/series/one"])
        self.assertEqual(state["target_origin"], "https://mirror.example")
        self.assertNotEqual(FakeBrowser.instances[0].profile_dir, "C:/legacy/profile")

    def test_close_never_claims_ready_and_probe_detects_manual_close(self):
        self.ready_session()
        FakeBrowser.instances[0].closed = True
        state = wait_for(self.manager, lambda state: state["status"] == "closed")
        self.assertEqual(state["login"], "unknown")
        self.manager.open(self.series_id)
        wait_for(self.manager, lambda state: state["status"] == "ready")
        self.manager.close()
        state = wait_for(self.manager, lambda state: state["status"] == "closed")
        self.assertEqual(state["login"], "unknown")

    def start_blocking_scan(self):
        self.ready_session()
        with self.db.connect() as db:
            db.execute("INSERT INTO scan_runs(series_id,status,started_at) VALUES(?,?,?)", (self.series_id, "running", self.db.now()))
        self.patcher = patch("backend.scanner.JphooScanner", BlockingScanner)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.manager.start(self.series_id)
        self.assertTrue(BlockingScanner.started.wait(1), "扫描器没有启动")

    def test_start_reserves_starting_state_before_worker_creates_scanner(self):
        self.ready_session()
        with patch("backend.scanner.JphooScanner", BlockingScanner):
            self.manager.start(self.series_id)
            with self.assertRaisesRegex(ValueError, "正在运行"):
                self.manager.start(self.series_id)
            self.manager.stop(self.series_id)
            wait_for(self.manager, lambda state: not state["running"] and state["status"] in {"stopped", "closed"})

    def test_close_stops_active_scan_then_releases_browser(self):
        self.start_blocking_scan()
        self.manager.close()
        state = wait_for(self.manager, lambda state: state["status"] == "closed")
        self.assertTrue(BlockingScanner.instances[0].stop_requested.is_set())
        self.assertTrue(FakeBrowser.instances[0].closed)
        self.assertIsNone(self.manager.scanner)
        self.assertEqual(state["login"], "unknown")
        self.assertEqual(self.db.latest_scan_status("jphoo")["status"], "stopping")

    def test_shutdown_stops_active_scan_and_joins_worker_before_profile_release(self):
        self.start_blocking_scan()
        self.manager.shutdown()
        self.assertFalse(self.manager.thread.is_alive())
        self.assertTrue(BlockingScanner.instances[0].stop_requested.is_set())
        self.assertTrue(FakeBrowser.instances[0].closed)
        self.assertIsNone(self.manager.scanner)
        self.assertEqual(self.manager.status()["status"], "closed")
        self.assertEqual(self.db.latest_scan_status("jphoo")["status"], "stopping")



    def test_completed_scan_result_keeps_its_status(self):
        self.ready_session()
        with patch("backend.scanner.JphooScanner", ImmediateScanner):
            self.manager.start(self.series_id)
            state = wait_for(self.manager, lambda state: not state["running"] and state["status"] == "stopped")
        self.assertEqual(state["status"], "stopped")
        self.assertNotIn("multiple values", state.get("message", ""))
if __name__ == "__main__":
    unittest.main()
