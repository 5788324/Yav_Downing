import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.backup import backup_data_dir
from backend.db import LibraryDatabase
from backend.restore import RestoreError, restore_data_dir


class RestoreTests(unittest.TestCase):
    def _count(self, db_path):
        db = sqlite3.connect(db_path)
        try:
            return db.execute('SELECT COUNT(*) FROM movies').fetchone()[0]
        finally:
            db.close()

    def test_dry_run_and_restore_are_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'data'
            cover = root / 'cover.jpg'
            cover.write_bytes(b'cover')
            db = LibraryDatabase(data / 'library.db')
            first = db.add_or_update_movie('ABC-001')
            with db.connect() as connection:
                connection.execute('UPDATE movies SET cover_path=? WHERE id=?', (str(cover), first))
            snapshot = backup_data_dir(data, root / 'backups')
            db.add_or_update_movie('ABC-002')
            profile = data / 'browser-profile'
            profile.mkdir()
            (profile / 'keep.txt').write_text('private', encoding='utf-8')
            report = restore_data_dir(data, snapshot['backup_dir'], dry_run=True)
            self.assertEqual(report['mode'], 'dry-run')
            self.assertEqual(self._count(data / 'library.db'), 2)
            result = restore_data_dir(data, snapshot['backup_dir'])
            self.assertEqual(self._count(data / 'library.db'), 1)
            self.assertTrue(Path(result['pre_restore_backup']).is_dir())
            self.assertEqual(self._count(Path(result['pre_restore_backup']) / 'library.db'), 2)
            self.assertEqual((profile / 'keep.txt').read_text(encoding='utf-8'), 'private')
            restored = sqlite3.connect(data / 'library.db')
            try:
                restored_cover = Path(restored.execute('SELECT cover_path FROM movies WHERE id=?', (first,)).fetchone()[0])
            finally:
                restored.close()
            self.assertEqual(restored_cover.read_bytes(), b'cover')

    def test_invalid_manifest_does_not_touch_current_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root / 'data'
            LibraryDatabase(data / 'library.db').add_or_update_movie('SAFE-001')
            bad = root / 'bad'
            bad.mkdir()
            (bad / 'manifest.json').write_text(json.dumps({'backup_format': 1, 'database': 'library.db', 'files': []}), encoding='utf-8')
            with self.assertRaisesRegex(RestoreError, '数据库快照不存在'):
                restore_data_dir(data, bad)
            self.assertEqual(self._count(data / 'library.db'), 1)


if __name__ == '__main__':
    unittest.main()