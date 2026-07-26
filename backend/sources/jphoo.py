from .base import MovieSource
class JphooSource(MovieSource):
    name = "jphoo"
    def scan_series(self, url): raise NotImplementedError("JPHOO 扫描将在阶段 4 迁移")
    def fetch_movie(self, url): raise NotImplementedError("JPHOO 详情解析将在阶段 4 迁移")
    def fetch_magnets(self, url): raise NotImplementedError("JPHOO 磁链解析将在阶段 4 迁移")
