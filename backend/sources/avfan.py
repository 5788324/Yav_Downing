"""AVFan 公开 HTML 解析；验证页明确报错，不作为空列表完成。"""
import re
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
from .javdb import JavdbSource, SourceMovie, SourceMagnet, size_bytes
from ..db import normalize_btih
from datetime import date
from urllib.parse import unquote_plus


def candidate_matches(movie, name):
    """先拒绝日期冲突，再要求明确片名或演员匹配。"""
    name = unquote_plus(name or '')
    if not name: return False
    marker = re.search(r'(?<!\d)(\d{2,4})[. -](\d{2})[. -](\d{2})(?!\d)', name)
    if marker and movie.release_date:
        a,b,c = map(int, marker.groups())
        try:
            candidate_date = date(a if a > 99 else 2000+a,b,c).isoformat()
        except ValueError:
            try: candidate_date = date(2000+c,a,b).isoformat()
            except ValueError: return False
        if candidate_date != movie.release_date: return False
    heading = re.sub(r'^\S+\s+', '', movie.title).casefold()
    words = {w for w in re.findall(r'[a-z]{3,}', heading) if w not in {'the','and','for','with'}}
    candidate_words = set(re.findall(r'[a-z]{3,}', name.casefold()))
    title_match = len(words & candidate_words) >= min(3,len(words)) if words else False
    cast_match = any(all(w in candidate_words for w in re.findall(r'[a-z]{3,}', actor.casefold())) for actor in movie.actresses or [] if len(re.findall(r'[a-z]{3,}', actor.casefold())) >= 2)
    return title_match or cast_match


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'avfan.com':
        raise ValueError('AVFan 只接受 https://avfan.com/ 网址')
    return url


def checked_soup(html):
    soup = BeautifulSoup(html, 'lxml')
    if soup.select_one('#challenge-running, #challenge-form') or 'Just a moment' in (soup.title.get_text() if soup.title else ''):
        raise RuntimeError('AVFan 需要在采集器浏览器中完成人机验证')
    return soup


def parse_movie(html, url):
    soup = checked_soup(html)
    info = soup.select_one('dl.movie-info')
    if not info or not soup.select_one('h1'):
        raise ValueError('AVFan 影片资料区缺失，可能需要验证或登录')
    fields = {}
    for dt in info.select('dt'):
        dd = dt.find_next_sibling('dd')
        if dd: fields[dt.get_text(strip=True)] = dd
    def value(label):
        node = fields.get(label)
        return node.get_text(' ', strip=True) if node else ''
    title = soup.title.get_text().rsplit('|', 1)[0].strip() if soup.title else soup.h1.get_text(' ', strip=True)
    cover = soup.select_one('a[href*="/covers/"]')
    duration = re.search(r'\d+', value('片长'))
    cast = fields.get('演员')
    actresses = list(dict.fromkeys(a.get_text(strip=True) for a in cast.select('a.female') if a.get_text(strip=True))) if cast else []
    return SourceMovie(title, url, urljoin(url, cover['href']) if cover else '', value('制作商'), value('系列'), value('发行日期'), int(duration[0]) if duration and int(duration[0]) > 0 else None, actresses)


def parse_magnets(html):
    soup = checked_soup(html)
    out = {}
    for a in soup.select('a[href^="magnet:"]'):
        magnet = a['href']
        raw = parse_qs(urlparse(magnet).query).get('xt', [''])[0]
        try: btih = normalize_btih(raw.removeprefix('urn:btih:'))
        except ValueError: continue
        if not btih: continue
        spans = a.select('span')
        size = size_bytes(spans[-1].get_text(' ', strip=True)) if spans else None
        previous = out.get(btih)
        if not previous or (size or 0) > (previous.size_bytes or 0): out[btih] = SourceMagnet(magnet, size)
    return list(out.values())


class AvfanSource(JavdbSource):
    name = 'avfan'
    def __init__(self, session=None, delay=1.5, loader=None):
        super().__init__(session, delay)
        self.loader = loader
    def request(self, url):
        validate_url(url)
        if self.loader:
            self._pace_request()
            return self.loader(url)
        return super().request(url)
    def fetch_movie(self, url):
        return parse_movie(str(self._movie_soup(url)), url)
    def fetch_magnets(self, url):
        html = str(self._movie_soup(url))
        movie = parse_movie(html, url)
        result = [item for item in parse_magnets(html) if candidate_matches(movie, parse_qs(urlparse(item.magnet).query).get('dn',[''])[0])]
        self._page_cache.pop(url, None)
        return result
    def scan_series(self, url, *, start_page=1, stop_event=None):
        validate_url(url)
        if not re.fullmatch(r'/(?:zh-CN/)?(?:series|makers)/[A-Za-z0-9]+', urlparse(url).path):
            raise ValueError('请使用 AVFan 系列或厂商网址')
        parsed = urlparse(url); query = parse_qs(parsed.query)
        page = max(1, start_page)
        while not stop_event or not stop_event.is_set():
            query['page'] = [str(page)]
            current = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
            soup = checked_soup(self.request(current))
            if not soup.select_one('h2, h1'): raise ValueError('AVFan 列表结构异常')
            links = list(dict.fromkeys(urljoin(url, a['href']) for a in soup.select('a[href]') if re.fullmatch(r'/(?:zh-CN/)?movies/[A-Za-z0-9]+', a['href'])))
            yield page, links
            next_page = any(urlparse(urljoin(url, a['href'])).path == parsed.path and parse_qs(urlparse(a['href']).query).get('page') == [str(page+1)] for a in soup.select('a[href]'))
            if not next_page: return
            page += 1
