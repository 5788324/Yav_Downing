"""Yav V2 只读完整性审计。"""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
from .db import INVALID_METADATA_VALUES

def audit(path: str | Path) -> dict:
    db_path = Path(path).resolve()
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        duplicate = connection.execute("SELECT btih,COUNT(*) amount,GROUP_CONCAT(movie_id) movie_ids FROM magnets GROUP BY btih HAVING COUNT(*)>1").fetchall()
        marks = ",".join("?" for _ in INVALID_METADATA_VALUES)
        invalid = connection.execute(f"SELECT m.id,m.title,m.manual_fields,a.name FROM movies m JOIN movie_actresses ma ON ma.movie_id=m.id JOIN actresses a ON a.id=ma.actress_id WHERE a.name IN ({marks})", tuple(INVALID_METADATA_VALUES)).fetchall()
        return {"movies": connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0], "magnets": connection.execute("SELECT COUNT(*) FROM magnets").fetchone()[0], "cross_movie_duplicate_btih": [{"btih":r[0],"amount":r[1],"movie_ids":r[2]} for r in duplicate], "invalid_actresses": [{"movie_id":r[0],"title":r[1],"manual_fields":r[2],"name":r[3]} for r in invalid]}
    finally: connection.close()

def main():
    parser=argparse.ArgumentParser(description="Yav V2 只读完整性审计")
    parser.add_argument("--db",required=True)
    print(json.dumps(audit(parser.parse_args().db),ensure_ascii=False,indent=2))
if __name__ == "__main__": main()