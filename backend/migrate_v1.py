"""从 V1 SQLite 导入 V2；默认只演练，不修改任何数据库。"""
from __future__ import annotations
import argparse, sqlite3
from collections import Counter
from pathlib import Path
from .db import LibraryDatabase

def count(db):
    if isinstance(db, LibraryDatabase):
        with db.connect() as connection: return count(connection)
    return {name: db.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0] for name in ('movies','actresses','source_entries','magnets')}

def legacy_rows(path):
    source=sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True); source.row_factory=sqlite3.Row
    try:
        works=source.execute('SELECT * FROM works ORDER BY id').fetchall()
        for work in works:
            actors=[r['name'] for r in source.execute('SELECT a.name FROM actors a JOIN work_actors wa ON wa.actor_id=a.id WHERE wa.work_id=?',(work['id'],))]
            magnets=source.execute('SELECT * FROM magnets WHERE work_id=?',(work['id'],)).fetchall()
            yield work,actors,magnets
    finally: source.close()

def migrate(old_db, new_db, apply=False):
    old_db,new_db=Path(old_db),Path(new_db)
    if not old_db.is_file(): raise FileNotFoundError(f'旧数据库不存在：{old_db}')
    before = count(LibraryDatabase(new_db)) if new_db.exists() else {'movies':0,'actresses':0,'source_entries':0,'magnets':0}
    seen=Counter(); source_count=Counter(); invalid=0
    if apply:
        target=LibraryDatabase(new_db)
        for work,actors,magnets in legacy_rows(old_db):
            title=work['title_manual'] or work['title_auto'] or work['code_manual'] or work['code_auto'] or '（资料待补全）'
            movie_id=target.add_or_update_movie(title,studio=work['publisher_manual'] or work['publisher_auto'] or '',series=work['series'] or '',release_date=work['release_date_manual'] or work['release_date_auto'] or '',cover_url=work['cover_url_manual'] or work['cover_url_auto'] or '',actresses=actors,source=work['site'],source_url=work['source_url'])
            seen['movies'] += 1; source_count[work['site']] += 1
            for magnet in magnets:
                try: target.add_magnet(movie_id,magnet['magnet'],magnet['source_site'] or work['site'],work['source_url'],size_bytes=round(float(magnet['size_gb'] or 0)*1024**3)); seen['magnets'] += 1
                except ValueError: invalid += 1
        after=count(target)
    else:
        for work,actors,magnets in legacy_rows(old_db):
            seen['movies'] += 1; seen['actress_links'] += len(actors); seen['magnets'] += len(magnets); source_count[work['site']] += 1
        after=before
    return {'mode':'apply' if apply else 'dry-run','old_db':str(old_db),'new_db':str(new_db),'before':before,'after':after,'scanned':dict(seen),'sources':dict(source_count),'invalid_magnets':invalid}

def main():
    parser=argparse.ArgumentParser(description='V1 到 V2 SQLite 迁移（默认 dry-run）')
    parser.add_argument('--old-db',type=Path,required=True,help='V1 library.db 路径（只读）')
    parser.add_argument('--new-db',type=Path,required=True,help='V2 library.db 路径')
    parser.add_argument('--apply',action='store_true',help='实际写入 V2；省略时只统计')
    args=parser.parse_args(); report=migrate(args.old_db,args.new_db,args.apply)
    print('模式：',report['mode']); print('旧库：',report['old_db']); print('新库：',report['new_db']); print('迁移前：',report['before']); print('扫描/导入：',report['scanned']); print('按来源：',report['sources']); print('迁移后：',report['after']); print('无效磁链：',report['invalid_magnets'])
if __name__=='__main__': main()

