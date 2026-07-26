import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from backend.backup import backup_data_dir
from backend.db import LibraryDatabase


class BackupTests(unittest.TestCase):
    def test_backup_copies_database_existing_covers_and_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data_dir = root / "data"
            covers = root / "covers"
            covers.mkdir(parents=True)
            existing = covers / "cover.jpg"
            existing.write_bytes(b"cover-data")
            db = LibraryDatabase(data_dir / "library.db")
            first = db.add_or_update_movie("ABC-001")
            second = db.add_or_update_movie("ABC-002")
            with db.connect() as connection:
                connection.execute("UPDATE movies SET cover_path=? WHERE id=?", (str(existing), first))
                connection.execute("UPDATE movies SET cover_path=? WHERE id=?", (str(covers / "missing.jpg"), second))
            report = backup_data_dir(data_dir, root / "backups")
            backup_dir = Path(report["backup_dir"])
            self.assertEqual((report["copied_covers"], report["missing_covers"]), (1, 1))
            self.assertTrue((backup_dir / "library.db").is_file())
            self.assertEqual((backup_dir / "covers" / f"{first}.jpg").read_bytes(), b"cover-data")
            manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["local_covers"], [{"movie_id": first, "file": f"{first}.jpg"}])
            self.assertEqual(manifest["missing_cover_movie_ids"], [second])
            with closing(sqlite3.connect(backup_dir / "library.db")) as snapshot:
                self.assertEqual(snapshot.execute("SELECT COUNT(*) FROM movies").fetchone()[0], 2)
            self.assertTrue(existing.is_file(), "备份不得修改原封面")

    def test_backup_requires_existing_v2_database(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "找不到 V2 数据库"):
                backup_data_dir(Path(folder) / "empty")


if __name__ == "__main__":
    unittest.main()
