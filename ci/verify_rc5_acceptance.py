import sqlite3
import sys
from pathlib import Path

mode = sys.argv[1]
path = Path(sys.argv[2])
connection = sqlite3.connect(path)
try:
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    if mode == "dry-restore":
        assert connection.execute(
            "SELECT COUNT(*) FROM movies WHERE title=?", ("ACCEPT-B",)
        ).fetchone()[0] == 1
    elif mode == "restored":
        assert connection.execute(
            "SELECT COUNT(*) FROM movies WHERE title=?", ("ACCEPT-A",)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM movies WHERE title=?", ("ACCEPT-B",)
        ).fetchone()[0] == 0
    elif mode == "migrated":
        assert connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM magnets").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM magnet_sources").fetchone()[0] == 1
    else:
        raise ValueError(f"unknown verification mode: {mode}")
finally:
    connection.close()
