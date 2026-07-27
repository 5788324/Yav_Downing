import sqlite3
import sys

path = sys.argv[1]
db = sqlite3.connect(path)
db.executescript(
    """
    CREATE TABLE works(
        id INTEGER PRIMARY KEY,
        title_manual TEXT,
        title_auto TEXT,
        code_manual TEXT,
        code_auto TEXT,
        publisher_manual TEXT,
        publisher_auto TEXT,
        series TEXT,
        release_date_manual TEXT,
        release_date_auto TEXT,
        cover_url_manual TEXT,
        cover_url_auto TEXT,
        favorite INTEGER,
        site TEXT,
        source_url TEXT
    );
    CREATE TABLE actors(id INTEGER PRIMARY KEY, name TEXT);
    CREATE TABLE work_actors(work_id INTEGER, actor_id INTEGER);
    CREATE TABLE magnets(work_id INTEGER, magnet TEXT, source_site TEXT, size_gb REAL);
    """
)
db.execute(
    "INSERT INTO works VALUES(1,'CI-001','','','','Studio','','Series','2024-01-01','','','',1,'JavDB','https://example.test/1')"
)
db.execute("INSERT INTO actors VALUES(1,'演员甲')")
db.execute("INSERT INTO work_actors VALUES(1,1)")
db.execute("INSERT INTO magnets VALUES(1,'magnet:?xt=urn:btih:ABC123','JavDB',1.5)")
db.commit()
db.close()
