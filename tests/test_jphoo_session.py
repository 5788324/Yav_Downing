import tempfile
import time
import unittest
from pathlib import Path
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
        return {"profile_dir": self.profile_dir, "target_url": target_url, "target_origin": "https://mirror.example", "current_url": target_url, "password_visible": 0, "password_hidden": 1, "cookie_count": 2, "domain_cookie_count": 1, "local_storage_keys": 1, "session_storage_keys": 0, "signals": ["authentication_storage_present"], "login": "ready", "session_state": "open"}


def wait_for(manager, predicate):
    deadline = time.time() + 2
    while time.time() < deadline:
        if predicate(manager.status()):
            return manager.status()
        time.sleep(0.01)
    raise AssertionError(manager.status())


class JphooSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = LibraryDatabase(Path(self.temp.name) / "library.db")
        self.series_id = self.db.save_source_series("真实镜像", "https://mirror.example/series/one", source="jphoo", profile_dir="C:/legacy/profile")
        FakeBrowser.instances.clear()
        self.manager = JphooSessionManager(self.db, Path(self.temp.name) / "app-profile", browser_factory=FakeBrowser)

    def tearDown(self):
        self.manager.shutdown()
        self.temp.cleanup()

    def test_authentication_state_ignores_hidden_password_form(self):
        self.assertEqual(authentication_state("https://mirror.example/work/1", 0, 0, 0, 0)[0], "unknown")
        self.assertEqual(authentication_state("https://mirror.example/work/1", 1, 1, 0, 0)[0], "login_required")
        self.assertEqual(authentication_state("https://mirror.example/login", 0, 1, 0, 0)[0], "login_required")
        self.assertEqual(authentication_state("https://mirror.example/work/1", 0, 1, 0, 0)[0], "ready")

    def test_legacy_profile_is_preserved_when_series_is_edited(self):
        self.db.save_source_series("重命名", "https://mirror.example/series/two", True, self.series_id, source="jphoo")
        self.assertEqual(self.db.get_source_series(self.series_id, "jphoo")["profile_dir"], "C:/legacy/profile")
    def test_open_and_check_reuse_one_application_profile_and_series_origin(self):
        self.manager.open(self.series_id)
        wait_for(self.manager, lambda state: state["status"] == "ready")
        self.manager.check()
        state = wait_for(self.manager, lambda state: state.get("last_verified_at"))
        self.assertEqual(len(FakeBrowser.instances), 1)
        self.assertEqual(FakeBrowser.instances[0].profile_dir, str((Path(self.temp.name) / "app-profile").resolve()))
        self.assertEqual(FakeBrowser.instances[0].page.urls, ["https://mirror.example/series/one", "https://mirror.example/series/one"])
        self.assertEqual(state["target_origin"], "https://mirror.example")
        self.assertNotEqual(FakeBrowser.instances[0].profile_dir, "C:/legacy/profile")

    def test_close_never_claims_ready_and_probe_detects_manual_close(self):
        self.manager.open(self.series_id)
        wait_for(self.manager, lambda state: state["status"] == "ready")
        FakeBrowser.instances[0].closed = True
        state = wait_for(self.manager, lambda state: state["status"] == "closed")
        self.assertEqual(state["login"], "unknown")
        self.manager.open(self.series_id)
        wait_for(self.manager, lambda state: state["status"] == "ready")
        self.manager.close()
        state = wait_for(self.manager, lambda state: state["status"] == "closed")
        self.assertEqual(state["login"], "unknown")


if __name__ == "__main__":
    unittest.main()
