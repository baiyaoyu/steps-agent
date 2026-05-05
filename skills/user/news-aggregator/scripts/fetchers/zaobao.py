#!/usr/bin/env python3
"""
联合早报爬取器

爬取联合早报中国版面新闻
支持代理配置（通过 .env 文件配置 ZAOBAO_PROXY）
"""

import os
from typing import List, Dict
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import re

# 自动加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .base import BaseFetcher


class ZaobaoFetcher(BaseFetcher):
    """联合早报爬取器"""
    
    SOURCE_NAME = "联合早报"
    SOURCE_ID = "zaobao"
    
    def __init__(self, hours: int = 24):
        super().__init__(hours)
        self.url = 'https://www.zaobao.com/news/china'
        
        # 配置代理（从 .env 或环境变量读取）
        proxy = os.environ.get('ZAOBAO_PROXY', '').strip()
        if proxy:
            # 支持格式: http://127.0.0.1:7890 或 socks5://127.0.0.1:1080
            self.session.proxies = {
                'http': proxy,
                'https': proxy
            }
    
    def fetch(self) -> List[Dict]:
        """爬取联合早报中国版面"""
        news = []
        
        try:
            response = self.session.get(self.url, timeout=self.timeout)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'lxml')
            
            seen_urls = set()
            
            # 查找所有 article 标签
            articles = soup.find_all('article')
            
            for article in articles:
                try:
                    # 查找链接
                    link = article.find('a', href=re.compile(r'/news/china/story'))
                    if not link:
                        continue
                    
                    href = link.get('href', '')
                    
                    # 查找标题 (line-clamp 类的 div)
                    title_div = article.find('div', class_=re.compile(r'line-clamp'))
                    if not title_div:
                        continue
                    
                    title = title_div.get_text(strip=True)
                    if len(title) < 5:
                        continue
                    
                    # 查找时间 (text-xs 类的 div 下的 span)
                    time_div = article.find('div', class_='text-xs')
                    time_str = ''
                    if time_div:
                        time_span = time_div.find('span')
                        if time_span:
                            time_str = time_span.get_text(strip=True)
                    
                    full_url = urljoin('https://www.zaobao.com', href)
                    
                    if full_url in seen_urls:
                        continue
                    seen_urls.add(full_url)
                    
                    time_formatted, pub_time = self.parse_time(time_str)
                    
                    if pub_time < self.cutoff_time:
                        continue
                    
                    news.append({
                        'title': title,
                        'time': time_formatted,
                        'time_obj': pub_time,
                        'source': self.SOURCE_NAME,
                        'url': full_url,
                        'is_hotspot': self.is_hotspot(title)
                    })
                except Exception:
                    continue
            
        except Exception as e:
            pass
        
        return news
