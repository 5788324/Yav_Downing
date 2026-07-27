from __future__ import annotations

import html
import sqlite3
import sys
from pathlib import Path

from backend.db import LibraryDatabase


def svg_cover(path: Path, title: str, hue: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = html.escape(title)
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="840" viewBox="0 0 600 840">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="hsl({hue} 55% 62%)"/><stop offset="1" stop-color="hsl({(hue + 55) % 360} 48% 24%)"/></linearGradient></defs>
<rect width="600" height="840" fill="url(#g)"/><circle cx="470" cy="150" r="170" fill="rgba(255,255,255,.12)"/>
<text x="50" y="650" fill="white" font-size="58" font-family="serif" font-weight="700">{safe}</text>
<text x="50" y="718" fill="rgba(255,255,255,.72)" font-size="26" font-family="sans-serif">Yav UI fixture</text>
</svg>''',
        encoding="utf-8",
    )


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: ui_seed.py DATA_DIR")
    data_dir = Path(sys.argv[1]).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "library.db"
    if db_path.exists():
        db_path.unlink()
    database = LibraryDatabase(db_path)
    studios = ["青岚制作", "白塔影业", "橙木工作室"]
    series_values = ["城市夜航", "夏日档案", "冬季书简", "无界剧场"]
    actresses = ["林一", "周夏", "沈遥", "顾清", "叶舟"]
    covers = data_dir / "covers"

    for number in range(1, 83):
        title = f"UI-{number:03d} 测试影片"
        studio = "" if number % 11 == 0 else studios[number % len(studios)]
        series = "" if number % 13 == 0 else series_values[number % len(series_values)]
        cast = [] if number % 7 == 0 else [actresses[number % len(actresses)]]
        if number % 9 == 0:
            cast.append(actresses[(number + 2) % len(actresses)])
        cover_url = "https://invalid.example.test/missing-poster.jpg" if number == 2 else ""
        release_date = f"202{number % 6}-{(number % 12) + 1:02d}-{(number % 27) + 1:02d}"
        source = "JavDB" if number % 2 else "JPHOO"
        source_url = f"https://example.test/{source.lower()}/{number}"
        movie_id = database.add_or_update_movie(
            title,
            studio=studio,
            series=series,
            release_date=release_date,
            duration_minutes=80 + number,
            cover_url=cover_url,
            actresses=cast,
            source=source,
            source_url=source_url,
            source_movie_id=f"SRC-{number:03d}",
        )
        if number <= 9:
            database.set_favorite(movie_id, True)
        if number % 3:
            btih = f"{number:040X}"
            magnet = f"magnet:?xt=urn:btih:{btih}&dn={title}"
            database.add_magnet(movie_id, magnet, source, source_url, size_bytes=(number + 1) * 1024 * 1024 * 128)
            if number % 10 == 0:
                other = "JPHOO" if source == "JavDB" else "JavDB"
                other_url = f"https://example.test/{other.lower()}/{number}"
                database.add_or_update_movie(title, source=other, source_url=other_url)
                database.add_magnet(movie_id, magnet, other, other_url, size_bytes=(number + 1) * 1024 * 1024 * 128)
                second_btih = f"{number + 1000:040X}"
                database.add_magnet(
                    movie_id,
                    f"magnet:?xt=urn:btih:{second_btih}&dn={title}-bonus",
                    other,
                    other_url,
                    size_bytes=None,
                )
        if number % 5 == 0:
            cover = covers / f"movie-{movie_id}.svg"
            svg_cover(cover, f"UI-{number:03d}", (number * 23) % 360)
            with database.connect() as connection:
                connection.execute("UPDATE movies SET cover_path=? WHERE id=?", (str(cover), movie_id))

    # A deliberately sparse record exercises all unknown-value filters.
    sparse_id = database.add_or_update_movie("UI-999 完全待补全")
    database.set_favorite(sparse_id, False)

    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA wal_checkpoint(FULL)")
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    print(f"seeded={83} database={db_path}")


if __name__ == "__main__":
    main()
