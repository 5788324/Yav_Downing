import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.migrate_v1 import migrate, v2_counts


class V1MigrationTests(unittest.TestCase):
    def _legacy_db(self, path):
        db = sqlite3.connect(path)
        try:
            db.executescript('''
                CREATE TABLE works(id INTEGER PRIMARY KEY, title_manual TEXT, title_auto TEXT, code_manual TEXT, code_auto TEXT, publisher_manual TEXT, publisher_auto TEXT, series TEXT, release_date_manual TEXT, release_date_auto TEXT, cover_url_manual TEXT, cover_url_auto TEXT, favorite INTEGER, site TEXT, source_url TEXT);
                CREATE TABLE actors(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE work_actors(work_id INTEGER, actor_id INTEGER);
                CREATE TABLE magnets(work_id INTEGER, magnet TEXT, source_site TEXT, size_gb REAL);
            ''')
            db.execute("INSERT INTO works VALUES(1,'ABC-001','', '', '', 'Studio', '', 'Series', '2024-01-01', '', '', '', 1, 'JavDB', 'https://example.test/v/1')")
            db.execute("INSERT INTO actors VALUES(1,'女优甲')")
            db.execute('INSERT INTO work_actors VALUES(1,1)')
            db.execute("INSERT INTO magnets VALUES(1,'magnet:?xt=urn:btih:ABC123','JavDB',1.5)")
            db.commit()
        finally:
            db.close()

    def test_dry_run_is_read_only_and_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, new = root / 'v1.db', root / 'v2.db'
            self._legacy_db(old)
            before_bytes = old.read_bytes()
            report = migrate(old, new)
            self.assertEqual(report['mode'], 'dry-run')
            self.assertFalse(new.exists())
            self.assertEqual(old.read_bytes(), before_bytes)
            first = migrate(old, new, apply=True)
            second = migrate(old, new, apply=True)
            self.assertEqual(first['after']['movies'], 1)
            self.assertEqual(second['after']['movies'], 1)
            self.assertEqual(second['after']['magnets'], 1)
            self.assertEqual(second['after']['magnet_sources'], 1)
            self.assertEqual(v2_counts(new)['actresses'], 1)


if __name__ == '__main__':
    unittest.main()