"""Yav V2 只读完整性审计。"""
from __future__ import annotations
import argparse, json, re, sqlite3
from pathlib import Path
from .db import is_invalid_metadata, normalize_btih

def audit(path: str | Path) -> dict:
    db_path = Path(path).resolve()
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        raw = connection.execute("SELECT id,movie_id,btih FROM magnets").fetchall()
        normalized: dict[str, list[sqlite3.Row]] = {}
        hex40 = base32 = invalid_btih = 0
        for row in raw:
            value = row["btih"] or ""
            if re.fullmatch(r"[0-9a-fA-F]{40}", value): hex40 += 1
            elif re.fullmatch(r"[A-Za-z2-7]{32}", value): base32 += 1
            else: invalid_btih += 1
            try: normalized.setdefault(normalize_btih(value), []).append(row)
            except ValueError: pass
        same_movie, cross_movie = [], []
        for btih, rows in normalized.items():
            movie_ids = sorted({row["movie_id"] for row in rows})
            if len(rows) > 1 and len(movie_ids) == 1: same_movie.append({"btih": btih, "amount": len(rows), "movie_ids": movie_ids})
            if len(movie_ids) > 1: cross_movie.append({"btih": btih, "amount": len(rows), "movie_ids": movie_ids})
        actresses = connection.execute("SELECT m.id,m.title,m.manual_fields,a.name FROM movies m JOIN movie_actresses ma ON ma.movie_id=m.id JOIN actresses a ON a.id=ma.actress_id").fetchall()
        invalid = [row for row in actresses if is_invalid_metadata(row["name"])]
        return {"movies": connection.execute("SELECT COUNT(*) FROM movies").fetchone()[0], "magnets": len(raw), "btih_40_hex": hex40, "btih_32_base32": base32, "invalid_btih": invalid_btih, "same_movie_normalized_duplicate_btih": same_movie, "cross_movie_normalized_duplicate_btih": cross_movie, "cross_movie_duplicate_btih": cross_movie, "invalid_actresses": [{"movie_id":r["id"],"title":r["title"],"manual_fields":r["manual_fields"],"name":r["name"]} for r in invalid]}
    finally: connection.close()

def main():
    parser=argparse.ArgumentParser(description="Yav V2 只读完整性审计")
    parser.add_argument("--db",required=True)
    print(json.dumps(audit(parser.parse_args().db),ensure_ascii=False,indent=2))
if __name__ == "__main__": main()