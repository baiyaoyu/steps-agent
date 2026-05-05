#!/usr/bin/env python3
"""
澎湃新闻爬取器

爬取澎湃新闻首页轮播图和推荐区域
"""

from typing import List, Dict
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import re

from .base import BaseFetcher


class PengpaiFetcher(BaseFetcher):
    """澎湃新闻爬取器"""
    
    SOURCE_NAME = "澎湃新闻"
    SOURCE_ID = "pengpai"
    
    def __init__(self, hours: int = 24):
        super().__init__(hours)
        self.url = 'https://www.thepaper.cn/'
    
    def fetch(self) -> List[Dict]:
        """爬取澎湃新闻首页"""
        news = []
        
        try:
            response = self.session.get(self.url, timeout=self.timeout)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'lxml')
            
            seen_urls = set()
            
            # 方法1: 从轮播图项提取
            carousel_items = soup.find_all('div', class_=re.compile(r'carousel_img'))
            for item in carousel_items:
                try:
                    link = item.find('a', href=re.compile(r'newsDetail'))
                    if not link:
                        continue
                    
                    href = link.get('href', '')
                    
                    # 查找时间元素
                    time_elem = item.find(class_=re.compile(r'time', re.I))
                    time_str = time_elem.get_text(strip=True) if time_elem else ''
                    
                    # 优先从图片 alt 属性获取标题
                    title = ''
                    img = link.find('img')
                    if img:
                        title = img.get('alt', '') or img.get('title', '')
                    
                    if not title:
                        title = link.get_text(strip=True)
                    
                    if not title or len(title) < 5:
                        continue
                    
                    full_url = urljoin('https://www.thepaper.cn', href)
                    
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
            
            # 方法2: 从推荐区域提取
            recommend = soup.find(class_=re.compile(r'recommend'))
            if recommend:
                cards = recommend.find_all('div', class_=re.compile(r'cardcontent'))
                for card in cards:
                    try:
                        link = card.find('a', href=re.compile(r'newsDetail_forward'))
                        if not link:
                            continue
                        
                        href = link.get('href', '')
                        if 'commTag' in href:
                            continue
                        
                        # 获取标题
                        title = ''
                        h2 = link.find('h2')
                        if h2:
                            title = h2.get_text(strip=True)
                        if not title:
                            img = link.find('img')
                            if img:
                                title = img.get('alt', '') or img.get('title', '')
                        
                        if not title or len(title) < 5:
                            continue
                        
                        # 获取时间
                        time_str = ''
                        des = card.find(class_=re.compile(r'cardcontentdes'))
                        if des:
                            spans = des.find_all('span')
                            for span in spans:
                                text = span.get_text(strip=True)
                                if re.match(r'^(\d+(小时|分钟|天)前|刚刚)$', text):
                                    time_str = text
                                    break
                        
                        full_url = urljoin('https://www.thepaper.cn', href)
                        
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
