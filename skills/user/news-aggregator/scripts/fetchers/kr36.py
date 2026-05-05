#!/usr/bin/env python3
"""
36氪爬取器

爬取36氪快讯和文章
支持"8点1氪"专栏单独提取和内容解析
"""

from typing import List, Dict, Tuple, Optional
import requests
import re
from datetime import datetime
import json
import time

from .base import BaseFetcher


class Kr36Fetcher(BaseFetcher):
    """36氪爬取器"""
    
    SOURCE_NAME = "36氪"
    SOURCE_ID = "kr36"
    
    # 专栏标识（标题中包含这些关键词即为专栏文章）
    DIGEST_PATTERNS = ['8点1氪', '夜读']
    
    # 8点1氪专栏作者ID
    DIGEST_AUTHOR_ID = '5652071'
    
    def __init__(self, hours: int = 24):
        super().__init__(hours)
        self.url = 'https://36kr.com/'
        self.newsflashes_url = 'https://36kr.com/newsflashes'
        # 存储"8点1氪"专栏
        self.daily_digest = None
    
    def _is_digest_article(self, title: str) -> bool:
        """识别是否为专栏文章"""
        if not title:
            return False
        return any(pattern in title for pattern in self.DIGEST_PATTERNS)
    
    def fetch(self) -> List[Dict]:
        """爬取36氪快讯
        
        自动识别并分离"8点1氪"等专栏文章
        """
        news = []
        
        try:
            # 从快讯页面解析
            newsflashes = self._fetch_newsflashes()
            if newsflashes:
                news.extend(newsflashes)
            
            # 从专栏作者获取最新"8点1氪"
            self._fetch_daily_digest()
            
        except Exception as e:
            pass
        
        return news
    
    def _fetch_daily_digest(self) -> None:
        """从专栏作者API获取最新的"8点1氪"文章
        
        使用作者文章列表API获取最新专栏文章
        """
        try:
            api_url = 'https://gateway.36kr.com/api/mis/me/article'
            timestamp = int(time.time() * 1000)
            
            data = {
                'partner_id': 'web',
                'timestamp': timestamp,
                'param': {
                    'userId': self.DIGEST_AUTHOR_ID,
                    'pageEvent': 0,
                    'pageSize': 5,  # 只取前5篇
                    'pageCallback': '',
                    'siteId': 1,
                    'platformId': 2
                }
            }
            
            headers = {
                'Content-Type': 'application/json',
            }
            
            response = self.session.post(api_url, json=data, headers=headers, timeout=self.timeout)
            
            if response.status_code != 200:
                return
            
            result = response.json()
            if result.get('code') != 0:
                return
            
            items = result.get('data', {}).get('itemList', [])
            if not items:
                return
            
            # 遍历文章列表，找最新的"8点1氪"
            for item in items:
                template = item.get('templateMaterial', {})
                title = template.get('widgetTitle', '')
                
                if not self._is_digest_article(title):
                    continue
                
                item_id = template.get('itemId', '')
                publish_time = template.get('publishTime', 0)
                
                if not item_id:
                    continue
                
                time_formatted, pub_time = self._parse_kr36_time(str(publish_time))
                
                # 检查时间范围
                if pub_time < self.cutoff_time:
                    continue
                
                article_url = f'https://36kr.com/p/{item_id}'
                
                # 获取封面图片
                cover_image = ''
                widget_image = template.get('widgetImage', '')
                if isinstance(widget_image, str) and widget_image:
                    cover_image = widget_image
                
                # 解析文章内容
                sections = self._parse_digest_content(article_url)
                
                self.daily_digest = {
                    'column_type': self._get_column_type(title),
                    'title': title,
                    'time': time_formatted,
                    'time_obj': pub_time,
                    'source': self.SOURCE_NAME,
                    'url': article_url,
                    'cover_image': cover_image,
                    'sections': sections
                }
                return
            
        except Exception:
            pass
    
    def _parse_digest_content(self, article_url: str) -> List[Dict]:
        """解析专栏文章内容结构
        
        返回格式：
        [
            {
                'section_title': 'TOP 3大新闻',
                'items': [
                    {'title': '甲骨文裁员3万人', 'content': '具体内容...'},
                    ...
                ]
            },
            ...
        ]
        """
        sections = []
        
        try:
            from bs4 import BeautifulSoup
            
            response = self.session.get(article_url, timeout=self.timeout)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'lxml')
            
            # 找到文章内容容器
            h2 = soup.find('h2')
            if not h2:
                return sections
            
            parent = h2.parent
            if not parent:
                return sections
            
            current_section = None
            current_item = None
            
            for child in parent.children:
                if not hasattr(child, 'name') or not child.name:
                    continue
                
                if child.name == 'h2':
                    # 新 section
                    if current_section:
                        if current_item:
                            current_section['items'].append(current_item)
                            current_item = None
                        sections.append(current_section)
                    
                    current_section = {
                        'section_title': child.get_text(strip=True),
                        'items': []
                    }
                    current_item = None
                    
                elif child.name == 'p' and current_section:
                    text = child.get_text(strip=True)
                    if not text:
                        continue
                    
                    strong = child.find('strong')
                    if strong:
                        # 新条目标题
                        if current_item:
                            current_section['items'].append(current_item)
                        
                        strong_text = strong.get_text(strip=True)
                        # 获取 strong 后面的内容（去掉标题后的文本）
                        remaining = text.replace(strong_text, '', 1).strip()
                        
                        current_item = {
                            'title': strong_text,
                            'content': remaining
                        }
                    elif current_item:
                        # 继续追加内容
                        current_item['content'] += ' ' + text
            
            # 保存最后一个 section 和 item
            if current_section:
                if current_item:
                    current_section['items'].append(current_item)
                sections.append(current_section)
            
            # 过滤掉空 section 或"今日热点导览"（只有标题列表，无内容）
            sections = [s for s in sections if s['items'] and s['section_title'] != '今日热点导览']
            
        except Exception:
            pass
        
        return sections
    
    def _get_column_type(self, title: str) -> str:
        """根据标题识别专栏类型"""
        if '8点1氪' in title:
            return '8点1氪'
        elif '夜读' in title:
            return '夜读'
        return '专栏'
    
    def _fetch_newsflashes(self) -> List[Dict]:
        """从快讯页面获取新闻"""
        news = []
        
        try:
            from bs4 import BeautifulSoup
            
            response = self.session.get(self.newsflashes_url, timeout=self.timeout)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'lxml')
            
            # 36氪使用 React 渲染，数据在 script 标签中
            scripts = soup.find_all('script')
            
            for script in scripts:
                if not script.string:
                    continue
                
                # 查找包含快讯数据的 script
                if 'window.initialState' in script.string or 'newsflashList' in script.string:
                    try:
                        data = self._extract_json_from_script(script.string)
                        if data:
                            news.extend(self._parse_newsflash_data(data))
                    except Exception:
                        continue
            
            # 如果没有从 script 中解析到，尝试从 HTML 解析
            if not news:
                news.extend(self._parse_newsflash_html(soup))
            
        except Exception:
            pass
        
        return news
    
    def _extract_json_from_script(self, script_content: str) -> dict:
        """从 script 标签内容中提取 JSON 数据"""
        try:
            # 方式1: window.initialState={...}
            match = re.search(r'window\.initialState\s*=\s*(\{.*\})\s*$', script_content, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            
            # 方式2: 匹配包含 newsflashList 的 JSON
            match = re.search(r'({[\s\S]*"newsflashList"[\s\S]*})', script_content)
            if match:
                return json.loads(match.group(1))
            
        except (json.JSONDecodeError, AttributeError):
            pass
        
        return {}
    
    def _parse_newsflash_data(self, data: dict) -> List[Dict]:
        """解析快讯 JSON 数据"""
        news = []
        
        try:
            items = []
            
            # 结构1: 新版数据结构 newsflashCatalogData.data.newsflashList.data.itemList
            catalog_data = data.get('newsflashCatalogData', {})
            if catalog_data:
                newsflash_list = catalog_data.get('data', {}).get('newsflashList', {}).get('data', {})
                items = newsflash_list.get('itemList', [])
                
                for item in items:
                    try:
                        template = item.get('templateMaterial', {})
                        if not template:
                            continue
                        
                        title = template.get('widgetTitle', '')
                        if not title or len(title) < 5:
                            continue
                        
                        item_id = template.get('itemId', '')
                        url = f"https://36kr.com/newsflashes/{item_id}" if item_id else ''
                        if not url:
                            continue
                        
                        # 时间戳（毫秒）
                        publish_time = template.get('publishTime', 0)
                        time_formatted, pub_time = self._parse_kr36_time(str(publish_time))
                        
                        if pub_time < self.cutoff_time:
                            continue
                        
                        # 封面图片
                        widget_image = template.get('widgetImage', {})
                        cover_image = widget_image.get('url', '') if isinstance(widget_image, dict) else ''
                        
                        news.append({
                            'title': title,
                            'time': time_formatted,
                            'time_obj': pub_time,
                            'source': self.SOURCE_NAME,
                            'url': url,
                            'is_hotspot': self.is_hotspot(title),
                            'cover_image': cover_image
                        })
                    except Exception:
                        continue
                
                if news:
                    return news
            
            # 结构2: 旧版数据结构 data.newsflashList.newsflashList
            if 'newsflashList' in data:
                if isinstance(data['newsflashList'], dict):
                    items = data['newsflashList'].get('newsflashList', [])
                else:
                    items = data['newsflashList']
            
            # 结构3: data.props.pageProps.newsflashList
            if not items and 'props' in data:
                props = data.get('props', {})
                page_props = props.get('pageProps', {})
                items = page_props.get('newsflashList', [])
            
            for item in items:
                try:
                    title = item.get('title', '') or item.get('name', '')
                    if not title:
                        continue
                    
                    # 有些快讯没有标题，使用内容的前50字
                    if not title and item.get('description'):
                        title = item.get('description', '')[:50] + '...'
                    
                    if len(title) < 5:
                        continue
                    
                    url = item.get('news_url', '') or item.get('url', '')
                    if not url:
                        # 构建快讯链接
                        item_id = item.get('id', '')
                        if item_id:
                            url = f"https://36kr.com/newsflashes/{item_id}"
                    
                    if not url:
                        continue
                    
                    # 解析时间
                    time_str = item.get('published_at', '') or item.get('createTime', '') or item.get('publish_time', '')
                    time_formatted, pub_time = self._parse_kr36_time(time_str)
                    
                    if pub_time < self.cutoff_time:
                        continue
                    
                    # 获取封面图片
                    cover_image = item.get('cover', '') or item.get('image', '')
                    
                    # 获取摘要
                    summary = item.get('description', '') or item.get('content', '')
                    if summary and len(summary) > 100:
                        summary = summary[:100] + '...'
                    
                    news.append({
                        'title': title,
                        'time': time_formatted,
                        'time_obj': pub_time,
                        'source': self.SOURCE_NAME,
                        'url': url,
                        'is_hotspot': self.is_hotspot(title),
                        'cover_image': cover_image,
                        'summary': summary
                    })
                except Exception:
                    continue
            
        except Exception:
            pass
        
        return news
    
    def _parse_newsflash_html(self, soup) -> List[Dict]:
        """从 HTML 中解析快讯（备用方案）"""
        news = []
        
        try:
            # 查找快讯列表项
            items = soup.find_all('div', class_=re.compile(r'newsflash-item|item'))
            
            for item in items:
                try:
                    # 获取标题
                    title_elem = item.find('a', class_=re.compile(r'title')) or item.find('h3')
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text(strip=True)
                    url = title_elem.get('href', '')
                    
                    if not title or len(title) < 5:
                        continue
                    
                    if url and not url.startswith('http'):
                        url = 'https://36kr.com' + url
                    
                    # 获取时间
                    time_elem = item.find('span', class_=re.compile(r'time|date'))
                    time_str = time_elem.get_text(strip=True) if time_elem else ''
                    
                    time_formatted, pub_time = self._parse_kr36_time(time_str)
                    
                    if pub_time < self.cutoff_time:
                        continue
                    
                    news.append({
                        'title': title,
                        'time': time_formatted,
                        'time_obj': pub_time,
                        'source': self.SOURCE_NAME,
                        'url': url,
                        'is_hotspot': self.is_hotspot(title)
                    })
                except Exception:
                    continue
            
        except Exception:
            pass
        
        return news
    
    def _parse_kr36_time(self, time_str: str):
        """解析36氪时间格式"""
        if not time_str:
            return '刚刚', datetime.now()
        
        time_str = str(time_str).strip()
        now = datetime.now()
        
        # 时间戳格式
        if time_str.isdigit():
            try:
                timestamp = int(time_str)
                # 判断是秒还是毫秒
                if timestamp > 10000000000:
                    timestamp = timestamp / 1000
                dt = datetime.fromtimestamp(timestamp)
                return dt.strftime('%m月%d日 %H:%M'), dt
            except (ValueError, OSError):
                pass
        
        # 格式: "2026-04-01 09:40:47"
        match = re.match(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})', time_str)
        if match:
            try:
                dt = datetime(*map(int, match.groups()))
                return dt.strftime('%m月%d日 %H:%M'), dt
            except ValueError:
                pass
        
        # 格式: "04-01 09:40"
        match = re.match(r'(\d{2})-(\d{2})\s+(\d{2}):(\d{2})', time_str)
        if match:
            month, day, hour, minute = map(int, match.groups())
            try:
                dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
                return dt.strftime('%m月%d日 %H:%M'), dt
            except ValueError:
                pass
        
        # 使用基类方法
        return self.parse_time(time_str)
