"""AVFan 命令行采集入口；使用独立 Edge Profile。"""
import argparse
import json
import signal
from pathlib import Path
from .db import LibraryDatabase
from .scanner import JavdbScanner
from .sources.avfan import AvfanSource, validate_url


class AvfanScanner(JavdbScanner):
    source_name = 'avfan'
    source_factory = staticmethod(AvfanSource)


def main():
    parser = argparse.ArgumentParser(description='AVFan 系列/厂商采集（独立浏览器验证）')
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--url', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--from-start', action='store_true')
    args = parser.parse_args()
    validate_url(args.url)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(args.profile.resolve()), channel='msedge', headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(args.url, wait_until='domcontentloaded', timeout=30000)
            input('请在此独立 Edge 确认页面正常（如需验证请手动完成），然后按 Enter 开始：')
            def load(url):
                response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                if response and response.status >= 400: raise RuntimeError(f'AVFan HTTP {response.status}')
                return page.content()
            # 在初始化数据库前验证首个页面，避免验证失败留下空库。
            from .sources.avfan import checked_soup
            checked_soup(page.content())
            db = LibraryDatabase(args.db)
            existing = next((row for row in db.list_source_series('avfan') if row['url'] == args.url), None)
            sid = existing['id'] if existing else db.save_source_series(args.name, args.url, source='avfan')
            scanner = AvfanScanner(db)
            scanner.source_factory = lambda: AvfanSource(loader=load)
            signal.signal(signal.SIGINT, lambda *_: scanner.stop())
            print(json.dumps(scanner.run(sid, args.from_start), ensure_ascii=False))
        finally:
            context.close()


if __name__ == '__main__': main()
