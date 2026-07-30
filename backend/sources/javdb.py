"""JavDB 的轻量 HTTP 来源适配器。"""
from __future__ import annotations
import re, time
from dataclasses import dataclass
from threading import Event
from urllib.parse import urljoin, urlparse
import requests
from ..db import is_invalid_metadata
from bs4 import BeautifulSoup

def normalize_release_date(value: str) -> str:
    text = (value or "").replace("/", "-").replace(".", "-")
    found = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    return f"{int(found.group(1)):04d}-{int(found.group(2)):02d}-{int(found.group(3)):02d}" if found else ""

@dataclass
class SourceMovie:
    title: str; source_url: str; cover_url: str=''; studio: str=''; series: str=''; release_date: str=''; duration_minutes: int|None=None; actresses: list[str]|None=None
@dataclass
class SourceMagnet:
    magnet: str; size_bytes: int|None=None

def size_bytes(value: str) -> int|None:
    hit=re.search(r'([\d.]+)\s*(GB|MB|KB)',value or '',re.I)
    if not hit:return None
    return round(float(hit.group(1))*{'GB':1024**3,'MB':1024**2,'KB':1024}[hit.group(2).upper()])

class JavdbSource:
    name='javdb'; headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'}
    def __init__(self, session=None, delay=0.6): self.session=session or requests.Session(); self.delay=delay; self._page_cache={}
    def request(self, url):
        last_error = None
        for attempt in range(3):
            try:
                response = self.session.get(url, headers=self.headers, timeout=(5, 20))
                response.raise_for_status(); response.encoding = 'utf-8'; return response.text
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2: time.sleep(attempt + 1)
        status = getattr(getattr(last_error, 'response', None), 'status_code', None)
        detail = f"HTTP {status}" if status else type(last_error).__name__ if last_error else '未知请求错误'
        raise RuntimeError(f"JavDB 请求连续失败：{detail}")
    def scan_series(self,url,*,start_page=1,stop_event:Event|None=None):
        current=url; page=1
        while current:
            if stop_event and stop_event.is_set(): return
            soup=BeautifulSoup(self.request(current),'lxml'); base=f'{urlparse(current).scheme}://{urlparse(current).netloc}'
            links=[]
            for a in soup.select('a[href^="/v/"]'):
                href=a.get('href','')
                if '?' not in href and '#' not in href: links.append(urljoin(base,href))
            if page >= start_page:
                yield page,list(dict.fromkeys(links))
            next_link=soup.select_one('a.pagination-next[rel="next"]'); current=urljoin(base,next_link['href']) if next_link and next_link.get('href') else None; page+=1
            if current: time.sleep(self.delay)
    def _movie_soup(self, url):
        if url not in self._page_cache: self._page_cache[url] = self.request(url)
        return BeautifulSoup(self._page_cache[url], 'lxml')
    def fetch_movie(self,url):
        soup=self._movie_soup(url); text=' '.join(soup.stripped_strings)
        title=(soup.select_one('meta[property="og:title"]') or soup.title); title=(title.get('content') if title and title.has_attr('content') else title.get_text(' ',strip=True) if title else '').split('|')[0].strip()
        cover=soup.select_one('meta[property="og:image"],.video-cover img,.cover img'); cover=urljoin(url,(cover.get('content') or cover.get('src',''))) if cover else ''
        date=re.search(r'(?:發行日期|发行日期|日期)\s*[:：]?\s*(\d{4}[./-]\d{1,2}[./-]\d{1,2})',text)
        duration=re.search(r'(?:長度|长度|時長|时长)\s*[:：]?\s*(\d+)',text)
        actresses=[a.get_text(' ',strip=True) for a in soup.select('a[href^="/actor/"],a[href^="/actors/"],a[href^="/performer/"],a[href^="/performers/"]') if a.get_text(strip=True) and not is_invalid_metadata(a.get_text(' ',strip=True))]
        studios=[a.get_text(' ',strip=True) for a in soup.select('a[href*="maker"],a[href*="studio"],a[href*="publisher"]') if a.get_text(strip=True)]
        return SourceMovie(title=title, source_url=url, cover_url=cover, studio=studios[0] if studios else '', release_date=normalize_release_date(date.group(1)) if date else '', duration_minutes=int(duration.group(1)) if duration else None, actresses=list(dict.fromkeys(actresses)))
    def fetch_magnets(self,url):
        soup=self._movie_soup(url); out=[]
        for a in soup.select('a[href^="magnet:"]'):
            magnet=a.get('href',''); size=size_bytes(a.get_text(' ',strip=True)); out.append(SourceMagnet(magnet,size))
        return list({m.magnet:m for m in out}.values())
