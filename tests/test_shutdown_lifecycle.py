import json
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import yav_v2
from backend.app import ApplicationRuntime, Handler
from backend.db import LibraryDatabase
from backend.runtime import APP_VERSION, clear_runtime_state, port_is_open, read_runtime_state, write_runtime_state


class NoBrowserInstanceCollisionTests(unittest.TestCase):
    def test_duplicate_no_browser_start_returns_without_native_message_box(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Mock()
            lock.acquire.return_value = False
            logger = Mock()
            with patch.object(yav_v2, "configure_logging", return_value=logger), \
                 patch.object(yav_v2, "choose_port", return_value=18768), \
                 patch.object(yav_v2, "InstanceLock", return_value=lock), \
                 patch.object(yav_v2, "_wait_for_existing_instance", return_value=(18768, True)), \
                 patch.object(yav_v2, "_message") as message_box, \
                 patch.object(yav_v2.webbrowser, "open") as open_browser:
                self.assertEqual(yav_v2.run(["--data-dir", folder, "--port", "18768", "--no-browser"]), 0)
            message_box.assert_not_called()
            open_browser.assert_not_called()
            logger.info.assert_called()


class _Component:
    def __init__(self, name, events):
        self.name, self.events = name, events
        self.running = False

    def status(self):
        return {"running": self.running}

    def stop(self):
        self.events.append(f"{self.name}:stop")

    def shutdown(self, timeout=0):
        self.events.append(f"{self.name}:shutdown:{timeout}")
        self.running = False
        return True

    def is_running_series(self, _series_id):
        return False


class ShutdownHttpTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.db = LibraryDatabase(Path(self.folder.name) / "library.db")
        self.events = []
        Handler.database = self.db
        Handler.scans = _Component("javdb", self.events)
        Handler.jphoo_scans = Handler.jphoo_login = _Component("jphoo", self.events)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.runtime = ApplicationRuntime(self.server, Handler.scans, Handler.jphoo_scans, "test-token", "instance-a")
        Handler.runtime = self.runtime
        self.thread = threading.Thread(target=self.server.serve_forever, name="test-yav-server")
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        if self.thread.is_alive():
            self.server.shutdown()
        self.thread.join(3)
        self.server.server_close()
        self.folder.cleanup()

    def request(self, path, payload=None, *, origin=None, content_type="application/json"):
        headers = {"Content-Type": content_type}
        if origin is not None:
            headers["Origin"] = origin
        request = Request(self.base + path, data=json.dumps(payload or {}).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_status_identity_and_rejections(self):
        with urlopen(self.base + "/api/app/status", timeout=3) as response:
            status = json.loads(response.read().decode("utf-8"))
        self.assertEqual(status["app"], "Yav")
        self.assertEqual(status["version"], APP_VERSION)
        self.assertEqual(status["instance_id"], "instance-a")
        self.assertFalse(status["shutdown_pending"])
        self.assertNotIn("token", status)
        self.assertEqual(self.request("/api/app/shutdown", {}, content_type="text/plain")[0], 415)
        self.assertEqual(self.request("/api/app/shutdown", {"instance_id": "instance-a"})[0], 403)
        self.assertEqual(self.request("/api/app/shutdown", {"token": "wrong", "instance_id": "instance-a"})[0], 403)
        self.assertEqual(self.request("/api/app/shutdown", {"token": "test-token", "instance_id": "wrong"})[0], 403)
        self.assertEqual(self.request("/api/app/shutdown", {"token": "test-token", "instance_id": "instance-a"}, origin="http://evil.example")[0], 403)

    def test_accepted_shutdown_returns_before_server_stops_and_releases_port(self):
        status, payload = self.request("/api/app/shutdown", {"token": "test-token", "instance_id": "instance-a"})
        self.assertEqual(status, 202)
        self.assertFalse(payload["already_pending"])
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive(), "shutdown handler must not deadlock serve_forever")
        self.server.server_close()
        self.assertFalse(port_is_open(self.server.server_port))
        self.assertEqual(self.events, ["javdb:shutdown:10", "jphoo:shutdown:15"])

    def test_repeat_request_is_idempotent_before_controller_starts(self):
        self.assertTrue(self.runtime.request_shutdown())
        self.assertFalse(self.runtime.request_shutdown())
        self.assertTrue(self.runtime.start_shutdown())
        self.assertFalse(self.runtime.start_shutdown())
        self.thread.join(3)
        self.assertFalse(self.thread.is_alive())

    def test_old_token_cannot_close_new_instance(self):
        self.assertEqual(self.request("/api/app/shutdown", {"token": "old-token", "instance_id": "instance-a"})[0], 403)
        self.assertTrue(self.thread.is_alive())


class RuntimeCredentialTests(unittest.TestCase):
    def test_state_is_separate_and_secret_is_not_in_instance_json(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_runtime_state(root, pid=123, port=8765, instance_id="abc", token="secret-value")
            info, token = read_runtime_state(root)
            self.assertEqual((info["pid"], info["port"], info["instance_id"], info["version"], token), (123, 8765, "abc", APP_VERSION, "secret-value"))
            raw = (root / "runtime" / "instance.json").read_text(encoding="utf-8")
            self.assertNotIn("secret-value", raw)
            clear_runtime_state(root)
            self.assertFalse((root / "runtime").exists())

    def test_cli_wrong_data_dir_and_non_yav_service_do_not_receive_shutdown(self):
        from unittest.mock import patch
        class Response:
            status = 200
            def read(self): return b'{"app":"Other","instance_id":"abc","pid":1}'
            def __enter__(self): return self
            def __exit__(self, *_args): return False
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other:
            write_runtime_state(Path(folder), pid=__import__("os").getpid(), port=18888, instance_id="abc", token="secret")
            logger = __import__("logging").getLogger("shutdown-cli-test")
            with patch("yav_v2.urlopen", return_value=Response()) as request_call, patch("yav_v2.pid_is_alive", return_value=True), patch("yav_v2.port_is_open", return_value=True):
                self.assertEqual(yav_v2._run_command(yav_v2.parse_args(["--data-dir", folder, "--shutdown"]), logger), 0)
            self.assertEqual(request_call.call_count, 1, "非 Yav 状态响应绝不可收到 POST shutdown")
            self.assertEqual(yav_v2._run_command(yav_v2.parse_args(["--data-dir", other, "--shutdown"]), logger), 0)


if __name__ == "__main__":
    unittest.main()