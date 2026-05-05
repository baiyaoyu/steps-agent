#!/usr/bin/env python3
"""
财新网爬取器

爬取财新网首页新闻列表
支持识别付费文章
"""

from typing import List, Dict
from urllib.parse import urljoin
import requests
import re
from datetime import datetime

from .base import BaseFetcher


class CaixinFetcher(BaseFetcher):
    """财新网爬取器"""
    
    SOURCE_NAME = "财新"
    SOURCE_ID = "caixin"
    
    def __init__(self, hours: int = 24):
        super().__init__(hours)
        self.url = 'https://www.caixin.com/'
        # 财新有多个频道，这里爬取首页的综合新闻
        self.api_url = 'https://gateway.caixin.com/api/extapi/homeInterface.jsp'
    
    def fetch(self) -> List[Dict]:
        """爬取财新网首页"""
        news = []
        
        try:
            # 方法1: 尝试从 API 获取数据
            api_news = self._fetch_from_api()
            if api_news:
                news.extend(api_news)
            
            # 方法2: 从首页 HTML 解析（作为补充）
            html_news = self._fetch_from_html()
            if html_news:
                # 合并去重
                seen_urls = {n['url'] for n in news}
                for item in html_news:
                    if item['url'] not in seen_urls:
                        news.append(item)
                        seen_urls.add(item['url'])
            
        except Exception as e:
            pass
        
        return news
    
    def _fetch_from_api(self) -> List[Dict]:
        """从财新 API 获取新闻列表"""
        news = []
        
        try:
            # 调用财新首页接口
            params = {
                'subject': '100589266',  # 首页新闻
                'start': 1,
                'count': 20,
                'picdim': '_266_177',
                'type': 2,
                'callback': '?'
            }
            
            response = self.session.get(self.api_url, params=params, timeout=self.timeout)
            
            # JSONP 响应，提取 JSON 部分
            text = response.text
            if text.startswith('?'):
                text = text[1:]
            if text.startswith('(') and text.endswith(')'):
                text = text[1:-1]
            
            import json
            data = json.loads(text)
            
            if 'datas' not in data:
                return news
            
            for item in data['datas']:
                try:
                    title = item.get('desc', '')
                    if not title or len(title) < 5:
                        continue
                    
                    url = item.get('link', '')
                    if not url:
                        continue
                    
                    # 解析时间
                    time_str = item.get('time', '')
                    time_formatted, pub_time = self._parse_caixin_time(time_str)
                    
                    if pub_time < self.cutoff_time:
                        continue
                    
                    # 判断是否免费
                    # attr=5 表示收费文章
                    attr = item.get('attr', 0)
                    is_free = attr != 5
                    
                    # 判断限时免费
                    free_time = item.get('freeTime')
                    free_duration = item.get('freeDuration', '')
                    
                    # 获取封面图片
                    cover_image = ''
                    pict = item.get('pict', {})
                    if pict and 'imgs' in pict and pict['imgs']:
                        cover_image = pict['imgs'][0].get('url', '')
                    
                    news.append({
                        'title': title,
                        'time': time_formatted,
                        'time_obj': pub_time,
                        'source': self.SOURCE_NAME,
                        'url': url,
                        'is_hotspot': self.is_hotspot(title),
                        'is_free': is_free,
                        'free_duration': free_duration if free_time else None,
                        'cover_image': cover_image
                    })
                except Exception:
                    continue
            
        except Exception:
            pass
        
        return news
    
    def _fetch_from_html(self) -> List[Dict]:
        """从首页 HTML 解析新闻"""
        news = []
        
        try:
            from bs4 import BeautifulSoup
            
            response = self.session.get(self.url, timeout=self.timeout)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'lxml')
            
            seen_urls = set()
            
            # 解析头条区域
            toutiao = soup.find('div', class_='toutiao_box')
            if toutiao:
                for dl in toutiao.find_all('dl'):
                    try:
                        link = dl.find('a')
                        if not link:
                            continue
                        
                        url = link.get('href', '')
                        title = link.get_text(strip=True)
                        
                        if not title or len(title) < 5:
                            continue
                        
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        
                        # 查找时间
                        time_str = ''
                        dd = dl.find('dd')
                        if dd:
                            span = dd.find('span')
                            if span:
                                time_str = span.get_text(strip=True)
                        
                        time_formatted, pub_time = self._parse_caixin_time(time_str)
                        
                        # 如果时间解析失败，尝试从 URL 提取日期
                        if time_formatted == '刚刚' and url:
                            url_date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', url)
                            if url_date_match:
                                year, month, day = map(int, url_date_match.groups())
                                try:
                                    from datetime import datetime
                                    dt = datetime.now().replace(year=year, month=month, day=day)
                                    time_formatted = f'{month:02d}月{day:02d}日'
                                    pub_time = dt
                                except ValueError:
                                    pass
                        
                        if pub_time < self.cutoff_time:
                            continue
                        
                        # 检查是否有收费图标
                        is_free = True
                        icon_key = dl.find('span', class_='icon_key')
                        if icon_key:
                            is_free = False
                        
                        news.append({
                            'title': title,
                            'time': time_formatted,
                            'time_obj': pub_time,
                            'source': self.SOURCE_NAME,
                            'url': url,
                            'is_hotspot': self.is_hotspot(title),
                            'is_free': is_free
                        })
                    except Exception:
                        continue
            
        except Exception:
            pass
        
        return news
    
    def _parse_caixin_time(self, time_str: str):
        """解析财新时间格式"""
        if not time_str:
            return '刚刚', datetime.now()
        
        time_str = time_str.strip()
        now = datetime.now()
        
        # 财新格式1: "04月01日 07:52"（纯时间格式）
        match = re.match(r'^(\d{2})月(\d{2})日\s+(\d{2}):(\d{2})$', time_str)
        if match:
            month, day, hour, minute = map(int, match.groups())
            try:
                dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                return time_str, dt
            except ValueError:
                pass
        
        # 财新格式2: "文｜财新 xxx 04月02日 07:00" 或 "文｜财新 xxx 发自香港 04月02日 07:00"
        # 或 "文｜财新 xxx 04月02日 10:00 | 经济"（带分类标签）
        match = re.search(r'(\d{2})月(\d{2})日\s+(\d{2}):(\d{2})', time_str)
        if match:
            month, day, hour, minute = map(int, match.groups())
            try:
                dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                return f'{month:02d}月{day:02d}日 {hour:02d}:{minute:02d}', dt
            except ValueError:
                pass
        
        # 使用基类的解析方法
        return self.parse_time(time_str)
