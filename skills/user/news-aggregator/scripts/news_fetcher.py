#!/usr/bin/env python3
"""
新闻聚合爬取脚本
从多个新闻源获取最新新闻，生成时间线数据

支持来源：
- 联合早报（中国版面）
- 澎湃新闻
- 财新网
- 36氪

使用方式：
    python news_fetcher.py --hours 24 --source all --limit 20 --cover crawl
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Tuple

from fetchers import ZaobaoFetcher, PengpaiFetcher, CaixinFetcher, Kr36Fetcher, FETCHER_MAP


def build_timeline(news_list: List[Dict]) -> Dict:
    """构建时间线数据结构"""
    timeline = defaultdict(list)
    
    for item in news_list:
        date = item['time_obj'].strftime('%Y-%m-%d')
        timeline_item = {
            'time': item['time'],
            'title': item['title'],
            'source': item['source'],
            'url': item['url']
        }
        # 添加可选字段
        if 'is_free' in item:
            timeline_item['is_free'] = item['is_free']
        if 'free_duration' in item and item['free_duration']:
            timeline_item['free_duration'] = item['free_duration']
        
        timeline[date].append(timeline_item)
    
    return dict(sorted(timeline.items(), key=lambda x: x[0], reverse=True))


def balance_sources(news_list: List[Dict], limit: int) -> List[Dict]:
    """均衡多个来源的新闻数量"""
    if limit <= 0:
        return news_list
    
    # 按来源分组
    by_source = defaultdict(list)
    for item in news_list:
        by_source[item['source']].append(item)
    
    sources = list(by_source.keys())
    if not sources:
        return []
    
    # 如果只有一个来源，直接截取
    if len(sources) == 1:
        return news_list[:limit]
    
    # 按时间排序每个来源的新闻
    for source in sources:
        by_source[source].sort(key=lambda x: x['time_obj'], reverse=True)
    
    # 均衡分配：交替从各来源取新闻
    result = []
    source_indices = {s: 0 for s in sources}
    
    while len(result) < limit:
        added = False
        for source in sources:
            if len(result) >= limit:
                break
            idx = source_indices[source]
            if idx < len(by_source[source]):
                result.append(by_source[source][idx])
                source_indices[source] += 1
                added = True
        
        if not added:
            break
    
    # 最终按时间排序
    result.sort(key=lambda x: x['time_obj'], reverse=True)
    return result


def select_hotspot(news_list: List[Dict], cover_mode: str = 'crawl') -> Dict:
    """选择最热点的新闻用于封面生成
    
    优先选择：
    1. 有封面图片的新闻（已提供或可爬取）
    2. 热点分数最高的新闻
    """
    if not news_list:
        return {}
    
    # 使用具体爬取器的热点评分方法
    from fetchers.zaobao import ZaobaoFetcher
    
    fetcher = ZaobaoFetcher(hours=24)
    
    # 分类：有封面图片的 vs 无封面图片的
    with_cover = []  # 已有封面图片（财新、36氪文章等）
    without_cover = []  # 无封面图片（36氪快讯等）
    
    for item in news_list:
        # 判断是否有封面：已提供封面 或 是可爬取封面的文章类型
        has_cover = False
        
        if item.get('cover_image'):
            # 已有封面图片
            has_cover = True
        elif item.get('source') == '36氪':
            # 36氪：只有文章(/p/)有封面，快讯(/newsflashes/)无封面
            url = item.get('url', '')
            has_cover = '/p/' in url
        else:
            # 其他来源默认可以爬取封面
            has_cover = True
        
        score = 0
        if item.get('is_hotspot'):
            score = fetcher.get_hotspot_score(
                item['title'], item['source'], item['time_obj']
            )
        
        if has_cover:
            with_cover.append((score, item))
        else:
            without_cover.append((score, item))
    
    # 优先从有封面的新闻中选择热点
    with_cover.sort(key=lambda x: x[0], reverse=True)
    without_cover.sort(key=lambda x: x[0], reverse=True)
    
    if with_cover:
        best = with_cover[0][1]
        best_score = with_cover[0][0]
    elif without_cover:
        # 退而求其次，选择无封面的热点（此时封面需要AI生成）
        best = without_cover[0][1]
        best_score = without_cover[0][0]
    else:
        best = news_list[0]
        best_score = 0
    
    result = {
        'title': best['title'],
        'time': best['time'],
        'source': best['source'],
        'url': best['url'],
        'score': best_score
    }
    
    # 如果已有封面图片（财新、36氪文章可能直接提供）
    if 'cover_image' in best and best['cover_image']:
        result['cover_image'] = best['cover_image']
        result['cover_mode'] = 'provided'
    # 如果是爬取模式，尝试获取封面图片URL
    elif cover_mode == 'crawl':
        # 检查是否是36氪快讯（无封面）
        if best.get('source') == '36氪' and '/newsflashes/' in best.get('url', ''):
            result['cover_image'] = ''
            result['cover_mode'] = 'crawl_failed'
            result['note'] = '快讯无封面图片'
        else:
            print(f"正在爬取封面图片: {best['title'][:30]}...", file=sys.stderr)
            cover_url = fetcher.fetch_cover_image(best['url'], best.get('source', ''))
            if cover_url:
                result['cover_image'] = cover_url
                result['cover_mode'] = 'crawled'
            else:
                result['cover_image'] = ''
                result['cover_mode'] = 'crawl_failed'
    else:
        result['cover_mode'] = 'ai_generate'
    
    return result


def fetch_news(source: str, hours: int, kr36_8d1k: bool = False) -> Tuple[List[Dict], Dict]:
    """根据来源获取新闻
    
    Args:
        source: 新闻来源（'all' 或具体来源名称）
        hours: 时间范围（小时）
        kr36_8d1k: 是否只获取36氪"8点1氪"专栏
    
    Returns:
        Tuple[List[Dict], Dict]: (新闻列表, 专栏数据)
        专栏数据包含 'daily_digest' 键（8点1氪）
    """
    all_news = []
    special_columns = {}
    
    # 如果只获取8点1氪，只爬取36氪
    if kr36_8d1k:
        sources_to_fetch = ['kr36']
    elif source == 'all':
        # 获取所有来源
        sources_to_fetch = ['zaobao', 'pengpai', 'caixin', 'kr36']
    else:
        # 获取指定来源
        sources_to_fetch = [s.strip() for s in source.split(',')]
    
    for s in sources_to_fetch:
        if s not in FETCHER_MAP:
            continue
            
        try:
            fetcher_class = FETCHER_MAP[s]
            print(f"正在爬取{fetcher_class.SOURCE_NAME}...", file=sys.stderr)
            fetcher = fetcher_class(hours=hours)
            news = fetcher.fetch()
            
            # 获取"8点1氪"专栏
            if hasattr(fetcher, 'daily_digest') and fetcher.daily_digest:
                special_columns['daily_digest'] = fetcher.daily_digest
                print(f"获取\"{fetcher.daily_digest.get('column_type', '专栏')}\"专栏", file=sys.stderr)
            
            # 如果只获取8点1氪，不添加普通新闻
            if not kr36_8d1k:
                print(f"{fetcher_class.SOURCE_NAME}获取 {len(news)} 条", file=sys.stderr)
                all_news.extend(news)
                    
        except Exception as e:
            print(f"{s}爬取失败: {str(e)}", file=sys.stderr)
    
    return all_news, special_columns


def main():
    parser = argparse.ArgumentParser(description='新闻聚合爬取')
    parser.add_argument('--hours', type=int, default=24, 
                        choices=[4, 8, 12, 24, 48, 72], help='时间范围（小时）')
    parser.add_argument('--source', type=str, default='all',
                        help='新闻来源：all(全部)、zaobao(联合早报)、pengpai(澎湃新闻)、caixin(财新)、kr36(36氪)，可逗号分隔多个')
    parser.add_argument('--limit', type=int, default=0,
                        help='最大新闻条数，0表示不限制（默认0）')
    parser.add_argument('--cover', type=str, default='crawl',
                        choices=['crawl', 'ai'],
                        help='封面模式：crawl(爬取原图，默认)、ai(AI生成)')
    parser.add_argument('--8d1k', dest='kr36_8d1k', action='store_true',
                        help='只获取36氪"8点1氪"专栏内容，不获取普通新闻')
    args = parser.parse_args()
    
    # 获取新闻
    all_news, special_columns = fetch_news(args.source, args.hours, args.kr36_8d1k)
    
    # 如果只获取8点1氪，直接输出专栏数据
    if args.kr36_8d1k:
        result = {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'hours': args.hours,
            'kr36_8d1k': True
        }
        
        if 'daily_digest' in special_columns:
            digest = special_columns['daily_digest']
            # 移除 time_obj（用于内部排序）
            output_digest = {k: v for k, v in digest.items() if k != 'time_obj'}
            result['daily_digest'] = output_digest
        else:
            result['daily_digest'] = None
            result['message'] = '未找到"8点1氪"专栏文章'
        
        print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
        return
    
    # 去重（根据标题前20字）
    seen_titles = set()
    unique_news = []
    for item in all_news:
        title_key = item['title'][:20]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_news.append(item)
    
    # 按时间降序排序
    unique_news.sort(key=lambda x: x['time_obj'], reverse=True)
    
    # 应用限制（多来源时均衡分配）
    if args.limit > 0:
        unique_news = balance_sources(unique_news, args.limit)
    
    # 构建输出
    news_output = []
    for item in unique_news:
        output_item = {
            'title': item['title'],
            'time': item['time'],
            'source': item['source'],
            'url': item['url'],
            'is_hotspot': item['is_hotspot']
        }
        # 添加可选字段
        if 'is_free' in item:
            output_item['is_free'] = item['is_free']
        if 'free_duration' in item and item['free_duration']:
            output_item['free_duration'] = item['free_duration']
        if 'summary' in item:
            output_item['summary'] = item['summary']
        
        news_output.append(output_item)
    
    # 统计各来源数量
    source_counts = defaultdict(int)
    for n in unique_news:
        source_counts[n['source']] += 1
    
    # 生成时间
    generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    result = {
        'generated_at': generated_at,
        'hours': args.hours,
        'source': args.source,
        'limit': args.limit,
        'cover_mode': args.cover,
        'total': len(unique_news),
        'news': news_output,
        'timeline': build_timeline(unique_news),
        'hotspot': select_hotspot(unique_news, args.cover),
        'source_counts': dict(source_counts)
    }
    
    # 添加"8点1氪"专栏（如果有）
    if 'daily_digest' in special_columns:
        digest = special_columns['daily_digest']
        # 移除 time_obj
        output_digest = {k: v for k, v in digest.items() if k != 'time_obj'}
        result['daily_digest'] = output_digest
    
    print(f"总计获取 {len(unique_news)} 条新闻", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
