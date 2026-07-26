import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yav_v2
from backend.runtime import InstanceLock, safe_text


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

    def test_stale_instance_lock_is_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            stale = root / 'yav.lock'
            stale.write_text('{"pid": 99999999, "port": 8765}', encoding='utf-8')
            lock = InstanceLock(root, 8766)
            self.assertTrue(lock.acquire())
            lock.release()


if __name__ == '__main__':
    unittest.main()