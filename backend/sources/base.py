"""来源的轻量接口；抓取逻辑会在阶段 4 从 V1 分别迁入。"""
from abc import ABC, abstractmethod

class MovieSource(ABC):
    name: str
    @abstractmethod
    def scan_series(self, url: str): ...
    @abstractmethod
    def fetch_movie(self, url: str): ...
    @abstractmethod
    def fetch_magnets(self, url: str): ...
