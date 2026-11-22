import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from backend.avfan_session import AvfanSession
from backend.db import LibraryDatabase


class AvfanSessionTests(unittest.TestCase):
    def wait_state(self, session, expected):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if session.session_status()['status'] == expected: return
            time.sleep(.02)
        self.fail(str(session.session_status()))

    def test_login_check_and_idle_poll_never_navigate_and_closed_window_cannot_start(self):
        with tempfile.TemporaryDirectory() as temp:
            db = LibraryDatabase(Path(temp)/'test.db')
            sid = db.save_source_series('Test','https://avfan.com/zh-CN/series/a',source='avfan')
            page = MagicMock()
            page.is_closed.return_value = False
            page.url = 'https://avfan.com/zh-CN/series/a'
            page.content.return_value = '<h1>Test</h1>'
            context = MagicMock(); context.pages = [page]
            pw = MagicMock(); pw.chromium.launch_persistent_context.return_value = context
            with patch('playwright.sync_api.sync_playwright') as factory:
                factory.return_value.start.return_value = pw
                session = AvfanSession(db, Path(temp)/'profile')
                try:
                    session.action('open',sid); self.wait_state(session,'window_open')
                    session.action('check'); self.wait_state(session,'ready')
                    for _ in range(5): session.session_status()
                    self.assertEqual(page.goto.call_count,1)
                    page.is_closed.return_value = True
                    self.wait_state(session,'closed')
                    with self.assertRaises(ValueError): session.start(sid)
                    page.is_closed.return_value = False
                    # 已关闭的状态仍要求重新打开并验证。
                    with self.assertRaises(ValueError): session.start(sid)
                finally:
                    self.assertTrue(session.shutdown())
