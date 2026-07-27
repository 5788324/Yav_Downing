import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yav_v2
from backend.runtime import InstanceLock, safe_text, write_runtime_state


class ReleaseEntryTests(unittest.TestCase):
    def test_command_flags_and_redaction(self):
        args = yav_v2.parse_args(['--data-dir', 'X:/data', '--port', '8877', '--no-browser', '--migrate-v1', 'X:/v1.db', '--dry-run'])
        self.assertEqual(args.data_dir, Path('X:/data'))
        self.assertEqual(args.port, 8877)
        self.assertTrue(args.no_browser)
        self.assertTrue(args.dry_run)
        self.assertNotIn('secret-token', safe_text('token=secret-token magnet:?xt=urn:btih:ABC'))

    def test_migration_apply_backs_up_existing_v2(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder)
            args = yav_v2.parse_args(['--data-dir', str(data), '--migrate-v1', str(data / 'old.db')])
            logger = logging.getLogger('test-release-entry')
            with patch('yav_v2.v2_counts', return_value={'movies': 1}), patch('yav_v2.backup_data_dir', return_value={'backup_dir': 'pre'}), patch('yav_v2.migrate', return_value={'mode': 'apply', 'before': {}, 'after': {}}) as migration:
                (data / 'library.db').write_bytes(b'db')
                self.assertEqual(yav_v2._run_command(args, logger), 0)
            self.assertTrue(migration.call_args.kwargs['apply'])

    def test_stale_instance_lock_is_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_runtime_state(root, pid=99999999, port=8765, instance_id="stale", token="old")
            stale = root / 'runtime' / 'instance.lock'
            stale.write_text('0', encoding='utf-8')
            lock = InstanceLock(root, 8766)
            self.assertTrue(lock.acquire())
            self.assertEqual(lock.path.parent.name, 'runtime')
            lock.release()

    def test_unlocked_file_does_not_depend_on_old_pid_or_http_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_runtime_state(root, pid=1234, port=8765, instance_id="old", token="old")
            (root / 'runtime' / 'instance.lock').write_text('0', encoding='utf-8')
            lock = InstanceLock(root, 8766)
            self.assertTrue(lock.acquire())
            lock.release()

    def test_wait_for_existing_instance_uses_runtime_port(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_runtime_state(root, pid=1234, port=8899, instance_id="running", token="token")
            with patch('yav_v2.open_existing_page', side_effect=[False, True]) as probe, patch('yav_v2.time.sleep'):
                port, ready = yav_v2._wait_for_existing_instance(root, 8765, timeout=1)
            self.assertTrue(ready)
            self.assertEqual(port, 8899)
            self.assertEqual(probe.call_args_list[0].args[0], 8899)


if __name__ == '__main__':
    unittest.main()
