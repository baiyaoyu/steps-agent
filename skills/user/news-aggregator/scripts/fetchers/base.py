#!/usr/bin/env python3
"""
新闻爬取器基类

提供公共方法和抽象接口
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin


# 热点关键词（用于识别重要新闻）
HOTSPOT_KEYWORDS = [
    '制裁', '访华', '访美', '会晤', '峰会', '会议', '政策', '突破', '首次',
    '重磅', '突发', '紧急', '重大', '历史性', '里程碑', '宣布', '决定',
    '改革', '签署', '发布', '出台', '暴跌', '暴涨', '危机', '冲突',
    '战争', '和平', '协议', '条约', '选举', '当选', '辞职', '任命',
    '科技', '突破', '发现', '发明', '创新', 'AI', '芯片', '航天',
    '经济', '金融', '股市', '贸易', '关税', 'GDP',
]


class BaseFetcher(ABC):
    """新闻爬取器基类"""
    
    # 子类需要设置的属性
    SOURCE_NAME: str = ""  # 来源名称
    SOURCE_ID: str = ""    # 来源标识
    
    def __init__(self, hours: int = 24):
        """
        初始化爬取器
        
        Args:
            hours: 获取最近N小时的新闻
        """
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })
        self.timeout = 20
        self.hours = hours
        self.cutoff_time = datetime.now() - timedelta(hours=hours)
    
    def parse_time(self, time_str: str) -> Tuple[str, datetime]:
        """解析时间字符串，返回(原始显示字符串, datetime对象)"""
        if not time_str:
            dt = datetime.now()
            return '刚刚', dt
        
        time_str = time_str.strip()
        original_str = time_str
        now = datetime.now()
        
        # 处理相对时间
        if '小时前' in time_str:
            match = re.search(r'(\d+)', time_str)
            hours = int(match.group(1)) if match else 1
            dt = now - timedelta(hours=hours)
            return original_str, dt
        elif '分钟前' in time_str:
            match = re.search(r'(\d+)', time_str)
            minutes = int(match.group(1)) if match else 1
            dt = now - timedelta(minutes=minutes)
            return original_str, dt
        elif '刚刚' in time_str:
            return '刚刚', now
        elif '今天' in time_str:
            return original_str, now
        elif '昨天' in time_str:
            dt = now - timedelta(days=1)
            return original_str, dt
        elif '天前' in time_str:
            match = re.search(r'(\d+)', time_str)
            days = int(match.group(1)) if match else 1
            dt = now - timedelta(days=days)
            return original_str, dt
        
        # 处理 "X月X日" 格式
        month_day_match = re.match(r'^(\d{1,2})月(\d{1,2})日$', time_str)
        if month_day_match:
            month, day = int(month_day_match.group(1)), int(month_day_match.group(2))
            try:
                dt = now.replace(month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
            except ValueError:
                dt = now
            return original_str, dt
        
        # 处理 "X月X日 HH:MM" 格式
        month_day_time_match = re.match(r'^(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})$', time_str)
        if month_day_time_match:
            month, day, hour, minute = map(int, month_day_time_match.groups())
            try:
                dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                dt = now
            return original_str, dt
        
        # 处理纯时间格式 "HH:MM"
        time_only_match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
        if time_only_match:
            hour, minute = int(time_only_match.group(1)), int(time_only_match.group(2))
            dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            return original_str, dt
        
        # 处理 "MM-DD HH:MM" 格式
        date_time_match = re.match(r'^(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$', time_str)
        if date_time_match:
            month, day, hour, minute = map(int, date_time_match.groups())
            dt = now.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            return original_str, dt
        
        # 处理 "MM-DD" 格式
        date_match = re.match(r'^(\d{1,2})-(\d{1,2})$', time_str)
        if date_match:
            month, day = map(int, date_match.groups())
            dt = now.replace(month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
            return original_str, dt
        
        # 其他格式尝试解析
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y年%m月%d日 %H:%M',
            '%Y年%m月%d日',
            '%Y/%m/%d %H:%M',
            '%Y/%m/%d',
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(time_str, fmt)
                return original_str, dt
            except ValueError:
                continue
        
        return original_str, now
    
    def is_hotspot(self, title: str) -> bool:
        """判断是否为热点新闻"""
        for keyword in HOTSPOT_KEYWORDS:
            if keyword in title:
                return True
        return False
    
    def get_hotspot_score(self, title: str, source: str, pub_time: datetime) -> int:
        """计算热点分数"""
        score = 0
        
        for keyword in HOTSPOT_KEYWORDS:
            if keyword in title:
                score += 10
        
        # 来源权重
        if '联合早报' in source:
            score += 5
        elif '财新' in source:
            score += 4
        elif '36氪' in source:
            score += 3
        
        # 时间权重
        hours_ago = (datetime.now() - pub_time).total_seconds() / 3600
        if hours_ago < 6:
            score += 15
        elif hours_ago < 12:
            score += 10
        elif hours_ago < 24:
            score += 5
        
        return score
    
    def fetch_cover_image(self, url: str, source: str = '') -> str:
        """从新闻详情页爬取封面图片
        
        Args:
            url: 新闻详情页URL
            source: 新闻来源（用于选择合适的提取策略）
            
        Returns:
            封面图片URL，失败返回空字符串
        """
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'lxml')
            html = response.text
            
            # 澎湃新闻：从 JSON 数据中提取
            if 'thepaper.cn' in url or source == '澎湃新闻':
                script = soup.find('script', type='application/json')
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        content_detail = data.get('props', {}).get('pageProps', {}).get('detailData', {}).get('contentDetail', {})
                        
                        pic = content_detail.get('pic', '')
                        if pic and 'imgpai.thepaper.cn' in pic:
                            return pic
                        
                        share_pic = content_detail.get('sharePic', '')
                        if share_pic and 'imgpai.thepaper.cn' in share_pic:
                            return share_pic
                    except:
                        pass
            
            # 联合早报：从 HTML 中提取 s3fs-public 图片
            if 'zaobao.com' in url or source == '联合早报':
                pattern = r'https://dss\d\.zbstatic\d\.com/s3fs-public/styles/article_large[^\"\'<>]+'
                matches = re.findall(pattern, html)
                if matches:
                    img_url = matches[0].split('&quot;')[0].split('"')[0]
                    return img_url
                
                pattern2 = r'https://dss\d\.zbstatic\d\.com/s3fs-public/[^\"\'<>]+\.(?:jpg|jpeg|png|webp)'
                matches2 = re.findall(pattern2, html, re.I)
                if matches2:
                    return matches2[0]
            
            # 财新：从 og:image 或图片标签提取
            if 'caixin.com' in url or source == '财新':
                # 尝试 og:image
                og_image = soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    return og_image['content']
                # 尝试文章内图片
                article = soup.find('div', class_='article-content') or soup.find('div', class_='text')
                if article:
                    img = article.find('img')
                    if img and img.get('src'):
                        return img['src']
            
            # 36氪：从 og:image 提取
            if '36kr.com' in url or source == '36氪':
                og_image = soup.find('meta', property='og:image')
                if og_image and og_image.get('content'):
                    return og_image['content']
            
            # 通用方法1: og:image meta标签
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                content = og_image['content']
                if 'pic-default' not in content and 'static/media' not in content:
                    return content
            
            # 通用方法2: twitter:image meta标签
            twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                content = twitter_image['content']
                if 'pic-default' not in content and 'static/media' not in content:
                    return content
            
            # 通用方法3: 文章内第一个大图
            article = soup.find('article') or soup.find('div', class_=re.compile(r'(article|content|story)'))
            if article:
                img = article.find('img')
                if img and img.get('src'):
                    src = img['src']
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif not src.startswith('http'):
                        src = urljoin(url, src)
                    if 'static/media' not in src and 'pic-default' not in src:
                        return src
            
        except Exception as e:
            pass
        
        return ''
    
    @abstractmethod
    def fetch(self) -> List[Dict]:
        """
        爬取新闻列表
        
        子类必须实现此方法
        
        Returns:
            新闻列表，每条新闻包含：
            - title: 标题
            - time: 时间（原始显示字符串）
            - time_obj: datetime 对象
            - source: 来源名称
            - url: 链接
            - is_hotspot: 是否热点
            - is_free: 是否免费（可选，财新专用）
            - cover_image: 封面图片URL（可选）
            - summary: 摘要（可选）
        """
        pass
