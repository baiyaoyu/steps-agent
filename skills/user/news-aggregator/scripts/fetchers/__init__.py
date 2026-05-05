#!/usr/bin/env python3
"""
新闻爬取器模块
"""

from .base import BaseFetcher
from .zaobao import ZaobaoFetcher
from .pengpai import PengpaiFetcher
from .caixin import CaixinFetcher
from .kr36 import Kr36Fetcher

__all__ = [
    'BaseFetcher',
    'ZaobaoFetcher',
    'PengpaiFetcher',
    'CaixinFetcher',
    'Kr36Fetcher',
]

# 来源映射
FETCHER_MAP = {
    'zaobao': ZaobaoFetcher,
    'pengpai': PengpaiFetcher,
    'caixin': CaixinFetcher,
    'kr36': Kr36Fetcher,
}
