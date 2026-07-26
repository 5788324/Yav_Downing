from .base import MovieSource
class JavdbSource(MovieSource):
    name = "javdb"
    def scan_series(self, url): raise NotImplementedError("JavDB 扫描将在阶段 4 迁移")
    def fetch_movie(self, url): raise NotImplementedError("JavDB 详情解析将在阶段 4 迁移")
    def fetch_magnets(self, url): raise NotImplementedError("JavDB 磁链解析将在阶段 4 迁移")
